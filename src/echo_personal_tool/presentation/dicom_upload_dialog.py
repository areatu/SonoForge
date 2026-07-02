"""Dialog to upload local DICOM studies to a PACS server."""

from __future__ import annotations

from PySide6.QtCore import QThreadPool, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.application.dicom_upload_utils import collect_dicom_bytes
from echo_personal_tool.application.workers.dicom_upload_worker import DicomUploadWorker
from echo_personal_tool.domain.models import StudyMetadata
from echo_personal_tool.domain.models.orthanc import StowResult
from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.infrastructure.server_client_factory import (
    dimse_upload_available,
    make_upload_targets,
)
from echo_personal_tool.infrastructure.server_settings import ServerSettings


def run_dicom_upload_dialog(
    parent: QWidget | None,
    studies: list[StudyMetadata],
    settings: ServerSettings,
) -> None:
    payloads = collect_dicom_bytes(studies)
    if not payloads:
        QMessageBox.information(
            parent,
            tr("dialog.dicom_upload.title"),
            tr("dialog.dicom_upload.no_files"),
        )
        return

    dialog = QDialog(parent)
    dialog.setWindowTitle(tr("dialog.dicom_upload.title"))
    layout = QVBoxLayout(dialog)

    layout.addWidget(
        QLabel(tr("dialog.dicom_upload.summary", count=len(payloads)))
    )

    protocol_combo = QComboBox()
    protocol_combo.addItem(tr("dialog.dicom_upload.protocol_stow"), "stow")
    if dimse_upload_available(settings):
        protocol_combo.addItem(tr("dialog.dicom_upload.protocol_dimse"), "dimse")
    form = QFormLayout()
    form.addRow(tr("dialog.dicom_upload.protocol"), protocol_combo)
    layout.addLayout(form)

    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)

    if dialog.exec() != QDialog.DialogCode.Accepted:
        return

    protocol = str(protocol_combo.currentData())
    try:
        uploader, stow_client = make_upload_targets(settings, protocol)
    except ValueError as exc:
        QMessageBox.warning(
            parent,
            tr("dialog.dicom_upload.title"),
            str(exc),
        )
        return

    progress = QProgressDialog(
        tr("dialog.dicom_upload.progress"),
        tr("dialog.dicom_upload.cancel"),
        0,
        len(payloads),
        parent,
    )
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(0)
    progress.setValue(0)

    worker = DicomUploadWorker(
        payloads,
        uploader=uploader,
        stow_client=stow_client,
        parent=parent,
    )
    worker.signals.progress.connect(
        lambda current, total: progress.setValue(current)
        if total
        else None
    )

    def _on_finished(result: StowResult) -> None:
        progress.close()
        total = len(payloads)
        if (
            result.failed_uids
            or result.error_message
            or result.success_count < total
        ):
            QMessageBox.warning(
                parent,
                tr("dialog.dicom_upload.title"),
                tr(
                    "dialog.dicom_upload.partial",
                    success=result.success_count,
                    failed=len(result.failed_uids),
                    message=result.error_message,
                ),
            )
        else:
            QMessageBox.information(
                parent,
                tr("dialog.dicom_upload.title"),
                tr("dialog.dicom_upload.success", count=result.success_count),
            )

    def _on_failed(message: str) -> None:
        progress.close()
        if message != "Upload cancelled":
            QMessageBox.warning(
                parent,
                tr("dialog.dicom_upload.title"),
                tr("dialog.dicom_upload.failed", message=message),
            )

    worker.signals.finished.connect(_on_finished)
    worker.signals.failed.connect(_on_failed)
    progress.canceled.connect(worker.cancel)
    QThreadPool.globalInstance().start(worker)
    progress.exec()
