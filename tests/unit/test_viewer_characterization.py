"""QH-0 characterization locks for ``ViewerWidget`` (issue #516).

Each test drives the widget through its public API and pins what a clustering
refactor must keep observable. They are intentionally written against the
*current* code, before any extraction: a failure here is a behaviour change, not
a stale expectation. The harness lives in ``viewer_characterization.py``.
"""

from __future__ import annotations

import pytest

from echo_personal_tool.application.localization import tr
from echo_personal_tool.presentation.display_formats import format_fps
from echo_personal_tool.presentation.viewer_widget import ViewerWidget
from tests.unit.viewer_characterization import (
    MEASUREMENT_SIGNALS,
    SignalRecorder,
    contour_snapshot,
    ctrl_wheel_event,
    instance_snapshot,
    make_frame,
    make_instance,
    make_state,
    make_viewer,
    viewer_surface,
)

pytestmark = pytest.mark.gui


def _loaded_viewer(qtbot, *, total: int = 10, frame: int = 0) -> ViewerWidget:
    viewer = make_viewer(qtbot)
    viewer.show_frame(make_frame())
    viewer.set_state(make_state(frame=frame, total=total))
    return viewer


def test_set_state_projects_transport_and_emits_no_frame_signal(qtbot) -> None:
    viewer = _loaded_viewer(qtbot, total=10, frame=2)
    recorder = SignalRecorder(viewer)
    viewer.set_state(make_state(frame=2, total=10, fps=25.0, playing=True))
    surface = viewer_surface(viewer)

    assert surface["timeline"] == (0, 9, 2)
    assert surface["frame_label"] == tr("viewer.frame_counter", current="3", total="10")
    assert surface["fps_label"] == f"FPS: {format_fps(25.0)}"
    assert surface["play_caption"] == tr("viewer.pause")
    assert surface["play_enabled"] is True
    assert recorder.only(()) == []


def test_timeline_emits_one_frame_selected_per_real_change(qtbot) -> None:
    viewer = _loaded_viewer(qtbot, total=10)
    recorder = SignalRecorder(viewer)

    viewer.contract.timeline_slider.setValue(7)
    assert recorder.args_of("frame_selected") == [(7,)]

    recorder.clear()
    viewer.contract.timeline_slider.setValue(7)
    assert recorder.names() == []


def test_play_button_requests_playback_without_mutating_state(qtbot) -> None:
    viewer = _loaded_viewer(qtbot, total=10, frame=3)
    recorder = SignalRecorder(viewer)
    before = viewer_surface(viewer)

    viewer.contract.play_button.click()

    assert recorder.names() == ["play_pause_requested"]
    assert viewer_surface(viewer)["play_caption"] == before["play_caption"] == tr("viewer.play")
    assert viewer.current_state() is not None
    assert viewer.current_state().is_playing is False
    assert viewer.current_state().current_frame_index == 3


def test_zoom_cycle_is_fit_100_200_and_leaves_transport_alone(qtbot) -> None:
    viewer = _loaded_viewer(qtbot, total=10, frame=4)
    before = viewer_surface(viewer)
    assert before["zoom_mode"] == "fit"

    seen = [viewer.zoom_mode]
    for _ in range(3):
        viewer.cycle_zoom_mode()
        seen.append(viewer.zoom_mode)
    assert seen == ["fit", "100%", "200%", "fit"]

    after = viewer_surface(viewer)
    for field in ("timeline", "frame_label", "fps_label", "instance", "overlay"):
        assert after[field] == before[field]

    viewer.set_zoom_mode("bogus")
    assert viewer.zoom_mode == "fit"


def test_viewbox_keeps_pan_and_menu_disabled(qtbot) -> None:
    viewer = make_viewer(qtbot)
    view = viewer.contract.view

    assert view.state["mouseEnabled"] == [False, False]
    assert view.menuEnabled() is False


