"""The «D/S маркеры» button (2026-10-27 UI list, item 6)."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from echo_personal_tool.domain.services.cardiac_study import is_cardiac_cine
from echo_personal_tool.presentation.tool_buttons import buttons as tool_buttons


def test_ds_markers_sits_immediately_before_calibration() -> None:
    ids = [spec.id for spec in tool_buttons.TOOL_BUTTONS]
    assert ids[ids.index("ds_markers") + 1] == "calibration"
    spec = tool_buttons.tool_button_spec("ds_markers")
    assert spec is not None
    assert spec.ref == "cine_phase_markers"
    assert spec.icon == "activity_cine_phases"


def test_ds_markers_tooltip_explains_the_manual_request() -> None:
    spec = tool_buttons.tool_button_spec("ds_markers")
    assert spec is not None
    text = tool_buttons.tooltip(spec, "ru")
    assert "D/S" in text or "диастол" in text.lower()
    assert tool_buttons.caption(spec, "ru")


def test_ds_markers_icon_is_bundled() -> None:
    from echo_personal_tool.presentation.tool_buttons.base import load_tool_icon

    app = QApplication.instance() or QApplication([])
    assert app is not None
    assert not load_tool_icon("activity_cine_phases").isNull()


def test_allow_unlabeled_keeps_the_2d_and_non_cardiac_gates() -> None:
    assert not is_cardiac_cine()
    assert is_cardiac_cine(allow_unlabeled=True)
    # An explicit request never turns a spectral/M-mode time axis into a cine.
    assert not is_cardiac_cine(clip_mode="doppler", body_part="HEART", allow_unlabeled=True)
    assert not is_cardiac_cine(clip_mode="m_mode", body_part="HEART", allow_unlabeled=True)
    # Nor does it override a *local* non-cardiac organ label.
    assert not is_cardiac_cine(series_description="Thyroid", allow_unlabeled=True)
    assert is_cardiac_cine(study_description="ЭхоКГ")
    assert is_cardiac_cine(study_description="ЭхоКГ", allow_unlabeled=True)


@pytest.mark.gui
def test_the_button_latches_for_the_current_clip_only(qtbot) -> None:

    from echo_personal_tool.application.app_controller import AppController
    from echo_personal_tool.domain.models.metadata import InstanceMetadata
    from echo_personal_tool.infrastructure.user_preferences import UserPreferences
    from echo_personal_tool.presentation.main_window import MainWindow

    window = MainWindow(controller=AppController(), user_preferences=UserPreferences(tool_panel_v2=True))
    qtbot.addWidget(window)
    manager = window._controller.state_manager
    manager._instance = InstanceMetadata(
        sop_instance_uid="1.2.3.ds",
        series_uid="1.2.3",
        modality="US",
        number_of_frames=30,
        pixel_spacing=(0.5, 0.5),
        frame_time_ms=33.3,
        series_description="Cine (MP4)",
        path=None,
    )
    manager._total_frames = 30
    manager._frame_time_ms = 33.3
    assert window._latched_tool_buttons() == ()
    assert "cine_phase_markers" in window._tool_button_handlers()

    window._toggle_phase_markers()
    assert "1.2.3.ds" in window._phase_markers_forced()
    assert window._latched_tool_buttons() == ("ds_markers",)
    row = window._tool_row
    if row is not None:
        assert row.button("ds_markers").isChecked()

    window._toggle_phase_markers()
    assert "1.2.3.ds" not in window._phase_markers_forced()
    assert window._latched_tool_buttons() == ()
    if row is not None:
        assert not row.button("ds_markers").isChecked()


@pytest.mark.gui
def test_the_button_refuses_a_non_2d_clip(qtbot) -> None:
    from echo_personal_tool.application.app_controller import AppController
    from echo_personal_tool.domain.models.metadata import InstanceMetadata
    from echo_personal_tool.infrastructure.user_preferences import UserPreferences
    from echo_personal_tool.presentation.main_window import MainWindow

    window = MainWindow(controller=AppController(), user_preferences=UserPreferences(tool_panel_v2=True))
    qtbot.addWidget(window)
    instance = InstanceMetadata(
        sop_instance_uid="1.2.3.pw",
        series_uid="1.2.3",
        modality="US",
        number_of_frames=30,
        pixel_spacing=None,
        frame_time_ms=10.0,
        series_description="PW Doppler",
        path=None,
        clip_mode="doppler",
    )
    window._controller.state_manager._instance = instance
    window._toggle_phase_markers()
    assert window._phase_markers_forced() == set()
