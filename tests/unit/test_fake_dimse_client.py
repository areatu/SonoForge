"""Unit tests for infrastructure/fake_dimse_client.py."""

from __future__ import annotations

import pydicom

from echo_personal_tool.infrastructure.fake_dimse_client import FakeDimseClient


class TestFakeDimseClientEcho:
    def test_c_echo_always_true(self):
        client = FakeDimseClient()
        assert client.c_echo() is True


class TestFakeDimseClientFindStudies:
    def test_all_studies(self):
        client = FakeDimseClient()
        studies = client.c_find_studies()
        assert len(studies) == 2

    def test_filter_by_patient_name(self):
        client = FakeDimseClient()
        studies = client.c_find_studies(patient_name="DOE")
        assert len(studies) == 1
        assert studies[0].patient_name == "DOE^JOHN"

    def test_filter_by_patient_name_case_insensitive(self):
        client = FakeDimseClient()
        studies = client.c_find_studies(patient_name="doe")
        assert len(studies) == 1

    def test_filter_by_patient_id(self):
        client = FakeDimseClient()
        studies = client.c_find_studies(patient_id="MOCK001")
        assert len(studies) == 1
        assert studies[0].patient_id == "MOCK001"

    def test_filter_by_study_date(self):
        client = FakeDimseClient()
        studies = client.c_find_studies(study_date="20240115")
        assert len(studies) == 1
        assert studies[0].study_date == "20240115"

    def test_no_match(self):
        client = FakeDimseClient()
        studies = client.c_find_studies(patient_name="NONEXISTENT")
        assert len(studies) == 0

    def test_combined_filters(self):
        client = FakeDimseClient()
        studies = client.c_find_studies(patient_name="SMITH", patient_id="MOCK002")
        assert len(studies) == 1
        assert studies[0].patient_name == "SMITH^JANE"


class TestFakeDimseClientFindSeries:
    def test_known_study(self):
        client = FakeDimseClient()
        series = client.c_find_series("1.2.840.113619.2.55.3.12345")
        assert len(series) == 2
        assert series[0].modality == "US"

    def test_unknown_study(self):
        client = FakeDimseClient()
        series = client.c_find_series("1.2.3.4.5")
        assert len(series) == 0


class TestFakeDimseClientFindInstances:
    def test_known_series(self):
        client = FakeDimseClient()
        instances = client.c_find_instances(
            "1.2.840.113619.2.55.3.12345",
            "1.2.840.113619.2.55.3.12345.1",
        )
        assert len(instances) == 3

    def test_unknown_series(self):
        client = FakeDimseClient()
        instances = client.c_find_instances("1.2.3", "4.5.6")
        assert len(instances) == 0


class TestFakeDimseClientStore:
    def test_c_store_always_true(self):
        client = FakeDimseClient()
        assert client.c_store(b"\x00\x01") is True


class TestFakeDimseClientGetInstance:
    def test_returns_valid_dicom(self):
        client = FakeDimseClient()
        data = client.c_get_instance(
            "1.2.840.113619.2.55.3.12345",
            "1.2.840.113619.2.55.3.12345.1",
            "1.2.840.113619.2.55.3.12345.1.1",
        )
        assert isinstance(data, bytes)
        ds = pydicom.dcmread(__import__("io").BytesIO(data))
        assert str(ds.SOPInstanceUID) == "1.2.840.113619.2.55.3.12345.1.1"
        assert str(ds.PatientName) == "MOCK^PATIENT"

    def test_with_cancelled_flag(self):
        client = FakeDimseClient()
        data = client.c_get_instance(
            "1.2.840.113619.2.55.3.12345",
            "1.2.840.113619.2.55.3.12345.1",
            "1.2.840.113619.2.55.3.12345.1.1",
            is_cancelled=lambda: False,
        )
        assert len(data) > 0

    def test_with_tls_args(self):
        client = FakeDimseClient()
        data = client.c_get_instance(
            "1.2.840.113619.2.55.3.12345",
            "1.2.840.113619.2.55.3.12345.1",
            "1.2.840.113619.2.55.3.12345.1.1",
            tls_args=None,
        )
        assert len(data) > 0


class TestFakeDimseClientMoveInstances:
    def test_populates_received_dict(self):
        client = FakeDimseClient()
        received: dict[str, bytes] = {}
        result = client.c_move_instances(
            "1.2.840.113619.2.55.3.12345",
            "1.2.840.113619.2.55.3.12345.1",
            ["1.2.840.113619.2.55.3.12345.1.1", "1.2.840.113619.2.55.3.12345.1.2"],
            move_destination_ae="TEST",
            scp_host="127.0.0.1",
            scp_port=11112,
            received=received,
        )
        assert result.completed == 2
        assert result.failed == 0
        assert len(received) == 2

    def test_empty_uids(self):
        client = FakeDimseClient()
        received: dict[str, bytes] = {}
        result = client.c_move_instances(
            "1.2.3", "4.5.6", [],
            move_destination_ae="TEST",
            scp_host="127.0.0.1",
            scp_port=11112,
            received=received,
        )
        assert result.completed == 0
        assert len(received) == 0


class TestFakeDimseClientMoveSeries:
    def test_known_series(self):
        client = FakeDimseClient()
        received: dict[str, bytes] = {}
        result = client.c_move_series(
            "1.2.840.113619.2.55.3.12345",
            "1.2.840.113619.2.55.3.12345.1",
            move_destination_ae="TEST",
            scp_host="127.0.0.1",
            scp_port=11112,
            received=received,
        )
        assert result.completed == 3
        assert result.failed == 0
        assert len(received) == 3

    def test_unknown_series(self):
        client = FakeDimseClient()
        received: dict[str, bytes] = {}
        result = client.c_move_series(
            "1.2.3", "4.5.6",
            move_destination_ae="TEST",
            scp_host="127.0.0.1",
            scp_port=11112,
            received=received,
        )
        assert result.completed == 0
        assert len(received) == 0
