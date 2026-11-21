"""Unit tests for the view-recognition corpus helpers (issue #639, step 1).

Covers the pure domain layer of corpus assembly: deterministic view-
stratified train/val splitting, manifest assembly, corpus validation, and
the summary report — all without Qt, IO, or pydicom.
"""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.models.view_recognition import (
    KNOWN_VIEWS,
    UNKNOWN_VIEW,
    ViewRecognitionSample,
)
from echo_personal_tool.domain.services.view_recognition_corpus import (
    build_manifest,
    iter_samples_in_split,
    split_corpus,
    summarize_corpus,
    validate_corpus,
)


def _sample(sample_id: str, view: str, split: str = "train") -> ViewRecognitionSample:
    return ViewRecognitionSample(sample_id, f"/data/{sample_id}.dcm", view, split)


def _corpus(views: list[str]) -> list[ViewRecognitionSample]:
    return [_sample(f"s{i}", view) for i, view in enumerate(views)]


# ── split_corpus ─────────────────────────────────────────────────────


def test_split_corpus_preserves_all_samples() -> None:
    samples = _corpus(["A4C", "A4C", "A4C", "PLAX", "PLAX", "SAX"])
    train, val = split_corpus(samples, val_ratio=0.25, seed=1)
    all_ids = {s.sample_id for s in samples}
    assert {s.sample_id for s in train} | {s.sample_id for s in val} == all_ids
    assert len(train) + len(val) == len(samples)


def test_split_corpus_is_stratified_by_view() -> None:
    samples = _corpus(["A4C"] * 10 + ["PLAX"] * 4)
    train, val = split_corpus(samples, val_ratio=0.2, seed=7)
    # Both classes keep a share of the validation set.
    assert {s.view for s in val} == {"A4C", "PLAX"}


def test_split_corpus_deterministic_for_seed() -> None:
    samples = _corpus(["A4C"] * 8 + ["SAX"] * 5)
    train_a, val_a = split_corpus(samples, val_ratio=0.2, seed=123)
    train_b, val_b = split_corpus(samples, val_ratio=0.2, seed=123)
    assert [s.sample_id for s in train_a] == [s.sample_id for s in train_b]
    assert [s.sample_id for s in val_a] == [s.sample_id for s in val_b]


def test_split_corpus_different_seed_changes_assignment() -> None:
    samples = _corpus(["A4C"] * 20)
    train_a, _ = split_corpus(samples, val_ratio=0.2, seed=1)
    train_b, _ = split_corpus(samples, val_ratio=0.2, seed=2)
    assert {s.sample_id for s in train_a} != {s.sample_id for s in train_b}


def test_split_corpus_zero_ratio_keeps_everything_in_train() -> None:
    samples = _corpus(["A4C", "PLAX", "SAX"])
    train, val = split_corpus(samples, val_ratio=0.0, seed=1)
    assert len(val) == 0
    assert len(train) == len(samples)


def test_split_corpus_single_member_group_goes_to_train() -> None:
    samples = _corpus(["A4C", "A4C", "PLAX"])
    train, val = split_corpus(samples, val_ratio=0.5, seed=1)
    assert all(s.view != "PLAX" for s in val)
    assert [s.view for s in train if s.view == "PLAX"] == ["PLAX"]


def test_split_corpus_invalid_ratio_raises() -> None:
    samples = _corpus(["A4C"])
    with pytest.raises(ValueError, match="val_ratio"):
        split_corpus(samples, val_ratio=1.0, seed=1)


def test_split_corpus_unknown_view_kept_separately() -> None:
    samples = [_sample("u1", UNKNOWN_VIEW), _sample("u2", UNKNOWN_VIEW), _sample("a1", "A4C")]
    train, val = split_corpus(samples, val_ratio=0.5, seed=1)
    unknown_in_val = [s for s in val if s.view == UNKNOWN_VIEW]
    # The unknown group keeps at most one sample in val.
    assert len(unknown_in_val) <= 1
    unknown_in_train = [s for s in train if s.view == UNKNOWN_VIEW]
    assert len(unknown_in_train) + len(unknown_in_val) == 2
    assert {s.sample_id for s in train} | {s.sample_id for s in val} == {"u1", "u2", "a1"}


# ── build_manifest ───────────────────────────────────────────────────


def test_build_manifest_round_trip() -> None:
    samples = _corpus(["A4C", "PLAX"])
    manifest = build_manifest(samples)
    restored = build_manifest(manifest.samples)
    assert manifest.schema_version == restored.schema_version
    assert manifest.class_names == KNOWN_VIEWS
    assert manifest.samples == restored.samples


def test_build_manifest_custom_class_names() -> None:
    samples = _corpus(["A4C"])
    manifest = build_manifest(samples, class_names=("A4C",))
    assert manifest.class_names == ("A4C",)


# ── validate_corpus ──────────────────────────────────────────────────


def test_validate_corpus_accepts_valid_corpus() -> None:
    samples = [_sample("s1", "A4C", "train"), _sample("s2", "PLAX", "val")]
    assert validate_corpus(samples) == []


def test_validate_corpus_reports_empty_fields() -> None:
    empty_id = ViewRecognitionSample("", "/a.dcm", "A4C", "train")
    empty_path = ViewRecognitionSample("s1", "", "A4C", "train")
    empty_view = ViewRecognitionSample("s2", "/b.dcm", "", "train")
    problems = validate_corpus([empty_id, empty_path, empty_view])
    assert any("sample_id" in p for p in problems)
    assert any("source_path" in p for p in problems)
    assert any("view" in p for p in problems)


def test_validate_corpus_flags_unknown_view() -> None:
    problems = validate_corpus([_sample("s1", "NOT_A_VIEW", "train")])
    assert any("NOT_A_VIEW" in p for p in problems)


def test_validate_corpus_accepts_unknown_fallback_view() -> None:
    problems = validate_corpus([_sample("s1", UNKNOWN_VIEW, "train")])
    assert problems == []


def test_validate_corpus_flags_invalid_split() -> None:
    problems = validate_corpus([_sample("s1", "A4C", "bogus")])
    assert any("bogus" in p for p in problems)


def test_validate_corpus_requires_train_split() -> None:
    samples = [_sample("s1", "A4C", "val")]
    problems = validate_corpus(samples)
    assert any("'train'" in p for p in problems)
    assert validate_corpus(samples, require_train=False) == []


def test_validate_corpus_does_not_require_val() -> None:
    samples = [_sample("s1", "A4C", "train")]
    assert validate_corpus(samples) == []


# ── summarize_corpus / iter_samples_in_split ─────────────────────────


def test_summarize_corpus_covers_every_class_and_unknown() -> None:
    samples = [_sample("s1", "A4C", "train"), _sample("s2", UNKNOWN_VIEW, "val")]
    summary = summarize_corpus(samples)
    assert set(summary) == set(KNOWN_VIEWS) | {UNKNOWN_VIEW}
    assert summary["A4C"]["train"] == 1
    assert summary[UNKNOWN_VIEW]["val"] == 1


def test_iter_samples_in_split_filters_in_order() -> None:
    samples = _corpus(["A4C", "PLAX", "SAX"])
    samples[0] = _sample("s0", "A4C", "val")
    val = iter_samples_in_split(samples, "val")
    assert [s.sample_id for s in val] == ["s0"]
    assert [s.sample_id for s in iter_samples_in_split(samples, "train")] == ["s1", "s2"]
