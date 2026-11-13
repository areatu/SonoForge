"""Background worker that exports a frame range of a DICOM clip as DICOM.

The gallery's «Экспорт в DICOM…» writes either the whole file (a byte copy —
nothing is re-encoded) or a consecutive frame range as a new multi-frame
DICOM: the selected frames are decoded and stored uncompressed (Explicit VR
Little Endian) with the original header metadata.  Keeping the export
uncompressed is deliberate — slicing encapsulated (compressed) pixel data is
not lossless, and an export must not silently change the transfer syntax.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

import numpy as np
import pydicom
from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from echo_personal_tool.infrastructure.safe_diagnostics import log_boundary_failure

logger = logging.getLogger(__name__)

DCM_EXPORT_FAILURE_CODE = "export_failed"


class DcmExportSignals(QObject):
    progress = Signal(int, int)  # current_frame, total_frames
    finished = Signal(str)  # output_path
    failed = Signal(str)  # stable failure code


class DcmRangeExportWorker(QRunnable):
    """Export the whole DICOM file or a 0-based inclusive frame range of it."""

    def __init__(
        self,
        source_path: Path,
        dest_path: Path,
        frame_range: tuple[int, int] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__()
        self._source_path = Path(source_path)
        self._dest_path = Path(dest_path)
        self._frame_range = frame_range
        self.signals = DcmExportSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        try:
            if self._frame_range is None:
                shutil.copy2(str(self._source_path), str(self._dest_path))
                self.signals.finished.emit(str(self._dest_path))
                return
            self._export_range()
        except Exception as exc:  # noqa: BLE001 — worker boundary delivers failure to the UI
            log_boundary_failure(logger, "dcm.export", exc, code="unexpected", level=logging.ERROR)
            self.signals.failed.emit(DCM_EXPORT_FAILURE_CODE)

    def _export_range(self) -> None:
        from echo_personal_tool.infrastructure.dicom_session import get_thread_dicom_session

        frame_range = self._frame_range
        assert frame_range is not None  # run() handles the whole-file case
        start, end = frame_range
        session = get_thread_dicom_session(self._source_path)
        session.open(self._source_path)
        try:
            total = session.frame_count
            start = max(0, min(start, total - 1))
            end = max(start, min(end, total - 1))
            # Export only the requested range: a selected range must not require
            # the whole study to be resident first (#545).
            decoded = session.decode_frames(range(start, end + 1))
        finally:
            session.release_heavy()

        count = end - start + 1
        first = decoded[start]
        selected = np.empty((count,) + first.shape, dtype=first.dtype)
        for offset, index in enumerate(range(start, end + 1)):
            selected[offset] = decoded[index]
        for i in range(count):
            if i % 5 == 0 or i == count - 1:
                self.signals.progress.emit(i + 1, count)

        ds = pydicom.dcmread(str(self._source_path))
        self._write_multiframe(ds, selected)
        self.signals.finished.emit(str(self._dest_path))

    def _write_multiframe(self, ds: pydicom.Dataset, frames: np.ndarray) -> None:
        out = ds.copy()
        file_meta = getattr(ds, "file_meta", None)
        if file_meta is not None:
            file_meta.TransferSyntaxUID = pydicom.uid.ExplicitVRLittleEndian
            out.file_meta = file_meta
        out.NumberOfFrames = str(int(frames.shape[0]))
        first = np.asarray(frames[0])
        out.Rows, out.Columns = int(first.shape[0]), int(first.shape[1])
        if first.ndim == 3:
            out.SamplesPerPixel = int(first.shape[2])
            out.PhotometricInterpretation = "RGB"
            out.PlanarConfiguration = 0
            pixels = np.ascontiguousarray(frames).tobytes()
        else:
            out.SamplesPerPixel = 1
            out.PhotometricInterpretation = "MONOCHROME2"
            out.BitsAllocated = 8
            out.BitsStored = 8
            out.HighBit = 7
            out.PixelRepresentation = 0
            pixels = np.ascontiguousarray(frames, dtype=np.uint8).tobytes()
        out.PixelData = pixels
        self._dest_path.parent.mkdir(parents=True, exist_ok=True)
        out.save_as(str(self._dest_path), write_like_original=False)
