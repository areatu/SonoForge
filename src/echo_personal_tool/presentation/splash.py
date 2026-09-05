"""Fullscreen startup splash — AnythingLLM Desktop 1.16.1 style.

Design (matches the AnythingLLM 1.16.x boot screen the user described):

    • frameless fullscreen window, pure black background
    • centered white logo
    • under the logo: thin progress bar that fills with white + “NN%”
    • a row of words fades in near the end — each word transitions from
      transparent + gaussian blur into sharp focus (staggered)
    • the window then closes into the maximized main window (fade out)

The percentage is cosmetic and never reaches 100 % until real startup work
has finished: ``set_progress()`` (optional) syncs it with actual milestones,
``complete_with()`` jumps it to 100 % and reveals the main window after a
pleasant minimum display time.

Disable entirely with the environment variable ``ECHO_NO_SPLASH=1``
(used by automated tests / screenshots).
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QElapsedTimer,
    QPropertyAnimation,
    Qt,
    QTimer,
    QVariantAnimation,
)
from PySide6.QtGui import QColor, QFont, QPalette, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsBlurEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.resources.bundled_fonts import FONT_FAMILY_UI

# ── Timing constants (tweak here; all in ms) ────────────────────────
MIN_VISIBLE_MS = 3400  # splash stays at least this long after show()
FADE_OUT_MS = 420  # fade of the black window into the main window
AUTO_STEP_MS = 420  # interval between automatic progress bumps
WORD_START_MS = 1000  # first word starts fading in
WORD_STAGGER_MS = 700  # …then every next word follows after this delay
WORD_FADE_MS = 620  # blur→focus duration per word

# ── Progress markers reached automatically while startup runs ──────
_AUTO_TARGETS = (8, 18, 30, 44, 58, 72, 84, 92)

# ── Visuals ─────────────────────────────────────────────────────────
_LOGO_WIDTH = 360  # px on the (scaled) logo lockup
_BAR_WIDTH = 200  # px of the white progress bar
_BLUR_START = 9.0  # gaussian blur radius at word start


def _env_flag(name: str, default: bool = True) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() not in ("0", "false", "no", "off")


def is_splash_enabled() -> bool:
    """Whether the splash should be shown at all.

    Opt-out via ``ECHO_NO_SPLASH=1``. Also returns False when no real
    QApplication is running yet (e.g. headless/mocked unit tests that
    exercise ``main()`` with a stubbed application object).
    """
    if not _env_flag("ECHO_NO_SPLASH", default=True):
        return False
    try:
        from PySide6.QtWidgets import QApplication

        return QApplication.instance() is not None
    except Exception:
        return False


def _white_logo_path() -> Path:
    """The white logo variant (the only one that works on black)."""
    base = Path(__file__).resolve().parent.parent / "resources"
    path = base / "logo_dark.png"
    if path.exists():
        return path
    return base / "logo.png"


class _Word(QWidget):
    """One word of the blur-in row.

    Opacity lives on the wrapper, gaussian blur on the inner label —
    two effects can't share one widget, so they are nested.
    """

    def __init__(self, text: str, text_color: str, font: QFont) -> None:
        super().__init__()
        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity)

        self._blur = QGraphicsBlurEffect(self)
        self._blur.setBlurRadius(0.0)

        self._label = QLabel(text, self)
        self._label.setFont(font)
        self._label.setStyleSheet(f"background: transparent; color: {text_color};")
        self._label.setGraphicsEffect(self._blur)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._label)

        self._opacity_anim: QPropertyAnimation | None = None
        self._blur_anim: QVariantAnimation | None = None

    # ── animation ───────────────────────────────────────────────────

    def play_fade_in(self, delay_ms: int, duration_ms: int, reduce_motion: bool) -> None:
        if reduce_motion:
            self._opacity.setOpacity(1.0)
            self._blur.setBlurRadius(0.0)
            return
        QTimer.singleShot(delay_ms, lambda: self._run(duration_ms))

    def _run(self, duration_ms: int) -> None:
        # opacity 0 → 1
        opacity_anim = QPropertyAnimation(self._opacity, b"opacity", self)
        opacity_anim.setDuration(duration_ms)
        opacity_anim.setStartValue(0.0)
        opacity_anim.setEndValue(1.0)
        opacity_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        opacity_anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        self._opacity_anim = opacity_anim
        # blur 9px → 0 (sharp focus)
        blur_anim = QVariantAnimation(self)
        blur_anim.setStartValue(_BLUR_START)
        blur_anim.setEndValue(0.0)
        blur_anim.setDuration(duration_ms)
        blur_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        blur_anim.valueChanged.connect(lambda v: self._blur.setBlurRadius(float(v)))
        blur_anim.start()
        self._blur_anim = blur_anim


class SplashScreen(QWidget):
    """Frameless fullscreen black splash with blur-in words.

    Usage::

        splash = SplashScreen(words=tuple(tr("splash.words").split("|")),
                              reduce_motion=preferences.reduce_motion)
        splash.show_and_play()
        # ... real startup work ... optional: splash.set_progress(40)
        splash.complete_with(window, on_complete=reveal_window)
        result = app.exec()
    """

    def __init__(
        self,
        *,
        words: tuple[str, ...] = (),
        theme_mode: str = "dark",
        reduce_motion: bool = False,
        app_name: str = "SonoForge",
    ) -> None:
        super().__init__(None)
        self._app_name = app_name
        self._words = words
        self._reduce_motion = reduce_motion
        self._completed = False
        self._finish_callback: callable | None = None
        self._elapsed = QElapsedTimer()
        self._percent = 0.0
        self._auto_index = 0
        self._auto_timer: QTimer | None = None
        self._progress_anim: QVariantAnimation | None = None
        self._fade: QPropertyAnimation | None = None

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle(app_name)
        self.setStyleSheet("background: #000000;")
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#000000"))
        self.setPalette(palette)

        self._build_ui()
        self._resize_to_screen()

    # ── UI ──────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        text_color = "rgba(255,255,255,0.9)"

        # white logo lockup
        logo_label = QLabel(self)
        logo_path = _white_logo_path()
        if logo_path.exists():
            pm = QPixmap(str(logo_path))
            if not pm.isNull():
                scaled = pm.scaledToWidth(
                    _LOGO_WIDTH,
                    Qt.TransformationMode.SmoothTransformation,
                )
                logo_label.setPixmap(scaled)
        logo_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        logo_label.setStyleSheet("background: transparent;")
        self._logo_label = logo_label

        # percent label + white progress bar (Photoshop-style, under the logo)
        percent_label = QLabel("0%", self)
        percent_label.setFont(_font(12, weight=QFont.Weight.Medium))
        percent_label.setStyleSheet("color: rgba(255,255,255,0.85); background: transparent;")
        percent_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self._percent_label = percent_label

        bar_track = QWidget(self)
        bar_track.setFixedSize(_BAR_WIDTH, 3)
        bar_track.setStyleSheet("background: rgba(255,255,255,0.14); border-radius: 1px;")
        bar_fill = QWidget(bar_track)
        bar_fill.setFixedWidth(0)
        bar_fill.setStyleSheet("background: #ffffff; border-radius: 1px;")
        bar_fill.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._bar_fill = bar_fill
        self._bar_track = bar_track

        progress_row = QWidget(self)
        progress_row.setStyleSheet("background: transparent;")
        progress_layout = QHBoxLayout(progress_row)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        progress_layout.setSpacing(14)
        progress_layout.addWidget(bar_track, alignment=Qt.AlignmentFlag.AlignVCenter)
        progress_layout.addWidget(percent_label, alignment=Qt.AlignmentFlag.AlignVCenter)

        # blur-in word row (near the end of the sequence)
        word_row = QWidget(self)
        word_row.setStyleSheet("background: transparent;")
        word_layout = QHBoxLayout(word_row)
        word_layout.setContentsMargins(0, 0, 0, 0)
        word_layout.setSpacing(30)
        word_font = _font(14, weight=QFont.Weight.Normal)
        self._word_widgets: list[_Word] = []
        for text in self._words:
            word = _Word(text, text_color, word_font)
            self._word_widgets.append(word)
            word_layout.addWidget(word)
        self._word_row = word_row

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.addStretch(2)
        column.addWidget(logo_label, alignment=Qt.AlignmentFlag.AlignHCenter)
        column.addSpacing(34)
        column.addWidget(progress_row, alignment=Qt.AlignmentFlag.AlignHCenter)
        column.addSpacing(26)
        column.addWidget(word_row, alignment=Qt.AlignmentFlag.AlignHCenter)
        column.addStretch(3)

    def _resize_to_screen(self) -> None:
        """Cover the whole screen like AnythingLLM 1.16's borderless boot."""
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        self.setGeometry(screen.geometry())

    # ── public API ──────────────────────────────────────────────────

    def show_and_play(self) -> SplashScreen:
        """Show the fullscreen splash and start all animations."""
        self.show()
        self._elapsed.start()
        # autoplay progress: bump to the next marker on a timer
        self._auto_timer = QTimer(self)
        self._auto_timer.setInterval(AUTO_STEP_MS)
        self._auto_timer.timeout.connect(self._auto_step)
        self._auto_timer.start()
        # stagger the blur-in of the words
        for i, word in enumerate(self._word_widgets):
            word.play_fade_in(
                WORD_START_MS + i * WORD_STAGGER_MS,
                WORD_FADE_MS,
                reduce_motion=self._reduce_motion,
            )
        return self

    def set_progress(self, percent: int) -> None:
        """Sync the cosmetic counter with a real startup milestone (0–100)."""
        self._ease_to(min(100, max(0, int(percent))))

    def complete_with(self, main_window: QWidget, on_complete: callable | None = None) -> None:
        """Startup finished: jump to 100 %, then reveal the main window.

        The main window stays hidden until the minimum display time has
        elapsed; then *on_complete* is invoked (reveal the main window)
        and the black splash fades out over it.
        """
        if self._completed:
            return
        self._completed = True
        self._finish_callback = on_complete
        if self._auto_timer is not None:
            self._auto_timer.stop()
        self._ease_to(100)
        if self._reduce_motion:
            wait_ms = min(900, MIN_VISIBLE_MS)
        else:
            wait_ms = max(0, MIN_VISIBLE_MS - int(self._elapsed.elapsed()))
        QTimer.singleShot(wait_ms + 220, lambda: self._reveal(main_window))

    # ── internals ───────────────────────────────────────────────────

    def _auto_step(self) -> None:
        if self._completed:
            return
        target = _AUTO_TARGETS[min(self._auto_index, len(_AUTO_TARGETS) - 1)]
        self._auto_index += 1
        self._ease_to(target)

    def _ease_to(self, target: float) -> None:
        current = self._percent
        if abs(target - current) < 0.5:
            return
        anim = QVariantAnimation(self)
        anim.setStartValue(current)
        anim.setEndValue(float(target))
        anim.setDuration(360)
        anim.setEasingCurve(QEasingCurve.Type.OutQuad)
        anim.valueChanged.connect(self._on_progress_tick)
        anim.start()
        self._progress_anim = anim

    def _on_progress_tick(self, value) -> None:
        self._percent = float(value)
        percent = int(round(self._percent))
        self._percent_label.setText(f"{percent}%")
        width = max(0, int(_BAR_WIDTH * self._percent / 100.0))
        self._bar_fill.setFixedWidth(width)

    def _reveal(self, main_window: QWidget) -> None:
        if self._finish_callback is not None:
            try:
                self._finish_callback(main_window)
            except Exception:
                pass
        if main_window is not None:
            main_window.raise_()
            main_window.activateWindow()
        if self._reduce_motion:
            self._close_splash()
            return
        # fade the black window out over the (now visible) main window
        self.setWindowOpacity(1.0)
        fade = QPropertyAnimation(self, b"windowOpacity")
        fade.setDuration(FADE_OUT_MS)
        fade.setStartValue(1.0)
        fade.setEndValue(0.0)
        fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        fade.finished.connect(self._close_splash)
        fade.start()
        self._fade = fade

    def _close_splash(self) -> None:
        if self._auto_timer is not None:
            self._auto_timer.stop()
        self.hide()
        self.close()
        self.deleteLater()


def _font(point_size: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    font = QFont(FONT_FAMILY_UI, point_size)
    font.setWeight(weight)
    return font
