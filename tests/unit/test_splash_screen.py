"""Tests for the splash concept 4 / 4.1 (logo fill, percent, module status)."""

from __future__ import annotations

import pytest

from echo_personal_tool.presentation import splash as splash_mod
from echo_personal_tool.presentation.splash import SplashScreen

pytestmark = pytest.mark.gui


def _make_splash(qtbot, **kwargs) -> SplashScreen:
    splash = SplashScreen(
        reduce_motion=kwargs.pop("reduce_motion", False),
        compact=kwargs.pop("compact", False),
        **kwargs,
    )
    qtbot.addWidget(splash)
    return splash


def _fast_timings(monkeypatch) -> None:
    """Shrink splash timing constants so tests finish quickly."""
    monkeypatch.setattr(splash_mod, "MIN_VISIBLE_MS", 200)
    monkeypatch.setattr(splash_mod, "FADE_OUT_MS", 40)
    monkeypatch.setattr(splash_mod, "AUTO_STEP_MS", 50)


class TestSplashStructure:
    def test_is_frameless_and_always_on_top(self, qtbot) -> None:
        from PySide6.QtCore import Qt

        splash = _make_splash(qtbot)
        flags = splash.windowFlags()
        assert flags & Qt.WindowType.FramelessWindowHint
        assert flags & Qt.WindowType.WindowStaysOnTopHint

    def test_fullscreen_covers_screen(self, qtbot) -> None:
        from PySide6.QtWidgets import QApplication

        splash = _make_splash(qtbot)
        splash.show_and_play()
        screen = QApplication.primaryScreen()
        assert screen is not None
        assert splash.geometry() == screen.geometry()
        splash._close_splash()

    def test_compact_is_small_and_centered(self, qtbot) -> None:
        from PySide6.QtWidgets import QApplication

        splash = _make_splash(qtbot, compact=True)
        splash.show_and_play()
        screen = QApplication.primaryScreen()
        assert screen is not None
        assert splash.width() < screen.geometry().width()
        assert splash.height() < screen.geometry().height()
        sc = screen.availableGeometry().center()
        assert abs(splash.geometry().center().x() - sc.x()) <= 4
        assert abs(splash.geometry().center().y() - sc.y()) <= 4
        splash._close_splash()

    def test_has_logo_fill_and_percent(self, qtbot) -> None:
        splash = _make_splash(qtbot)
        assert not splash._fill._pm.isNull()
        assert splash._fill.width() > 0
        assert splash._percent_label.text() == "0%"

    def test_has_module_label(self, qtbot) -> None:
        splash = _make_splash(qtbot)
        assert splash._module_label is not None
        assert splash._module_label.isVisible()

    def test_percent_font_is_large(self, qtbot) -> None:
        splash = _make_splash(qtbot)
        assert splash._percent_label.font().pointSize() >= 28


class TestSplashProgress:
    def test_logo_fill_rises_with_progress(self, qtbot) -> None:
        splash = _make_splash(qtbot)
        assert splash._fill._progress == 0.0
        splash.set_progress(50)

        def _half() -> bool:
            return splash._fill._progress >= 49.9

        qtbot.waitUntil(_half, timeout=2500)
        assert splash._fill._progress == pytest.approx(50.0, abs=1.0)
        assert splash._percent_label.text() == "50%"
        splash.set_progress(100)

        def _full() -> bool:
            return splash._fill._progress > 99.9

        qtbot.waitUntil(_full, timeout=2500)
        splash._close_splash()

    def test_module_label_updates(self, qtbot) -> None:
        splash = _make_splash(qtbot)
        splash.show_and_play()

        def _has_text() -> bool:
            return splash._module_label.text() != ""

        qtbot.waitUntil(_has_text, timeout=3000)
        assert "..." in splash._module_label.text()
        splash._close_splash()


class TestSplashTimeline:
    def test_progress_advances_automatically(self, qtbot, monkeypatch) -> None:
        _fast_timings(monkeypatch)
        splash = _make_splash(qtbot)
        splash.show_and_play()

        def _advanced() -> bool:
            return splash._percent > 0

        qtbot.waitUntil(_advanced, timeout=3000)
        assert splash._percent_label.text() != "0%"
        splash._close_splash()

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
        qtbot.wait(100)
        try:
            assert not splash.isVisible()
        except RuntimeError:
            pass  # C++ object already deleted by deleteLater()
        assert revealed[0] is dummy

    def test_reduce_motion_sets_clarity_immediately(self, qtbot, monkeypatch) -> None:
        from PySide6.QtWidgets import QWidget

        monkeypatch.setattr(splash_mod, "MIN_VISIBLE_MS", 200)
        splash = _make_splash(qtbot, reduce_motion=True)
        dummy = QWidget()
        qtbot.addWidget(dummy)
        splash.show_and_play()
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