def test_zoom_around_changes_only_the_factor(qtbot) -> None:
    viewer = _loaded_viewer(qtbot, total=10, frame=4)
    before = instance_snapshot(viewer)

    viewer.set_zoom_mode("100%")
    base = viewer.zoom_factor
    viewer.zoom_around(10.0, 20.0, 1.5)

    assert viewer.zoom_factor == pytest.approx(min(base * 1.5, 8.0))
    after = instance_snapshot(viewer)
    for field in ("instance", "pixels", "sliders", "overlay", "overlay_custom"):
        assert after[field] == before[field]


def test_ctrl_wheel_zooms_and_never_steals_the_frame(qtbot) -> None:
    viewer = _loaded_viewer(qtbot, total=10, frame=4)
    recorder = SignalRecorder(viewer)
    before = instance_snapshot(viewer)

    handled = viewer.contract.handle_wheel(ctrl_wheel_event(120))

    assert handled is True
    assert viewer.zoom_factor > 1.0
    assert recorder.names() == []
    after = instance_snapshot(viewer)
    for field in ("instance", "pixels", "sliders", "overlay"):
        assert after[field] == before[field]


def test_label_picker_is_ui_only_and_dismisses_silently(qtbot) -> None:
    viewer = make_viewer(qtbot)
    picker = viewer.label_picker()
    recorder = SignalRecorder(viewer)
    before = instance_snapshot(viewer)

    picker.open_for(value_text="12 mm", context="2d")
    assert viewer.is_label_picker_visible() is True

    assert viewer.dismiss_label_picker() is True
    assert viewer.is_label_picker_visible() is False
    assert recorder.names() == []
    assert instance_snapshot(viewer) == before


def test_accepting_a_picker_without_a_measurement_target_is_silent(qtbot) -> None:
    viewer = make_viewer(qtbot)
    viewer.label_picker().open_for(value_text="12 mm", context="2d")
    recorder = SignalRecorder(viewer)
    before = instance_snapshot(viewer)

    assert viewer.accept_label_picker() is True
    assert viewer.is_label_picker_visible() is False
    assert recorder.names() == []
    assert instance_snapshot(viewer) == before


def test_hidden_picker_accept_is_a_noop(qtbot) -> None:
    viewer = make_viewer(qtbot)
    recorder = SignalRecorder(viewer)

    assert viewer.accept_label_picker() is False
    assert viewer.dismiss_label_picker() is False
    assert recorder.names() == []


def test_instance_and_frame_switches_dismiss_the_picker(qtbot) -> None:
    first = make_instance(sop_instance_uid="1.2.3.qh0.picker.a")
    second = make_instance(sop_instance_uid="1.2.3.qh0.picker.b")
    viewer = make_viewer(qtbot)
    viewer.set_state(make_state(total=10, instance=first))
    viewer.show_frame(make_frame())

    viewer.label_picker().open_for(value_text="12 mm", context="2d")
    assert viewer.is_label_picker_visible() is True
    viewer.set_state(make_state(frame=1, total=10, instance=first))
    assert viewer.is_label_picker_visible() is False

    viewer.label_picker().open_for(value_text="12 mm", context="2d")
    viewer.set_state(make_state(total=10, instance=second))
    assert viewer.is_label_picker_visible() is False


def test_picker_context_override_is_ui_state_only(qtbot) -> None:
    viewer = make_viewer(qtbot)
    recorder = SignalRecorder(viewer)
    before = instance_snapshot(viewer)
    picker = viewer.label_picker()

    picker.open_for(value_text="VTI", context="2d")
    viewer.set_label_picker_context("doppler")
    assert picker.context() == "doppler"

    viewer.set_label_picker_context(None)
    assert picker.context() == "doppler"  # applied on the next open, not retroactively
    picker.open_for(value_text="VTI", context="2d")
    assert picker.context() == "2d"
    assert recorder.names() == []
    assert instance_snapshot(viewer) == before


def test_display_levels_follow_the_sliders_not_the_document(qtbot) -> None:
    viewer = _loaded_viewer(qtbot, total=10, frame=2)
    contract = viewer.contract
    before_pixels = instance_snapshot(viewer)["pixels"]
    before = instance_snapshot(viewer)
    recorder = SignalRecorder(viewer)

    contract.window_slider.setValue(contract.window_slider.value() + 40)

    assert instance_snapshot(viewer)["pixels"] != before_pixels
    after = instance_snapshot(viewer)
    for field in ("instance", "zoom_mode", "zoom_factor", "overlay"):
        assert after[field] == before[field]
    assert recorder.only(MEASUREMENT_SIGNALS) == []


