"""Modal «PDF…» export of the report mode (S3-04, issue 313).

The window used to render the sheet on the UI thread inside the click handler.
Now the render and the atomic write run in :class:`ReportExportWorker`, and this
job owns everything the dialog needs for as long as the worker lives:

* the progress dialog (modal, cancellable) — it closes as soon as the user
  presses «Отмена», which is *earlier* than the worker stops rendering;
* the worker reference — without it the worker's signal object would be freed
  the moment the dialog closes and the outcome would never reach the UI;
* the outcome callback — called exactly once with one of the three codes below.

Closing the dialog while the export is still running counts as cancellation: the
job cancels the worker right after ``exec()`` returns instead of waiting for the
dialog's own ``canceled`` signal, which Qt 6 delivers on a later event-loop turn
(and therefore *after* a fast render may already have published the file).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThreadPool, Slot
from PySide6.QtWidgets import QProgressDialog, QWidget

from echo_personal_tool.application.localization import tr
from echo_personal_tool.application.workers.report_export_worker import ReportExportWorker
from echo_personal_tool.domain.services.report_builder import ReportDocument

#: Outcome codes reported to the caller (never exception text).
PDF_EXPORT_FINISHED = "finished"
PDF_EXPORT_FAILED = "failed"
PDF_EXPORT_CANCELLED = "cancelled"

OutcomeCallback = Callable[[str, str], None]


class ReportPdfExportJob(QObject):
    """One PDF export: dialog + worker + a single outcome callback.

    The callback receives ``(outcome, file_name)``: ``file_name`` is the
    destination's base name for :data:`PDF_EXPORT_FINISHED` and empty otherwise.
    The job deletes itself once the outcome is known.
    """

    def __init__(
        self,
        parent: QWidget,
        document: ReportDocument,
        dest_path: str | Path,
        *,
        font_size: int = 10,
        on_outcome: OutcomeCallback | None = None,
    ) -> None:
        super().__init__(parent)
        self._dest_path = Path(dest_path)
        self._on_outcome = on_outcome
        self._worker: ReportExportWorker | None = None
        self._reported = False

        self._dialog = QProgressDialog(
            tr("report.export_progress"),
            tr("report.export_cancel"),
            0,
            0,
            parent,
        )
        self._dialog.setWindowTitle(tr("report.export_pdf_title"))
        self._dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self._dialog.setMinimumDuration(0)
        self._dialog.setValue(0)

        worker = ReportExportWorker(document, self._dest_path, font_size=font_size)
        worker.signals.finished.connect(self._on_finished, Qt.ConnectionType.QueuedConnection)
        worker.signals.failed.connect(self._on_failed, Qt.ConnectionType.QueuedConnection)
        worker.signals.cancelled.connect(self._on_cancelled, Qt.ConnectionType.QueuedConnection)
        self._dialog.canceled.connect(worker.cancel)
        self._worker = worker

    # ── lifecycle ────────────────────────────────────────────────────

    @property
    def destination(self) -> Path:
        return self._dest_path

    @property
    def worker(self) -> ReportExportWorker | None:
        return self._worker

    def run(self) -> None:
        """Show the dialog until the export ends or the user cancels it."""
        worker = self._worker
        if worker is None:  # pragma: no cover - defensive
            return
        QThreadPool.globalInstance().start(worker)
        self._dialog.exec()
        # The dialog closes before the worker stops rendering, so an export that
        # is still in flight is exactly the user's cancellation.
        if self._worker is worker:
            worker.cancel()

    def cancel(self) -> None:
        """Cancel the export (safe before, during and after ``run()``)."""
        worker = self._worker
        if worker is not None:
            worker.cancel()
        self._dialog.cancel()

    # ── outcomes ─────────────────────────────────────────────────────

    @Slot(str)
    def _on_finished(self, saved: str) -> None:
        self._report(PDF_EXPORT_FINISHED, Path(saved).name)

    @Slot(str)
    def _on_failed(self, error_code: str) -> None:
        # A stable code, never exception text: the caller shows a fixed line.
        del error_code
        self._report(PDF_EXPORT_FAILED, "")

    @Slot()
    def _on_cancelled(self) -> None:
        self._report(PDF_EXPORT_CANCELLED, "")

    def _report(self, outcome: str, file_name: str) -> None:
        if self._reported:
            return
        self._reported = True
        self._worker = None
        self._dialog.close()
        self._dialog.setParent(None)
        self._dialog.deleteLater()
        if self._on_outcome is not None:
            self._on_outcome(outcome, file_name)
        self.deleteLater()


__all__ = [
    "PDF_EXPORT_CANCELLED",
    "PDF_EXPORT_FAILED",
    "PDF_EXPORT_FINISHED",
    "OutcomeCallback",
    "ReportPdfExportJob",
]
