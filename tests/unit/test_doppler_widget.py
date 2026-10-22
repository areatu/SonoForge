"""Unit tests for the Doppler widget."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
from PySide6.QtCore import Qt

from echo_personal_tool.domain.models import (
    DopplerIntervalMarker,
    DopplerMeasurementDTO,
    DopplerPeakMarker,
    DopplerTrace,
)
from echo_personal_tool.domain.models.doppler_roi import DopplerCalibrationState, DopplerSpectrogramRoi
from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.presentation.doppler_calibration_hint import DOPPLER_MANUAL_CALIBRATION_HINT_KEY
from echo_personal_tool.presentation.doppler_widget import DopplerWidget

pytestmark = pytest.mark.gui


def _without_measurement_ids(dto: DopplerMeasurementDTO) -> DopplerMeasurementDTO:
    """Compare marker values while ignoring the per-measurement identity (D-23)."""
    return DopplerMeasurementDTO(
        peaks=tuple(replace(marker, measurement_id="") for marker in dto.peaks),
        intervals=tuple(replace(marker, measurement_id="") for marker in dto.intervals),
        traces=tuple(replace(trace, measurement_id="") for trace in dto.traces),
    )


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
    dto = widget.get_measurement_dto()
    assert _without_measurement_ids(dto) == expected
    assert _without_measurement_ids(blocker.args[0]) == expected
    # Every new measurement carries an identity so repeats can coexist (D-23).
    assert dto.peaks[0].measurement_id
    assert widget._status_label.text() == "Tool: Peak marker (M) | Click peak (label: A)"


def test_interval_marker_two_click_flow_emits_updated_measurement(qtbot) -> None:
    widget = DopplerWidget()
    qtbot.addWidget(widget)
    widget.set_tool_mode("interval")

    assert widget._handle_plot_click(150.0, 0.0) is True
    assert widget._active_interval_start == 150.0
    assert widget._status_label.text() == ("Tool: Interval marker (T) | Click interval end (label: DT)")

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
    dto = widget.get_measurement_dto()
    assert _without_measurement_ids(dto) == expected
    assert _without_measurement_ids(blocker.args[0]) == expected
    assert dto.intervals[0].measurement_id
    assert len(widget._interval_items) == 1
    assert widget._status_label.text() == ("Tool: Interval marker (T) | Click interval start (label: IVRT)")


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
    dto = widget.get_measurement_dto()
    assert _without_measurement_ids(dto) == expected
    assert _without_measurement_ids(blocker.args[0]) == expected
    assert dto.traces[0].measurement_id
    assert widget._active_partial_points == []
    assert len(widget._trace_items) == 1
    assert widget._status_label.text() == ("Tool: VTI trace (V) | Click points, double-click to finish")


def _velocity_missing_state() -> DopplerCalibrationState:
    return DopplerCalibrationState(
        roi=DopplerSpectrogramRoi(x0=0.0, y0=0.0, width=400.0, height=160.0),
        baseline_y_px=80.0,
        velocity_span_cm_s=0.0,
        time_span_ms=1000.0,
    )


def test_manual_calibration_hint_follows_velocity_scale(qtbot) -> None:
    widget = DopplerWidget()
    qtbot.addWidget(widget)
    widget.resize(640, 420)
    widget.show()
    qtbot.waitExposed(widget)

    missing = _velocity_missing_state()
    assert not missing.has_velocity_scale()
    widget.set_calibration_state(missing)
    assert widget.manual_calibration_hint_visible()
    hint = widget._manual_calibration_hint
    assert hint.text() == tr(DOPPLER_MANUAL_CALIBRATION_HINT_KEY)
    assert hint.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    # Centered on the spectrogram viewport (the ROI of this standalone plot).
    viewport = widget._plot.viewport()
    assert viewport.rect().contains(hint.geometry().center())

    calibrated = replace(missing, velocity_span_cm_s=200.0)
    assert calibrated.is_complete()
    widget.set_calibration_state(calibrated)
    assert not widget.manual_calibration_hint_visible()


def test_manual_calibration_hint_hides_while_calibration_is_active(qtbot) -> None:
    widget = DopplerWidget()
    qtbot.addWidget(widget)
    widget.resize(640, 420)
    widget.show()
    qtbot.waitExposed(widget)

    widget.set_calibration_state(_velocity_missing_state())
    assert widget.manual_calibration_hint_visible()

    widget.set_calibration_active(True)
    assert not widget.manual_calibration_hint_visible()

    widget.set_calibration_active(False)
    assert widget.manual_calibration_hint_visible()


def test_manual_calibration_hint_click_reaches_the_plot(qtbot) -> None:
    from PySide6.QtCore import QEvent, QObject, QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    widget = DopplerWidget()
    qtbot.addWidget(widget)
    widget.resize(640, 420)
    widget.show()
    qtbot.waitExposed(widget)
    widget.set_calibration_state(_velocity_missing_state())
    hint = widget._manual_calibration_hint
    assert hint.isVisible()
    assert hint.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    received: list[object] = []
    viewport = widget._plot.viewport()

    class _Filter(QObject):
        def eventFilter(self, obj, event) -> bool:  # noqa: N802
            if obj is viewport and event.type() == QEvent.Type.MouseButtonPress:
                received.append(obj)
            return False

    filt = _Filter(viewport)
    viewport.installEventFilter(filt)
    # Press in viewport coordinates at the hint center. The window system
    # delivers that to the widget underneath a transparent-for-mouse label.
    local = viewport.mapFromGlobal(hint.mapToGlobal(hint.rect().center()))
    event = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(local),
        viewport.mapToGlobal(local),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    assert QApplication.sendEvent(viewport, event) is True
    assert viewport in received
    # A press aimed at the label is not consumed by the label itself.
    hint_event = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(hint.rect().center()),
        hint.mapToGlobal(hint.rect().center()),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    assert hint.event(hint_event) is False
    assert not hint_event.isAccepted()
