"""A study is never refused for its size (regression for the 200 Mpx budget).

A one-minute 512×512 cine at 30 fps is ~1564 frames (~410 Mpx).  The S3-04
decode budget rejected exactly that study before a single frame was decoded,
so a legitimate long loop could not be opened at all.  Clinical loops must
decode; memory is bounded by the frame cache and the memmap path for
uncompressed pixel data, not by a header threshold.

The fixtures below claim a large geometry but carry only a tiny pixel block:
``open()`` reads the header and the frame count, never the pixels, so the test
proves the size refusal is gone without allocating hundreds of megabytes.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian

from echo_personal_tool.infrastructure.dicom_session import DicomSession

UID = "1.2.840.113619.2.55.3.1234567890.314"


def _write_header_only_cine(
    path: Path,
    *,
    rows: int,
    columns: int,
    frames: int,
    samples: int = 1,
    bits: int = 8,
) -> Path:
    """Write a readable DICOM whose header describes a large, long cine."""
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.6.1"
    meta.MediaStorageSOPInstanceUID = UID
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    dataset = FileDataset(str(path), {}, file_meta=meta, preamble=b"\x00" * 128)

    dataset.Rows = rows
    dataset.Columns = columns
    dataset.SamplesPerPixel = samples
    dataset.PhotometricInterpretation = "RGB" if samples == 3 else "MONOCHROME2"
    dataset.BitsAllocated = bits
    dataset.BitsStored = bits
    dataset.HighBit = bits - 1
    dataset.PixelRepresentation = 0
    dataset.NumberOfFrames = frames
    # Eight bytes, whatever the header claims: this test never decodes pixels.
    dataset.PixelData = b"\x00" * 8
    dataset.save_as(str(path), enforce_file_format=True)
    return path


class TestLongStudiesAreNeverRefusedForSize:
    def test_a_one_minute_512_cine_opens(self, tmp_path: Path) -> None:
        # 512 × 512 × 1564 frames = 410 Mpx, above the former 200 Mpx budget.
        path = _write_header_only_cine(
            tmp_path / "one_minute.dcm",
            rows=512,
            columns=512,
            frames=1564,
        )

        session = DicomSession(isolated=True)
        try:
            session.open(path)
            assert session.frame_count == 1564
        finally:
            session.release()

    def test_a_sixteen_bit_long_cine_opens(self, tmp_path: Path) -> None:
        # The same one-minute loop at 16 bits is ~820 Mpx; the sample count,
        # not the byte width, used to be the refusal reason.
        path = _write_header_only_cine(
            tmp_path / "one_minute_16bit.dcm",
            rows=512,
            columns=512,
            frames=1564,
            bits=16,
        )

        session = DicomSession(isolated=True)
        try:
            session.open(path)
            assert session.frame_count == 1564
        finally:
            session.release()

    def test_an_rgb_cine_over_two_hundred_megapixels_opens(self, tmp_path: Path) -> None:
        # 512 × 512 × 300 × 3 samples = 236 Mpx.
        path = _write_header_only_cine(
            tmp_path / "rgb.dcm",
            rows=512,
            columns=512,
            frames=300,
            samples=3,
        )

        session = DicomSession(isolated=True)
        try:
            session.open(path)
            assert session.frame_count == 300
        finally:
            session.release()

    def test_the_session_has_no_size_refusal_hook(self) -> None:
        # Guard against reintroducing a header-only refusal in the open path.
        assert not hasattr(DicomSession, "_enforce_pixel_budget")

    def test_the_validator_has_no_default_size_limit(self) -> None:
        # The pre-parse validator used to refuse files over 500 MB.  The
        # application must not set a size limit; the optional guard stays for
        # callers that explicitly ask for one.
        import inspect

        from echo_personal_tool.infrastructure.dicom_validator import (
            validate_dicom_header,
        )

        signature = inspect.signature(validate_dicom_header)
        assert signature.parameters["max_size_bytes"].default is None

    def test_the_refusal_message_is_gone_from_locales(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        for name in ("en", "ru"):
            path = repo_root / "src/echo_personal_tool/infrastructure/locales" / f"{name}.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            assert "status.study_too_large" not in payload

    def test_the_worker_has_no_size_refusal_path(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        source = (repo_root / "src/echo_personal_tool/application/workers/dicom_decode_worker.py").read_text(
            encoding="utf-8"
        )
        assert "StudyTooLargeError" not in source
        assert "pixel_budget" not in source
