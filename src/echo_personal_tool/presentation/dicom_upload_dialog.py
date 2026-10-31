"""Dialog to upload local DICOM studies to a PACS server."""

from __future__ import annotations

from PySide6.QtCore import Qt, QThreadPool
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
from echo_personal_tool.application.localization import tr, tr_plural
from echo_personal_tool.application.server_io import (
    ServerSettings,
    dimse_upload_available,
    make_upload_targets,
    stow_upload_available,
)
from echo_personal_tool.application.workers.dicom_upload_worker import (
    UPLOAD_CANCELLED_CODE,
    DicomUploadWorker,
)
from echo_personal_tool.domain.models import StudyMetadata
from echo_personal_tool.domain.models.orthanc import StowResult
from echo_personal_tool.presentation.styled_dialogs import localize_dialog_button_box, theme_button_box_icons


def run_dicom_upload_dialog(
    parent: QWidget | None,
    studies: list[StudyMetadata],
    settings: ServerSettings,
    annotations: dict[str, list] | None = None,
) -> None:
    payloads = collect_dicom_bytes(studies, annotations=annotations)
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

    layout.addWidget(QLabel(tr_plural("dialog.dicom_upload.summary", len(payloads))))

    protocol_combo = QComboBox()
    if stow_upload_available(settings):
        protocol_combo.addItem(tr("dialog.dicom_upload.protocol_stow"), "stow")
    if dimse_upload_available(settings):
        protocol_combo.addItem(tr("dialog.dicom_upload.protocol_dimse"), "dimse")
    if protocol_combo.count() == 0:
        QMessageBox.warning(
            parent,
            tr("dialog.dicom_upload.title"),
            tr("dialog.dicom_upload.no_protocol"),
        )
        return
    form = QFormLayout()
    form.addRow(tr("dialog.dicom_upload.protocol"), protocol_combo)
    layout.addLayout(form)

    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    localize_dialog_button_box(
        buttons,
        overrides={QDialogButtonBox.StandardButton.Ok: "dialog.dicom_upload.send"},
    )
    theme_button_box_icons(buttons)
    layout.addWidget(buttons)

    from echo_personal_tool.presentation.ui_animations import exec_animated

    if exec_animated(dialog) != QDialog.DialogCode.Accepted:
        return

    from echo_personal_tool.presentation.server_settings_dialog import (
        ensure_transport_confirmed_before_network,
    )

    confirmed = ensure_transport_confirmed_before_network(parent, settings)
    if confirmed is None:
        return
    settings = confirmed

    protocol = str(protocol_combo.currentData())
    try:
        uploader, stow_client = make_upload_targets(settings, protocol)
    except ValueError:
        QMessageBox.warning(
            parent,
            tr("dialog.dicom_upload.title"),
            tr("dialog.dicom_upload.no_protocol"),
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
    worker.signals.progress.connect(lambda current, total: progress.setValue(current) if total else None)

    def _on_finished(result: StowResult) -> None:
        progress.close()
        total = len(payloads)
        if result.failed_uids or result.error_message or result.success_count < total:
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
                tr_plural("dialog.dicom_upload.success", result.success_count),
            )

    def _on_failed(message: str) -> None:
        progress.close()
        # Cancellation is a stable code, not an error dialog.  The worker never
        # forwards exception text, so the dialog renders a fixed localized line.
        if message != UPLOAD_CANCELLED_CODE:
            QMessageBox.warning(
                parent,
                tr("dialog.dicom_upload.title"),
                tr("dialog.dicom_upload.failed"),
            )

    worker.signals.finished.connect(_on_finished)
    worker.signals.failed.connect(_on_failed)
    progress.canceled.connect(worker.cancel)
    QThreadPool.globalInstance().start(worker)
    progress.exec()
