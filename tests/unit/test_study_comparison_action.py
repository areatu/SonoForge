"""The window action behind «Сравнить с предыдущим исследованием…» (562)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from echo_personal_tool.application.study_comparison import ComparisonCandidate
from echo_personal_tool.domain.models.metadata import InstanceMetadata, SeriesMetadata, StudyMetadata
from echo_personal_tool.domain.services.study_comparison import StudyIdentity
from echo_personal_tool.presentation import study_comparison as action


class _Comparison:
    def __init__(self, current: StudyIdentity | None) -> None:
        self._current = current
        self.started: list[tuple[StudyIdentity, object, object]] = []
        self.result = True

    def current_identity(self) -> StudyIdentity | None:
        return self._current

    def start_previous(self, identity, instance, *, measurements=None) -> bool:
        self.started.append((identity, instance, measurements))
        return self.result


class _Tabs:
    def __init__(self, tabs, active="tab-1") -> None:
        self.tabs = tuple(tabs)
        self.active_tab_id = active

    def get(self, tab_id: str):
        return next((tab for tab in self.tabs if tab.tab_id == tab_id), None)


def _instance(uid: str) -> InstanceMetadata:
    return InstanceMetadata(
        sop_instance_uid=uid,
        series_uid="series",
        modality="US",
        number_of_frames=30,
        pixel_spacing=None,
        frame_time_ms=33.3,
        series_description="A4C",
        path=Path("/data/a.dcm"),
        patient_surname="Ivanov",
    )


def _tab(tab_id: str, study_uid: str, date: datetime, *, measured: bool = False):
    instance = _instance(f"sop-{study_uid}")
    study = StudyMetadata(
        study_uid=study_uid,
        study_datetime=date,
        series=(SeriesMetadata("series", study_uid, "US", "A4C", (instance,)),),
    )
    return SimpleNamespace(
        tab_id=tab_id,
        root=f"/{tab_id}",
        studies=[study],
        clinical_memory=SimpleNamespace(studies={study_uid: "stored"} if measured else {}),
    )


def _window(current: StudyIdentity | None, tabs) -> SimpleNamespace:
    return SimpleNamespace(
        _comparison=_Comparison(current),
        _tab_coordinator=SimpleNamespace(tabs=_Tabs(tabs)),
    )


def _current() -> StudyIdentity:
    return StudyIdentity(study_uid="current", study_datetime=datetime(2026, 3, 1), patient_surname="Ivanov")


def test_the_action_lists_only_open_tabs_and_opens_the_chosen_pair(monkeypatch) -> None:
    tab = _tab("tab-2", "previous", datetime(2026, 1, 1), measured=True)
    window = _window(_current(), [tab])
    chosen = ComparisonCandidate(
        identity=_identity_from(tab),
        instance=tab.studies[0].series[0].instances[0],
        study=tab.studies[0],
        tab_id="tab-2",
        tab_number=1,
    )
    monkeypatch.setattr(action, "ask_comparison_candidate", lambda *args, **kwargs: chosen)
    monkeypatch.setattr(action.QMessageBox, "information", lambda *args, **kwargs: None)

    assert action.open_previous_study_comparison(window) is True

    identity, instance, measurements = window._comparison.started[0]
    assert identity.study_uid == "previous"
    assert instance.sop_instance_uid == "sop-previous"
    assert measurements == "stored"


def _identity_from(tab) -> StudyIdentity:
    study = tab.studies[0]
    return StudyIdentity(
        study_uid=study.study_uid,
        study_datetime=study.study_datetime,
        patient_surname="Ivanov",
        source=tab.root,
        tab_id=tab.tab_id,
        tab_number=1,
        clip_count=1,
    )


def test_without_a_current_study_the_action_explains_itself(monkeypatch) -> None:
    messages: list[str] = []
    monkeypatch.setattr(action.QMessageBox, "information", lambda *args: messages.append(args[2]))
    window = _window(None, [])

    assert action.open_previous_study_comparison(window) is False
    assert "Сначала откройте текущее исследование" in messages[0]


def test_without_another_open_study_the_action_explains_itself(monkeypatch) -> None:
    messages: list[str] = []
    monkeypatch.setattr(action.QMessageBox, "information", lambda *args: messages.append(args[2]))
    window = _window(_current(), [_tab("tab-1", "current", datetime(2026, 3, 1))])

    assert action.open_previous_study_comparison(window) is False
    assert "Нет другого открытого исследования" in messages[0]
    assert window._comparison.started == []


def test_cancelling_the_picker_does_not_start_anything(monkeypatch) -> None:
    window = _window(_current(), [_tab("tab-2", "previous", datetime(2026, 1, 1))])
    monkeypatch.setattr(action, "ask_comparison_candidate", lambda *args, **kwargs: None)

    assert action.open_previous_study_comparison(window) is False
    assert window._comparison.started == []


def test_the_coordinator_can_still_refuse_the_pair(monkeypatch) -> None:
    tab = _tab("tab-2", "previous", datetime(2026, 1, 1))
    window = _window(_current(), [tab])
    chosen = ComparisonCandidate(
        identity=_identity_from(tab),
        instance=tab.studies[0].series[0].instances[0],
        study=tab.studies[0],
        tab_id="tab-2",
        tab_number=1,
    )
    monkeypatch.setattr(action, "ask_comparison_candidate", lambda *args, **kwargs: chosen)
    window._comparison.result = False

    assert action.open_previous_study_comparison(window) is False
    assert len(window._comparison.started) == 1, "the explicit choice reached the coordinator exactly once"
