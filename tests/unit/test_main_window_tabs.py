"""Tab strip, switching and close rules in MainWindow (Э9, PR-B).

The controller's loaders are replaced by recorders: the tests drive the window
the way the controller does (``studies_loaded``), without DICOM files.
"""

from __future__ import annotations

from datetime import datetime

import pytest

pytestmark = pytest.mark.gui

from PySide6.QtWidgets import QApplication, QMessageBox, QWidget  # noqa: E402

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


def test_strip_is_below_system_bar_without_plus_button(window) -> None:
    assert window._root_layout.indexOf(window._system_bar) == 0
    assert window._root_layout.indexOf(window._tab_strip) == 1
    assert window._root_layout.indexOf(window._main_stack) == 2
    assert window.findChild(QWidget, "tabStripNew") is None
    assert not hasattr(window._tab_strip, "new_button")


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
    _open_and_publish(window, "/data/local", "local")
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
    # the reused initial empty tab gets its studies when the controller publishes them
    assert [t.studies[0].study_uid for t in shared if t.studies] == ["b.study", "c.study"]


# ----- pre-release step 2: optional tabs ---------------------------------------


def _apply_tabs(window, enabled: bool) -> None:
    from dataclasses import replace

    from echo_personal_tool.infrastructure.user_preferences import save_user_preferences

    preferences = replace(window._user_preferences, tabs_enabled=enabled)
    # The settings dialog writes first, then invokes on_apply.
    save_user_preferences(preferences)
    window._apply_user_preferences(preferences)


# A font change repolishes *every* widget owned by QApplication, including
# hidden dialogs left by earlier tests. Exercise the real settings path in a
# fresh Qt process, as test_ui_scale does, instead of measuring suite history.
_TAB_HEIGHT_PROBE = r"""
import json
import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, QSettings
from PySide6.QtWidgets import QApplication

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.infrastructure.user_preferences import UserPreferences
from echo_personal_tool.presentation.main_window import MainWindow
from echo_personal_tool.presentation.ui_metrics import control_height

root = Path(sys.argv[2])
app = QApplication([])
settings = QSettings(str(root / "settings.ini"), QSettings.Format.IniFormat)
with (
    patch("echo_personal_tool.infrastructure.user_preferences._settings_store", lambda: settings),
    patch("echo_personal_tool.infrastructure.paths.measurements_dir", lambda: root / "measurements"),
    patch("echo_personal_tool.infrastructure.profile.orthanc_cache_root", lambda: root / "cache"),
):
    window = MainWindow(controller=AppController(), user_preferences=UserPreferences())
    try:
        window.resize(1200, 800)
        window.show()
        app.processEvents()
        window._apply_user_preferences(replace(window._user_preferences, ui_font_size=int(sys.argv[1])))
        app.processEvents()
        strip = window._tab_strip
        print(json.dumps({
            "expected": control_height(window._system_bar._btn_caliper),
            "caliper_font_px": window._system_bar._btn_caliper.font().pixelSize(),
            "strip": strip.height(),
            "bar": strip._bar.height(),
            "tab": strip._bar.tabRect(0).height(),
            "margin_top": strip.layout().contentsMargins().top(),
        }))
    finally:
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
"""


@pytest.mark.parametrize("font_size", [12, 18])
def test_strip_height_tracks_caliper_control(tmp_path, font_size) -> None:
    import json
    import os
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-c", _TAB_HEIGHT_PROBE, str(font_size), str(tmp_path)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["strip"] == report["bar"] == report["tab"] == report["expected"]
    assert report["margin_top"] == 0
    assert report["caliper_font_px"] == max(font_size - 1, 11)


def test_disabled_tabs_replace_folder_without_growing_count(window) -> None:
    first = _open_and_publish(window, "/data/A", "a")
    _apply_tabs(window, False)
    assert window._tab_strip.isHidden()
    window._tabs.update_viewer(first, active_instance_uid="a.1", frame_index=3, viewer_state={"old": True})
    window.open_folder_path("/data/B")
    assert window._tabs.active_tab_id == first
    assert len(window._tabs) == window._tab_strip.tab_count() == 1
    assert window._tabs.active.root == "/data/B"
    assert window._tabs.active.active_instance_uid == ""
    assert window._tabs.active.viewer_state_json == "{}"
    _publish(window, _studies("b"))
    assert window._tabs.active.studies == _studies("b")
    _apply_tabs(window, True)
    assert not window._tab_strip.isHidden()
    window.open_folder_path("/data/C")
    assert len(window._tabs) == 2


