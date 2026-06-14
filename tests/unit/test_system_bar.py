"""Tests for SystemBar widget."""

from __future__ import annotations

from echo_personal_tool.presentation.system_bar import SystemBar


def test_system_bar_emits_view_mode(qtbot) -> None:
    bar = SystemBar()
    qtbot.addWidget(bar)
    with qtbot.waitSignal(bar.view_mode_changed, timeout=1000) as blocker:
        bar._btn_doppler.click()
    assert blocker.args == ["doppler"]
    assert bar._btn_doppler.isChecked()
    assert not bar._btn_2d.isChecked()


def test_system_bar_study_context_and_status(qtbot) -> None:
    bar = SystemBar()
    qtbot.addWidget(bar)
    bar.set_study_context("A4C cine", "US")
    bar.set_status_message("Frame loaded")
    assert "A4C" in bar._study_label.text()
    assert bar._modality_label.text() == "US"
    assert "Frame" in bar._status_label.text()
