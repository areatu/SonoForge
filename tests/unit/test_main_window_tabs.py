"""Tab strip, switching and close rules in MainWindow (Э9, PR-B).

The controller's loaders are replaced by recorders: the tests drive the window
the way the controller does (``studies_loaded``), without DICOM files.
"""

from __future__ import annotations

from datetime import datetime

import pytest

pytestmark = pytest.mark.gui

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from echo_personal_tool.application.tab_session import (  # noqa: E402
    MAX_OPEN_TABS,
    TAB_ORIGIN_EMPTY,
    TAB_ORIGIN_FOLDER,
    TAB_ORIGIN_SERVER,
)
from echo_personal_tool.domain.models.metadata import (  # noqa: E402
    InstanceMetadata,
    SeriesMetadata,
    StudyMetadata,
)


@pytest.fixture(autouse=True)
def _isolate(isolated_qsettings):
    return isolated_qsettings


def _instance(uid: str) -> InstanceMetadata:
    return InstanceMetadata(
        sop_instance_uid=uid,
        series_uid=f"{uid}.series",
        modality="US",
        number_of_frames=4,
        pixel_spacing=(0.5, 0.5),
        frame_time_ms=33.3,
        series_description="A4C",
        path=None,
    )


def _studies(prefix: str, instances: int = 2) -> list[StudyMetadata]:
    series = SeriesMetadata(
        series_uid=f"{prefix}.series",
        study_uid=f"{prefix}.study",
        modality="US",
        description="A4C",
        instances=tuple(_instance(f"{prefix}.{i}") for i in range(instances)),
    )
    return [StudyMetadata(study_uid=f"{prefix}.study", study_datetime=datetime(2026, 10, 1, 9), series=(series,))]


@pytest.fixture
def window(qtbot, make_main_window, monkeypatch):
    from echo_personal_tool.application.app_controller import AppController

    controller = AppController()
    calls: dict[str, list] = {"folder": [], "studies": []}
    monkeypatch.setattr(controller, "open_folder", lambda root, error_log_path=None: calls["folder"].append(root))
    monkeypatch.setattr(controller, "load_pre_scanned_studies", lambda studies: calls["studies"].append(studies))
    win = make_main_window(controller=controller)
    win.resize(1200, 800)
    win.show()
    qtbot.waitExposed(win)
    cleared: list[str] = []
    monkeypatch.setattr(win._orthanc_cache, "clear_session", cleared.append)
    win._test_calls = calls  # type: ignore[attr-defined]
    win._test_cleared = cleared  # type: ignore[attr-defined]
    return win


def _publish(window, studies: list[StudyMetadata]) -> None:
    """What the controller does when a study set is ready."""
    window._controller.studies_loaded.emit(studies)
    QApplication.processEvents()


def _open_and_publish(window, root: str, prefix: str) -> str:
    window.open_folder_path(root)  # type: ignore[arg-type]
    tab_id = window._tabs.active_tab_id
    _publish(window, _studies(prefix))
    return tab_id


def test_window_starts_with_one_empty_tab_and_placeholder(window) -> None:
    assert len(window._tabs) == 1
    assert window._tabs.active is not None and window._tabs.active.origin == TAB_ORIGIN_EMPTY
    assert window._tab_strip.tab_count() == 1
    assert window._main_stack.currentWidget() is window._empty_tab_page


def test_first_load_fills_the_empty_tab_instead_of_adding_one(window) -> None:
    first = window._tabs.active_tab_id
    window.open_folder_path("/data/A")  # type: ignore[arg-type]
    assert len(window._tabs) == 1
    assert window._tabs.active_tab_id == first
    assert window._tabs.active.origin == TAB_ORIGIN_FOLDER
    assert window._test_calls["folder"] == ["/data/A"]
    assert window._tab_loading_id == first
    _publish(window, _studies("a"))
    assert window._tab_loading_id is None
    assert window._main_stack.currentWidget() is window._content_widget
    assert window._tab_strip.caption(first).endswith("US · A4C")


def test_second_folder_opens_in_its_own_tab_and_parks_the_first(window) -> None:
    a = _open_and_publish(window, "/data/A", "a")
    window.open_folder_path("/data/B")  # type: ignore[arg-type]
    b = window._tabs.active_tab_id
    assert b != a
    assert len(window._tabs) == 2
    assert window._tab_loading_id == b
    assert window._tabs.get(a).studies, "the first tab keeps its studies"


