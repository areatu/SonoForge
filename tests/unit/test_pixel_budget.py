"""Decode budget of the DICOM session (S3-04, #313).

Two promises are pinned here:

* the arithmetic of ``Rows × Columns × Frames × SamplesPerPixel`` and the limit;
* the session refuses an oversized study *before* any pixel byte is mapped or
  read, and leaves nothing of the refused file behind.
"""

from __future__ import annotations

from pathlib import Path

import pydicom
import pytest
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian

from echo_personal_tool.infrastructure.dicom_session import DicomSession
from echo_personal_tool.infrastructure.pixel_budget import (
    MAX_DECODED_PIXELS,
    StudyTooLargeError,
    check_dataset_budget,
    check_pixel_budget,
    decoded_pixels,
)

UID = "1.2.840.113619.2.55.3.1234567890.313"


def _write_header_only_dicom(
    path: Path,
    *,
    rows: int,
    columns: int,
    frames: int | None,
    samples: int = 1,
) -> Path:
    """Write a readable DICOM whose *header* claims a pathological geometry.

    The pixel block is deliberately tiny: the budget must be enforced from the
    header, so the test never has to allocate what it refuses.
    """
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.6.1"
    meta.MediaStorageSOPInstanceUID = UID
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    dataset = FileDataset(str(path), {}, file_meta=meta, preamble=b"\x00" * 128)

    dataset.Rows = rows
    dataset.Columns = columns
    dataset.SamplesPerPixel = samples
    dataset.PhotometricInterpretation = "RGB" if samples == 3 else "MONOCHROME2"
    dataset.BitsAllocated = 8
    dataset.BitsStored = 8
    dataset.HighBit = 7
    dataset.PixelRepresentation = 0
    dataset.NumberOfFrames = frames
    # Eight bytes, whatever the header claims: the budget must be enforced from
    # the header alone, and a test must never write what it refuses to decode.
    dataset.PixelData = b"\x00" * 8
    dataset.save_as(str(path), enforce_file_format=True)
    return path


# ── arithmetic ───────────────────────────────────────────────────────


class TestDecodedPixels:
    def test_multiplies_every_factor(self) -> None:
        assert decoded_pixels(2, 3, 4, 5) == 120

    def test_defaults_to_one_sample(self) -> None:
        assert decoded_pixels(10, 10, 3) == 300

    @pytest.mark.parametrize("junk", [None, "", "abc", -5, object()])
    def test_junk_becomes_zero(self, junk: object) -> None:
        # A malformed header must not turn into an exception of its own; the
        # decoder reports the missing geometry itself.
        assert decoded_pixels(junk, 10, 10) == 0


class TestCheckPixelBudget:
    def test_accepts_a_normal_cine(self) -> None:
        assert check_pixel_budget(512, 512, 120) == 512 * 512 * 120

    def test_accepts_exactly_the_limit(self) -> None:
        assert check_pixel_budget(10_000, 10_000, 2) == 200_000_000

    def test_refuses_one_pixel_over_the_limit(self) -> None:
        with pytest.raises(StudyTooLargeError):
            check_pixel_budget(10_000, 10_000, 2, limit=199_999_999)

    def test_samples_are_counted(self) -> None:
        # An RGB frame of the same geometry allocates three times the memory.
        with pytest.raises(StudyTooLargeError):
            check_pixel_budget(512, 512, 300, samples=3)

    def test_explicit_limit_overrides_the_default(self) -> None:
        with pytest.raises(StudyTooLargeError):
            check_pixel_budget(100, 100, 100, limit=999_999)

    def test_the_default_limit_is_two_hundred_megapixels(self) -> None:
        assert MAX_DECODED_PIXELS == 200_000_000


