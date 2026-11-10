"""Per-frame limit, pixel-data layout and the frame-count fallback without a whole-file read (#475)."""

from __future__ import annotations

import struct
from io import BytesIO
from pathlib import Path

import numpy as np
import pydicom
import pytest
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.encaps import encapsulate
from pydicom.uid import ExplicitVRLittleEndian, ImplicitVRLittleEndian

from echo_personal_tool.infrastructure import dicom_session
from echo_personal_tool.infrastructure.dicom_frame_count import infer_frame_count_from_layout
from echo_personal_tool.infrastructure.dicom_frame_geometry import (
    MAX_FRAME_BYTES,
    DicomFrameGeometryError,
    check_frame_geometry,
    pixel_data_layout,
    read_value,
)
from echo_personal_tool.infrastructure.dicom_session import DicomSession
from tests.fixtures.generate_synthetic_dicom import write_synthetic_jpeg_multiframe_dicom


def _geometry(**header: object) -> Dataset:
    dataset = Dataset()
    for keyword, value in header.items():
        setattr(dataset, keyword, value)
    return dataset


def _element_offset(path: Path) -> int:
    with path.open("rb") as fh:
        pydicom.dcmread(fh, stop_before_pixels=True, force=True)
        return fh.tell()


def _drop_number_of_frames(path: Path) -> Path:
    dataset = pydicom.dcmread(path)
    del dataset.NumberOfFrames
    dataset.save_as(path)
    return path


def _native(path: Path, *, frames: int, implicit: bool = False, rows: int = 8, cols: int = 8) -> Path:
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = pydicom.uid.UltrasoundMultiFrameImageStorage
    meta.MediaStorageSOPInstanceUID = pydicom.uid.generate_uid()
    meta.TransferSyntaxUID = ImplicitVRLittleEndian if implicit else ExplicitVRLittleEndian
    dataset = FileDataset(str(path), {}, file_meta=meta, preamble=b"\x00" * 128)
    dataset.Rows = rows
    dataset.Columns = cols
    dataset.SamplesPerPixel = 1
    dataset.PhotometricInterpretation = "MONOCHROME2"
    dataset.BitsAllocated = 8
    dataset.BitsStored = 8
    dataset.HighBit = 7
    dataset.PixelRepresentation = 0
    dataset.PixelData = bytes(range(rows * cols)) * frames
    dataset.save_as(str(path), enforce_file_format=True)
    return path


class TestFrameGeometry:
    def test_the_limit_keeps_room_for_real_frames(self) -> None:
        # 8K RGB at 16 bits per sample — far above any echo frame — is inside the limit.
        geometry = check_frame_geometry(_geometry(Rows=4320, Columns=7680, SamplesPerPixel=3, BitsAllocated=16))

        assert geometry is not None
        assert geometry.frame_bytes == 4320 * 7680 * 3 * 2 < MAX_FRAME_BYTES

    def test_the_forged_header_from_the_issue_is_far_above_it(self) -> None:
        with pytest.raises(DicomFrameGeometryError) as caught:
            check_frame_geometry(_geometry(Rows=65535, Columns=65535, SamplesPerPixel=3, BitsAllocated=8))

        assert caught.value.code == "limit"
        assert "256 MiB" in str(caught.value)

    def test_sub_byte_samples_round_up_to_a_byte(self) -> None:
        geometry = check_frame_geometry(_geometry(Rows=10, Columns=10, SamplesPerPixel=1, BitsAllocated=1))

        assert geometry is not None
        assert geometry.frame_bytes == 100

    def test_a_dataset_without_pixel_geometry_is_not_checked(self) -> None:
        assert check_frame_geometry(_geometry(Modality="SR")) is None

    def test_the_limit_is_a_parameter_for_tests_and_callers(self) -> None:
        with pytest.raises(DicomFrameGeometryError):
            check_frame_geometry(_geometry(Rows=16, Columns=16), limit=255)


