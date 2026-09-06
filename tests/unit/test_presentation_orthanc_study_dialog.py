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


class TestBuildStudyTree:
    def _study(self, name="John", date="20240101", desc="Echo", uid="uid-123"):
        study = MagicMock()
        study.patient_name = name
        study.study_date = date
        study.study_description = desc
        study.study_uid = uid
        return study

    def test_empty(self, dialog):
        dialog._build_study_tree([])
        assert dialog._tree.topLevelItemCount() == 0

    def test_with_data(self, dialog):
        dialog._build_study_tree([self._study()])
        assert dialog._tree.topLevelItemCount() == 1

    def test_sorts_by_date_desc(self, dialog):
        dialog._build_study_tree(
            [
                self._study(date="20240101", uid="a"),
                self._study(date="20240615", uid="b"),
                self._study(date="20240310", uid="c"),
            ]
        )
        assert dialog._tree.topLevelItemCount() == 3
        # Newest first
        assert dialog._tree.topLevelItem(0).data(1, 258) == "20240615"  # _SORT_ROLE = UserRole+2 = 258


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


class TestStartNextDownload:
    def test_all_fail_shows_error_not_done(self, dialog):
        """When all studies fail, _on_failed should be called (not _on_done)."""
        dialog._session_id = "test-session"
        dialog._total_studies = 2
        dialog._completed_downloads = 2
        dialog._failed_downloads = 2
        dialog._pending_downloads = []

        with (
            patch.object(dialog, "_on_done") as mock_done,
            patch.object(dialog, "_on_failed") as mock_failed,
            patch.object(dialog, "_reset_after_download"),
        ):
            dialog._start_next_download()
            mock_failed.assert_called_once()
            mock_done.assert_not_called()

    def test_partial_failure_keeps_successful_downloads(self, dialog):
        """When some studies fail but others succeeded, the successful data
        must be kept (_on_partial_done), NOT wiped via _on_failed."""
        dialog._session_id = "test-session"
        dialog._total_studies = 2
        dialog._completed_downloads = 2
        dialog._failed_downloads = 1
        dialog._pending_downloads = []

        with (
            patch.object(dialog, "_on_done") as mock_done,
            patch.object(dialog, "_on_failed") as mock_failed,
            patch.object(dialog, "_on_partial_done") as mock_partial,
            patch.object(dialog, "_reset_after_download"),
        ):
            dialog._start_next_download()
            mock_partial.assert_called_once()
            mock_failed.assert_not_called()
            mock_done.assert_not_called()

    def test_all_success_shows_done(self, dialog):
        """When all studies succeed, _on_done should be called."""
        dialog._session_id = "test-session"
        dialog._total_studies = 2
        dialog._completed_downloads = 2
        dialog._failed_downloads = 0
        dialog._pending_downloads = []
        dialog._result = None

        with (
            patch.object(dialog, "_on_done") as mock_done,
            patch.object(dialog, "_on_failed") as mock_failed,
        ):
            dialog._start_next_download()
            mock_done.assert_called_once()
            mock_failed.assert_not_called()


class TestOnSingleStudyFailedCount:
    def test_increments_both_counts(self, dialog):
        """_on_single_study_failed should increment both completed and failed counts."""
        dialog._total_studies = 2
        dialog._completed_downloads = 0
        dialog._failed_downloads = 0
        dialog._pending_downloads = []
        dialog._session_id = "test-session"
        # Prevent _start_next_download from calling accept/reject
        with patch.object(dialog, "_start_next_download"):
            dialog._on_single_study_failed("uid", "error msg")
        assert dialog._completed_downloads == 1
        assert dialog._failed_downloads == 1


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


class TestSeriesLoadingState:
    def test_initial_empty(self, dialog):
        assert dialog._series_loading == set()