def test_slider_combinations_change_only_display_pixels(qtbot) -> None:
    viewer = _loaded_viewer(qtbot, total=10, frame=2)
    before = instance_snapshot(viewer)
    recorder = SignalRecorder(viewer)
    contract = viewer.contract

    contract.window_slider.setValue(contract.window_slider.value() + 25)
    contract.level_slider.setValue(contract.level_slider.value() + 10)
    contract.dr_slider.setValue(contract.dr_slider.value() - 10)

    after = instance_snapshot(viewer)
    assert after["pixels"] != before["pixels"]
    for field in ("instance", "zoom_mode", "zoom_factor", "overlay", "overlay_custom"):
        assert after[field] == before[field]
    assert recorder.only(MEASUREMENT_SIGNALS) == []


def test_instance_switch_restores_cached_wl_dr_without_measurement_signals(qtbot) -> None:
    first = make_instance(sop_instance_uid="1.2.3.qh0.a")
    second = make_instance(sop_instance_uid="1.2.3.qh0.b")
    viewer = make_viewer(qtbot)
    viewer.set_state(make_state(total=10, instance=first))
    viewer.show_frame(make_frame())
    contract = viewer.contract

    contract.set_wl_dr_sliders(140, 63, 37)
    viewer.set_state(make_state(total=10, instance=second))
    viewer.show_frame(make_frame(64))
    contract.set_wl_dr_sliders(75, 52, 48)

    recorder = SignalRecorder(viewer)
    viewer.set_state(make_state(total=10, instance=first))

    assert (contract.window_slider.value(), contract.level_slider.value(), contract.dr_slider.value()) == (
        140,
        63,
        37,
    )
    assert recorder.only(MEASUREMENT_SIGNALS) == []


def test_results_overlay_setter_is_silent_and_reset_only_clears_the_custom_flag(qtbot) -> None:
    viewer = _loaded_viewer(qtbot, total=10)
    recorder = SignalRecorder(viewer)

    viewer.set_results_overlay_position(0.25, 0.75)

    assert viewer.results_overlay_position() == pytest.approx((0.25, 0.75))
    assert viewer.results_overlay_custom_position() is True
    assert recorder.names() == []

    viewer.reset_results_overlay_to_default()

    # A hidden label is not repositioned: reset only drops the custom flag, and
    # the stored ratios stay until the next layout pass asks for them.
    assert viewer.results_overlay_custom_position() is False
    assert viewer.results_overlay_position() == pytest.approx((0.25, 0.75))
    assert recorder.names() == []


def test_closed_contour_round_trip_keeps_its_payload(qtbot) -> None:
    viewer = _loaded_viewer(qtbot, total=10, frame=3)
    recorder = SignalRecorder(viewer)

    assert viewer.start_closed_contour(chamber="LA", phase="systole", view="A4C") is True
    for point in ((8.0, 8.0), (40.0, 8.0), (40.0, 40.0), (8.0, 40.0)):
        assert viewer.handle_contour_click(point) is True
    assert viewer.finish_contour() is True

    payloads = recorder.args_of("contour_completed")
    assert len(payloads) == 1
    contour = payloads[0][0]
    assert contour_snapshot(contour) == {
        "chamber": "LA",
        "phase": "systole",
        "view": "A4C",
        "frame_index": 3,
        "points": 4,
    }
    assert "contours_changed" in recorder.names()

    assert viewer.delete_contour_for_current_phase("A4C") is True
    assert viewer.contours() == []
    assert viewer.can_undo() is True
    assert viewer.undo() is True
    assert [contour_snapshot(item) for item in viewer.contours()] == [contour_snapshot(contour)]
    assert viewer.can_redo() is True
    assert viewer.redo() is True
    assert viewer.contours() == []


