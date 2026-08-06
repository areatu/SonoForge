"""Mock DIMSE client for offline development (same data as FakeDicomWebClient)."""

from __future__ import annotations

from collections.abc import Callable
from io import BytesIO

from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage

from echo_personal_tool.domain.models.orthanc import InstanceInfo, SeriesInfo, StudyInfo
from echo_personal_tool.domain.ports import CMoveResult

_MOCK_STUDIES = [
    StudyInfo(
        study_uid="1.2.840.113619.2.55.3.12345",
        patient_name="DOE^JOHN",
        patient_id="MOCK001",
        study_date="20240115",
        study_description="Echocardiography",
        series_count=2,
    ),
    StudyInfo(
        study_uid="1.2.840.113619.2.55.3.67890",
        patient_name="SMITH^JANE",
        patient_id="MOCK002",
        study_date="20240320",
        study_description="Cardiac MRI",
        series_count=3,
    ),
]

_MOCK_SERIES = {
    "1.2.840.113619.2.55.3.12345": [
        SeriesInfo(
            series_uid="1.2.840.113619.2.55.3.12345.1",
            study_uid="1.2.840.113619.2.55.3.12345",
            modality="US",
            description="A4C",
            instance_count=30,
        ),
        SeriesInfo(
            series_uid="1.2.840.113619.2.55.3.12345.2",
            study_uid="1.2.840.113619.2.55.3.12345",
            modality="US",
            description="A2C",
            instance_count=25,
        ),
    ],
    "1.2.840.113619.2.55.3.67890": [
        SeriesInfo(
            series_uid="1.2.840.113619.2.55.3.67890.1",
            study_uid="1.2.840.113619.2.55.3.67890",
            modality="MR",
            description="Cine SSFP",
            instance_count=20,
        ),
    ],
}

_MOCK_INSTANCES = {
    "1.2.840.113619.2.55.3.12345.1": [
        InstanceInfo(
            sop_instance_uid=f"1.2.840.113619.2.55.3.12345.1.{i}",
            series_uid="1.2.840.113619.2.55.3.12345.1",
            study_uid="1.2.840.113619.2.55.3.12345",
        )
        for i in range(1, 4)
    ],
}


class FakeDimseClient:
    """Mock DIMSE for offline development."""

    def c_echo(self) -> bool:
        return True

    def c_find_studies(
        self,
        *,
        patient_name: str | None = None,
        patient_id: str | None = None,
        study_date: str | None = None,
    ) -> list[StudyInfo]:
        results = list(_MOCK_STUDIES)
        if patient_name:
            name_upper = patient_name.upper()
            results = [s for s in results if name_upper in s.patient_name.upper()]
        if patient_id:
            results = [s for s in results if patient_id in s.patient_id]
        if study_date:
            results = [s for s in results if study_date in s.study_date]
        return results

    def c_find_series(self, study_uid: str) -> list[SeriesInfo]:
        return list(_MOCK_SERIES.get(study_uid, []))

    def c_find_instances(self, study_uid: str, series_uid: str) -> list[InstanceInfo]:
        return list(_MOCK_INSTANCES.get(series_uid, []))

    def c_store(self, dicom_bytes: bytes) -> bool:
        return True

    def c_get_instance(
        self,
        study_uid: str,
        series_uid: str,
        instance_uid: str,
        *,
        tls_args: tuple | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> bytes:
        """Return a mock DICOM instance."""
        ds = Dataset()
        ds.SOPClassUID = SecondaryCaptureImageStorage
        ds.SOPInstanceUID = instance_uid
        ds.StudyInstanceUID = study_uid
        ds.SeriesInstanceUID = series_uid
        ds.PatientName = "MOCK^PATIENT"
        ds.PatientID = "MOCK001"

        file_meta = FileMetaDataset()
        file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        file_meta.MediaStorageSOPClassUID = ds.SOPClassUID
        file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
        ds.file_meta = file_meta

        buf = BytesIO()
        ds.save_as(buf, enforce_file_format=True)
        return buf.getvalue()

    def c_move_instances(
        self,
        study_uid: str,
        series_uid: str,
        instance_uids: list[str],
        *,
        move_destination_ae: str,
        scp_host: str,
        scp_port: int,
        received: dict[str, bytes],
        tls_args: tuple | None = None,
    ) -> CMoveResult:
        """Mock C-MOVE: populate received dict with mock instances."""
        for uid in instance_uids:
            received[uid] = self.c_get_instance(study_uid, series_uid, uid)
        return CMoveResult(
            completed=len(instance_uids),
            failed=0,
            warning=0,
        )

    def c_move_series(
        self,
        study_uid: str,
        series_uid: str,
        *,
        move_destination_ae: str,
        scp_host: str,
        scp_port: int,
        received: dict[str, bytes],
        tls_args: tuple | None = None,
    ) -> CMoveResult:
        """Mock C-MOVE series: populate received dict with mock instances."""
        # Get mock instances for this series
        instances = self.c_find_instances(study_uid, series_uid)
        count = 0
        for inst in instances:
            received[inst.sop_instance_uid] = self.c_get_instance(study_uid, series_uid, inst.sop_instance_uid)
            count += 1
        return CMoveResult(completed=count, failed=0, warning=0)
