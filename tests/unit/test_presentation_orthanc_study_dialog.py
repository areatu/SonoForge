"""Unit tests for presentation/orthanc_study_dialog.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from echo_personal_tool.domain.models.orthanc import SeriesInfo, StudyInfo
from echo_personal_tool.presentation.orthanc_study_delegate import ROLE_CHECKED, ROLE_PARTIAL, ROLE_ROW, ROLE_UID


def _study(
    *,
    uid: str = "study-uid",
    name: str = "JOHN^DOE",
    date: str = "20240404",
    desc: str = "Echo",
    birth: str = "",
    sex: str = "",
):
    return StudyInfo(
        study_uid=uid,
        patient_name=name,
        patient_id="12345",
        study_date=date,
        study_description=desc,
        series_count=3,
        patient_birth_date=birth,
        patient_sex=sex,
        modalities_in_study="US, XA",
        instances_count=120,
        accession_number="A-1",
    )


def _series(study_uid: str, count: int) -> list[SeriesInfo]:
    return [
        SeriesInfo(
            study_uid=study_uid,
            series_uid=f"s{index + 1}",
            modality="US",
            description=f"Series {index + 1}",
            instance_count=10 * (index + 1),
            series_number=index + 1,
        )
        for index in range(count)
    ]


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

    def test_study_list_exists(self, dialog):
        assert dialog._studies_list is not None
        assert dialog._series_list is not None


class TestResultData:
    def test_returns_none_initially(self, dialog):
        assert dialog.result_data() is None

    def test_returns_result(self, dialog):
        dialog._result = ("session", "study-uid")
        assert dialog.result_data() == ("session", "study-uid")


class TestDownloadedStudies:
    def test_empty_initially(self, dialog):
        assert dialog.downloaded_studies() == []
        assert dialog.completed_disk_download_path() is None

    def test_returns_studies(self, dialog):
        study = MagicMock()
        dialog._downloaded_studies = [study]
        assert dialog.downloaded_studies() == [study]


class TestCollectCheckedSeries:
    def test_empty_tree(self, dialog):
        assert dialog._collect_all_checked_series() == []

    def test_unchecked_study_is_ignored(self, dialog):
        dialog._on_studies_loaded([_study(uid="study-uid")], None)
        assert dialog._collect_all_checked_series() == []

    def test_whole_study_selection_uses_all_known_series(self, dialog):
        dialog._on_studies_loaded([_study(uid="study-uid")], None)
        dialog._on_series_loaded(("study-uid", _series("study-uid", 3), None))
        dialog._set_study_selected("study-uid", True)
        result = dialog._collect_all_checked_series()
        assert result == [("study-uid", ["s1", "s2", "s3"])]

    def test_subset_selection_keeps_only_checked_series(self, dialog):
        dialog._on_studies_loaded([_study(uid="study-uid")], None)
        dialog._on_series_loaded(("study-uid", _series("study-uid", 3), None))
        dialog._select_study_row("study-uid")
        dialog._set_all_series_checked(True)
        # Untick the middle series through the public toggle path
        item = dialog._series_list.topLevelItem(1)
        dialog._on_series_check_toggled(item)
        assert dialog._collect_all_checked_series() == [("study-uid", ["s1", "s3"])]

    def test_hidden_study_is_not_downloaded(self, dialog):
        dialog._on_studies_loaded([_study(uid="old", date="20200101"), _study(uid="new", date="20990101")], None)
        for uid in ("old", "new"):
            dialog._on_series_loaded((uid, _series(uid, 2), None))
            dialog._set_study_selected(uid, True)
        dialog._filter_studies_by_date(30)
        assert dialog._collect_all_checked_series() == [("new", ["s1", "s2"])]

    def test_study_selected_before_series_known_is_kept(self, dialog):
        """Regression: a ticked study with no series list yet must survive.

        Dropping the entry made "select → Load immediately" finish with
        "0 studies downloaded" while still reporting success.
        """
        dialog._on_studies_loaded([_study(uid="study-uid")], None)
        assert dialog._series_cache == {}
        dialog._set_study_selected("study-uid", True)
        assert dialog._collect_all_checked_series() == [("study-uid", [])]

    def test_checkbox_state_reflects_partial_selection(self, dialog):
        dialog._on_studies_loaded([_study(uid="study-uid")], None)
        dialog._on_series_loaded(("study-uid", _series("study-uid", 3), None))
        dialog._set_study_selected("study-uid", True)
        item = dialog._studies_list.topLevelItem(0)
        assert item.data(0, ROLE_CHECKED) is True
        assert item.data(0, ROLE_PARTIAL) is False

        dialog._select_study_row("study-uid")
        dialog._on_series_check_toggled(dialog._series_list.topLevelItem(0))
        assert item.data(0, ROLE_CHECKED) is False
        assert item.data(0, ROLE_PARTIAL) is True


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
    def test_empty(self, dialog):
        dialog._build_study_rows([])
        assert dialog._studies_list.topLevelItemCount() == 0
        assert dialog._studies_stack.currentIndex() == 1  # empty-state page

    def test_with_data(self, dialog):
        dialog._build_study_rows([_study()])
        assert dialog._studies_list.topLevelItemCount() == 1
        row = dialog._studies_list.topLevelItem(0).data(0, ROLE_ROW)
        assert row is not None
        assert row.study.study_uid == "study-uid"

    def test_sorts_by_date_desc(self, dialog):
        dialog._sort_mode = "date_desc"
        dialog._build_study_rows(
            [
                _study(date="20240101", uid="a"),
                _study(date="20240615", uid="b"),
                _study(date="20240310", uid="c"),
            ]
        )
        order = [
            dialog._studies_list.topLevelItem(i).data(0, ROLE_UID)
            for i in range(dialog._studies_list.topLevelItemCount())
        ]
        assert order == ["b", "c", "a"]

    def test_sort_by_name(self, dialog):
        dialog._sort_mode = "name"
        dialog._build_study_rows(
            [
                _study(name="ПЕТРОВА^АННА", uid="p"),
                _study(name="ИВАНОВ^ИВАН", uid="i"),
            ]
        )
        assert dialog._studies_list.topLevelItem(0).data(0, ROLE_UID) == "i"


class TestStudyRowContent:
    def test_row_formats_patient_name_and_demographics(self, dialog):
        study = _study(uid="u1", birth="19570112", sex="M", date="20240404")
        row = dialog._make_study_row(study)
        assert row.title == "John Doe"
        assert "М" in row.demographics
        assert "ID 12345" in row.demographics

    def test_row_badges_from_server_tags(self, dialog):
        study = _study(uid="u1")
        row = dialog._make_study_row(study)
        texts = [b.text for b in row.badges]
        assert "US/XA" in texts
        assert any("сер." in t for t in texts)
        assert any("инст." in t for t in texts)
        assert any(t.startswith("№ ") for t in texts)

    def test_statistics_badge_added_after_fetch(self, dialog):
        from echo_personal_tool.domain.models.orthanc import StudyStatistics

        dialog._on_studies_loaded([_study(uid="u1")], None)
        dialog._on_study_stats("u1", StudyStatistics(instances=412, series=5, size_mb=84.3, is_stable=True))
        row = dialog._studies_list.topLevelItem(0).data(0, ROLE_ROW)
        texts = [b.text for b in row.badges]
        assert any("84" in t for t in texts)
        assert any("завершено" in t for t in texts)


class TestSelectionSummary:
    def test_empty_summary(self, dialog):
        dialog._update_selection_summary()
        assert "Ничего не выбрано" in dialog._summary_label.text()

    def test_summary_counts_studies_and_series(self, dialog):
        dialog._on_studies_loaded([_study(uid="u1")], None)
        dialog._on_series_loaded(("u1", _series("u1", 2), None))
        dialog._set_study_selected("u1", True)
        text = dialog._summary_label.text()
        assert "1" in text and "2" in text


class TestOnItemChanged:
    def test_non_study_item_ignored(self, dialog):
        """A row without a UID must not raise when toggled."""
        from PySide6.QtWidgets import QTreeWidgetItem

        dialog._on_study_check_toggled(QTreeWidgetItem())

    def test_row_without_uid_is_ignored_by_series_toggle(self, dialog):
        from PySide6.QtWidgets import QTreeWidgetItem

        dialog._on_series_check_toggled(QTreeWidgetItem())


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

    def test_cancel_downloading_without_worker_closes(self, dialog):
        """Finished worker + stuck flag: close immediately, never recurse."""
        dialog._downloading = True
        dialog._worker = None
        with patch.object(dialog, "_force_close_if_still_downloading") as mock_close:
            dialog._on_cancel()
        mock_close.assert_called_once()


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


class TestPartialInstanceFailureWarning:
    @patch("echo_personal_tool.presentation.orthanc_study_dialog.QMessageBox.warning")
    def test_partial_cache_write_failure_is_shown_after_successful_download(self, mock_warning, dialog):
        message = "Downloaded 1/2. Errors: cache write failed: Orthanc cache quota reached"
        dialog._on_partial_instance_failure("1.2.3.4", message)

        with patch.object(dialog, "accept") as mock_accept:
            dialog._on_done("session", "1.2.3.4")

        mock_warning.assert_called_once()
        assert message in mock_warning.call_args.args[2]
        mock_accept.assert_called_once()


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
        assert dialog._studies_list.isEnabled()

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
        assert dialog._studies_list.isEnabled()


class TestResetAfterDownload:
    def test_resets(self, dialog):
        dialog._downloading = True
        dialog._worker = MagicMock()
        dialog._reset_after_download()
        assert dialog._downloading is False
        assert dialog._worker is None


class TestOnDiskDownloadDone:
    """Regression: a stuck ``_downloading`` flag locks the dialog forever."""

    def _prepare(self, dialog, tmp_path):
        dialog._downloading = True
        dialog._worker = MagicMock()
        dialog._session_id = "test-session"
        dialog._save_to_disk_path = str(tmp_path)
        dialog._cache.session_path.return_value = tmp_path

    def test_success_resets_and_accepts(self, dialog, tmp_path):
        self._prepare(dialog, tmp_path)
        with (
            patch.object(dialog, "_copy_session_files", return_value=3),
            patch.object(dialog, "accept") as mock_accept,
            patch("echo_personal_tool.presentation.orthanc_study_dialog.QMessageBox"),
        ):
            dialog._on_disk_download_done()
        assert dialog._downloading is False
        assert dialog._worker is None
        assert dialog._session_id is None
        assert dialog.completed_disk_download_path() == tmp_path
        mock_accept.assert_called_once()

    def test_copy_error_still_resets(self, dialog, tmp_path):
        self._prepare(dialog, tmp_path)
        with (
            patch.object(dialog, "_copy_session_files", side_effect=OSError("No space left on device")),
            patch.object(dialog, "accept") as mock_accept,
            patch("echo_personal_tool.presentation.orthanc_study_dialog.QMessageBox") as mock_box,
        ):
            dialog._on_disk_download_done()
        assert dialog._downloading is False
        assert dialog._worker is None
        assert dialog._studies_list.isEnabled()
        mock_accept.assert_not_called()
        mock_box.warning.assert_called_once()

    def test_partial_copy_error_keeps_ui_unblocked(self, dialog, tmp_path):
        self._prepare(dialog, tmp_path)
        dialog._completed_downloads = 2
        dialog._failed_downloads = 1
        dialog._total_studies = 3
        with (
            patch.object(dialog, "_copy_session_files", side_effect=PermissionError("denied")),
            patch.object(dialog, "accept") as mock_accept,
            patch("echo_personal_tool.presentation.orthanc_study_dialog.QMessageBox"),
        ):
            dialog._on_disk_download_done(partial=True)
        assert dialog._downloading is False
        assert dialog._find_btn.isEnabled()
        mock_accept.assert_not_called()


class TestSeriesLoadingState:
    def test_initial_empty(self, dialog):
        assert dialog._series_loading == set()


class TestSeriesPane:
    def test_lazy_series_query_starts_in_background(self, dialog):
        with (
            patch.object(dialog._client, "query_series") as mock_qs,
            patch("echo_personal_tool.presentation.orthanc_study_dialog.QThreadPool") as mock_pool,
        ):
            dialog._prefetch_series("study-uid", force=True)
            mock_qs.assert_not_called()
            mock_pool.globalInstance().start.assert_called_once()
        assert "study-uid" in dialog._series_loading

    def test_duplicate_query_prevented(self, dialog):
        dialog._series_loading.add("study-uid")
        with patch("echo_personal_tool.presentation.orthanc_study_dialog.QThreadPool") as mock_pool:
            dialog._prefetch_series("study-uid", force=True)
            mock_pool.globalInstance().start.assert_not_called()

    def test_already_loaded_study_is_not_refetched(self, dialog):
        dialog._series_loaded.add("study-uid")
        with patch("echo_personal_tool.presentation.orthanc_study_dialog.QThreadPool") as mock_pool:
            dialog._prefetch_series("study-uid", force=True)
            mock_pool.globalInstance().start.assert_not_called()

    def test_populates_series_rows(self, dialog):
        dialog._on_studies_loaded([_study(uid="study-uid")], None)
        dialog._select_study_row("study-uid")
        dialog._on_series_loaded(("study-uid", _series("study-uid", 2), None))
        assert dialog._series_list.topLevelItemCount() == 2
        first = dialog._series_list.topLevelItem(0).data(0, ROLE_ROW)
        assert first.title.startswith("1.")
        assert first.series.modality == "US"
        assert dialog._series_list.topLevelItem(0).data(0, ROLE_UID) == "s1"

    def test_series_error_is_shown_in_header(self, dialog):
        dialog._on_studies_loaded([_study(uid="study-uid")], None)
        dialog._select_study_row("study-uid")
        dialog._on_series_loaded(("study-uid", [], "Connection timeout"))
        assert "Connection timeout" in dialog._series_header.text()
        assert dialog._series_list.topLevelItemCount() == 0

    def test_unknown_study_does_not_crash(self, dialog):
        dialog._on_series_loaded(("nonexistent-uid", [], None))
        assert "nonexistent-uid" not in dialog._series_loading

    def test_selecting_study_fills_right_pane(self, dialog):
        dialog._on_studies_loaded([_study(uid="u1"), _study(uid="u2")], None)
        dialog._on_series_loaded(("u2", _series("u2", 3), None))
        dialog._select_study_row("u2")
        dialog._populate_series("u2")
        assert dialog._series_list.topLevelItemCount() == 3
        assert "u2" == dialog._current_study_uid
        assert dialog._patient_label.isVisibleTo(dialog) or dialog._patient_label.text()

    def test_series_actions_hidden_without_series(self, dialog):
        dialog._on_studies_loaded([_study(uid="u1")], None)
        dialog._select_study_row("u1")
        dialog._on_series_loaded(("u1", [], None))
        assert not dialog._series_actions.isVisible()


class TestDeferredLoad:
    def test_load_waits_for_unknown_series_list(self, dialog):
        """Selecting a study whose series are unknown must fetch them first."""
        dialog._on_studies_loaded([_study(uid="u1")], None)
        dialog._selected_all.add("u1")
        with patch("echo_personal_tool.presentation.orthanc_study_dialog.QThreadPool") as mock_pool:
            dialog._on_load()
            mock_pool.globalInstance().start.assert_called()
        assert dialog._downloading is False
        assert dialog._pending_action == "load"

    def test_load_waits_for_inflight_series_query(self, dialog):
        """Regression: an in-flight series query is not "ready" yet."""
        dialog._on_studies_loaded([_study(uid="u1")], None)
        dialog._selected_all.add("u1")
        dialog._series_loading.add("u1")
        # The query is already in flight, so it must not be started twice.
        with patch("echo_personal_tool.presentation.orthanc_study_dialog.QThreadPool") as mock_pool:
            dialog._on_load()
            mock_pool.globalInstance().start.assert_not_called()
        assert dialog._downloading is False
        assert dialog._pending_action == "load"

    def test_pending_action_runs_when_series_arrive(self, dialog):
        dialog._on_studies_loaded([_study(uid="u1")], None)
        dialog._selected_all.add("u1")
        dialog._pending_action = "load"
        dialog._cache.create_session.return_value = "session-1"
        with patch("echo_personal_tool.presentation.orthanc_study_dialog.QThreadPool"):
            dialog._on_series_loaded(("u1", _series("u1", 2), None))
        assert dialog._downloading is True
        # The first (and only) study was already handed to the download worker.
        assert dialog._total_studies == 1
        assert dialog._worker is not None


class TestStaleStudyResults:
    def test_superseded_result_is_ignored(self, dialog):
        dialog._on_studies_loaded([_study(uid="new")], None)
        dialog._study_query_generation = 5
        dialog._on_studies_loaded_for(4, [_study(uid="old")], None)
        assert [s.study_uid for s in dialog._studies] == ["new"]

    def test_current_generation_is_applied(self, dialog):
        dialog._study_query_generation = 5
        dialog._on_studies_loaded_for(5, [_study(uid="fresh")], None)
        assert [s.study_uid for s in dialog._studies] == ["fresh"]


class TestPatientHistory:
    """Prior studies of the same patient ("compare with the last exam")."""

    def _prior(self, uid: str, date: str, *, pid: str = "12345", desc: str = "Echo") -> StudyInfo:
        return StudyInfo(
            study_uid=uid,
            patient_name="JOHN^DOE",
            patient_id=pid,
            study_date=date,
            study_description=desc,
        )

    def _show(self, dialog, studies: list[StudyInfo], *, pid: str = "12345") -> None:
        """Feed a history answer the way the query worker does."""
        dialog._history_patient = pid
        dialog._on_patient_history_loaded(pid, studies, None)

    def _chips(self, dialog) -> list[str]:
        layout = dialog._history_chips_layout
        return [
            layout.itemAt(i).widget().text() for i in range(layout.count()) if layout.itemAt(i).widget() is not None
        ]

    def test_prior_studies_are_rendered_as_chips(self, dialog):
        dialog._current_study_uid = "u1"
        self._show(
            dialog,
            [self._prior("u1", "20260901"), self._prior("u2", "20260614"), self._prior("u3", "20260312")],
        )
        assert dialog._history_label.text().endswith("(2)")
        assert len(self._chips(dialog)) == 2
        assert dialog._history_panel.isVisibleTo(dialog)
        # Newest first, the currently open study is never offered as "prior".
        assert self._chips(dialog)[0].startswith("14.06.2026")

    def test_other_patients_are_filtered_out(self, dialog):
        """A server that ignores the PatientID filter must not leak rows."""
        dialog._current_study_uid = "u1"
        self._show(dialog, [self._prior("u2", "20260614"), self._prior("u9", "20260614", pid="999")])
        assert len(self._chips(dialog)) == 1

    def test_strip_is_hidden_when_the_patient_is_unknown(self, dialog):
        dialog._current_study_uid = "u1"
        self._show(dialog, [self._prior("u2", "20260614")])
        assert dialog._history_panel.isVisibleTo(dialog)
        dialog._request_patient_history(
            StudyInfo(study_uid="u1", patient_name="", patient_id="", study_date="", study_description="")
        )
        assert not dialog._history_panel.isVisibleTo(dialog)
        assert self._chips(dialog) == []

    def test_strip_is_hidden_without_prior_studies(self, dialog):
        dialog._current_study_uid = "u1"
        self._show(dialog, [self._prior("u1", "20260901")])
        assert not dialog._history_panel.isVisibleTo(dialog)

    def test_strip_is_capped(self, dialog):
        dialog._current_study_uid = "u1"
        studies = [self._prior(f"u{i}", "20260614") for i in range(2, 20)]
        self._show(dialog, studies)
        assert len(self._chips(dialog)) == 6

    def test_cached_history_does_not_query_again(self, dialog):
        dialog._current_study_uid = "u1"
        self._show(dialog, [self._prior("u2", "20260614")])
        with patch("echo_personal_tool.presentation.orthanc_study_dialog.QThreadPool") as mock_pool:
            dialog._request_patient_history(
                StudyInfo(
                    study_uid="u1",
                    patient_name="JOHN^DOE",
                    patient_id="12345",
                    study_date="20260901",
                    study_description="Echo",
                )
            )
            mock_pool.globalInstance().start.assert_not_called()
        assert len(self._chips(dialog)) == 1

    def test_new_result_set_clears_the_strip(self, dialog):
        dialog._current_study_uid = "u1"
        self._show(dialog, [self._prior("u2", "20260614")])
        dialog._on_studies_loaded([_study(uid="u1")], None)
        assert not dialog._history_panel.isVisibleTo(dialog)
        assert dialog._history_patient == ""

    def test_chip_click_ticks_the_study(self, dialog):
        dialog._current_study_uid = "u1"
        self._show(dialog, [self._prior("u2", "20260614")])
        dialog._history_chips_layout.itemAt(0).widget().click()
        assert "u2" in dialog._selected_all
        assert "14.06.2026" in dialog._status_label.text()

    def test_chip_click_selects_a_listed_study(self, dialog):
        dialog._on_studies_loaded([_study(uid="u1"), _study(uid="u2", date="20260614")], None)
        dialog._select_study_row("u1")
        self._show(dialog, [self._prior("u2", "20260614")])
        dialog._history_chips_layout.itemAt(0).widget().click()
        assert dialog._current_study_uid == "u2"
        assert "u2" in dialog._selected_all

    def test_chip_click_ignores_unknown_uids(self, dialog):
        dialog._current_study_uid = "u1"
        self._show(dialog, [self._prior("u2", "20260614")])
        dialog._on_history_chip_clicked("nope")
        assert "nope" not in dialog._selected_all  # a stale chip must not create a selection

    def test_header_counts_studies_ticked_outside_the_list(self, dialog):
        dialog._on_studies_loaded([_study(uid="u1")], None)
        dialog._current_study_uid = "u1"
        self._show(dialog, [self._prior("u2", "20260614")])
        dialog._history_chips_layout.itemAt(0).widget().click()
        assert dialog._studies_selected_off_list() == 1
        assert "вне списка" in dialog._studies_header.text()

    def test_header_has_no_hint_when_every_selection_is_listed(self, dialog):
        dialog._on_studies_loaded([_study(uid="u1")], None)
        dialog._set_study_selected("u1", True)
        assert dialog._studies_selected_off_list() == 0
        assert "вне списка" not in dialog._studies_header.text()

    def test_history_query_asks_the_server_by_patient_id(self, dialog):
        with patch("echo_personal_tool.presentation.orthanc_study_dialog.QThreadPool") as mock_pool:
            dialog._request_patient_history(
                StudyInfo(
                    study_uid="u1",
                    patient_name="JOHN^DOE",
                    patient_id="12345",
                    study_date="20260901",
                    study_description="Echo",
                )
            )
            mock_pool.globalInstance().start.assert_called()
        assert dialog._history_patient == "12345"


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