def test_switching_back_reloads_the_tab_studies_without_rescanning(window) -> None:
    a = _open_and_publish(window, "/data/A", "a")
    window.open_folder_path("/data/B")  # type: ignore[arg-type]
    _publish(window, _studies("b"))
    window._on_tab_selected(a)
    assert window._tabs.active_tab_id == a
    assert window._test_calls["folder"] == ["/data/A", "/data/B"], "no rescan on switch"
    assert window._test_calls["studies"][-1] == window._tabs.get(a).studies
    assert window._tab_loading_id == a
    _publish(window, window._tabs.get(a).studies)
    assert window._tab_loading_id is None


def test_switch_is_refused_while_a_study_is_loading(window) -> None:
    a = _open_and_publish(window, "/data/A", "a")
    window.open_folder_path("/data/B")  # type: ignore[arg-type]
    b = window._tabs.active_tab_id
    assert window._tab_loading_id == b
    assert window._switch_to_tab(a) is False
    assert window._tabs.active_tab_id == b
    assert window._tab_strip.current_tab_id() == b


def test_switch_is_refused_when_measurements_cannot_be_flushed(window, monkeypatch) -> None:
    a = _open_and_publish(window, "/data/A", "a")
    window.open_folder_path("/data/B")  # type: ignore[arg-type]
    _publish(window, _studies("b"))
    monkeypatch.setattr(window._controller.measurement_persistence, "flush", lambda: False)
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    before = len(window._test_calls["studies"])
    window._on_tab_selected(a)
    assert len(window._test_calls["studies"]) == before
    assert window._tabs.active_tab_id != a


def test_new_plus_tab_is_empty_and_shows_the_placeholder(window) -> None:
    _open_and_publish(window, "/data/A", "a")
    window._on_new_tab_requested()
    assert len(window._tabs) == 2
    assert window._tabs.active.origin == TAB_ORIGIN_EMPTY
    assert window._main_stack.currentWidget() is window._empty_tab_page
    assert window._test_calls["studies"][-1] == []


def test_closing_the_active_tab_loads_its_neighbour(window) -> None:
    a = _open_and_publish(window, "/data/A", "a")
    window.open_folder_path("/data/B")  # type: ignore[arg-type]
    b = window._tabs.active_tab_id
    _publish(window, _studies("b"))
    window._on_tab_selected(a)
    _publish(window, window._tabs.get(a).studies)
    window._on_tab_close_requested(a)
    assert window._tabs.active_tab_id == b
    assert window._test_calls["studies"][-1] == window._tabs.get(b).studies


def test_closing_the_last_tab_leaves_a_fresh_empty_tab(window) -> None:
    only = window._tabs.active_tab_id
    _open_and_publish(window, "/data/A", "a")
    window._on_tab_close_requested(window._tabs.active_tab_id)
    assert len(window._tabs) == 1
    assert window._tabs.active_tab_id != only
    assert window._tabs.active.origin == TAB_ORIGIN_EMPTY


def test_closing_a_server_tab_purges_its_pacs_cache_once(window) -> None:
    window._acquire_tab_for_load(TAB_ORIGIN_SERVER, "", "z3-A")
    _publish(window, _studies("srv"))
    server_tab = window._tabs.tabs[0].tab_id
    window._on_new_tab_requested()
    _publish(window, [])  # the controller publishes the empty set for the « + » tab
    window._on_tab_close_requested(server_tab)
    assert window._test_cleared == ["z3-A"]


def test_pacs_cache_of_an_open_tab_is_protected(window) -> None:
    window._acquire_tab_for_load(TAB_ORIGIN_SERVER, "", "z3-A")
    _publish(window, _studies("srv"))
    assert "z3-A" in window._active_orthanc_cache_sessions()


def test_limit_asks_and_declines_by_default(window, monkeypatch) -> None:
    for i in range(MAX_OPEN_TABS):  # the first one fills the empty start tab
        window.open_folder_path(f"/data/{i}")  # type: ignore[arg-type]
        _publish(window, _studies(f"s{i}"))
    assert window._tabs.is_full
    asked: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *a, **k: asked.append(a[2]) or QMessageBox.StandardButton.No),
    )
    window.open_folder_path("/data/extra")  # type: ignore[arg-type]
    assert asked, "the limit must be a question, not a silent close"
    assert len(window._tabs) == MAX_OPEN_TABS
    assert "/data/extra" not in window._test_calls["folder"]


def test_limit_yes_closes_the_oldest_inactive_tab(window, monkeypatch) -> None:
    first = _open_and_publish(window, "/data/first", "first")
    for i in range(MAX_OPEN_TABS - 1):
        window._tabs.open_tab(origin=TAB_ORIGIN_FOLDER, root=f"/x/{i}", studies=_studies(f"x{i}"))
    assert window._tabs.is_full
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    window.open_folder_path("/data/new")  # type: ignore[arg-type]
    assert first not in window._tabs
    assert len(window._tabs) == MAX_OPEN_TABS


