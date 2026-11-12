"""Label picker owner extracted from :class:`ViewerWidget` (A4).

``ViewerLabelPicker`` owns *only* the UI state of naming a fresh measurement:
the popup widget, the target it was opened for, whether naming is enabled, the
context override, and the caliper-label cycle the popup shares with ``Tab``.

It never reads or writes measurements, contours, the Doppler overlay or the
document.  When the popup commits a label the owner hands the option and the
target back to the viewer, which remains the single clinical owner.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QWidget

from echo_personal_tool.presentation.label_picker import LabelPicker

#: Labels the free-caliper cycle starts with.  The picker's catalog is the
#: source of available names; this list is only the order ``Tab`` walks when no
#: popup is open.
DEFAULT_CALIPER_LABELS: tuple[str, ...] = (
    "LVEDD",
    "LVESD",
    "IVSd",
    "LVPWd",
    "LVOT",
    "LA",
    "LAL",
    "RA",
    "RV basal",
    "TAPSE",
)

#: ``("contour", reference) | ("caliper", key) | ("trace", measurement_id)``.
LabelTarget = tuple[str, Any]


class ViewerLabelPicker:
    """One owner for the naming popup and the caliper-label cycle."""

    def __init__(
        self,
        *,
        parent: QWidget,
        apply_label: Callable[[object, LabelTarget], None],
        can_cycle_label: Callable[[], bool],
        cardiac_provider: Callable[[], bool],
    ) -> None:
        self._parent = parent
        self._apply_label = apply_label
        self._can_cycle_label = can_cycle_label
        self._cardiac_provider = cardiac_provider
        self._picker: LabelPicker | None = None
        self._enabled = True
        self._target: LabelTarget | None = None
        self._context_override: str | None = None
        self._cardiac_override: bool | None = None
        self._labels = list(DEFAULT_CALIPER_LABELS)
        self._label_index = 0

    # ── popup lifecycle ─────────────────────────────────────────────

    def picker(self) -> LabelPicker:
        """Return (creating if needed) the viewer's popup widget."""
        if self._picker is None:
            picker = LabelPicker(self._parent)
            picker.label_selected.connect(self._on_selected)
            picker.tab_cycled.connect(self._on_tab_cycled)
            picker.dismissed.connect(self._on_dismissed)
            self._picker = picker
        return self._picker

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        if not self._enabled:
            self.dismiss()

    @property
    def visible(self) -> bool:
        return self._picker is not None and not self._picker.isHidden()

    def offer(
        self,
        *,
        target: LabelTarget,
        value_text: str,
        context: str,
        anchor: QPoint | None = None,
        bounds: QRect | None = None,
    ) -> bool:
        """Open the popup for *target*; a disabled picker stays closed."""
        if not self._enabled:
            return False
        self._target = target
        self.picker().open_for(
            value_text=value_text,
            context=self._context_override or context,
            anchor=anchor,
            bounds=bounds,
        )
        return True

    def accept(self) -> bool:
        if not self.visible or self._picker is None:
            return False
        return bool(self._picker.accept_current())

    def dismiss(self) -> bool:
        self._target = None
        if self._picker is None or self._picker.isHidden():
            return False
        return bool(self._picker.dismiss())

    def handle_key(self, event: QKeyEvent) -> bool:
        if not self.visible or self._picker is None:
            return False
        return bool(self._picker.handle_key_press(event))

    def cycle_visible_selection(self, *, emit_tab: bool = False) -> bool:
        """Move the popup selection; return False when the popup is closed."""
        if not self.visible or self._picker is None:
            return False
        self._picker.cycle_next(emit_tab=emit_tab)
        return True

    def take_target(self) -> LabelTarget | None:
        """Take (and clear) the target of the open popup, if any."""
        target = self._target
        self._target = None
        return target

    def _on_selected(self, option: object) -> None:
        target = self.take_target()
        if target is not None:
            self._apply_label(option, target)

    def _on_tab_cycled(self) -> None:
        if self._can_cycle_label():
            self.cycle_label()

    def _on_dismissed(self) -> None:
        self._target = None

    # ── picker context and cardiac gate ─────────────────────────────

    @property
    def context_override(self) -> str | None:
        return self._context_override

    def set_context(self, context: str | None) -> None:
        value = context.strip().lower() if context and context.strip() else None
        self._context_override = value
        if self.visible and value and self._picker is not None:
            self._picker.set_context(value)

    def resolve_context(self, default_context: str) -> str:
        """The host-selected context wins over the measurement-derived one."""
        return self._context_override or default_context

    def set_cardiac_context(self, cardiac: bool | None) -> None:
        self._cardiac_override = None if cardiac is None else bool(cardiac)
        if not self.is_cardiac_context():
            self.dismiss()

    def is_cardiac_context(self) -> bool:
        if self._cardiac_override is not None:
            return self._cardiac_override
        return bool(self._cardiac_provider())

    # ── caliper-label cycle (shared with the popup's Tab key) ──────

    @property
    def labels(self) -> list[str]:
        return self._labels

    @labels.setter
    def labels(self, labels: list[str]) -> None:
        self._labels = list(labels)

    @property
    def label_index(self) -> int:
        return self._label_index

    @label_index.setter
    def label_index(self, index: int) -> None:
        self._label_index = int(index)

    def current_label(self) -> str:
        return self._labels[self._label_index]

    def set_label(self, label: str) -> None:
        if label not in self._labels:
            self._labels.append(label)
        self._label_index = self._labels.index(label)

    def cycle_label(self) -> str:
        self._label_index = (self._label_index + 1) % len(self._labels)
        return self.current_label()
