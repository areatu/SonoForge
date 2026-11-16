"""The repeat-selection dialog shows accepted/excluded beats and shared stats (issue 559)."""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QTreeWidget

from echo_personal_tool.domain.models.doppler import DopplerMeasurementDTO, DopplerPeakMarker
from echo_personal_tool.presentation.doppler_repeats import DopplerRepeatsDialog

pytestmark = pytest.mark.gui


def _dto() -> DopplerMeasurementDTO:
    return DopplerMeasurementDTO(
        peaks=(
            DopplerPeakMarker("TR Vmax", 0.0, 300.0, measurement_id="a"),
            DopplerPeakMarker("TR Vmax", 10.0, 900.0, measurement_id="b", accepted=False),
            DopplerPeakMarker("TR Vmax", 20.0, 320.0, measurement_id="c"),
        ),
        intervals=(),
        traces=(),
    )


def test_dialog_lists_every_beat_and_the_selected_statistics(qtbot) -> None:
    dialog = DopplerRepeatsDialog(dto=_dto(), apply_dto=lambda _dto: None)
    qtbot.addWidget(dialog)
    tree = dialog.findChild(QTreeWidget, "dopplerRepeatsTree")
    assert tree is not None

    assert dialog.rows == 3
    assert tree.topLevelItemCount() == 1
    assert tree.topLevelItem(0).childCount() == 3
    assert "n=2" in tree.topLevelItem(0).text(2)
    stats = dialog.statistics()[0]
    assert stats.accepted == (300.0, 320.0)
    assert stats.excluded == (900.0,)
    assert stats.n == 2
    assert stats.sd == pytest.approx(14.142, abs=0.001)

    method = dialog.findChild(QLabel, "dopplerRepeatsMethod")
    assert method is not None and "3" in method.text()

    tree.topLevelItem(0).child(1).setCheckState(0, Qt.CheckState.Checked)
    assert dialog.statistics()[0].accepted == (300.0, 900.0, 320.0)
    assert dialog.statistics()[0].n == 3
    assert "n=3" in tree.topLevelItem(0).text(2)


def test_apply_returns_the_same_markers_with_explicit_flags(qtbot) -> None:
    applied: list[DopplerMeasurementDTO] = []
    dialog = DopplerRepeatsDialog(dto=_dto(), apply_dto=applied.append)
    qtbot.addWidget(dialog)

    dialog.apply_selection()

    assert dialog.result() == dialog.DialogCode.Accepted
    assert len(applied) == 1
    assert [marker.accepted for marker in applied[0].peaks] == [True, False, True]
    assert [marker.measurement_id for marker in applied[0].peaks] == ["a", "b", "c"]
