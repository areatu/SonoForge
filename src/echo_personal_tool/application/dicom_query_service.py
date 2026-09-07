"""Unified query service: DICOMweb, DIMSE, or Auto fallback.

Error semantics (consistent across studies/series/instances):
- explicit source (DICOMWEB / DIMSE): a failed query raises — the caller
  (background dialog worker) surfaces the error to the UI instead of
  confusing "server down" with "no results";
- AUTO: the first working protocol wins; empty results from DICOMweb fall
  back to DIMSE; if every protocol raises, the last error propagates;
- a missing client is NOT an error: it yields an empty result.
"""

from __future__ import annotations

import logging

from echo_personal_tool.domain.models.orthanc import InstanceInfo, SeriesInfo, StudyInfo
from echo_personal_tool.domain.ports import DicomWebClient, DimseClient, QuerySource

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
        kwargs = {
            "patient_name": patient_name,
            "patient_id": patient_id,
            "study_date": study_date,
        }
        if self._source == QuerySource.DIMSE:
            return self._dimse_query_studies(**kwargs)
        if self._source == QuerySource.DICOMWEB:
            return self._web_query_studies(**kwargs)
        return self._auto_query_studies(**kwargs)

    def query_series(self, study_uid: str) -> list[SeriesInfo]:
        if self._source == QuerySource.DIMSE and self._dimse is not None:
            return self._dimse.c_find_series(study_uid)

        errors: list[Exception] = []

        if self._web is not None:
            try:
                return self._web.query_series(study_uid)
            except Exception as exc:  # noqa: BLE001
                logger.debug("DICOMweb query_series failed for %s", study_uid, exc_info=True)
                errors.append(exc)

        if self._dimse is not None:
            try:
                return self._dimse.c_find_series(study_uid)
            except Exception as exc:  # noqa: BLE001
                logger.debug("DIMSE c_find_series fallback failed for %s", study_uid, exc_info=True)
                errors.append(exc)

        if errors:
            raise errors[-1]
        return []

    def query_instances(self, study_uid: str, series_uid: str) -> list[InstanceInfo]:
        if self._source == QuerySource.DIMSE and self._dimse is not None:
            return self._dimse.c_find_instances(study_uid, series_uid)

        errors: list[Exception] = []

        if self._web is not None:
            try:
                return self._web.query_instances(study_uid, series_uid)
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "DICOMweb query_instances failed for %s/%s",
                    study_uid,
                    series_uid,
                    exc_info=True,
                )
                errors.append(exc)

        if self._dimse is not None:
            try:
                return self._dimse.c_find_instances(study_uid, series_uid)
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "DIMSE c_find_instances fallback failed for %s/%s",
                    study_uid,
                    series_uid,
                    exc_info=True,
                )
                errors.append(exc)

        if errors:
            raise errors[-1]
        return []

    def _web_query_studies(self, **kwargs) -> list[StudyInfo]:  # noqa: ANN003
        if self._web is None:
            return []
        return self._web.query_studies(**kwargs)

    def _dimse_query_studies(self, **kwargs) -> list[StudyInfo]:  # noqa: ANN003
        if self._dimse is None:
            return []
        return self._dimse.c_find_studies(**kwargs)

    def _auto_query_studies(self, **kwargs) -> list[StudyInfo]:  # noqa: ANN003
        # Try DICOMweb first; empty-but-successful results still fall back to
        # DIMSE when available. An authoritative answer (non-empty result, or
        # an empty answer from a protocol that actually responded) wins over a
        # failure of the *other* protocol; an error is raised only when every
        # attempted protocol failed.
        errors: list[Exception] = []
        web_answered_empty = False
        if self._web is not None:
            try:
                results = self._web.query_studies(**kwargs)
                if results:
                    return results
                web_answered_empty = True
            except Exception as exc:  # noqa: BLE001
                logger.debug("DICOMweb query_studies failed", exc_info=True)
                errors.append(exc)

        if self._dimse is not None:
            try:
                logger.info("DICOMweb returned no results, falling back to DIMSE")
                return self._dimse.c_find_studies(**kwargs)
            except Exception as exc:  # noqa: BLE001
                logger.debug("DIMSE c_find_studies fallback failed", exc_info=True)
                errors.append(exc)

        # The DIMSE fallback probe failed, but DICOMweb itself answered with
        # an empty result — trust that authoritative "no studies" answer.
        if errors and not web_answered_empty:
            raise errors[-1]
        return []
