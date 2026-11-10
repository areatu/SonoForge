"""The DICOM export coordinator reports DICOM, independently of MP4."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QWidget

from echo_personal_tool.domain.models import InstanceMetadata
from echo_personal_tool.presentation import dicom_export

pytestmark = pytest.mark.gui


class ExportSignals(QObject):
    progress = Signal(int, int)
    finished = Signal(str)
    failed = Signal(str)


def test_dicom_export_status_and_worker_connections(qtbot, tmp_path, monkeypatch):
    parent = QWidget()
    qtbot.addWidget(parent)
    instance = InstanceMetadata(
        sop_instance_uid="1",
        series_uid="2",
        modality="US",
        number_of_frames=2,
        pixel_spacing=None,
        frame_time_ms=33.3,
        series_description="",
        path=tmp_path / "in.dcm",
    )
    signals = ExportSignals()
    created = []

    def make_worker(**kwargs):
        worker = SimpleNamespace(signals=signals, arguments=kwargs)
        created.append(worker)
        return worker

    pool = Mock()
    monkeypatch.setattr(dicom_export, "QThreadPool", SimpleNamespace(globalInstance=lambda: pool))
    monkeypatch.setattr("echo_personal_tool.application.workers.dcm_export_worker.DcmRangeExportWorker", make_worker)
    monkeypatch.setattr(
        "echo_personal_tool.presentation.styled_dialogs.styled_save_file",
        lambda *_: (str(tmp_path / "out.dcm"), ""),
    )
    statuses = []
    failed = Mock()
    dicom_export.request_dicom_export(parent, instance, lambda _: (0, 1), statuses.append, failed)
    pool.start.assert_called_once_with(created[0])
    assert created[0].arguments["dest_path"] == Path(tmp_path / "out.dcm")
    signals.progress.emit(1, 2)
    signals.finished.emit("out.dcm")
    signals.failed.emit("export_failed")
    qtbot.waitUntil(lambda: len(statuses) == 3 and failed.called)
    assert all("DICOM" in message and "MP4" not in message for message in statuses)
    assert "out.dcm" in statuses[-1]
    failed.assert_called_once_with("export_failed")