def test_open_model_contour_keeps_phase_view_and_completion_order(qtbot) -> None:
    viewer = _loaded_viewer(qtbot, total=10, frame=3)
    recorder = SignalRecorder(viewer)

    assert viewer.start_model_contour(phase="ED", view="A4C", chamber="LV") is True
    for point in ((10.0, 40.0), (50.0, 40.0), (30.0, 10.0)):
        assert viewer.handle_contour_click(point) is True

    assert viewer.is_contour_mode_active is False
    payloads = recorder.args_of("contour_completed")
    assert len(payloads) == 1
    contour = payloads[0][0]
    assert contour_snapshot(contour) == {
        "chamber": "LV",
        "phase": "ED",
        "view": "A4C",
        "frame_index": 3,
        "points": 32,
    }
    assert contour.is_open_arc is True
    assert [name for name in recorder.names() if name in {"contours_changed", "contour_completed"}] == [
        "contours_changed",
        "contour_completed",
    ]


def test_rejected_landmarks_do_not_commit_a_contour(qtbot) -> None:
    viewer = _loaded_viewer(qtbot, total=10)
    recorder = SignalRecorder(viewer)

    assert viewer.start_model_contour(phase="ED", view="A4C", chamber="LV") is True
    for _ in range(3):
        assert viewer.handle_contour_click((10.0, 40.0)) is True

    assert recorder.args_of("contour_landmark_rejected") == [("invalid",)]
    assert recorder.args_of("contour_completed") == []
    assert "contours_changed" not in recorder.names()
    assert viewer.contours() == []
    assert viewer.is_contour_mode_active is True


def test_refine_without_an_open_contour_commits_nothing(qtbot) -> None:
    viewer = _loaded_viewer(qtbot, total=10)
    recorder = SignalRecorder(viewer)

    assert viewer.refine_active_open_contour() == (False, "")
    assert recorder.names() == []
    assert viewer.contours() == []


def test_a_frame_switch_discards_the_running_freehand_stroke(qtbot) -> None:
    viewer = _loaded_viewer(qtbot, total=10)
    viewer.set_area_tool_mode("freehand")
    assert viewer.start_generic_area_contour() is True
    assert viewer.contract.freehand_recording is True
    viewer.contract.freehand_points = [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)]
    recorder = SignalRecorder(viewer)

    viewer.set_state(make_state(frame=1, total=10))

    assert viewer.contract.freehand_recording is False
    assert viewer.contract.freehand_points == []
    assert viewer.contract.freehand_open_arc is False
    assert viewer.is_contour_mode_active is False
    assert viewer.contours() == []
    assert recorder.names() == []


def test_tool_switch_keeps_one_active_tool_and_clears_the_hint(qtbot) -> None:
    viewer = _loaded_viewer(qtbot, total=10)
    recorder = SignalRecorder(viewer)

    viewer.toggle_calibration_caliper()
    assert viewer.is_calibration_active is True

    viewer.start_linear_caliper_for("LVd")
    assert viewer.is_calibration_active is False
    assert viewer.is_linear_caliper_active is True
    assert recorder.only(MEASUREMENT_SIGNALS) == []

    viewer.cancel_active_tool()
    assert viewer.is_linear_caliper_active is False
    assert viewer.is_calibration_active is False
    assert viewer_surface(viewer)["hint"] == ""
    # Switching tools clears the linear preview, which is announced to the app;
    # it must never look like a completed calibration or measurement.
    assert recorder.args_of("calibration_completed") == []
    assert "linear_measurements_changed" in recorder.names()


def test_qh3_owner_inventory_is_stable_across_disposal(qtbot) -> None:
    viewer = _loaded_viewer(qtbot, total=10)

    inventory = viewer.qh3_controller_inventory()

    assert inventory == [
        "ResultsOverlayController",
        "TagsOverlayController",
        "MagnifierController",
    ]

    viewer.dispose_viewer_resources()
    viewer.dispose_viewer_resources()

    assert viewer.qh3_controller_inventory() == inventory
    assert viewer.current_instance_uid() == make_instance().sop_instance_uid
