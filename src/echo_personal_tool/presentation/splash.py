"""Startup splash screen in the style of AnythingLLM Desktop.

Design (AnythingLLM-inspired, but on-brand for SonoForge):

    • small frameless always-on-top window, fixed size, centered on screen
    • dark clinical gradient background (follows the active theme palette)
    • brand block: official logo tile + “SonoForge” wordmark + localized tagline
    • thin circular spinner (accent color, rotating arc with a gap)
    • one-line status text that changes between startup stages
    • soft fade-out into the maximized main window, no white flash

The splash never reports fake percentages; it only shows cosmetic stage
labels while the real (synchronous) startup work happens between
``set_status`` calls, then guarantees a pleasant *minimum* display time
before revealing the main window.

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
    QRectF,
    Qt,
    QTimer,
    QVariantAnimation,
)
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.resources.bundled_fonts import FONT_FAMILY_UI

# ── Public timing constants (tweak here; all in ms) ─────────────────
MIN_VISIBLE_MS = 3400  # splash stays at least this long after show()
STAGE_INTERVAL_MS = 850  # each status line is shown for this long
FADE_OUT_MS = 360  # cross-fade into the main window
SPIN_REVOLUTION_MS = 900  # one full spinner turn

# ── Geometry ────────────────────────────────────────────────────────
WINDOW_W = 520
WINDOW_H = 352
_CORNER_RADIUS = 16


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


def _hex_to_qcolor(value: str, alpha: int = 255) -> QColor:
    color = QColor(value if value.startswith("#") else f"#{value}")
    color.setAlpha(alpha)
    return color


def _luminance(hex_color: str) -> float:
    c = QColor(hex_color if hex_color.startswith("#") else f"#{hex_color}")
    return (0.2126 * c.red() + 0.7152 * c.green() + 0.0722 * c.blue()) / 255.0


def _lighten(hex_color: str, amount: float) -> str:
    """Lighten (amount > 0) or darken (amount < 0) a #rrggbb color by [0..1]."""
    c = QColor(hex_color if hex_color.startswith("#") else f"#{hex_color}")
    factor = 1.0 + amount
    r = min(255, max(0, int(round(c.red() * factor))))
    g = min(255, max(0, int(round(c.green() * factor))))
    b = min(255, max(0, int(round(c.blue() * factor))))
    return f"#{r:02x}{g:02x}{b:02x}"


def _logo_path_for(theme_mode: str) -> Path:
    """Pick the logo variant that contrasts with the splash background."""
    from echo_personal_tool.presentation.dark_theme import get_logo_path

    base = Path(__file__).resolve().parent.parent / "resources"
    name = "logo.png"
    if theme_mode in {"dark", "vscode_dark"}:
        name = "logo_dark.png"
    elif theme_mode == "system":
        from echo_personal_tool.presentation.dark_theme import _is_system_dark

        name = "logo_dark.png" if _is_system_dark() else "logo.png"
    path = base / name
    if path.exists():
        return path
    return Path(get_logo_path())


class _ArcSpinner(QWidget):
    """Thin circular spinner: rotating arc with a small gap (AnythingLLM style)."""

    def __init__(self, accent: QColor, track: QColor, size: int = 38, pen_width: int = 3) -> None:
        super().__init__()
        self._accent = accent
        self._track = track
        self._angle = 0.0
        self._pen_width = pen_width
        self._anim: QVariantAnimation | None = None
        self.setFixedSize(size, size)

    def start(self) -> None:
        if self._anim is not None:
            return
        anim = QVariantAnimation(self)
        anim.setStartValue(0.0)
        anim.setEndValue(360.0)
        anim.setDuration(SPIN_REVOLUTION_MS)
        anim.setLoopCount(-1)
        anim.valueChanged.connect(self._on_tick)
        anim.start()
        self._anim = anim

    def stop(self) -> None:
        if self._anim is not None:
            self._anim.stop()
            self._anim.deleteLater()
            self._anim = None

    def _on_tick(self, value) -> None:
        self._angle = float(value)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        margin = float(self._pen_width) / 2.0 + 1.0
        rect = QRectF(self.rect()).adjusted(margin, margin, -margin, -margin)
        # faint full ring (track)
        track_pen = QPen(self._track, self._pen_width)
        track_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(track_pen)
        painter.drawEllipse(rect)
        # bright rotating arc, 300° span -> 60° gap
        arc_pen = QPen(self._accent, self._pen_width)
        arc_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(arc_pen)
        span = 300.0 * 16
        painter.drawArc(rect, int(round(self._angle * 16.0)), int(round(span)))
        painter.end()