def test_disabled_tabs_load_entire_pacs_batch_even_over_tab_limit(window) -> None:
    _open_and_publish(window, "/data/A", "a")
    _apply_tabs(window, False)
    batch = _batch(*(f"s{i}" for i in range(MAX_OPEN_TABS + 2)))
    assert window._open_server_batch(batch, "batch-cache")
    assert len(window._tabs) == 1
    assert window._test_calls["studies"][-1] == batch
    _publish(window, batch)
    assert window._tabs.active.studies == batch
    assert window._tabs.active.cache_session_id == "batch-cache"


def test_single_tab_replacement_flush_failure_keeps_source(window, monkeypatch) -> None:
    first = _open_and_publish(window, "/data/A", "a")
    _apply_tabs(window, False)
    monkeypatch.setattr(window, "_tab_flush_or_block", lambda: False)
    window.open_folder_path("/data/B")
    assert window._tabs.active_tab_id == first
    assert window._tabs.active.root == "/data/A"
    assert window._test_calls["folder"] == ["/data/A"]


def test_single_tab_replacement_defers_pacs_purge_until_old_files_are_released(window, monkeypatch) -> None:
    _apply_tabs(window, False)
    assert window._open_server_batch(_studies("srv"), "old-cache")
    _publish(window, _studies("srv"))
    window.open_folder_path("/data/local")
    assert window._test_cleared == []
    monkeypatch.setattr(window, "_active_orthanc_cache_sessions", lambda: {"old-cache"})
    _publish(window, _studies("local"))
    assert window._test_cleared == []
    monkeypatch.setattr(window, "_active_orthanc_cache_sessions", lambda: set())
    window._process_pending_cache_purges()
    assert window._test_cleared == ["old-cache"]


def test_disabled_tab_shortcuts_do_nothing(window, qtbot) -> None:
    from PySide6.QtCore import Qt

    first = _open_and_publish(window, "/data/A", "a")
    _apply_tabs(window, False)
    for key, modifiers in [
        (Qt.Key.Key_W, Qt.KeyboardModifier.ControlModifier),
        (Qt.Key.Key_Tab, Qt.KeyboardModifier.ControlModifier),
        (Qt.Key.Key_Tab, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier),
    ]:
        qtbot.keyClick(window, key, modifiers)
    window._cycle_tab(1)
    window._cycle_tab(-1)
    window._close_active_tab_shortcut()
    assert window._tabs.active_tab_id == first
    assert window._tabs.active.studies == _studies("a")
    assert len(window._tabs) == 1


def test_disable_keeps_first_and_closes_others_without_empty_measurement_prompt(window, monkeypatch) -> None:
    first = _open_and_publish(window, "/data/A", "a")
    window._open_server_batch(_batch("b", "c"), "extra-cache")
    _publish(window, _studies("b"))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: pytest.fail("No measurements: no prompt"))
    _apply_tabs(window, False)
    assert len(window._tabs) == 1
    assert window._tabs.active_tab_id == first
    assert window._test_calls["studies"][-1] == _studies("a")
    _publish(window, _studies("a"))
    assert window._test_cleared == ["extra-cache"]


def test_disable_keeps_shared_cache_of_first_tab(window) -> None:
    window._open_server_batch(_batch("a", "b", "c"), "shared-cache")
    first = window._tabs.active_tab_id
    _publish(window, _studies("a"))
    _apply_tabs(window, False)
    assert window._tabs.active_tab_id == first
    assert len(window._tabs) == 1
    assert window._test_cleared == []


