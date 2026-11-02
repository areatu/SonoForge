"""Abstract base for editor panels with undo/redo hooks."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget


def matches_query(query: str, *fields: str) -> bool:
    """True when *query* occurs in one of *fields*; case is ignored ("IVS" finds "IVSd", "ЛЕВЫЙ" finds "левый")."""
    needle = query.lower()
    return any(needle in field.lower() for field in fields)


class BaseEditor(QWidget):
    """Base class for all constructor editors."""

    # Emitted when content changes (for dirty tracking)
    content_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

    def delete_selected(self) -> None:
        """Override in subclass to handle Delete key."""
        pass
