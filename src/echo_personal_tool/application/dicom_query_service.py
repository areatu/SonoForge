"""Unified query service: DICOMweb, DIMSE, or Auto fallback."""

from __future__ import annotations

import logging

from echo_personal_tool.domain.models.orthanc import InstanceInfo, SeriesInfo, StudyInfo
from echo_personal_tool.domain.ports import DimseClient, DicomWebClient, QuerySource

logger = logging.getLogger(__name__)


class DicomQueryService:
    """Single query entry point for orthanc_study_dialog."""

    def __init__(
        self,
        web: DicomWebClient | None,
        dimse: DimseClient | None,
        *,
        source: QuerySource = QuerySource.AUTO,
    ) -> None:
        self._web = web
        self._dimse = dimse
        self._source = source

    @property
    def source(self) -> QuerySource:
        return self._source

    @source.setter
    def source(self, value: QuerySource) -> None:
        self._source = value

    def query_studies(
        self,
        *,
        patient_name: str | None = None,
        patient_id: str | None = None,
        study_date: str | None = None,
    ) -> list[StudyInfo]:
        if self._source == QuerySource.DIMSE:
            return self._dimse_query_studies(
                patient_name=patient_name,
                patient_id=patient_id,
                study_date=study_date,
            )
        if self._source == QuerySource.DICOMWEB:
            return self._web_query_studies(
                patient_name=patient_name,
                patient_id=patient_id,
                study_date=study_date,
            )
        # AUTO: try web first, fallback to dimse
        return self._auto_query_studies(
            patient_name=patient_name,
            patient_id=patient_id,
            study_date=study_date,
        )

    def query_series(self, study_uid: str) -> list[SeriesInfo]:
        if self._source == QuerySource.DIMSE and self._dimse is not None:
            return self._dimse.c_find_series(study_uid)
        if self._web is not None:
            return self._web.query_series(study_uid)
        if self._dimse is not None:
            return self._dimse.c_find_series(study_uid)
        return []

    def query_instances(self, study_uid: str, series_uid: str) -> list[InstanceInfo]:
        if self._source == QuerySource.DIMSE and self._dimse is not None:
            return self._dimse.c_find_instances(study_uid, series_uid)
        if self._web is not None:
            return self._web.query_instances(study_uid, series_uid)
        if self._dimse is not None:
            return self._dimse.c_find_instances(study_uid, series_uid)
        return []

    def _web_query_studies(self, **kwargs) -> list[StudyInfo]:  # noqa: ANN003
        if self._web is None:
            return []
        try:
            return self._web.query_studies(**kwargs)
        except Exception:  # noqa: BLE001
            logger.debug("DICOMweb query_studies failed", exc_info=True)
            return []

    def _dimse_query_studies(self, **kwargs) -> list[StudyInfo]:  # noqa: ANN003
        if self._dimse is None:
            return []
        try:
            return self._dimse.c_find_studies(**kwargs)
        except Exception:  # noqa: BLE001
            logger.debug("DIMSE c_find_studies failed", exc_info=True)
            return []

    def _auto_query_studies(self, **kwargs) -> list[StudyInfo]:  # noqa: ANN003
        # Try DICOMweb first
        results = self._web_query_studies(**kwargs)
        if results:
            return results
        # Fallback to DIMSE if available
        if self._dimse is not None:
            logger.info("DICOMweb returned empty, falling back to DIMSE")
            return self._dimse_query_studies(**kwargs)
        return []
