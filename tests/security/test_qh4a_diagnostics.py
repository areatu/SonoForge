"""QH-4a register evidence: known structured secrets must not leave support ZIPs.

This is not a claim that regex can anonymise arbitrary free-form clinical text.
Raw logs/crash dumps remain sensitive; see the audit register's OPEN rows.
"""

from __future__ import annotations

import logging
import zipfile

import pytest

from echo_personal_tool.infrastructure.diagnostics import create_diagnostic_bundle
from echo_personal_tool.infrastructure.log_sanitizer import sanitize_log_text
from echo_personal_tool.infrastructure.safe_diagnostics import (
    log_boundary_event,
    project_safe_diagnostic_lines,
)

pytestmark = pytest.mark.security

_SENTINELS = (
    "PHI_QH4A_PERSON",
    "PHI_QH4A_ID",
    "QH4A_PASSWORD",
    "QH4A_BEARER",
    "QH4A_BASIC",
    "QH4A_APIKEY",
    "QH4A_PAYLOAD",
    "QH4A_LABEL",
    "1.2.840.113619.999.777.666",
    "PHI_QH4A_PATH",
)

_CASES = (
    ('PatientName="PHI_QH4A_PERSON"', "PHI_QH4A_PERSON"),
    ('{"PatientID": "PHI_QH4A_ID"}', "PHI_QH4A_ID"),
    ("{'patient_name': 'PHI_QH4A_PERSON'}", "PHI_QH4A_PERSON"),
    ('password="QH4A_PASSWORD"', "QH4A_PASSWORD"),
    ("Authorization: Bearer QH4A_BEARER", "QH4A_BEARER"),
    ("{'Authorization': 'Basic QH4A_BASIC'}", "QH4A_BASIC"),
    ('{"api_key": "QH4A_APIKEY"}', "QH4A_APIKEY"),
    ('payload="QH4A_PAYLOAD"', "QH4A_PAYLOAD"),
    ("label='QH4A_LABEL'", "QH4A_LABEL"),
    ("sop_instance_uid=1.2.840.113619.999.777.666", "1.2.840.113619.999.777.666"),
    ("read /home/PHI_QH4A_PATH/source.dcm", "PHI_QH4A_PATH"),
)


@pytest.mark.parametrize("raw,sentinel", _CASES)
def test_structured_sentinel_redacted(raw, sentinel):
    filtered = sanitize_log_text("operation=save code=io " + raw)
    assert sentinel not in filtered
    assert "operation=save code=io" in filtered
    assert sanitize_log_text(filtered) == filtered


