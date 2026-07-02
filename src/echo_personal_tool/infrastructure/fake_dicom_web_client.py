"""Fake DICOMweb client backed by JSON fixtures for offline dev."""

from __future__ import annotations

import json
from pathlib import Path

from echo_personal_tool.domain.models.orthanc import (
    InstanceInfo,
    SeriesInfo,
    StowResult,
    StudyInfo,
)
from echo_personal_tool.infrastructure.orthanc_dicom_json import (
    parse_instances,
    parse_series,
    parse_studies,
)


class FakeDicomWebClient:
    def __init__(self, fixtures_dir: Path | None = None) -> None:
        self._fixtures = fixtures_dir or Path(__file__).resolve().parents[3] / "tests/fixtures/orthanc"
        self._studies_payload: list[dict] | None = None
        self._series_payload: list[dict] | None = None
        self._instances_payload: list[dict] | None = None
        self._sample_dcm: bytes | None = None

    def _load_studies(self) -> list[dict]:
        if self._studies_payload is None:
            self._studies_payload = json.loads(
                (self._fixtures / "studies.json").read_text(encoding="utf-8")
            )
        return self._studies_payload

    def _load_series(self) -> list[dict]:
        if self._series_payload is None:
            self._series_payload = json.loads(
                (self._fixtures / "series.json").read_text(encoding="utf-8")
            )
        return self._series_payload

    def _load_instances(self) -> list[dict]:
        if self._instances_payload is None:
            self._instances_payload = json.loads(
                (self._fixtures / "instances.json").read_text(encoding="utf-8")
            )
        return self._instances_payload

    def _load_sample_dcm(self) -> bytes:
        if self._sample_dcm is None:
            self._sample_dcm = (self._fixtures / "sample.dcm").read_bytes()
        return self._sample_dcm

    def ping(self) -> bool:
        return True

    def query_studies(
        self,
        *,
        patient_name: str | None = None,
        patient_id: str | None = None,
        study_date: str | None = None,
    ) -> list[StudyInfo]:
        studies = parse_studies(self._load_studies())
        if patient_name is not None:
            needle = patient_name.casefold()
            studies = [s for s in studies if needle in s.patient_name.casefold()]
        if patient_id is not None:
            studies = [s for s in studies if patient_id in s.patient_id]
        if study_date is not None:
            studies = [s for s in studies if study_date in s.study_date]
        return studies

    def query_series(self, study_uid: str) -> list[SeriesInfo]:
        return parse_series(self._load_series(), study_uid)

    def query_instances(self, study_uid: str, series_uid: str) -> list[InstanceInfo]:
        return parse_instances(self._load_instances(), study_uid, series_uid)

    def download_instance(
        self, study_uid: str, series_uid: str, instance_uid: str
    ) -> bytes:
        return self._load_sample_dcm()

    def stow_instances(self, dicom_files: list[bytes]) -> StowResult:
        return StowResult(success_count=len(dicom_files))
