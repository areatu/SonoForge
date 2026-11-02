"""Background worker that writes the report PDF (S3-04, #313).

The export used to run on the UI thread: rendering the A4 sheet through ReportLab
took long enough that the window stopped repainting on a study with many groups.
This worker renders on a pool thread and publishes atomically, so the window stays
alive and the UI can offer «Отмена».

Cancellation is cooperative. ``cancel()`` is safe to call from the UI thread at any
moment; the worker checks it before rendering starts and again after rendering but
*before* the bytes are published, so a cancelled export never leaves a PDF behind.
Rendering itself is one ReportLab pass and is not interrupted mid-page — the slice
promises "cancellation is handled", not "partially written file".

The ``failed`` signal carries a stable code only: exception text and paths never
reach the UI (QH-4a ER-09).
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from echo_personal_tool.application.report_export import (
    ReportExportError,
    publish_report_pdf,
    render_report,
)
from echo_personal_tool.domain.services.report_builder import ReportDocument
from echo_personal_tool.infrastructure.safe_diagnostics import log_boundary_failure

logger = logging.getLogger(__name__)

#: Stable UI-safe failure code (never exception text or a filesystem path).
REPORT_EXPORT_FAILURE_CODE = "pdf_export_failed"


class ReportExportSignals(QObject):
    finished = Signal(str)  # destination path
    failed = Signal(str)  # stable failure code
    cancelled = Signal()


class ReportExportWorker(QRunnable):
    """Render a report document and publish its PDF outside the UI thread."""

    def __init__(
        self,
        document: ReportDocument,
        dest_path: str | Path,
        *,
        font_size: int = 10,
    ) -> None:
        super().__init__()
        self._document = document
        self._dest_path = Path(dest_path)
        self._font_size = int(font_size)
        self._cancel = threading.Event()
        self.signals = ReportExportSignals()
        self.setAutoDelete(True)

    @property
    def dest_path(self) -> Path:
        return self._dest_path

    @property
    def is_cancelled(self) -> bool:
        return self._cancel.is_set()

    def cancel(self) -> None:
        """Ask the worker to drop the export (thread-safe, idempotent)."""
        self._cancel.set()

    @Slot()
    def run(self) -> None:
        if self.is_cancelled:
            self.signals.cancelled.emit()
            return
        try:
            rendered = render_report(self._document, font_size=self._font_size)
        except ReportExportError as exc:
            log_boundary_failure(logger, "report.export", exc, code=exc.code, level=logging.WARNING)
            self.signals.failed.emit(REPORT_EXPORT_FAILURE_CODE)
            return
        except Exception as exc:  # noqa: BLE001 - worker boundary delivers a stable code
            log_boundary_failure(logger, "report.export", exc, code="unexpected", level=logging.ERROR)
            self.signals.failed.emit(REPORT_EXPORT_FAILURE_CODE)
            return

        # The slow part is behind us; a cancel that arrived meanwhile still wins,
        # so the user never gets a file they asked not to write.
        if self.is_cancelled:
            self.signals.cancelled.emit()
            return

        try:
            publish_report_pdf(rendered.pdf, self._dest_path)
        except ReportExportError as exc:
            log_boundary_failure(logger, "report.export", exc, code=exc.code, level=logging.WARNING)
            self.signals.failed.emit(REPORT_EXPORT_FAILURE_CODE)
            return
        except Exception as exc:  # noqa: BLE001 - worker boundary delivers a stable code
            log_boundary_failure(logger, "report.export", exc, code="unexpected", level=logging.ERROR)
            self.signals.failed.emit(REPORT_EXPORT_FAILURE_CODE)
            return

        self.signals.finished.emit(str(self._dest_path))


__all__ = [
    "REPORT_EXPORT_FAILURE_CODE",
    "ReportExportSignals",
    "ReportExportWorker",
]
