"""Bounded local I/O jobs; static failure codes only, no patient paths in logs."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from echo_personal_tool.domain.models.training_archive import ArchiveWriteError


class MLWorkbenchSignals(QObject):
    completed = Signal(int, object)
    failed = Signal(int)


class MLWorkbenchWorker(QRunnable):
    def __init__(self, generation: int, action: Callable[[], Any]) -> None:
        super().__init__()
        self.generation = generation
        self.action = action
        self.signals = MLWorkbenchSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self.action()
        except (
            ArchiveWriteError,
            OSError,
            ValueError,
            LookupError,
            TypeError,
            RuntimeError,
            EOFError,
            OverflowError,
            MemoryError,
        ):
            # Expected storage, format/path and resource failures have no safe
            # exception text. Programming errors are not silently swallowed.
            self.signals.failed.emit(self.generation)
        else:
            self.signals.completed.emit(self.generation, result)
