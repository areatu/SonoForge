"""Qt adapter: gate segmentation callbacks independently of worker cleanup."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Any

from PySide6.QtCore import Qt

from echo_personal_tool.application.composition import segmentation_jobs_of
from echo_personal_tool.application.segmentation_jobs import SegmentationBasis, segmentation_basis


def connect_segmentation(
    controller: Any,
    worker: Any,
    finished: Callable[[Any], None],
    failed: Callable[[str], None],
    timed_out: Callable[[], None],
) -> None:
    """Bind terminal signals to one ticket; every terminal still releases its worker."""
    jobs = segmentation_jobs_of(controller)

    def current_basis() -> SegmentationBasis:
        return segmentation_basis(
            controller._state_manager.snapshot,
            controller._current_instance,
            document_id=controller._resolve_study_uid(),
            generation=controller._study_load_generation,
            loaded_frame_index=controller._loaded_frame_index,
        )

    ticket = jobs.begin(current_basis())

    def dispatch(callback: Callable[..., None], *payload: Any) -> None:
        decision = jobs.finish(ticket, current_basis())
        if decision is None:
            return
        controller._segment_in_progress = False
        if decision:
            callback(*payload)

    worker.signals.finished.connect(partial(dispatch, finished), Qt.ConnectionType.QueuedConnection)
    worker.signals.failed.connect(partial(dispatch, failed), Qt.ConnectionType.QueuedConnection)
    worker.signals.timed_out.connect(partial(dispatch, timed_out), Qt.ConnectionType.QueuedConnection)
    worker.setAutoDelete(False)
    controller._retain_worker(worker)
    worker.signals.finished.connect(partial(controller._release_worker, worker), Qt.ConnectionType.QueuedConnection)
    worker.signals.failed.connect(partial(controller._release_worker, worker), Qt.ConnectionType.QueuedConnection)
    worker.signals.timed_out.connect(partial(controller._release_worker, worker), Qt.ConnectionType.QueuedConnection)
    controller._thread_pool.start(worker)
