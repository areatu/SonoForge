from unittest.mock import MagicMock, patch

import numpy as np
import pytest

pytestmark = pytest.mark.gui

from PySide6.QtCore import Qt

from echo_personal_tool.domain.models.doppler_roi import (
    DopplerKind,
    DopplerSpectrogramRoi,
)
from echo_personal_tool.presentation.viewer_widget import ViewerWidget


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
    frame[int(roi.y0) : int(roi.y0 + roi.height), int(roi.x0) : int(roi.x1)] = 30
    for ty in (80, 160, 240, 320):
        frame[ty, 600:610] = 220
    return frame, roi


def test_baseline_click_auto_suggests_span_not_applied(qtbot, monkeypatch):
    """Auto-calibration after a baseline click is only a suggestion.

    Manual calibration takes priority: the detected span must NOT be applied
    silently; the manual 2-click flow starts and the span becomes the dialog
    default."""
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
    # Calibration state is NOT auto-applied...
    assert widget._doppler_calibration_state is None
    assert widget._doppler_pending_auto_velocity_span == 200.0
    # ...the manual 2-click flow is active and will prompt for the span.
    assert widget._doppler_cal_step is None
    assert widget._calibration_active is True


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
    # Fallback should set _doppler_pending_roi so grid-line snapping works
    assert widget._doppler_pending_roi is not None


def test_baseline_click_no_frame_returns_false(qtbot):
    """When no frame is available, the method returns False."""
    widget = ViewerWidget()
    widget._doppler_cal_step = "baseline"
    ev = _MockMouseEvent(button=Qt.MouseButton.LeftButton)
    handled = widget._handle_doppler_calibration_click(ev)
    assert handled is False


def test_baseline_click_suggestion_becomes_dialog_default(qtbot, monkeypatch):
    """The auto-detected span pre-fills the manual span dialog."""
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
    assert widget._doppler_pending_auto_velocity_span == 200.0

    captured: dict[str, float] = {}

    def fake_getdouble(parent, title, label, value, min_val, max_val, decimals):
        captured["value"] = value
        return (200.0, True)

    with patch(
        "echo_personal_tool.presentation.viewer_widget.QInputDialog.getDouble",
        side_effect=fake_getdouble,
    ):
        widget._prompt_spectral_velocity_span(64.0)

    assert captured["value"] == 200.0
    assert widget._doppler_calibration_state is not None
    assert widget._doppler_calibration_state.has_velocity_scale()


def test_snapping_uses_doppler_grid_lines(qtbot):
    """During Doppler velocity calibration, mouse-move snapping uses
    _doppler_grid_line_positions (not depth tick positions)."""
    widget = ViewerWidget()
    qtbot.addWidget(widget)
    frame = np.zeros((400, 640, 3), dtype=np.uint8)
    widget._current_frame = frame
    widget._calibration_active = True
    widget._calibration_kind = "doppler_velocity"
    widget._calibration_start_y = None
    widget._doppler_grid_line_positions = [100.0, 200.0, 300.0]
    widget._depth_tick_y_positions = []

    snapped = []
    widget._update_calibration_preview = lambda a, b: snapped.append(b)
    widget._update_calibration_horizontal_guides = lambda y: None

    widget._view = MagicMock()
    widget._view.mapSceneToView = MagicMock(return_value=MagicMock(y=lambda: 103.0, x=lambda: 0.0))
    widget._update_measurement_crosshair = MagicMock()

    from PySide6.QtCore import QPointF

    widget._on_scene_mouse_moved(QPointF(0, 0))

    assert len(snapped) == 1
    assert snapped[0] == 100.0  # snapped to nearest grid line at y=100
