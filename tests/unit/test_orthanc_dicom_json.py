"""Unit tests for Orthanc DICOMweb JSON parser."""

from __future__ import annotations

import json
from pathlib import Path

from echo_personal_tool.infrastructure.orthanc_dicom_json import (
    parse_instances,
    parse_series,
    parse_studies,
    tag_value,
)

# ── Existing tests ─────────────────────────────────────────────────


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


def test_tag_value_reads_ui_study_instance_uid() -> None:
    item = {
        "0020000D": {
            "vr": "UI",
            "Value": ["1.2.410.200001.1.1185.2062614048.1.20240404.1120546412.448.1"],
        }
    }
    assert tag_value(item, "0020000D") == ("1.2.410.200001.1.1185.2062614048.1.20240404.1120546412.448.1")


def test_parse_studies_from_fixture() -> None:
    raw = Path("tests/fixtures/orthanc/studies.json").read_text(encoding="utf-8")
    studies = parse_studies(json.loads(raw))
    assert len(studies) >= 1
    assert studies[0].study_uid.startswith("1.2.")
    assert studies[0].study_uid == ("1.2.410.200001.1.1185.2062614048.1.20240404.1120546412.448.1")
    assert studies[0].patient_name == "TEST^PATIENT"
    assert studies[0].patient_id == "TEST123"
    assert studies[0].study_date == "20240404"
    assert studies[0].study_description == "Echo study"


def test_parse_series_injects_study_uid() -> None:
    study_uid = "1.2.410.200001.1.1185.2062614048.1.20240404.1120546412.448.1"
    payload = [
        {
            "0020000E": {"vr": "UI", "Value": ["1.2.410.200001.1.1185.2062614048.1.20240404.1120546412.448.2"]},
            "00080060": {"vr": "CS", "Value": ["US"]},
            "0008103E": {"vr": "LO", "Value": ["Echo series"]},
            "00201209": {"vr": "IS", "Value": ["10"]},
        }
    ]
    series_list = parse_series(payload, study_uid)
    assert len(series_list) == 1
    assert series_list[0].series_uid == ("1.2.410.200001.1.1185.2062614048.1.20240404.1120546412.448.2")
    assert series_list[0].study_uid == study_uid
    assert series_list[0].modality == "US"
    assert series_list[0].description == "Echo series"
    assert series_list[0].instance_count == 10


def test_parse_instances_injects_study_and_series_uid() -> None:
    study_uid = "1.2.410.200001.1.1185.2062614048.1.20240404.1120546412.448.1"
    series_uid = "1.2.410.200001.1.1185.2062614048.1.20240404.1120546412.448.2"
    payload = [
        {
            "00080018": {
                "vr": "UI",
                "Value": ["1.2.410.200001.1.1185.2062614048.1.20240404.1120546412.448.3"],
            }
        }
    ]
    instances = parse_instances(payload, study_uid, series_uid)
    assert len(instances) == 1
    assert instances[0].sop_instance_uid == ("1.2.410.200001.1.1185.2062614048.1.20240404.1120546412.448.3")
    assert instances[0].study_uid == study_uid
    assert instances[0].series_uid == series_uid


# ── New tests using real-world fixtures ─────────────────────────────


class TestParseStudiesRealFixtures:
    def test_single_study(self, qido_studies_single) -> None:
        studies = parse_studies(qido_studies_single)
        assert len(studies) == 1
        assert studies[0].patient_name == "Doe^John"
        assert studies[0].patient_id == "P001"
        assert studies[0].study_date == "20250115"
        assert studies[0].study_description == "Transthoracic Echocardiogram"

    def test_multi_studies(self, qido_studies_multi) -> None:
        studies = parse_studies(qido_studies_multi)
        assert len(studies) == 2
        assert studies[0].patient_name == "Doe^John"
        assert studies[1].patient_name == "Smith^Jane"

    def test_empty_studies(self, qido_studies_empty) -> None:
        studies = parse_studies(qido_studies_empty)
        assert len(studies) == 0


class TestParseSeriesRealFixtures:
    def test_echo_series(self, qido_series_echo) -> None:
        series = parse_series(qido_series_echo, "1.2.3")
        assert len(series) == 3
        descriptions = [s.description for s in series]
        assert "A4C Cine" in descriptions
        assert "A2C Cine" in descriptions

    def test_instance_counts(self, qido_series_echo) -> None:
        series = parse_series(qido_series_echo, "1.2.3")
        counts = [s.instance_count for s in series]
        assert 30 in counts
        assert 25 in counts

    def test_ct_series(self, qido_series_ct) -> None:
        series = parse_series(qido_series_ct, "1.2.3")
        assert len(series) == 1
        assert series[0].modality == "CT"
        assert series[0].instance_count == 250


class TestParseInstancesRealFixtures:
    def test_echo_instances(self, wado_instances_echo) -> None:
        instances = parse_instances(wado_instances_echo, "1.2.3", "1.2.4")
        assert len(instances) == 3
        assert all(i.study_uid == "1.2.3" for i in instances)
        assert all(i.series_uid == "1.2.4" for i in instances)
