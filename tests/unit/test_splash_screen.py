"""Tests for the AnythingLLM 1.16-style fullscreen startup splash (v3)."""

from __future__ import annotations

import pytest

from echo_personal_tool.presentation import splash as splash_mod
from echo_personal_tool.presentation.splash import SplashScreen

pytestmark = pytest.mark.gui

WORDS = ("Local-first", "Private", "ASE aligned")


def _make_splash(qtbot, **kwargs) -> SplashScreen:
    splash = SplashScreen(
        words=WORDS,
        reduce_motion=kwargs.pop("reduce_motion", False),
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

    def test_covers_full_screen(self, qtbot) -> None:
        from PySide6.QtWidgets import QApplication

        splash = _make_splash(qtbot)
        splash.show_and_play()
        screen = QApplication.primaryScreen()
        assert screen is not None
        assert splash.geometry() == screen.geometry()
        splash._close_splash()

    def test_has_logo_fill_percent_and_words(self, qtbot) -> None:
        splash = _make_splash(qtbot)
        # logo fill widget exists with a real (scaled) logo pixmap
        assert not splash._fill._pm.isNull()
        assert splash._fill.width() > 0
        assert splash._percent_label.text() == "0%"
        assert [w._label.text() for w in splash._word_widgets] == list(WORDS)

    def test_black_background(self, qtbot) -> None:
        from PySide6.QtGui import QPalette

        splash = _make_splash(qtbot)
        assert splash.palette().color(QPalette.ColorRole.Window).name() == "#000000"

    def test_words_start_hidden_and_blurred(self, qtbot) -> None:
        splash = _make_splash(qtbot)
        for i, word in enumerate(splash._word_widgets):
            zone = splash_mod._WORD_ZONES[i]
            if zone[0] > 0:
                assert word._opacity_effect.opacity() < 0.15
                assert word._blur_effect.blurRadius() > 8


class TestSplashProgress:
    def test_words_sharpen_with_progress(self, qtbot) -> None:
        splash = _make_splash(qtbot)
        splash.set_progress(100)

        def _sharp() -> bool:
            return all(w._blur_effect.blurRadius() < 1.0 for w in splash._word_widgets)

        qtbot.waitUntil(_sharp, timeout=2500)
        for word in splash._word_widgets:
            assert word._opacity_effect.opacity() > 0.9
        splash._close_splash()

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

    def test_words_placed_around_logo(self, qtbot) -> None:
        splash = _make_splash(qtbot)
        fill = splash._fill
        fx, fy = fill.x(), fill.y()
        for word in splash._word_widgets:
            # every word lives outside the logo rectangle (above or below)
            assert word.y() + word.height() < fy or word.y() > fy + fill.height()


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
        qtbot.waitUntil(lambda: not splash.isVisible(), timeout=3000)
        assert revealed[0] is dummy

    def test_reduce_motion_shows_words_immediately(self, qtbot, monkeypatch) -> None:
        from PySide6.QtWidgets import QWidget

        monkeypatch.setattr(splash_mod, "MIN_VISIBLE_MS", 200)
        splash = _make_splash(qtbot, reduce_motion=True)
        dummy = QWidget()
        qtbot.addWidget(dummy)
        splash.show_and_play()
        for word in splash._word_widgets:
            assert word._opacity_effect.opacity() == 1.0 or word._opacity_effect.opacity() > 0.95
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
