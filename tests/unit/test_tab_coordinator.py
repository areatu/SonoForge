"""TabCoordinator: the tab load sequence without a real window (N-08, Э9).

The window-level behaviour is covered by ``test_main_window_tabs.py``; this
module drives the extracted coordinator against a fake host, so the sequence
(acquire → park → load → finish/abort) is testable without MainWindow.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QMessageBox

from echo_personal_tool.application.download_history import DownloadHistory
from echo_personal_tool.application.tab_session import (
    MAX_OPEN_TABS,
    TAB_ORIGIN_EMPTY,
    TAB_ORIGIN_FOLDER,
    TAB_ORIGIN_SERVER,
    TabSessionManager,
)
from echo_personal_tool.domain.models.metadata import (
    InstanceMetadata,
    SeriesMetadata,
    StudyMetadata,
)
from echo_personal_tool.presentation.tab_coordinator import TabCoordinator

pytestmark = pytest.mark.gui


class _FakeViewer(QObject):
    """QObject so ``QSignalBlocker`` in ``after_loaded`` has something to block."""

    def __init__(self) -> None:
        super().__init__()
        self.cleared = 0
        self.overlay = (0.0, 0.0)

    def clear(self) -> None:
        self.cleared += 1

    def results_overlay_position(self) -> tuple[float, float]:
        return self.overlay

    def set_results_overlay_position(self, x: float, y: float) -> None:
        self.overlay = (float(x), float(y))


class _FakeGallery:
    def __init__(self) -> None:
        self.selected: list[str] = []

    def select_instance(self, instance) -> None:  # noqa: ANN001 - InstanceMetadata
        self.selected.append(instance.sop_instance_uid)


class _FakeStrip:
    def __init__(self) -> None:
        self.rendered: list[tuple[list[tuple[str, str]], str | None]] = []

    def set_tabs(self, tabs, active_tab_id) -> None:  # noqa: ANN001 - Qt signal payload
        self.rendered.append((list(tabs), active_tab_id))


class _FakeStack:
    """Mirrors the two pages of the real stack: content (0) and placeholder (1)."""

    def __init__(self) -> None:
        self.index = 0
        self.content = object()
        self.placeholder = object()

    def setCurrentIndex(self, index: int) -> None:  # noqa: N802 - Qt naming
        self.index = index

    def currentWidget(self):  # noqa: ANN201 - one of the two page markers
        return self.content if self.index == 0 else self.placeholder


class _FakeEmptyPage:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def show_message(self, title: str, body: str) -> None:
        self.messages.append((title, body))


class _FakeSlider:
    def __init__(self, value: int = 0) -> None:
        self._value = value

    def value(self) -> int:
        return self._value

    def setValue(self, value: int) -> None:  # noqa: N802 - Qt naming
        self._value = value


class _FakeToggle:
    """``window_slider``/``level_slider``/``dr_slider`` wrappers of the tool panel."""

    def __init__(self, value: int = 0) -> None:
        self._slider = _FakeSlider(value)

    def slider(self) -> _FakeSlider:
        return self._slider


class _FakeControls:
    def __init__(self) -> None:
        self.window_slider = _FakeToggle(100)
        self.level_slider = _FakeToggle(50)
        self.dr_slider = _FakeToggle(40)


class _FakeToolPanel:
    def __init__(self) -> None:
        self.controls = _FakeControls()


class _FakeOverlay:
    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0

    def start(self, message: str) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1


class FakeWindow:
    """The ``TabWindow`` surface the coordinator declares, plus call recorders."""

    def __init__(self, *, tabs_enabled: bool = True, flush: bool = True) -> None:
        self._user_preferences = SimpleNamespace(tabs_enabled=tabs_enabled)
        self._store: dict[str, object] = {}
        self._controller = SimpleNamespace(
            state_manager=SimpleNamespace(
                snapshot=SimpleNamespace(current_frame_index=0, instance=None),
            ),
            measurement_persistence=SimpleNamespace(store=self._store),
            load_pre_scanned_studies=self.load_studies,
        )
        self._viewer = _FakeViewer()
        self._tool_panel = _FakeToolPanel()
        self._gallery = _FakeGallery()
        self._tab_strip = _FakeStrip()
        self._main_stack = _FakeStack()
        self._content_widget = self._main_stack.content
        self._empty_tab_page = _FakeEmptyPage()
        self._study_loading_overlay = _FakeOverlay()
        self._download_history = DownloadHistory()
        self.flush_ok = flush
        self.statuses: list[str] = []
        self.flushes = 0
        self.purges: list[str] = []
        self.purge_processed = 0
        self.special_layout = False
        self.left_layouts = 0
        self.doppler_resets = 0
        self.loaded: list[list[StudyMetadata]] = []
        self.selected: list[str] = []
        self.has_loaded_study = True
        self.start_page_visible = 0
        self.recents_refreshed = 0
        self.clip_counts: list[int] = []

    # host hooks -----------------------------------------------------
    def _show_status(self, message: str) -> None:
        self.statuses.append(message)

    def _tab_flush_or_block(self) -> bool:
        self.flushes += 1
        return self.flush_ok

    def _queue_cache_purge(self, session_id: str) -> None:
        if session_id:
            self.purges.append(session_id)

    def _process_pending_cache_purges(self) -> None:
        self.purge_processed += 1

    def _special_layout_active(self) -> bool:
        return self.special_layout

    def _leave_special_layouts(self) -> None:
        self.left_layouts += 1
        self.special_layout = False

    def _reset_doppler_mode_override(self) -> None:
        self.doppler_resets += 1

    @contextmanager
    def _batch_study_surface_updates(self):
        yield

    def _on_instance_selected(self, selected: InstanceMetadata) -> None:
        self.selected.append(selected.sop_instance_uid)

    def _set_start_page_visible(self, visible: bool) -> None:
        self.start_page_visible = 1 if visible else 0
        self._has_loaded_study = not visible

    def _refresh_start_page_recents(self) -> None:
        self.recents_refreshed += 1

    def _update_last_session_clip_count(self, clip_count: int) -> None:
        self.clip_counts.append(int(clip_count))

    # recorder for the controller ------------------------------------
    def load_studies(self, studies) -> None:  # noqa: ANN001 - controller signature
        self.loaded.append(list(studies))


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


def _studies(prefix: str) -> list[StudyMetadata]:
    series = SeriesMetadata(
        series_uid=f"{prefix}.series",
        study_uid=f"{prefix}.study",
        modality="US",
        description="A4C",
        instances=(_instance(f"{prefix}.0"),),
    )
    return [StudyMetadata(study_uid=f"{prefix}.study", study_datetime=datetime(2026, 10, 1, 9), series=(series,))]


def _finish(coordinator: TabCoordinator, studies: list[StudyMetadata]) -> str | None:
    """What the window does when the controller publishes a study set."""
    tab_id = coordinator.finish_load(studies)
    coordinator.after_loaded(tab_id, studies)
    return tab_id


def _coordinator(**kwargs) -> tuple[TabCoordinator, FakeWindow]:
    window = FakeWindow(**kwargs)
    coordinator = TabCoordinator(window)
    coordinator.open_empty_tab()
    return coordinator, window


def test_the_first_load_fills_the_starting_empty_tab() -> None:
    coordinator, window = _coordinator()
    empty_id = coordinator.tabs.active_tab_id

    assert coordinator.acquire_for_load(TAB_ORIGIN_FOLDER, "/data/A", "") is True

    assert len(coordinator.tabs) == 1
    assert coordinator.tabs.active_tab_id == empty_id
    assert coordinator.tabs.active.origin == TAB_ORIGIN_FOLDER
    assert coordinator.loading_tab_id == empty_id
    assert window._main_stack.index == 1, "the placeholder stays until studies arrive"


def test_a_second_folder_parks_the_first_tab_and_opens_another() -> None:
    coordinator, _ = _coordinator()
    first = coordinator.tabs.active_tab_id
    coordinator.acquire_for_load(TAB_ORIGIN_FOLDER, "/data/A", "")
    _finish(coordinator, _studies("a"))

    assert coordinator.acquire_for_load(TAB_ORIGIN_FOLDER, "/data/B", "") is True

    assert len(coordinator.tabs) == 2
    assert coordinator.tabs.get(first).studies, "the parked tab keeps its studies"
    assert coordinator.tabs.active.root == "/data/B"


def test_a_load_is_refused_while_another_is_in_flight() -> None:
    coordinator, window = _coordinator()
    coordinator.acquire_for_load(TAB_ORIGIN_FOLDER, "/data/A", "")

    assert coordinator.acquire_for_load(TAB_ORIGIN_FOLDER, "/data/B", "") is False

    assert len(coordinator.tabs) == 1
    assert window.statuses, "the refusal is explained in the status bar"


def test_a_load_is_refused_when_measurements_cannot_be_flushed() -> None:
    coordinator, window = _coordinator(flush=False)

    assert coordinator.acquire_for_load(TAB_ORIGIN_FOLDER, "/data/A", "") is False

    assert window.flushes == 1
    assert coordinator.tabs.active.origin == TAB_ORIGIN_EMPTY
    assert coordinator.loading_tab_id is None


def test_with_tabs_disabled_the_source_is_replaced_and_the_old_cache_purged() -> None:
    coordinator, window = _coordinator(tabs_enabled=False)
    coordinator.acquire_for_load(TAB_ORIGIN_SERVER, "", "z3-old")
    _finish(coordinator, _studies("old"))

    assert coordinator.acquire_for_load(TAB_ORIGIN_FOLDER, "/data/new", "") is True

    assert len(coordinator.tabs) == 1
    assert coordinator.tabs.active.root == "/data/new"
    assert window.purges == ["z3-old"], "the replaced session leaves the cache"


def test_finish_load_attaches_the_studies_to_the_loading_tab() -> None:
    coordinator, _ = _coordinator()
    coordinator.acquire_for_load(TAB_ORIGIN_FOLDER, "/data/A", "")

    tab_id = coordinator.finish_load(_studies("a"))

    assert tab_id == coordinator.tabs.active_tab_id
    assert coordinator.tabs.get(tab_id).studies == _studies("a")
    assert coordinator.loading_tab_id is None


def test_abort_returns_to_the_tab_the_viewer_came_from() -> None:
    coordinator, _ = _coordinator()
    first = coordinator.tabs.active_tab_id
    coordinator.acquire_for_load(TAB_ORIGIN_FOLDER, "/data/A", "")
    _finish(coordinator, _studies("a"))
    assert coordinator.acquire_for_load(TAB_ORIGIN_FOLDER, "/data/B", "") is True
    _finish(coordinator, _studies("b"))
    second = coordinator.tabs.active_tab_id

    assert coordinator.switch_to(first) is True
    coordinator.abort_load()

    assert coordinator.tabs.active_tab_id == second, "the refused switch rolls back"
    assert coordinator.loading_tab_id is None


def test_switching_back_reloads_the_parked_studies_and_restores_the_clip() -> None:
    coordinator, window = _coordinator()
    first = coordinator.tabs.active_tab_id
    coordinator.acquire_for_load(TAB_ORIGIN_FOLDER, "/data/A", "")
    _finish(coordinator, _studies("a"))
    # the viewer shows a clip of A: parking the tab stores it for the return
    window._controller.state_manager.snapshot = SimpleNamespace(
        current_frame_index=2,
        instance=SimpleNamespace(sop_instance_uid="a.0"),
    )
    coordinator.acquire_for_load(TAB_ORIGIN_FOLDER, "/data/B", "")
    _finish(coordinator, _studies("b"))
    window.loaded.clear()

    assert coordinator.switch_to(first) is True
    assert window.loaded[-1] == _studies("a"), "no rescan: the tab's own studies are pushed back"

    assert coordinator.after_loaded(first, _studies("a")) is True
    assert window.selected == ["a.0"], "the clip the tab was showing comes back"


def test_switch_is_refused_while_loading() -> None:
    coordinator, _ = _coordinator()
    first = coordinator.tabs.active_tab_id
    coordinator.acquire_for_load(TAB_ORIGIN_FOLDER, "/data/A", "")
    _finish(coordinator, _studies("a"))
    coordinator.acquire_for_load(TAB_ORIGIN_FOLDER, "/data/B", "")
    second = coordinator.tabs.active_tab_id

    # Switching to a non-loading tab is allowed while another tab loads.
    assert coordinator.switch_to(first) is True
    assert coordinator.tabs.active_tab_id == first

    # Switching TO the loading tab is still refused.
    assert coordinator.switch_to(second) is False
    assert coordinator.tabs.active_tab_id == first


def test_a_background_download_lands_in_its_own_tab() -> None:
    coordinator, window = _coordinator()
    first = coordinator.tabs.active_tab_id
    coordinator.acquire_for_load(TAB_ORIGIN_FOLDER, "/data/A", "")
    _finish(coordinator, _studies("a"))
    coordinator.acquire_for_load(TAB_ORIGIN_FOLDER, "/data/B", "")
    second = coordinator.tabs.active_tab_id
    assert coordinator.switch_to(first) is True
    assert coordinator.loading_tab_id == second, "the download keeps its tab while another one is shown"
    window.loaded.clear()

    coordinator.finish_background_load(_studies("b"))

    assert coordinator.loading_tab_id is None
    assert coordinator.tabs.get(second).studies == _studies("b")
    assert coordinator.tabs.active_tab_id == first, "the visible tab does not move"
    assert window.loaded == [], "a background download never pushes into the view"
    assert coordinator.switch_to(second) is True, "the finished download is switchable"


def test_a_failed_background_download_releases_the_loading_mark() -> None:
    coordinator, _ = _coordinator()
    first = coordinator.tabs.active_tab_id
    coordinator.acquire_for_load(TAB_ORIGIN_FOLDER, "/data/A", "")
    _finish(coordinator, _studies("a"))
    coordinator.acquire_for_load(TAB_ORIGIN_FOLDER, "/data/B", "")
    second = coordinator.tabs.active_tab_id
    assert coordinator.switch_to(first) is True

    coordinator.fail_background_load()

    assert coordinator.loading_tab_id is None
    assert coordinator.tabs.active_tab_id == first
    assert coordinator.switch_to(second) is True


def test_the_limit_asks_before_closing_the_oldest_inactive_tab(monkeypatch) -> None:
    coordinator, _ = _coordinator()
    first = coordinator.tabs.active_tab_id
    coordinator.acquire_for_load(TAB_ORIGIN_FOLDER, "/data/0", "")
    _finish(coordinator, _studies("s0"))
    for index in range(1, MAX_OPEN_TABS):
        coordinator.tabs.open_tab(origin=TAB_ORIGIN_FOLDER, root=f"/data/{index}", studies=_studies(f"s{index}"))
    assert coordinator.tabs.is_full

    asked: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *args, **kwargs: asked.append(args[2]) or QMessageBox.StandardButton.No),
    )
    assert coordinator.ensure_capacity() is False
    assert asked, "the limit must be a question, not a silent close"
    assert len(coordinator.tabs) == MAX_OPEN_TABS

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    assert coordinator.ensure_capacity() is True
    assert first not in coordinator.tabs, "the oldest inactive tab goes first"
    assert len(coordinator.tabs) == MAX_OPEN_TABS - 1


def test_a_batch_opens_one_tab_per_study_and_records_the_history() -> None:
    coordinator, window = _coordinator()

    assert coordinator.open_batch(_studies("a") + _studies("b"), "sess-1") is True

    tabs = coordinator.tabs.tabs
    assert [tab.cache_session_id for tab in tabs] == ["sess-1", "sess-1"]
    assert window.loaded[-1] == _studies("a"), "only the first study loads now"
    assert [record.study_uid for record in window._download_history.records()] == ["b.study", "a.study"]


def test_a_batch_with_tabs_disabled_loads_wholesale() -> None:
    coordinator, window = _coordinator(tabs_enabled=False)
    batch = _studies("a") + _studies("b")

    assert coordinator.open_batch(batch, "sess-1") is True

    assert len(coordinator.tabs) == 1
    assert window.loaded[-1] == batch


def test_caption_numbers_the_tabs_and_names_the_series() -> None:
    coordinator, _ = _coordinator()
    coordinator.acquire_for_load(TAB_ORIGIN_FOLDER, "/data/A", "")

    _finish(coordinator, _studies("a"))

    caption = coordinator.caption(coordinator.tabs.active)
    assert caption.startswith("1 ·")
    assert "A4C" in caption


def test_main_stack_shows_the_welcome_page_for_an_empty_tab() -> None:
    # Э5 (spec 2026-10-07 §7): the empty tab carries the welcome page, not the
    # plain placeholder — that one is reserved for a fresh load into a busy tab.
    coordinator, window = _coordinator()

    coordinator.update_main_stack()

    assert window._main_stack.index == 0
    assert window.start_page_visible == 1
    assert window._has_loaded_study is False
    assert window._empty_tab_page.messages == []


def test_main_stack_shows_the_loading_placeholder_for_a_fresh_load() -> None:
    coordinator, window = _coordinator()
    coordinator.acquire_for_load(TAB_ORIGIN_FOLDER, "/data/A", "")

    coordinator.update_main_stack()

    assert window._main_stack.index == 1
    assert window._empty_tab_page.messages, "a fresh load explains what is happening"


def test_main_stack_keeps_the_previous_image_during_a_switch() -> None:
    coordinator, window = _coordinator()
    first = coordinator.tabs.active_tab_id
    coordinator.acquire_for_load(TAB_ORIGIN_FOLDER, "/data/A", "")
    _finish(coordinator, _studies("a"))
    coordinator.acquire_for_load(TAB_ORIGIN_FOLDER, "/data/B", "")
    _finish(coordinator, _studies("b"))
    assert window._main_stack.index == 0

    assert coordinator.switch_to(first) is True

    assert window._study_loading_overlay.started == 1
    assert window._main_stack.index == 0, "the old image stays until the tab's studies arrive"
    _finish(coordinator, _studies("a"))
    assert window._study_loading_overlay.stopped >= 1


def test_after_loaded_clears_the_retained_image_for_a_never_visited_tab() -> None:
    coordinator, window = _coordinator()
    first = coordinator.tabs.active_tab_id
    coordinator.acquire_for_load(TAB_ORIGIN_FOLDER, "/data/A", "")
    _finish(coordinator, _studies("a"))
    coordinator.acquire_for_load(TAB_ORIGIN_FOLDER, "/data/B", "")
    _finish(coordinator, _studies("b"))

    assert coordinator.switch_to(first) is True
    _finish(coordinator, _studies("a"))

    assert window._viewer.cleared == 1, "no old pixels are presented as the tab's content"


def test_leaving_a_special_layout_happens_only_when_one_is_active() -> None:
    coordinator, window = _coordinator()
    window.special_layout = True

    coordinator.acquire_for_load(TAB_ORIGIN_FOLDER, "/data/A", "")

    assert window.left_layouts == 1
    _finish(coordinator, _studies("a"))
    assert coordinator.acquire_for_load(TAB_ORIGIN_FOLDER, "/data/B", "") is True
    assert window.left_layouts == 1, "nothing to leave the second time"


def test_live_measurements_come_from_the_persistence_store() -> None:
    coordinator, window = _coordinator()
    coordinator.acquire_for_load(TAB_ORIGIN_FOLDER, "/data/A", "")
    _finish(coordinator, _studies("a"))
    tab = coordinator.tabs.active

    window._store["a.study"] = SimpleNamespace(has_measurements=False)
    assert coordinator.has_live_measurements(tab) is False
    window._store["a.study"] = SimpleNamespace(has_measurements=True)
    assert coordinator.has_live_measurements(tab) is True


def test_manager_can_be_injected() -> None:
    manager = TabSessionManager(max_tabs=2)
    coordinator = TabCoordinator(FakeWindow(), manager=manager)

    coordinator.open_empty_tab()

    assert coordinator.tabs is manager
    assert len(manager) == 1
