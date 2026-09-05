"""Unit tests for presentation/doppler_overlay.py."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from echo_personal_tool.domain.models import (
    DopplerIntervalMarker,
    DopplerMeasurementDTO,
    DopplerPeakMarker,
)
from echo_personal_tool.domain.models.doppler_axis import DopplerAxisMapping

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def _setup_qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture()
def mock_plot():
    plot = MagicMock()
    plot.items = []
    plot.addItem = lambda item: plot.items.append(item)
    plot.removeItem = MagicMock()
    plot.plot_height = 200
    plot.plot_width = 1000
    return plot


@pytest.fixture()
def overlay(mock_plot):
    from echo_personal_tool.presentation.doppler_overlay import DopplerOverlayTools

    return DopplerOverlayTools(mock_plot)


class TestConstruction:
    def test_creates_with_default_mode(self, overlay):
        assert overlay.get_tool_mode() == "none"
        assert overlay._peak_markers == []
        assert overlay._interval_markers == []
        assert overlay._traces == []
        assert not overlay.has_trace_onset()
        assert not overlay.has_pending_interval_start()

    def test_default_axis_mapping(self, overlay):
        mapping = overlay.axis_mapping()
        assert isinstance(mapping, DopplerAxisMapping)


class TestSetToolMode:
    def test_set_peak_mode(self, overlay):
        overlay.set_tool_mode("peak")
        assert overlay.get_tool_mode() == "peak"

    def test_set_interval_mode(self, overlay):
        overlay.set_tool_mode("interval")
        assert overlay.get_tool_mode() == "interval"

    def test_set_trace_mode(self, overlay):
        overlay.set_tool_mode("trace")
        assert overlay.get_tool_mode() == "trace"

    def test_invalid_mode_raises(self, overlay):
        with pytest.raises(ValueError, match="Unsupported Doppler tool mode"):
            overlay.set_tool_mode("invalid")

    def test_set_same_mode_noop(self, overlay):
        overlay.set_tool_mode("peak")
        overlay.set_tool_mode("peak")
        assert overlay.get_tool_mode() == "peak"

    def test_set_none_clears_partial_state(self, overlay):
        overlay.set_tool_mode("peak")
        overlay._active_partial_points = [(1.0, 2.0)]
        overlay.set_tool_mode("none")
        assert overlay._active_partial_points == []


class TestCancelActiveTool:
    def test_cancels_active_mode(self, overlay):
        overlay.set_tool_mode("peak")
        result = overlay.cancel_active_tool()
        assert result is True
        assert overlay.get_tool_mode() == "none"

    def test_returns_false_when_already_none(self, overlay):
        result = overlay.cancel_active_tool()
        assert result is False

    def test_clears_workflow(self, overlay):
        overlay.start_mitral_inflow_workflow()
        overlay.cancel_active_tool()
        assert overlay._workflow is None


class TestPeakLabel:
    def test_set_peak_label(self, overlay):
        overlay.set_peak_label("E", single_shot=True)
        assert overlay._peak_label_index == 0
        assert overlay._single_shot_peak is True

    def test_invalid_peak_label_raises(self, overlay):
        with pytest.raises(ValueError, match="Unsupported label"):
            overlay.set_peak_label("INVALID")

    def test_set_interval_label(self, overlay):
        overlay.set_interval_label("DT", single_shot=True)
        assert overlay._interval_label_index == 0

    def test_invalid_interval_label_raises(self, overlay):
        with pytest.raises(ValueError, match="Unsupported label"):
            overlay.set_interval_label("INVALID")


class TestHandleClick:
    def test_none_mode_returns_false(self, overlay):
        result = overlay.handle_click(100.0, 50.0)
        assert result is False

    def test_peak_mode_adds_marker(self, overlay):
        overlay.set_tool_mode("peak")
        result = overlay.handle_click(100.0, 50.0)
        assert result is True
        assert len(overlay._peak_markers) == 1

    def test_interval_first_click_sets_start(self, overlay):
        overlay.set_tool_mode("interval")
        result = overlay.handle_click(100.0, 50.0)
        assert result is True
        assert overlay.has_pending_interval_start()

    def test_interval_second_click_adds_marker(self, overlay):
        overlay.set_tool_mode("interval")
        overlay.handle_click(100.0, 50.0)
        result = overlay.handle_click(200.0, 50.0)
        assert result is True
        assert len(overlay._interval_markers) == 1
        assert not overlay.has_pending_interval_start()

    def test_peak_marker_can_be_dragged_and_emits_updated_measurement(self, overlay):
        overlay.set_axis_mapping(
            DopplerAxisMapping.from_frame_size(1000.0, 200.0, time_span_ms=1000.0)
        )
        overlay.set_tool_mode("peak")
        overlay.handle_click(100.0, 80.0)
        emitted = []
        overlay.markers_changed.connect(emitted.append)

        assert overlay.begin_peak_drag(100.0, 80.0) is True
        assert overlay.move_peak_drag(250.0, 60.0) is True
        assert overlay.finish_peak_drag() is True

        marker = overlay.get_measurement_dto().peaks[0]
        assert marker.time_ms == pytest.approx(250.0)
        assert marker.velocity_cm_s == pytest.approx(40.0)
        assert emitted
        assert overlay.finish_peak_drag() is False


class TestTraceClick:
    def test_trace_first_click_near_baseline(self, overlay):
        overlay.set_tool_mode("trace")
        # First click must be near baseline
        baseline_y = overlay._baseline_plot_y_px()
        result = overlay.handle_click(100.0, baseline_y)
        assert result is True
        assert overlay.has_trace_onset()

    def test_trace_first_click_far_from_baseline_rejected(self, overlay):
        overlay.set_tool_mode("trace")
        result = overlay.handle_click(100.0, 10.0)
        assert result is False

    def test_trace_double_click_finishes(self, overlay):
        overlay.set_tool_mode("trace")
        baseline_y = overlay._baseline_plot_y_px()
        overlay.handle_click(100.0, baseline_y)
        overlay.handle_click(200.0, 50.0)
        overlay.handle_click(300.0, baseline_y)
        result = overlay.handle_click(300.0, baseline_y, double=True)
        assert isinstance(result, bool)


class TestSetTraceLabel:
    def test_set_trace_label(self, overlay):
        overlay.set_trace_label("VTI MV")
        assert overlay._trace_label == "VTI MV"

    def test_empty_label_defaults_to_vti(self, overlay):
        overlay.set_trace_label("")
        assert overlay._trace_label == "VTI"

    def test_unknown_label_allowed(self, overlay):
        overlay.set_trace_label("CustomVTI")
        assert overlay._trace_label == "CustomVTI"


class TestPrefillIntervalStart:
    def test_sets_start_time(self, overlay):
        overlay.prefill_interval_start(500.0)
        assert overlay.has_pending_interval_start()

    def test_sets_preview(self, overlay):
        overlay.prefill_interval_start(500.0)
        overlay.set_tool_mode("interval")
        assert overlay._interval_preview_item is not None


class TestMitralInflowWorkflow:
    def test_starts_workflow(self, overlay):
        overlay.start_mitral_inflow_workflow()
        assert overlay._workflow is not None
        assert overlay.get_tool_mode() == "peak"

    def test_workflow_prompt(self, overlay):
        overlay.start_mitral_inflow_workflow()
        prompt = overlay.workflow_prompt()
        assert prompt is not None

    def test_workflow_none_when_not_active(self, overlay):
        assert overlay.workflow_prompt() is None


class TestGetMeasurementDto:
    def test_returns_empty_dto(self, overlay):
        dto = overlay.get_measurement_dto()
        assert isinstance(dto, DopplerMeasurementDTO)
        assert dto.peaks == ()
        assert dto.intervals == ()
        assert dto.traces == ()

    def test_returns_populated_dto(self, overlay):
        overlay.set_tool_mode("peak")
        overlay.handle_click(100.0, 50.0)
        dto = overlay.get_measurement_dto()
        assert len(dto.peaks) == 1


class TestLoadMeasurementDto:
    def test_loads_dto(self, overlay):
        dto = DopplerMeasurementDTO(
            peaks=(DopplerPeakMarker(label="E", time_ms=100.0, velocity_cm_s=80.0),),
            intervals=(DopplerIntervalMarker(label="DT", start_time_ms=100.0, end_time_ms=300.0),),
            traces=(),
        )
        overlay.load_measurement_dto(dto)
        assert len(overlay._peak_markers) == 1
        assert len(overlay._interval_markers) == 1


class TestClearMeasurements:
    def test_clears_all(self, overlay):
        overlay.set_tool_mode("peak")
        overlay.handle_click(100.0, 50.0)
        overlay.clear_measurements()
        assert len(overlay._peak_markers) == 0
        assert len(overlay._interval_markers) == 0
        assert len(overlay._traces) == 0
        assert overlay.get_tool_mode() == "none"

    def test_keep_calibration_graphics(self, overlay):
        overlay.clear_measurements(keep_calibration_graphics=True)
        assert len(overlay._peak_markers) == 0


class TestSetAxisMapping:
    def test_sets_new_mapping(self, overlay):
        mapping = DopplerAxisMapping(time_span_ms=2000.0)
        overlay.set_axis_mapping(mapping)
        assert overlay.axis_mapping() is mapping


class TestTracePrompt:
    def test_trace_prompt_in_peak_mode(self, overlay):
        overlay.set_tool_mode("peak")
        assert overlay.trace_prompt() is None

    def test_trace_prompt_in_trace_mode(self, overlay):
        overlay.set_tool_mode("trace")
        prompt = overlay.trace_prompt()
        assert prompt is not None
        assert "VTI" in prompt


class TestConsumeTraceClickSuppression:
    def test_returns_false_when_not_suppressed(self, overlay):
        assert overlay.consume_trace_click_suppression() is False

    def test_returns_true_and_resets(self, overlay):
        overlay._trace_suppress_click = True
        assert overlay.consume_trace_click_suppression() is True
        assert overlay.consume_trace_click_suppression() is False


class TestHandleClickInTraceMode:
    def test_double_click_near_baseline(self, overlay):
        overlay.set_tool_mode("trace")
        baseline_y = overlay._baseline_plot_y_px()
        overlay.handle_click(100.0, baseline_y)
        result = overlay.handle_click(200.0, baseline_y, double=True)
        assert isinstance(result, bool)

    def test_double_click_far_from_baseline(self, overlay):
        overlay.set_tool_mode("trace")
        result = overlay.handle_click(100.0, 10.0, double=True)
        assert result is False


class TestVesselMode:
    def test_set_vessel_mode_and_status(self, overlay, mock_plot):
        overlay.set_axis_mapping(_vessel_mapping())
        overlay.set_vessel_mode()
        assert overlay.vessel_status() == "psv"
        overlay.handle_vessel_click(200.0, 100.0)
        assert overlay.vessel_status() == "edv"
        overlay.handle_vessel_click(300.0, 50.0)
        assert overlay.vessel_status() == "done"
        assert overlay.get_vessel_values() is not None

    def test_vessel_metrics_emitted(self, overlay, mock_plot):
        overlay.set_axis_mapping(_vessel_mapping())
        received = []
        overlay.vessel_changed.connect(received.append)
        overlay.set_vessel_mode()
        overlay.handle_vessel_click(200.0, 100.0)
        overlay.handle_vessel_click(300.0, 50.0)
        assert received and received[-1] is not None

    def test_clear_vessel(self, overlay, mock_plot):
        overlay.set_axis_mapping(_vessel_mapping())
        overlay.set_vessel_mode()
        overlay.handle_vessel_click(200.0, 100.0)
        overlay.handle_vessel_click(300.0, 50.0)
        overlay.clear_vessel()
        assert overlay.vessel_status() == "none"
        assert overlay.get_vessel_values() is None

    def test_vessel_values_map_velocity(self, overlay, mock_plot):
        overlay.set_axis_mapping(_vessel_mapping())
        overlay.set_vessel_mode()
        # baseline at y=100, span 200 => pixels_per_cm_s = 200/200 = 1
        overlay.handle_vessel_click(200.0, 50.0)  # PSV -> 50 cm/s
        overlay.handle_vessel_click(300.0, 100.0)  # EDV -> 0 cm/s
        psv, edv = overlay.get_vessel_values()
        assert psv == pytest.approx(50.0)
        assert edv == pytest.approx(0.0)

    def test_move_vessel_caliper_drag(self, overlay, mock_plot):
        overlay.set_axis_mapping(_vessel_mapping())
        overlay.set_vessel_mode()
        overlay.handle_vessel_click(200.0, 50.0)
        overlay.handle_vessel_click(300.0, 100.0)
        assert overlay.begin_vessel_drag(201.0, 50.0) is True
        overlay.move_vessel_caliper(200.0, 60.0)
        psv, _ = overlay.get_vessel_values()
        assert psv == pytest.approx(40.0)
        overlay.finish_vessel_drag()
        assert overlay.vessel_status() == "done"

    def test_vessel_text_includes_units(self, overlay, mock_plot):
        overlay.set_axis_mapping(_vessel_mapping())
        overlay.set_vessel_mode()
        overlay.handle_vessel_click(200.0, 50.0)  # PSV -> 50 cm/s
        overlay.handle_vessel_click(300.0, 90.0)  # EDV -> 10 cm/s
        assert overlay._vessel_text_item is not None
        text = overlay._vessel_text_item.toPlainText()
        assert "PSV: 50.0 cm/s" in text
        assert "EDV: 10.0 cm/s" in text
        assert "MV≈: 23.3 cm/s" in text

    def test_vessel_text_has_opaque_background(self, overlay, mock_plot):
        overlay.set_axis_mapping(_vessel_mapping())
        overlay.set_vessel_mode()
        overlay.handle_vessel_click(200.0, 50.0)
        overlay.handle_vessel_click(300.0, 100.0)
        fill = overlay._vessel_text_item.fill
        assert fill is not None
        color = fill.color()
        assert color.alpha() > 150

    def test_vessel_no_vertical_lines(self, overlay, mock_plot):
        overlay.set_axis_mapping(_vessel_mapping())
        overlay.set_vessel_mode()
        overlay.handle_vessel_click(200.0, 50.0)
        overlay.handle_vessel_click(300.0, 100.0)
        from pyqtgraph import PlotDataItem

        for item in mock_plot.items:
            if not isinstance(item, PlotDataItem):
                continue
            pen = item.opts.get("pen")
            if pen is None:
                continue
            assert pen.color().name() not in ("#e53935", "#43a047")


class TestDerivePsvEdvIndices:
    def test_finds_interior_edv_min(self):
        from echo_personal_tool.presentation.doppler_overlay import derive_psv_edv_indices

        # velocities cm/s: [10, 30, 60, 80, 90, 75, 50, 35, 22, 40] -> y = 100 - v
        envelope = tuple((100.0 + i * 100.0, y) for i, y in enumerate([90, 70, 40, 20, 10, 25, 50, 65, 78, 60]))
        psv_idx, edv_idx = derive_psv_edv_indices(envelope)
        assert psv_idx == 4
        assert edv_idx == 8

    def test_flat_end_falls_back_to_last_point(self):
        from echo_personal_tool.presentation.doppler_overlay import derive_psv_edv_indices

        # minimum in the window is only ~1 cm/s below the end -> unreliable
        envelope = tuple((100.0 + i * 100.0, y) for i, y in enumerate([90, 70, 40, 20, 10, 30, 45, 58, 70, 69]))
        psv_idx, edv_idx = derive_psv_edv_indices(envelope)
        assert psv_idx == 4
        assert edv_idx == 9

    def test_short_envelope_uses_last_point(self):
        from echo_personal_tool.presentation.doppler_overlay import derive_psv_edv_indices

        envelope = ((100.0, 50.0), (200.0, 60.0), (300.0, 40.0), (400.0, 70.0))
        psv_idx, edv_idx = derive_psv_edv_indices(envelope)
        assert psv_idx == 2
        assert edv_idx == 3

    def test_psv_near_end_short_diastolic_fallback(self):
        from echo_personal_tool.presentation.doppler_overlay import derive_psv_edv_indices

        # velocities cm/s: [20, 40, 60, 80, 70, 50, 30, 20, 15, 90] -> PSV at the last point
        envelope = tuple((100.0 + i * 100.0, y) for i, y in enumerate([80, 60, 40, 20, 30, 50, 70, 80, 85, 10]))
        psv_idx, edv_idx = derive_psv_edv_indices(envelope)
        assert psv_idx == 9
        assert edv_idx == 9


class TestAutoTrace:
    def test_apply_auto_trace_sets_vessel_done(self, overlay, mock_plot):
        overlay.set_axis_mapping(_vessel_mapping())
        envelope = ((100.0, 50.0), (200.0, 60.0), (300.0, 40.0), (400.0, 70.0))
        result = overlay.apply_auto_trace(envelope)
        assert result is not None
        psv, edv = result
        assert psv == pytest.approx(60.0)
        assert edv == pytest.approx(30.0)
        assert overlay.vessel_status() == "done"
        psv_v, edv_v = overlay.get_vessel_values()
        assert psv_v == pytest.approx(60.0)
        assert edv_v == pytest.approx(30.0)
        assert overlay._auto_envelope_item is not None
        assert overlay._auto_envelope_item in mock_plot.items

    def test_apply_auto_trace_places_edv_at_diastolic_min(self, overlay, mock_plot):
        overlay.set_axis_mapping(_vessel_mapping())
        envelope = tuple((100.0 + i * 100.0, y) for i, y in enumerate([90, 70, 40, 20, 10, 25, 50, 65, 78, 60]))
        result = overlay.apply_auto_trace(envelope)
        assert result == pytest.approx((90.0, 22.0))
        assert overlay._vessel_psv_px == envelope[4]
        assert overlay._vessel_edv_px == envelope[8]

    def test_apply_auto_trace_short_envelope_returns_none(self, overlay, mock_plot):
        overlay.set_axis_mapping(_vessel_mapping())
        assert overlay.apply_auto_trace(((100.0, 50.0),)) is None
        assert overlay._auto_envelope_item is None

    def test_apply_auto_trace_empty_returns_none(self, overlay, mock_plot):
        overlay.set_axis_mapping(_vessel_mapping())
        assert overlay.apply_auto_trace(()) is None

    def test_clear_vessel_removes_envelope(self, overlay, mock_plot):
        overlay.set_axis_mapping(_vessel_mapping())
        overlay.apply_auto_trace(((100.0, 50.0), (200.0, 60.0)))
        assert overlay._auto_envelope_item is not None
        overlay.clear_vessel()
        assert overlay._auto_envelope_item is None

    def test_clear_measurements_clears_vessel_state(self, overlay, mock_plot):
        """Vessel PSV/EDV markers, auto-trace line, and text must be cleared by
        clear_measurements() (used on file switch) so stale measurements do not
        linger over a newly loaded study."""
        overlay.set_axis_mapping(_vessel_mapping())
        overlay.apply_auto_trace(((100.0, 50.0), (200.0, 60.0)))
        assert overlay._vessel_psv_px is not None
        assert overlay._vessel_edv_px is not None
        assert overlay._auto_envelope_item is not None
        overlay.clear_measurements(keep_calibration_graphics=False)
        assert overlay._vessel_psv_px is None
        assert overlay._vessel_edv_px is None
        assert overlay._auto_envelope_item is None
        assert overlay.vessel_status() == "none"


class TestAutoTraceWithCycles:
    def test_apply_auto_trace_uses_ecg_cycle(self, overlay, mock_plot):
        from echo_personal_tool.domain.services.cardiac_cycle_service import CardiacCycle

        overlay.set_axis_mapping(_vessel_mapping_with_time())
        envelope = tuple((100.0 + i * 100.0, y) for i, y in enumerate([90, 70, 40, 20, 10, 25, 50, 65, 78, 60]))
        cycle = CardiacCycle(
            start_ms=0.0,
            end_ms=2500.0,
            r_peak_ms=0.0,
            ed_ms=0.0,
            es_ms=2500.0,
            source="ecg",
            confidence=0.9,
        )
        result = overlay.apply_auto_trace(envelope, cycles=(cycle,))
        assert result == pytest.approx((90.0, 22.0))
        assert overlay.vessel_cycle_source() == "ecg"

    def test_apply_auto_trace_falls_back_when_cycle_absent(self, overlay, mock_plot):
        from echo_personal_tool.domain.services.cardiac_cycle_service import CardiacCycle

        overlay.set_axis_mapping(_vessel_mapping_with_time())
        envelope = tuple((100.0 + i * 100.0, y) for i, y in enumerate([90, 70, 40, 20, 10, 25, 50, 65, 78, 60]))
        cycle = CardiacCycle(
            start_ms=2500.0,
            end_ms=4000.0,
            r_peak_ms=2500.0,
            ed_ms=2500.0,
            es_ms=4000.0,
            source="ecg",
            confidence=0.9,
        )
        result = overlay.apply_auto_trace(envelope, cycles=(cycle,))
        assert result == pytest.approx((90.0, 22.0))
        assert overlay.vessel_cycle_source() == "image"

    def test_apply_auto_trace_no_cycles_source_image(self, overlay, mock_plot):
        overlay.set_axis_mapping(_vessel_mapping_with_time())
        envelope = ((100.0, 50.0), (200.0, 60.0), (300.0, 40.0), (400.0, 70.0))
        overlay.apply_auto_trace(envelope)
        assert overlay.vessel_cycle_source() == "image"

    def test_clear_vessel_resets_cycle_source(self, overlay, mock_plot):
        from echo_personal_tool.domain.services.cardiac_cycle_service import CardiacCycle

        overlay.set_axis_mapping(_vessel_mapping_with_time())
        envelope = tuple((100.0 + i * 100.0, y) for i, y in enumerate([90, 70, 40, 20, 10, 25, 50, 65, 78, 60]))
        cycle = CardiacCycle(
            start_ms=0.0,
            end_ms=2500.0,
            r_peak_ms=0.0,
            ed_ms=0.0,
            es_ms=2500.0,
            source="ecg",
            confidence=0.9,
        )
        overlay.apply_auto_trace(envelope, cycles=(cycle,))
        assert overlay.vessel_cycle_source() == "ecg"
        overlay.clear_vessel()
        assert overlay.vessel_cycle_source() is None


class TestAutoVtiTrace:
    def test_commits_trace_from_envelope(self, overlay, mock_plot):
        overlay.set_axis_mapping(_vessel_mapping_with_time())
        envelope = ((100.0, 50.0), (200.0, 60.0), (300.0, 40.0), (400.0, 70.0))
        assert overlay.apply_auto_vti_trace(envelope, trace_label="VTI") is True
        assert len(overlay._traces) == 1
        assert overlay._traces[0].label == "VTI"
        assert overlay._auto_envelope_item is not None

    def test_trace_zone_draws_only_clipped_envelope_and_peak_guide(self, overlay, mock_plot):
        overlay.set_axis_mapping(_vessel_mapping_with_time())
        envelope = tuple((100.0 + i * 100.0, y) for i, y in enumerate([90, 70, 40, 20, 10, 25, 50]))

        assert overlay.apply_auto_vti_trace(
            envelope,
            trace_label="VTI MV",
            time_range_ms=(200.0, 600.0),
        ) is True

        trace = overlay._traces[0]
        assert min(point[0] for point in trace.points) >= 200.0
        assert max(point[0] for point in trace.points) <= 600.0
        assert overlay._auto_peak_guide_item is not None
        assert len(mock_plot.items) > 0

    def test_short_envelope_returns_false(self, overlay, mock_plot):
        overlay.set_axis_mapping(_vessel_mapping())
        assert overlay.apply_auto_vti_trace(((100.0, 50.0),)) is False
        assert overlay._traces == []

    def test_empty_envelope_returns_false(self, overlay, mock_plot):
        overlay.set_axis_mapping(_vessel_mapping())
        assert overlay.apply_auto_vti_trace(()) is False

    def test_clips_to_selected_cycle(self, overlay, mock_plot):
        from echo_personal_tool.domain.services.cardiac_cycle_service import CardiacCycle

        overlay.set_axis_mapping(_vessel_mapping_with_time())
        envelope = tuple((100.0 + i * 100.0, y) for i, y in enumerate([90, 70, 40, 20, 10, 25, 50, 65, 78, 60]))
        # cycle 900..1500 ms -> x 550..800 -> envelope points at x=600,700,800
        cycle = CardiacCycle(
            start_ms=900.0,
            end_ms=1500.0,
            r_peak_ms=900.0,
            ed_ms=900.0,
            es_ms=1500.0,
            source="ecg",
            confidence=0.9,
        )
        assert overlay.apply_auto_vti_trace(envelope, cycles=(cycle,)) is True
        trace = overlay._traces[0]
        assert len(trace.points) == 3
        times = [p[0] for p in trace.points]
        assert min(times) >= 900.0
        assert max(times) <= 1500.0

    def test_cycle_absent_falls_back_to_whole_envelope(self, overlay, mock_plot):
        from echo_personal_tool.domain.services.cardiac_cycle_service import CardiacCycle

        overlay.set_axis_mapping(_vessel_mapping_with_time())
        envelope = tuple((100.0 + i * 100.0, y) for i, y in enumerate([90, 70, 40, 20, 10, 25, 50, 65, 78, 60]))
        cycle = CardiacCycle(
            start_ms=5000.0,
            end_ms=6000.0,
            r_peak_ms=5000.0,
            ed_ms=5000.0,
            es_ms=6000.0,
            source="ecg",
            confidence=0.9,
        )
        assert overlay.apply_auto_vti_trace(envelope, cycles=(cycle,)) is True
        assert len(overlay._traces[0].points) == 10

    def test_clips_to_user_defined_time_range(self, overlay, mock_plot):
        overlay.set_axis_mapping(_vessel_mapping_with_time())
        envelope = tuple((100.0 + i * 100.0, y) for i, y in enumerate([90, 70, 40, 20, 10, 25, 50, 65, 78, 60]))
        assert overlay.apply_auto_vti_trace(envelope, time_range_ms=(900.0, 1500.0)) is True
        trace = overlay._traces[0]
        times = [p[0] for p in trace.points]
        assert min(times) >= 900.0
        assert max(times) <= 1500.0

    def test_time_range_priority_over_cycles(self, overlay, mock_plot):
        from echo_personal_tool.domain.services.cardiac_cycle_service import CardiacCycle

        overlay.set_axis_mapping(_vessel_mapping_with_time())
        envelope = tuple((100.0 + i * 100.0, y) for i, y in enumerate([90, 70, 40, 20, 10, 25, 50, 65, 78, 60]))
        cycle = CardiacCycle(
            start_ms=5000.0,
            end_ms=6000.0,
            r_peak_ms=5000.0,
            ed_ms=5000.0,
            es_ms=6000.0,
            source="ecg",
            confidence=0.9,
        )
        assert overlay.apply_auto_vti_trace(envelope, cycles=(cycle,), time_range_ms=(900.0, 1500.0)) is True
        trace = overlay._traces[0]
        times = [p[0] for p in trace.points]
        assert min(times) >= 900.0
        assert max(times) <= 1500.0

    def test_time_range_too_short_returns_false(self, overlay, mock_plot):
        overlay.set_axis_mapping(_vessel_mapping_with_time())
        envelope = tuple((100.0 + i * 100.0, y) for i, y in enumerate([90, 70, 40, 20, 10, 25, 50, 65, 78, 60]))
        assert overlay.apply_auto_vti_trace(envelope, time_range_ms=(900.0, 901.0)) is False


class TestAutovtiRegionSelection:
    def test_sets_tool_mode(self, overlay):
        overlay.set_axis_mapping(_vessel_mapping_with_time())
        overlay.set_trace_label("VTI")
        overlay.set_tool_mode("autovti_region")
        assert overlay._tool_mode == "autovti_region"
        assert overlay._trace_label == "VTI"

    def test_first_click_records_start_and_direction_up(self, overlay, mock_plot):
        overlay.set_axis_mapping(_vessel_mapping_with_time())
        overlay.set_trace_label("VTI")
        overlay.set_tool_mode("autovti_region")
        baseline_y = overlay._baseline_plot_y_px()
        assert overlay.handle_click(300.0, baseline_y - 50) is True
        assert overlay._autovti_start_ms is not None
        assert overlay._autovti_direction == "up"
        assert overlay._autovti_region_item is not None

    def test_first_click_direction_down(self, overlay, mock_plot):
        overlay.set_axis_mapping(_vessel_mapping_with_time())
        overlay.set_trace_label("VTI")
        overlay.set_tool_mode("autovti_region")
        baseline_y = overlay._baseline_plot_y_px()
        assert overlay.handle_click(300.0, baseline_y + 50) is True
        assert overlay._autovti_direction == "down"

    def test_direction_uses_velocity_not_raw_y(self, overlay, mock_plot):
        """Direction must come from velocity_cm_s_from_y, not a raw Y comparison,
        so it is correct regardless of ViewBox coordinate orientation."""
        overlay.set_axis_mapping(_vessel_mapping_with_time())
        overlay.set_trace_label("VTI")
        overlay.set_tool_mode("autovti_region")
        # _vessel_mapping_with_time: baseline_y=100, velocity_max=100, span=200, height=200
        # velocity_cm_s_from_y(50) = 100 - (50/200)*200 = 50 → positive → "up"
        # velocity_cm_s_from_y(150) = 100 - (150/200)*200 = -50 → negative → "down"
        assert overlay.handle_click(300.0, 50.0) is True
        assert overlay._autovti_direction == "up"
        overlay._clear_autovti_region()
        overlay.set_tool_mode("autovti_region")
        assert overlay.handle_click(300.0, 150.0) is True
        assert overlay._autovti_direction == "down"

    def test_second_click_emits_signal(self, overlay, mock_plot):
        overlay.set_axis_mapping(_vessel_mapping_with_time())
        overlay.set_trace_label("VTI")
        overlay.set_tool_mode("autovti_region")
        baseline_y = overlay._baseline_plot_y_px()
        overlay.handle_click(300.0, baseline_y - 50)

        received = []
        overlay.autovti_region_selected.connect(lambda s, e, d: received.append((s, e, d)))
        overlay.handle_click(700.0, baseline_y - 50)

        assert len(received) == 1
        start_ms, end_ms, direction = received[0]
        assert start_ms < end_ms
        assert direction == "up"
        # Clear is deferred via QTimer.singleShot — process events first
        from PySide6.QtWidgets import QApplication

        QApplication.instance().processEvents()
        assert overlay._autovti_start_ms is None
        assert overlay._autovti_region_item is None

    def test_cancels_via_clear_partial_state(self, overlay, mock_plot):
        overlay.set_axis_mapping(_vessel_mapping_with_time())
        overlay.set_trace_label("VTI")
        overlay.set_tool_mode("autovti_region")
        baseline_y = overlay._baseline_plot_y_px()
        overlay.handle_click(300.0, baseline_y - 50)
        assert overlay._autovti_start_ms is not None
        overlay.cancel_active_tool()
        assert overlay._autovti_start_ms is None
        assert overlay._autovti_region_item is None
        assert overlay._tool_mode == "none"

    def test_second_click_creates_and_clears_band(self, overlay, mock_plot):
        overlay.set_axis_mapping(_vessel_mapping_with_time())
        overlay.set_trace_label("VTI")
        overlay.set_tool_mode("autovti_region")
        baseline_y = overlay._baseline_plot_y_px()
        overlay.handle_click(300.0, baseline_y - 50)

        added_items = []
        original_add = mock_plot.addItem

        def track_add(item):
            added_items.append(item)
            original_add(item)

        mock_plot.addItem = track_add

        received = []
        overlay.autovti_region_selected.connect(lambda s, e, d: received.append((s, e, d)))
        overlay.handle_click(700.0, baseline_y - 50)

        assert len(received) == 1
        # Clear is deferred via QTimer.singleShot — process events first
        from PySide6.QtWidgets import QApplication

        QApplication.instance().processEvents()
        assert overlay._autovti_start_ms is None
        assert overlay._autovti_region_item is None
        assert overlay._autovti_band_item is None


class TestAveragedVessel:
    def test_averages_psv_edv_across_cycles(self, overlay, mock_plot):
        from echo_personal_tool.domain.services.cardiac_cycle_service import CardiacCycle

        overlay.set_axis_mapping(_vessel_mapping_with_time())
        envelope = (
            (100.0, 70.0),
            (200.0, 40.0),
            (300.0, 30.0),
            (400.0, 55.0),
            (500.0, 65.0),
            (600.0, 35.0),
            (700.0, 25.0),
            (800.0, 50.0),
            (900.0, 60.0),
            (1000.0, 70.0),
        )
        cycle1 = CardiacCycle(0.0, 1000.0, 0.0, 0.0, 1000.0, "ecg", 0.9)
        cycle2 = CardiacCycle(1000.0, 2000.0, 1000.0, 1000.0, 2000.0, "ecg", 0.9)
        result = overlay.apply_averaged_vessel(envelope, cycles=(cycle1, cycle2))
        assert result is not None
        psv, edv = result
        assert psv == pytest.approx(72.5)
        assert edv == pytest.approx(32.5)
        assert overlay.vessel_cycle_source() == "ecg"
        assert overlay.vessel_averaged_cycles() == 2
        assert overlay.vessel_status() == "done"
        assert overlay._vessel_cycle_selection is True
        assert len(overlay._vessel_cycles) == 2

    def test_requires_cycles(self, overlay, mock_plot):
        overlay.set_axis_mapping(_vessel_mapping())
        assert overlay.apply_averaged_vessel(((100.0, 50.0), (200.0, 60.0))) is None
        assert overlay.vessel_averaged_cycles() == 1

    def test_empty_returns_none(self, overlay, mock_plot):
        overlay.set_axis_mapping(_vessel_mapping())
        assert overlay.apply_averaged_vessel(()) is None

    def test_clear_vessel_resets_averaged_cycles(self, overlay, mock_plot):
        from echo_personal_tool.domain.services.cardiac_cycle_service import CardiacCycle

        overlay.set_axis_mapping(_vessel_mapping_with_time())
        envelope = ((100.0, 70.0), (300.0, 30.0), (500.0, 65.0), (700.0, 25.0), (900.0, 60.0))
        cycle = CardiacCycle(0.0, 1000.0, 0.0, 0.0, 1000.0, "ecg", 0.9)
        overlay.apply_averaged_vessel(envelope, cycles=(cycle,))
        assert overlay.vessel_averaged_cycles() == 1
        overlay.clear_vessel()
        assert overlay.vessel_averaged_cycles() == 1


class TestAveragedVesselMedian:
    def _artifact_envelope(self):
        # velocities = 100 - y; cycle2 PSV is an artifact spike (y=0 -> 100 cm/s)
        return (
            (100.0, 50.0),
            (200.0, 50.0),
            (300.0, 10.0),
            (400.0, 50.0),
            (500.0, 90.0),
            (600.0, 50.0),
            (700.0, 50.0),
            (800.0, 0.0),
            (900.0, 50.0),
            (1000.0, 90.0),
            (1100.0, 50.0),
            (1200.0, 50.0),
            (1300.0, 10.0),
            (1400.0, 50.0),
            (1500.0, 90.0),
        )

    def _three_cycles(self):
        from echo_personal_tool.domain.services.cardiac_cycle_service import CardiacCycle

        return (
            CardiacCycle(0.0, 1000.0, 0.0, 0.0, 1000.0, "ecg", 0.9),
            CardiacCycle(1000.0, 2000.0, 1000.0, 1000.0, 2000.0, "ecg", 0.9),
            CardiacCycle(2000.0, 3000.0, 2000.0, 2000.0, 3000.0, "ecg", 0.9),
        )

    def test_median_ignores_artifact_cycle(self, overlay, mock_plot):
        overlay.set_axis_mapping(_vessel_mapping_with_time())
        result = overlay.apply_averaged_vessel(self._artifact_envelope(), cycles=self._three_cycles())
        assert result is not None
        psv, edv = result
        # mean would be (90 + 100 + 90)/3 = 93.3; median stays 90
        assert psv == pytest.approx(90.0)
        assert edv == pytest.approx(10.0)

    def test_stores_cycles_and_candidates(self, overlay, mock_plot):
        overlay.set_axis_mapping(_vessel_mapping_with_time())
        overlay.apply_averaged_vessel(self._artifact_envelope(), cycles=self._three_cycles())
        assert len(overlay._vessel_cycles) == 3
        assert overlay._vessel_cycle_index == 0
        assert overlay._vessel_cycle_selection is True
        # cycle 1 artifact candidate at t=1600, 100 cm/s
        assert overlay._vessel_cycle_psv_candidates[1] == (1600.0, 100.0)

    def test_envelope_cycles_set_envelope_source(self, overlay, mock_plot):
        from echo_personal_tool.domain.services.cardiac_cycle_service import CardiacCycle

        overlay.set_axis_mapping(_vessel_mapping_with_time())
        envelope = (
            (100.0, 70.0),
            (200.0, 40.0),
            (300.0, 30.0),
            (400.0, 55.0),
            (500.0, 65.0),
            (600.0, 35.0),
            (700.0, 25.0),
            (800.0, 50.0),
            (900.0, 60.0),
            (1000.0, 70.0),
        )
        cycle = CardiacCycle(0.0, 2000.0, 0.0, 0.0, 2000.0, "envelope", 1.0)
        overlay.apply_averaged_vessel(envelope, cycles=(cycle,))
        assert overlay.vessel_cycle_source() == "envelope"


def _vessel_mapping_with_time():
    from echo_personal_tool.domain.models.doppler_axis import DopplerAxisMapping
    from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi

    roi = DopplerSpectrogramRoi(x0=0.0, y0=0.0, width=1000.0, height=200.0)
    return DopplerAxisMapping(
        roi=roi,
        baseline_y_px=100.0,
        velocity_span_cm_s=200.0,
        velocity_min_cm_s=-100.0,
        velocity_max_cm_s=100.0,
        plot_width=1000.0,
        plot_height=200.0,
        time_span_ms=2000.0,
    )


def _vessel_mapping():
    from echo_personal_tool.domain.models.doppler_axis import DopplerAxisMapping
    from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi

    roi = DopplerSpectrogramRoi(x0=0.0, y0=0.0, width=1000.0, height=200.0)
    return DopplerAxisMapping(
        roi=roi,
        baseline_y_px=100.0,
        velocity_span_cm_s=200.0,
        velocity_min_cm_s=-100.0,
        velocity_max_cm_s=100.0,
        plot_width=1000.0,
        plot_height=200.0,
    )


class TestVesselCycleCorrection:
    def _averaged(self, overlay, mock_plot):
        overlay.set_axis_mapping(_vessel_mapping_with_time())
        envelope = (
            (100.0, 70.0),
            (200.0, 40.0),
            (300.0, 30.0),
            (400.0, 55.0),
            (500.0, 65.0),
            (600.0, 35.0),
            (700.0, 25.0),
            (800.0, 50.0),
            (900.0, 60.0),
            (1000.0, 70.0),
        )
        from echo_personal_tool.domain.services.cardiac_cycle_service import CardiacCycle

        cycles = (
            CardiacCycle(0.0, 1000.0, 0.0, 0.0, 1000.0, "envelope", 1.0),
            CardiacCycle(1000.0, 2000.0, 1000.0, 1000.0, 2000.0, "envelope", 1.0),
        )
        overlay.apply_averaged_vessel(envelope, cycles=cycles)
        return envelope

    def test_draws_band_on_selected_cycle(self, overlay, mock_plot):
        self._averaged(overlay, mock_plot)
        assert overlay._vessel_cycle_band is not None
        assert overlay._vessel_cycle_band in mock_plot.items
        assert overlay._vessel_cycle_text is not None

    def test_arrow_moves_index_and_redraws(self, overlay, mock_plot):
        self._averaged(overlay, mock_plot)
        assert overlay.vessel_cycle_index() == 0
        assert overlay.move_vessel_cycle(1) is True
        assert overlay.vessel_cycle_index() == 1
        assert overlay.vessel_cycle_candidate() == pytest.approx(75.0)

    def test_arrow_wraps_around(self, overlay, mock_plot):
        self._averaged(overlay, mock_plot)
        overlay.move_vessel_cycle(-1)
        assert overlay.vessel_cycle_index() == 1

    def test_assign_applies_candidate_and_exits(self, overlay, mock_plot):
        self._averaged(overlay, mock_plot)
        overlay.move_vessel_cycle(1)
        assert overlay.assign_vessel_cycle_psv() is True
        assert overlay.vessel_cycle_selection_active() is False
        psv, edv = overlay.get_vessel_values()
        assert psv == pytest.approx(75.0)
        assert edv == pytest.approx(32.5)
        assert overlay.vessel_status() == "done"

    def test_cancel_keeps_median_psv(self, overlay, mock_plot):
        self._averaged(overlay, mock_plot)
        median_psv, _ = overlay.get_vessel_values()
        overlay.move_vessel_cycle(1)
        assert overlay.cancel_vessel_cycle_selection() is True
        psv, _ = overlay.get_vessel_values()
        assert psv == pytest.approx(median_psv)
        assert overlay._vessel_cycle_band is None

    def test_candidate_none_when_inactive(self, overlay, mock_plot):
        overlay.set_axis_mapping(_vessel_mapping())
        assert overlay.vessel_cycle_candidate() is None

    def test_selection_active_requires_candidates(self, overlay, mock_plot):
        overlay.set_axis_mapping(_vessel_mapping())
        overlay._vessel_cycle_selection = True
        assert overlay.vessel_cycle_selection_active() is False

    def test_auto_trace_clears_selection_state(self, overlay, mock_plot):
        envelope = self._averaged(overlay, mock_plot)
        assert overlay.vessel_cycle_selection_active() is True
        assert overlay._vessel_cycle_band is not None
        overlay.apply_auto_trace(envelope)
        assert overlay.vessel_cycle_selection_active() is False
        assert overlay._vessel_cycles == ()
        assert overlay._vessel_cycle_psv_candidates == ()
        assert overlay._vessel_cycle_band is None
        overlay._redraw_vessel_graphics()
        assert overlay._vessel_cycle_band is None

    def test_failed_reapply_clears_selection(self, overlay, mock_plot):
        self._averaged(overlay, mock_plot)
        assert overlay.vessel_cycle_selection_active() is True
        assert overlay._vessel_cycle_band is not None
        assert overlay.apply_averaged_vessel(()) is None
        assert overlay.vessel_cycle_selection_active() is False
        assert overlay.vessel_cycle_count() == 0
        assert overlay._vessel_cycle_band is None

    def test_auto_trace_short_envelope_clears_selection(self, overlay, mock_plot):
        self._averaged(overlay, mock_plot)
        assert overlay.vessel_cycle_selection_active() is True
        assert overlay._vessel_cycle_band is not None
        assert overlay.apply_auto_trace(((100.0, 70.0),)) is None
        assert overlay.vessel_cycle_selection_active() is False
        assert overlay._vessel_cycle_band is None

    def test_clear_vessel_resets_selection(self, overlay, mock_plot):
        self._averaged(overlay, mock_plot)
        overlay.clear_vessel()
        assert overlay.vessel_cycle_selection_active() is False
        assert overlay.vessel_cycle_count() == 0
        assert overlay._vessel_cycle_band is None


class TestAutovtiRegionEndToEnd:
    """End-to-end test for the autovti_region two-click flow."""

    def test_full_flow_completes_trace(self, overlay, mock_plot):
        """Two clicks -> signal -> trace committed."""
        overlay.set_axis_mapping(_vessel_mapping_with_time())
        overlay.set_trace_label("VTI")
        overlay.set_tool_mode("autovti_region")

        # First click
        baseline_y = overlay._baseline_plot_y_px()
        assert overlay.handle_click(300.0, baseline_y - 50) is True
        assert overlay._autovti_start_ms is not None
        assert overlay._autovti_direction == "up"

        # Second click emits signal
        received = []
        overlay.autovti_region_selected.connect(lambda s, e, d: received.append((s, e, d)))
        assert overlay.handle_click(700.0, baseline_y - 50) is True

        assert len(received) == 1
        start_ms, end_ms, direction = received[0]
        assert start_ms < end_ms
        assert direction == "up"
        # Clear is deferred via QTimer.singleShot — process events first
        from PySide6.QtWidgets import QApplication

        QApplication.instance().processEvents()
        assert overlay._autovti_start_ms is None
        assert overlay._tool_mode == "none"

    def test_direction_determined_from_first_click(self, overlay, mock_plot):
        """Direction comes from first click's velocity sign."""
        overlay.set_axis_mapping(_vessel_mapping_with_time())
        overlay.set_trace_label("VTI")
        overlay.set_tool_mode("autovti_region")

        baseline_y = overlay._baseline_plot_y_px()
        # Click below baseline -> velocity negative -> "down"
        overlay.handle_click(300.0, baseline_y + 50)
        assert overlay._autovti_direction == "down"

        received = []
        overlay.autovti_region_selected.connect(lambda s, e, d: received.append((s, e, d)))
        overlay.handle_click(700.0, baseline_y + 50)
        assert received[0][2] == "down"

    def test_end_before_start_swapped(self, overlay, mock_plot):
        """When second click is before first, start/end are swapped."""
        overlay.set_axis_mapping(_vessel_mapping_with_time())
        overlay.set_trace_label("VTI")
        overlay.set_tool_mode("autovti_region")

        baseline_y = overlay._baseline_plot_y_px()
        overlay.handle_click(700.0, baseline_y - 50)  # start at 700

        received = []
        overlay.autovti_region_selected.connect(lambda s, e, d: received.append((s, e, d)))
        overlay.handle_click(300.0, baseline_y - 50)  # end at 300 < start

        assert received[0][0] < received[0][1]  # swapped

    def test_cancel_between_clicks_resets(self, overlay, mock_plot):
        """Cancelling after first click resets state."""
        overlay.set_axis_mapping(_vessel_mapping_with_time())
        overlay.set_trace_label("VTI")
        overlay.set_tool_mode("autovti_region")

        baseline_y = overlay._baseline_plot_y_px()
        overlay.handle_click(300.0, baseline_y - 50)
        assert overlay._autovti_start_ms is not None

        overlay.cancel_active_tool()
        assert overlay._autovti_start_ms is None
        assert overlay._tool_mode == "none"

        # Re-enter autovti_region mode and second click should start new region
        overlay.set_tool_mode("autovti_region")
        assert overlay.handle_click(700.0, baseline_y - 50) is True
        assert overlay._autovti_start_ms is not None  # new start, not emission
