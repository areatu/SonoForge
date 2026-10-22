"""Tests for StowResult model and STOW-RS multipart body builder."""

from __future__ import annotations

from echo_personal_tool.domain.models.orthanc import StowResult
from echo_personal_tool.infrastructure.orthanc_client import (
    _build_stow_multipart_body,
    _parse_stow_response,
)


def test_stow_result_defaults() -> None:
    r = StowResult(success_count=5)
    assert r.success_count == 5
    assert r.failed_uids == []
    assert r.error_message == ""


def test_stow_result_with_failures() -> None:
    r = StowResult(success_count=3, failed_uids=["uid1", "uid2"], error_message="partial")
    assert r.success_count == 3
    assert len(r.failed_uids) == 2


def test_build_stow_multipart_body_single() -> None:
    body = _build_stow_multipart_body("test-boundary", [b"\x00dicom-data"])
    assert b"test-boundary" in body
    assert b"application/dicom" in body
    assert b"\x00dicom-data" in body
    assert body.endswith(b"--test-boundary--\r\n")


def test_build_stow_multipart_body_multiple() -> None:
    body = _build_stow_multipart_body("b", [b"file1", b"file2", b"file3"])
    assert body.count(b"file1") == 1
    assert body.count(b"file2") == 1
    assert body.count(b"file3") == 1


def test_parse_stow_response_all_success() -> None:
    data = [{"00081120": {"Value": []}}] * 3
    result = _parse_stow_response(data, 3)
    assert result.success_count == 3
    assert result.failed_uids == []


def test_parse_stow_response_partial_failure() -> None:
    data = [
        {"00081120": {"Value": []}},
        {"00081199": [{"00081150": {}, "00081155": {"Value": ["bad-uid-1"]}}]},
    ]
    result = _parse_stow_response(data, 2)
    assert result.success_count == 1
    assert result.failed_uids == ["bad-uid-1"]


def test_parse_stow_response_empty_list() -> None:
    result = _parse_stow_response([], 0)
    assert result.success_count == 0


def test_parse_stow_response_non_list() -> None:
    result = _parse_stow_response("error", 5)
    assert result.success_count == 5
