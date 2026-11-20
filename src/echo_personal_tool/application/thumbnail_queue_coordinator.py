"""ThumbnailQueueCoordinator — the thumbnail decode queue slice of ``AppController`` (#619).

``AppController`` used to own the whole priority queue inline: the scheduler, the
worker map, the in-flight table, the preview-size probe and the pump loop.  The
coordinator owns all of that now; ``AppController`` keeps a thin facade
(``load_thumbnail`` / ``request_thumbnail_preview(s)`` / ``_pump_thumbnail_queue``
/ ``_reset_thumbnail_queue`` / ``_thumbnail_preview_box``) and forwards the
``thumbnail_loaded`` signal.

The worker class is injected as a factory so tests can monkeypatch
``app_controller.ThumbnailLoaderWorker`` and still intercept construction — the
facade closure resolves the module global at call time.

Decode gating (don't replenish background decode while a first-frame decode is
pending or playback is running) is read through providers, so the coordinator
never reaches into ``AppController`` state directly.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import partial
from typing import Any, cast

from PySide6.QtCore import QObject, Qt, QThreadPool, Signal
from PySide6.QtGui import QImage

from echo_personal_tool.application.diagnostics import log_boundary_failure
from echo_personal_tool.application.thumbnail_scheduler import (
    ThumbnailPriority,
    ThumbnailScheduler,
)
from echo_personal_tool.application.workers.thumbnail_loader_worker import ThumbnailLoaderWorker
from echo_personal_tool.domain.models import InstanceMetadata

logger = logging.getLogger(__name__)

#: Historical decode box when no gallery provider is wired.
LEGACY_PREVIEW_BOX = 96

WorkerFactory = Callable[..., ThumbnailLoaderWorker]


class ThumbnailQueueCoordinator(QObject):
    """Priority queue of thumbnail decodes with a bounded worker pool."""

    thumbnail_loaded = Signal(str, QImage)

    def __init__(
        self,
        *,
        parent: QObject | None = None,
        max_in_flight: int = 2,
        scheduler: ThumbnailScheduler | None = None,
        thread_pool: QThreadPool | None = None,
        worker_factory: WorkerFactory,
        pending_decode_provider: Callable[[], int],
        is_playing_provider: Callable[[], bool],
    ) -> None:
        super().__init__(parent)
        self._max_in_flight = max_in_flight
        self._preview_size_provider: Callable[[], int] | None = None
        self._scheduler = scheduler if scheduler is not None else ThumbnailScheduler(max_in_flight=max_in_flight)
        # Thumbnails use their own pool; tests may still inject one.
        self._pool = thread_pool if thread_pool is not None else QThreadPool(self)
        if thread_pool is None:
            self._pool.setMaxThreadCount(max_in_flight)
        self._generation = 0
        self._workers: dict[tuple[int, str], ThumbnailLoaderWorker] = {}
        self._instances: dict[str, InstanceMetadata] = {}
        self._in_flight: dict[str, ThumbnailPriority] = {}
        self._first_preview_emitted = False
        self._worker_factory = worker_factory
        self._pending_decode_provider = pending_decode_provider
        self._is_playing_provider = is_playing_provider

    # -- read-only seams for the AppController facade and tests ---------------

    @property
    def max_in_flight(self) -> int:
        return self._max_in_flight

    @property
    def pool(self) -> QThreadPool:
        return self._pool

    @property
    def scheduler(self) -> ThumbnailScheduler:
        return self._scheduler

    @property
    def workers(self) -> dict[tuple[int, str], ThumbnailLoaderWorker]:
        return self._workers

    @property
    def instances(self) -> dict[str, InstanceMetadata]:
        return self._instances

    @property
    def in_flight(self) -> dict[str, ThumbnailPriority]:
        return self._in_flight

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def first_preview_emitted(self) -> bool:
        return self._first_preview_emitted

    @first_preview_emitted.setter
    def first_preview_emitted(self, value: bool) -> None:
        self._first_preview_emitted = value

    # -- public API ------------------------------------------------------------

    def load_thumbnail(
        self,
        instance: InstanceMetadata,
        priority: ThumbnailPriority = ThumbnailPriority.P2_BACKGROUND,
    ) -> None:
        # Keep the gallery's viewport priority: otherwise file 114 lags behind 1–113.
        self.request_preview(instance, priority)

    def set_preview_size_provider(self, provider: Callable[[], int] | None) -> None:
        """Let the gallery decide the decode box (logical thumb × screen DPR, Э4)."""
        self._preview_size_provider = provider

    def preview_box(self) -> int:
        provider = self._preview_size_provider
        if provider is None:
            return LEGACY_PREVIEW_BOX
        try:
            return max(LEGACY_PREVIEW_BOX, int(provider()))
        except Exception as exc:  # noqa: BLE001 - a bad probe must not break thumbnails
            log_boundary_failure(logger, "thumbnail.size_probe", exc, code="invalid", level=logging.DEBUG)
            return LEGACY_PREVIEW_BOX

    def request_preview(
        self,
        instance: InstanceMetadata,
        priority: ThumbnailPriority = ThumbnailPriority.P2_BACKGROUND,
    ) -> None:
        if instance.path is None:
            return
        uid = instance.sop_instance_uid
        self._instances[uid] = instance
        self._scheduler.enqueue(uid, priority)
        self.pump()

    def request_previews(
        self,
        instances: list[InstanceMetadata],
        priority: ThumbnailPriority = ThumbnailPriority.P2_BACKGROUND,
    ) -> None:
        uids: list[str] = []
        for instance in instances:
            if instance.path is None:
                continue
            uid = instance.sop_instance_uid
            self._instances[uid] = instance
            uids.append(uid)
        if not uids:
            return
        self._scheduler.reprioritize(uids, priority)
        self.pump()

    def reset(self) -> None:
        self._generation += 1
        self._scheduler.reset()
        self._instances.clear()
        self._in_flight.clear()
        self._first_preview_emitted = False
        # Keep old workers counted until their completion reaches the GUI thread,
        # including on repeated folder switches; the global in-flight limit still holds.
        for worker in self._workers.values():
            worker.cancel()

    def pump(self) -> None:
        # Let at most the already running previews finish. Don't keep replenishing
        # background decode while the user waits for the first frame or presses Play.
        if self._pending_decode_provider() or self._is_playing_provider():
            return
        while True:
            slots = self._max_in_flight - len(self._workers)
            batch = self._scheduler.next_batch(limit=slots)
            if not batch:
                return
            for task in batch:
                instance = self._instances.get(task.sop_instance_uid)
                if instance is None or instance.path is None:
                    self._scheduler.mark_failed(task.sop_instance_uid)
                    self._instances.pop(task.sop_instance_uid, None)
                    continue
                worker = self._worker_factory(
                    instance.path,
                    task.sop_instance_uid,
                    number_of_frames=instance.number_of_frames,
                    media_format=instance.media_format,
                    preview_size=self.preview_box(),
                )
                generation = self._generation
                worker.signals.finished.connect(
                    partial(self._completed, generation, failed=False), Qt.ConnectionType.QueuedConnection
                )
                worker.signals.failed.connect(
                    partial(self._completed, generation, failed=True), Qt.ConnectionType.QueuedConnection
                )
                self._in_flight[task.sop_instance_uid] = task.priority
                self._workers[(generation, task.sop_instance_uid)] = worker
                self._pool.start(worker)

    # -- worker completion -----------------------------------------------------

    def _completed(self, generation: int, uid: str, result: Any, *, failed: bool) -> None:
        self._workers.pop((generation, uid), None)
        if generation != self._generation:
            self.pump()
            return
        if failed:
            self._on_failed(uid, str(result))
        else:
            self._on_loaded(uid, cast(QImage, result))

    def _on_loaded(self, sop_instance_uid: str, image: QImage) -> None:
        self._scheduler.mark_done(sop_instance_uid)
        self._in_flight.pop(sop_instance_uid, None)
        self._instances.pop(sop_instance_uid, None)
        if not self._first_preview_emitted:
            self._first_preview_emitted = True
            from echo_personal_tool.infrastructure.log_sanitizer import sanitize_uid

            logger.info("first_preview_emitted uid=%s", sanitize_uid(sop_instance_uid))
        self.thumbnail_loaded.emit(sop_instance_uid, image)
        self.pump()

    def _on_failed(self, sop_instance_uid: str, _message: str) -> None:
        self._scheduler.mark_failed(sop_instance_uid)
        self._in_flight.pop(sop_instance_uid, None)
        self._instances.pop(sop_instance_uid, None)
        self.pump()
