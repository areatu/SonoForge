"""Tests for the AnythingLLM 1.16-style fullscreen startup splash."""

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
    monkeypatch.setattr(splash_mod, "WORD_START_MS", 30)
    monkeypatch.setattr(splash_mod, "WORD_STAGGER_MS", 30)


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

    def test_has_logo_percent_bar_and_word_row(self, qtbot) -> None:
        splash = _make_splash(qtbot)
        assert splash._logo_label.pixmap() is not None and not splash._logo_label.pixmap().isNull()
        assert splash._percent_label.text() == "0%"
        assert splash._bar_fill.width() == 0
        assert [w._label.text() for w in splash._word_widgets] == list(WORDS)

    def test_set_progress_updates_counter_and_bar(self, qtbot) -> None:
        splash = _make_splash(qtbot)
        splash.set_progress(50)
        assert splash._percent_label.text() == "50%"
        assert splash._bar_fill.width() > 0

    def test_words_are_white_labels_on_black_window(self, qtbot) -> None:
        splash = _make_splash(qtbot)
        assert splash.palette().window().name() == "#000000"
        for word in splash._word_widgets:
            assert "white" in word._label.styleSheet() or "255,255,255" in word._label.styleSheet()


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

    def test_words_fade_in(self, qtbot, monkeypatch) -> None:
        _fast_timings(monkeypatch)
        splash = _make_splash(qtbot)
        splash.show_and_play()

        def _revealed() -> bool:
            return all(w._opacity.opacity() > 0.9 for w in splash._word_widgets)

        qtbot.waitUntil(_revealed, timeout=3000)
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

    def test_reduce_motion_skips_animations(self, qtbot, monkeypatch) -> None:
        from PySide6.QtWidgets import QWidget

        monkeypatch.setattr(splash_mod, "MIN_VISIBLE_MS", 200)
        splash = _make_splash(qtbot, reduce_motion=True)
        dummy = QWidget()
        qtbot.addWidget(dummy)
        splash.show_and_play()
        # words are immediately fully opaque & sharp
        assert all(w._opacity.opacity() == 1.0 for w in splash._word_widgets)
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