class TestStudyTooLargeError:
    def test_reports_the_measured_and_allowed_budgets(self) -> None:
        error = StudyTooLargeError(10_000, 10_000, 10)
        assert error.pixels == 1_000_000_000
        assert error.megapixels == 1000.0
        assert error.limit_megapixels == 200.0
        assert error.code == "study_too_large"

    def test_message_carries_numbers_only(self) -> None:
        # The same message reaches the status bar, so it must never grow a path
        # or an identifier.
        message = str(StudyTooLargeError(20_000, 20_000, 1))
        assert "rows=20000" in message
        assert "columns=20000" in message
        assert "/" not in message
        assert ".dcm" not in message


class TestCheckDatasetBudget:
    def test_reads_geometry_from_the_dataset(self) -> None:
        class _Dataset:
            Rows = 100
            Columns = 200
            SamplesPerPixel = 1

        assert check_dataset_budget(_Dataset(), 3) == 60_000

    def test_absent_geometry_passes(self) -> None:
        class _Dataset:
            pass

        assert check_dataset_budget(_Dataset(), 5) == 0


# ── the session refuses before pixels ────────────────────────────────


class TestSessionRefusesOversizedStudies:
    def test_single_pathological_frame_is_refused_before_reading_bytes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = _write_header_only_dicom(tmp_path / "huge_frame.dcm", rows=20_000, columns=20_000, frames=None)

        def _no_read(self: Path) -> bytes:  # pragma: no cover - must not run
            raise AssertionError("the pixel block must not be read for a refused study")

        monkeypatch.setattr(Path, "read_bytes", _no_read)
        session = DicomSession(isolated=True)
        with pytest.raises(StudyTooLargeError):
            session.open(path)

    def test_multi_frame_study_is_refused_on_the_real_frame_count(self, tmp_path: Path) -> None:
        # 10 000 × 10 000 is 100 Mpx per frame (inside the budget), so only the
        # frame count makes this study oversized — the second check catches it.
        path = _write_header_only_dicom(tmp_path / "huge_cine.dcm", rows=10_000, columns=10_000, frames=10)

        session = DicomSession(isolated=True)
        with pytest.raises(StudyTooLargeError) as raised:
            session.open(path)

        assert raised.value.frames == 10

    def test_a_refused_study_leaves_nothing_behind(self, tmp_path: Path) -> None:
        path = _write_header_only_dicom(tmp_path / "huge_cine.dcm", rows=10_000, columns=10_000, frames=10)
        session = DicomSession(isolated=True)

        with pytest.raises(StudyTooLargeError):
            session.open(path)

        assert session.frame_count == 0
        assert session._metadata is None  # noqa: SLF001 - the point of the test
        assert session._pixel_data_raw is None  # noqa: SLF001
        assert session._open_path is None  # noqa: SLF001

    def test_a_normal_study_still_opens(self, tmp_path: Path) -> None:
        from tests.fixtures.generate_synthetic_dicom import write_synthetic_multiframe_dicom

        path = tmp_path / "normal.dcm"
        write_synthetic_multiframe_dicom(path)
        session = DicomSession(isolated=True)
        try:
            session.open(path)
            assert session.frame_count > 0
        finally:
            session.release()


# ── the worker explains the refusal ──────────────────────────────────


def test_the_decode_worker_names_the_budget_without_a_path() -> None:
    from echo_personal_tool.application.workers.dicom_decode_worker import (
        _study_too_large_message,
    )

    message = _study_too_large_message(StudyTooLargeError(10_000, 10_000, 10))

    assert "1000" in message
    assert "200" in message
    assert ".dcm" not in message
    assert "/" not in message


def test_the_header_only_fixture_parses_without_pixels(tmp_path: Path) -> None:
    """Guard for the fixture itself: the header must be readable on its own."""
    path = _write_header_only_dicom(tmp_path / "header.dcm", rows=64, columns=64, frames=2)
    dataset = pydicom.dcmread(str(path), stop_before_pixels=True, force=True)
    assert (int(dataset.Rows), int(dataset.Columns), int(dataset.NumberOfFrames)) == (64, 64, 2)
