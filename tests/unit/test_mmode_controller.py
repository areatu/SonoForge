"""MModeController without a ViewerWidget (issue 479).

The calibration flow (ROI -> depth -> time), the DICOM/heuristic fallbacks and
the frame caliper labels are pure state and run in the plain unit job. The scan
line tests build pyqtgraph items and are marked ``gui``.
"""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi
from echo_personal_tool.domain.models.frame_panels import (
    FramePanelLayout,
    MmodeCalibrationState,
    PanelKind,
    UltrasoundPanel,
)
from echo_personal_tool.presentation.viewer.mmode_controller import MMODE_CALIPER_LABEL
from tests.unit.mmode_fakes import FakeClick, FakeMModeViewer

ROI = DopplerSpectrogramRoi(x0=10.0, y0=40.0, width=100.0, height=50.0)
SECONDS = 4  # DICOM PhysicalUnits: seconds
CENTIMETERS = 3  # DICOM PhysicalUnits: cm


def _frame(height: int = 120, width: int = 160) -> np.ndarray:
    return np.zeros((height, width), dtype=np.uint8)


def _complete_state(*, time_from_dicom: bool = True) -> MmodeCalibrationState:
    return MmodeCalibrationState(
        roi=ROI,
        vertical_mm_per_pixel=0.5,
        horizontal_ms_per_pixel=4.0,
        from_dicom_tags=time_from_dicom,
        depth_from_dicom_tags=time_from_dicom,
        time_from_dicom_tags=time_from_dicom,
    )


def _m_panel(
    *,
    delta_x: float | None = None,
    units_x: int | None = None,
    delta_y: float | None = None,
    units_y: int | None = None,
) -> UltrasoundPanel:
    return UltrasoundPanel(
        kind=PanelKind.M_MODE,
        bounds=ROI,
        physical_delta_x=delta_x,
        physical_units_x=units_x,
        physical_delta_y=delta_y,
        physical_units_y=units_y,
    )


def _signals(fake: FakeMModeViewer) -> dict[str, list[object]]:
    seen: dict[str, list[object]] = {"calibration": [], "time": [], "line": []}
    fake.controller.calibration_changed.connect(seen["calibration"].append)
    fake.controller.time_calibration_completed.connect(seen["time"].append)
    fake.controller.line_completed.connect(lambda start, end: seen["line"].append((start, end)))
    return seen


# -- calibration state -------------------------------------------------------


def test_a_fresh_controller_owns_no_calibration() -> None:
    controller = FakeMModeViewer().controller
    assert controller.calibration_state is None
    assert controller.is_calibrated() is False
    assert controller.cal_step is None
    assert controller.line_active is False
    assert controller.vertical_lock is False


def test_apply_normalizes_the_roi_to_the_frame_and_notifies() -> None:
    fake = FakeMModeViewer(frame=_frame(height=60, width=80))
    seen = _signals(fake)
    oversized = DopplerSpectrogramRoi(x0=10.0, y0=40.0, width=500.0, height=500.0)
    fake.controller.apply_calibration_state(MmodeCalibrationState(oversized, 0.5, 4.0))
    state = fake.controller.calibration_state
    assert state is not None
    assert state.roi.x0 + state.roi.width <= 80.0
    assert state.roi.y0 + state.roi.height <= 60.0
    assert fake.controller.is_calibrated() is True
    assert seen["calibration"] == [state]


def test_apply_while_the_widget_syncs_a_tab_stays_silent() -> None:
    fake = FakeMModeViewer()
    seen = _signals(fake)
    fake.syncing = True
    fake.controller.apply_calibration_state(_complete_state())
    assert fake.controller.calibration_state == _complete_state()
    assert seen["calibration"] == []


def test_restore_applies_the_saved_calibration() -> None:
    fake = FakeMModeViewer()
    fake.controller.restore_state(_complete_state())
    assert fake.controller.calibration_state == _complete_state()


