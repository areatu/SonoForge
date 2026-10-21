"""QH-4a register evidence: known structured secrets must not leave support ZIPs.

This is not a claim that regex can anonymise arbitrary free-form clinical text.
Raw logs/crash dumps remain sensitive; see the audit register's OPEN rows.
"""

from __future__ import annotations

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
    for path in src.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name not in {"log_boundary_failure", "log_boundary_event"} or len(node.args) < 2:
                continue
            operation = node.args[1]
            if isinstance(operation, ast.Constant) and isinstance(operation.value, str):
                if operation.value not in _OPERATIONS:
                    unknown.append(f"{path.relative_to(src.parent)}:{node.lineno} -> {operation.value}")
    assert unknown == [], "boundary operations missing from the allowlist:\n" + "\n".join(unknown)
