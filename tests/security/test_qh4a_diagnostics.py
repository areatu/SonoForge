"""QH-4a register evidence: known structured secrets must not leave support ZIPs.

This is not a claim that regex can anonymise arbitrary free-form clinical text.
Raw logs/crash dumps remain sensitive; see the audit register's OPEN rows.
"""

from __future__ import annotations

import zipfile

import pytest

from echo_personal_tool.infrastructure.diagnostics import create_diagnostic_bundle
from echo_personal_tool.infrastructure.log_sanitizer import sanitize_log_text

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
    raw = "\n".join("operation=save code=io " + case[0] for case in _CASES)
    (logs / "PHI_QH4A_PERSON.log").write_text(raw, encoding="utf-8")
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
    assert "operation=save code=io" in payload


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
    from echo_personal_tool.infrastructure.safe_diagnostics import log_boundary_failure

    logger = logging.getLogger("qh4a.boundary")
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