def test_restore_without_a_saved_calibration_reads_the_panel() -> None:
    panels = FramePanelLayout(panels=(_m_panel(delta_x=0.004, units_x=SECONDS, delta_y=0.05, units_y=CENTIMETERS),))
    fake = FakeMModeViewer(frame=_frame(), panels=panels)
    fake.controller.restore_state(None)
    state = fake.controller.calibration_state
    assert state is not None and state.is_complete()
    assert state.vertical_mm_per_pixel == pytest.approx(0.5)
    assert state.horizontal_ms_per_pixel == pytest.approx(4.0)
    assert state.time_from_dicom_tags is True


def test_restore_without_frame_or_calibration_does_nothing() -> None:
    fake = FakeMModeViewer()
    fake.controller.restore_state(None)
    assert fake.controller.calibration_state is None


def test_try_apply_needs_an_m_mode_panel() -> None:
    assert FakeMModeViewer(frame=_frame()).controller.try_apply_from_dicom_or_heuristic() is False
    b_only = FramePanelLayout(panels=(UltrasoundPanel(kind=PanelKind.B_MODE, bounds=ROI),))
    fake = FakeMModeViewer(frame=_frame(), panels=b_only)
    assert fake.controller.try_apply_from_dicom_or_heuristic() is False


def test_try_apply_falls_back_to_b_mode_depth_and_frame_time() -> None:
    panels = FramePanelLayout(
        panels=(
            UltrasoundPanel(kind=PanelKind.B_MODE, bounds=ROI, physical_delta_y=0.03, physical_units_y=CENTIMETERS),
            _m_panel(),
        )
    )
    fake = FakeMModeViewer(frame=_frame(), panels=panels, frame_time_ms=1000.0)
    assert fake.controller.try_apply_from_dicom_or_heuristic() is True
    state = fake.controller.calibration_state
    assert state is not None
    assert state.vertical_mm_per_pixel == pytest.approx(0.3)
    assert state.horizontal_ms_per_pixel == pytest.approx(1000.0 / ROI.width)
    assert fake.calibration_active is False, "a complete state arms no manual step"


def test_try_apply_without_a_depth_scale_arms_the_depth_step_on_the_dicom_roi(monkeypatch) -> None:
    monkeypatch.setattr(
        "echo_personal_tool.domain.services.auto_depth_calibration.try_auto_depth_calibration_in_roi",
        lambda frame, roi: None,
    )
    panels = FramePanelLayout(panels=(_m_panel(delta_x=0.004, units_x=SECONDS),))
    fake = FakeMModeViewer(frame=_frame(), panels=panels)
    assert fake.controller.try_apply_from_dicom_or_heuristic() is True
    assert fake.calls[:2] == ["cancel_tool", "clear_calibration_caliper"]
    assert fake.calibration_kind == "mmode_depth"
    assert fake.calibration_active is True
    assert fake.calibration_x == pytest.approx(ROI.x0 + ROI.width / 2.0)
    assert fake.controller.pending_roi is not None


def test_try_apply_without_a_time_scale_arms_the_time_step() -> None:
    panels = FramePanelLayout(panels=(_m_panel(delta_y=0.05, units_y=CENTIMETERS),))
    fake = FakeMModeViewer(frame=_frame(), panels=panels)
    assert fake.controller.try_apply_from_dicom_or_heuristic() is True
    assert fake.calibration_kind == "mmode_time"
    assert fake.calibration_active is True
    assert fake.controller.time_start_x is None


# -- calibration flow: ROI -> depth -> time ----------------------------------


def test_panel_calibration_needs_a_frame() -> None:
    fake = FakeMModeViewer()
    assert fake.controller.start_panel_calibration() is False
    assert fake.controller.cal_step is None


def test_panel_calibration_resets_the_draft_and_asks_for_the_first_corner() -> None:
    fake = FakeMModeViewer(frame=_frame())
    assert fake.controller.start_panel_calibration() is True
    assert fake.controller.cal_step == "roi"
    assert fake.controller.roi_corner1 is None
    assert fake.controller.pending_roi is None
    assert fake.calls == ["cancel_tool", "clear_calibration_caliper"]
    assert len(fake.messages) == 1


