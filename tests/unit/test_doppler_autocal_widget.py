import numpy as np
import pytest
from unittest.mock import MagicMock, patch

pytestmark = pytest.mark.gui

from echo_personal_tool.domain.models.doppler_roi import (
    DopplerKind,
    DopplerSpectrogramRoi,
)
from echo_personal_tool.presentation.viewer_widget import ViewerWidget
from PySide6.QtCore import Qt


class _MockMouseEvent:
    """Minimal mock of QMouseEvent with callable button() returning Qt enum."""

    def __init__(self, button=Qt.MouseButton.LeftButton, position=(320.0, 200.0)):
        self._button = button
        self._position = position
        self.buttons = 0
        self.modifiers = 0

    def button(self):
        return self._button

    def scenePos(self):
        return self._position


def _frame_with_ticks(height=400, width=640):
    frame = np.zeros((height, width), dtype=np.uint8)
    roi = DopplerSpectrogramRoi(x0=40, y0=0, width=540, height=height)
    frame[int(roi.y0):int(roi.y0 + roi.height), int(roi.x0):int(roi.x1)] = 30
    for ty in (80, 160, 240, 320):
        frame[ty, 600:610] = 220
    return frame, roi


def test_baseline_click_autocalibrates(qtbot, monkeypatch):
    """Auto-calibration after baseline click produces a calibrated state."""
    widget = ViewerWidget()
    qtbot.addWidget(widget)
    frame, roi = _frame_with_ticks()
    widget._current_frame = frame
    widget._doppler_pending_roi = roi
    widget._doppler_cal_step = "baseline"
    widget._doppler_cal_kind = DopplerKind.SPECTRAL

    widget._map_view_event = MagicMock(return_value=(320.0, 200.0))

    def mock_auto(frame, roi, baseline_y, kind):
        result = MagicMock()
        result.confidence = 0.95
        result.velocity_span_cm_s = 200.0
        return result

    # Patch the function in the module where it is imported (viewer_widget.py)
    with patch(
        "echo_personal_tool.presentation.viewer_widget.try_auto_doppler_velocity_calibration",
        side_effect=mock_auto,
    ):
        ev = _MockMouseEvent(button=Qt.MouseButton.LeftButton)
        handled = widget._handle_doppler_calibration_click(ev)

    assert handled is True
    assert widget._doppler_calibration_state is not None
    assert widget._doppler_calibration_state.has_velocity_scale()


def test_baseline_click_no_ticks_falls_back(qtbot, monkeypatch):
    """When no ticks are detected, auto-calibration returns None and the
    fallback 2-click flow is used."""
    widget = ViewerWidget()
    qtbot.addWidget(widget)
    frame = np.zeros((400, 640), dtype=np.uint8)
    widget._current_frame = frame
    widget._doppler_pending_roi = DopplerSpectrogramRoi(x0=40, y0=0, width=540, height=400)
    widget._doppler_cal_step = "baseline"
    widget._doppler_cal_kind = DopplerKind.SPECTRAL

    widget._map_view_event = MagicMock(return_value=(320.0, 200.0))

    def mock_auto(frame, roi, baseline_y, kind):
        return None

    # Patch the function in the module where it is imported (viewer_widget.py)
    with patch(
        "echo_personal_tool.presentation.viewer_widget.try_auto_doppler_velocity_calibration",
        side_effect=mock_auto,
    ):
        ev = _MockMouseEvent(button=Qt.MouseButton.LeftButton)
        handled = widget._handle_doppler_calibration_click(ev)

    assert handled is True
    assert widget._doppler_calibration_state is None


def test_baseline_click_no_frame_returns_false(qtbot):
    """When no frame is available, the method returns False."""
    widget = ViewerWidget()
    widget._doppler_cal_step = "baseline"
    ev = _MockMouseEvent(button=Qt.MouseButton.LeftButton)
    handled = widget._handle_doppler_calibration_click(ev)
    assert handled is False


def test_baseline_click_high_confidence_applies_calibration(qtbot, monkeypatch):
    """When auto-calibration returns high confidence, it is applied directly."""
    widget = ViewerWidget()
    qtbot.addWidget(widget)
    frame, roi = _frame_with_ticks()
    widget._current_frame = frame
    widget._doppler_pending_roi = roi
    widget._doppler_cal_step = "baseline"
    widget._doppler_cal_kind = DopplerKind.SPECTRAL

    widget._map_view_event = MagicMock(return_value=(320.0, 200.0))

    def mock_auto(frame, roi, baseline_y, kind):
        result = MagicMock()
        result.confidence = 0.95
        result.velocity_span_cm_s = 200.0
        return result

    # Patch the function in the module where it is imported (viewer_widget.py)
    with patch(
        "echo_personal_tool.presentation.viewer_widget.try_auto_doppler_velocity_calibration",
        side_effect=mock_auto,
    ):
        ev = _MockMouseEvent(button=Qt.MouseButton.LeftButton)
        handled = widget._handle_doppler_calibration_click(ev)

    assert handled is True
    assert widget._doppler_calibration_state is not None
    assert widget._doppler_calibration_state.velocity_span_cm_s == 200.0
