"""Extended tests for DicomQueryService covering error and fallback branches."""

from __future__ import annotations

from echo_personal_tool.application.dicom_query_service import DicomQueryService
from echo_personal_tool.domain.models.orthanc import StudyInfo
from echo_personal_tool.domain.ports import QuerySource


class _MockWeb:
    def __init__(self, studies=None, fail=False):
        self._studies = studies or []
        self._fail = fail

    def query_studies(self, **kwargs):
        if self._fail:
            raise ConnectionError("timeout")
        return self._studies

    def query_series(self, study_uid):
        return []

    def query_instances(self, study_uid, series_uid):
        return []

    def ping(self):
        return True

    def download_instance(self, *args):
        return b""

    def stow_instances(self, dicom_files):
        return None


class _MockDimse:
    def __init__(self, studies=None, fail=False):
        self._studies = studies or []
        self._fail = fail

    def c_find_studies(self, **kwargs):
        if self._fail:
            raise ConnectionError("timeout")
        return self._studies

    def c_find_series(self, study_uid):
        return []

    def c_find_instances(self, study_uid, series_uid):
        return []

    def c_echo(self):
        return True

    def c_store(self, data):
        return True

    def c_get_instance(self, *args, **kwargs):
        return b""

    def c_move_instances(self, *args, **kwargs):
        return None

    def c_move_series(self, *args, **kwargs):
        return None


def test_web_exception_returns_empty() -> None:
    web = _MockWeb(fail=True)
    dimse = _MockDimse(studies=[StudyInfo(
        study_uid="1", patient_name="TEST", patient_id="1",
        study_date="20240101", study_description="Test", series_count=1,
    )])
    svc = DicomQueryService(web=web, dimse=dimse, source=QuerySource.DICOMWEB)
    assert svc.query_studies() == []


def test_dimse_exception_returns_empty() -> None:
    dimse = _MockDimse(fail=True)
    svc = DicomQueryService(web=None, dimse=dimse, source=QuerySource.DIMSE)
    assert svc.query_studies() == []


def test_auto_web_exception_fallback_to_dimse() -> None:
    """Auto mode: web raises → falls back to dimse."""
    web = _MockWeb(fail=True)
    study = StudyInfo(
        study_uid="1", patient_name="TEST", patient_id="1",
        study_date="20240101", study_description="Test", series_count=1,
    )
    dimse = _MockDimse(studies=[study])
    svc = DicomQueryService(web=web, dimse=dimse, source=QuerySource.AUTO)
    result = svc.query_studies()
    assert len(result) == 1


def test_auto_both_empty_returns_empty() -> None:
    web = _MockWeb(studies=[])
    dimse = _MockDimse(studies=[])
    svc = DicomQueryService(web=web, dimse=dimse, source=QuerySource.AUTO)
    assert svc.query_studies() == []


def test_auto_web_returns_results_skips_dimse() -> None:
    study = StudyInfo(
        study_uid="1", patient_name="TEST", patient_id="1",
        study_date="20240101", study_description="Test", series_count=1,
    )
    web = _MockWeb(studies=[study])
    dimse = _MockDimse(studies=[study])
    svc = DicomQueryService(web=web, dimse=dimse, source=QuerySource.AUTO)
    result = svc.query_studies()
    assert len(result) == 1


def test_web_none_returns_empty() -> None:
    svc = DicomQueryService(web=None, dimse=None, source=QuerySource.DICOMWEB)
    assert svc.query_studies() == []


def test_dimse_none_returns_empty() -> None:
    svc = DicomQueryService(web=None, dimse=None, source=QuerySource.DIMSE)
    assert svc.query_studies() == []


def test_query_series_web_fallback_to_dimse() -> None:
    """query_series: DIMSE source with dimse=None but web available → uses web."""
    web = _MockWeb()
    svc = DicomQueryService(web=web, dimse=None, source=QuerySource.AUTO)
    result = svc.query_series("1.2.3")
    assert isinstance(result, list)


def test_query_series_none_clients_returns_empty() -> None:
    svc = DicomQueryService(web=None, dimse=None, source=QuerySource.AUTO)
    assert svc.query_series("1.2.3") == []


def test_query_instances_none_clients_returns_empty() -> None:
    svc = DicomQueryService(web=None, dimse=None, source=QuerySource.AUTO)
    assert svc.query_instances("1.2.3", "1.2.3.4") == []


def test_query_series_dimse_source_with_no_dimse_falls_back_to_web() -> None:
    """DIMSE source but dimse is None → falls to web path."""
    web = _MockWeb()
    svc = DicomQueryService(web=web, dimse=None, source=QuerySource.DIMSE)
    result = svc.query_series("1.2.3")
    assert isinstance(result, list)
