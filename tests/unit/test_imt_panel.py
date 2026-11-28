"""Compact view builder keeps technical fields collapsed and explicit actions wired."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from echo_personal_tool.presentation.imt_panel import build_imt_panel

pytestmark = pytest.mark.gui


def test_panel_builder_collapses_details_and_wires_explicit_actions(qtbot):
    panel = QWidget()
    qtbot.addWidget(panel)
    calls = []
    for name in (
        "start_selection",
        "set_boundary_editing",
        "accept_result",
        "reject",
        "restore_dicom_scale",
        "propose",
        "load",
        "revalidate",
        "rotate_selection",
        "reposition",
    ):
        setattr(panel, name, lambda *args, key=name: calls.append((key, args)))
    panel.panel_widget = panel
    panel.run = lambda callback: callback()
    build_imt_panel(panel)
    panel.show()
    assert panel.details.isHidden() and not panel.more.isChecked()
    assert not panel.accept_button.isEnabled() and not panel.angle.isEnabled()
    qtbot.mouseClick(panel.more, Qt.MouseButton.LeftButton)
    assert panel.details.isVisible()
    qtbot.mouseClick(panel.more, Qt.MouseButton.LeftButton)
    assert panel.details.isHidden()
    panel.accept_button.setEnabled(True)
    qtbot.mouseClick(panel.accept_button, Qt.MouseButton.LeftButton)
    assert ("accept_result", ()) in calls
    panel.angle.setEnabled(True)
    panel.angle.setValue(-12.5)
    assert ("rotate_selection", (-12.5,)) in calls
