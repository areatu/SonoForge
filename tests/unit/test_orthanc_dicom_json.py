"""Unit tests for Orthanc DICOMweb JSON parser."""

from __future__ import annotations

import json
from pathlib import Path

from echo_personal_tool.infrastructure.orthanc_dicom_json import (
    parse_studies,
    tag_value,
)


def test_tag_value_reads_pn_and_uid() -> None:
    item = {"00100010": {"vr": "PN", "Value": ["IVANOV^IVAN"]}}
    assert tag_value(item, "00100010") == "IVANOV^IVAN"


def test_tag_value_reads_pn_alphabetic_dict() -> None:
    item = {
        "00100010": {
            "vr": "PN",
            "Value": [{"Alphabetic": "IVANOV^IVAN", "Ideographic": ""}],
        }
    }
    assert tag_value(item, "00100010") == "IVANOV^IVAN"


def test_tag_value_returns_default_for_missing_tag() -> None:
    assert tag_value({}, "00100010") == ""
    assert tag_value({}, "00100010", default="N/A") == "N/A"


def test_parse_studies_from_fixture() -> None:
    raw = Path("tests/fixtures/orthanc/studies.json").read_text(encoding="utf-8")
    studies = parse_studies(json.loads(raw))
    assert len(studies) >= 1
    assert studies[0].study_uid.startswith("1.2.")
    assert studies[0].study_uid == (
        "1.2.410.200001.1.1185.2062614048.1.20240404.1120546412.448.1"
    )
    assert studies[0].patient_name == "TEST^PATIENT"
    assert studies[0].patient_id == "TEST123"
    assert studies[0].study_date == "20240404"
    assert studies[0].study_description == "Echo study"
