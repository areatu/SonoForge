"""Startup splash — concept 4 (AnythingLLM 1.16 lineage).

Variant history (docs/splash-preview/):
  • index1.html — compact branded window + spinner (superseded)
  • index2.html — fullscreen black boot + horizontal white progress bar
  • index3.html — logo fills from bottom to top via an animated wavy mask
    (with droplets) + word row under the logo
  • index.html  — concept 4 (this module): droplets removed, big bold
    words scattered around the logo at different heights/distances, big
    percent counter; optional faint background image
  • index4-1.html — concept 4.1: same design in a small rounded card
    (compact mode of this module)

Concept 4 design:

    • frameless window (fullscreen black, or a small rounded centered
      card in compact mode), always on top, no taskbar entry
    • centered logo, initially barely visible (~10 % opacity); as the
      cosmetic progress grows, an animated wavy mask (sine edge only, no
      droplets) reveals the logo from bottom to top with white, until it
      is fully white at 100 %
    • small “NN%” counter under the logo (larger font)
    • words (Local-first / Private / ASE aligned) are scattered around
      the logo — each at a different height and a different distance from
      it — in bold; each starts at low opacity with a strong gaussian
      blur and sharpens within its own progress zone
    • optional faint background image (e.g. a 4-chamber echo frame) drawn
      at ~20 % opacity — off by default
    • the window closes (fade) into the maximized main window

The percentage is honest: it auto-steps to ~92 % while the real
(synchronous) startup work runs between ``set_progress`` calls and jumps
to 100 % only when initialization has actually finished.

Disable entirely with the environment variable ``ECHO_NO_SPLASH=1``.
"""

from __future__ import annotations

import math
import os
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
    QApplication,
    QGraphicsBlurEffect,
    QGraphicsOpacityEffect,
    QLabel,
    QWidget,
)

from echo_personal_tool.resources.bundled_fonts import FONT_FAMILY_UI

# ── Timing constants (tweak here; all in ms) ────────────────────────
MIN_VISIBLE_MS = 3400  # splash stays at least this long after show()
FADE_OUT_MS = 420  # fade into the main window
AUTO_STEP_MS = 420  # interval between automatic progress bumps
_PROGRESS_EASE_MS = 380  # ease duration of a progress step
WAVE_TICK_MS = 33  # repaint of the animated mask (~30 fps)

# ── Progress markers reached automatically while startup runs ──────
_AUTO_TARGETS = (8, 18, 30, 44, 58, 72, 84, 92)

# ── Word placement zones (start / end progress for each word) ──────
_WORD_ZONES = ((16, 58), (34, 76), (52, 96))

# ── Visuals (fullscreen reference values, scaled by logo width) ────
_LOGO_W_REF = 340  # reference logo width the sizes below are tuned for
_WORD_PT_REF = 20  # word font size at reference scale
_PCT_PT_REF = 22  # percent font size at reference scale
_WORD_BLUR_REF = 16.0  # gaussian blur radius while a word is hidden
_WORD_ALPHA_MIN = 0.08  # opacity of a word while it is hidden