class TestPixelDataLayout:
    def test_native_explicit_vr(self, tmp_path: Path) -> None:
        path = _native(tmp_path / "native.dcm", frames=3)

        layout = pixel_data_layout(path, _element_offset(path))

        assert layout is not None
        assert not layout.encapsulated
        assert layout.length == 3 * 64
        assert read_value(path, layout) == pydicom.dcmread(path).PixelData

    def test_native_implicit_vr(self, tmp_path: Path) -> None:
        path = _native(tmp_path / "implicit.dcm", frames=2, implicit=True)

        layout = pixel_data_layout(path, _element_offset(path))

        assert layout is not None
        assert (layout.length, layout.items) == (2 * 64, None)
        assert read_value(path, layout) == pydicom.dcmread(path).PixelData

    def test_encapsulated_items_are_counted_and_the_value_matches_pydicom(self, tmp_path: Path) -> None:
        path = write_synthetic_jpeg_multiframe_dicom(tmp_path / "jpeg.dcm", frame_count=4, rows=16, cols=16)

        layout = pixel_data_layout(path, _element_offset(path))

        assert layout is not None
        assert layout.items == 5  # Basic Offset Table + one fragment per frame
        assert read_value(path, layout) == pydicom.dcmread(path).PixelData

    def test_a_damaged_item_is_not_guessed(self, tmp_path: Path) -> None:
        path = write_synthetic_jpeg_multiframe_dicom(tmp_path / "jpeg.dcm", frame_count=2, rows=16, cols=16)
        offset = _element_offset(path)
        raw = bytearray(path.read_bytes())
        # The first item's length now points past the end of the file.
        struct.pack_into("<I", raw, offset + 12 + 4, 0x7FFFFFF0)
        path.write_bytes(bytes(raw))

        assert pixel_data_layout(path, offset) is None

    def test_an_offset_that_is_not_the_pixel_element_gives_none(self, tmp_path: Path) -> None:
        path = _native(tmp_path / "native.dcm", frames=1)

        assert pixel_data_layout(path, 0) is None
        assert pixel_data_layout(path, path.stat().st_size) is None

    def test_frame_count_from_the_layout(self) -> None:
        header = _geometry(Rows=8, Columns=8, SamplesPerPixel=1, BitsAllocated=8)

        assert infer_frame_count_from_layout(header, native_length=5 * 64) == 5
        assert infer_frame_count_from_layout(header, native_length=64) == 1
        assert infer_frame_count_from_layout(header, native_length=5 * 64 + 3) == 1
        assert infer_frame_count_from_layout(header, encapsulated_items=7) == 6
        assert infer_frame_count_from_layout(header, encapsulated_items=2) == 1
        header.NumberOfFrames = 9
        assert infer_frame_count_from_layout(header, encapsulated_items=3) == 9


