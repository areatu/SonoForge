"""Tests for Orthanc DICOMweb with real JSON fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from echo_personal_tool.infrastructure.orthanc_dicom_json import (
    parse_instances,
    parse_series,
    parse_studies,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "orthanc"


@pytest.fixture()
def qido_single():
    with open(FIXTURES / "qido" / "studies_single.json") as f:
        return json.load(f)


@pytest.fixture()
def qido_multi():
    with open(FIXTURES / "qido" / "studies_multi.json") as f:
        return json.load(f)


@pytest.fixture()
def qido_empty():
    with open(FIXTURES / "qido" / "studies_empty.json") as f:
        return json.load(f)


@pytest.fixture()
def qido_series_echo():
    with open(FIXTURES / "qido" / "series_echo.json") as f:
        return json.load(f)


@pytest.fixture()
def qido_series_ct():
    with open(FIXTURES / "qido" / "series_ct.json") as f:
        return json.load(f)


@pytest.fixture()
def wado_instance_metadata():
    with open(FIXTURES / "wado" / "instance_metadata.json") as f:
        return json.load(f)


@pytest.fixture()
def wado_instances_echo():
    with open(FIXTURES / "wado" / "instances_echo.json") as f:
        return json.load(f)


@pytest.fixture()
def stow_success():
    with open(FIXTURES / "stow" / "success.json") as f:
        return json.load(f)


@pytest.fixture()
def stow_partial_failure():
    with open(FIXTURES / "stow" / "partial_failure.json") as f:
        return json.load(f)


@pytest.fixture()
def stow_all_failed():
    with open(FIXTURES / "stow" / "all_failed.json") as f:
        return json.load(f)


@pytest.fixture()
def error_500():
    with open(FIXTURES / "errors" / "500_internal.json") as f:
        return json.load(f)


@pytest.fixture()
def error_401():
    with open(FIXTURES / "errors" / "401_unauthorized.json") as f:
        return json.load(f)


# ── QIDO-RS Studies ────────────────────────────────────────────────


class TestQidoStudiesSingle:
    def test_parse_single_study(self, qido_single) -> None:
        studies = parse_studies(qido_single)
        assert len(studies) == 1

    def test_study_uid(self, qido_single) -> None:
        studies = parse_studies(qido_single)
        assert studies[0].study_uid == "1.2.840.113619.2.55.3.604688119.330.1426555527.469"

    def test_patient_name(self, qido_single) -> None:
        studies = parse_studies(qido_single)
        assert studies[0].patient_name == "Doe^John"

    def test_patient_id(self, qido_single) -> None:
        studies = parse_studies(qido_single)
        assert studies[0].patient_id == "P001"

    def test_study_date(self, qido_single) -> None:
        studies = parse_studies(qido_single)
        assert studies[0].study_date == "20250115"

    def test_study_description(self, qido_single) -> None:
        studies = parse_studies(qido_single)
        assert studies[0].study_description == "Transthoracic Echocardiogram"


class TestQidoStudiesMulti:
    def test_parse_multiple_studies(self, qido_multi) -> None:
        studies = parse_studies(qido_multi)
        assert len(studies) == 2

    def test_first_study(self, qido_multi) -> None:
        studies = parse_studies(qido_multi)
        assert studies[0].patient_name == "Doe^John"
        assert studies[0].patient_id == "P001"

    def test_second_study(self, qido_multi) -> None:
        studies = parse_studies(qido_multi)
        assert studies[1].patient_name == "Smith^Jane"
        assert studies[1].patient_id == "P002"


class TestQidoStudiesEmpty:
    def test_parse_empty(self, qido_empty) -> None:
        studies = parse_studies(qido_empty)
        assert len(studies) == 0


# ── QIDO-RS Series ────────────────────────────────────────────────


class TestQidoSeriesEcho:
    def test_parse_series(self, qido_series_echo) -> None:
        series = parse_series(qido_series_echo, "1.2.3")
        assert len(series) == 3

    def test_series_uids(self, qido_series_echo) -> None:
        series = parse_series(qido_series_echo, "1.2.3")
        uids = [s.series_uid for s in series]
        assert len(set(uids)) == 3  # all unique

    def test_modalities(self, qido_series_echo) -> None:
        series = parse_series(qido_series_echo, "1.2.3")
        modalities = [s.modality for s in series]
        assert all(m == "US" for m in modalities)

    def test_descriptions(self, qido_series_echo) -> None:
        series = parse_series(qido_series_echo, "1.2.3")
        descriptions = [s.description for s in series]
        assert "A4C Cine" in descriptions
        assert "A2C Cine" in descriptions
        assert "LVOT Doppler" in descriptions

    def test_instance_counts(self, qido_series_echo) -> None:
        series = parse_series(qido_series_echo, "1.2.3")
        counts = [s.instance_count for s in series]
        assert 30 in counts
        assert 25 in counts
        assert 1 in counts


class TestQidoSeriesCt:
    def test_parse_ct_series(self, qido_series_ct) -> None:
        series = parse_series(qido_series_ct, "1.2.3")
        assert len(series) == 1
        assert series[0].modality == "CT"
        assert series[0].instance_count == 250


# ── WADO-RS ────────────────────────────────────────────────────────


class TestWadoInstanceMetadata:
    def test_parse_metadata(self, wado_instance_metadata) -> None:
        instances = parse_instances(
            [{"00080018": {"vr": "UI", "Value": ["1.2.3"]}}],
            "1.2.3", "1.2.4"
        )
        assert len(instances) == 1

    def test_metadata_has_required_fields(self, wado_instance_metadata) -> None:
        assert "00080018" in wado_instance_metadata  # SOPInstanceUID
        assert "00080060" in wado_instance_metadata  # Modality
        assert "00100010" in wado_instance_metadata  # PatientName
        assert "00280010" in wado_instance_metadata  # Rows
        assert "00280011" in wado_instance_metadata  # Columns

    def test_pixel_spacing(self, wado_instance_metadata) -> None:
        ps = wado_instance_metadata.get("00280030", {})
        values = ps.get("Value", [])
        assert len(values) == 2
        assert values[0] == "0.5"
        assert values[1] == "0.5"


class TestWadoInstancesEcho:
    def test_parse_instances(self, wado_instances_echo) -> None:
        instances = parse_instances(wado_instances_echo, "1.2.3", "1.2.4")
        assert len(instances) == 3

    def test_instance_uids(self, wado_instances_echo) -> None:
        instances = parse_instances(wado_instances_echo, "1.2.3", "1.2.4")
        uids = [i.sop_instance_uid for i in instances]
        assert len(set(uids)) == 3


# ── STOW-RS ────────────────────────────────────────────────────────


class TestStowSuccess:
    def test_has_location(self, stow_success) -> None:
        assert "00081190" in stow_success
        location = stow_success["00081190"].get("Value", "")
        assert "studies" in location


class TestStowPartialFailure:
    def test_has_failed_sequence(self, stow_partial_failure) -> None:
        assert "00081199" in stow_partial_failure
        failed_seq = stow_partial_failure["00081199"].get("Value", [])
        assert len(failed_seq) == 1

    def test_failed_has_reason(self, stow_partial_failure) -> None:
        failed_seq = stow_partial_failure["00081199"]["Value"]
        assert "00081197" in failed_seq[0]  # Failed SOP Sequence


class TestStowAllFailed:
    def test_all_failed(self, stow_all_failed) -> None:
        failed_seq = stow_all_failed["00081199"].get("Value", [])
        assert len(failed_seq) == 2
        assert "00081190" not in stow_all_failed  # no success location


# ── Errors ─────────────────────────────────────────────────────────


class TestErrors:
    def test_500(self, error_500) -> None:
        assert error_500.get("httpStatus") == 500

    def test_401(self, error_401) -> None:
        assert error_401.get("httpStatus") == 401
