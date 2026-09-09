"""Regression coverage for previews, rewarming and truly indexed DICOM fallback."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pydicom
import pytest
from pydicom.encaps import encapsulate
from pydicom.uid import JPEG2000Lossless, RLELossless

from echo_personal_tool.infrastructure import dicom_session as impl
from echo_personal_tool.infrastructure.dicom_reader import DicomReaderImpl
from tests.fixtures.generate_synthetic_dicom import (
    write_synthetic_jpeg_multiframe_dicom,
    write_synthetic_multiframe_dicom,
)


@pytest.fixture(autouse=True)
def clean_sessions():
    impl._cleanup_all_sessions()
    yield
    impl._cleanup_all_sessions()


def jpeg(tmp_path, name):
    path = tmp_path / name
    write_synthetic_jpeg_multiframe_dicom(path, frame_count=6, rows=64, cols=64)
    return path


def test_preview_keeps_active_compressed_session_warm(tmp_path, monkeypatch):
    a, b = jpeg(tmp_path, "a.dcm"), jpeg(tmp_path, "b.dcm")
    active = impl.get_dicom_session(a)
    active.open(a)
    active.decode_first_frame()
    payload = active._encapsulated_frames

    def no_fallback(*args):
        pytest.fail("preview invalidated active pixels")

    monkeypatch.setattr(active, "_decode_pydicom_fallback", no_fallback)
    for _ in range(3):
        pixels = DicomReaderImpl(isolated=True).read_pixels(b, 2)
        assert pixels.shape == (64, 64)
        assert active._encapsulated_frames is payload
        assert active.decode_single_frame(1).shape == (64, 64)
    assert len(impl._all_sessions) == len(impl._session_registry) == 1


def test_preview_does_not_wait_for_active_session_lock(tmp_path):
    a, b = jpeg(tmp_path, "a.dcm"), jpeg(tmp_path, "b.dcm")
    active = impl.get_dicom_session(a)
    active.open(a)
    # Hold a's lock in this thread. A preview on b must not acquire it to evict a.
    with ThreadPoolExecutor(max_workers=1) as pool:
        with active._lock:
            result = pool.submit(DicomReaderImpl(isolated=True).read_pixels, b, 2)
            assert result.result(timeout=5).shape == (64, 64)


def test_preview_releases_buffers_on_decode_error(tmp_path, monkeypatch):
    path = jpeg(tmp_path, "bad.dcm")
    sessions = []

    def fail(self, index):
        sessions.append(self)
        raise ValueError("decode failed")

    monkeypatch.setattr(impl.DicomSession, "read_frame", fail)
    with pytest.raises(ValueError, match="decode failed"):
        DicomReaderImpl(isolated=True).read_pixels(path)
    assert sessions[0]._raw_bytes is None
    assert sessions[0]._metadata is None
    assert sessions[0]._open_path is None


def test_compressed_rewarm_without_open_never_decodes_full_cine(tmp_path, monkeypatch):
    path = jpeg(tmp_path, "rewarm.dcm")
    session = impl.get_dicom_session(path)
    session.open(path)
    expected = session.decode_single_frame(2)
    session.release_heavy()

    def no_fallback(*args):
        pytest.fail("a cold compressed index must be rebuilt before decoding")

    monkeypatch.setattr(session, "_decode_pydicom_fallback", no_fallback)
    np.testing.assert_array_equal(session.decode_single_frame(2), expected)
    assert session._encapsulated_frames is not None


def test_rle_fallback_requests_only_one_index_and_owns_frame(tmp_path, monkeypatch):
    path = tmp_path / "rle.dcm"
    write_synthetic_multiframe_dicom(path, frame_count=6, rows=64, cols=64)
    ds = pydicom.dcmread(path)
    ds.compress(RLELossless)
    ds.save_as(path, enforce_file_format=True)
    requested = []
    original = pydicom.pixels.pixel_array

    def indexed(source, *, index=None, **kwargs):
        assert index is not None, "must never request the whole cine"
        requested.append(index)
        return original(source, index=index, **kwargs)

    monkeypatch.setattr(pydicom.pixels, "pixel_array", indexed)
    session = impl.DicomSession(isolated=True)
    try:
        session.open(path)
        frame = session.decode_single_frame(3)
        assert requested == [3]
        assert frame.flags.owndata and frame.base is None
        assert frame.nbytes == 64 * 64
        assert int(frame[0, 0]) == 3
        requested.clear()
        frames = session.decode_all_frames()
        assert sorted(requested) == list(range(6))
        assert frames.shape == (6, 64, 64)
        assert [int(f[0, 0]) for f in frames] == list(range(6))
    finally:
        session.release()


@pytest.mark.parametrize("dtype,bits", [(np.uint8, 8), (np.uint16, 12), (np.uint16, 16)])
@pytest.mark.parametrize("photometric", ["MONOCHROME1", "MONOCHROME2"])
def test_j2k_fast_route_is_pixel_exact_and_avoids_gil_backend(tmp_path, monkeypatch, dtype, bits, photometric):
    import openjpeg

    path = tmp_path / "j2k.dcm"
    write_synthetic_multiframe_dicom(path, frame_count=3, rows=64, cols=64)
    ds = pydicom.dcmread(path)
    pixels = np.random.default_rng(42).integers(0, 2**bits, (3, 64, 64), dtype=dtype)
    ds.BitsAllocated = np.dtype(dtype).itemsize * 8
    ds.BitsStored = bits
    ds.HighBit = bits - 1
    ds.PhotometricInterpretation = photometric
    ds.file_meta.TransferSyntaxUID = JPEG2000Lossless
    ds.PixelData = encapsulate([openjpeg.encode(frame, bits_stored=bits) for frame in pixels])
    ds["PixelData"].is_undefined_length = True
    ds.save_as(path, enforce_file_format=True)
    reference = pydicom.pixels.pixel_array(path, index=1)

    def no_openjpeg(*args):
        pytest.fail("supported unsigned monochrome J2K must use GIL-releasing cv2")

    monkeypatch.setattr(impl, "_decode_fragment_openjpeg", no_openjpeg)
    session = impl.DicomSession(isolated=True)
    try:
        session.open(path)
        decoded = session.decode_single_frame(1)
        np.testing.assert_array_equal(decoded, reference)
        np.testing.assert_array_equal(decoded, pixels[1])
        assert decoded.dtype == reference.dtype
    finally:
        session.release()


def test_j2k_failed_cv2_candidate_uses_existing_backend(tmp_path, monkeypatch):
    from tests.fixtures.generate_synthetic_dicom import write_synthetic_jpeg2000_multiframe_dicom

    path = tmp_path / "j2k.dcm"
    write_synthetic_jpeg2000_multiframe_dicom(path, frame_count=3, rows=64, cols=64)
    monkeypatch.setattr(impl, "_decode_fragment_cv2", lambda *args: None)
    session = impl.DicomSession(isolated=True)
    try:
        session.open(path)
        np.testing.assert_array_equal(session.decode_single_frame(1), pydicom.pixels.pixel_array(path, index=1))
    finally:
        session.release()


@pytest.mark.parametrize(
    "syntax,samples,signed,photometric,bits",
    [
        ("1.2.840.10008.1.2.4.91", 1, 0, "MONOCHROME2", 8),
        ("1.2.840.10008.1.2.4.90", 1, 1, "MONOCHROME2", 16),
        ("1.2.840.10008.1.2.4.90", 3, 0, "RGB", 8),
        ("1.2.840.10008.1.2.4.90", 3, 0, "YBR_RCT", 8),
    ],
)
def test_unvalidated_j2k_formats_keep_existing_backend(monkeypatch, syntax, samples, signed, photometric, bits):
    ds = pydicom.Dataset()
    ds.Rows = ds.Columns = 8
    ds.SamplesPerPixel = samples
    ds.PixelRepresentation = signed
    ds.PhotometricInterpretation = photometric
    ds.BitsAllocated = bits
    session = impl.DicomSession(isolated=True)
    session._metadata = ds
    session._frame_count = 1
    session._is_uncompressed = False
    session._transfer_syntax_uid = syntax
    session._encapsulated_frames = [b"fixture"]
    expected = np.zeros((8, 8), dtype=np.uint8)

    def no_candidate(*args):
        pytest.fail("must not switch an unvalidated format to the new cv2-first route")

    monkeypatch.setattr(impl, "_decode_fragment_cv2", no_candidate)
    monkeypatch.setattr(impl, "_decode_compressed_frame", lambda *args: expected)
    assert session._decode_single_frame(0) is expected


def test_dicom_without_pixel_data_raises_value_error(tmp_path):
    """A DICOM file with no pixel data must raise ValueError (not raw AttributeError)."""
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian

    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    file_meta.MediaStorageSOPInstanceUID = "1.2.3"
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

    path = tmp_path / "no_pixels.dcm"
    ds = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\x00" * 128)
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    ds.SOPInstanceUID = "1.2.3"
    ds.StudyInstanceUID = "1.2.4"
    ds.SeriesInstanceUID = "1.2.5"
    ds.Modality = "CT"
    ds.Rows = 64
    ds.Columns = 64
    ds.BitsAllocated = 8
    ds.BitsStored = 8
    ds.HighBit = 7
    ds.PixelRepresentation = 0
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    # Intentionally omit PixelData
    ds.save_as(str(path))

    reader = DicomReaderImpl(isolated=True)
    with pytest.raises(ValueError, match="no pixel data"):
        reader.read_pixels(path, frame_index=0)