class TestFrameCountFallbackReadsNoWholeFile:
    """Without NumberOfFrames, open() used to read the whole file and parse it a second time."""

    @pytest.fixture
    def whole_file_reads(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        reads: list[str] = []
        original_read_bytes = Path.read_bytes
        original_dcmread = pydicom.dcmread

        def read_bytes(self: Path) -> bytes:
            reads.append(f"read_bytes:{self.name}")
            return original_read_bytes(self)

        def dcmread(fp: object, *args: object, **kwargs: object) -> object:
            if isinstance(fp, BytesIO):
                reads.append("dcmread(BytesIO)")
            elif not kwargs.get("stop_before_pixels"):
                reads.append("dcmread(full)")
            return original_dcmread(fp, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(Path, "read_bytes", read_bytes)
        monkeypatch.setattr(dicom_session.pydicom, "dcmread", dcmread)
        return reads

    def test_an_encapsulated_cine_without_the_tag_recovers_its_frames(
        self, tmp_path: Path, whole_file_reads: list[str]
    ) -> None:
        path = _drop_number_of_frames(
            write_synthetic_jpeg_multiframe_dicom(tmp_path / "jpeg.dcm", frame_count=6, rows=16, cols=16)
        )
        whole_file_reads.clear()  # writing the fixture is not the session's doing
        session = DicomSession(isolated=True)
        try:
            session.open(path)
            assert session.frame_count == 6
            assert whole_file_reads == []
            assert session._raw_bytes is None

            frames = [session.decode_single_frame(index) for index in range(6)]
        finally:
            session.release()

        assert [frame.shape for frame in frames] == [(16, 16)] * 6
        assert whole_file_reads == []

    def test_a_native_cine_without_the_tag_recovers_its_frames(
        self, tmp_path: Path, whole_file_reads: list[str]
    ) -> None:
        path = _native(tmp_path / "native.dcm", frames=4)
        whole_file_reads.clear()
        session = DicomSession(isolated=True)
        try:
            session.open(path)
            assert session.frame_count == 4
            first = session.decode_single_frame(0)
        finally:
            session.release()

        assert whole_file_reads == []
        assert np.array_equal(first.ravel(), np.arange(64, dtype=np.uint8))

    def test_after_release_heavy_only_the_pixel_value_is_read_again(
        self, tmp_path: Path, whole_file_reads: list[str]
    ) -> None:
        path = write_synthetic_jpeg_multiframe_dicom(tmp_path / "jpeg.dcm", frame_count=3, rows=16, cols=16)
        whole_file_reads.clear()
        session = DicomSession(isolated=True)
        try:
            session.open(path)
            session.decode_single_frame(0)
            session.release_heavy()

            frame = session.decode_single_frame(2)
        finally:
            session.release()

        assert frame.shape == (16, 16)
        assert whole_file_reads == []


class TestWorkerMessages:
    def test_typed_refusals_get_their_own_static_message(self) -> None:
        from echo_personal_tool.application.workers.dicom_decode_worker import (
            DICOM_FRAME_INVALID_MESSAGE,
            DICOM_FRAME_TOO_LARGE_MESSAGE,
            frame_geometry_failure_message,
        )

        assert frame_geometry_failure_message(DicomFrameGeometryError("limit", "x")) == DICOM_FRAME_TOO_LARGE_MESSAGE
        assert frame_geometry_failure_message(DicomFrameGeometryError("invalid", "x")) == DICOM_FRAME_INVALID_MESSAGE

    def test_the_decode_worker_reports_a_forged_header_without_decoding(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        from echo_personal_tool.application.workers.dicom_decode_worker import (
            DICOM_FRAME_TOO_LARGE_MESSAGE,
            DicomDecodeWorker,
        )

        meta = FileMetaDataset()
        meta.MediaStorageSOPClassUID = pydicom.uid.UltrasoundMultiFrameImageStorage
        meta.MediaStorageSOPInstanceUID = pydicom.uid.generate_uid()
        meta.TransferSyntaxUID = pydicom.uid.JPEG2000Lossless
        dataset = FileDataset(str(tmp_path / "forged.dcm"), {}, file_meta=meta, preamble=b"\x00" * 128)
        dataset.Rows = dataset.Columns = 65535
        dataset.SamplesPerPixel = 3
        dataset.PhotometricInterpretation = "RGB"
        dataset.BitsAllocated = dataset.BitsStored = 8
        dataset.HighBit = 7
        dataset.PixelRepresentation = 0
        dataset.PixelData = encapsulate([b"\x00" * 64])
        dataset["PixelData"].VR = "OB"
        path = tmp_path / "forged.dcm"
        dataset.save_as(str(path), enforce_file_format=True)

        worker = DicomDecodeWorker(path, request_id=7)
        failures: list[tuple[int, str]] = []
        frames: list[object] = []
        worker.signals.failed.connect(lambda request_id, message: failures.append((request_id, message)))
        worker.signals.first_frame_ready.connect(lambda *args: frames.append(args))

        with caplog.at_level("WARNING"):
            worker.run()

        assert failures == [(7, DICOM_FRAME_TOO_LARGE_MESSAGE)]
        assert frames == []
        assert any("operation=dicom.decode code=limit error_type=ValueError" in r.getMessage() for r in caplog.records)
        assert all(str(tmp_path) not in r.getMessage() for r in caplog.records)