class TestOnItemExpanded:
    _STUDY_ROLE = 256  # Qt.ItemDataRole.UserRole

    def _add_study_item(self, dialog, uid="study-uid"):
        from PySide6.QtWidgets import QTreeWidgetItem

        item = QTreeWidgetItem(["John", "20240101", "Echo"])
        item.setData(0, self._STUDY_ROLE, uid)
        dialog._tree.addTopLevelItem(item)
        return item

    def test_does_not_call_query_series_synchronously(self, dialog):
        item = self._add_study_item(dialog)
        with (
            patch.object(dialog._client, "query_series") as mock_qs,
            patch("echo_personal_tool.presentation.orthanc_study_dialog.QThreadPool") as mock_pool,
        ):
            dialog._on_item_expanded(item)
            mock_qs.assert_not_called()
            mock_pool.globalInstance().start.assert_called_once()

    def test_shows_loading_indicator(self, dialog):
        item = self._add_study_item(dialog)
        with patch("echo_personal_tool.presentation.orthanc_study_dialog.QThreadPool"):
            dialog._on_item_expanded(item)
            assert item.childCount() == 1

    def test_tracks_in_flight_query(self, dialog):
        item = self._add_study_item(dialog)
        with patch("echo_personal_tool.presentation.orthanc_study_dialog.QThreadPool"):
            dialog._on_item_expanded(item)
            assert "study-uid" in dialog._series_loading

    def test_prevents_duplicate_query(self, dialog):
        item = self._add_study_item(dialog)
        dialog._series_loading.add("study-uid")
        with patch("echo_personal_tool.presentation.orthanc_study_dialog.QThreadPool") as mock_pool:
            dialog._on_item_expanded(item)
            mock_pool.globalInstance().start.assert_not_called()

    def test_ignores_child_items(self, dialog):
        from PySide6.QtWidgets import QTreeWidgetItem

        parent = self._add_study_item(dialog)
        child = QTreeWidgetItem(["child", "", ""])
        child.setData(0, self._STUDY_ROLE, "child-uid")
        parent.addChild(child)
        with patch("echo_personal_tool.presentation.orthanc_study_dialog.QThreadPool") as mock_pool:
            dialog._on_item_expanded(child)
            mock_pool.globalInstance().start.assert_not_called()

    def test_skips_already_has_children(self, dialog):
        from PySide6.QtWidgets import QTreeWidgetItem

        item = self._add_study_item(dialog)
        item.addChild(QTreeWidgetItem(["", "", "existing"]))
        with patch("echo_personal_tool.presentation.orthanc_study_dialog.QThreadPool") as mock_pool:
            dialog._on_item_expanded(item)
            mock_pool.globalInstance().start.assert_not_called()


class TestOnSeriesLoaded:
    _STUDY_ROLE = 256
    _SERIES_ROLE = 257

    def _add_study_item(self, dialog, uid="study-uid"):
        from PySide6.QtWidgets import QTreeWidgetItem

        item = QTreeWidgetItem(["John", "20240101", "Echo"])
        item.setData(0, self._STUDY_ROLE, uid)
        dialog._tree.addTopLevelItem(item)
        # Simulate loading placeholder child
        loading = QTreeWidgetItem(["", "", "Loading..."])
        item.addChild(loading)
        return item

    def test_populates_series_on_success(self, dialog):
        item = self._add_study_item(dialog)
        from echo_personal_tool.domain.models.orthanc import SeriesInfo

        series_list = [
            SeriesInfo(
                study_uid="study-uid", series_uid="series-1", modality="US", description="Echo", instance_count=10
            ),
            SeriesInfo(
                study_uid="study-uid", series_uid="series-2", modality="DC", description="Doppler", instance_count=5
            ),
        ]
        dialog._on_series_loaded(("study-uid", series_list, None))
        assert item.childCount() == 2
        assert item.child(0).data(0, self._SERIES_ROLE) == "series-1"
        assert item.child(1).data(0, self._SERIES_ROLE) == "series-2"
        assert "study-uid" not in dialog._series_loading

    def test_shows_error_on_failure(self, dialog):
        item = self._add_study_item(dialog)
        dialog._on_series_loaded(("study-uid", [], "Connection timeout"))
        assert item.childCount() == 1
        assert "study-uid" not in dialog._series_loading

    def test_missing_target_item_no_crash(self, dialog):
        dialog._on_series_loaded(("nonexistent-uid", [], None))
        assert "nonexistent-uid" not in dialog._series_loading

    def test_removes_loading_placeholder(self, dialog):
        item = self._add_study_item(dialog)
        assert item.childCount() == 1  # loading child
        dialog._on_series_loaded(("study-uid", [], None))
        assert item.childCount() == 0  # loading replaced with nothing

    def test_empty_series_clears_children(self, dialog):
        item = self._add_study_item(dialog)
        dialog._on_series_loaded(("study-uid", [], None))
        assert item.childCount() == 0

    def test_finds_correct_item_among_multiple(self, dialog):
        from echo_personal_tool.domain.models.orthanc import SeriesInfo

        self._add_study_item(dialog, uid="study-1")
        target = self._add_study_item(dialog, uid="study-2")
        self._add_study_item(dialog, uid="study-3")

        dialog._on_series_loaded(
            (
                "study-2",
                [SeriesInfo(study_uid="study-2", series_uid="s2", modality="US", description="A", instance_count=1)],
                None,
            )
        )
        assert target.childCount() == 1
        assert target.child(0).data(0, self._SERIES_ROLE) == "s2"


class TestReject:
    def test_reject_when_not_downloading(self, dialog):
        dialog._downloading = False
        with patch.object(dialog._force_close_timer, "stop"), patch("PySide6.QtWidgets.QDialog.reject"):
            dialog.reject()

    def test_clears_series_loading_on_reject(self, dialog):
        dialog._downloading = False
        dialog._series_loading.add("study-uid")
        with patch.object(dialog._force_close_timer, "stop"), patch("PySide6.QtWidgets.QDialog.reject"):
            dialog.reject()
        assert dialog._series_loading == set()
