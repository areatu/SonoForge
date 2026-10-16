"""Dark clinical theme for the presentation layer.

Facade of the design-token package (UI-0, PR-1). The colours live in
:mod:`echo_personal_tool.presentation.theme.palettes`, the semantic roles in
:mod:`echo_personal_tool.presentation.theme.tokens`, and the stylesheet is
assembled from the tokens in :mod:`echo_personal_tool.presentation.theme.qss`.

The public API of this module is unchanged: ``get_theme_palette()`` still
returns the legacy 28-key palette (computed from the tokens),
``build_clinical_stylesheet()`` still returns the same sheet, and the module
constants still describe the dark theme. The calls are moved to the tokens
one area at a time (UI-0 PR-3…PR-7); the legacy palette disappears in UI-8.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget

from echo_personal_tool.presentation.theme.palettes import (
    LEGACY_PALETTES,
    LEGACY_SLIDER_FILL,
    LEGACY_SLIDER_TRACK,
    get_palette_tokens,
    is_dark_theme,
)
from echo_personal_tool.presentation.theme.qss import build_clinical_stylesheet as _build_stylesheet
from echo_personal_tool.presentation.theme.system_theme import is_system_dark as _system_is_dark
from echo_personal_tool.presentation.theme.system_theme import resolve_theme_id

# ── Legacy palettes (28 keys, computed from the tokens) ───────────
_DARK = LEGACY_PALETTES["dark"]
_LIGHT = LEGACY_PALETTES["light"]
_VS_CODE_DARK = LEGACY_PALETTES["vscode_dark"]
_VS_CODE_LIGHT = LEGACY_PALETTES["vscode_light"]

# Backward-compatible module-level constants (dark theme defaults)
BG_DARK = _DARK["bg_dark"]
BG_PANEL = _DARK["bg_panel"]
BG_CONTROL = _DARK["bg_control"]
BG_BUTTON = _DARK["bg_button"]
BG_BUTTON_HOVER = _DARK["bg_button_hover"]
BG_BUTTON_PRESSED = _DARK["bg_button_pressed"]
ACCENT = _DARK["accent"]
ACCENT_BRIGHT = _DARK["accent_bright"]
ACCENT_TAB = _DARK["accent_tab"]
TEXT = _DARK["text"]
TEXT_DIM = _DARK["text_dim"]
BORDER = _DARK["border"]
SLIDER_TRACK = LEGACY_SLIDER_TRACK
SLIDER_FILL = LEGACY_SLIDER_FILL

_current_theme_mode = "dark"


def get_theme_palette() -> dict[str, str]:
    """Return the active theme palette dict."""
    return _resolve_theme(_current_theme_mode)


def get_theme_tokens() -> dict[str, str]:
    """Return the design tokens of the active theme (UI-0, PR-3).

    The migration entry point of the redesign (§5.3): a widget asks for a
    *role* (``"text.1"``, ``"state.warn"``) instead of a legacy palette key
    (``"text"``, ``"warning"``), so the same code paints every theme — a theme
    is one dict of values, never a branch in the widget. The mapping is a
    copy: a caller cannot change the palette of a theme.

    Together with :func:`get_theme_palette` this function leaves the facade in
    UI-8, when the last call site is moved to the tokens.
    """
    return get_palette_tokens(resolve_theme_id(_current_theme_mode))


def get_logo_path() -> Path:
    """Return the logo path matching the current theme (dark/inverted or light/original)."""
    _base = Path(__file__).resolve().parent.parent / "resources"
    is_dark = _is_dark_theme(_current_theme_mode)
    name = "logo_dark.png" if is_dark else "logo.png"
    path = _base / name
    return path if path.exists() else _base / "logo.png"


def _is_dark_theme(mode: str) -> bool:
    """Tell whether a theme mode paints a dark background."""
    return is_dark_theme(resolve_theme_id(mode))


def _is_system_dark() -> bool:
    """Detect system dark mode on Windows/macOS/Linux."""
    return _system_is_dark()


_THEME_MAP = {
    "dark": _DARK,
    "light": _LIGHT,
    "vscode_dark": _VS_CODE_DARK,
    "vscode_light": _VS_CODE_LIGHT,
    "graphite": LEGACY_PALETTES["graphite"],
}


def _resolve_theme_id(mode: str) -> str:
    """Return the concrete theme id of a theme mode ("system" follows the OS)."""
    return resolve_theme_id(mode)


def _resolve_theme(mode: str) -> dict[str, str]:
    """Return the palette of a theme mode ("system" follows the OS)."""
    return _THEME_MAP.get(resolve_theme_id(mode), _DARK)


def build_clinical_stylesheet(font_size: int = 13, *, theme: str = "dark") -> str:
    """Build the application stylesheet of a theme from the design tokens."""
    return _build_stylesheet(font_size, theme)


def apply_clinical_theme(
    widget: QWidget | None = None,
    *,
    font_size: int = 13,
    theme: str = "dark",
    animate: bool = True,
) -> None:
    """Apply palette to the whole app. *theme* is 'dark', 'light', or 'system'."""
    global _current_theme_mode
    _current_theme_mode = theme
    app = QApplication.instance()
    if app is None:
        return
    if animate and widget is not None:
        _fade_theme_transition(widget, font_size, theme)
    else:
        _apply_theme_direct(app, widget, font_size, theme)


def _apply_theme_direct(
    app: QApplication,
    widget: QWidget | None,
    font_size: int,
    theme: str,
) -> None:
    stylesheet = build_clinical_stylesheet(font_size, theme=theme)
    # Reapplying an identical app-wide sheet repolishes every open/hidden
    # dialog. Avoid that work when a window is opened without a theme change.
    if app.styleSheet() != stylesheet:
        app.setStyleSheet(stylesheet)
    p = _resolve_theme(theme)
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(p["bg_panel"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(p["text"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(p["bg_dark"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(p["bg_control"]))
    palette.setColor(QPalette.ColorRole.Text, QColor(p["text"]))
    palette.setColor(QPalette.ColorRole.Button, QColor(p["bg_button"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(p["text"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(p["accent_tab"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(p["text"]))
    app.setPalette(palette)
    if widget is not None:
        widget.setPalette(palette)


def _fade_theme_transition(widget: QWidget, font_size: int, theme: str) -> None:
    from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QTimer
    from PySide6.QtWidgets import QGraphicsOpacityEffect, QMainWindow

    from echo_personal_tool.presentation.ui_animations import _reduce_motion_enabled

    app = QApplication.instance()
    if app is None:
        return
    _apply_theme_direct(app, widget, font_size, theme)
    if _reduce_motion_enabled():
        return
    try:
        import shiboken6

        if not shiboken6.isValid(widget):
            return
    except ImportError:
        pass
    # PR1 stability: never attach a GraphicsEffect to a main window or any
    # window hosting a WebEngine view. With a live QWebEngineView/video
    # surface this is a known SIGSEGV path (theme switch then crashes, spawn
    # pool leaks semaphores). Plain widgets keep the fade (covered by
    # test_fade_theme_transition).
    if isinstance(widget, QMainWindow):
        return
    try:
        for child in widget.findChildren(QWidget):
            if "WebEngine" in type(child).__name__:
                return
    except RuntimeError:
        return
    try:
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
    except RuntimeError:
        return
    anim = QPropertyAnimation(effect, b"opacity")
    anim.setDuration(150)
    anim.setStartValue(0.6)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.Type.InOutQuad)

    def _cleanup() -> None:
        try:
            import shiboken6

            if shiboken6.isValid(widget):
                widget.setGraphicsEffect(None)
        except (ImportError, RuntimeError):
            pass

    anim.finished.connect(_cleanup)
    try:
        QTimer.singleShot(0, anim.start)
    except RuntimeError:
        _cleanup()
        return
    widget._theme_anim = anim
    widget._theme_effect = effect