def test_roi_clicks_ignore_other_buttons_and_idle_state() -> None:
    fake = FakeMModeViewer(frame=_frame())
    assert fake.controller.handle_calibration_click(FakeClick(5.0, 5.0)) is False
    fake.controller.start_panel_calibration()
    assert fake.controller.handle_calibration_click(FakeClick(5.0, 5.0, left=False)) is False
    assert fake.controller.roi_corner1 is None


def test_two_roi_clicks_arm_the_depth_caliper_in_the_middle_of_the_rectangle() -> None:
    fake = FakeMModeViewer(frame=_frame())
    fake.controller.start_panel_calibration()
    assert fake.controller.handle_calibration_click(FakeClick(20.0, 30.0)) is True
    assert fake.controller.roi_corner1 == (20.0, 30.0)
    assert fake.controller.handle_calibration_click(FakeClick(100.0, 90.0)) is True
    assert fake.controller.cal_step is None
    assert fake.controller.roi_corner1 is None
    roi = fake.controller.pending_roi
    assert roi is not None
    assert (roi.x0, roi.width) == (20.0, 80.0)
    assert fake.calibration_kind == "mmode_depth"
    assert fake.calibration_active is True
    assert fake.calibration_x == pytest.approx(60.0)
    assert len(fake.messages) == 3


def test_escape_during_the_roi_step_drops_the_draft() -> None:
    fake = FakeMModeViewer(frame=_frame())
    assert fake.controller.cancel_roi_step() is False
    fake.controller.start_panel_calibration()
    fake.controller.handle_calibration_click(FakeClick(20.0, 30.0))
    assert fake.controller.cancel_roi_step() is True
    assert fake.controller.cal_step is None
    assert fake.controller.roi_corner1 is None
    assert fake.controller.pending_roi is None


def test_the_depth_answer_keeps_the_roi_and_chains_to_the_time_step() -> None:
    fake = FakeMModeViewer(frame=_frame())
    fake.controller.start_depth_step(ROI)
    fake.answers.append((2.0, True))  # 2 cm over 40 px
    fake.controller.prompt_depth_calibration(40.0)
    assert fake.controller.pending_roi == ROI
    assert fake.controller.pending_depth_mm_per_pixel == pytest.approx(0.5)
    assert fake.calibration_kind == "mmode_time"
    assert fake.controller.time_start_x is None
    assert fake.questions[0][2:] == (1.0, 0.01, 100.0, 2)


def test_a_cancelled_depth_dialog_drops_the_pending_roi() -> None:
    fake = FakeMModeViewer(frame=_frame())
    fake.controller.start_depth_step(ROI)
    fake.answers.append((2.0, False))
    fake.controller.prompt_depth_calibration(40.0)
    assert fake.controller.pending_roi is None
    assert fake.controller.pending_depth_mm_per_pixel is None


def test_the_time_answer_completes_the_calibration() -> None:
    fake = FakeMModeViewer(frame=_frame())
    seen = _signals(fake)
    fake.controller.start_depth_step(ROI)
    fake.answers.extend([(2.0, True), (1000.0, True)])
    fake.controller.prompt_depth_calibration(40.0)
    fake.controller.mark_time_start(10.0)
    assert fake.controller.time_start_x == 10.0
    fake.controller.prompt_time_span(250.0)
    state = fake.controller.calibration_state
    assert state is not None
    assert state.vertical_mm_per_pixel == pytest.approx(0.5)
    assert state.horizontal_ms_per_pixel == pytest.approx(4.0)
    assert state.from_dicom_tags is False
    assert seen["calibration"] == [state]
    assert seen["time"] == []
    assert fake.controller.pending_roi is None
    assert fake.controller.pending_depth_mm_per_pixel is None
    assert fake.controller.time_start_x is None