# compact card geometry (scaled down on small screens)
_CARD_W = 620
_CARD_H = 430
_CARD_RADIUS = 26


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

    def __init__(self, text: str, font: QFont, blur_max: float, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._blur_max = blur_max
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(_WORD_ALPHA_MIN)
        self.setGraphicsEffect(self._opacity_effect)

        self._blur_effect = QGraphicsBlurEffect(self)
        self._blur_effect.setBlurRadius(blur_max)

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
        self._blur_effect.setBlurRadius(self._blur_max * (1.0 - t))


class _LogoFill(QWidget):
    """The logo that fills with white from the bottom (wavy mask, no droplets).

    The faint full logo is painted underneath; a second copy is drawn
    inside a wavy clip region covering the bottom ``progress`` % of the
    widget — the bright “filled” part. The top edge of the region is a
    slowly moving sine wave (that roughness is the “dirty edge” of the
    mask; explicit droplets were removed per design feedback).
    """

    def __init__(self, pixmap: QPixmap, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pm = pixmap
        self._progress = 0.0
        self._phase = 0.0
        self._clock = QElapsedTimer()
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

    def _tick(self) -> None:
        if self._progress < 100.0:
            self._phase = self._clock.elapsed() / 520.0  # wave speed
        self.update()

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

        # 2. bright fill inside the wavy bottom region (mask roughness only)
        edge = self.height() * (1.0 - progress / 100.0)
        freq = 2.6  # waves across the logo
        amp = 2.4  # px

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
        painter.end()


class SplashScreen(QWidget):
    """Frameless black splash (fullscreen or compact card), logo fill.

    Usage::

        splash = SplashScreen(words=tuple(tr("splash.words").split("|")),
                              reduce_motion=preferences.reduce_motion)
        splash.show_and_play()
        # ... real startup work ... optional: splash.set_progress(46)
        splash.complete_with(window, on_complete=reveal_window)
        result = app.exec()

    ``compact=True`` renders concept 4.1 — a small rounded card centered on
    the screen instead of a fullscreen window.
    """

    def __init__(
        self,
        *,
        words: tuple[str, ...] = (),
        theme_mode: str = "dark",  # noqa: ARG002 - kept for API compatibility
        reduce_motion: bool = False,
        app_name: str = "SonoForge",
        compact: bool = False,
        background: str | None = None,
    ) -> None:
        super().__init__(None)
        self._app_name = app_name
        self._words = words
        self._reduce_motion = reduce_motion
        self._compact = compact
        self._completed = False
        self._finish_callback: callable | None = None
        self._elapsed = QElapsedTimer()
        self._percent = 0.0
        self._auto_index = 0
        self._auto_timer: QTimer | None = None
        self._progress_anim: QVariantAnimation | None = None
        self._fade: QPropertyAnimation | None = None
        self._background: QPixmap | None = self._load_background(background)

        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
        self.setWindowFlags(flags)
        self.setWindowTitle(app_name)
        if compact:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#000000"))
        self.setPalette(palette)

        self._apply_geometry()
        self._build_ui()
        if self._compact:
            self._center_on_screen()

    # ── helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _load_background(path: str | None) -> QPixmap | None:
        if not path:
            return None
        try:
            pm = QPixmap(path)
            return None if pm.isNull() else pm
        except Exception:
            return None

    def _apply_geometry(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        if self._compact:
            avail = screen.availableGeometry()
            factor = min(1.0, avail.width() / _CARD_W, avail.height() / _CARD_H)
            factor = max(factor, 0.55)
            self.setFixedSize(int(round(_CARD_W * factor)), int(round(_CARD_H * factor)))
        else:
            self.setGeometry(screen.geometry())

    # ── UI ──────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # logo size: fixed reference width fullscreen, ~34 % of the card in
        # compact mode; everything else (fonts, gaps) scales with the logo
        if self._compact:
            logo_w = max(170, int(round(self.width() * 0.34)))
        else:
            logo_w = _LOGO_W_REF
        scale = logo_w / _LOGO_W_REF
        logo_path = _white_logo_path()
        pixmap = QPixmap(str(logo_path)) if logo_path.exists() else QPixmap()
        if pixmap.isNull():
            raise FileNotFoundError(f"White logo asset not found: {logo_path}")
        pixmap = pixmap.scaledToWidth(logo_w, Qt.TransformationMode.SmoothTransformation)

        self._fill = _LogoFill(pixmap, self)
        if not self._reduce_motion:
            self._fill.start()

        word_pt = max(13 if self._compact else 15, int(round(_WORD_PT_REF * scale)))
        pct_pt = max(15 if self._compact else 16, int(round(_PCT_PT_REF * scale)))
        blur_max = max(8.0, _WORD_BLUR_REF * scale)

        self._percent_label = QLabel("0%", self)
        self._percent_label.setFont(_font(pct_pt, weight=QFont.Weight.DemiBold))
        self._percent_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._percent_label.setStyleSheet("background: transparent; color: rgba(255,255,255,0.7);")

        self._word_widgets: list[_Word] = []
        word_font = _font(word_pt, weight=QFont.Weight.DemiBold)
        for text in self._words[: len(_WORD_ZONES)]:
            self._word_widgets.append(_Word(text, word_font, blur_max, parent=self))
        for i, word in enumerate(self._word_widgets):
            zone = _WORD_ZONES[i]
            word.set_clarity(1.0 if self._reduce_motion else (0.0 if zone[0] > 0 else 1.0))

        self._relayout()

    def _relayout(self) -> None:
        """Scatter words around the logo — different heights, distances, sides."""
        w = self.width()
        h = self.height()
        if w <= 1 or h <= 1:
            return
        logo_w = self._fill.width()
        logo_h = self._fill.height()
        s = logo_w / _LOGO_W_REF  # same layout scale as the logo
        cx = w / 2.0
        cy = h / 2.0
        lx = cx - logo_w / 2.0
        ly = cy - logo_h / 2.0
        self._fill.move(int(round(lx)), int(round(ly)))

        fm = QFontMetricsF(self._percent_label.font())
        pct_w = math.ceil(fm.horizontalAdvance("100%"))
        pct_h = math.ceil(fm.height())
        pct_y = ly + logo_h + 24.0 * s
        self._percent_label.setFixedSize(pct_w, pct_h)
        self._percent_label.move(int(round(cx - pct_w / 2.0)), int(round(pct_y)))

        margin = 18.0
        # Asymmetric constellation around the logo:
        #   word 0 — above-left, close to the logo, low
        #   word 1 — above-right, higher above and farther to the right
        #   word 2 — below-left, far below, close to the logo's left edge
        placements = (
            ("br", lx - 28.0 * s, ly - 14.0 * s),  # right edge, bottom edge
            ("tl", lx + logo_w + 52.0 * s, ly - 92.0 * s),  # left edge, bottom edge
            ("br", lx - 12.0 * s, ly + logo_h + 110.0 * s),  # right edge, top edge
        )
        for i, word in enumerate(self._word_widgets[: len(placements)]):
            mode, ax, ay = placements[i]
            word_w = word.width()
            word_h = word.height()
            if mode == "br":  # anchor is the word's bottom-right corner
                x = ax - word_w
                y = ay - word_h
            else:  # anchor is the word's bottom-left corner
                x = ax
                y = ay - word_h
            x = max(margin, min(x, w - word_w - margin))
            y = max(margin, min(y, h - word_h - margin))
            word.move(int(round(x)), int(round(y)))

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        self._relayout()

    # ── painting (black panel / rounded card + optional background) ──

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()

        clip = QPainterPath()
        if self._compact:
            clip.addRoundedRect(rect, _CARD_RADIUS, _CARD_RADIUS)
        else:
            clip.addRect(rect)
        painter.save()
        painter.setClipPath(clip)

        painter.fillRect(rect, QColor("#000000"))

        # optional faint background image (concept 4.1 experiment)
        if self._background is not None:
            bg = self._background
            # cover-fit the widget
            target = rect
            bw, bh = bg.width(), bg.height()
            if bw > 0 and bh > 0:
                scale = max(target.width() / bw, target.height() / bh)
                dw = bw * scale
                dh = bh * scale
                dx = (target.width() - dw) / 2.0
                dy = (target.height() - dh) / 2.0
                painter.setOpacity(0.20)
                painter.drawPixmap(dx, dy, dw, dh, bg)
                painter.setOpacity(1.0)
        painter.restore()

        if self._compact:
            pen_color = QColor(255, 255, 255, 26)
            painter.setPen(pen_color)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), _CARD_RADIUS, _CARD_RADIUS)
        painter.end()

    def _center_on_screen(self) -> None:
        screen = self.screen()
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        self.move(
            geo.x() + (geo.width() - self.width()) // 2,
            geo.y() + (geo.height() - self.height()) // 2,
        )

    # ── public API ──────────────────────────────────────────────────

    def show_and_play(self) -> SplashScreen:
        """Show the splash and start all animations."""
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
        """Startup finished: jump to 100 %, then reveal the main window."""
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
        # fade the window out over the (now visible) main window
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
