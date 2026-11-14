"""Tests for DICOM pre-parse validation, raw datasets and type classification (#551).

Besides the Part 10 magic fast path, these cover a dataset without the preamble:
the bounded fallback, pixel decoding from offset 0, and the distinction between
DICOMDIR/index, unsupported SR/PR and genuinely corrupt input.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pydicom
import pytest
from pydicom.dataset import Dataset
from pydicom.filebase import DicomBytesIO
from pydicom.filewriter import write_dataset
from pydicom.sequence import Sequence
from pydicom.uid import UltrasoundMultiFrameImageStorage

from echo_personal_tool.infrastructure.dicom_reader import DicomReaderImpl
from echo_personal_tool.infrastructure.dicom_validator import (
    DICOMDIR_SOP_CLASS_UID,
    CorruptDicomError,
    DicomKind,
    InvalidDicomError,
    UnsupportedDicomError,
    classify_dicom_dataset,
    validate_dicom_header,
)
from echo_personal_tool.infrastructure.local_scanner import LocalMediaDirectoryScanner


class TestValidateDicomHeader:
    def test_valid_dicom(self, tmp_path: Path) -> None:
        """A file with proper preamble + DICM magic should pass."""
        dcm = tmp_path / "valid.dcm"
        preamble = b"\x00" * 128
        dcm.write_bytes(preamble + b"DICM" + b"\x00" * 100)
        assert validate_dicom_header(dcm) is None

    def test_not_a_file(self, tmp_path: Path) -> None:
        dcm = tmp_path / "nonexistent.dcm"
        with pytest.raises(InvalidDicomError, match="Not a file"):
            validate_dicom_header(dcm)

    def test_file_too_small(self, tmp_path: Path) -> None:
        dcm = tmp_path / "tiny.dcm"
        dcm.write_bytes(b"\x00" * 10)
        with pytest.raises(InvalidDicomError, match="too small"):
            validate_dicom_header(dcm)

    def test_file_exactly_preamble_size_plus_4(self, tmp_path: Path) -> None:
        """132 bytes = 128 preamble + 4 magic = minimum valid size."""
        dcm = tmp_path / "min.dcm"
        dcm.write_bytes(b"\x00" * 128 + b"DICM")
        assert validate_dicom_header(dcm) is None

    def test_file_131_bytes_too_small(self, tmp_path: Path) -> None:
        dcm = tmp_path / "short.dcm"
        dcm.write_bytes(b"\x00" * 131)
        with pytest.raises(InvalidDicomError, match="too small"):
            validate_dicom_header(dcm)

    def test_file_exceeds_max_size(self, tmp_path: Path) -> None:
        dcm = tmp_path / "big.dcm"
        dcm.write_bytes(b"\x00" * 200)
        with pytest.raises(InvalidDicomError, match="exceeds"):
            validate_dicom_header(dcm, max_size_bytes=100)

    def test_missing_magic_bytes(self, tmp_path: Path) -> None:
        dcm = tmp_path / "bad_magic.dcm"
        dcm.write_bytes(b"\x00" * 128 + b"NOPE" + b"\x00" * 100)
        with pytest.raises(InvalidDicomError, match="Missing DICOM magic"):
            validate_dicom_header(dcm)

    def test_custom_max_size_bytes(self, tmp_path: Path) -> None:
        dcm = tmp_path / "mid.dcm"
        dcm.write_bytes(b"\x00" * 128 + b"DICM" + b"\x00" * 100)
        # 232 bytes, limit 300 → should pass
        validate_dicom_header(dcm, max_size_bytes=300)
        # 232 bytes, limit 200 → should fail
        with pytest.raises(InvalidDicomError, match="exceeds"):
            validate_dicom_header(dcm, max_size_bytes=200)

    def test_is_a_directory(self, tmp_path: Path) -> None:
        d = tmp_path / "dir.dcm"
        d.mkdir()
        with pytest.raises(InvalidDicomError, match="Not a file"):
            validate_dicom_header(d)


class TestInvalidDicomError:
    def test_is_exception(self) -> None:
        assert issubclass(InvalidDicomError, Exception)

    def test_message_preserved(self) -> None:
        e = InvalidDicomError("test msg")
        assert str(e) == "test msg"


_STUDY_UID = "1.2.826.0.1.3680043.8.498.551.1"
_SERIES_UID = "1.2.826.0.1.3680043.8.498.551.2"
_SOP_UID = "1.2.826.0.1.3680043.8.498.551.3"
_SR_SOP_CLASS = "1.2.840.10008.5.1.4.1.1.88.11"
_PR_SOP_CLASS = "1.2.840.10008.5.1.4.1.1.11.1"


def _raw_dataset(
    *,
    sop_class: str = UltrasoundMultiFrameImageStorage,
    sop_uid: str = _SOP_UID,
    study_uid: str | None = _STUDY_UID,
    series_uid: str | None = _SERIES_UID,
    rows: int | None = 4,
    columns: int | None = 5,
    frames: int = 2,
    pixels: bytes | None = None,
) -> Dataset:
    dataset = Dataset()
    dataset.SOPClassUID = sop_class
    dataset.SOPInstanceUID = sop_uid
    if study_uid is not None:
        dataset.StudyInstanceUID = study_uid
    if series_uid is not None:
        dataset.SeriesInstanceUID = series_uid
    dataset.Modality = "US"
    if rows is not None and columns is not None:
        dataset.Rows = rows
        dataset.Columns = columns
        dataset.SamplesPerPixel = 1
        dataset.PhotometricInterpretation = "MONOCHROME2"
        dataset.BitsAllocated = 8
        dataset.BitsStored = 8
        dataset.HighBit = 7
        dataset.PixelRepresentation = 0
        if frames > 1:
            dataset.NumberOfFrames = frames
        dataset.PixelData = pixels if pixels is not None else bytes(range(rows * columns * frames))
    return dataset


def _write_raw(
    path: Path,
    *,
    implicit: bool = False,
    little_endian: bool = True,
    directory: bool = False,
    **dataset_kwargs,
) -> Path:
    dataset = _raw_dataset(**dataset_kwargs)
    if directory:
        dataset.SOPClassUID = DICOMDIR_SOP_CLASS_UID
        dataset.DirectoryRecordSequence = Sequence()
    buffer = DicomBytesIO()
    buffer.is_implicit_VR = implicit
    buffer.is_little_endian = little_endian
    write_dataset(buffer, dataset)
    path.write_bytes(buffer.getvalue())
    assert path.read_bytes()[128:132] != b"DICM"
    return path


@pytest.fixture(params=[False, True], ids=["explicit-le", "implicit-le"])
def raw_image(request: pytest.FixtureRequest, tmp_path: Path) -> Path:
    return _write_raw(tmp_path / "raw.dcm", implicit=bool(request.param))


class TestRawDatasetValidation:
    def test_raw_image_is_accepted(self, raw_image: Path) -> None:
        assert validate_dicom_header(raw_image) is None

    def test_raw_dicomdir_is_accepted_as_an_index(self, tmp_path: Path) -> None:
        path = _write_raw(tmp_path / "DICOMDIR", directory=True, rows=None, columns=None)

        assert validate_dicom_header(path) is None
        dataset = pydicom.dcmread(path, stop_before_pixels=True, force=True)
        assert classify_dicom_dataset(dataset) is DicomKind.DICOMDIR
        assert classify_dicom_dataset(dataset).is_index is True

    def test_missing_sop_identity_is_corrupt(self, tmp_path: Path) -> None:
        path = _write_raw(tmp_path / "no-sop.dcm", sop_class="", sop_uid="")

        with pytest.raises(CorruptDicomError, match="Missing DICOM magic"):
            validate_dicom_header(path)

    def test_missing_study_series_identity_is_corrupt(self, tmp_path: Path) -> None:
        path = _write_raw(tmp_path / "no-study.dcm", study_uid=None, series_uid=None)

        with pytest.raises(CorruptDicomError, match="Study/Series UID"):
            validate_dicom_header(path)

    def test_arbitrary_binary_without_magic_stays_corrupt(self, tmp_path: Path) -> None:
        path = tmp_path / "payload.bin"
        path.write_bytes(b"not a dicom file, just bytes " * 40)

        with pytest.raises(CorruptDicomError, match="Missing DICOM magic"):
            validate_dicom_header(path)

    def test_truncated_raw_header_is_corrupt(self, tmp_path: Path) -> None:
        path = _write_raw(tmp_path / "truncated.dcm")
        path.write_bytes(path.read_bytes()[:140])

        with pytest.raises(CorruptDicomError, match="Missing DICOM magic"):
            validate_dicom_header(path)

    def test_big_endian_raw_dataset_is_unsupported(self, tmp_path: Path) -> None:
        path = _write_raw(tmp_path / "raw-be.dcm", little_endian=False)

        with pytest.raises(UnsupportedDicomError, match="Big-endian"):
            validate_dicom_header(path)

    def test_part10_magic_keeps_the_fast_path(self, tmp_path: Path) -> None:
        """A Part 10 header is accepted without parsing the rest of the file."""
        path = tmp_path / "part10.dcm"
        path.write_bytes(b"\x00" * 128 + b"DICM" + b"not parsed")

        assert validate_dicom_header(path) is None


class TestRawDatasetReading:
    def test_reads_pixels_from_both_raw_encodings(self, raw_image: Path) -> None:
        pixels = DicomReaderImpl().read_pixels(raw_image, frame_index=1)

        assert pixels.shape == (4, 5)
        assert pixels.tolist() == np.arange(20, 40, dtype=np.uint8).reshape(4, 5).tolist()

    def test_metadata_reports_the_raw_study(self, raw_image: Path) -> None:
        metadata = DicomReaderImpl().read_metadata(raw_image)

        assert metadata.sop_instance_uid == _SOP_UID
        assert metadata.series_uid == _SERIES_UID
        assert metadata.number_of_frames == 2

    def test_raw_pixel_span_starts_at_offset_zero(self, raw_image: Path) -> None:
        """A raw dataset must not be scanned with the Part 10 +132 offset."""
        from echo_personal_tool.infrastructure.dicom_session import _scan_pixel_data_span

        data = raw_image.read_bytes()
        assert _scan_pixel_data_span(data) == (len(data) - 40, 40)

    def test_scanner_binds_a_raw_file_to_its_uid_study(self, raw_image: Path) -> None:
        studies = LocalMediaDirectoryScanner().scan(raw_image.parent)

        assert [study.study_uid for study in studies] == [_STUDY_UID]
        assert len(studies[0].series[0].instances) == 1
        assert studies[0].series[0].instances[0].path == raw_image


class TestUnsupportedAndCorruptAreDistinct:
    def test_structured_report_is_unsupported_not_corrupt(self, tmp_path: Path) -> None:
        path = _write_raw(tmp_path / "report.dcm", sop_class=_SR_SOP_CLASS, rows=None, columns=None)
        validate_dicom_header(path)
        dataset = pydicom.dcmread(path, stop_before_pixels=True, force=True)

        assert classify_dicom_dataset(dataset) is DicomKind.STRUCTURED_REPORT
        with pytest.raises(UnsupportedDicomError, match="structured_report"):
            DicomReaderImpl().read_pixels(path)

    def test_presentation_state_is_unsupported_not_corrupt(self, tmp_path: Path) -> None:
        path = _write_raw(tmp_path / "state.dcm", sop_class=_PR_SOP_CLASS, rows=None, columns=None)

        with pytest.raises(UnsupportedDicomError, match="presentation_state"):
            DicomReaderImpl().read_metadata(path)

    def test_dicomdir_is_an_index_not_a_broken_picture(self, tmp_path: Path) -> None:
        path = _write_raw(tmp_path / "DICOMDIR", directory=True, rows=None, columns=None)

        with pytest.raises(UnsupportedDicomError, match="dicomdir"):
            DicomReaderImpl().read_pixels(path)

    def test_scanner_skips_unsupported_types_without_logging_corruption(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_raw(tmp_path / "image.dcm")
        _write_raw(tmp_path / "report.dcm", sop_class=_SR_SOP_CLASS, rows=None, columns=None)
        _write_raw(tmp_path / "DICOMDIR", directory=True, rows=None, columns=None)

        errors: list[tuple[Path, Exception]] = []
        scanner = LocalMediaDirectoryScanner()
        monkeypatch.setattr(scanner, "_log_scan_error", lambda path, exc: errors.append((path, exc)))

        studies = scanner.scan(tmp_path)

        assert len(studies) == 1
        assert len(studies[0].series[0].instances) == 1
        assert errors == []

    def test_scanner_logs_a_corrupt_raw_header_once(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        broken = _write_raw(tmp_path / "broken.dcm", sop_class="", sop_uid="")

        errors: list[tuple[Path, Exception]] = []
        scanner = LocalMediaDirectoryScanner()
        monkeypatch.setattr(scanner, "_log_scan_error", lambda path, exc: errors.append((path, exc)))

        assert scanner.scan(tmp_path) == []
        assert len(errors) == 1
        assert isinstance(errors[0][1], CorruptDicomError)

        error_log = tmp_path / "errors.log"
        LocalMediaDirectoryScanner(error_log_path=error_log).scan(tmp_path)
        assert error_log.read_text(encoding="utf-8") == "format=.dcm error=CorruptDicomError\n"
        assert broken.name not in error_log.read_text(encoding="utf-8")
