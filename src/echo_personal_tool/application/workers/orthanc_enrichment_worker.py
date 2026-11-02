"""Background worker: per-study metadata enrichment for the loader dialog.

Runs the instance-tag scan (QIDO-RS pages) off the GUI thread and reports
progress page by page so the study list can render modes/stress/device badges
while the scan is still running.  Mirrors the worker style used by
:mod:`echo_personal_tool.application.workers.orthanc_download_worker`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, Signal

from echo_personal_tool.domain.models.orthanc import StudyEnrichment
from echo_personal_tool.infrastructure.safe_diagnostics import (
    log_boundary_failure,
    safe_error_category,
)

log = logging.getLogger(__name__)


class EnrichmentSignals(QObject):
    """Qt signals bridging the worker thread back to the dialog."""

    #: One page of partial results: dict[str, StudyEnrichment].
    batch = Signal(object)
    #: (full result | None, error category | None).
    finished = Signal(object, object)


class OrthancEnrichmentWorker(QRunnable):
    """Fetch instance-level tags aggregated per study in a background thread."""

    def __init__(
        self,
        fetch_fn: Callable[..., dict[str, StudyEnrichment]],
        signals: EnrichmentSignals,
    ) -> None:
        super().__init__()
        self._fetch_fn = fetch_fn
        self._signals = signals
        self.setAutoDelete(True)

    def run(self) -> None:
        error: str | None = None
        result: dict[str, StudyEnrichment] | None = None

        def _on_batch(partial: dict[str, StudyEnrichment]) -> None:
            try:
                self._signals.batch.emit(partial)
            except RuntimeError:
                log.debug("[ENRICH] batch signal already deleted, skipping emit")

        try:
            result = self._fetch_fn(on_batch=_on_batch)
        except Exception as exc:  # noqa: BLE001
            log_boundary_failure(log, "dicom.query", exc, code="io", level=logging.WARNING)
            error = safe_error_category(exc)
        if not isinstance(result, dict):
            result = None
        try:
            self._signals.finished.emit(result, error)
        except RuntimeError:
            log.debug("[ENRICH] finished signal already deleted, skipping emit")
