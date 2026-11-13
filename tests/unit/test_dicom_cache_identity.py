"""File-generation regressions for reader and session caches (#543)."""

import os
import sys
from pathlib import Path

import numpy as np
import pydicom
import pytest

from echo_personal_tool.infrastructure.dicom_reader import DicomReaderImpl, _DecodedPixelCache
from echo_personal_tool.infrastructure.dicom_session import DicomSession, release_stale_sessions
from echo_personal_tool.infrastructure.file_identity import FileIdentity
from tests.unit.test_p3_pixel_cache import _make_test_dicom


def _replace_pixels(path: Path, value: int, *, atomic: bool) -> None:
    # Windows may refuse replacement/truncation of a mapped source. Release the
    # session map there; the independent decoded cache must still invalidate.
    if sys.platform == "win32":
        release_stale_sessions()
    dataset = pydicom.dcmread(path)
    dataset.PixelData = np.full((dataset.Rows, dataset.Columns), value, dtype=np.uint16).tobytes()
    target = path.with_suffix(".replacement") if atomic else path
    dataset.save_as(target, enforce_file_format=True)
    if atomic:
        target.replace(path)


@pytest.mark.parametrize("atomic", [False, True])
def test_replaced_source_invalidates_reader_and_session(tmp_path, atomic):
    path = _make_test_dicom(tmp_path)
    reader = DicomReaderImpl()
    first = reader.read_pixels(path).copy()
    stat = path.stat()
    _replace_pixels(path, 42, atomic=atomic)
    # Atomic replacement must be detected even with preserved size/mtime.
    # For in-place writes force an observable timestamp delta on coarse filesystems.
    mtime = stat.st_mtime_ns if atomic else stat.st_mtime_ns + 1_000_000_000
    os.utime(path, ns=(stat.st_atime_ns, mtime))
    result = reader.read_pixels(path)
    assert not np.array_equal(result, first)
    np.testing.assert_array_equal(result, np.full(first.shape, 42))


def test_relative_absolute_alias_uses_same_generation(tmp_path, monkeypatch):
    path = _make_test_dicom(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert FileIdentity.capture(Path("test.dcm")) == FileIdentity.capture(path)
    reader = DicomReaderImpl()
    assert reader.read_pixels(Path("test.dcm")) is reader.read_pixels(path)


def test_deleted_source_never_returns_cached_pixels(tmp_path):
    path = _make_test_dicom(tmp_path)
    reader = DicomReaderImpl()
    reader.read_pixels(path)
    path.unlink()
    with pytest.raises(FileNotFoundError):
        reader.read_pixels(path)


def test_replacement_during_decode_is_retried(tmp_path, monkeypatch):
    path = _make_test_dicom(tmp_path)
    original = DicomSession.read_frame
    calls = []

    def read_and_replace(session, frame_index):
        pixels = original(session, frame_index)
        calls.append(frame_index)
        if len(calls) == 1:
            _replace_pixels(path, 57, atomic=True)
        return pixels

    monkeypatch.setattr(DicomSession, "read_frame", read_and_replace)
    result = DicomReaderImpl().read_pixels(path)
    assert calls == [0, 0]
    np.testing.assert_array_equal(result, np.full(result.shape, 57))


def test_old_decode_cannot_be_cached_under_new_generation(tmp_path):
    path = tmp_path / "source"
    path.write_bytes(b"old")
    identity = FileIdentity.capture(path)
    path.write_bytes(b"new contents")
    cache = _DecodedPixelCache()
    cache.put(path, 0, np.ones((2, 2)), identity=identity)
    assert cache.get(path, 0) is None


def test_continuously_replaced_source_fails_instead_of_returning_old_pixels(tmp_path, monkeypatch):
    path = _make_test_dicom(tmp_path)
    original = DicomSession.read_frame

    def read_and_replace(session, frame_index):
        pixels = original(session, frame_index)
        _replace_pixels(path, 63, atomic=True)
        return pixels

    monkeypatch.setattr(DicomSession, "read_frame", read_and_replace)
    with pytest.raises(OSError, match="source changed"):
        DicomReaderImpl().read_pixels(path)
