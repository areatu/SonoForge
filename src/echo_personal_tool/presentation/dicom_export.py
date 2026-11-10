"""Coordinate a DICOM export without conflating its status with MP4 export."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import QWidget

from echo_personal_tool.application.localization import tr
from echo_personal_tool.domain.models import InstanceMetadata


def request_dicom_export(
    parent: QWidget,
    instance: object,
    ask_frame_range: Callable,
    show_status: Callable,
    on_failed: Callable,
) -> None:
    if not isinstance(instance, InstanceMetadata) or instance.path is None:
        return
    frame_range = ask_frame_range(instance)
    if frame_range is False:
        return
    from echo_personal_tool.presentation.styled_dialogs import styled_save_file

    dest, _ = styled_save_file(
        parent, tr("dialog.export_dcm_range.title"), instance.path.stem + ".dcm", "DICOM (*.dcm)"
    )
    if not dest:
        return
    from echo_personal_tool.application.workers.dcm_export_worker import DcmRangeExportWorker

    show_status(tr("status.dcm_exporting"))
    worker = DcmRangeExportWorker(
        source_path=instance.path, dest_path=Path(dest), frame_range=frame_range, parent=parent
    )
    worker.signals.progress.connect(
        lambda current, total: show_status(tr("status.dcm_export_progress", current=current, total=total)),
        Qt.ConnectionType.QueuedConnection,
    )
    worker.signals.finished.connect(
        lambda path: show_status(tr("status.dcm_exported", path=path)), Qt.ConnectionType.QueuedConnection
    )
    worker.signals.failed.connect(on_failed, Qt.ConnectionType.QueuedConnection)
    QThreadPool.globalInstance().start(worker)