def test_support_zip_redacts_structured_fields_and_filenames(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    raw = (
        "2026-10-20 12:00:00,000 [WARNING] echo_personal_tool.test: "
        "operation=measurement.save code=io error_type=OSError\n"
        + "\n".join("operation=save code=io " + case[0] for case in _CASES)
    )
    (logs / "PHI_QH4A_PERSON.log").write_text(raw, encoding="utf-8")
    (logs / "crash-PHI_QH4A_PERSON.log").write_text(
        "Traceback (most recent call last): PHI_QH4A_PERSON /private/patient-study.dcm\n"
        "2026-10-20 12:00:00,000 [ERROR] echo_personal_tool.crash: "
        "operation=crash.main code=unexpected error_type=RuntimeError\n",
        encoding="utf-8",
    )
    (logs / "private.json").write_text(raw, encoding="utf-8")
    archive_path = create_diagnostic_bundle(tmp_path / "diagnostics.zip", log_directory=logs)
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        payload = "\n".join(archive.read(name).decode("utf-8") for name in names)
    for sentinel in _SENTINELS:
        assert sentinel not in payload
        assert all(sentinel not in name for name in names)
    assert "private.json" not in names
    assert "logs/log-001.log" in names
    assert "operation=measurement.save code=io error_type=OSError" in payload
    assert "Traceback" not in payload
    # Crash logs are projected line-by-line: the allowlisted boundary event
    # survives, every raw crash line around it does not.
    assert "operation=crash.main code=unexpected error_type=RuntimeError" in payload


def test_support_zip_does_not_follow_symlink_to_private_data(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    secret = tmp_path / "private.txt"
    secret.write_text("PHI_QH4A_PERSON", encoding="utf-8")
    link = logs / "session.log"
    try:
        link.symlink_to(secret)
    except OSError:
        # Windows CI without symlink privilege still tests the production
        # guard; only symlink creation is emulated, not the bundle writer.
        from unittest.mock import patch

        link.write_text("PHI_QH4A_PERSON", encoding="utf-8")
        with patch("pathlib.Path.is_symlink", autospec=True, side_effect=lambda path: path == link):
            archive_path = create_diagnostic_bundle(tmp_path / "diagnostics.zip", log_directory=logs)
    else:
        archive_path = create_diagnostic_bundle(tmp_path / "diagnostics.zip", log_directory=logs)
    with zipfile.ZipFile(archive_path) as archive:
        assert not any(name.startswith("logs/") for name in archive.namelist())


def test_boundary_projection_never_formats_untrusted_exception(caplog):
    import logging

    from echo_personal_tool.infrastructure.safe_diagnostics import log_boundary_failure

    class PHI_QH4A_PRIVATE(RuntimeError):
        def __str__(self):
            raise AssertionError("Exception messages must not be formatted")

    logger = logging.getLogger("qh4a.boundary")
    error = PHI_QH4A_PRIVATE("PHI_QH4A_PRIVATE /private/patient.dcm")
    log_boundary_failure(logger, "measurement.save", error, code="io")
    log_boundary_failure(logger, "PHI_QH4A_PRIVATE", error, code="PHI_QH4A_PRIVATE")
    assert "operation=measurement.save code=io error_type=RuntimeError" in caplog.text
    assert "operation=unknown code=unexpected error_type=RuntimeError" in caplog.text
    assert "PHI_QH4A_PRIVATE" not in caplog.text
    assert "/private/patient.dcm" not in caplog.text
    assert all(record.exc_info is None and record.stack_info is None for record in caplog.records)


def test_boundary_projection_preserves_timeout_and_storage_codes(caplog):
    import logging

    from echo_personal_tool.infrastructure.measurement_codec import MeasurementStorageError
    from echo_personal_tool.infrastructure.safe_diagnostics import log_boundary_failure, safe_failure_code

    logger = logging.getLogger("qh4a.boundary")
    assert safe_failure_code("conflict") == "conflict"
    assert safe_failure_code("PHI_QH4A_PRIVATE /private/patient.dcm") == "unexpected"
    log_boundary_failure(logger, "onnx.timeout", TimeoutError("PHI_QH4A_PRIVATE"), code="timeout")
    for code in (
        "identity",
        "invalid",
        "limit",
        "source",
        "unaccepted",
        "version",
        "busy",
        "conflict",
        "quota",
        "unsafe_path",
    ):
        log_boundary_failure(logger, "measurement.save", MeasurementStorageError(code), code=code)
        assert f"operation=measurement.save code={code} error_type=Exception" in caplog.text
    assert "operation=onnx.timeout code=timeout error_type=TimeoutError" in caplog.text
    assert "PHI_QH4A_PRIVATE" not in caplog.text


def test_mp4_and_orthanc_worker_diagnostics_are_allowlisted(caplog):
    import logging

    from echo_personal_tool.infrastructure.safe_diagnostics import log_boundary_failure

    logger = logging.getLogger("qh4a.worker-boundary")
    log_boundary_failure(logger, "mp4.export", RuntimeError("PHI_QH4A_PRIVATE"), code="unexpected")
    log_boundary_failure(logger, "orthanc.download", OSError("/private/patient.dcm"), code="io")

    assert "operation=mp4.export code=unexpected error_type=RuntimeError" in caplog.text
    assert "operation=orthanc.download code=io error_type=OSError" in caplog.text
    assert "PHI_QH4A_PRIVATE" not in caplog.text
    assert "/private/patient.dcm" not in caplog.text


def test_boundary_projection_covers_manual_calibration_rejection(caplog):
    """QH-4a ER-08: calibration.manual rejects with a stable code, no raw text."""
    import logging

    from echo_personal_tool.infrastructure.safe_diagnostics import log_boundary_failure

    logger = logging.getLogger("qh4a.boundary")
    log_boundary_failure(logger, "calibration.manual", ValueError("not-a-tuple"), code="invalid")
    assert "operation=calibration.manual code=invalid error_type=ValueError" in caplog.text
    assert "not-a-tuple" not in caplog.text


def test_support_projection_keeps_only_complete_allowlisted_boundary_events():
    from echo_personal_tool.infrastructure.safe_diagnostics import project_safe_diagnostic_lines

    accepted = (
        "2026-10-20 12:00:00,000 [WARNING] echo_personal_tool.test: "
        "operation=measurement.save code=io error_type=OSError"
    )
    accepted_mp4 = (
        "2026-10-20 12:00:00,000 [ERROR] echo_personal_tool.worker: "
        "operation=mp4.export code=unexpected error_type=RuntimeError"
    )
    accepted_orthanc = (
        "2026-10-20 12:00:00,000 [WARNING] echo_personal_tool.worker: "
        "operation=orthanc.download code=blocked error_type=RuntimeError"
    )
    source = "\n".join(
        (
            accepted,
            accepted_mp4,
            accepted_orthanc,
            accepted + " PHI_QH4A_PRIVATE /private/patient-study.dcm",
            "2026-10-20 12:00:00,000 [ERROR] logger: operation=other code=io error_type=OSError",
            "2026-10-20 12:00:00,000 [ERROR] logger: operation=measurement.save code=patient.dcm error_type=OSError",
            "Traceback (most recent call last): PHI_QH4A_PRIVATE",
        )
    )
    assert project_safe_diagnostic_lines(source) == "\n".join(
        (
            "operation=measurement.save code=io error_type=OSError",
            "operation=mp4.export code=unexpected error_type=RuntimeError",
            "operation=orthanc.download code=blocked error_type=RuntimeError",
        )
    )


_PREFIX = "2026-10-21 10:00:00,000 [WARNING] echo_personal_tool.test: "


def test_projection_keeps_only_complete_allowlisted_events():
    raw = "\n".join(
        (
            _PREFIX + "operation=measurement.save code=io error_type=OSError",
            _PREFIX + "operation=measurement.save code=io error_type=PHI_QH4A_PRIVATE",
            _PREFIX + "operation=PHI_QH4A_PRIVATE code=io error_type=OSError",
            _PREFIX + "operation=measurement.save code=PHI_QH4A_PRIVATE error_type=OSError",
            _PREFIX + "operation=calibration.auto code=blocked error_type=ValueError",
            _PREFIX + "operation=measurement.save code=io error_type=OSError extra=PHI_QH4A_PRIVATE",
            "Traceback (most recent call last): PHI_QH4A_PRIVATE",
        )
    )
    projected = project_safe_diagnostic_lines(raw)

    assert projected.splitlines() == [
        "operation=measurement.save code=io error_type=OSError",
        "operation=calibration.auto code=blocked error_type=ValueError",
    ]
    assert "PHI_QH4A_PRIVATE" not in projected


def test_boundary_event_rejects_untrusted_tokens(caplog):
    import logging

    logger = logging.getLogger("qh4a.boundary.event")
    log_boundary_event(logger, "PHI_QH4A_PRIVATE", "PHI_QH4A_PRIVATE", "PHI_QH4A_PRIVATE")
    log_boundary_event(logger, "calibration.grid", "blocked", "ValueError")

    assert "operation=unknown code=unexpected error_type=Exception" in caplog.text
    assert "operation=calibration.grid code=blocked error_type=ValueError" in caplog.text
    assert "PHI_QH4A_PRIVATE" not in caplog.text


def test_every_literal_boundary_operation_is_allowlisted():
    """Producer-side allowlist check (ER-10/11): no ad-hoc operation tokens.

    A new ``log_boundary_failure(logger, "some.operation", ...)`` must be added
    to ``safe_diagnostics._OPERATIONS`` in the same change, otherwise its
    records silently drop out of the support bundle during projection.
    """
    import ast
    from pathlib import Path

    from echo_personal_tool.infrastructure.safe_diagnostics import _OPERATIONS

    src = Path(__file__).parents[2] / "src" / "echo_personal_tool"
    unknown: list[str] = []
    missing_imports: list[str] = []
    helpers = {"log_boundary_failure", "log_boundary_event", "safe_error_category", "safe_failure_code"}
    for path in src.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported = {
            alias.asname or alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name) and func.id in helpers and path.name != "safe_diagnostics.py":
                if func.id not in imported:
                    missing_imports.append(f"{path.relative_to(src.parent)}:{node.lineno} -> {func.id}")
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name not in {"log_boundary_failure", "log_boundary_event"} or len(node.args) < 2:
                continue
            operation = node.args[1]
            if isinstance(operation, ast.Constant) and isinstance(operation.value, str):
                if operation.value not in _OPERATIONS:
                    unknown.append(f"{path.relative_to(src.parent)}:{node.lineno} -> {operation.value}")
    assert missing_imports == [], "missing safe_diagnostics imports:\n" + "\n".join(missing_imports)
    assert unknown == [], "boundary operations missing from the allowlist:\n" + "\n".join(unknown)


def test_zero_logger_exception_or_exc_info_in_codebase():
    """Producer-side ratchet (ER-08/ER-09/ER-10/ER-11): zero raw traceback logging.

    Every ``except`` block across ``src/echo_personal_tool`` must route through
    ``log_boundary_failure`` / ``log_boundary_event`` or category-only domain
    messages — never ``logger.exception(...)`` or ``exc_info=True``.
    (``PresenterDiagnostics.exception`` is sanitized at ``_write`` time.)
    """
    import ast
    from pathlib import Path

    src = Path(__file__).parents[2] / "src" / "echo_personal_tool"
    violations: list[str] = []
    for path in sorted(src.rglob("*.py")):
        rel = path.relative_to(src)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr == "exception":
                # Allow PresenterDiagnostics.exception (self._diag / diag in presenter_view.py)
                target = ast.unparse(node.func.value)
                if rel.as_posix() == "presentation/presenter_view.py" and target in {"self._diag", "diag"}:
                    continue
                violations.append(f"{rel}:{node.lineno} -> {ast.unparse(node)}")
            elif node.func.attr in {"debug", "info", "warning", "error", "critical", "log"}:
                for kw in node.keywords:
                    if kw.arg == "exc_info" and not (
                        isinstance(kw.value, ast.Constant) and kw.value.value in (None, False)
                    ):
                        violations.append(f"{rel}:{node.lineno} -> exc_info in {ast.unparse(node)}")
    assert violations == [], "raw traceback logging found:\n" + "\n".join(violations)


def test_zero_raw_exception_payload_in_logger_calls():
    """Producer-side ratchet (ER-08/ER-09): zero raw ``exc`` or ``str(exc)`` in logger calls."""
    import ast
    from pathlib import Path

    src = Path(__file__).parents[2] / "src" / "echo_personal_tool"
    violations: list[str] = []
    for path in sorted(src.rglob("*.py")):
        rel = path.relative_to(src)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler) or not node.name:
                continue
            exc_name = node.name
            for child in ast.walk(node):
                if not isinstance(child, ast.Call) or not isinstance(child.func, ast.Attribute):
                    continue
                if child.func.attr not in {"debug", "info", "warning", "error", "critical", "log"}:
                    continue
                for arg in child.args:
                    if isinstance(arg, ast.Name) and arg.id == exc_name:
                        violations.append(f"{rel}:{child.lineno} -> raw {exc_name} in {ast.unparse(child)}")
                    elif (
                        isinstance(arg, ast.Call)
                        and isinstance(arg.func, ast.Name)
                        and arg.func.id in {"str", "repr"}
                        and any(isinstance(a, ast.Name) and a.id == exc_name for a in arg.args)
                    ):
                        violations.append(f"{rel}:{child.lineno} -> {arg.func.id}({exc_name}) in {ast.unparse(child)}")
    assert violations == [], "raw exception payload logging found:\n" + "\n".join(violations)


def test_local_session_and_crash_logs_are_sanitized_at_write_time(tmp_path):
    """ER-10 / ER-11: local session-*.log and crash.log scrub PHI/paths/UIDs on write and startup."""
    import logging

    from echo_personal_tool.infrastructure.log_sanitizer import sanitize_local_log_files
    from echo_personal_tool.infrastructure.logging_setup import _SanitizingCrashStream, _SanitizingFileFormatter

    # 1. Pre-existing legacy log file is scrubbed in place
    legacy = tmp_path / "session-legacy.log"
    legacy.write_text(
        '2026-10-20 12:00:00 [ERROR] test: PatientName="PHI_QH4A_PERSON" '
        "sop_instance_uid=1.2.840.113619.999.777.666 /Users/PHI_QH4A_PATH/study.dcm\n"
        "ValueError: secret patient payload PHI_QH4A_ID\n",
        encoding="utf-8",
    )
    sanitize_local_log_files(tmp_path)
    scrubbed_legacy = legacy.read_text(encoding="utf-8")
    for sentinel in ("PHI_QH4A_PERSON", "1.2.840.113619.999.777.666", "PHI_QH4A_PATH", "PHI_QH4A_ID"):
        assert sentinel not in scrubbed_legacy

    # 2. _SanitizingFileFormatter scrubs formatted log records and drops exc_info/stack_info
    formatter = _SanitizingFileFormatter("%(levelname)s %(name)s: %(message)s")
    try:
        raise ValueError("PatientName='PHI_QH4A_PERSON' /Users/PHI_QH4A_PATH/study.dcm")
    except ValueError:
        import sys

        record = logging.LogRecord(
            name="echo_personal_tool.test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg='failed for PatientID="PHI_QH4A_ID" at /Users/PHI_QH4A_PATH/study.dcm',
            args=(),
            exc_info=sys.exc_info(),
        )
    formatted = formatter.format(record)
    assert "PHI_QH4A_PERSON" not in formatted
    assert "PHI_QH4A_ID" not in formatted
    assert "PHI_QH4A_PATH" not in formatted
    assert "Traceback" not in formatted

    # 3. _SanitizingCrashStream scrubs fault/crash lines before hitting disk
    crash_path = tmp_path / "crash.log"
    with crash_path.open("w", encoding="utf-8") as raw_crash:
        stream = _SanitizingCrashStream(raw_crash, crash_path)
        stream.write(
            'File "/Users/PHI_QH4A_PATH/study.dcm", line 42\n'
            'RuntimeError: PatientName="PHI_QH4A_PERSON" uid=1.2.840.113619.999.777.666\n'
        )
        stream.flush()
    crash_text = crash_path.read_text(encoding="utf-8")
    assert "PHI_QH4A_PATH" not in crash_text
    assert "PHI_QH4A_PERSON" not in crash_text
    assert "1.2.840.113619.999.777.666" not in crash_text
    assert "RuntimeError: <redacted>" in crash_text


def test_presenter_diagnostics_log_is_sanitized_at_write_time(tmp_path):
    """ER-10 / ER-11: presenter_diag.log scrubs paths, UIDs, and PHI tokens on write."""
    from echo_personal_tool.presentation.presenter_diagnostics import PresenterDiagnostics

    log_path = tmp_path / "presenter_diag.log"
    diag = PresenterDiagnostics(log_path, enabled=True)
    diag.event(
        "sync_test",
        path="/Users/PHI_QH4A_PATH/study.dcm",
        sop_instance_uid="1.2.840.113619.999.777.666",
    )
    diag.exception("forward_frame", RuntimeError('PatientName="PHI_QH4A_PERSON" /Users/PHI_QH4A_PATH/study.dcm'))
    content = log_path.read_text(encoding="utf-8")
    assert "PHI_QH4A_PATH" not in content
    assert "1.2.840.113619.999.777.666" not in content
    assert "PHI_QH4A_PERSON" not in content
    assert "sync_test" in content
    assert "forward_frame" in content


def test_saved_records_normalizes_unknown_storage_error_codes(tmp_path, monkeypatch):
    """ER-02 / ER-03: saved_records normalizes non-allowlisted codes and classifies schema_version=0 as corrupt."""
    import json

    from echo_personal_tool.application import saved_records
    from echo_personal_tool.application.measurement_persistence import MeasurementPersistence
    from echo_personal_tool.application.study_measurement_session import StudyMeasurementSessionStore
    from echo_personal_tool.infrastructure.measurement_codec import FORMAT, MeasurementStorageError

    def raise_untrusted(_payload):
        raise MeasurementStorageError("PHI_QH4A_PRIVATE:/Users/PHI_QH4A_PATH/study.dcm")

    monkeypatch.setattr(saved_records, "loads", raise_untrusted)
    summary = saved_records.summarize_record("a" * 64, b"{}")
    assert summary.status == saved_records.STATUS_CORRUPT
    assert summary.error == "io"
    assert "PHI_QH4A_PRIVATE" not in summary.error
    assert "PHI_QH4A_PATH" not in summary.error

    class _BadRepo:
        def entries(self):
            raise MeasurementStorageError("PHI_QH4A_PRIVATE:/Users/PHI_QH4A_PATH/study.dcm")

    listing = saved_records.read_saved_records(_BadRepo())
    assert listing.failed is True
    assert listing.error == "io"

    class _OsErrorRepo:
        def entries(self):
            raise OSError("/Users/PHI_QH4A_PATH/study.dcm permission denied")

    listing_os = saved_records.read_saved_records(_OsErrorRepo())
    assert listing_os.failed is True
    assert listing_os.error == "scan"

    monkeypatch.undo()
    # ER-03: schema_version=0 or non-int is corrupt, whereas future integer version is unsupported
    (tmp_path / ("0" * 64 + ".json")).write_bytes(json.dumps({"format": FORMAT, "schema_version": 0}).encode())
    (tmp_path / ("1" * 64 + ".json")).write_bytes(json.dumps({"format": FORMAT, "schema_version": "x"}).encode())
    (tmp_path / ("9" * 64 + ".json")).write_bytes(json.dumps({"format": FORMAT, "schema_version": 999}).encode())
    persistence = MeasurementPersistence(tmp_path, StudyMeasurementSessionStore(), enabled=True)
    try:
        by_key = {s.key: s.status for s in persistence.list_record_summaries().summaries}
        assert by_key["0" * 64] == "corrupt"
        assert by_key["1" * 64] == "corrupt"
        assert by_key["9" * 64] == "unsupported"
    finally:
        persistence.close()


def test_measurement_persistence_survives_deleted_qt_receiver_callback(caplog):
    """ER-04: deleted Qt receiver raising RuntimeError in callback does not escape."""
    from echo_personal_tool.application.measurement_persistence import MeasurementPersistence

    delivered: list[tuple[object, ...]] = []

    def dead_qt_slot(*args):
        delivered.append(args)
        raise RuntimeError("Internal C++ object (QWidget) already deleted.")

    with caplog.at_level(logging.DEBUG):
        # Must swallow RuntimeError and log boundary cleanup without raising
        MeasurementPersistence._deliver_callback(dead_qt_slot, "ok")

    assert delivered == [("ok",)]
    assert "operation=ui.cleanup code=cleanup error_type=RuntimeError" in caplog.text
    assert "already deleted" not in caplog.text, "the exception text must not reach the log"


def test_deliver_callback_swallows_only_the_dead_receiver_runtime_error():
    """ER-04: the boundary is narrow — any other failure of a live receiver still surfaces."""
    from echo_personal_tool.application.measurement_persistence import MeasurementPersistence

    def broken_slot(*_args):
        raise ValueError("a real bug in the slot")

    with pytest.raises(ValueError, match="a real bug"):
        MeasurementPersistence._deliver_callback(broken_slot, "ok")
    MeasurementPersistence._deliver_callback(None, "ok")  # no receiver at all is fine


def test_describe_study_maps_corrupt_dicom_and_eof_to_source_error(tmp_path, caplog):
    """ER-05: corrupt DICOM header / EOFError maps to MeasurementStorageError('source')."""
    from echo_personal_tool.domain.models.metadata import InstanceMetadata, SeriesMetadata, StudyMetadata
    from echo_personal_tool.infrastructure.measurement_codec import MeasurementStorageError
    from echo_personal_tool.infrastructure.measurement_sources import describe_study

    bad_dcm = tmp_path / "PHI_QH4A_PATH.dcm"
    bad_dcm.write_bytes(b"not a valid dicom header")
    inst = InstanceMetadata(
        sop_instance_uid="1.2.840.113619.2.1.1",
        series_uid="1.2.840.113619.2.1",
        modality="US",
        number_of_frames=1,
        pixel_spacing=(0.1, 0.1),
        frame_time_ms=33.0,
        series_description="test",
        path=bad_dcm,
        media_format="dicom",
    )
    from datetime import datetime

    study = StudyMetadata(
        study_uid="1.2.840.113619.2",
        study_datetime=datetime(2026, 10, 20),
        series=(
            SeriesMetadata(
                series_uid="1.2.840.113619.2.1",
                study_uid="1.2.840.113619.2",
                modality="US",
                description="s",
                instances=(inst,),
            ),
        ),
    )

    from unittest.mock import patch

    from pydicom.errors import InvalidDicomError

    with patch("pydicom.dcmread", side_effect=InvalidDicomError("corrupt header /Users/PHI_QH4A_PATH.dcm")):
        with pytest.raises(MeasurementStorageError) as exc_info:
            describe_study(study)
        assert exc_info.value.code == "source"

    with patch("pydicom.dcmread", side_effect=EOFError("truncated /Users/PHI_QH4A_PATH.dcm")):
        with pytest.raises(MeasurementStorageError) as exc_info_eof:
            describe_study(study)
        assert exc_info_eof.value.code == "source"

    assert "operation=persistence.source code=source" in caplog.text
    assert "PHI_QH4A_PATH" not in caplog.text


def test_measurement_persistence_close_respects_timeout_ms(tmp_path, monkeypatch, caplog):
    """ER-06: close(timeout_ms=...) passes the caller timeout to repository.close future."""
    import time

    from echo_personal_tool.application.measurement_persistence import MeasurementPersistence
    from echo_personal_tool.application.study_measurement_session import StudyMeasurementSessionStore

    persistence = MeasurementPersistence(tmp_path, StudyMeasurementSessionStore(), enabled=False)

    def slow_close():
        time.sleep(0.3)

    monkeypatch.setattr(persistence.repository, "close", slow_close)
    t0 = time.monotonic()
    result = persistence.close(timeout_ms=30)
    elapsed = time.monotonic() - t0
    assert result is False
    assert elapsed < 1.0
    assert "operation=measurement.close code=timeout error_type=TimeoutError" in caplog.text


def test_report_export_pdf_boundary_failure_does_not_leak_path(caplog):
    """ER-07: PDF export failure logs boundary code without leaking target path or message."""
    import logging

    from echo_personal_tool.infrastructure.measurement_report_pdf import PdfExportError
    from echo_personal_tool.infrastructure.safe_diagnostics import log_boundary_failure

    logger = logging.getLogger("echo_personal_tool.presentation.report_mode.export")
    exc = PdfExportError("pdf_export_failed: /Users/PHI_QH4A_PATH/secret_report.pdf")
    log_boundary_failure(logger, "report.export", exc, code="io")
    assert "operation=report.export code=io error_type=RuntimeError" in caplog.text
    assert "PHI_QH4A_PATH" not in caplog.text
    assert "secret_report.pdf" not in caplog.text