@pytest.mark.parametrize("accept", [False, True])
def test_disable_confirms_once_for_active_and_parked_measurements(window, monkeypatch, accept) -> None:
    from echo_personal_tool.application.study_measurement_session import StudyMeasurementData
    from echo_personal_tool.domain.models import LinearMeasurement
    from echo_personal_tool.infrastructure.user_preferences import load_user_preferences

    first = _open_and_publish(window, "/data/A", "a")
    second = _open_and_publish(window, "/data/B", "b")
    store = window._controller.measurement_persistence.store
    store.restore("b.study", StudyMeasurementData(linear_measurements=(LinearMeasurement("LA", 60.0, 30.0),)))
    third = _open_and_publish(window, "/data/C", "c")
    assert window._tabs.get(second).has_measurements
    # The real controller clears the previous live store on each study load.
    store.clear()
    store.restore("c.study", StudyMeasurementData(linear_measurements=(LinearMeasurement("LA", 64.0, 32.0),)))
    asked = []

    def question(*args):
        asked.append(args)
        return QMessageBox.StandardButton.Yes if accept else QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", question)
    captions = [window._tab_caption(window._tabs.get(t)) for t in (second, third)]
    _apply_tabs(window, False)
    assert len(asked) == 1
    assert all(caption in asked[0][2] for caption in captions)
    assert asked[0][-1] == QMessageBox.StandardButton.No
    assert load_user_preferences().tabs_enabled is (not accept)
    assert window._user_preferences.tabs_enabled is (not accept)
    assert len(window._tabs) == (1 if accept else 3)
    assert window._tabs.active_tab_id == (first if accept else third)


def test_disable_detects_parked_measurements_with_empty_active_tab_data(window, monkeypatch) -> None:
    from echo_personal_tool.application.study_measurement_session import StudyMeasurementData
    from echo_personal_tool.domain.models import LinearMeasurement

    _open_and_publish(window, "/data/A", "a")
    _open_and_publish(window, "/data/B", "b")
    store = window._controller.measurement_persistence.store
    store.restore("b.study", StudyMeasurementData(linear_measurements=(LinearMeasurement("LA", 60.0, 30.0),)))
    _open_and_publish(window, "/data/C", "c")
    store.clear()
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *args: asked.append(args) or QMessageBox.StandardButton.No)
    _apply_tabs(window, False)
    assert len(asked) == 1
    assert len(window._tabs) == 3


@pytest.mark.parametrize("blocked", ["load", "flush"])
def test_disable_is_rolled_back_when_navigation_is_blocked(window, monkeypatch, blocked) -> None:
    from echo_personal_tool.infrastructure.user_preferences import load_user_preferences

    _open_and_publish(window, "/data/A", "a")
    window.open_folder_path("/data/B")
    if blocked == "flush":
        _publish(window, _studies("b"))
        monkeypatch.setattr(window, "_tab_flush_or_block", lambda: False)
    active = window._tabs.active_tab_id
    _apply_tabs(window, False)
    assert load_user_preferences().tabs_enabled
    assert window._user_preferences.tabs_enabled
    assert len(window._tabs) == 2
    assert window._tabs.active_tab_id == active
    assert not window._tab_strip.isHidden()


def test_disabled_strip_stays_hidden_when_fullscreen_chrome_returns(window) -> None:
    _apply_tabs(window, False)
    window._enter_fullscreen_kiosk()
    window._fullscreen_reveal_chrome(auto_hide=False)
    assert window._tab_strip.isHidden()
    window._exit_fullscreen_kiosk()
    assert window._tab_strip.isHidden()


def test_startup_with_tabs_disabled(qtbot, make_main_window) -> None:
    from echo_personal_tool.infrastructure.user_preferences import UserPreferences

    win = make_main_window(user_preferences=UserPreferences(tabs_enabled=False))
    assert win._tab_strip.isHidden()
    assert len(win._tabs) == 1


def test_disable_preserves_live_measurements_when_first_tab_is_already_active(window, monkeypatch) -> None:
    from echo_personal_tool.application.study_measurement_session import StudyMeasurementData
    from echo_personal_tool.domain.models import LinearMeasurement

    first = _open_and_publish(window, "/data/A", "a")
    window._tabs.open_tab(origin=TAB_ORIGIN_FOLDER, root="/data/B", studies=_studies("b"), activate=False)
    store = window._controller.measurement_persistence.store
    data = StudyMeasurementData(linear_measurements=(LinearMeasurement("LA", 60, 30),))
    store.restore("a.study", data)
    before = list(window._test_calls["studies"])
    monkeypatch.setattr(QMessageBox, "question", lambda *args: pytest.fail("The measured first tab is not closing"))
    _apply_tabs(window, False)
    assert window._tabs.active_tab_id == first
    assert len(window._tabs) == 1
    assert window._test_calls["studies"] == before
    assert store.get("a.study") == data


