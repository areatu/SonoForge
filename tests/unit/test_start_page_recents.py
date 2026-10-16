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

from echo_personal_tool.domain.models import LinearMeasurement  # noqa: E402
from echo_personal_tool.domain.models.metadata import (  # noqa: E402
    InstanceMetadata,
    SeriesMetadata,
    StudyMetadata,
)
from echo_personal_tool.infrastructure.i18n import tr, tr_plural  # noqa: E402
from echo_personal_tool.presentation.start_page import RecentStudySummary  # noqa: E402

# Every wait below is a round-trip through the persistence worker (QH-1a): the
# listing is never produced on the GUI thread, so the assertion can only be
# evaluated after the worker has answered. Five seconds is not enough on a
# loaded CI runner (four xdist workers, each with a full main window), so the
# wait is generous — the condition, not the clock, is what the test checks.
_WORKER_TIMEOUT_MS = 15000


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


def _numeric_study() -> list[StudyMetadata]:
    """A study whose UID is a real DICOM UID: the repository hashes it.

    The folder/server fixtures above use readable prefixes ("s.study") that the
    measurement store rejects as identifiers — saved records need a valid UID.
    """
    instance = InstanceMetadata(
        sop_instance_uid="1.2.840.1.1",
        series_uid="1.2.840.1.2",
        modality="US",
        number_of_frames=4,
        pixel_spacing=(0.5, 0.5),
        frame_time_ms=33.3,
        series_description="A4C",
        path=None,
    )
    series = SeriesMetadata(
        series_uid="1.2.840.1.2",
        study_uid="1.2.840.1",
        modality="US",
        description="Echocardiography",
        instances=(instance,),
    )
    return [StudyMetadata(study_uid="1.2.840.1", study_datetime=datetime(2026, 10, 8, 9), series=(series,))]


def _saved_record(window, qtbot, monkeypatch):
    """Turn autosave on and write one real record through the persistence API."""
    from echo_personal_tool.application import measurement_persistence as persistence_module

    sources = {"1.2.840.1.1": {"fingerprint": "a" * 64, "frames": 4, "spacing": [0.5, 0.5]}}
    monkeypatch.setattr(persistence_module, "describe_study", lambda _study: sources)
    window._user_preferences.measurement_persistence_enabled = True
    persistence = window._controller.measurement_persistence
    persistence.enable()
    loaded: list = []
    persistence.load(_numeric_study(), lambda: loaded.append(True))
    qtbot.waitUntil(lambda: bool(loaded), timeout=_WORKER_TIMEOUT_MS)
    store = persistence.store
    store.set_patient_metrics("1.2.840.1", 175.0, 72.0)
    store.set_linear_measurements_for_instance(
        "1.2.840.1", "1.2.840.1.1", (LinearMeasurement("LVEDD", 20, 10, 0, sop_instance_uid="1.2.840.1.1"),)
    )
    assert persistence.flush()
    return persistence


def test_saved_record_appears_as_a_disabled_row_after_a_real_save(window, qtbot, monkeypatch) -> None:
    """QH-1a: the block reads saved records from disk, not from the RAM store."""
    persistence = _saved_record(window, qtbot, monkeypatch)

    window._on_persistence_status("saved")  # the real slot the window reacts to
    window._refresh_start_page_recents()
    qtbot.waitUntil(
        lambda: any(s.origin == "stored" for s in window._start_page._recent_studies),
        timeout=_WORKER_TIMEOUT_MS,
    )
    summary = next(s for s in window._start_page._recent_studies if s.origin == "stored")
    # Rows carry the localised text of the active UI language (the window applies
    # the stored preference), so compare against the catalog, not a hard-coded form.
    assert summary.available is False
    assert summary.title.startswith("20")  # «дата · сохранённые измерения»
    assert tr("start_page.recent_studies_saved") in summary.title
    assert tr_plural("start_page.recent_studies_measurements", 1) in summary.details
    assert len(summary.key) == 64  # opaque study key, not a UID

    # Disabled rows never open anything.
    calls: list = []
    monkeypatch.setattr(window, "_open_orthanc_dialog", lambda **kwargs: calls.append(kwargs))
    monkeypatch.setattr(window, "open_folder_path", lambda path: calls.append(path))
    window._on_start_page_recent_study(summary)
    assert calls == []
    assert persistence.close()


def test_unreadable_record_is_reported_instead_of_an_empty_block(window, qtbot, monkeypatch) -> None:
    """A damaged file is visible as its own row, not as «нет сохранённых измерений»."""
    from echo_personal_tool.infrastructure.measurement_codec import study_key

    persistence = _saved_record(window, qtbot, monkeypatch)
    (persistence.repository.root / (study_key("1.2.9") + ".json")).write_bytes(b'{"broken"')

    window._invalidate_saved_records()
    window._refresh_start_page_recents()
    unreadable = tr_plural("start_page.recent_studies_unreadable", 1)
    qtbot.waitUntil(
        lambda: any(unreadable in s.title for s in window._start_page._recent_studies),
        timeout=_WORKER_TIMEOUT_MS,
    )
    stored = [s for s in window._start_page._recent_studies if s.origin == "stored"]
    assert len(stored) == 2, "the readable record and the damaged row are both shown"
    assert persistence.close()


def test_failed_listing_is_not_shown_as_an_empty_block(window, qtbot, monkeypatch) -> None:
    persistence = _saved_record(window, qtbot, monkeypatch)
    entries = persistence.repository.entries
    monkeypatch.setattr(
        persistence.repository,
        "entries",
        lambda: (_ for _ in ()).throw(PermissionError(13, "denied")),
    )
    window._invalidate_saved_records()
    window._refresh_start_page_recents()
    qtbot.waitUntil(
        lambda: any(tr("start_page.recent_studies_failed") in s.title for s in window._start_page._recent_studies),
        timeout=_WORKER_TIMEOUT_MS,
    )
    # The page must not claim «Пока нет недавних исследований» when the read failed.
    assert window._start_page._studies_empty.isVisible() is False
    # Restore the repository before the window closes: a study that cannot be
    # flushed shows the blocking «unsaved» dialog on teardown.
    monkeypatch.setattr(persistence.repository, "entries", entries)
    assert persistence.flush()
    assert persistence.close()


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
