"""Tests for the JSON view-decision store (#639 step 4 persistence)."""

from __future__ import annotations

import json
from pathlib import Path

from echo_personal_tool.domain.models.view_recognition import (
    UNKNOWN_VIEW,
    ViewDecision,
    ViewDecisionSource,
)
from echo_personal_tool.infrastructure.view_decision_store import JsonViewDecisionStore


def _decision(view: str = "A4C", source: ViewDecisionSource = ViewDecisionSource.MANUAL) -> ViewDecision:
    return ViewDecision(
        study_uid="study-1",
        series_uid="series-1",
        view=view,
        source=source,
        confidence=1.0,
        profile_id="builtin.adult_echo",
    )


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    store = JsonViewDecisionStore(tmp_path)
    assert store.load("study-1", "series-1") is None

    store.save(_decision())
    loaded = store.load("study-1", "series-1")
    assert loaded == _decision()


def test_multiple_series_in_one_study(tmp_path: Path) -> None:
    store = JsonViewDecisionStore(tmp_path)
    store.save(_decision("A4C"))
    store.save(
        ViewDecision(
            study_uid="study-1",
            series_uid="series-2",
            view="PLAX",
            source=ViewDecisionSource.MANUAL,
            confidence=1.0,
            profile_id="builtin.adult_echo",
        )
    )
    assert store.load("study-1", "series-1").view == "A4C"
    assert store.load("study-1", "series-2").view == "PLAX"
    # one file per study
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_missing_directory_and_file_are_not_errors(tmp_path: Path) -> None:
    store = JsonViewDecisionStore(tmp_path / "nested" / "dir")
    assert store.load("study-1", "series-1") is None
    store.save(_decision())
    assert store.load("study-1", "series-1") == _decision()


def test_corrupt_file_degrades_to_empty(tmp_path: Path) -> None:
    store = JsonViewDecisionStore(tmp_path)
    (tmp_path / "study-1.json").write_text("{not json", encoding="utf-8")
    assert store.load("study-1", "series-1") is None


def test_unsafe_symlink_is_refused(tmp_path: Path) -> None:
    store = JsonViewDecisionStore(tmp_path)
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    link = tmp_path / "study-1.json"
    link.symlink_to(target)
    assert store.load("study-1", "series-1") is None


def test_saved_document_shape(tmp_path: Path) -> None:
    store = JsonViewDecisionStore(tmp_path)
    store.save(_decision())
    raw = json.loads((tmp_path / "study-1.json").read_text(encoding="utf-8"))
    assert raw["schema_version"] == 1
    assert raw["decisions"]["series-1"]["view"] == "A4C"
    assert raw["decisions"]["series-1"]["source"] == "manual"


def test_unknown_view_decision_has_no_profile(tmp_path: Path) -> None:
    store = JsonViewDecisionStore(tmp_path)
    decision = ViewDecision(
        study_uid="s",
        series_uid="se",
        view=UNKNOWN_VIEW,
        source=ViewDecisionSource.MANUAL,
        confidence=1.0,
        profile_id=None,
    )
    store.save(decision)
    assert store.load("s", "se") == decision
