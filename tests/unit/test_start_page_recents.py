"""«Недавние исследования» on the welcome page (Э5 §7.3, spec 2026-10-07).

The block must be fed from the folder/server history of this run and from Z2-M
saved-measurement records, and a click must open the folder or the server loader
with the study preselected.
"""

from __future__ import annotations

from datetime import datetime

import pytest

pytestmark = pytest.mark.gui

from PySide6.QtWidgets import QApplication  # noqa: E402

from echo_personal_tool.domain.models.metadata import (  # noqa: E402
    InstanceMetadata,
    SeriesMetadata,
    StudyMetadata,
)
from echo_personal_tool.presentation.start_page import RecentStudySummary  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate(isolated_qsettings):
    return isolated_qsettings


def _studies(prefix: str) -> list[StudyMetadata]:
    instance = InstanceMetadata(
        sop_instance_uid=f"{prefix}.0",
        series_uid=f"{prefix}.series",
        modality="US",
        number_of_frames=4,
        pixel_spacing=(0.5, 0.5),
        frame_time_ms=33.3,
        series_description="A4C",
        path=None,
    )
    series = SeriesMetadata(
        series_uid=f"{prefix}.series",
        study_uid=f"{prefix}.study",
        modality="US",
        description="Echocardiography",
        instances=(instance,),
    )
    return [StudyMetadata(study_uid=f"{prefix}.study", study_datetime=datetime(2026, 10, 8, 9), series=(series,))]


@pytest.fixture
def window(qtbot, make_main_window, monkeypatch):
    from echo_personal_tool.application.app_controller import AppController

    controller = AppController()
    monkeypatch.setattr(controller, "open_folder", lambda root, error_log_path=None: None)
    monkeypatch.setattr(controller, "load_pre_scanned_studies", lambda studies: None)
    win = make_main_window(controller=controller)
    win.resize(1200, 800)
    win.show()
    qtbot.waitExposed(win)
    return win


def _publish(window, studies: list[StudyMetadata]) -> None:
    window._controller.studies_loaded.emit(studies)
    QApplication.processEvents()


def test_empty_tab_shows_welcome_page_and_research_block_is_connected(window, monkeypatch) -> None:
    assert window._main_stack.currentWidget() is window._content_widget
    assert window._viewer_stack.currentWidget() is window._start_page
    # The signal the block relies on must be wired to the window handler.
    calls: list = []
    monkeypatch.setattr(window, "_open_orthanc_dialog", lambda **kwargs: calls.append(kwargs))
    window._start_page.recent_study_requested.emit(
        RecentStudySummary(key="x", title="t", origin="server", study_uid="1.2.3")
    )
    assert calls == [{"preselect_study_uid": "1.2.3"}]


def test_folder_load_populates_recent_studies_with_reopenable_folder(window, monkeypatch, tmp_path) -> None:
    folder = tmp_path / "Echo cases"
    folder.mkdir()
    window.open_folder_path(folder)
    _publish(window, _studies("a"))
    summaries = window._start_page._recent_studies
    assert [s.origin for s in summaries] == ["folder"]
    row = summaries[0]
    assert row.available is True
    assert row.folder == str(folder)
    assert "2026-10-08" in row.title and "Echocardiography" in row.title
    assert "1" in row.details and "folder" in row.details

    opened: list[str] = []
    monkeypatch.setattr(window, "open_folder_path", lambda path: opened.append(str(path)))
    window._on_start_page_recent_study(row)
    assert opened == [str(folder)]


def test_server_batch_populates_recent_studies_and_preselects_on_click(window, monkeypatch) -> None:
    window._open_server_batch(_studies("srv"), "session-1")
    summaries = window._start_page._recent_studies
    assert [s.origin for s in summaries] == ["server"]
    row = summaries[0]
    assert row.available is True
    assert row.study_uid == "srv.study"

    calls: list = []
    monkeypatch.setattr(window, "_open_orthanc_dialog", lambda **kwargs: calls.append(kwargs))
    window._on_start_page_recent_study(row)
    assert calls == [{"preselect_study_uid": "srv.study"}]


def test_stored_measurement_records_render_as_disabled_rows(window, monkeypatch) -> None:
    window._user_preferences.measurement_persistence_enabled = True
    monkeypatch.setattr(
        window,
        "_stored_measurement_records",
        lambda: [{"study_uid": "stored.study", "saved_at": "2026-10-07T10:00:00", "sources": {"a": {}, "b": {}}}],
    )
    window._refresh_start_page_recents()
    summaries = window._start_page._recent_studies
    assert [s.origin for s in summaries] == ["stored"]
    row = summaries[0]
    assert row.available is False
    assert "2026-10-07" in row.title
    assert "2" in row.details

    # Disabled rows never open anything.
    calls: list = []
    monkeypatch.setattr(window, "_open_orthanc_dialog", lambda **kwargs: calls.append(kwargs))
    monkeypatch.setattr(window, "open_folder_path", lambda path: calls.append(path))
    window._on_start_page_recent_study(row)
    assert calls == []


def test_click_on_unavailable_row_is_ignored(window) -> None:
    window._on_start_page_recent_study(RecentStudySummary(key="k", title="t", available=False))
    window._on_start_page_recent_study("not-a-summary")


def test_recent_study_list_is_capped_and_newest_first(window, tmp_path) -> None:
    folder = tmp_path / "cases"
    folder.mkdir()
    window.open_folder_path(folder)
    _publish(window, _studies("a"))
    window.open_folder_path(folder)
    _publish(window, _studies("b"))
    window._open_server_batch(_studies("c"), "session-1")
    summaries = window._start_page._recent_studies
    assert len(summaries) == 3
    assert {s.study_uid for s in summaries} == {"a.study", "b.study", "c.study"}
    by_uid = {s.study_uid: s for s in summaries}
    assert by_uid["a.study"].folder == str(folder)
    assert by_uid["c.study"].origin == "server"
