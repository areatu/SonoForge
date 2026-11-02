"""Tests for query_source persistence from Orthanc study dialog."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.gui
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication

from echo_personal_tool.domain.ports import QuerySource
from echo_personal_tool.infrastructure import server_settings as ss
from echo_personal_tool.infrastructure.fake_dicom_web_client import FakeDicomWebClient
from echo_personal_tool.infrastructure.orthanc_cache import OrthancSessionCache
from echo_personal_tool.infrastructure.server_settings import (
    ServerSettings,
    load_server_settings,
    save_server_settings,
)
from echo_personal_tool.presentation.orthanc_study_dialog import OrthancStudyDialog


@pytest.fixture
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def make_dialog(qapp):
    def _make(*args, **kwargs):
        with (
            patch.object(OrthancStudyDialog, "_init_network"),
            patch.object(QTimer, "singleShot"),
        ):
            d = OrthancStudyDialog(*args, **kwargs)
        d._force_close_timer.stop()
        d._init_timer.stop()
        return d

    return _make


@pytest.fixture
def isolated_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    org = "sonoforge-test"
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
    make_dialog,
    isolated_settings: None,
    tmp_path,
) -> None:
    save_server_settings(ServerSettings(query_source="dicomweb"))
    dialog = make_dialog(
        FakeDicomWebClient(),
        OrthancSessionCache(tmp_path),
        server_settings=load_server_settings(),
    )
    dialog._persist_query_source("auto")
    assert load_server_settings().query_source == "auto"


def test_source_combo_persists_on_change(
    make_dialog,
    isolated_settings: None,
    tmp_path,
) -> None:
    from echo_personal_tool.application.dicom_query_service import DicomQueryService
    from echo_personal_tool.infrastructure.fake_dimse_client import FakeDimseClient

    save_server_settings(ServerSettings(use_mock=True, query_source="dicomweb"))
    query_service = DicomQueryService(
        web=FakeDicomWebClient(),
        dimse=FakeDimseClient(),
        source=QuerySource.DICOMWEB,
    )
    dialog = make_dialog(
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


def test_accepts_injected_retrieve_service(make_dialog, tmp_path) -> None:
    """L4: when the caller injects a shared retrieve service, the dialog must
    use it and must NOT build another one (which would duplicate the client)."""
    retrieve = object()  # DicomRetrieveService sentinel
    with patch(
        "echo_personal_tool.presentation.orthanc_study_dialog.make_dicom_retrieve_service",
        side_effect=AssertionError("dialog must not build its own retrieve service when injected"),
    ) as mock_factory:
        dialog = make_dialog(
            FakeDicomWebClient(),
            OrthancSessionCache(tmp_path),
            server_settings=ServerSettings(use_mock=True),
            retrieve_service=retrieve,
        )
        mock_factory.assert_not_called()
    assert dialog._retrieve_service is retrieve


def test_builds_own_retrieve_service_when_not_injected(make_dialog, tmp_path) -> None:
    """Backwards compatibility: without an injected retrieve service and with
    server settings, the dialog builds one from settings (legacy behaviour)."""
    retrieve = object()
    with patch(
        "echo_personal_tool.presentation.orthanc_study_dialog.make_dicom_retrieve_service",
        return_value=retrieve,
    ) as mock_factory:
        dialog = make_dialog(
            FakeDicomWebClient(),
            OrthancSessionCache(tmp_path),
            server_settings=ServerSettings(use_mock=True),
        )
        mock_factory.assert_called_once()
    assert dialog._retrieve_service is retrieve


def test_status_label_cannot_stretch_dialog(make_dialog, tmp_path) -> None:
    """CHANGELOG item 2: a long failure chain must not widen the dialog.

    The status label wraps and is clipped; the full text is only logged.
    """
    dialog = make_dialog(
        FakeDicomWebClient(),
        OrthancSessionCache(tmp_path),
        server_settings=ServerSettings(use_mock=True),
    )
    label = dialog._status_label
    assert label.wordWrap()
    assert label.minimumWidth() == 0

    dialog.resize(800, 520)
    dialog._set_status("cache write failed: [Errno 2] " * 40)

    assert len(label.text()) <= 240
    assert label.text().endswith("…")

    dialog.adjustSize()
    assert dialog.width() <= 800


def test_clip_keeps_short_text_and_bounds_long_text() -> None:
    from echo_personal_tool.presentation.orthanc_study_dialog import OrthancStudyDialog

    assert OrthancStudyDialog._clip("short", 240) == "short"
    clipped = OrthancStudyDialog._clip("x" * 1000, 400)
    assert len(clipped) == 400
    assert clipped.endswith("…")


def test_completion_marker_is_independent_from_download_selection(make_dialog, tmp_path):
    from echo_personal_tool.application.saved_records import study_key_for_uid
    from echo_personal_tool.domain.models.orthanc import StudyInfo
    from echo_personal_tool.presentation.orthanc_study_delegate import ROLE_CHECKED, ROLE_COMPLETED

    uid = "1.2.3.4"
    dialog = make_dialog(FakeDicomWebClient(), OrthancSessionCache(tmp_path))
    with patch.object(dialog, "_start_enrichment"):
        dialog._on_studies_loaded([StudyInfo(uid, "", "", "", "")])
    item = dialog._studies_list.topLevelItem(0)
    assert not item.data(0, ROLE_COMPLETED)
    dialog.set_completed_measurement_keys({study_key_for_uid(uid)})
    assert item.data(0, ROLE_COMPLETED)
    assert not item.data(0, ROLE_CHECKED)
    dialog._on_completion_toggled(item)
    assert not item.data(0, ROLE_COMPLETED)
    assert not item.data(0, ROLE_CHECKED)
    dialog.set_completed_measurement_keys({study_key_for_uid(uid)})
    assert not item.data(0, ROLE_COMPLETED)  # manual choice wins
    dialog.reject()


def test_continue_work_releases_modality_without_cancelling(make_dialog, tmp_path):
    from PySide6.QtCore import Qt

    dialog = make_dialog(FakeDicomWebClient(), OrthancSessionCache(tmp_path))
    dialog.open()
    dialog._downloading = True
    dialog._continue_in_background()
    assert dialog.isVisible()
    assert dialog.windowModality() == Qt.WindowModality.NonModal
    assert dialog._background_requested
    assert dialog._downloading
    dialog._downloading = False
    dialog.reject()
