"""Behavioural tests for the pure viewer measurement helpers (spec 474).

These functions were extracted from ``ViewerWidget`` as module-level helpers
so the viewer class stays under its size ceiling.  They touch no viewer
state — only contour identity and measurement-catalog formatting — so they
can be tested without a Qt widget.
"""

from __future__ import annotations

from echo_personal_tool.domain.models import Contour
from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
from echo_personal_tool.domain.services.nomenclature import catalog_label
from echo_personal_tool.infrastructure.i18n import set_language
from echo_personal_tool.presentation.viewer_measurement_helpers import (
    derived_volume_lines,
    with_measurement_identity,
)


def _contour(**overrides) -> Contour:
    defaults = dict(
        phase="",
        view="A4C",
        chamber="LV",
        points=[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)],
        measurement_id="",
    )
    defaults.update(overrides)
    return Contour(**defaults)


# ── with_measurement_identity ──────────────────────────────────────


def test_with_measurement_identity_assigns_id_when_empty() -> None:
    contour = _contour()
    assert contour.measurement_id == ""
    result = with_measurement_identity(contour)
    assert result.measurement_id != ""
    assert len(result.measurement_id) == 16


def test_with_measurement_identity_preserves_existing_id() -> None:
    contour = _contour(measurement_id="existing-id-1234")
    result = with_measurement_identity(contour)
    assert result.measurement_id == "existing-id-1234"


def test_with_measurement_identity_is_idempotent() -> None:
    contour = _contour()
    once = with_measurement_identity(contour)
    twice = with_measurement_identity(once)
    assert twice.measurement_id == once.measurement_id


# ── derived_volume_lines ──────────────────────────────────────────
#
# Label discipline: the emitted lines speak the *active* locale (the
# suite-wide ``_ru_locale`` fixture pins Russian before every test), so
# assertions resolve the catalog label through ``catalog_label`` instead of
# hard-coding either the EN or the RU string (rule D-11: fully RU or fully EN).


def _mm(label: str, value: float | None) -> LinearMeasurement:
    return LinearMeasurement(
        label=label,
        pixel_length=100.0,
        millimeter_length=value,
    )


def test_derived_volume_lines_bladder_complete_triplet() -> None:
    deduped = {
        "a": _mm("BL-L", 40.0),
        "b": _mm("BL-W", 30.0),
        "c": _mm("BL-D", 20.0),
    }
    lines = derived_volume_lines(deduped)
    assert len(lines) == 1
    assert catalog_label("bladder.volume") in lines[0]
    assert "mL" in lines[0]


def test_derived_volume_lines_bladder_uses_legacy_height_key() -> None:
    deduped = {
        "a": _mm("BL-L", 40.0),
        "b": _mm("BL-W", 30.0),
        "c": _mm("BL-H", 20.0),
    }
    lines = derived_volume_lines(deduped)
    assert len(lines) == 1
    assert catalog_label("bladder.volume") in lines[0]


def test_derived_volume_lines_bladder_incomplete_yields_nothing() -> None:
    deduped = {
        "a": _mm("BL-L", 40.0),
        "b": _mm("BL-W", 30.0),
    }
    assert derived_volume_lines(deduped) == []


def test_derived_volume_lines_bladder_uncalibrated_yields_nothing() -> None:
    deduped = {
        "a": _mm("BL-L", None),
        "b": _mm("BL-W", 30.0),
        "c": _mm("BL-D", 20.0),
    }
    assert derived_volume_lines(deduped) == []


def test_derived_volume_lines_thyroid_both_lobes() -> None:
    deduped = {
        "r1": _mm("TH-R-H", 25.0),
        "r2": _mm("TH-R-W", 20.0),
        "r3": _mm("TH-R-TH", 15.0),
        "l1": _mm("TH-L-H", 24.0),
        "l2": _mm("TH-L-W", 19.0),
        "l3": _mm("TH-L-TH", 14.0),
    }
    lines = derived_volume_lines(deduped)
    assert len(lines) == 3
    labels = [line.split(":")[0] for line in lines]
    assert catalog_label("thyroid.r_volume") in labels
    assert catalog_label("thyroid.l_volume") in labels
    assert catalog_label("thyroid.volume") in labels


def test_derived_volume_lines_thyroid_single_lobe_no_total() -> None:
    deduped = {
        "r1": _mm("TH-R-H", 25.0),
        "r2": _mm("TH-R-W", 20.0),
        "r3": _mm("TH-R-TH", 15.0),
    }
    lines = derived_volume_lines(deduped)
    assert len(lines) == 1
    assert catalog_label("thyroid.r_volume") in lines[0]


def test_derived_volume_lines_organ_volume_triplet() -> None:
    deduped = {
        "a": _mm("ORGAN-VOL-1", 10.0),
        "b": _mm("ORGAN-VOL-2", 8.0),
        "c": _mm("ORGAN-VOL-3", 6.0),
    }
    lines = derived_volume_lines(deduped)
    assert len(lines) == 1
    assert catalog_label("organ.volume") in lines[0]
    assert "mL" in lines[0]


def test_derived_volume_lines_organ_volume_incomplete() -> None:
    deduped = {
        "a": _mm("ORGAN-VOL-1", 10.0),
        "b": _mm("ORGAN-VOL-2", 8.0),
    }
    assert derived_volume_lines(deduped) == []


def test_derived_volume_lines_empty_input() -> None:
    assert derived_volume_lines({}) == []


def test_derived_volume_lines_unrelated_measurements_ignored() -> None:
    deduped = {
        "a": _mm("LV-EDV", 100.0),
        "b": _mm("LV-ESV", 40.0),
    }
    assert derived_volume_lines(deduped) == []


def test_derived_volume_lines_label_follows_active_locale() -> None:
    """The overlay line label tracks the selected language (rule D-11)."""
    deduped = {
        "a": _mm("BL-L", 40.0),
        "b": _mm("BL-W", 30.0),
        "c": _mm("BL-D", 20.0),
    }
    for lang in ("ru", "en"):
        set_language(lang)
        lines = derived_volume_lines(deduped)
        assert len(lines) == 1
        assert lines[0].startswith(catalog_label("bladder.volume") + ":")
        assert "mL" in lines[0]
    set_language("ru")