class _PulseDot(QWidget):
    """Small accent dot that gently pulses — subtle heartbeat cue for clinicians."""

    def __init__(self, accent: QColor, size: int = 7) -> None:
        super().__init__()
        self._accent = accent
        self._level = 1.0
        self._anim: QVariantAnimation | None = None
        self.setFixedSize(size, size)

    def start(self) -> None:
        if self._anim is not None:
            return
        anim = QVariantAnimation(self)
        anim.setStartValue(0.25)
        anim.setEndValue(1.0)
        anim.setDuration(1100)
        anim.setLoopCount(-1)
        anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        anim.valueChanged.connect(self._on_tick)
        anim.start()
        self._anim = anim

    def stop(self) -> None:
        if self._anim is not None:
            self._anim.stop()
            self._anim.deleteLater()
            self._anim = None

    def _on_tick(self, value) -> None:
        self._level = float(value)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(self._accent)
        color.setAlphaF(0.35 + 0.65 * self._level)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        r = self.width() / 2.0
        painter.drawEllipse(QRectF(self.width() / 2.0 - r, self.height() / 2.0 - r, 2 * r, 2 * r))
        painter.end()


class SplashScreen(QWidget):
    """Frameless, centered startup splash.

    Usage::

        splash = SplashScreen(stages=(tr("splash.stage.starting"), ...),
                              tagline=tr("splash.tagline"),
                              theme_mode=preferences.theme_mode,
                              reduce_motion=preferences.reduce_motion)
        splash.show_and_play()
        # ... do real startup work, calling splash.set_status(...) between steps ...
        splash.complete_with(window, on_complete=reveal_window)
        result = app.exec()
    """

    def __init__(
        self,
        *,
        stages: tuple[str, ...],
        tagline: str,
        theme_mode: str = "dark",
        reduce_motion: bool = False,
        app_name: str = "SonoForge",
    ) -> None:
        super().__init__(None)
        self._app_name = app_name
        self._stages = stages
        self._reduce_motion = reduce_motion
        self._completed = False
        self._finish_callback: callable | None = None
        self._elapsed = QElapsedTimer()
        self._stage_index = 0
        self._fade: QPropertyAnimation | None = None

        self._palette = self._resolve_palette(theme_mode)
        self._is_dark = _luminance(self._palette["bg_dark"]) < 0.5

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setWindowTitle(app_name)

        self._build_ui(theme_mode)
        self._center_on_screen()

    # ── palette ─────────────────────────────────────────────────────

    @staticmethod
    def _resolve_palette(theme_mode: str) -> dict[str, str]:
        """Return the SonoForge palette dict for *theme_mode* (dark default)."""
        try:
            from echo_personal_tool.presentation.dark_theme import _resolve_theme

            return _resolve_theme(theme_mode)
        except Exception:  # pragma: no cover - defensive fallback
            return {
                "bg_dark": "#102135",
                "bg_panel": "#12273d",
                "bg_control": "#1a3050",
                "bg_button": "#244161",
                "accent": "#40e2de",
                "accent_bright": "#5ff0ea",
                "text": "#f1f5f9",
                "text_dim": "#9bacbb",
                "border": "#2a4a6b",
            }

    # ── UI ──────────────────────────────────────────────────────────

    def _build_ui(self, theme_mode: str) -> None:
        p = self._palette
        accent = _hex_to_qcolor(p["accent"])
        text_color = p["text"]
        dim_color = p["text_dim"]

        root = QWidget(self)
        root.setGeometry(0, 0, WINDOW_W, WINDOW_H)
        self._root = root

        # accent underline drawn under the wordmark
        accent_line = QWidget(root)
        accent_line.setFixedSize(46, 2)
        accent_line.setStyleSheet(f"background: {p['accent']}; border-radius: 1px;")
        accent_line.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._accent_line = accent_line

        # logo tile + wordmark lockup
        logo_path = _logo_path_for(theme_mode)
        tile = QLabel(root)
        tile.setFixedSize(64, 64)
        tile.setStyleSheet(
            "border-radius: 16px; border: 1px solid rgba(255,255,255,0.07);"
            f"background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {_tile_top(p)}, stop:1 {_tile_bottom(p)});"
        )
        tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if logo_path.exists():
            pm = QPixmap(str(logo_path))
            if not pm.isNull():
                tile.setPixmap(
                    pm.scaled(
                        44,
                        44,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
        self._logo_tile = tile

        wordmark = QLabel(self._app_name, root)
        wordmark.setFont(_font(26, weight=QFont.Weight.DemiBold))
        wordmark.setStyleSheet(f"color: {text_color}; background: transparent;")
        wordmark.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        self._wordmark = wordmark

        tagline = QLabel(tagline, root)
        tagline.setFont(_font(12))
        tagline.setStyleSheet(f"color: {dim_color}; background: transparent;")
        tagline.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        self._tagline = tagline

        # brand row: tile left of the stacked wordmark/tagline
        brand_text_col = QWidget(root)
        brand_text_col.setStyleSheet("background: transparent;")
        brand_text_col_layout = QVBoxLayout(brand_text_col)
        brand_text_col_layout.setContentsMargins(0, 0, 0, 0)
        brand_text_col_layout.setSpacing(3)
        brand_text_col_layout.addWidget(wordmark)
        brand_text_col_layout.addWidget(tagline)
        brand_text_col_layout.addWidget(accent_line, alignment=Qt.AlignmentFlag.AlignHCenter)

        brand_row = QWidget(root)
        brand_row.setStyleSheet("background: transparent;")
        row = QHBoxLayout(brand_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(18)
        row.addWidget(tile, alignment=Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(brand_text_col, alignment=Qt.AlignmentFlag.AlignVCenter)

        # spinner
        track = QColor(accent)
        track.setAlphaF(0.18)
        self._spinner = _ArcSpinner(accent, track)
        if not self._reduce_motion:
            self._spinner.start()

        # status row: pulsing dot + label
        status_row = QWidget(root)
        status_row.setStyleSheet("background: transparent;")
        status_layout = QHBoxLayout(status_row)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(9)
        self._pulse_dot = _PulseDot(accent)
        if not self._reduce_motion:
            self._pulse_dot.start()
        status_layout.addWidget(self._pulse_dot, alignment=Qt.AlignmentFlag.AlignVCenter)

        self._status_label = QLabel("", root)
        self._status_label.setFont(_font(13))
        self._status_label.setStyleSheet(f"color: {dim_color}; background: transparent;")
        status_layout.addWidget(self._status_label)

        # vertical stack, everything centered
        column = QVBoxLayout(root)
        column.setContentsMargins(44, 40, 44, 40)
        column.setSpacing(0)
        column.addStretch(1)
        column.addWidget(brand_row, alignment=Qt.AlignmentFlag.AlignHCenter)
        column.addSpacing(26)
        column.addWidget(self._spinner, alignment=Qt.AlignmentFlag.AlignHCenter)
        column.addSpacing(18)
        column.addWidget(status_row, alignment=Qt.AlignmentFlag.AlignHCenter)
        column.addStretch(2)

        if self._stages:
            self.set_status(self._stages[0])

    # ── public API ──────────────────────────────────────────────────

    def show_and_play(self) -> SplashScreen:
        """Show the splash and start the spinner / stage sequence."""
        self.show()
        self._elapsed.start()
        if not self._reduce_motion and self._stages:
            self._schedule_next_stage()
        return self

    def set_status(self, text: str | None) -> None:
        """Force the status line to *text* (also used to sync after real work)."""
        if text is None or not hasattr(self, "_status_label"):
            return
        self._status_label.setText(text)

    def complete_with(self, main_window: QWidget, on_complete: callable | None = None) -> None:
        """Signal that startup finished.

        The main window stays hidden until the splash's minimum display time
        has elapsed; then *on_complete* is invoked (reveal the main window)
        and the splash fades out.
        """
        if self._completed:
            return
        self._completed = True
        self._finish_callback = on_complete
        if self._stages:
            self.set_status(self._stages[-1])

        if self._reduce_motion:
            wait_ms = min(900, MIN_VISIBLE_MS)
        else:
            wait_ms = max(0, MIN_VISIBLE_MS - int(self._elapsed.elapsed()))
        QTimer.singleShot(wait_ms, lambda: self._reveal(main_window))

    # ── internals ───────────────────────────────────────────────────

    def _schedule_next_stage(self) -> None:
        QTimer.singleShot(STAGE_INTERVAL_MS, self._tick_stage)

    def _tick_stage(self) -> None:
        if self._completed:
            return
        self._stage_index += 1
        if self._stage_index < len(self._stages):
            self.set_status(self._stages[self._stage_index])
            self._schedule_next_stage()

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
        # fade out over the (now visible) main window — no desktop flash.
        # windowOpacity is the native property (works with WA_TranslucentBackground).
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
        self._spinner.stop()
        if hasattr(self, "_pulse_dot"):
            self._pulse_dot.stop()
        self.hide()
        self.close()
        self.deleteLater()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        """Draw the rounded gradient panel + hairline border."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        p = self._palette
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        top = _lighten(p["bg_dark"], 0.10 if self._is_dark else 0.0)
        top = "#ffffff" if not self._is_dark else top
        gradient = QLinearGradient(0, 0, 0, WINDOW_H)
        gradient.setColorAt(0.0, QColor(top))
        gradient.setColorAt(1.0, QColor(p["bg_dark"]))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawRoundedRect(rect, _CORNER_RADIUS, _CORNER_RADIUS)

        # subtle top accent sheen
        if self._is_dark:
            sheen = QLinearGradient(0, 0, 0, WINDOW_H)
            sheen.setColorAt(0.0, _hex_to_qcolor(p["accent"], alpha=26))
            sheen.setColorAt(0.25, _hex_to_qcolor(p["accent"], alpha=0))
            painter.setBrush(sheen)
            painter.drawRoundedRect(rect, _CORNER_RADIUS, _CORNER_RADIUS)

        border = QColor(p["border"])
        border.setAlpha(160 if self._is_dark else 170)
        pen = QPen(border, 1)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(pen)
        painter.drawRoundedRect(rect, _CORNER_RADIUS, _CORNER_RADIUS)
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


def _tile_top(p: dict[str, str]) -> str:
    base = p.get("bg_control", "#1a3050")
    return _lighten(base, 0.08)


def _tile_bottom(p: dict[str, str]) -> str:
    base = p.get("bg_control", "#1a3050")
    if _luminance(base) < 0.5:
        return _lighten(base, -0.14)
    return _lighten(base, -0.04)


def _font(point_size: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    font = QFont(FONT_FAMILY_UI, point_size)
    font.setWeight(weight)
    return font
