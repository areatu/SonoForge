"""Background worker that decodes all frames from a DICOM file."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from echo_personal_tool.infrastructure.dicom_session import get_thread_dicom_session


class DicomDecodeSignals(QObject):
    finished = Signal(int, object, object)  # request_id, path, frames ndarray
    failed = Signal(int, str)


class DicomDecodeWorker(QRunnable):
    def __init__(
        self,
        path: Path,
        request_id: int,
        parent: QObject | None = None,
    ) -> None:
        super().__init__()
        self._path = Path(path)
        self._request_id = request_id
        self.signals = DicomDecodeSignals(parent)
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        try:
            session = get_thread_dicom_session()
            session.open(self._path)
            frames = session.decode_all_frames()
            self.signals.finished.emit(
                self._request_id,
                self._path,
                np.ascontiguousarray(frames).copy(),
            )
        except Exception as exc:  # noqa: BLE001
            self.signals.failed.emit(self._request_id, str(exc))
