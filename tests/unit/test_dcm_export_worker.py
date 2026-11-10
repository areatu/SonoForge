"""Behavioral unit tests for DcmRangeExportWorker (issue 483)."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pydicom
import pytest

from echo_personal_tool.application.workers.dcm_export_worker import (
    DCM_EXPORT_FAILURE_CODE,
    DcmRangeExportWorker,
)
from tests.fixtures.generate_synthetic_dicom import write_synthetic_multiframe_dicom


def _write_rgb_multiframe_dicom(path: Path, frames: np.ndarray) -> Path:
    """Write an uncompressed RGB multi-frame DICOM dataset for range-export tests."""
    tmp_mono = path.parent / "_seed_mono.dcm"
    write_synthetic_multiframe_dicom(tmp_mono, frame_count=1, rows=frames.shape[1], cols=frames.shape[2])
    ds = pydicom.dcmread(str(tmp_mono))
    tmp_mono.unlink()
    ds.file_meta.TransferSyntaxUID = pydicom.uid.ExplicitVRLittleEndian
    ds.NumberOfFrames = str(int(frames.shape[0]))
    ds.Rows, ds.Columns = int(frames.shape[1]), int(frames.shape[2])
    ds.SamplesPerPixel = 3
    ds.PhotometricInterpretation = "RGB"
    ds.PlanarConfiguration = 0
    ds.BitsAllocated = 8
    ds.BitsStored = 8
    ds.HighBit = 7
    ds.PixelRepresentation = 0
    ds.PixelData = np.ascontiguousarray(frames, dtype=np.uint8).tobytes()
    ds.save_as(str(path), write_like_original=False)
    return path


class TestDcmRangeExportWorker:
    def test_whole_file_export_copies_bytes_verbatim(self, tmp_path: Path) -> None:
        src = write_synthetic_multiframe_dicom(tmp_path / "source.dcm", frame_count=4, rows=24, cols=32)
        dest = tmp_path / "exported_whole.dcm"
        finished: list[str] = []
        failed: list[str] = []
        progress: list[tuple[int, int]] = []

        worker = DcmRangeExportWorker(src, dest, frame_range=None)
        worker.signals.finished.connect(finished.append)
        worker.signals.failed.connect(failed.append)
        worker.signals.progress.connect(lambda cur, tot: progress.append((cur, tot)))
        worker.run()

        assert failed == []
        assert progress == []
        assert finished == [str(dest)]
        assert dest.read_bytes() == src.read_bytes()

    def test_monochrome_range_export_writes_selected_frames_uncompressed(self, tmp_path: Path) -> None:
        src = write_synthetic_multiframe_dicom(tmp_path / "cine.dcm", frame_count=6, rows=20, cols=28)
        src_ds = pydicom.dcmread(str(src))
        # Stamp distinct per-frame intensities so slice order is verifiable
        raw = np.stack([np.full((20, 28), (idx + 1) * 25, dtype=np.uint8) for idx in range(6)], axis=0)
        src_ds.BitsAllocated = 8
        src_ds.BitsStored = 8
        src_ds.HighBit = 7
        src_ds.PixelRepresentation = 0
        src_ds.PixelData = raw.tobytes()
        src_ds.save_as(str(src), write_like_original=False)

        dest = tmp_path / "nested" / "slice.dcm"
        finished: list[str] = []
        failed: list[str] = []
        progress: list[tuple[int, int]] = []

        worker = DcmRangeExportWorker(src, dest, frame_range=(2, 4))
        worker.signals.finished.connect(finished.append)
        worker.signals.failed.connect(failed.append)
        worker.signals.progress.connect(lambda cur, tot: progress.append((cur, tot)))
        worker.run()

        assert failed == []
        assert finished == [str(dest)]
        assert progress == [(1, 3), (3, 3)]

        out_ds = pydicom.dcmread(str(dest))
        assert out_ds.file_meta.TransferSyntaxUID == pydicom.uid.ExplicitVRLittleEndian
        assert int(out_ds.NumberOfFrames) == 3
        assert out_ds.PhotometricInterpretation == "MONOCHROME2"
        assert int(out_ds.SamplesPerPixel) == 1
        np.testing.assert_array_equal(out_ds.pixel_array, raw[2:5])

    def test_rgb_range_export_clamps_bounds_and_batches_progress(self, tmp_path: Path) -> None:
        rgb = np.zeros((7, 16, 20, 3), dtype=np.uint8)
        for idx in range(7):
            rgb[idx, :, :, 0] = idx * 30
            rgb[idx, :, :, 1] = 100
            rgb[idx, :, :, 2] = 200 - idx * 10
        src = _write_rgb_multiframe_dicom(tmp_path / "rgb_cine.dcm", rgb)
        dest = tmp_path / "rgb_out.dcm"

        finished: list[str] = []
        progress: list[tuple[int, int]] = []
        worker = DcmRangeExportWorker(src, dest, frame_range=(-3, 99))
        worker.signals.finished.connect(finished.append)
        worker.signals.progress.connect(lambda cur, tot: progress.append((cur, tot)))
        worker.run()

        assert finished == [str(dest)]
        # i % 5 == 0 or i == count - 1 for count == 7 -> i in {0, 5, 6} -> (1, 7), (6, 7), (7, 7)
        assert progress == [(1, 7), (6, 7), (7, 7)]

        out_ds = pydicom.dcmread(str(dest))
        assert int(out_ds.NumberOfFrames) == 7
        assert out_ds.PhotometricInterpretation == "RGB"
        assert int(out_ds.SamplesPerPixel) == 3
        assert int(out_ds.PlanarConfiguration) == 0
        np.testing.assert_array_equal(out_ds.pixel_array, rgb)

    def test_export_failure_emits_stable_code_and_redacts_phi_from_logs(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        missing = tmp_path / "PHI_PATIENT_SECRET_483.dcm"
        dest = tmp_path / "never_created.dcm"
        finished: list[str] = []
        failed: list[str] = []

        worker = DcmRangeExportWorker(missing, dest, frame_range=(0, 2))
        worker.signals.finished.connect(finished.append)
        worker.signals.failed.connect(failed.append)

        with caplog.at_level(logging.ERROR):
            worker.run()

        assert finished == []
        assert failed == [DCM_EXPORT_FAILURE_CODE]
        assert not dest.exists()
        assert "operation=dcm.export code=unexpected" in caplog.text
        assert "PHI_PATIENT_SECRET_483" not in caplog.text
        assert all(record.exc_info is None for record in caplog.records)
