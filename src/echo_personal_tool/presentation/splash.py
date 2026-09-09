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

    • frameless window (fullscreen black, or a small centered
      card in compact mode), always on top, no taskbar entry
    • centered logo, initially barely visible (~10 % opacity); as the
      cosmetic progress grows, an animated wavy mask (sine edge only, no
      droplets) reveals the logo from bottom to top with white, until it
      is fully white at 100 %
    • big "NN%" counter under the logo
    • module loading status line (smaller font) under the percent
    • optional faint background image (e.g. a 4-chamber echo frame) drawn
      at ~20 % opacity — off by default
    • the window closes (fade) into the maximized main window

The percentage is honest: it auto-steps to ~92 % while the real
(synchronous) startup runs between ``set_progress`` calls and jumps
to 100 % only when initialization has actually finished.

Disable entirely with the environment variable ``ECHO_NO_SPLASH=1``.
"""

from __future__ import annotations

import logging
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
    QLabel,
    QWidget,
)

from echo_personal_tool.resources.bundled_fonts import FONT_FAMILY_UI

logger = logging.getLogger(__name__)

# ── Timing constants (tweak here; all in ms) ────────────────────────
MIN_VISIBLE_MS = 3400  # splash stays at least this long after show()
FADE_OUT_MS = 420  # fade into the main window
AUTO_STEP_MS = 420  # interval between automatic progress bumps
_PROGRESS_EASE_MS = 650  # ease duration of a progress step (slower fill)
WAVE_TICK_MS = 33  # repaint of the animated mask (~30 fps)
_FLASH_MS = 300  # total flash duration (brief bright pulse)

# ── Progress markers reached automatically while startup runs ──────
_AUTO_TARGETS = (8, 18, 30, 44, 58, 72, 84, 92)

# ── Visuals (fullscreen reference values, scaled by logo width) ────
_LOGO_W_REF = 340  # reference logo width the sizes below are tuned for
_PCT_PT_REF = 66  # percent font size at reference scale (3x original 22pt)
_MOD_PT_REF = 14  # module status font size at reference scale

# compact card geometry
_CARD_W = 620
_CARD_H = 580

# ── Module loading status lines ────────────────────────────────────
_MODULE_LINES_EN = (
    "Loading models",
    "Initializing DICOM engine",
    "Loading ASE reference",
    "Preparing viewer",
    "Initializing calculators",
    "Loading segmentation models",
    "Preparing Doppler module",
    "Building UI",
)


def _env_flag(name: str, default: bool = True) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() not in ("0", "false", "no", "off")


def is_splash_enabled() -> bool:
    """Whether the splash should be shown at all."""
    if _env_flag("ECHO_NO_SPLASH", default=False):
        return False
    try:
        from PySide6.QtWidgets import QApplication

        return QApplication.instance() is not None
    except Exception:
        logger.debug("splash: QApplication check failed", exc_info=True)
        return False


def _white_logo_path() -> Path:
    """The white logo variant (the only one that works on black)."""
    base = Path(__file__).resolve().parent.parent / "resources"
    path = base / "logo_dark.png"
    if path.exists():
        return path
    return base / "logo.png"


def _placeholder_logo(width: int) -> QPixmap:
    """Fallback pixmap when logo files are missing (e.g. broken install)."""
    from PySide6.QtCore import QSize

    pm = QPixmap(QSize(width, width))
    pm.fill(QColor("#000000"))
    painter = QPainter(pm)
    painter.setPen(QColor("#ffffff"))
    font = QFont(FONT_FAMILY_UI, max(12, width // 10))
    font.setWeight(QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "SonoForge")
    painter.end()
    return pm


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * max(0.0, min(1.0, t))


def _font(point_size: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    font = QFont(FONT_FAMILY_UI, point_size)
    font.setWeight(weight)
    return font


def _set_label_color(label: QLabel, color: QColor) -> None:
    """Change label foreground color without touching stylesheet (preserves font)."""
    pal = label.palette()
    pal.setColor(QPalette.ColorRole.WindowText, color)
    label.setPalette(pal)


class _LogoFill(QWidget):
    """The logo that fills with white from the bottom (wavy mask, no droplets).

    The faint full logo is painted underneath; a second copy is drawn
    inside a wavy clip region covering the bottom ``progress`` % of the
    widget — the bright "filled" part. The top edge of the region is a
    slowly moving sine wave (that roughness is the "dirty edge" of the
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

        if progress >= 99.5:
            painter.setOpacity(1.0)
            painter.drawPixmap(0, 0, self._pm)
            painter.end()
            return

        # 1. faint base logo; opacity grows to fully white at 100 %
        base_alpha = _lerp(0.10, 1.0, progress / 100.0)
        painter.setOpacity(base_alpha)
        painter.drawPixmap(0, 0, self._pm)

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

        splash = SplashScreen(reduce_motion=preferences.reduce_motion)
        splash.show_and_play()
        # ... real startup work ... optional: splash.set_progress(46)
        splash.complete_with(window, on_complete=reveal_window)
        result = app.exec()

    ``compact=True`` renders concept 4.1 — a small centered card instead
    of a fullscreen window.
    """

    def __init__(
        self,
        *,
        reduce_motion: bool = False,
        app_name: str = "SonoForge",
        compact: bool = False,
        background: str | None = None,
        **_kwargs: object,
    ) -> None:
        super().__init__(None)
        self._app_name = app_name
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
        self._flash_anim: QVariantAnimation | None = None
        self._flash_overlay = 0.0  # 0.0 = no flash overlay, 1.0 = full white
        self._module_index = 0
        self._module_timer: QTimer | None = None

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
        if self._compact:
            logo_w = max(200, int(round(self.width() * 0.55)))
        else:
            logo_w = _LOGO_W_REF
        scale = logo_w / _LOGO_W_REF
        logo_path = _white_logo_path()
        pixmap = QPixmap(str(logo_path)) if logo_path.exists() else QPixmap()
        if pixmap.isNull():
            logger.warning("splash: logo not found at %s, using placeholder", logo_path)
            pixmap = _placeholder_logo(logo_w)
        pixmap = pixmap.scaledToWidth(logo_w, Qt.TransformationMode.SmoothTransformation)

        self._fill = _LogoFill(pixmap, self)
        if not self._reduce_motion:
            self._fill.start()

        pct_pt = max(28 if self._compact else 32, int(round(_PCT_PT_REF * scale)))
        mod_pt = max(10, int(round(_MOD_PT_REF * scale)))

        # Percent label — font set ONCE, color managed via QPalette (never via
        # setStyleSheet, which resets the font on Linux/Qt6).
        self._percent_label = QLabel("0%", self)
        self._percent_label.setFont(_font(pct_pt, weight=QFont.Weight.DemiBold))
        self._percent_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _set_label_color(self._percent_label, QColor(255, 255, 255, 178))

        self._module_label = QLabel("", self)
        self._module_label.setFont(_font(mod_pt))
        self._module_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _set_label_color(self._module_label, QColor(255, 255, 255, 115))

        self._relayout()

    def _relayout(self) -> None:
        w = self.width()
        h = self.height()
        if w <= 1 or h <= 1:
            return
        logo_w = self._fill.width()
        logo_h = self._fill.height()
        s = logo_w / _LOGO_W_REF
        cx = w / 2.0

        # keep the same top-edge distance as the old 68% layout
        ly = (h - logo_h) / 2.0 - 40.0 * s
        lx = cx - logo_w / 2.0
        self._fill.move(int(round(lx)), int(round(ly)))

        # percent label: 10 px below the logo
        fm = QFontMetricsF(self._percent_label.font())
        pct_w = math.ceil(fm.horizontalAdvance("100%"))
        pct_h = math.ceil(fm.height())
        pct_y = ly + logo_h + 10.0
        self._percent_label.setFixedSize(max(pct_w, 80), pct_h)
        self._percent_label.move(int(round(cx - pct_w / 2.0)), int(round(pct_y)))

        # module status label: ~15 px below the percent label
        mod_fm = QFontMetricsF(self._module_label.font())
        mod_h = math.ceil(mod_fm.height())
        mod_y = pct_y + pct_h + 15.0
        self._module_label.setFixedSize(int(round(w * 0.8)), mod_h)
        self._module_label.move(int(round(cx - w * 0.4)), int(round(mod_y)))

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        self._relayout()

    # ── painting (black panel + flash overlay) ───────────────────────

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()

        clip = QPainterPath()
        clip.addRect(rect)
        painter.save()
        painter.setClipPath(clip)

        painter.fillRect(rect, QColor("#000000"))

        # optional faint background image
        if self._background is not None:
            bg = self._background
            bw, bh = bg.width(), bg.height()
            if bw > 0 and bh > 0:
                scale = max(rect.width() / bw, rect.height() / bh)
                dw = bw * scale
                dh = bh * scale
                dx = (rect.width() - dw) / 2.0
                dy = (rect.height() - dh) / 2.0
                painter.setOpacity(0.20)
                painter.drawPixmap(dx, dy, dw, dh, bg)
                painter.setOpacity(1.0)
        painter.restore()

        if self._compact:
            pen_color = QColor(255, 255, 255, 26)
            painter.setPen(pen_color)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect.adjusted(1, 1, -1, -1))

        # flash overlay: brief white pulse painted ON TOP of everything
        if self._flash_overlay > 0.01:
            painter.setOpacity(self._flash_overlay * 0.45)
            painter.fillRect(rect, QColor("#ffffff"))

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
        self._start_module_cycle()
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
        if self._module_timer is not None:
            self._module_timer.stop()
            self._module_timer = None
        self._ease_to(100)
        if self._reduce_motion:
            wait_ms = min(900, MIN_VISIBLE_MS)
            QTimer.singleShot(wait_ms + 500, lambda: self._reveal(main_window))
        else:
            wait_ms = max(0, MIN_VISIBLE_MS - int(self._elapsed.elapsed()))
            # ease(~650ms) + flash(~300ms) + 500ms pause
            QTimer.singleShot(wait_ms + 1000, lambda: self._reveal(main_window))

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
        # alpha: 140 → 255 as progress grows (no stylesheet — QPalette only)
        alpha = int(_lerp(140, 255, self._percent / 100.0))
        _set_label_color(self._percent_label, QColor(255, 255, 255, alpha))
        # fill and percent are always in sync
        self._fill.set_progress(self._percent)
        # trigger flash when reaching 100 %
        if percent >= 100 and self._flash_anim is None:
            self._trigger_flash()

    def _trigger_flash(self) -> None:
        """Brief white overlay pulse on the entire splash at 100 %."""
        anim = QVariantAnimation(self)
        anim.setStartValue(0.0)
        anim.setKeyValueAt(0.2, 1.0)
        anim.setEndValue(0.0)
        anim.setDuration(_FLASH_MS)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.valueChanged.connect(self._set_flash_overlay)
        anim.start()
        self._flash_anim = anim

    def _set_flash_overlay(self, value: float) -> None:
        self._flash_overlay = max(0.0, min(1.0, float(value)))
        self.update()

    # ── module loading status ───────────────────────────────────────

    def _start_module_cycle(self) -> None:
        self._module_timer = QTimer(self)
        self._module_timer.setInterval(600)
        self._module_timer.timeout.connect(self._next_module)
        self._module_timer.start()
        self._next_module()

    def _next_module(self) -> None:
        if self._completed:
            return
        idx = self._module_index % len(_MODULE_LINES_EN)
        self._module_label.setText(_MODULE_LINES_EN[idx] + "...")
        self._module_index += 1

    # ── reveal / close ──────────────────────────────────────────────

    def _reveal(self, main_window: QWidget) -> None:
        if self._finish_callback is not None:
            try:
                self._finish_callback(main_window)
            except Exception:
                logger.debug("splash: finish callback raised", exc_info=True)
        if main_window is not None:
            main_window.raise_()
            main_window.activateWindow()
        if self._reduce_motion:
            self._close_splash()
            return
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
        if self._module_timer is not None:
            self._module_timer.stop()
        self._fill.stop()
        self.hide()
        self.close()
        self.deleteLater()
