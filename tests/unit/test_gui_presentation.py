"""GUI presentation tests — all in one file to avoid multi-QApplication issues."""

from __future__ import annotations

import os
import sys

import pytest

# Ensure offscreen platform for Windows headless CI
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytestmark = pytest.mark.gui
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

pytest.importorskip("pytestqt")

from echo_personal_tool.presentation.calibration_snap import snap_y_to_nearest_tick
from echo_personal_tool.presentation.caliper_label_item import (
    compute_caliper_label_layout,
    readable_text_angle,
)
from echo_personal_tool.presentation.mmode_caliper import MModeCaliperTool
from echo_personal_tool.presentation.ui_animations import (
    HoverButtonMixin,
    _hex_to_rgb,
    _lerp_color,
    _rgb_to_hex,
    animate_widget_opacity,
    hide_dialog_animated,
    loading_button,
    set_button_loading,
)


@pytest.fixture(scope="session")
def qapp_session():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


# ── ui_animations ────────────────────────────────────────────────

class TestHexToRgb:
    def test_standard(self) -> None:
        assert _hex_to_rgb("#ff0000") == (255, 0, 0)
    def test_without_hash(self) -> None:
        assert _hex_to_rgb("00ff00") == (0, 255, 0)
    def test_short_returns_fallback(self) -> None:
        assert _hex_to_rgb("#abc") == (46, 64, 84)
    def test_empty(self) -> None:
        assert _hex_to_rgb("") == (46, 64, 84)

class TestRgbToHex:
    def test_basic(self) -> None:
        assert _rgb_to_hex(255, 128, 0) == "#ff8000"

class TestLerpColor:
    def test_midpoint(self) -> None:
        assert _lerp_color("#000000", "#ffffff", 0.5) == "#7f7f7f"
    def test_start(self) -> None:
        assert _lerp_color("#ff0000", "#0000ff", 0.0) == "#ff0000"
    def test_end(self) -> None:
        assert _lerp_color("#ff0000", "#0000ff", 1.0) == "#0000ff"

class TestHoverButtonMixin:
    def test_install(self, qapp_session) -> None:
        btn = QPushButton("test")
        m = HoverButtonMixin.install(btn)
        assert isinstance(m, HoverButtonMixin)
    def test_same_widget_same_instance(self, qapp_session) -> None:
        btn = QPushButton("test")
        assert HoverButtonMixin.install(btn) is HoverButtonMixin.install(btn)

class TestAnimateWidgetOpacity:
    def test_creates_animation(self, qapp_session) -> None:
        w = QWidget()
        anim = animate_widget_opacity(w, 0.0, 1.0, duration_ms=100)
        assert anim is not None

class TestLoadingButton:
    def test_restores_state(self, qapp_session) -> None:
        btn = QPushButton("Submit")
        with loading_button(btn, "Loading..."):
            assert btn.text() == "Loading..."
            assert btn.isEnabled() is False
        assert btn.text() == "Submit"
        assert btn.isEnabled() is True

class TestSetButtonLoading:
    def test_enable_disable(self, qapp_session) -> None:
        btn = QPushButton("OK")
        set_button_loading(btn, True, "Wait...")
        assert btn.text() == "Wait..."
        set_button_loading(btn, False)
        assert btn.text() == "OK"

class TestHideDialogAnimated:
    def test_calls_on_done(self, qapp_session) -> None:
        from PySide6.QtWidgets import QDialog
        called = []
        hide_dialog_animated(QDialog(), on_done=lambda: called.append(True))
        assert called == [True]

# ── mmode_caliper ────────────────────────────────────────────────

class TestMModeCaliper:
    def test_init(self, qapp_session) -> None:
        tool = MModeCaliperTool()
        assert tool.measurements == []
    def test_distance_caliper(self, qapp_session) -> None:
        tool = MModeCaliperTool(depth_mm_per_pixel=0.5)
        tool.start_distance_caliper()
        tool.on_click(10.0, 20.0)
        tool.on_click(10.0, 40.0)
        assert len(tool.measurements) == 1
        assert tool.measurements[0].value_mm == 10.0
    def test_time_caliper(self, qapp_session) -> None:
        tool = MModeCaliperTool(time_ms_per_pixel=2.0)
        tool.start_time_caliper()
        tool.on_click(10.0, 20.0)
        tool.on_click(50.0, 20.0)
        assert tool.measurements[0].value_ms == 80.0
    def test_clear(self, qapp_session) -> None:
        tool = MModeCaliperTool(depth_mm_per_pixel=0.5)
        tool.start_distance_caliper()
        tool.on_click(10.0, 20.0)
        tool.clear()
        assert tool.measurements == []
    def test_no_active_mode_click_ignored(self, qapp_session) -> None:
        tool = MModeCaliperTool()
        tool.on_click(10.0, 20.0)
        assert len(tool.measurements) == 0
    def test_signal(self, qapp_session) -> None:
        tool = MModeCaliperTool(depth_mm_per_pixel=1.0)
        received = []
        tool.measurement_added.connect(lambda m: received.append(m))
        tool.start_distance_caliper()
        tool.on_click(0.0, 0.0)
        tool.on_click(0.0, 10.0)
        assert len(received) == 1

# ── caliper_label_item ───────────────────────────────────────────

class TestReadableTextAngle:
    def test_zero(self) -> None:
        assert readable_text_angle(0.0) == 0.0
    def test_45(self) -> None:
        assert readable_text_angle(45.0) == 45.0
    def test_90_boundary(self) -> None:
        # 90 degrees is boundary — stays as 90 (not > 90)
        assert readable_text_angle(90.0) == 90.0
    def test_180(self) -> None:
        assert readable_text_angle(180.0) == 0.0
    def test_negative(self) -> None:
        assert readable_text_angle(-45.0) == -45.0

class TestComputeCaliperLabelLayout:
    def test_horizontal(self) -> None:
        layout = compute_caliper_label_layout((0, 50), (100, 50), vertical_labels=frozenset(), label="X")
        assert layout.anchor_x == 50.0
    def test_vertical(self) -> None:
        layout = compute_caliper_label_layout((50, 0), (50, 100), vertical_labels=frozenset(), label="X")
        assert layout.offset_x < 0

# ── calibration_snap ─────────────────────────────────────────────

class TestSnapY:
    def test_empty_ticks(self) -> None:
        assert snap_y_to_nearest_tick(50.0, []) == 50.0
    def test_snaps(self) -> None:
        assert snap_y_to_nearest_tick(22.0, [10, 20, 30, 40]) == 20.0
    def test_no_snap_far(self) -> None:
        assert snap_y_to_nearest_tick(25.0, [10, 20, 30, 40], radius_px=2.0) == 25.0
