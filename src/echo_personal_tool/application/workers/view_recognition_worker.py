"""Background worker for view recognition (#639 step 4).

Runs :meth:`ViewRecognitionWorkflow.suggest` off the main thread: the
recognizer may be an ONNX classifier (step 2) whose inference must not block
the UI. The worker is stateless apart from its inputs and reports the
:class:`ViewSuggestion` through signals.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from PySide6.QtCore import QObject, QRunnable, Signal

from echo_personal_tool.domain.services.view_recognition_workflow import (
    ViewRecognitionWorkflow,
)


class ViewRecognitionSignals(QObject):
    """Signals emitted by :class:`ViewRecognitionWorker`."""

    suggestion_ready = Signal(object)  # ViewSuggestion
    failed = Signal(str)


class ViewRecognitionWorker(QRunnable):
    """Run one view-recognition suggestion for a loaded series."""

    def __init__(
        self,
        workflow: ViewRecognitionWorkflow,
        frames: Sequence[np.ndarray],
        *,
        study_uid: str,
        series_uid: str,
        parent: QObject | None = None,
    ) -> None:
        super().__init__()
        self._workflow = workflow
        self._frames = list(frames)
        self._study_uid = study_uid
        self._series_uid = series_uid
        self.signals = ViewRecognitionSignals()
        self.setAutoDelete(True)

    def run(self) -> None:  # noqa: D102 - QRunnable entry point
        try:
            suggestion = self._workflow.suggest(
                self._frames,
                study_uid=self._study_uid,
                series_uid=self._series_uid,
            )
        except (RuntimeError, ValueError, OSError, TypeError) as exc:
            # surface a stable message to the UI instead of dying the worker thread
            self.signals.failed.emit(f"view_recognition_failed: {type(exc).__name__}")
            return
        self.signals.suggestion_ready.emit(suggestion)
