"""Tests for query_source persistence from Orthanc study dialog."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.gui
from PySide6.QtCore import QSettings, Qt, QTimer
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


def test_continue_work_hides_dialog_without_cancelling(make_dialog, tmp_path):
    from PySide6.QtCore import Qt

    dialog = make_dialog(FakeDicomWebClient(), OrthancSessionCache(tmp_path))
    dialog.open()
    dialog._downloading = True
    dialog._continue_in_background()
    # «Продолжить работу» must actually get the download window out of the
    # way: the main window's tabs and toolbar are usable, the batch keeps
    # running, and the hidden dialog is not re-shown by the modality flip.
    assert not dialog.isVisible()
    assert dialog.windowModality() == Qt.WindowModality.NonModal
    assert dialog._background_requested
    assert dialog._downloading
    # Finishing (or failing) the batch brings the window back so its result /
    # error message has a visible parent and the user can cancel or retry.
    dialog._reset_after_download()
    assert dialog.isVisible()
    dialog.reject()


def test_server_action_restores_a_hidden_download(make_dialog, tmp_path):
    """The coordinator still owns the hidden dialog and can bring it back."""
    from unittest.mock import MagicMock

    from echo_personal_tool.presentation.download_coordinator import DownloadCoordinator

    dialog = make_dialog(FakeDicomWebClient(), OrthancSessionCache(tmp_path))
    dialog.open()
    dialog._downloading = True
    dialog._continue_in_background()
    assert not dialog.isVisible()

    coordinator = DownloadCoordinator(
        MagicMock(),
        cache=MagicMock(),
        history=MagicMock(),
    )
    coordinator._dialog = dialog
    assert coordinator.has_active_download()
    coordinator.show_active_dialog()
    assert dialog.isVisible()
    dialog._downloading = False
    dialog.reject()


def test_continue_work_hides_before_modality_flip(make_dialog, tmp_path):
    """Hide must precede the modality flip — the order is the fix.

    Qt disables the parent HWND while a window-modal dialog is open and
    re-enables it on hide, but ONLY if the dialog is still modal at hide
    time.  Flipping ``setWindowModality(NonModal)`` first makes Qt skip that
    re-enable: the dialog disappears yet the main window stays blocked at
    the Win32 level (the "blocked" sound plays on every click, no button
    works, the hidden dialog cannot be brought back) and the app has to be
    killed from Task Manager.      Guard the ordering here; the native
    consequence is asserted in the Windows-platform test below.
    """
    dialog = make_dialog(FakeDicomWebClient(), OrthancSessionCache(tmp_path))
    calls: list[tuple] = []
    orig_hide = OrthancStudyDialog.hide
    orig_flip = OrthancStudyDialog.setWindowModality

    def hide(wrapper_self):
        calls.append(("hide",))
        return orig_hide(wrapper_self)

    def flip(wrapper_self, modality):
        calls.append(("modality", modality))
        return orig_flip(wrapper_self, modality)

    dialog.open()
    dialog._downloading = True
    with (
        patch.object(OrthancStudyDialog, "hide", hide),
        patch.object(OrthancStudyDialog, "setWindowModality", flip),
    ):
        dialog._continue_in_background()

    assert calls == [("hide",), ("modality", Qt.WindowModality.NonModal)]
    assert not dialog.isVisible()
    assert dialog.windowModality() == Qt.WindowModality.NonModal
    assert dialog._background_requested
    dialog._downloading = False
    dialog.reject()


@pytest.mark.skipif(sys.platform != "win32", reason="native HWND enable state is Windows-only")
def test_continue_work_reenables_parent_window(make_dialog, tmp_path, qapp):
    """«Continue working» must release the main window, not just hide itself.

    Asserts the real Win32 consequence of the ordering above: while the
    window-modal dialog is up the parent HWND is disabled, and after
    ``_continue_in_background()`` it must be enabled again — otherwise every
    click in the main window plays the "blocked" sound and the app has to be
    killed from Task Manager.  Needs a real windows platform (the default
    test run is offscreen, where there are no HWNDs):
    ``QT_QPA_PLATFORM=windows pytest …``
    """
    import ctypes

    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QWidget

    if QGuiApplication.platformName() != "windows":
        pytest.skip("needs the real windows QPA platform for HWNDs")

    parent = QWidget()
    parent.show()
    qapp.processEvents()
    user32 = ctypes.windll.user32
    hwnd = int(parent.winId())
    assert user32.IsWindowEnabled(hwnd)

    dialog = make_dialog(FakeDicomWebClient(), OrthancSessionCache(tmp_path), parent=parent)
    dialog.open()
    qapp.processEvents()
    # Window-modal: the parent is blocked while the dialog is up.
    assert not user32.IsWindowEnabled(hwnd)

    dialog._downloading = True
    dialog._continue_in_background()
    qapp.processEvents()

    assert not dialog.isVisible()
    assert dialog.windowModality() == Qt.WindowModality.NonModal
    # The whole point: the main window must be usable again.
    assert user32.IsWindowEnabled(hwnd)

    # …and re-showing the dialog later (batch finished / PACS action) must
    # not re-block the parent now that it is non-modal.
    dialog._reset_after_download()
    qapp.processEvents()
    assert dialog.isVisible()
    assert user32.IsWindowEnabled(hwnd)

    dialog._downloading = False
    dialog.reject()
    parent.close()
