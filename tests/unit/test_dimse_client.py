"""Tests for PynetdimseClient against an in-process pynetdicom SCP."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage
from pynetdicom import AE, evt
from pynetdicom.sop_class import (
    StudyRootQueryRetrieveInformationModelFind,
    Verification,
)

from echo_personal_tool.infrastructure.dimse_client import PynetdimseClient

_STUDY_UID = "1.2.840.113619.2.55.3.604688123.802.1760000000.1"
_SERIES_UID = "1.2.840.113619.2.55.3.604688123.802.1760000000.2"
_INSTANCE_UID = "1.2.840.113619.2.55.3.604688123.802.1760000000.3"


def _handle_find(event):  # noqa: ANN001
    ds = event.identifier
    level = ds.QueryRetrieveLevel
    if level == "STUDY":
        out = Dataset()
        out.QueryRetrieveLevel = "STUDY"
        out.StudyInstanceUID = _STUDY_UID
        out.PatientName = "Doe^John"
        out.PatientID = "P001"
        out.StudyDate = "20260101"
        out.StudyDescription = "Echo study"
        out.NumberOfStudyRelatedSeries = 1
        yield 0xFF00, out
    elif level == "SERIES":
        out = Dataset()
        out.QueryRetrieveLevel = "SERIES"
        out.StudyInstanceUID = _STUDY_UID
        out.SeriesInstanceUID = _SERIES_UID
        out.Modality = "US"
        out.SeriesDescription = "Parasternal"
        out.NumberOfSeriesRelatedInstances = 1
        yield 0xFF00, out
    elif level == "IMAGE":
        out = Dataset()
        out.QueryRetrieveLevel = "IMAGE"
        out.StudyInstanceUID = _STUDY_UID
        out.SeriesInstanceUID = _SERIES_UID
        out.SOPInstanceUID = _INSTANCE_UID
        yield 0xFF00, out
    yield 0x0000, None


def _handle_store(event):  # noqa: ANN001
    return 0x0000


@pytest.fixture
def dimse_scp() -> Iterator[tuple[int, str]]:
    ae = AE(ae_title=b"TESTSCP")
    ae.add_supported_context(Verification)
    ae.add_supported_context(StudyRootQueryRetrieveInformationModelFind)
    ae.add_supported_context(SecondaryCaptureImageStorage)
    handlers = [
        (evt.EVT_C_FIND, _handle_find),
        (evt.EVT_C_STORE, _handle_store),
    ]
    server = ae.start_server(("127.0.0.1", 0), block=False, evt_handlers=handlers)
    _host, port = server.server_address
    yield port, "TESTSCP"
    server.shutdown()


def _client(port: int, called_ae: str) -> PynetdimseClient:
    return PynetdimseClient(
        ae_title="TESTSCU",
        called_ae=called_ae,
        host="127.0.0.1",
        port=port,
        timeout_s=5.0,
    )


def test_c_echo_success(dimse_scp: tuple[int, str]) -> None:
    port, called_ae = dimse_scp
    assert _client(port, called_ae).c_echo() is True


def test_c_echo_fails_on_bad_port() -> None:
    client = PynetdimseClient(host="127.0.0.1", port=1, timeout_s=0.5)
    assert client.c_echo() is False


def test_c_find_studies(dimse_scp: tuple[int, str]) -> None:
    port, called_ae = dimse_scp
    studies = _client(port, called_ae).c_find_studies(patient_name="Doe")
    assert len(studies) == 1
    assert studies[0].study_uid == _STUDY_UID
    assert studies[0].patient_name == "Doe^John"


def test_c_find_series(dimse_scp: tuple[int, str]) -> None:
    port, called_ae = dimse_scp
    series = _client(port, called_ae).c_find_series(_STUDY_UID)
    assert len(series) == 1
    assert series[0].series_uid == _SERIES_UID
    assert series[0].modality == "US"


def test_c_find_instances(dimse_scp: tuple[int, str]) -> None:
    port, called_ae = dimse_scp
    instances = _client(port, called_ae).c_find_instances(_STUDY_UID, _SERIES_UID)
    assert len(instances) == 1
    assert instances[0].sop_instance_uid == _INSTANCE_UID


def test_c_store(dimse_scp: tuple[int, str]) -> None:
    port, called_ae = dimse_scp
    ds = Dataset()
    ds.SOPClassUID = SecondaryCaptureImageStorage
    ds.SOPInstanceUID = "1.2.3.4.5"
    ds.PatientName = "Test"
    file_meta = FileMetaDataset()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_meta.MediaStorageSOPClassUID = ds.SOPClassUID
    file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
    ds.file_meta = file_meta
    from io import BytesIO

    buf = BytesIO()
    ds.save_as(buf, enforce_file_format=True)
    assert _client(port, called_ae).c_store(buf.getvalue()) is True
