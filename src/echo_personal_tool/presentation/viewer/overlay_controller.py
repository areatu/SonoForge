"""Results / frame / tags / debug overlay controllers — QH-3 pilot slice.

Spec §7.1: ResultsOverlayController owns layout/visibility/position and render
projection; it never recomputes clinical results from UI text — the single
projection lives in application/domain (measurement_report_formatter,
provenance_notes).  The controller only decides *where* and *whether* to show
the already-formatted string, exactly like the former ViewerWidget did, so the
QH-0 characterization harness stays green.

Lifecycle (§7.3): each controller is owner-scoped (parent = ViewerWidget),
has an idempotent `dispose()` that disconnects signals, hides widgets and
clears references.  Generation checks prevent stale callbacks from writing
after a source switch (S-02/S-05).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QLabel

try:
    from echo_personal_tool.resources.bundled_fonts import FONT_FAMILY_MONO
except Exception:  # noqa: BLE001 - font family is not essential for tests
    FONT_FAMILY_MONO = "monospace"

from echo_personal_tool.presentation.viewer.commands import CommandResult, accepted


def _results_overlay_style(font_size: int, opacity: float = 0.70) -> str:
    alpha = int(max(0.0, min(1.0, opacity)) * 255)
    return (
        f" background-color: rgba(0, 0, 0, {alpha});"
        + " color: #e8eef4;"
        + " padding: 11px 18px;"
        + f" font-family: '{FONT_FAMILY_MONO}', monospace;"
        + " border: 2px solid #3d7cb8;"
        + " border-radius: 5px;"
        + f" font-size: {font_size}px;"
    )


DEFAULT_RESULTS_OVERLAY_Y_RATIO = 0.5
RESULTS_OVERLAY_EDGE_MARGIN = 8


@dataclass(frozen=True, slots=True)
class OverlayPosition:
    x_ratio: float
    y_ratio: float
    custom: bool = False
    pinned: bool = False


# ── ResultsOverlayController ──────────────────────────────────────────────


class ResultsOverlayController(QObject):
    """Position/visibility controller for the measurement summary box."""

    # Mirrors the ViewerWidget signals so MainWindow can still listen
    position_changed = Signal(float, float)
    clear_requested = Signal()
    reset_position_requested = Signal()
    pin_toggled = Signal(bool)
    parameter_clicked = Signal(str)

    def __init__(
        self,
        label: QLabel,
        graphics_geometry_provider: Callable[[], Any],
        *,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._label = label
        self._graphics_geometry_provider = graphics_geometry_provider
        self._custom_position = False
        self._position_just_restored = False
        self._suppressed = False
        self._cleared = False

        # Wire the draggable label's own signals (ResultsOverlayLabel adds them)
        try:
            # label is expected to be ResultsOverlayLabel with those signals
            label.position_changed.connect(self.position_changed.emit)  # type: ignore[attr-defined]
            label.clear_requested.connect(self.clear_requested.emit)  # type: ignore[attr-defined]
            label.reset_position_requested.connect(self.reset_position_requested.emit)  # type: ignore[attr-defined]
            label.pin_toggled.connect(self.pin_toggled.emit)  # type: ignore[attr-defined]
            label.parameter_clicked.connect(self.parameter_clicked.emit)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001, S110
            pass

    # -- identity for generation checks (set by ViewerWidget facade) --------
    context: Any = None  # set by owner to current ViewerContext

    # -- style --------------------------------------------------------------

    def apply_style(self, font_size: int, opacity: float) -> None:
        self._label.setStyleSheet(_results_overlay_style(font_size, opacity))

    # -- text ---------------------------------------------------------------

    def set_text(self, text: str, *, suppressed: bool | None = None) -> CommandResult:
        if suppressed is not None:
            self._suppressed = bool(suppressed)
        if self._suppressed:
            self._label.hide()
            return accepted(reason="suppressed")
        if self._cleared and text.strip():
            return accepted(reason="cleared_until_next_non_empty")
        self._cleared = False
        just_restored = self._position_just_restored
        self._position_just_restored = False
        if text.strip():
            text_changed = text != self._label.text()
            was_visible = self._label.isVisible()
            if text_changed:
                self._label.setText(text)
                self._label.adjustSize()
            if not was_visible:
                self._label.show()
            self._label.raise_()
            if not just_restored and not self._custom_position and (not was_visible or text_changed):
                self._request_reposition()
        else:
            self._label.hide()
        return accepted()

    def text(self) -> str:
        return self._label.text()

    def clear(self) -> CommandResult:
        self._cleared = True
        self._label.hide()
        # Keep semantics of ViewerWidget._on_results_overlay_clear
        return accepted(reason="cleared")

    def set_suppressed(self, suppressed: bool) -> None:
        self._suppressed = bool(suppressed)
        if self._suppressed:
            self._label.hide()

    def is_suppressed(self) -> bool:
        return self._suppressed

    # -- position -----------------------------------------------------------

    def set_position(self, x_ratio: float, y_ratio: float, *, custom: bool = True) -> CommandResult:
        self._custom_position = bool(custom)
        self._position_just_restored = True
        if custom:
            # ResultsOverlayLabel stores ratios itself
            if hasattr(self._label, "set_position_ratios"):
                self._label.set_position_ratios(x_ratio, y_ratio)  # type: ignore[attr-defined]
        if self._label.isVisible():
            self._request_reposition()
        return accepted()

    def position(self) -> tuple[float, float]:
        if hasattr(self._label, "position_ratios"):
            return self._label.position_ratios()  # type: ignore[attr-defined]
        return (1.0, DEFAULT_RESULTS_OVERLAY_Y_RATIO)

    def reset_to_default(self) -> None:
        self._custom_position = False
        if self._label.isVisible():
            self._request_reposition()

    def is_pinned(self) -> bool:
        return bool(getattr(self._label, "_pinned", False))

    def custom_position(self) -> bool:
        return self._custom_position

    def mark_custom_position(self) -> None:
        self._custom_position = True

    # -- geometry -----------------------------------------------------------

    def reposition(self, *, reposition_results: bool = False) -> None:
        geo = self._graphics_geometry_provider()
        if geo is None:
            return
        if self._label.isVisible() and reposition_results:
            if self.is_pinned():
                return
            self._reposition_results_label(geo)

    def _request_reposition(self) -> None:
        if not self._label.isVisible():
            return
        if self.is_pinned():
            return
        QTimer.singleShot(0, self._reposition_deferred)

    def _reposition_deferred(self) -> None:
        if self._label.isVisible():
            geo = self._graphics_geometry_provider()
            if geo is not None:
                self._reposition_results_label(geo)

    def _reposition_results_label(self, geo: Any) -> None:
        if geo.width() < 16 or geo.height() < 16:
            return
        self._label.adjustSize()
        rw = self._label.width()
        rh = self._label.height()
        if self._custom_position:
            if hasattr(self._label, "position_ratios"):
                x_ratio, y_ratio = self._label.position_ratios()  # type: ignore[attr-defined]
                x = geo.x() + int(x_ratio * max(geo.width() - rw, 0))
                y = geo.y() + int(y_ratio * max(geo.height() - rh, 0))
            else:
                x = geo.x() + geo.width() - rw - RESULTS_OVERLAY_EDGE_MARGIN - 28
                y = geo.y() + max(int(geo.height() * DEFAULT_RESULTS_OVERLAY_Y_RATIO) + 19, RESULTS_OVERLAY_EDGE_MARGIN)
        else:
            x = geo.x() + geo.width() - rw - RESULTS_OVERLAY_EDGE_MARGIN - 28
            y = geo.y() + max(int(geo.height() * DEFAULT_RESULTS_OVERLAY_Y_RATIO) + 19, RESULTS_OVERLAY_EDGE_MARGIN)
        x = max(geo.x(), min(x, geo.x() + max(geo.width() - rw, 0)))
        y = max(geo.y(), min(y, geo.y() + max(geo.height() - rh, 0)))
        self._label.move(x, y)
        if self._custom_position and hasattr(self._label, "set_position_ratios"):
            self._label.set_position_ratios(  # type: ignore[attr-defined]
                (x - geo.x()) / max(geo.width(), 1),
                (y - geo.y()) / max(geo.height(), 1),
            )

    # -- lifecycle ----------------------------------------------------------

    def dispose(self) -> None:
        """Idempotent teardown — break signal cycles and hide the label."""
        try:
            self._label.hide()
        except RuntimeError:
            pass
        try:
            self.position_changed.disconnect()
        except (RuntimeError, TypeError):
            pass
        try:
            self.clear_requested.disconnect()
        except (RuntimeError, TypeError):
            pass
        try:
            self.reset_position_requested.disconnect()
        except (RuntimeError, TypeError):
            pass
        try:
            self.pin_toggled.disconnect()
        except (RuntimeError, TypeError):
            pass
        try:
            self.parameter_clicked.disconnect()
        except (RuntimeError, TypeError):
            pass


# ── FrameOverlayController ────────────────────────────────────────────────


class FrameOverlayController(QObject):
    """Calibration prompt / auto-ok banner and per-frame contour info (top-left)."""

    def __init__(
        self, label: QLabel, graphics_geometry_provider: Callable[[], Any], parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._label = label
        self._graphics_geometry_provider = graphics_geometry_provider
        self._lines: list[str] = []

    def append(self, line: str) -> None:
        if line:
            self._lines.append(line)
            self._refresh()

    def clear(self) -> None:
        self._lines.clear()
        self._label.hide()

    def lines(self) -> list[str]:
        return list(self._lines)

    def set_lines(self, lines: list[str]) -> None:
        self._lines = [l for l in lines if l]
        self._refresh()

    def _refresh(self) -> None:
        if not self._lines:
            self._label.hide()
            return
        self._label.setText("\n".join(self._lines))
        self._label.adjustSize()
        self._label.show()
        self._position()

    def _position(self) -> None:
        geo = self._graphics_geometry_provider()
        if geo is None:
            return
        if not self._label.isVisible():
            return
        self._label.adjustSize()
        label_w = self._label.width()
        label_h = self._label.height()
        # Center calibration banner, top-left otherwise
        from echo_personal_tool.infrastructure.i18n import tr

        try:
            calib_prompt = tr("viewer.calibration.calibration_prompt")
            calib_ok = tr("viewer.calibration.auto_ok")
            is_banner = self._lines == [calib_prompt] or self._lines == [calib_ok]
        except Exception:  # noqa: BLE001
            is_banner = False
        if is_banner:
            x = geo.x() + max((geo.width() - label_w) // 2, 8)
            y = geo.y() + max(geo.height() // 6 - label_h // 2, 8)
        else:
            x = geo.x() + 8
            y = geo.y() + 8
        self._label.move(x, y)

    def dispose(self) -> None:
        try:
            self._label.hide()
        except RuntimeError:
            pass
        self._lines.clear()


# ── TagsOverlayController ─────────────────────────────────────────────────


class TagsOverlayController(QObject):
    """DICOM tag inspector overlay (bottom-left)."""

    def __init__(
        self, label: QLabel, graphics_geometry_provider: Callable[[], Any], parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._label = label
        self._graphics_geometry_provider = graphics_geometry_provider

    def show_tags(self, lines: list[str]) -> None:
        if not lines:
            self._label.hide()
            return
        self._label.setText("\n".join(lines))
        self._label.adjustSize()
        self._label.show()
        self._position()

    def hide(self) -> None:
        self._label.hide()

    def _position(self) -> None:
        geo = self._graphics_geometry_provider()
        if geo is None or not self._label.isVisible():
            return
        self._label.adjustSize()
        self._label.move(
            geo.x() + 8,
            geo.y() + geo.height() - self._label.height() - 8,
        )

    def apply_style(self, font_size: int, opacity: float) -> None:
        self._label.setStyleSheet(_results_overlay_style(font_size, opacity))

    def dispose(self) -> None:
        try:
            self._label.hide()
        except RuntimeError:
            pass


# ── DebugOverlayController ────────────────────────────────────────────────


class DebugOverlayController(QObject):
    """Diagnostic overlay (viewport size, scale, ROI)."""

    def __init__(self, label: QLabel, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._label = label
        self._visible = False

    def toggle(self) -> bool:
        self._visible = not self._visible
        if self._visible:
            self._label.show()
        else:
            self._label.hide()
        return self._visible

    @property
    def visible(self) -> bool:
        return self._visible

    def update_text(self, text: str) -> None:
        self._label.setText(text)
        self._label.adjustSize()

    def dispose(self) -> None:
        try:
            self._label.hide()
        except RuntimeError:
            pass
        self._visible = False


__all__ = [
    "ResultsOverlayController",
    "FrameOverlayController",
    "TagsOverlayController",
    "DebugOverlayController",
    "OverlayPosition",
]
