"""The snapshot column (UI-2 PR-3, spec §4.1 and §8.1).

One vertical stack owns the image and everything glued to it: the tool row above,
the viewer (or the two Multiview panes) in the middle, and — from UI-3 and UI-4 —
the step bar and the cine loop below.  §4.1 measures the column 42 + 58 + 66 pixels
apart from the image, and §8.1 asks the assembly to read that composition from the
slot table instead of branching on flags.

The column never creates or destroys the widgets it is given: `_rebuild_layout()`
in the window hands the same viewer, row and rail from preset to preset, so a
preset switch must not cost a repaint of the clip or the state of a tool (the
300 ms budget of §11 UI-2 is spent on layout, not on rebuilding widgets).
"""

from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget

#: The three places a part of the column can occupy, top to bottom.
SLOT_TOP: str = "top"
SLOT_CENTER: str = "center"
SLOT_BOTTOM: str = "bottom"
COLUMN_SLOTS: tuple[str, ...] = (SLOT_TOP, SLOT_CENTER, SLOT_BOTTOM)


class ViewerColumn(QWidget):
    """``[верхняя полоса] · снимок · [нижние полосы]`` in one layout."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("viewerColumn")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._parts: dict[str, QWidget | None] = dict.fromkeys(COLUMN_SLOTS)

    def part(self, slot: str) -> QWidget | None:
        """The widget currently in ``slot`` (``None`` when the slot is empty)."""
        return self._parts.get(slot)

    def set_top(self, widget: QWidget | None) -> None:
        """The tool row above the image; ``None`` leaves the strip out (§4.1)."""
        self._set(SLOT_TOP, widget)

    def set_center(self, widget: QWidget) -> None:
        """The viewer, or the Multiview panes — the part that stretches."""
        self._set(SLOT_CENTER, widget)

    def set_bottom(self, widget: QWidget | None) -> None:
        """The step bar (UI-3) and the cine loop (UI-4); both are optional."""
        self._set(SLOT_BOTTOM, widget)

    def _set(self, slot: str, widget: QWidget | None) -> None:
        if slot not in COLUMN_SLOTS:
            raise ValueError(f"unknown column slot: {slot!r}")
        previous = self._parts.get(slot)
        if previous is not None and previous is not widget:
            self._layout.removeWidget(previous)
            # Detached, not deleted: the window owns these widgets and may hand
            # the same one back after a preset switch.
            previous.setVisible(False)
        self._parts[slot] = widget
        if widget is not None:
            widget.setVisible(True)
        self._resequence()

    def _resequence(self) -> None:
        """Rebuild the order of the children: top, center, bottom, whatever set what."""
        for widget in self._parts.values():
            if widget is not None:
                self._layout.removeWidget(widget)
        for slot in COLUMN_SLOTS:
            widget = self._parts[slot]
            if widget is None:
                continue
            self._layout.addWidget(widget, stretch=1 if slot == SLOT_CENTER else 0)

    def is_empty(self) -> bool:
        """Whether the column holds nothing (the assembly should not show it)."""
        return all(widget is None for widget in self._parts.values())
