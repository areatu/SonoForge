"""Mock DIMSE client for offline development (same data as FakeDicomWebClient)."""

from __future__ import annotations

from echo_personal_tool.domain.models.orthanc import InstanceInfo, SeriesInfo, StudyInfo

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
