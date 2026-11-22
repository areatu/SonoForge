"""Background worker that exports a DICOM clip as a compact JPEG Baseline DICOM.

The gallery's «Экспорт в DICOM…» asks for the whole clip or a consecutive frame
range.  Both paths decode the requested frames from the already de-identified
working file and write a new multi-frame DICOM with JPEG Baseline pixel data.
The source bytes are never copied verbatim: slicing encapsulated JPEG/JPEG2000
fragments is not lossless, and the export must stay small (12–40 MiB for a
typical cine) instead of duplicating a hundreds-of-megabytes raw file.

Copying the original *with* PHI is the separate «Скопировать DICOM-файл…»
action; this worker always inherits de-identification from its input file.
"""

from __future__ import annotations

import logging
import os
from io import BytesIO
from pathlib import Path

import numpy as np
import pydicom
from PIL import Image
from pydicom.encaps import encapsulate
from pydicom.uid import JPEGBaseline8Bit
from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from echo_personal_tool.infrastructure.safe_diagnostics import log_boundary_failure

logger = logging.getLogger(__name__)

DCM_EXPORT_FAILURE_CODE = "export_failed"

_TARGET_BYTES = 24 * 1024 * 1024
_MAX_BYTES = 40 * 1024 * 1024
_QUALITIES = (90, 92, 94, 96, 98, 100)
_SAMPLE_FRAMES = 8


class DcmExportSignals(QObject):
    progress = Signal(int, int)  # current_frame, total_frames
    finished = Signal(str)  # output_path
    failed = Signal(str)  # stable failure code


def _encode_jpeg(frame: np.ndarray, quality: int, monochrome: bool) -> bytes:
    buf = BytesIO()
    if monochrome:
        Image.fromarray(frame, mode="L").save(buf, format="JPEG", quality=quality)
    else:
        Image.fromarray(frame, mode="RGB").save(buf, format="JPEG", quality=quality, subsampling=1)
    return buf.getvalue()


def _choose_quality(frames: np.ndarray, monochrome: bool) -> int:
    """Pick the quality whose sampled frame size is closest to the target."""
    sample = frames[: min(_SAMPLE_FRAMES, len(frames))]
    best_quality, best_distance = _QUALITIES[-1], float("inf")
    for quality in _QUALITIES:
        avg = sum(len(_encode_jpeg(frame, quality, monochrome)) for frame in sample) / len(sample)
        distance = abs(avg * len(frames) - _TARGET_BYTES)
        if distance < best_distance:
            best_quality, best_distance = quality, distance
    return best_quality


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
            self._export_frames()
        except Exception as exc:  # noqa: BLE001 — worker boundary delivers failure to the UI
            log_boundary_failure(logger, "dcm.export", exc, code="unexpected", level=logging.ERROR)
            self.signals.failed.emit(DCM_EXPORT_FAILURE_CODE)

    def _export_frames(self) -> None:
        from echo_personal_tool.infrastructure.dicom_session import get_thread_dicom_session

        session = get_thread_dicom_session(self._source_path)
        session.open(self._source_path)
        try:
            total = session.frame_count
            start, end = self._frame_range or (0, total - 1)
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

        ds = pydicom.dcmread(str(self._source_path))
        self._write_compressed(ds, selected)
        self.signals.finished.emit(str(self._dest_path))

    def _write_compressed(self, ds: pydicom.Dataset, frames: np.ndarray) -> None:
        out = ds.copy()
        file_meta = getattr(out, "file_meta", None)
        if file_meta is None:
            file_meta = pydicom.dataset.FileMetaDataset()
            out.file_meta = file_meta
        file_meta.TransferSyntaxUID = JPEGBaseline8Bit
        out.is_implicit_VR = False
        out.is_little_endian = True

        count = int(frames.shape[0])
        first = np.asarray(frames[0])
        monochrome = first.ndim == 2
        out.NumberOfFrames = str(count)
        out.Rows, out.Columns = int(first.shape[0]), int(first.shape[1])
        out.SamplesPerPixel = 1 if monochrome else int(first.shape[2])
        out.PhotometricInterpretation = "MONOCHROME2" if monochrome else "YBR_FULL_422"
        if not monochrome:
            out.PlanarConfiguration = 0
        out.BitsAllocated = 8
        out.BitsStored = 8
        out.HighBit = 7
        out.PixelRepresentation = 0
        out.LossyImageCompression = "01"
        out.LossyImageCompressionMethod = "ISO_10918_1"

        quality = _choose_quality(frames, monochrome)
        tmp = self._dest_path.with_name(self._dest_path.name + ".tmp")
        try:
            while True:
                jpeg_frames = []
                for index, frame in enumerate(frames):
                    jpeg_frames.append(_encode_jpeg(frame, quality, monochrome))
                    if index % 5 == 0 or index == count - 1:
                        self.signals.progress.emit(index + 1, count)
                total_jpeg = sum(len(item) for item in jpeg_frames)
                out.PixelData = encapsulate(jpeg_frames)
                out["PixelData"].is_undefined_length = True
                out.LossyImageCompressionRatio = f"{frames.nbytes / total_jpeg:.1f}"
                self._dest_path.parent.mkdir(parents=True, exist_ok=True)
                out.save_as(str(tmp), write_like_original=False, enforce_file_format=True)
                if tmp.stat().st_size <= _MAX_BYTES or quality == _QUALITIES[0]:
                    os.replace(tmp, self._dest_path)
                    return
                tmp.unlink()
                quality = _QUALITIES[_QUALITIES.index(quality) - 1]
        finally:
            if tmp.exists():
                tmp.unlink()