def test_ctrl_tab_cycles_and_wraps(window) -> None:
    a = _open_and_publish(window, "/data/A", "a")
    window.open_folder_path("/data/B")  # type: ignore[arg-type]
    b = window._tabs.active_tab_id
    _publish(window, _studies("b"))
    window._cycle_tab(1)
    assert window._tabs.active_tab_id == a
    _publish(window, window._tabs.active.studies)
    window._cycle_tab(-1)
    assert window._tabs.active_tab_id == b


def test_restores_the_selected_instance_of_the_tab(window) -> None:
    window.open_folder_path("/data/A")  # type: ignore[arg-type]
    studies = _studies("a", instances=3)
    window._tabs.update_viewer(window._tabs.active_tab_id, active_instance_uid="a.2", frame_index=2)
    tab_id = window._tabs.active_tab_id
    window._restore_target = (tab_id, "a.2", 2)
    opened: list[str] = []
    window._on_instance_selected = lambda inst: opened.append(inst.sop_instance_uid)  # type: ignore[method-assign]
    window._tab_loading_id = tab_id
    window._controller.studies_loaded.emit(studies)
    QApplication.processEvents()
    assert opened == ["a.2"]


def test_tab_strip_signals_are_not_emitted_by_programmatic_rebuilds(window) -> None:
    selected: list[str] = []
    window._tab_strip.tab_selected.connect(selected.append)
    _open_and_publish(window, "/data/A", "a")
    window.open_folder_path("/data/B")  # type: ignore[arg-type]
    _publish(window, _studies("b"))
    QApplication.processEvents()
    assert selected == []


# ----- PR-C: a PACS download batch opens one tab per study ----------------------


def _batch(*prefixes: str) -> list[StudyMetadata]:
    out: list[StudyMetadata] = []
    for prefix in prefixes:
        out.extend(_studies(prefix))
    return out


def test_batch_opens_each_study_in_its_own_tab(window) -> None:
    window._open_server_batch(_batch("a", "b", "c"), "sess-1")
    tabs = window._tabs.tabs
    assert len(tabs) == 3
    assert all(t.origin == TAB_ORIGIN_SERVER for t in tabs)
    assert all(t.cache_session_id == "sess-1" for t in tabs)
    # only the first study loads now; the others wait in their tabs
    assert window._test_calls["studies"][-1] == _studies("a")
    assert window._tab_loading_id == tabs[0].tab_id
    assert window._tabs.active_tab_id == tabs[0].tab_id
    assert [len(t.studies) for t in tabs[1:]] == [1, 1]
    _publish(window, _studies("a"))
    assert [len(t.studies) for t in tabs] == [1, 1, 1]


def test_batch_is_recorded_in_the_download_history(window) -> None:
    window._open_server_batch(_batch("a", "b"), "sess-1")
    assert [r.study_uid for r in window._download_history.records()] == ["b.study", "a.study"]


def test_batch_cache_is_purged_only_after_the_last_tab_of_the_batch_closes(window) -> None:
    window._open_server_batch(_batch("a", "b", "c"), "sess-1")
    a, b, c = (t.tab_id for t in window._tabs.tabs)
    _publish(window, _studies("a"))
    window._on_tab_close_requested(b)
    window._on_tab_close_requested(c)
    assert window._test_cleared == []
    window._on_tab_close_requested(a)
    _publish(window, [])
    assert window._test_cleared == ["sess-1"]


def test_batch_declined_room_question_opens_only_what_fits(window, monkeypatch) -> None:
    for prefix in ("f1", "f2", "f3", "f4", "f5", "f6", "f7"):
        window._tabs.open_tab(origin=TAB_ORIGIN_FOLDER, root=f"/{prefix}", studies=_studies(prefix), activate=False)
    assert window._tabs.is_full
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))
    window._open_server_batch(_batch("a", "b", "c"), "sess-1")
    assert len(window._tabs) == MAX_OPEN_TABS
    assert window._test_calls["studies"][-1] == _studies("a")
    assert [t.cache_session_id for t in window._tabs.tabs].count("sess-1") == 1


def test_batch_accepted_room_question_closes_oldest_inactive_tabs(window, monkeypatch) -> None:
    for prefix in ("f1", "f2", "f3", "f4", "f5", "f6", "f7"):
        window._tabs.open_tab(origin=TAB_ORIGIN_FOLDER, root=f"/{prefix}", studies=_studies(prefix), activate=False)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    window._open_server_batch(_batch("a", "b", "c"), "sess-1")
    assert len(window._tabs) == MAX_OPEN_TABS
    shared = [t for t in window._tabs.tabs if t.cache_session_id == "sess-1"]
    assert len(shared) == 3
    assert {t.studies[0].study_uid for t in shared} == {"a.study", "b.study", "c.study"}
