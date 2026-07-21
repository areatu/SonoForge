"""Tests for MeasurementWorksheet."""


from __future__ import annotations

from echo_personal_tool.domain.models import Contour
from echo_personal_tool.domain.models.measurements import (
    DopplerResults,
    MeasurementSnapshot,
)
from echo_personal_tool.presentation.measurement_action import MeasurementAction
from echo_personal_tool.presentation.measurement_worksheet import MeasurementWorksheet

pytestmark = pytest.mark.gui


def test_worksheet_emits_action_on_click(qtbot) -> None:
    worksheet = MeasurementWorksheet()
    qtbot.addWidget(worksheet)
    item = worksheet._rows_by_key["lv_a4c_ed"]
    with qtbot.waitSignal(worksheet.action_requested, timeout=1000) as blocker:
        worksheet._tree.setCurrentItem(item)
        worksheet._on_item_clicked(item, 0)
    action, view, phase = blocker.args
    assert action == MeasurementAction.MANUAL_SIMPSON
    assert view == "A4C"
    assert phase == "ED"


def test_worksheet_updates_lvm_and_diastology(qtbot) -> None:
    worksheet = MeasurementWorksheet()
    qtbot.addWidget(worksheet)
    snapshot = MeasurementSnapshot(
        lvm_g=180.5,
        diastology_grade="Normal",
        doppler=DopplerResults(e_over_e_prime=7.0, e_over_e_prime_sept=6.5),
    )
    worksheet.update_from_snapshot(snapshot, ())
    assert "180" in worksheet._rows_by_key["lvm"].text(1)
    assert worksheet._rows_by_key["diast_grade"].text(1) == "Normal"


def test_es_prompt_blinks_worksheet_row(qtbot) -> None:
    worksheet = MeasurementWorksheet()
    qtbot.addWidget(worksheet)
    worksheet.start_es_prompt("manual", "4C")
    assert worksheet._blink_timer.isActive()
    worksheet.stop_es_prompt()
    assert not worksheet._blink_timer.isActive()


def test_worksheet_marks_contour_rows_done(qtbot) -> None:
    worksheet = MeasurementWorksheet()
    qtbot.addWidget(worksheet)
    contour = Contour(
        phase="ED",
        view="A4C",
        chamber="LV",
        mitral_annulus=((0.0, 0.0), (10.0, 0.0)),
        points=[(0.0, 0.0), (5.0, 5.0), (10.0, 0.0)],
        source="manual",
    )
    worksheet.update_from_snapshot(None, (contour,))
    assert worksheet._rows_by_key["lv_a4c_ed"].background(0) is not None
