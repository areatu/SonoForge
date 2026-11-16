"""GUI tests of the previous-study picker (issue 562)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

pytestmark = pytest.mark.gui

from echo_personal_tool.application.study_comparison import ComparisonCandidate
from echo_personal_tool.domain.models.metadata import InstanceMetadata, SeriesMetadata, StudyMetadata
from echo_personal_tool.domain.services.study_comparison import (
    PatientMatch,
    StudyIdentity,
    StudyOrder,
)
from echo_personal_tool.presentation.study_comparison_dialog import StudyComparisonDialog, ask_comparison_candidate


def _identity(uid: str, date: datetime, surname: str, *, source: str = "/data") -> StudyIdentity:
    return StudyIdentity(
        study_uid=uid,
        study_datetime=date,
        patient_surname=surname,
        modality="US",
        source=source,
        tab_id="tab-2",
        tab_number=2,
        clip_count=2,
    )


def _candidate(uid: str, date: datetime, surname: str, *, source: str = "/data") -> ComparisonCandidate:
    instance = InstanceMetadata(
        sop_instance_uid=f"sop-{uid}",
        series_uid="series",
        modality="US",
        number_of_frames=30,
        pixel_spacing=None,
        frame_time_ms=33.3,
        series_description="A4C",
        path=Path("/data/a.dcm"),
        patient_surname=surname,
    )
    study = StudyMetadata(
        study_uid=uid,
        study_datetime=date,
        series=(SeriesMetadata("series", uid, "US", "A4C", (instance,)),),
    )
    return ComparisonCandidate(
        identity=_identity(uid, date, surname, source=source),
        instance=instance,
        study=study,
        tab_id="tab-2",
        tab_number=2,
    )


def _labels(dialog, name: str):
    from PySide6.QtWidgets import QLabel

    return [label for label in dialog.findChildren(QLabel) if label.objectName() == name]


def test_the_picker_shows_dates_patient_and_source(qapp) -> None:
    from PySide6.QtWidgets import QTableWidget

    current = _identity("current", datetime(2026, 3, 1), "Ivanov", source="/current")
    dialog = StudyComparisonDialog(
        current=current,
        candidates=(
            _candidate("older", datetime(2026, 1, 1), "Ivanov", source="/previous"),
            _candidate("newer", datetime(2026, 4, 1), "Petrov", source="/next"),
        ),
    )

    table = dialog.findChild(QTableWidget, "comparisonCandidates")
    assert table.rowCount() == 2
    assert table.item(0, 0).text() == "01.01.2026"
    assert table.item(0, 1).text() == "Ivanov"
    assert table.item(0, 3).text() == "/previous"
    assert [label.text() for label in _labels(dialog, "comparisonCurrent")] == [
        "Текущее исследование: 01.03.2026 · пациент Ivanov · UID …current"
    ]
    assert dialog.selected_candidate().identity.study_uid == "older"
    selected = dialog.identity()
    assert selected is not None
    assert selected.patient_match is PatientMatch.SAME
    assert selected.order is StudyOrder.PREVIOUS
    assert "Пациент совпадает" in _labels(dialog, "comparisonHint")[0].text()
    dialog.deleteLater()


def test_a_proven_different_patient_is_called_out(qapp) -> None:
    current = _identity("current", datetime(2026, 3, 1), "Ivanov")
    dialog = StudyComparisonDialog(current=current, candidates=(_candidate("other", datetime(2026, 1, 1), "Petrov"),))

    hint = _labels(dialog, "comparisonHint")[0].text()
    assert "Пациенты различаются" in hint
    assert "Ivanov" in hint and "Petrov" in hint
    dialog.deleteLater()


def test_an_empty_name_is_unverified_not_same(qapp) -> None:
    current = _identity("current", datetime(2026, 3, 1), "")
    dialog = StudyComparisonDialog(current=current, candidates=(_candidate("other", datetime(2026, 1, 1), "Petrov"),))

    assert "не подтверждена" in _labels(dialog, "comparisonHint")[0].text()
    dialog.deleteLater()


def test_no_open_study_disables_the_action(qapp) -> None:
    from PySide6.QtWidgets import QDialogButtonBox, QTableWidget

    current = _identity("current", datetime(2026, 3, 1), "Ivanov")
    dialog = StudyComparisonDialog(current=current, candidates=())

    assert dialog.findChild(QTableWidget, "comparisonCandidates").rowCount() == 0
    assert "Нет другого открытого исследования" in _labels(dialog, "comparisonHint")[0].text()
    ok = dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok)
    assert ok.isEnabled() is False
    assert dialog.selected_candidate() is None
    assert ask_comparison_candidate(dialog, current=current, candidates=()) is None
    dialog.deleteLater()
