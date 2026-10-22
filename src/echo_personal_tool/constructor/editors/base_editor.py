"""Abstract base for editor panels with undo/redo hooks."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget


class BaseEditor(QWidget):
    """Base class for all constructor editors."""

    # Emitted when content changes (for dirty tracking)
    content_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

    def delete_selected(self) -> None:
        """Override in subclass to handle Delete key."""
        pass