def test_a_standalone_time_span_reports_the_scale_only() -> None:
    fake = FakeMModeViewer(frame=_frame())
    seen = _signals(fake)
    fake.answers.append((500.0, True))
    fake.controller.prompt_time_span(100.0)
    assert seen["time"] == [5.0]
    assert seen["calibration"] == []
    fake.syncing = True
    fake.answers.append((500.0, True))
    fake.controller.prompt_time_span(100.0)
    assert seen["time"] == [5.0], "no signal while the widget syncs a tab"


def test_a_trusted_dicom_time_scale_skips_the_dialog() -> None:
    fake = FakeMModeViewer(frame=_frame())
    fake.controller.apply_calibration_state(_complete_state(time_from_dicom=True))
    fake.controller.start_depth_step(ROI)
    fake.answers.append((2.0, True))
    fake.controller.prompt_depth_calibration(40.0)
    fake.controller.prompt_time_span(100.0)
    assert len(fake.questions) == 1, "only the depth question was asked"
    state = fake.controller.calibration_state
    assert state is not None
    assert state.horizontal_ms_per_pixel == pytest.approx(4.0)
    assert state.time_from_dicom_tags is True


def test_an_untrusted_time_scale_still_asks() -> None:
    fake = FakeMModeViewer(frame=_frame())
    fake.controller.apply_calibration_state(_complete_state(time_from_dicom=False))
    fake.answers.append((1000.0, True))
    fake.controller.prompt_time_span(100.0)
    assert len(fake.questions) == 1


def test_a_cancelled_time_dialog_drops_the_whole_draft() -> None:
    fake = FakeMModeViewer(frame=_frame())
    seen = _signals(fake)
    fake.controller.start_depth_step(ROI)
    fake.answers.extend([(2.0, True), (1000.0, False)])
    fake.controller.prompt_depth_calibration(40.0)
    fake.controller.prompt_time_span(100.0)
    assert fake.controller.pending_roi is None
    assert fake.controller.pending_depth_mm_per_pixel is None
    assert fake.controller.calibration_state is None
    assert seen == {"calibration": [], "time": [], "line": []}


def test_clearing_the_generic_caliper_resets_the_time_start_and_pending_depth() -> None:
    fake = FakeMModeViewer(frame=_frame())
    fake.controller.start_depth_step(ROI)
    fake.answers.append((2.0, True))
    fake.controller.prompt_depth_calibration(40.0)
    fake.controller.mark_time_start(12.0)
    fake.controller.on_calibration_caliper_cleared()
    assert fake.controller.time_start_x is None
    assert fake.controller.pending_depth_mm_per_pixel is None
    assert fake.controller.pending_roi == ROI


# -- vertical calipers on the M-mode strip -----------------------------------


def test_the_vertical_caliper_needs_a_complete_calibration() -> None:
    fake = FakeMModeViewer(frame=_frame())
    assert fake.controller.start_vertical_caliper() is False
    assert fake.linear_calipers == []
    fake.controller.apply_calibration_state(_complete_state())
    assert fake.controller.start_vertical_caliper() is True
    assert fake.linear_calipers == [MMODE_CALIPER_LABEL]


def test_a_frame_sequence_marks_its_labels_vertical_for_the_session() -> None:
    fake = FakeMModeViewer(frame=_frame())
    labels = ("IVSd", "LVEDD", "LVPWd")
    assert fake.controller.start_frame_caliper_sequence(labels) is False
    fake.controller.apply_calibration_state(_complete_state())
    assert fake.controller.start_frame_caliper_sequence(()) is False
    assert fake.controller.start_frame_caliper_sequence(labels) is True
    assert set(labels) <= fake.vertical_labels
    assert fake.controller.session_vertical_labels == frozenset(labels)
    fake.controller.reset_session_vertical_labels()
    assert fake.vertical_labels == {"TAPSE", "M-mode"}, "built-in vertical labels survive the reset"
    assert fake.controller.session_vertical_labels == frozenset()


def test_a_refused_sequence_adds_no_labels() -> None:
    fake = FakeMModeViewer(frame=_frame())
    fake.controller.apply_calibration_state(_complete_state())
    fake.caliper_accepts = False
    assert fake.controller.start_frame_caliper_sequence(("EPSS",)) is False
    assert "EPSS" not in fake.vertical_labels


