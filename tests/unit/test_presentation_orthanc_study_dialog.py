"""Unit tests for presentation/orthanc_study_dialog.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def _setup_qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture()
def mock_client():
    client = MagicMock()
    client.ping.return_value = True
    client.query_studies.return_value = []
    client.query_series.return_value = []
    return client


@pytest.fixture()
def mock_cache():
    cache = MagicMock()
    cache.create_session.return_value = "test-session"
    cache.session_path.return_value = MagicMock(exists=MagicMock(return_value=True))
    return cache


@pytest.fixture()
def dialog(mock_client, mock_cache):
    from PySide6.QtCore import QTimer

    from echo_personal_tool.presentation.orthanc_study_dialog import OrthancStudyDialog

    with (
        patch.object(OrthancStudyDialog, "_init_network"),
        patch.object(QTimer, "singleShot"),
    ):
        d = OrthancStudyDialog(mock_client, mock_cache)
    # Stop the force close timer to prevent segfaults during teardown
    d._force_close_timer.stop()
    yield d
    # Prevent any pending callbacks from accessing deleted C++ objects
    d.blockSignals(True)
    for child in d.findChildren(QTimer):
        child.stop()
        child.blockSignals(True)


class TestOrthancStudyDialogInit:
    def test_creates(self, dialog):
        assert dialog is not None

    def test_initial_state(self, dialog):
        assert dialog._result is None
        assert dialog._downloading is False
        assert dialog._worker is None
        assert dialog._downloaded_studies == []
        assert dialog._pending_downloads == []

    def test_title_set(self, dialog):
        assert dialog.windowTitle() != ""

    def test_search_edit_exists(self, dialog):
        assert dialog._search_edit is not None

    def test_tree_exists(self, dialog):
        assert dialog._tree is not None


class TestResultData:
    def test_returns_none_initially(self, dialog):
        assert dialog.result_data() is None

    def test_returns_result(self, dialog):
        dialog._result = ("session", "study-uid")
        assert dialog.result_data() == ("session", "study-uid")


class TestDownloadedStudies:
    def test_empty_initially(self, dialog):
        assert dialog.downloaded_studies() == []

    def test_returns_studies(self, dialog):
        study = MagicMock()
        dialog._downloaded_studies = [study]
        assert dialog.downloaded_studies() == [study]


class TestCollectCheckedSeries:
    def test_empty_tree(self, dialog):
        result = dialog._collect_all_checked_series()
        assert result == []

    def test_no_checked(self, dialog):
        from PySide6.QtWidgets import QTreeWidgetItem

        item = QTreeWidgetItem()
        item.setData(0, 256, "study-uid")  # _STUDY_UID_ROLE = UserRole = 256
        dialog._tree.addTopLevelItem(item)
        result = dialog._collect_all_checked_series()
        assert result == []


class TestShortUid:
    def test_short_uid(self, dialog):
        assert dialog._short_uid("abc") == "abc"

    def test_long_uid(self, dialog):
        uid = "a" * 20
        result = dialog._short_uid(uid)
        assert len(result) == 13
        assert result.endswith("…")


class TestSeriesLabel:
    def test_series_label(self, dialog):
        from echo_personal_tool.domain.models.orthanc import SeriesInfo

        series = SeriesInfo(
            study_uid="study-uid",
            series_uid="uid",
            modality="US",
            description="Echo",
            instance_count=10,
        )
        label = dialog._series_label(series)
        assert "US" in label
        assert "Echo" in label
        assert "10" in label


class TestCheckPing:
    def test_ping_success(self, dialog, mock_client):
        mock_client.ping.return_value = True
        dialog._check_ping()
        assert "available" in dialog._status_label.text().lower() or "доступен" in dialog._status_label.text().lower()

    def test_ping_failure(self, dialog, mock_client):
        mock_client.ping.return_value = False
        with patch("echo_personal_tool.presentation.orthanc_study_dialog.QMessageBox"):
            dialog._check_ping()


class TestLoadStudies:
    def test_load_studies_empty(self, dialog, mock_client):
        mock_client.query_studies.return_value = []
        dialog._load_studies()
        assert dialog._tree.topLevelItemCount() == 0

    def test_load_studies_with_data(self, dialog, mock_client):
        study = MagicMock()
        study.patient_name = "John"
        study.study_date = "20240101"
        study.study_description = "Echo"
        study.study_uid = "uid-123"
        mock_client.query_studies.return_value = [study]
        dialog._load_studies()
        assert dialog._tree.topLevelItemCount() == 1

    def test_load_studies_exception(self, dialog, mock_client):
        mock_client.query_studies.side_effect = Exception("Network error")
        with patch("echo_personal_tool.presentation.orthanc_study_dialog.QMessageBox"):
            dialog._load_studies()


class TestOnItemChanged:
    def test_non_series_item_ignored(self, dialog):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QTreeWidgetItem

        item = QTreeWidgetItem()
        item.setData(0, Qt.ItemDataRole.UserRole, None)
        dialog._on_item_changed(item, 1)  # column != 0
        # Should not crash


class TestUpdateLoadButton:
    def test_disabled_when_no_checked(self, dialog):
        dialog._update_load_button()
        assert not dialog._load_btn.isEnabled()

    def test_disabled_when_downloading(self, dialog):
        dialog._downloading = True
        dialog._update_load_button()


class TestOnSourceChanged:
    def test_source_changed_dimse(self, dialog):
        dialog._source_combo.setCurrentIndex(1)  # DIMSE
        dialog._on_source_changed()

    def test_persist_query_source(self, dialog):
        with (
            patch("echo_personal_tool.presentation.orthanc_study_dialog.load_server_settings") as mock_load,
            patch("echo_personal_tool.presentation.orthanc_study_dialog.save_server_settings"),
        ):
            mock_load.return_value = MagicMock(query_source="dicomweb")
            dialog._persist_query_source("dicomweb")
            # No change, should not save


class TestOnCancel:
    def test_cancel_not_downloading(self, dialog):
        dialog._downloading = False
        with patch.object(dialog, "reject") as mock_reject:
            dialog._on_cancel()
            mock_reject.assert_called_once()


class TestForceClose:
    def test_force_close_when_downloading(self, dialog):
        dialog._downloading = True
        dialog._session_id = "test-session"
        dialog._force_close_if_still_downloading()
        assert dialog._downloading is False
        assert dialog._session_id is None


class TestOnStudiesReady:
    def test_extends_list(self, dialog):
        study = MagicMock()
        study.series = [MagicMock(instances=[MagicMock()])]
        dialog._on_studies_ready([study])
        assert len(dialog._downloaded_studies) == 1


class TestOnProgress:
    def test_updates_progress(self, dialog):
        dialog._on_progress(5, 10, "series-uid")
        assert dialog._progress.value() == 5
        assert dialog._progress.maximum() == 10


class TestOnSingleStudyDone:
    def test_increments_count(self, dialog):
        dialog._total_studies = 2
        dialog._completed_downloads = 0
        dialog._pending_downloads = []
        dialog._on_single_study_done("session", "study-uid")
        assert dialog._completed_downloads == 1


class TestOnSingleStudyFailed:
    def test_increments_count(self, dialog):
        dialog._total_studies = 2
        dialog._completed_downloads = 0
        dialog._pending_downloads = []
        dialog._on_single_study_failed("uid", "error msg")
        assert dialog._completed_downloads == 1


class TestOnDone:
    def test_sets_result(self, dialog):
        dialog._total_studies = 1
        dialog._completed_downloads = 1
        with patch.object(dialog, "accept"):
            dialog._on_done("session-123", "study-uid")
        assert dialog._result == ("session-123", "study-uid")
        assert dialog._session_id is None


class TestOnFailed:
    def test_resets_state(self, dialog):
        dialog._session_id = "test"
        dialog._pending_downloads = []
        with patch("echo_personal_tool.presentation.orthanc_study_dialog.QMessageBox"):
            dialog._on_failed("uid", "error")
        assert dialog._session_id is None
        assert dialog._tree.isEnabled()

    def test_retries_next_pending(self, dialog):
        dialog._session_id = "test"
        dialog._pending_downloads = [("study", ["series"])]
        with patch.object(dialog, "_start_next_download") as mock_next:
            dialog._on_failed("uid", "error")
            mock_next.assert_called_once()


class TestOnCancelled:
    def test_resets_state(self, dialog):
        dialog._session_id = "test"
        with patch.object(dialog, "reject"):
            dialog._on_cancelled("test")
        assert dialog._session_id is None
        assert dialog._tree.isEnabled()


class TestResetAfterDownload:
    def test_resets(self, dialog):
        dialog._downloading = True
        dialog._worker = MagicMock()
        dialog._reset_after_download()
        assert dialog._downloading is False
        assert dialog._worker is None


class TestReject:
    def test_reject_when_not_downloading(self, dialog):
        dialog._downloading = False
        with patch.object(dialog._force_close_timer, "stop"), patch("PySide6.QtWidgets.QDialog.reject"):
            dialog.reject()
