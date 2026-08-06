"""Tests for EmbeddedStorageSCP."""

from __future__ import annotations

import time
from collections.abc import Iterator

import pytest
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage
from pynetdicom import AE

from echo_personal_tool.infrastructure.embedded_storage_scp import EmbeddedStorageSCP

_SOP_UID = "1.2.3.4.5.6"
_STUDY_UID = "1.2.840.113619.2.55.3.604688123.802.1760000000.1"
_SERIES_UID = "1.2.840.113619.2.55.3.604688123.802.1760000000.2"
_INSTANCE_UID = "1.2.840.113619.2.55.3.604688123.802.1760000000.3"


def _make_dicom_bytes() -> bytes:
    """Create minimal DICOM bytes for testing."""
    ds = Dataset()
    ds.SOPClassUID = SecondaryCaptureImageStorage
    ds.SOPInstanceUID = _SOP_UID
    ds.PatientName = "Test"
    file_meta = FileMetaDataset()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_meta.MediaStorageSOPClassUID = ds.SOPClassUID
    file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
    ds.file_meta = file_meta
    from io import BytesIO

    buf = BytesIO()
    ds.save_as(buf, enforce_file_format=True)
    return buf.getvalue()


def _handle_c_move(event):  # noqa: ANN001
    """Mock C-MOVE handler that sends instance to the specified destination."""
    ds = event.identifier
    status = Dataset()
    status.Status = 0xFF00  # Pending
    status.NumberOfRemainingSuboperations = 0
    status.NumberOfCompletedSuboperations = 1
    status.NumberOfFailedSuboperations = 0
    status.NumberOfWarningSuboperations = 0

    # Simulate sending to the move destination
    ae = event.assoc.ae
    # In a real scenario, we'd connect to the move destination and send
    # For testing, we just yield the status
    yield status, None

    # Final success
    final = Dataset()
    final.Status = 0x0000
    final.NumberOfCompletedSuboperations = 1
    yield final, None


@pytest.fixture
def embedded_scp() -> Iterator[EmbeddedStorageSCP]:
    """Create and start an embedded SCP on a random port."""
    scp = EmbeddedStorageSCP(
        host="127.0.0.1",
        port=0,  # Let OS assign port
        ae_title="TESTSCP",
    )
    scp.start()
    # Wait for server to be ready
    time.sleep(0.1)
    yield scp
    scp.shutdown()


def test_embedded_scp_start_shutdown() -> None:
    """Test that SCP can be started and stopped."""
    scp = EmbeddedStorageSCP(
        host="127.0.0.1",
        port=0,
        ae_title="TESTSCP",
    )
    scp.start()
    assert scp._server is not None
    scp.shutdown()
    assert scp._server is None


def test_embedded_scp_context_manager() -> None:
    """Test context manager protocol."""
    with EmbeddedStorageSCP(
        host="127.0.0.1",
        port=0,
        ae_title="TESTSCP",
    ) as scp:
        assert scp._server is not None
    assert scp._server is None


def test_embedded_scp_receive_instance(embedded_scp: EmbeddedStorageSCP) -> None:
    """Test that SCP can receive a DICOM instance."""
    # Get the actual port the server is listening on
    port = embedded_scp._server.server_address[1]

    # Create an SCU that sends C-STORE
    ae = AE(ae_title="TESTSCU")
    ae.add_requested_context(SecondaryCaptureImageStorage)
    assoc = ae.associate("127.0.0.1", port, ae_title="TESTSCP")

    assert assoc.is_established

    # Send the instance
    ds = Dataset()
    ds.SOPClassUID = SecondaryCaptureImageStorage
    ds.SOPInstanceUID = _SOP_UID
    ds.PatientName = "Test"
    file_meta = FileMetaDataset()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_meta.MediaStorageSOPClassUID = ds.SOPClassUID
    file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
    ds.file_meta = file_meta

    status = assoc.send_c_store(ds)
    assoc.release()

    # Verify instance was received
    assert _SOP_UID in embedded_scp.instances
    assert len(embedded_scp.instances[_SOP_UID]) > 0


def test_embedded_scp_multiple_instances(embedded_scp: EmbeddedStorageSCP) -> None:
    """Test receiving multiple instances."""
    port = embedded_scp._server.server_address[1]

    ae = AE(ae_title="TESTSCU")
    ae.add_requested_context(SecondaryCaptureImageStorage)
    assoc = ae.associate("127.0.0.1", port, ae_title="TESTSCP")

    assert assoc.is_established

    # Send 3 instances
    for i in range(3):
        ds = Dataset()
        ds.SOPClassUID = SecondaryCaptureImageStorage
        ds.SOPInstanceUID = f"1.2.3.4.{i}"
        ds.PatientName = f"Patient{i}"
        file_meta = FileMetaDataset()
        file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        file_meta.MediaStorageSOPClassUID = ds.SOPClassUID
        file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
        ds.file_meta = file_meta
        assoc.send_c_store(ds)

    assoc.release()

    # Verify all instances received
    assert len(embedded_scp.instances) == 3
    for i in range(3):
        assert f"1.2.3.4.{i}" in embedded_scp.instances