# ----- step 4: retain chrome while the study surface changes -------------------


def _two_loaded_tabs(window):
    first = _open_and_publish(window, "/data/A", "a")
    second = _open_and_publish(window, "/data/B", "b")
    return first, second


def test_switch_keeps_content_and_tools_visible_until_studies_arrive(window, monkeypatch):
    from unittest.mock import Mock

    from PySide6.QtCore import QEvent, QObject

    first, _ = _two_loaded_tabs(window)
    hidden = []

    class Filter(QObject):
        def eventFilter(self, watched, event):
            if event.type() == QEvent.Type.Hide:
                hidden.append(watched)
            return False

    observer = Filter()
    for widget in (window._tool_panel, window._content_widget, window._viewer):
        widget.installEventFilter(observer)
    pages = []
    window._main_stack.currentChanged.connect(pages.append)
    leave = Mock()
    monkeypatch.setattr(window, "_leave_special_layouts", leave)
    assert window._switch_to_tab(first)
    assert window._main_stack.currentWidget() is window._content_widget
    assert window._study_loading_overlay.isVisible()
    assert window._study_loading_overlay.geometry() == window._viewer_stack.rect()
    assert window._viewer_stack.updatesEnabled()
    assert window._gallery.updatesEnabled()
    assert window._tool_panel.updatesEnabled()
    assert window.updatesEnabled()
    leave.assert_not_called()
    _publish(window, _studies("a"))
    assert pages == hidden == []
    assert window._study_loading_overlay.isHidden()
    assert not window._study_loading_overlay._filter_installed


def test_retained_image_cannot_receive_mouse_keyboard_or_shortcut_actions(window, qtbot):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeySequence, QShortcut

    first, _ = _two_loaded_tabs(window)
    clicked = []
    window._system_bar._btn_caliper.clicked.connect(lambda: clicked.append(True))
    shortcuts = []
    shortcut = QShortcut(QKeySequence("Ctrl+J"), window)
    shortcut.activated.connect(lambda: shortcuts.append(True))
    window._switch_to_tab(first)
    qtbot.mouseClick(window._system_bar._btn_caliper, Qt.MouseButton.LeftButton)
    qtbot.keyClick(window, Qt.Key.Key_J, Qt.KeyboardModifier.ControlModifier)
    qtbot.keyClick(window._viewer, Qt.Key.Key_L)
    assert clicked == shortcuts == []
    _publish(window, _studies("a"))
    qtbot.mouseClick(window._system_bar._btn_caliper, Qt.MouseButton.LeftButton)
    assert clicked == [True]


def test_overlay_resizes_and_reinstalls_input_guard_after_window_hide_show(window, qtbot):
    first, _ = _two_loaded_tabs(window)
    window._switch_to_tab(first)
    window.resize(1400, 900)
    QApplication.processEvents()
    assert window._study_loading_overlay.geometry() == window._viewer_stack.rect()
    window.hide()
    assert not window._study_loading_overlay._filter_installed
    window.show()
    qtbot.waitExposed(window)
    assert window._study_loading_overlay._filter_installed
    window._abort_tab_load()


def test_abort_removes_loading_veil_and_restores_previous_tab(window):
    first, second = _two_loaded_tabs(window)
    window._switch_to_tab(first)
    window._abort_tab_load()
    assert window._tabs.active_tab_id == second
    assert window._tab_loading_id is None
    assert window._main_stack.currentWidget() is window._content_widget
    assert window._study_loading_overlay.isHidden()
    assert not window._study_loading_overlay._filter_installed


