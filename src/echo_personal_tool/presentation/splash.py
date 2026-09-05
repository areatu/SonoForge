"""Fullscreen startup splash — AnythingLLM Desktop 1.16.1 style, variant 3.

Variant history (see docs/splash-preview/):
  • index1.html — compact branded window + spinner (superseded)
  • index2.html — fullscreen black boot, horizontal white progress bar
    + blur-in words (superseded)
  • index.html / this module — logo fill from bottom to top + word field

Design of the current variant:

    • frameless window covering the whole screen, pure black (#000)
    • centered logo, initially barely visible (low opacity)
    • as the cosmetic progress grows, the logo fills from bottom to top
      with white: an animated wavy “water” mask (sine edge + rising
      droplets) reveals the bright logo, until it is fully white at 100 %
    • small “NN%” counter below the logo
    • three words (Local-first / Private / ASE aligned) are placed
      individually above and below the logo, left and right; each starts
      with low opacity and a strong gaussian blur and sharpens as the
      progress reaches its zone, becoming fully readable at the end
    • the window then closes (fade) into the maximized main window

The percentage is honest: it auto-steps to ~92 % while the real
(synchronous) startup work runs between ``set_progress`` calls and jumps
to 100 % only when initialization has actually finished.

Disable entirely with the environment variable ``ECHO_NO_SPLASH=1``.
"""

from __future__ import annotations

import math
import os
import random
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QElapsedTimer,
    QPointF,
    QPropertyAnimation,
    Qt,
    QTimer,
    QVariantAnimation,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QPainter,
    QPainterPath,
    QPalette,
    QPixmap,
)
from PySide6.QtWidgets import (
    QGraphicsBlurEffect,
    QGraphicsOpacityEffect,
    QLabel,
    QWidget,
)

from echo_personal_tool.resources.bundled_fonts import FONT_FAMILY_UI

# ── Timing constants (tweak here; all in ms) ────────────────────────
MIN_VISIBLE_MS = 3400  # splash stays at least this long after show()
FADE_OUT_MS = 420  # fade of the black window into the main window
AUTO_STEP_MS = 420  # interval between automatic progress bumps
_PROGRESS_EASE_MS = 380  # ease duration of a progress step
WAVE_TICK_MS = 33  # repaint of the wave / droplets (~30 fps)

# ── Progress markers reached automatically while startup runs ──────
_AUTO_TARGETS = (8, 18, 30, 44, 58, 72, 84, 92)

# ── Word placement zones (start / end progress for each word) ──────
_WORD_ZONES = ((16, 58), (34, 76), (52, 96))

# ── Visuals ─────────────────────────────────────────────────────────
_LOGO_W = 340  # displayed width of the logo
_WORD_BLUR_MAX = 16.0  # gaussian blur radius while a word is hidden
_WORD_ALPHA_MIN = 0.08  # opacity of a word while it is hidden


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


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * max(0.0, min(1.0, t))