# -- anatomical scan line (pyqtgraph items) ----------------------------------


def _with_view_box(*, frame: np.ndarray | None = None) -> FakeMModeViewer:
    """A fake viewer whose view is a real ViewBox — the line item draws into it."""
    import pyqtgraph as pg

    fake = FakeMModeViewer(frame=frame)
    fake.view = pg.ViewBox()
    return fake


@pytest.mark.gui
class TestScanLine:
    @pytest.fixture(autouse=True)
    def _qapp(self, qapp):
        return qapp

    def test_start_arms_placement_and_the_viewport_cursor(self) -> None:
        fake = _with_view_box(frame=_frame())
        fake.controller.start_line()
        assert fake.controller.line_active is True
        assert fake.controller.line_click_step == "start"
        assert fake.controller.line_item is not None
        assert fake.calls == ["unset_cursor", "apply_viewport_cursor"]

    def test_the_vertical_lock_carries_over_to_a_new_line(self) -> None:
        fake = _with_view_box(frame=_frame())
        fake.controller.set_vertical_lock(True)
        fake.controller.start_line()
        assert fake.controller.line_item is not None
        assert fake.controller.line_item.vertical_lock is True

    def test_two_clicks_complete_the_line_in_image_coordinates(self) -> None:
        fake = _with_view_box(frame=_frame(height=120))
        seen = _signals(fake)
        fake.controller.start_line()
        assert fake.controller.handle_line_click(10.0, 100.0) is True
        assert fake.controller.line_click_step == "end"
        assert fake.controller.handle_line_click(50.0, 20.0) is True
        assert fake.controller.line_click_step == "start"
        assert seen["line"] == [((10.0, 20.0), (50.0, 100.0))]

    def test_hover_previews_only_while_the_end_is_pending(self) -> None:
        fake = _with_view_box(frame=_frame())
        assert fake.controller.handle_line_hover(1.0, 1.0) is False
        fake.controller.start_line()
        assert fake.controller.handle_line_hover(1.0, 1.0) is False
        fake.controller.handle_line_click(10.0, 10.0)
        assert fake.controller.handle_line_hover(20.0, 20.0) is True

    def test_clicks_from_events_need_an_armed_line_and_the_left_button(self) -> None:
        fake = _with_view_box(frame=_frame())
        assert fake.controller.handle_line_click_from_event(FakeClick(10.0, 10.0)) is False
        fake.controller.start_line()
        assert fake.controller.handle_line_click_from_event(FakeClick(10.0, 10.0, left=False)) is False
        assert fake.controller.handle_line_click_from_event(FakeClick(10.0, 10.0)) is True

    def test_dragging_with_the_vertical_lock_keeps_x_and_emits_on_release(self) -> None:
        fake = _with_view_box(frame=_frame(height=120))
        seen = _signals(fake)
        fake.controller.set_vertical_lock(True)
        fake.controller.start_line()
        fake.controller.handle_line_click(10.0, 100.0)
        fake.controller.handle_line_click(50.0, 20.0)
        fake.controller.begin_node_drag(1)
        fake.controller.node_dragging(1, (90.0, 60.0))
        item = fake.controller.line_item
        assert item is not None
        assert item.line_end == (50.0, 60.0)
        assert len(seen["line"]) == 1, "no emission while dragging"
        fake.controller.end_node_drag(1)
        assert seen["line"][-1] == ((10.0, 20.0), (50.0, 60.0))

    def test_dragging_without_a_line_is_harmless(self) -> None:
        fake = _with_view_box(frame=_frame())
        seen = _signals(fake)
        fake.controller.node_dragging(0, (1.0, 1.0))
        fake.controller.end_node_drag(0)
        assert seen["line"] == []

    def test_cancel_removes_the_line(self) -> None:
        fake = _with_view_box(frame=_frame())
        fake.controller.start_line()
        fake.controller.cancel_line()
        assert fake.controller.line_active is False
        assert fake.controller.line_item is None
        assert fake.controller.line_click_step is None