def test_synchronous_loader_exception_restores_updates_and_input(window, monkeypatch):
    first, second = _two_loaded_tabs(window)

    def fail(_studies):
        raise RuntimeError("loader failed")

    monkeypatch.setattr(window._controller, "load_pre_scanned_studies", fail)
    with pytest.raises(RuntimeError, match="loader failed"):
        window._switch_to_tab(first)
    assert window._viewer_stack.updatesEnabled()
    assert window._gallery.updatesEnabled()
    assert window._study_loading_overlay.isHidden()
    assert window._tabs.active_tab_id == second


def test_batch_update_guard_is_nested_exception_safe_and_does_not_touch_chrome(window):
    window._gallery.setUpdatesEnabled(False)
    with pytest.raises(RuntimeError):
        with window._batch_study_surface_updates():
            assert not window._viewer_stack.updatesEnabled()
            assert window._tool_panel.updatesEnabled()
            assert window._system_bar.updatesEnabled()
            assert window.updatesEnabled()
            with window._batch_study_surface_updates():
                pass
            assert not window._viewer_stack.updatesEnabled()
            raise RuntimeError("test cleanup")
    assert window._viewer_stack.updatesEnabled()
    assert not window._gallery.updatesEnabled()
    window._gallery.setUpdatesEnabled(True)


def test_second_flush_refusal_does_not_leave_loading_veil(window, monkeypatch):
    first, second = _two_loaded_tabs(window)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: None)
    monkeypatch.setattr(
        window._controller, "load_pre_scanned_studies", lambda studies: window._on_persistence_blocked()
    )
    assert not window._switch_to_tab(first)
    assert window._tabs.active_tab_id == second
    assert window._tab_loading_id is None
    assert window._study_loading_overlay.isHidden()


def test_new_folder_load_still_uses_placeholder_not_retained_study(window):
    _open_and_publish(window, "/data/A", "a")
    window.open_folder_path("/data/B")
    assert window._main_stack.currentWidget() is window._empty_tab_page
    assert window._study_loading_overlay.isHidden()


def test_unvisited_tab_does_not_expose_old_pixels_or_emit_measurement_clear(window, monkeypatch):
    from unittest.mock import Mock

    first, _ = _two_loaded_tabs(window)
    cleared = []
    window._viewer.contours_changed.connect(cleared.append)
    clear = Mock(wraps=window._viewer.clear)
    monkeypatch.setattr(window._viewer, "clear", clear)
    window._switch_to_tab(first)
    _publish(window, _studies("a"))
    clear.assert_called_once()
    assert cleared == []


def test_special_layout_exit_runs_only_when_a_special_layout_is_active(window, monkeypatch):
    from unittest.mock import Mock

    first, _ = _two_loaded_tabs(window)
    window._mmode_active = True
    leave = Mock(side_effect=lambda: setattr(window, "_mmode_active", False))
    monkeypatch.setattr(window, "_leave_special_layouts", leave)
    window._switch_to_tab(first)
    leave.assert_called_once()
    _publish(window, _studies("a"))


def test_synchronous_completion_and_empty_result_both_release_busy_state(window, monkeypatch):
    first, second = _two_loaded_tabs(window)
    monkeypatch.setattr(
        window._controller, "load_pre_scanned_studies", lambda studies: window._controller.studies_loaded.emit(studies)
    )
    window._switch_to_tab(first)
    assert window._tab_loading_id is None
    assert window._study_loading_overlay.isHidden()
    assert window._viewer_stack.updatesEnabled()
    monkeypatch.setattr(
        window._controller, "load_pre_scanned_studies", lambda studies: window._controller.studies_loaded.emit([])
    )
    window._switch_to_tab(second)
    assert window._main_stack.currentWidget() is window._empty_tab_page
    assert not window._study_loading_overlay._filter_installed
    assert window._gallery.updatesEnabled()


def test_input_guard_does_not_block_other_windows_or_error_dialogs(window, qtbot):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QDialog, QPushButton

    first, _ = _two_loaded_tabs(window)
    window._switch_to_tab(first)
    dialog = QDialog(window)
    qtbot.addWidget(dialog)
    button = QPushButton("Close error", dialog)
    clicked = []
    button.clicked.connect(lambda: clicked.append(True))
    dialog.show()
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
    assert clicked == [True]
    dialog.close()
    window._abort_tab_load()
