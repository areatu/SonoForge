"""Undo/redo for measurement deletions (S2-04).

Provides a bounded undo/redo stack for measurement deletions (contours,
calipers/linear measurements, markers) so that an accidental deletion can be
reversed.  The stack is owned by the viewer (presentation layer) and cleared
when the tab closes, so no PHI/measurement data persists beyond tab life.

All entries are plain dataclasses — no Qt types, safe to hold in the
application layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "UndoEntry",
    "UndoRedoManager",
]


@dataclass(frozen=True)
class UndoEntry:
    """One undoable measurement deletion.

    ``kind`` is one of ``"contour"`` or ``"linear_measurement"``.
    ``payload`` holds the data needed to restore or re-delete:

    * ``kind == "contour"``: ``payload["contour"]`` is the :class:`Contour`
      that was deleted; ``payload["index"]`` is the list position it was
      removed from (may be ``None`` when the original position cannot be
      determined — the entry is then appended on undo).
    * ``kind == "linear_measurement"``: ``payload["key"]`` is the
      ``(sop_instance_uid, frame_index)`` key and ``payload["measurement"]``
      is the :class:`LinearMeasurement` that was deleted.
    """

    kind: str
    payload: dict[str, Any]
    #: Monotonically increasing sequence number; used to detect stale entries.
    seq: int = field(default=0, compare=False)


class UndoRedoManager:
    """Bounded undo/redo stack for measurement deletions.

    Parameters
    ----------
    max_entries:
        Maximum number of entries kept.  Older entries are dropped when the
        limit is exceeded (FIFO eviction).  Defaults to 50.
    """

    def __init__(self, *, max_entries: int = 50) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be >= 1")
        self._max_entries = max_entries
        self._undo_stack: list[UndoEntry] = []
        self._redo_stack: list[UndoEntry] = []
        self._seq: int = 0

    # ── capacity ──────────────────────────────────────────────────────

    @property
    def max_entries(self) -> int:
        return self._max_entries

    # ── queries ───────────────────────────────────────────────────────

    @property
    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    @property
    def size(self) -> int:
        return len(self._undo_stack)

    # ── mutation ──────────────────────────────────────────────────────

    def push(self, entry: UndoEntry) -> None:
        """Push a new deletion onto the undo stack.

        Pushing a new entry clears the redo stack (standard undo/redo
        semantics: a new action invalidates any pending redo).
        """
        self._seq += 1
        entry = UndoEntry(kind=entry.kind, payload=dict(entry.payload), seq=self._seq)
        self._undo_stack.append(entry)
        # Enforce the size cap by evicting the oldest entries.
        while len(self._undo_stack) > self._max_entries:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def undo(self) -> UndoEntry | None:
        """Pop the last deletion and push it onto the redo stack.

        Returns the entry that was undone, or ``None`` when the stack is
        empty.
        """
        if not self._undo_stack:
            return None
        entry = self._undo_stack.pop()
        self._redo_stack.append(entry)
        return entry

    def redo(self) -> UndoEntry | None:
        """Pop the last undone entry and push it back onto the undo stack.

        Returns the entry that was redone, or ``None`` when the redo stack is
        empty.
        """
        if not self._redo_stack:
            return None
        entry = self._redo_stack.pop()
        self._undo_stack.append(entry)
        return entry

    def clear(self) -> None:
        """Drop all undo and redo entries.

        Called when the tab/viewer closes so that no measurement data
        (potentially identifying) survives beyond tab life.
        """
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._seq = 0
