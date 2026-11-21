"""View-recognition orchestration for the application layer (#639 step 4).

The controller and the window stay thin: this coordinator owns the
one-shot-per-series guard, the frame sampling from the cache, the worker
lifetime on the thread pool and the decision persistence. It is a
``QObject`` with its own signals, so the UI binds directly to it and
``AppController`` needs no view-recognition code at all — the trigger is
wired once from the entrypoint (issue #474 size ceilings).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QObject, QThreadPool, Signal

from echo_personal_tool.domain.models.metadata import InstanceMetadata
from echo_personal_tool.domain.models.view_recognition import ViewDecision
from echo_personal_tool.domain.services.view_recognition_workflow import (
    ViewRecognitionWorkflow,
    ViewSuggestion,
)

if TYPE_CHECKING:
    from echo_personal_tool.application.frame_cache import FrameCache
    from echo_personal_tool.application.workers.view_recognition_worker import (
        ViewRecognitionWorker,
    )

#: Frames sampled for one recognition run (clip-level context).
FRAMES_PER_RUN = 8


class ViewRecognitionCoordinator(QObject):
    """Run view recognition once per loaded series; own the worker lifetime.

    ``on_frame_loaded`` is connected to the controller's ``frame_loaded``
    signal by the entrypoint. It samples frames from the cache, starts the
    worker on the pool and forwards the result as :attr:`suggestion_ready`.
    Manual choices flow back through :meth:`choose_view` and are persisted
    by the workflow.
    """

    suggestion_ready = Signal(object)  # ViewSuggestion
    decision_changed = Signal(object)  # ViewDecision
    status_message = Signal(str)

    def __init__(
        self,
        workflow: ViewRecognitionWorkflow,
        thread_pool: QThreadPool,
        resolve_study_uid: Callable[[InstanceMetadata | None], str],
        current_instance: Callable[[], InstanceMetadata | None],
        frame_cache: FrameCache,
        current_frame_pixels: Callable[[], np.ndarray | None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._workflow = workflow
        self._pool = thread_pool
        self._resolve_study_uid = resolve_study_uid
        self._current_instance = current_instance
        self._frame_cache = frame_cache
        self._current_frame_pixels = current_frame_pixels
        self._attempted: set[tuple[str, str]] = set()

    # ── public API ───────────────────────────────────────────────

    def on_frame_loaded(self, *_pixels: object) -> None:
        """Trigger recognition from the controller's frame_loaded signal."""
        self.maybe_start()

    def maybe_start(self) -> None:
        """Run recognition once per loaded series, from its first frame."""
        instance = self._current_instance()
        if instance is None or instance.path is None:
            return
        if instance.clip_mode != "2d":
            return  # view recognition applies to 2D cine clips only
        study_uid = self._resolve_study_uid(instance)
        key = (study_uid, instance.series_uid)
        if key in self._attempted:
            return
        self._attempted.add(key)
        frames = self._sample_frames(instance.path)
        if not frames:
            return
        worker: ViewRecognitionWorker = self._build_worker(
            workflow=self._workflow, frames=frames, study_uid=study_uid, series_uid=instance.series_uid
        )
        worker.signals.suggestion_ready.connect(self._on_suggestion)
        worker.signals.failed.connect(self._on_failed)
        self._pool.start(worker)

    def choose_view(self, view: str) -> ViewDecision | None:
        """Persist a user-chosen view for the loaded series."""
        instance = self._current_instance()
        if instance is None:
            return None
        decision = self._workflow.apply_override(
            view,
            study_uid=self._resolve_study_uid(instance),
            series_uid=instance.series_uid,
        )
        self.decision_changed.emit(decision)
        return decision

    def apply_decision(self, decision: ViewDecision) -> None:
        """Persist an externally built decision (UI / tests)."""
        self._workflow.save_decision(decision)
        self.decision_changed.emit(decision)

    # ── worker callbacks ─────────────────────────────────────────

    def _on_suggestion(self, suggestion: object) -> None:
        if isinstance(suggestion, ViewSuggestion):
            self.suggestion_ready.emit(suggestion)

    def _on_failed(self, message: str) -> None:
        self.status_message.emit(message)

    # ── frame sampling ────────────────────────────────────────────

    def _sample_frames(self, path: Path) -> list[np.ndarray]:
        """Up to :data:`FRAMES_PER_RUN` frames of ``path`` from the cache.

        Uses the stacked cine when the full clip is already decoded,
        otherwise the frames currently cached (at least the frame just
        loaded).
        """
        del path  # sampling reads the frame cache, not the file
        stacked = self._frame_cache.frames
        if stacked is not None and stacked.ndim >= 3 and stacked.shape[0] > 0:
            total = int(stacked.shape[0])
            if total <= FRAMES_PER_RUN:
                return [stacked[i] for i in range(total)]
            step = total / FRAMES_PER_RUN
            return [stacked[min(total - 1, int(i * step))] for i in range(FRAMES_PER_RUN)]
        cached = self._current_frame_pixels()
        return [cached] if cached is not None else []

    def _build_worker(
        self,
        workflow: ViewRecognitionWorkflow,
        frames: list[np.ndarray],
        *,
        study_uid: str,
        series_uid: str,
    ) -> ViewRecognitionWorker:
        from echo_personal_tool.application.workers.view_recognition_worker import (
            ViewRecognitionWorker,
        )

        return ViewRecognitionWorker(workflow, frames, study_uid=study_uid, series_uid=series_uid)
