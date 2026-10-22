"""Unit tests for media format detection."""

from __future__ import annotations

from pathlib import Path

from echo_personal_tool.infrastructure.media_formats import (
    detect_media_format,
    is_ignored_scan_path,
    is_media_file,
)


def test_detect_media_format_by_extension(tmp_path: Path) -> None:
    assert detect_media_format(tmp_path / "a.dcm") == "dicom"
    assert detect_media_format(tmp_path / "b.mp4") == "mp4"
    assert detect_media_format(tmp_path / "c.jpg") == "jpeg"
    assert detect_media_format(tmp_path / "d.png") == "png"
    assert detect_media_format(tmp_path / "README") is None
    assert detect_media_format(tmp_path / "config") is None


def test_is_ignored_scan_path_skips_git_and_idea(tmp_path: Path) -> None:
    git_file = tmp_path / "project" / ".git" / "config"
    idea_file = tmp_path / "project" / ".idea" / "workspace.xml"
    assert is_ignored_scan_path(git_file)
    assert is_ignored_scan_path(idea_file)
    assert not is_ignored_scan_path(tmp_path / "study" / "clip.mp4")


def test_extensionless_dicom_only_when_dicom(tmp_path: Path) -> None:
    from tests.fixtures.generate_synthetic_dicom import write_synthetic_dicom

    path = tmp_path / "NOEXT"
    write_synthetic_dicom(path)
    assert is_media_file(path)

    plain = tmp_path / "plainfile"
    plain.write_text("not dicom")
    assert not is_media_file(plain)
