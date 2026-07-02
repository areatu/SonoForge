"""Tests for query_source persistence from Orthanc study dialog."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from echo_personal_tool.domain.ports import QuerySource
from echo_personal_tool.infrastructure import server_settings as ss
from echo_personal_tool.infrastructure.server_settings import (
    ServerSettings,
    load_server_settings,
    save_server_settings,
)
from echo_personal_tool.presentation.orthanc_study_dialog import OrthancStudyDialog
from echo_personal_tool.infrastructure.fake_dicom_web_client import FakeDicomWebClient
from echo_personal_tool.infrastructure.orthanc_cache import OrthancSessionCache


@pytest.fixture
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def isolated_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    org = "echo-personal-tool-test"
    app = "server-test-query-source"
    monkeypatch.setattr(ss, "_SETTINGS_ORG", org)
    monkeypatch.setattr(ss, "_SETTINGS_APP", app)
    store = QSettings(org, app)
    store.clear()
    store.sync()
    yield
    store.clear()
    store.sync()


def test_persist_query_source_updates_qsettings(
    qapp, isolated_settings: None, tmp_path,
) -> None:
    save_server_settings(ServerSettings(query_source="dicomweb"))
    dialog = OrthancStudyDialog(
        FakeDicomWebClient(),
        OrthancSessionCache(tmp_path),
        server_settings=load_server_settings(),
    )
    dialog._persist_query_source("auto")
    assert load_server_settings().query_source == "auto"


def test_source_combo_persists_on_change(
    qapp, isolated_settings: None, tmp_path,
) -> None:
    from echo_personal_tool.application.dicom_query_service import DicomQueryService
    from echo_personal_tool.infrastructure.fake_dimse_client import FakeDimseClient

    save_server_settings(ServerSettings(use_mock=True, query_source="dicomweb"))
    query_service = DicomQueryService(
        web=FakeDicomWebClient(),
        dimse=FakeDimseClient(),
        source=QuerySource.DICOMWEB,
    )
    dialog = OrthancStudyDialog(
        FakeDicomWebClient(),
        OrthancSessionCache(tmp_path),
        server_settings=load_server_settings(),
        query_service=query_service,
    )
    dimse_idx = dialog._source_combo.findData("dimse")
    dialog._source_combo.setCurrentIndex(dimse_idx)
    dialog._on_source_changed()
    assert load_server_settings().query_source == "dimse"
    assert query_service.source == QuerySource.DIMSE
