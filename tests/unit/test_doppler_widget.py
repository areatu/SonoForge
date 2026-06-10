"""Unit tests for the Doppler widget."""

from __future__ import annotations

import numpy as np

from echo_personal_tool.domain.models import (
    DopplerIntervalMarker,
    DopplerMeasurementDTO,
    DopplerPeakMarker,
    DopplerTrace,
)
from echo_personal_tool.presentation.doppler_widget import DopplerWidget


def test_tool_mode_round_trip(qtbot) -> None:
    widget = DopplerWidget()
    qtbot.addWidget(widget)

    assert widget.get_tool_mode() == "none"

    widget.set_tool_mode("peak")
    assert widget.get_tool_mode() == "peak"

    widget.set_tool_mode("trace")
    assert widget.get_tool_mode() == "trace"


def test_get_measurement_dto_starts_empty(qtbot) -> None:
    widget = DopplerWidget()
    qtbot.addWidget(widget)

    assert widget.get_measurement_dto() == DopplerMeasurementDTO(
        peaks=(),
        intervals=(),
        traces=(),
    )


def test_cancel_active_tool_resets_mode(qtbot) -> None:
    widget = DopplerWidget()
    qtbot.addWidget(widget)

    widget.set_tool_mode("interval")
    widget._handle_plot_click(100.0, 0.0)

    assert widget.cancel_active_tool() is True
    assert widget.get_tool_mode() == "none"
    assert widget._active_interval_start is None
    assert widget.cancel_active_tool() is False


def test_show_spectrogram_accepts_grayscale_array(qtbot) -> None:
    widget = DopplerWidget()
    qtbot.addWidget(widget)

    pixels = np.arange(12, dtype=np.float32).reshape(3, 4)
    widget.show_spectrogram(pixels)

    assert widget._image_item.image is not None
    assert widget._image_item.image.shape == (3, 4)


def test_peak_marker_click_emits_updated_measurement(qtbot) -> None:
    widget = DopplerWidget()
    qtbot.addWidget(widget)
    widget.set_tool_mode("peak")

    with qtbot.waitSignal(widget.markers_changed, timeout=1000) as blocker:
        assert widget._handle_plot_click(120.0, 35.5) is True

    expected = DopplerMeasurementDTO(
        peaks=(DopplerPeakMarker(label="E", time_ms=120.0, velocity_cm_s=35.5),),
        intervals=(),
        traces=(),
    )
    assert widget.get_measurement_dto() == expected
    assert blocker.args == [expected]
    assert widget._status_label.text() == "Tool: Peak marker (M) | Click peak (label: A)"


def test_interval_marker_two_click_flow_emits_updated_measurement(qtbot) -> None:
    widget = DopplerWidget()
    qtbot.addWidget(widget)
    widget.set_tool_mode("interval")

    assert widget._handle_plot_click(150.0, 0.0) is True
    assert widget._active_interval_start == 150.0
    assert widget._status_label.text() == (
        "Tool: Interval marker (T) | Click interval end (label: DT)"
    )

    with qtbot.waitSignal(widget.markers_changed, timeout=1000) as blocker:
        assert widget._handle_plot_click(310.0, 0.0) is True

    expected = DopplerMeasurementDTO(
        peaks=(),
        intervals=(
            DopplerIntervalMarker(
                label="DT",
                start_time_ms=150.0,
                end_time_ms=310.0,
            ),
        ),
        traces=(),
    )
    assert widget.get_measurement_dto() == expected
    assert blocker.args == [expected]
    assert len(widget._interval_items) == 1
    assert widget._status_label.text() == (
        "Tool: Interval marker (T) | Click interval start (label: IVRT)"
    )


def test_clear_measurements_resets_markers_and_plot_items(qtbot) -> None:
    widget = DopplerWidget()
    qtbot.addWidget(widget)

    widget.set_tool_mode("peak")
    widget._handle_plot_click(120.0, 35.5)

    widget.set_tool_mode("interval")
    widget._handle_plot_click(150.0, 0.0)
    widget._handle_plot_click(310.0, 0.0)

    widget.set_tool_mode("trace")
    widget._handle_plot_click(10.0, 5.0)
    widget._handle_plot_click(25.0, 18.0)
    assert widget.finish_trace() is True

    dto = widget.get_measurement_dto()
    assert dto.peaks
    assert dto.intervals
    assert dto.traces
    assert len(widget._interval_items) == 1
    assert len(widget._trace_items) == 1

    with qtbot.assertNotEmitted(widget.markers_changed):
        widget.clear_measurements()

    assert widget.get_measurement_dto() == DopplerMeasurementDTO(
        peaks=(),
        intervals=(),
        traces=(),
    )
    assert widget._peak_markers == []
    assert widget._interval_markers == []
    assert widget._traces == []
    assert len(widget._interval_items) == 0
    assert len(widget._trace_items) == 0
    assert widget._active_partial_points == []
    assert widget._active_interval_start is None


def test_trace_clicks_and_finish_trace_emit_updated_measurement(qtbot) -> None:
    widget = DopplerWidget()
    qtbot.addWidget(widget)
    widget.set_tool_mode("trace")

    assert widget._handle_plot_click(10.0, 5.0) is True
    assert widget._handle_plot_click(25.0, 18.0) is True
    assert widget._handle_plot_click(50.0, 12.0) is True
    assert widget._active_partial_points == [(10.0, 5.0), (25.0, 18.0), (50.0, 12.0)]

    with qtbot.waitSignal(widget.markers_changed, timeout=1000) as blocker:
        assert widget.finish_trace() is True

    expected = DopplerMeasurementDTO(
        peaks=(),
        intervals=(),
        traces=(
            DopplerTrace(
                label="VTI",
                points=((10.0, 5.0), (25.0, 18.0), (50.0, 12.0)),
            ),
        ),
    )
    assert widget.get_measurement_dto() == expected
    assert blocker.args == [expected]
    assert widget._active_partial_points == []
    assert len(widget._trace_items) == 1
    assert widget._status_label.text() == (
        "Tool: VTI trace (V) | Click points, double-click to finish"
    )
