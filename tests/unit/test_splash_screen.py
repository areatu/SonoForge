"""Tests for the AnythingLLM-style startup splash screen."""

from __future__ import annotations

import pytest

from echo_personal_tool.presentation import splash as splash_mod
from echo_personal_tool.presentation.splash import SplashScreen

pytestmark = pytest.mark.gui

STAGES = ("Starting SonoForge…", "Initializing modules…", "Preparing workspace…", "Ready")


def _make_splash(qtbot, **kwargs) -> SplashScreen:
    splash = SplashScreen(
        stages=STAGES,
        tagline="Echocardiography analysis platform",
        theme_mode=kwargs.pop("theme_mode", "dark"),
        reduce_motion=kwargs.pop("reduce_motion", False),
        **kwargs,
    )
    qtbot.addWidget(splash)
    return splash


def _fast_timings(monkeypatch) -> None:
    """Shrink splash timing constants so tests finish quickly."""
    monkeypatch.setattr(splash_mod, "STAGE_INTERVAL_MS", 40)
    monkeypatch.setattr(splash_mod, "MIN_VISIBLE_MS", 200)
    monkeypatch.setattr(splash_mod, "FADE_OUT_MS", 40)


class TestSplashStructure:
    def test_is_frameless_and_always_on_top(self, qtbot) -> None:
        from PySide6.QtCore import Qt

        splash = _make_splash(qtbot)
        flags = splash.windowFlags()
        assert flags & Qt.WindowType.FramelessWindowHint
        assert flags & Qt.WindowType.WindowStaysOnTopHint

    def test_fixed_size_and_initial_status(self, qtbot) -> None:
        splash = _make_splash(qtbot)
        assert splash.minimumSize() == splash.maximumSize()
        assert splash.width() == splash_mod.WINDOW_W
        # first stage text is shown immediately
        assert splash._status_label.text() == STAGES[0]

    def test_has_spinner_and_pulse_dot(self, qtbot) -> None:
        splash = _make_splash(qtbot)
        assert splash._spinner is not None
        assert splash._pulse_dot is not None

    def test_logo_file_resolves(self, qtbot) -> None:
        from echo_personal_tool.presentation.splash import _logo_path_for

        path = _logo_path_for("dark")
        assert path.exists()
        assert path.name == "logo_dark.png"
        assert _logo_path_for("light").name == "logo.png"


class TestSplashTimeline:
    def test_stages_advance_automatically(self, qtbot, monkeypatch) -> None:
        _fast_timings(monkeypatch)
        splash = _make_splash(qtbot)
        splash.show_and_play()

        def _advanced() -> bool:
            return splash._status_label.text() == STAGES[1]

        qtbot.waitUntil(_advanced, timeout=3000)

    def test_complete_reveals_window_then_closes(self, qtbot, monkeypatch) -> None:
        from PySide6.QtWidgets import QWidget

        _fast_timings(monkeypatch)
        splash = _make_splash(qtbot)
        dummy = QWidget()
        qtbot.addWidget(dummy)
        revealed: list[QWidget] = []
        splash.show_and_play()
        splash.complete_with(dummy, on_complete=lambda win: (win.show(), revealed.append(win)))
        qtbot.waitUntil(lambda: len(revealed) == 1, timeout=3000)
        qtbot.waitUntil(lambda: not splash.isVisible(), timeout=3000)
        assert revealed[0] is dummy

    def test_reduce_motion_skips_animations(self, qtbot, monkeypatch) -> None:
        from PySide6.QtWidgets import QWidget

        monkeypatch.setattr(splash_mod, "MIN_VISIBLE_MS", 200)
        splash = _make_splash(qtbot, reduce_motion=True)
        dummy = QWidget()
        qtbot.addWidget(dummy)
        splash.show_and_play()
        # no spinner / pulse animations running
        assert splash._spinner._anim is None
        assert splash._pulse_dot._anim is None
        revealed: list[QWidget] = []
        splash.complete_with(dummy, on_complete=lambda win: revealed.append(win))
        qtbot.waitUntil(lambda: len(revealed) == 1, timeout=3000)


class TestSplashSwitch:
    def test_enabled_by_default(self, monkeypatch) -> None:
        monkeypatch.delenv("ECHO_NO_SPLASH", raising=False)
        assert splash_mod.is_splash_enabled()

    def test_disabled_via_env(self, monkeypatch) -> None:
        monkeypatch.setenv("ECHO_NO_SPLASH", "1")
        assert not splash_mod.is_splash_enabled()
