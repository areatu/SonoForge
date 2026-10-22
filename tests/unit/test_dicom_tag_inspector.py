"""Tests for DICOM tag inspector service."""

from __future__ import annotations

from echo_personal_tool.domain.services.dicom_tag_dictionary import PATIENT_NAME
from echo_personal_tool.infrastructure.dicom_tag_inspector import _resolve_tag_int


def test_resolve_tag_int_by_keyword() -> None:
    assert _resolve_tag_int("PatientName") == PATIENT_NAME


def test_resolve_tag_int_by_hex() -> None:
    assert _resolve_tag_int("(0010,0010)") == PATIENT_NAME
