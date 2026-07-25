"""Windows-style path compatibility tests for DICOM file handling.

Covers: backslash separators, UNC paths, Cyrillic characters in paths,
spaces in directory/file names.

Run:  ECHO_COMPAT=1 pytest tests/compat/test_windows_paths.py -v
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from tests.fixtures.generate_synthetic_dicom import write_synthetic_multiframe_dicom

_compat = pytest.mark.compat


def _make_dicom(tmp_path: Path, name: str = "test.dcm") -> Path:
    return write_synthetic_multiframe_dicom(
        tmp_path / name,
        frame_count=5,
        rows=32,
        cols=32,
    )


# ── Backslash paths ─────────────────────────────────────────────────


@_compat
@pytest.mark.xfail(sys.platform != "win32", reason="Windows-style backslash paths", strict=False)
def test_backslash_path_open(tmp_path: Path) -> None:
    """pydicom.dcmread should handle Windows backslash paths."""
    import pydicom

    dcm = _make_dicom(tmp_path, "backslash.dcm")
    win_path = str(dcm).replace("/", "\\")
    ds = pydicom.dcmread(win_path, force=True)
    assert ds.Rows == 32


@_compat
@pytest.mark.xfail(sys.platform != "win32", reason="Windows-style backslash paths", strict=False)
def test_backslash_path_decode(tmp_path: Path) -> None:
    """DicomSession.open() should handle backslash separators."""
    from echo_personal_tool.infrastructure.dicom_session import DicomSession

    dcm = _make_dicom(tmp_path, "decode.dcm")
    win_path = Path(str(dcm).replace("/", "\\"))
    session = DicomSession()
    session.open(win_path)
    assert session.frame_count == 5


@_compat
@pytest.mark.xfail(sys.platform != "win32", reason="Windows-style backslash paths", strict=False)
def test_backslash_in_subdirectory(tmp_path: Path) -> None:
    """Nested directory with backslash path components."""
    from echo_personal_tool.infrastructure.dicom_session import DicomSession

    subdir = tmp_path / "sub1" / "sub2" / "sub3"
    subdir.mkdir(parents=True)
    dcm = write_synthetic_multiframe_dicom(
        subdir / "nested.dcm",
        frame_count=3,
        rows=32,
        cols=32,
    )
    win_path = Path(str(dcm).replace("/", "\\"))
    session = DicomSession()
    session.open(win_path)
    assert session.frame_count == 3


# ── UNC paths ───────────────────────────────────────────────────────


@_compat
@pytest.mark.xfail(sys.platform != "win32", reason="UNC path support", strict=False)
def test_unc_path_read(tmp_path: Path) -> None:
    """UNC path (\\\\server\\share) should resolve for pydicom reads."""
    import pydicom

    dcm = _make_dicom(tmp_path, "unc.dcm")
    unc_path = "\\\\localhost\\" + str(dcm).replace("C:\\", "C$\\")
    ds = pydicom.dcmread(unc_path, force=True)
    assert ds.Rows == 32


@_compat
@pytest.mark.xfail(sys.platform != "win32", reason="UNC path support", strict=False)
def test_unc_path_decode(tmp_path: Path) -> None:
    """DicomSession with UNC-style path."""
    from echo_personal_tool.infrastructure.dicom_session import DicomSession

    dcm = _make_dicom(tmp_path, "unc_decode.dcm")
    unc_path = Path("\\\\127.0.0.1\\share\\" + dcm.name)
    session = DicomSession()
    session.open(unc_path)
    assert session.frame_count == 5


# ── Cyrillic characters ─────────────────────────────────────────────


@_compat
@pytest.mark.xfail(sys.platform != "win32", reason="Cyrillic path support on Windows", strict=False)
def test_cyrillic_directory_name(tmp_path: Path) -> None:
    """Directory with Cyrillic characters (Кардиология)."""
    from echo_personal_tool.infrastructure.dicom_session import DicomSession

    cyrillic_dir = tmp_path / "Кардиология" / "Пациент_001"
    cyrillic_dir.mkdir(parents=True)
    dcm = write_synthetic_multiframe_dicom(
        cyrillic_dir / "снимок.dcm",
        frame_count=4,
        rows=32,
        cols=32,
    )
    session = DicomSession()
    session.open(dcm)
    assert session.frame_count == 4


@_compat
@pytest.mark.xfail(sys.platform != "win32", reason="Cyrillic path support on Windows", strict=False)
def test_cyrillic_filename(tmp_path: Path) -> None:
    """DICOM file with Cyrillic filename."""
    from echo_personal_tool.infrastructure.dicom_session import DicomSession

    dcm = write_synthetic_multiframe_dicom(
        tmp_path / "файл_эхоСКГ.dcm",
        frame_count=3,
        rows=32,
        cols=32,
    )
    session = DicomSession()
    session.open(dcm)
    assert session.frame_count == 3


@_compat
@pytest.mark.xfail(sys.platform != "win32", reason="Mixed script path support", strict=False)
def test_mixed_cyrillic_latin_path(tmp_path: Path) -> None:
    """Path mixing Cyrillic and Latin characters."""
    from echo_personal_tool.infrastructure.dicom_session import DicomSession

    mixed_dir = tmp_path / "Echo_Диагностика" / "Patient_ID-42"
    mixed_dir.mkdir(parents=True)
    dcm = write_synthetic_multiframe_dicom(
        mixed_dir / " study_  001.dcm",
        frame_count=3,
        rows=32,
        cols=32,
    )
    session = DicomSession()
    session.open(dcm)
    assert session.frame_count == 3


# ── Spaces in paths ─────────────────────────────────────────────────


@_compat
@pytest.mark.xfail(sys.platform != "win32", reason="Spaces in paths on Windows", strict=False)
def test_spaces_in_directory(tmp_path: Path) -> None:
    """Directory with spaces in name."""
    from echo_personal_tool.infrastructure.dicom_session import DicomSession

    spaced_dir = tmp_path / "My Documents" / "DICOM Studies" / "2024-06-01"
    spaced_dir.mkdir(parents=True)
    dcm = write_synthetic_multiframe_dicom(
        spaced_dir / "cardiac cine.dcm",
        frame_count=5,
        rows=32,
        cols=32,
    )
    session = DicomSession()
    session.open(dcm)
    assert session.frame_count == 5


@_compat
@pytest.mark.xfail(sys.platform != "win32", reason="Spaces in paths on Windows", strict=False)
def test_trailing_spaces_in_filename(tmp_path: Path) -> None:
    """Filename with trailing spaces (Windows strips them)."""
    from echo_personal_tool.infrastructure.dicom_session import DicomSession

    dcm = write_synthetic_multiframe_dicom(
        tmp_path / "trailing_spaces.dcm",
        frame_count=3,
        rows=32,
        cols=32,
    )
    session = DicomSession()
    session.open(dcm)
    assert session.frame_count == 3


@_compat
@pytest.mark.xfail(sys.platform != "win32", reason="Spaces in paths on Windows", strict=False)
def test_path_with_leading_trailing_spaces(tmp_path: Path) -> None:
    """Directory with leading/trailing spaces."""
    from echo_personal_tool.infrastructure.dicom_session import DicomSession

    spaced_dir = tmp_path / "  padded  " / " dir "
    spaced_dir.mkdir(parents=True)
    dcm = write_synthetic_multiframe_dicom(
        spaced_dir / "img.dcm",
        frame_count=3,
        rows=32,
        cols=32,
    )
    session = DicomSession()
    session.open(dcm)
    assert session.frame_count == 3


# ── Gold store with Windows paths ───────────────────────────────────


@_compat
@pytest.mark.xfail(sys.platform != "win32", reason="Gold store with Windows paths", strict=False)
def test_gold_store_backslash_instance_path(tmp_path: Path) -> None:
    """Gold frame with Windows-style instance_path."""
    from echo_personal_tool.domain.services.gold_store import (
        make_gold_frame,
        merge_frame_into_gold,
        make_gold_study,
    )

    study = make_gold_study(
        study_id="win-test-1",
        instance_path="D:\\DICOM\\study\\img.dcm",
        pixel_spacing_mm=[0.3, 0.3],
    )
    frame = make_gold_frame(
        frame_index=10,
        phase="ED",
        points=[[10.0, 20.0], [30.0, 40.0], [50.0, 60.0]],
        mitral_annulus=[[15.0, 25.0], [35.0, 45.0]],
        instance_path="D:\\DICOM\\study\\img.dcm",
    )
    merged = merge_frame_into_gold(study, frame)
    assert len(merged["frames"]) == 1
    assert merged["instance_path"] == "D:\\DICOM\\study\\img.dcm"