def _font(point_size: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    font = QFont(FONT_FAMILY_UI, point_size)
    font.setWeight(weight)
    return font


class _Word(QWidget):
    """One positioned word with progress-driven opacity + blur."""

    def __init__(self, text: str, font: QFont) -> None:
        super().__init__()
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(_WORD_ALPHA_MIN)
        self.setGraphicsEffect(self._opacity_effect)

        self._blur_effect = QGraphicsBlurEffect(self)
        self._blur_effect.setBlurRadius(_WORD_BLUR_MAX)

        self._label = QLabel(text, self)
        self._label.setFont(font)
        self._label.setStyleSheet("background: transparent; color: #ffffff;")
        self._label.setGraphicsEffect(self._blur_effect)

        fm = QFontMetricsF(font)
        w = math.ceil(fm.horizontalAdvance(text))
        h = math.ceil(fm.height())
        self._label.setFixedSize(w, h)
        self.setFixedSize(w, h)

    def set_clarity(self, t: float) -> None:
        """t in [0..1]: 0 = hidden (strong blur), 1 = fully readable."""
        t = max(0.0, min(1.0, t))
        self._opacity_effect.setOpacity(_lerp(_WORD_ALPHA_MIN, 0.96, t))
        self._blur_effect.setBlurRadius(_WORD_BLUR_MAX * (1.0 - t))


class _LogoFill(QWidget):
    """The logo that fills with white from the bottom (water-like mask).

    Implementation:
      • the faint full logo is always painted (opacity grows with progress)
      • a second copy of the logo is drawn inside a wavy clip region that
        covers only the bottom ``progress`` % of the widget — the bright
        “filled” part; the top edge of that region is a slow sine wave
      • tiny droplets rise above the wave edge while it moves upward
      • at 100 % the whole logo is bright white
    """

    def __init__(self, pixmap: QPixmap, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pm = pixmap
        self._progress = 0.0
        self._phase = 0.0
        self._clock = QElapsedTimer()
        self._droplets: list[list[float]] = []  # x, y, vy, radius, born
        self._timer: QTimer | None = None
        self.setFixedSize(pixmap.width(), pixmap.height())

    def start(self) -> None:
        if self._timer is not None:
            return
        self._clock.start()
        timer = QTimer(self)
        timer.setInterval(WAVE_TICK_MS)
        timer.timeout.connect(self._tick)
        timer.start()
        self._timer = timer

    def stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer.deleteLater()
            self._timer = None

    def set_progress(self, value: float) -> None:
        self._progress = max(0.0, min(100.0, value))

    # ── animation ───────────────────────────────────────────────────

    def _tick(self) -> None:
        if self._progress < 100.0:
            elapsed = self._clock.elapsed()
            self._phase = elapsed / 520.0  # wave speed
            edge = self._edge_y()
            # droplets: advance upward + cull
            dt = WAVE_TICK_MS / 1000.0
            alive: list[list[float]] = []
            for d in self._droplets:
                d[1] -= d[2] * dt  # vy is px/s, upward (y decreases)
                if edge - d[1] < 110.0:  # not too far above the boundary
                    alive.append(d)
            self._droplets = alive
            # occasional spawn near the moving edge
            if self._progress > 0.0 and random.random() < 0.45:
                x = random.uniform(6.0, self.width() - 6.0)
                y = edge - random.uniform(2.0, 14.0)
                vy = random.uniform(28.0, 70.0)
                r = random.uniform(1.0, 2.6)
                self._droplets.append([x, y, vy, r, 0.0])
        self.update()

    def _edge_y(self) -> float:
        """Y of the wavy fill boundary (top of the filled region)."""
        return self.height() * (1.0 - self._progress / 100.0)

    # ── painting ────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        progress = self._progress

        # 1. faint base logo; opacity grows to fully white at 100 %
        base_alpha = _lerp(0.10, 1.0, progress / 100.0)
        painter.setOpacity(base_alpha)
        painter.drawPixmap(0, 0, self._pm)
        if progress >= 99.5:
            painter.setOpacity(1.0)
            painter.drawPixmap(0, 0, self._pm)
            painter.end()
            return

        # 2. bright fill inside the wavy bottom region
        edge = self._edge_y()
        freq = 2.6  # waves across the logo
        amp = 2.6  # px

        def wave_y(x: float) -> float:
            return edge + amp * math.sin(2.0 * math.pi * (x / w) * freq + self._phase)

        clip = QPainterPath()
        clip.moveTo(-2.0, edge)
        steps = max(8, w // 6)
        for i in range(steps + 1):
            x = w * i / steps
            clip.lineTo(QPointF(x, wave_y(x)))
        clip.lineTo(w + 2.0, h + 2.0)
        clip.lineTo(-2.0, h + 2.0)
        clip.closeSubpath()
        painter.save()
        painter.setClipPath(clip)
        painter.setOpacity(0.98)
        painter.drawPixmap(0, 0, self._pm)
        painter.restore()

        # 3. droplets floating up above the boundary
        painter.setOpacity(1.0)
        for d in self._droplets:
            x, y, _, r, _ = d
            dist = edge - y
            fade = max(0.0, 1.0 - dist / 90.0)
            if fade <= 0.0:
                continue
            painter.setPen(Qt.PenStyle.NoPen)
            color = QColor(255, 255, 255)
            color.setAlphaF(0.65 * fade)
            painter.setBrush(color)
            painter.drawEllipse(QPointF(x, y), r, r)
        painter.end()


class SplashScreen(QWidget):
    """Frameless fullscreen black splash, logo-fill + word field.

    Usage::

        splash = SplashScreen(words=tuple(tr("splash.words").split("|")),
                              reduce_motion=preferences.reduce_motion)
        splash.show_and_play()
        # ... real startup work ... optional: splash.set_progress(46)
        splash.complete_with(window, on_complete=reveal_window)
        result = app.exec()
    """

    def __init__(
        self,
        *,
        words: tuple[str, ...] = (),
        theme_mode: str = "dark",  # noqa: ARG002 - always black, kept for API compat
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
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#000000"))
        self.setPalette(palette)
        self.setStyleSheet("background: #000000;")

        self._build_ui()
        self._resize_to_screen()

    # ── UI ──────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        logo_path = _white_logo_path()
        pixmap = QPixmap(str(logo_path)) if logo_path.exists() else QPixmap()
        if pixmap.isNull():
            raise FileNotFoundError(f"White logo asset not found: {logo_path}")
        pixmap = pixmap.scaledToWidth(_LOGO_W, Qt.TransformationMode.SmoothTransformation)

        self._fill = _LogoFill(pixmap, self)
        if not self._reduce_motion:
            self._fill.start()

        self._percent_label = QLabel("0%", self)
        self._percent_label.setFont(_font(12, weight=QFont.Weight.Medium))
        self._percent_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._percent_label.setStyleSheet("background: transparent; color: rgba(255,255,255,0.7);")

        word_font = _font(14, weight=QFont.Weight.Normal)
        self._word_widgets: list[_Word] = []
        for text in self._words[: len(_WORD_ZONES)]:
            word = _Word(text, word_font)
            self._word_widgets.append(word)
        if not self._reduce_motion:
            for i, word in enumerate(self._word_widgets):
                zone = _WORD_ZONES[i]
                word.set_clarity(0.0 if zone[0] > 0 else 1.0)
        else:
            for word in self._word_widgets:
                word.set_clarity(1.0)

        self._relayout()

    def _relayout(self) -> None:
        """Position the logo (center) and the words around it."""
        w = self.width()
        h = self.height()
        if w <= 1 or h <= 1:
            return
        logo_w = self._fill.width()
        logo_h = self._fill.height()
        cx = w / 2.0
        cy = h / 2.0
        lx = cx - logo_w / 2.0
        ly = cy - logo_h / 2.0
        self._fill.move(int(round(lx)), int(round(ly)))

        # percent counter right under the logo, centered
        fm = QFontMetricsF(self._percent_label.font())
        pct_w = math.ceil(fm.horizontalAdvance("100%"))
        pct_h = math.ceil(fm.height())
        pct_y = ly + logo_h + 14
        self._percent_label.setFixedSize(pct_w, pct_h)
        self._percent_label.move(int(round(cx - pct_w / 2.0)), int(round(pct_y)))

        if not self._word_widgets:
            return

        # words around the logo: above-left, above-right, below-left
        gap = 40.0  # horizontal gap between logo and words
        top_y = ly - 26.0  # baseline: words sit above the logo top edge
        bottom_y = ly + logo_h + 74.0  # words sit below the logo bottom edge
        left_x = cx - logo_w / 2.0 - gap
        right_x = cx + logo_w / 2.0 + gap

        placements = (
            (left_x, top_y, False),  # above-left
            (right_x, top_y, True),  # above-right
            (left_x, bottom_y, False),  # below-left
        )
        for i, word in enumerate(self._word_widgets[: len(placements)]):
            px, py, right_aligned = placements[i]
            word_w = word.width()
            word_h = word.height()
            # keep inside screen margins
            margin = 24.0
            if right_aligned:
                x = min(px - word_w, w - word_w - margin)
                x = max(x, margin)
            else:
                x = max(px, margin)
                x = min(x, w - word_w - margin)
            y = py - word_h / 2.0
            y = max(margin, min(y, h - word_h - margin))
            word.move(int(round(x)), int(round(y)))

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        self._relayout()

    # ── public API ──────────────────────────────────────────────────

    def show_and_play(self) -> SplashScreen:
        """Show the fullscreen splash and start all animations."""
        self.show()
        self._elapsed.start()
        self._auto_timer = QTimer(self)
        self._auto_timer.setInterval(AUTO_STEP_MS)
        self._auto_timer.timeout.connect(self._auto_step)
        self._auto_timer.start()
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
        anim.setDuration(_PROGRESS_EASE_MS)
        anim.setEasingCurve(QEasingCurve.Type.OutQuad)
        anim.valueChanged.connect(self._on_progress_tick)
        anim.start()
        self._progress_anim = anim

    def _on_progress_tick(self, value) -> None:
        self._percent = float(value)
        percent = int(round(self._percent))
        self._percent_label.setText(f"{percent}%")
        alpha = _lerp(0.55, 1.0, self._percent / 100.0)
        self._percent_label.setStyleSheet(f"background: transparent; color: rgba(255,255,255,{alpha:.2f});")
        self._fill.set_progress(self._percent)
        for i, word in enumerate(self._word_widgets):
            if i < len(_WORD_ZONES):
                start, end = _WORD_ZONES[i]
                t = 0.0 if self._percent <= start else (self._percent - start) / (end - start)
                word.set_clarity(t)

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
        self._fill.stop()
        self.hide()
        self.close()
        self.deleteLater()
