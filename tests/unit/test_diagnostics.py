"""Tests for session logging, privacy-filtered support bundles, and scan-log migration."""

from __future__ import annotations

import faulthandler
import logging
import sys
import zipfile
from pathlib import Path

from echo_personal_tool.infrastructure.diagnostics import create_diagnostic_bundle, migrate_legacy_scan_errors
from echo_personal_tool.infrastructure.logging_setup import configure_logging, shutdown_logging


def test_configure_logging_creates_unique_rotating_session_file(tmp_path: Path) -> None:
    root = logging.getLogger()
    old_handlers = list(root.handlers)
    dicom_logger = logging.getLogger("echo_personal_tool.infrastructure.dicom_session")
    old_dicom_level = dicom_logger.level
    faulthandler_was_enabled = faulthandler.is_enabled()
    try:
        session = configure_logging(directory=tmp_path, max_bytes=250, backup_count=2)
        assert session.log_path is not None
        assert (session.crash_path is not None) is (not faulthandler_was_enabled)
        assert dicom_logger.level == logging.DEBUG
        assert session.log_path.name.startswith("session-")
        assert session.log_path.parent == tmp_path
        assert sys.excepthook is not session._previous_sys_hook

        test_logger = logging.getLogger("echo_personal_tool.logging_test")
        for index in range(12):
            test_logger.warning("diagnostic event %d %s", index, "x" * 80)
        session._handler.flush()
        assert list(tmp_path.glob(f"{session.log_path.name}.*"))
    finally:
        shutdown_logging()
    assert sys.excepthook is session._previous_sys_hook
    assert dicom_logger.level == old_dicom_level
    assert set(root.handlers) == set(old_handlers)


def test_diagnostic_bundle_filters_logs_and_excludes_non_log_files(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "session-Alice.log").write_text(
        "2026-10-05 10:00:00 [ERROR] test: PatientName=Alice Smith, PatientID=MRN-123\n"
        'patient_name="Alice Smith" PatientBirthDate=19800101 study_uid=1.2.3.4\n'
        "(0010,0010)=Jones^Jane (0010,0020)=MRN-456\n"
        "read C:\\Users\\Alice\\Patient Files\\JONES_20261005.dcm uid=1.2.840.113619.55\n"
        "read /home/alice smith/Patient Folder/series.dcm\n",
        encoding="utf-8",
    )
    (log_dir / "preferences.json").write_text('{"PatientName":"Alice Smith"}', encoding="utf-8")
    archive_path = tmp_path / "support.zip"

    result = create_diagnostic_bundle(archive_path, log_directory=log_dir)

    assert result == archive_path
    with zipfile.ZipFile(result) as archive:
        names = set(archive.namelist())
        assert "system-info.txt" in names
        assert "manifest.json" in names
        assert "logs/log-001.log" in names
        assert not any("Alice" in name for name in names)
        assert "preferences.json" not in names
        payload = "\n".join(archive.read(name).decode("utf-8") for name in names)
    for private_value in (
        "Alice",
        "JONES",
        "MRN-123",
        "MRN-456",
        "Jones^Jane",
        "19800101",
        "1.2.840.113619.55",
        "Patient Files",
        "Patient Folder",
    ):
        assert private_value not in payload
    assert "PatientName=<redacted>" in payload


def test_legacy_scan_error_log_is_filtered_then_removed(tmp_path: Path) -> None:
    patient_folder = tmp_path / "patient-study"
    patient_folder.mkdir()
    legacy = patient_folder / "scan_errors.log"
    legacy.write_text(
        "C:\\Patients\\Alice\\JONES_20261005.dcm invalid PatientID=MRN-123\n",
        encoding="utf-8",
    )
    log_dir = tmp_path / "app-logs"

    assert migrate_legacy_scan_errors(patient_folder, log_directory=log_dir) is True
    assert not legacy.exists()
    migrated = (log_dir / "scan_errors.log").read_text(encoding="utf-8")
    assert "Alice" not in migrated
    assert "JONES" not in migrated
    assert "MRN-123" not in migrated
    assert "<redacted>" in migrated
