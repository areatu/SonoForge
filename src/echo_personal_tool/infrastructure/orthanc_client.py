"""Orthanc DICOMweb client (QIDO-RS + WADO-RS over httpx)."""

from __future__ import annotations

import httpx

from echo_personal_tool.domain.models.orthanc import InstanceInfo, SeriesInfo, StudyInfo
from echo_personal_tool.infrastructure.orthanc_dicom_json import (
    parse_instances,
    parse_series,
    parse_studies,
)


class OrthancDicomWebClient:
    def __init__(self, base_url: str, username: str, password: str, timeout: float = 30.0):
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            auth=(username, password),
            timeout=timeout,
        )

    def ping(self) -> bool:
        try:
            r = self._client.get("/system")
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    def query_studies(self, patient_name: str | None = None) -> list[StudyInfo]:
        params = {}
        if patient_name:
            params["PatientName"] = f"*{patient_name}*"
        r = self._client.get(
            "/dicom-web/studies",
            params=params,
            headers={"Accept": "application/dicom+json"},
        )
        r.raise_for_status()
        return parse_studies(r.json())

    def query_series(self, study_uid: str) -> list[SeriesInfo]:
        r = self._client.get(
            f"/dicom-web/studies/{study_uid}/series",
            headers={"Accept": "application/dicom+json"},
        )
        r.raise_for_status()
        return parse_series(r.json(), study_uid)

    def query_instances(self, study_uid: str, series_uid: str) -> list[InstanceInfo]:
        r = self._client.get(
            f"/dicom-web/studies/{study_uid}/series/{series_uid}/instances",
            headers={"Accept": "application/dicom+json"},
        )
        r.raise_for_status()
        return parse_instances(r.json(), study_uid, series_uid)

    def download_instance(self, study_uid: str, series_uid: str, instance_uid: str) -> bytes:
        r = self._client.get(
            f"/dicom-web/studies/{study_uid}/series/{series_uid}/instances/{instance_uid}",
            headers={"Accept": "application/dicom"},
        )
        r.raise_for_status()
        return r.content

    def close(self) -> None:
        self._client.close()
