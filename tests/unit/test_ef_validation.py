"""External EF validation harness (#418): metrics, EchoNet adapter, manifest.

Synthetic numbers only — no dataset, no PHI.  The expected metric values are
hand-computed so a regression cannot redefine "validated".
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from echo_personal_tool.application.ef_validation import (
    DEFAULT_THRESHOLD_EF,
    MANIFEST_FORMAT,
    EFValidationError,
    build_validation_report,
    load_auto_ef_validation_summary,
    load_ef_reference_csv,
    load_validation_summary,
    save_validation_manifest,
)
from echo_personal_tool.domain.validation import metrics

REFERENCE_CSV = (
    "File,EF,ESVID\nA.avi,60,x1\nB.avi,35,x2\nC.avi,50,x3\nD.avi,20,x4\ngarbage.avi,not-a-number,x5\nempty.avi,,x6\n"
)


@pytest.fixture()
def reference_csv(tmp_path: Path) -> Path:
    path = tmp_path / "FileList.csv"
    path.write_text(REFERENCE_CSV, encoding="utf-8")
    return path


@pytest.fixture()
def reference(reference_csv: Path) -> dict[str, float]:
    return load_ef_reference_csv(reference_csv)


# ── pure metrics ─────────────────────────────────────────────────────────────


def test_mae_and_bias_are_hand_computable() -> None:
    assert metrics.mean_absolute_error([60.0, 35.0], [55.0, 40.0]) == pytest.approx(5.0)
    assert metrics.bias([60.0, 35.0], [55.0, 40.0]) == pytest.approx(0.0)
    assert metrics.bias([60.0, 35.0], [50.0, 30.0]) == pytest.approx(-7.5)


def test_bland_altman_limits_use_the_sample_sd() -> None:
    # Differences: -5, +5 → mean 0, sample SD = sqrt(50) ≈ 7.071 → 1.96·SD ≈ 13.86.
    bias_value, low, high = metrics.bland_altman_limits([60.0, 35.0], [55.0, 40.0])
    assert bias_value == pytest.approx(0.0)
    assert low == pytest.approx(-13.859292911256333)
    assert high == pytest.approx(13.859292911256333)


def test_pearson_r_is_one_for_a_linear_line_and_clamped() -> None:
    assert metrics.pearson_r([10.0, 20.0, 30.0], [20.0, 40.0, 60.0]) == pytest.approx(1.0)
    assert metrics.pearson_r([10.0, 20.0, 30.0], [60.0, 40.0, 20.0]) == pytest.approx(-1.0)


def test_degenerate_and_invalid_inputs_fail_closed() -> None:
    with pytest.raises(ValueError) as length:
        metrics.mean_absolute_error([1.0, 2.0], [1.0])
    assert "length_mismatch" in str(length.value)
    with pytest.raises(ValueError) as empty:
        metrics.mean_absolute_error([], [])
    assert "empty_input" in str(empty.value)
    with pytest.raises(ValueError) as finite:
        metrics.mean_absolute_error([1.0, float("nan")], [1.0, 2.0])
    assert "non_finite_input" in str(finite.value)
    with pytest.raises(ValueError) as degenerate:
        metrics.pearson_r([5.0, 5.0, 5.0], [1.0, 2.0, 3.0])
    assert "degenerate_input" in str(degenerate.value)
    with pytest.raises(ValueError):
        metrics.standard_deviation([1.0])


def test_confusion_counts_and_rates_for_reduced_ef_detection() -> None:
    # Condition-positive (EF<40): 35, 20.  Positive calls (pred<40): only 20.
    reference = [60.0, 35.0, 50.0, 20.0]
    predicted = [55.0, 20.0, 50.0, 50.0]
    assert metrics.confusion_counts(reference, predicted, threshold=40.0) == (1, 0, 1, 2)
    sensitivity, specificity = metrics.sensitivity_specificity(reference, predicted, threshold=40.0)
    assert sensitivity == pytest.approx(0.5)
    assert specificity == pytest.approx(1.0)


def test_missing_class_is_reported_as_none_not_zero() -> None:
    sensitivity, specificity = metrics.sensitivity_specificity([50.0, 60.0], [45.0, 65.0], threshold=40.0)
    assert sensitivity is None  # no condition-positive pairs
    assert specificity == pytest.approx(1.0)


# ── EchoNet-Dynamic reference adapter ────────────────────────────────────────


def test_reference_csv_parses_and_skips_malformed_rows(reference: dict[str, float]) -> None:
    assert reference == {"A.avi": 60.0, "B.avi": 35.0, "C.avi": 50.0, "D.avi": 20.0}


def test_reference_csv_with_wrong_columns_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "FileList.csv"
    path.write_text("Video,EjectionFraction\nA.avi,60\n", encoding="utf-8")
    with pytest.raises(EFValidationError) as excinfo:
        load_ef_reference_csv(path)
    assert excinfo.value.code == "reference_columns_missing"


def test_reference_csv_out_of_range_ef_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "FileList.csv"
    path.write_text("File,EF\nA.avi,142\n", encoding="utf-8")
    with pytest.raises(EFValidationError) as excinfo:
        load_ef_reference_csv(path)
    assert excinfo.value.code == "reference_empty"


def test_mapping_survives_extension_and_case_differences(reference: dict[str, float]) -> None:
    from echo_personal_tool.application.ef_validation import _match_reference

    assert _match_reference(reference, "A.avi") == 60.0
    assert _match_reference(reference, "a.AVI") == 60.0
    assert _match_reference(reference, "b") == 35.0
    with pytest.raises(EFValidationError) as excinfo:
        _match_reference(reference, "missing.avi")
    assert excinfo.value.code == "reference_missing"


# ── report building ──────────────────────────────────────────────────────────

MEASURED = {"study-a": 58.0, "study-b": 30.0, "study-c": 47.0, "study-d": 22.0}
MAPPING = {"study-a": "A.avi", "study-b": "B.avi", "study-c": "C.avi", "study-d": "D.avi"}


def test_report_shape_and_research_only_stamp(reference: dict[str, float]) -> None:
    report = build_validation_report(reference, MEASURED, MAPPING)
    assert report["format"] == MANIFEST_FORMAT
    assert report["version"] == 1
    assert report["n"] == 4
    assert report["tool"] == "auto-ef"
    assert report["research_only"] is True
    assert report["threshold_ef"] == DEFAULT_THRESHOLD_EF
    assert isinstance(report["metrics"]["mae"], float)
    assert math.isfinite(report["metrics"]["mae"])


def test_report_values_are_hand_computable(reference: dict[str, float]) -> None:
    report = build_validation_report(reference, MEASURED, MAPPING, threshold=40.0)
    # Differences pred-ref: -2, -5, -3, +2 → MAE 3.0, bias -2.0.
    assert report["metrics"]["mae"] == pytest.approx(3.0)
    assert report["metrics"]["bias"] == pytest.approx(-2.0)
    # Positive pairs: B(35), D(20); calls: B(30) positive, D(22) positive → sens 1.0.
    assert report["metrics"]["sensitivity"] == pytest.approx(1.0)
    # Negative pairs: A(60), C(50); calls: 58, 47 negative → spec 1.0.
    assert report["metrics"]["specificity"] == pytest.approx(1.0)


def test_unmapped_or_missing_pairs_fail_closed(reference: dict[str, float]) -> None:
    with pytest.raises(EFValidationError) as unmapped:
        build_validation_report(reference, {**MEASURED, "study-e": 40.0}, MAPPING)
    assert unmapped.value.code == "mapping_missing"
    with pytest.raises(EFValidationError) as missing:
        build_validation_report(reference, {"study-z": 40.0}, {"study-z": "zzz.avi"})
    assert missing.value.code == "reference_missing"
    with pytest.raises(EFValidationError) as few:
        build_validation_report(reference, {"study-a": 58.0, "study-b": 30.0}, {"study-a": "A.avi", "study-b": "B.avi"})
    assert few.value.code == "insufficient_pairs"
    with pytest.raises(EFValidationError) as invalid:
        build_validation_report(reference, {"study-a": 420.0, "study-b": 30.0, "study-c": 1.0}, MAPPING)
    assert invalid.value.code == "non_numeric_input"


# ── manifest persistence ─────────────────────────────────────────────────────


def test_manifest_round_trip(tmp_path: Path, reference: dict[str, float]) -> None:
    manifest = tmp_path / "auto_ef_manifest.json"
    report = build_validation_report(reference, MEASURED, MAPPING)
    saved = save_validation_manifest(report, path=manifest)
    assert saved == manifest
    loaded = load_validation_summary(path=manifest)
    assert loaded == report
    # The persisted payload is JSON, sorted and aggregate-only.
    on_disk = json.loads(manifest.read_text(encoding="utf-8"))
    assert on_disk["format"] == MANIFEST_FORMAT


def test_missing_manifest_is_none_not_an_error(tmp_path: Path) -> None:
    assert load_validation_summary(path=tmp_path / "absent.json") is None


def test_corrupt_manifest_fails_closed(tmp_path: Path) -> None:
    manifest = tmp_path / "auto_ef_manifest.json"
    manifest.write_text('{"format": "other-vendor-manifest", "n": 1}', encoding="utf-8")
    with pytest.raises(EFValidationError) as excinfo:
        load_validation_summary(path=manifest)
    assert excinfo.value.code == "manifest_format"


def test_facade_loads_the_default_location(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reference: dict[str, float]
) -> None:
    from echo_personal_tool.infrastructure import paths as host_paths

    monkeypatch.setattr(host_paths, "data_dir", lambda: tmp_path)
    assert load_auto_ef_validation_summary() is None
    report = build_validation_report(reference, MEASURED, MAPPING)
    save_validation_manifest(report)  # default path → validation_dir()/auto_ef_manifest.json
    loaded = load_auto_ef_validation_summary()
    assert loaded is not None
    assert loaded["n"] == 4
