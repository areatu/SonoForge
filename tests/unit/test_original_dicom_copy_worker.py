"""Behavioral tests for OriginalDicomCopyWorker (copy original by UID)."""

from __future__ import annotations

from pathlib import Path

import pydicom
import pytest

from echo_personal_tool.application.server_io import ServerSettings
from echo_personal_tool.application.services.dicom_retrieve_service import RetrieveError
from echo_personal_tool.application.workers import original_dicom_copy_worker as mod
from echo_personal_tool.application.workers.original_dicom_copy_worker import (
    ORIGINAL_COPY_FAILURE_CODE,
    OriginalDicomCopyWorker,
)
from tests.fixtures.generate_synthetic_dicom import write_synthetic_dicom


class _FakeService:
    def __init__(self, payload: bytes | None = None, error: Exception | None = None) -> None:
        self._payload = payload
        self._error = error
        self.calls: list[tuple[str, str, str]] = []

    def retrieve_instance(self, study_uid: str, series_uid: str, instance_uid: str) -> bytes:
        self.calls.append((study_uid, series_uid, instance_uid))
        if self._error is not None:
            raise self._error
        assert self._payload is not None
        return self._payload


@pytest.fixture
def source(tmp_path: Path) -> Path:
    return write_synthetic_dicom(
        tmp_path / "working.dcm",
        study_uid="1.2.3.4.5",
        series_uid="1.2.3.4.6",
        sop_uid="1.2.3.4.7",
    )


def _wire(monkeypatch: pytest.MonkeyPatch, service: _FakeService, closed: list[object]) -> object:
    web = object()
    monkeypatch.setattr(mod, "make_dicom_web_client", lambda _settings: web)
    monkeypatch.setattr(mod, "make_dimse_client", lambda _settings: object())
    monkeypatch.setattr(mod, "make_dicom_retrieve_service", lambda _settings, **_kw: service)
    monkeypatch.setattr(mod, "close_dicom_web_client", closed.append)
    return web


def test_success_writes_original_bytes_and_closes_web(
    tmp_path: Path, source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = source.read_bytes()
    service = _FakeService(payload=payload)
    closed: list[object] = []
    web = _wire(monkeypatch, service, closed)
    dest = tmp_path / "exported" / "original.dcm"
    finished: list[str] = []
    failed: list[str] = []

    worker = OriginalDicomCopyWorker(ServerSettings(), source, "1.2.3.4.6", "1.2.3.4.7", dest)
    worker.signals.finished.connect(finished.append)
    worker.signals.failed.connect(failed.append)
    worker.run()

    assert failed == []
    assert finished == [str(dest)]
    assert dest.read_bytes() == payload
    assert service.calls == [("1.2.3.4.5", "1.2.3.4.6", "1.2.3.4.7")]
    assert closed == [web]


def test_retrieve_failure_emits_stable_code_without_writing(
    tmp_path: Path, source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _FakeService(error=RetrieveError("All retrieval sources failed", code="all_sources_failed"))
    _wire(monkeypatch, service, [])
    dest = tmp_path / "original.dcm"
    finished: list[str] = []
    failed: list[str] = []

    worker = OriginalDicomCopyWorker(ServerSettings(), source, "1.2.3.4.6", "1.2.3.4.7", dest)
    worker.signals.finished.connect(finished.append)
    worker.signals.failed.connect(failed.append)
    worker.run()

    assert finished == []
    assert failed == [ORIGINAL_COPY_FAILURE_CODE]
    assert not dest.exists()


def test_uid_mismatch_is_rejected_without_writing(
    tmp_path: Path, source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = write_synthetic_dicom(
        tmp_path / "other.dcm",
        study_uid="1.2.3.4.5",
        series_uid="1.2.3.4.6",
        sop_uid="1.2.3.4.8",
    )
    service = _FakeService(payload=other.read_bytes())
    _wire(monkeypatch, service, [])
    dest = tmp_path / "original.dcm"
    failed: list[str] = []

    worker = OriginalDicomCopyWorker(ServerSettings(), source, "1.2.3.4.6", "1.2.3.4.7", dest)
    worker.signals.failed.connect(failed.append)
    worker.run()

    assert failed == [ORIGINAL_COPY_FAILURE_CODE]
    assert not dest.exists()


def test_missing_study_uid_is_rejected(tmp_path: Path, source: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ds = pydicom.dcmread(str(source))
    del ds.StudyInstanceUID
    broken = tmp_path / "no_study.dcm"
    ds.save_as(str(broken))
    service = _FakeService(payload=source.read_bytes())
    _wire(monkeypatch, service, [])
    dest = tmp_path / "original.dcm"
    failed: list[str] = []

    worker = OriginalDicomCopyWorker(ServerSettings(), broken, "1.2.3.4.6", "1.2.3.4.7", dest)
    worker.signals.failed.connect(failed.append)
    worker.run()

    assert failed == [ORIGINAL_COPY_FAILURE_CODE]
    assert service.calls == []
    assert not dest.exists()
