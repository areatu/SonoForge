"""Unit tests for the tab session layer (Э9, PR-A). No Qt widgets."""

from __future__ import annotations

from datetime import datetime

import pytest

from echo_personal_tool.application.tab_session import (
    MAX_OPEN_TABS,
    TAB_ORIGIN_EMPTY,
    TAB_ORIGIN_FOLDER,
    TAB_ORIGIN_SERVER,
    TabLimitError,
    TabSessionError,
    TabSessionManager,
    UnknownTabError,
    decode_viewer_state,
    encode_viewer_state,
    park_tab,
    release_decoded_resources,
)
from echo_personal_tool.domain.models.metadata import SeriesMetadata, StudyMetadata


def _study(uid: str, series: int = 1) -> StudyMetadata:
    return StudyMetadata(
        study_uid=uid,
        study_datetime=datetime(2026, 10, 1, 9, 0),
        series=tuple(
            SeriesMetadata(series_uid=f"{uid}.{i}", study_uid=uid, modality="US", description="A4C", instances=())
            for i in range(series)
        ),
    )


def _manager(max_tabs: int = MAX_OPEN_TABS) -> TabSessionManager:
    counter = iter(range(10_000))
    return TabSessionManager(
        max_tabs=max_tabs,
        clock=lambda: 1_000.0,
        id_factory=lambda: f"tab-{next(counter)}",
    )


# ----- open / activate ---------------------------------------------------


def test_first_tab_becomes_active_and_later_tabs_do_not_steal_focus_by_default() -> None:
    m = _manager()
    first = m.open_tab(origin=TAB_ORIGIN_FOLDER, root="/data/A")
    assert m.active_tab_id == first.tab_id
    second = m.open_tab(origin=TAB_ORIGIN_FOLDER, root="/data/B", activate=False)
    assert m.active_tab_id == first.tab_id
    assert [t.tab_id for t in m.tabs] == [first.tab_id, second.tab_id]


def test_new_tab_is_active_by_default_when_opened_later() -> None:
    m = _manager()
    m.open_tab(origin=TAB_ORIGIN_FOLDER, root="/data/A")
    second = m.open_tab(origin=TAB_ORIGIN_FOLDER, root="/data/B")
    assert m.active_tab_id == second.tab_id
    assert m.active is second


def test_tab_stores_its_own_studies_and_root() -> None:
    m = _manager()
    a = m.open_tab(origin=TAB_ORIGIN_FOLDER, root="/data/A", studies=[_study("1.2", 3)])
    b = m.open_tab(origin=TAB_ORIGIN_FOLDER, root="/data/B", studies=[_study("1.3")])
    assert a.root == "/data/A" and b.root == "/data/B"
    assert a.clip_count == 3
    assert b.clip_count == 1
    assert a.studies is not b.studies


def test_activate_returns_previous_and_rejects_unknown_id() -> None:
    m = _manager()
    a = m.open_tab(origin=TAB_ORIGIN_FOLDER, root="/a")
    b = m.open_tab(origin=TAB_ORIGIN_FOLDER, root="/b")
    assert m.activate(a.tab_id) == b.tab_id
    assert m.active_tab_id == a.tab_id
    with pytest.raises(UnknownTabError):
        m.activate("nope")


def test_empty_origin_tab_is_allowed_for_start_page() -> None:
    m = _manager()
    tab = m.open_tab(origin=TAB_ORIGIN_EMPTY)
    assert tab.studies == []
    assert tab.clip_count == 0


def test_unknown_origin_is_rejected() -> None:
    m = _manager()
    with pytest.raises(TabSessionError):
        m.open_tab(origin="network")


def test_server_tab_cannot_claim_a_local_root_and_folder_tab_cannot_hold_pacs_cache() -> None:
    m = _manager()
    with pytest.raises(TabSessionError):
        m.open_tab(origin=TAB_ORIGIN_SERVER, root="/local")
    with pytest.raises(TabSessionError):
        m.open_tab(origin=TAB_ORIGIN_FOLDER, root="/local", cache_session_id="z3-1")
    assert len(m) == 0


# ----- limit -------------------------------------------------------------


def test_default_limit_is_eight_tabs() -> None:
    assert MAX_OPEN_TABS == 8
    assert _manager().max_tabs == 8


def test_opening_beyond_limit_raises_and_keeps_existing_tabs() -> None:
    m = _manager(max_tabs=2)
    m.open_tab(origin=TAB_ORIGIN_FOLDER, root="/a")
    m.open_tab(origin=TAB_ORIGIN_FOLDER, root="/b")
    assert m.is_full
    with pytest.raises(TabLimitError):
        m.open_tab(origin=TAB_ORIGIN_FOLDER, root="/c")
    assert len(m) == 2


def test_closing_frees_a_slot() -> None:
    m = _manager(max_tabs=1)
    a = m.open_tab(origin=TAB_ORIGIN_FOLDER, root="/a")
    m.close_tab(a.tab_id)
    assert not m.is_full
    m.open_tab(origin=TAB_ORIGIN_FOLDER, root="/b")


# ----- PACS cache session invariants --------------------------------------


def test_tabs_of_one_download_batch_share_the_cache_session() -> None:
    m = _manager()
    first = m.open_tab(origin=TAB_ORIGIN_SERVER, cache_session_id="z3-A")
    second = m.open_tab(origin=TAB_ORIGIN_SERVER, cache_session_id="z3-A", activate=False)
    assert len(m) == 2
    assert m.cache_session_users("z3-A") == (first.tab_id, second.tab_id)


def test_cache_session_is_purged_only_when_its_last_tab_closes() -> None:
    m = _manager()
    first = m.open_tab(origin=TAB_ORIGIN_SERVER, cache_session_id="z3-A")
    second = m.open_tab(origin=TAB_ORIGIN_SERVER, cache_session_id="z3-A", activate=False)
    assert m.close_tab(first.tab_id).purge_cache_session_id == ""
    assert m.close_tab(second.tab_id).purge_cache_session_id == "z3-A"


def test_empty_cache_session_id_never_conflicts() -> None:
    m = _manager()
    m.open_tab(origin=TAB_ORIGIN_FOLDER, root="/a")
    m.open_tab(origin=TAB_ORIGIN_FOLDER, root="/b")
    assert len(m) == 2


def test_cache_session_users_lookup() -> None:
    m = _manager()
    tab = m.open_tab(origin=TAB_ORIGIN_SERVER, cache_session_id="z3-A")
    assert m.cache_session_users("z3-A") == (tab.tab_id,)
    assert m.cache_session_users("z3-A", except_tab_id=tab.tab_id) == ()
    assert m.cache_session_users("z3-B") == ()
    assert m.cache_session_users("") == ()


# ----- close --------------------------------------------------------------


def test_closing_active_tab_activates_right_neighbour_then_left() -> None:
    m = _manager()
    a = m.open_tab(origin=TAB_ORIGIN_FOLDER, root="/a")
    b = m.open_tab(origin=TAB_ORIGIN_FOLDER, root="/b")
    c = m.open_tab(origin=TAB_ORIGIN_FOLDER, root="/c")
    m.activate(b.tab_id)
    result = m.close_tab(b.tab_id)
    assert result.next_active_tab_id == c.tab_id
    assert m.active_tab_id == c.tab_id
    m.close_tab(c.tab_id)  # rightmost now: falls back to the left neighbour
    assert m.active_tab_id == a.tab_id


def test_closing_last_tab_leaves_no_active_tab() -> None:
    m = _manager()
    a = m.open_tab(origin=TAB_ORIGIN_EMPTY)
    result = m.close_tab(a.tab_id)
    assert result.next_active_tab_id is None
    assert m.active is None


def test_closing_inactive_tab_keeps_active_tab() -> None:
    m = _manager()
    a = m.open_tab(origin=TAB_ORIGIN_FOLDER, root="/a")
    b = m.open_tab(origin=TAB_ORIGIN_FOLDER, root="/b")
    result = m.close_tab(a.tab_id)
    assert result.next_active_tab_id is None
    assert m.active_tab_id == b.tab_id


def test_closing_server_tab_requests_purge_of_its_cache_session() -> None:
    m = _manager()
    tab = m.open_tab(origin=TAB_ORIGIN_SERVER, cache_session_id="z3-A")
    result = m.close_tab(tab.tab_id)
    assert result.closed.tab_id == tab.tab_id
    assert result.purge_cache_session_id == "z3-A"


def test_closing_folder_tab_purges_nothing() -> None:
    m = _manager()
    tab = m.open_tab(origin=TAB_ORIGIN_FOLDER, root="/a")
    assert m.close_tab(tab.tab_id).purge_cache_session_id == ""


def test_closing_unknown_tab_raises() -> None:
    with pytest.raises(UnknownTabError):
        _manager().close_tab("missing")


def test_tab_index_follows_tab_order_after_close() -> None:
    m = _manager()
    a = m.open_tab(origin=TAB_ORIGIN_FOLDER, root="/a")
    b = m.open_tab(origin=TAB_ORIGIN_FOLDER, root="/b")
    assert m.index_of(b.tab_id) == 1
    m.close_tab(a.tab_id)
    assert m.index_of(b.tab_id) == 0


# ----- viewer state round trip --------------------------------------------


def test_viewer_state_round_trip_is_stable_and_sorted() -> None:
    state = {"wl": {"window": 80, "level": 40}, "calib": [1.5, None], "overlay": True}
    text = encode_viewer_state(state)
    assert text == encode_viewer_state(dict(reversed(list(state.items()))))
    assert decode_viewer_state(text) == state


def test_corrupt_viewer_state_decodes_to_empty_dict() -> None:
    assert decode_viewer_state("") == {}
    assert decode_viewer_state("{not json") == {}
    assert decode_viewer_state("[1, 2]") == {}


def test_non_serializable_viewer_state_is_rejected() -> None:
    with pytest.raises(TabSessionError):
        encode_viewer_state({"bad": object()})
    with pytest.raises(TabSessionError):
        encode_viewer_state({"nan": float("nan")})


def test_update_viewer_stores_frame_instance_and_state() -> None:
    m = _manager()
    tab = m.open_tab(origin=TAB_ORIGIN_FOLDER, root="/a")
    m.update_viewer(tab.tab_id, active_instance_uid="1.2.3", frame_index=7, viewer_state={"wl": 80})
    assert tab.active_instance_uid == "1.2.3"
    assert tab.frame_index == 7
    assert decode_viewer_state(tab.viewer_state_json) == {"wl": 80}


def test_update_viewer_rejects_negative_frame() -> None:
    m = _manager()
    tab = m.open_tab(origin=TAB_ORIGIN_FOLDER, root="/a")
    with pytest.raises(TabSessionError):
        m.update_viewer(tab.tab_id, frame_index=-1)


# ----- parking (§5) -------------------------------------------------------


class _FakeFrameCache:
    def __init__(self) -> None:
        self.cleared = 0

    def clear(self) -> None:
        self.cleared += 1


class _FakeThumbs:
    def __init__(self) -> None:
        self.resets = 0

    def reset(self) -> None:
        self.resets += 1


def test_park_flushes_then_saves_state_then_releases_in_order() -> None:
    m = _manager()
    tab = m.open_tab(origin=TAB_ORIGIN_FOLDER, root="/a")
    order: list[str] = []

    def flush() -> None:
        order.append("flush")
        assert tab.viewer_state_json == "{}"  # state not yet written

    def release() -> None:
        order.append("release")
        assert decode_viewer_state(tab.viewer_state_json) == {"wl": 60}

    park_tab(
        m,
        tab.tab_id,
        viewer_state={"wl": 60},
        frame_index=12,
        active_instance_uid="1.2.3",
        flush_measurements=flush,
        release=release,
    )
    assert order == ["flush", "release"]
    assert tab.frame_index == 12
    assert tab.active_instance_uid == "1.2.3"


def test_park_keeps_tab_open_and_its_cache_session() -> None:
    m = _manager()
    tab = m.open_tab(origin=TAB_ORIGIN_SERVER, cache_session_id="z3-A")
    park_tab(m, tab.tab_id, viewer_state={}, frame_index=0)
    assert tab.tab_id in m
    assert tab.cache_session_id == "z3-A"


def test_release_clears_frames_and_thumbnail_queue_only() -> None:
    frames, thumbs = _FakeFrameCache(), _FakeThumbs()
    release_decoded_resources(frames, thumbs)
    assert (frames.cleared, thumbs.resets) == (1, 1)


def test_release_accepts_missing_components() -> None:
    release_decoded_resources(None, None)


def test_bad_id_factory_is_rejected() -> None:
    m = TabSessionManager(id_factory=lambda: "")
    with pytest.raises(TabSessionError):
        m.open_tab(origin=TAB_ORIGIN_EMPTY)


# ----- PR-B additions: retarget of the empty tab and captions ------------------


def test_empty_tab_can_be_retargeted_to_a_new_source() -> None:
    m = _manager()
    tab = m.open_tab(origin=TAB_ORIGIN_EMPTY)
    m.retarget_empty(tab.tab_id, origin=TAB_ORIGIN_SERVER, cache_session_id="z3-A")
    assert (tab.origin, tab.cache_session_id) == (TAB_ORIGIN_SERVER, "z3-A")
    assert m.cache_session_users("z3-A") == (tab.tab_id,)


def test_tab_with_studies_is_never_retargeted() -> None:
    m = _manager()
    tab = m.open_tab(origin=TAB_ORIGIN_FOLDER, root="/a", studies=[_study("1.2")])
    with pytest.raises(TabSessionError):
        m.retarget_empty(tab.tab_id, origin=TAB_ORIGIN_FOLDER, root="/b")
    assert tab.root == "/a"


def test_retarget_validates_source() -> None:
    m = _manager()
    empty = m.open_tab(origin=TAB_ORIGIN_EMPTY)
    with pytest.raises(TabSessionError):
        m.retarget_empty(empty.tab_id, origin="ftp")
    assert empty.origin == TAB_ORIGIN_EMPTY


def test_tab_title_has_no_patient_name_and_is_one_based() -> None:
    from echo_personal_tool.application.tab_session import tab_title

    m = _manager()
    tab = m.open_tab(origin=TAB_ORIGIN_FOLDER, root="/a", studies=[_study("1.2", 2)])
    title = tab_title(tab, 1, empty_label="Пусто", untitled_label="Без описания")
    assert title == "2 · 01.10.2026 · US · A4C"


def test_tab_title_for_empty_and_undescribed_tabs() -> None:
    from echo_personal_tool.application.tab_session import tab_title

    m = _manager()
    empty = m.open_tab(origin=TAB_ORIGIN_EMPTY)
    assert tab_title(empty, 0, empty_label="Пусто", untitled_label="?") == "1 · Пусто"
    bare = StudyMetadata(study_uid="9", study_datetime=datetime(2026, 1, 2), series=())
    tab = m.open_tab(origin=TAB_ORIGIN_FOLDER, root="/b", studies=[bare])
    assert tab_title(tab, 1, empty_label="Пусто", untitled_label="Без описания") == "2 · 02.01.2026 · Без описания"


# ----- active source replacement with tabs disabled ---------------------------


def test_replace_active_resets_studies_and_parked_state_but_keeps_identity() -> None:
    m = _manager()
    tab = m.open_tab(origin=TAB_ORIGIN_FOLDER, root="/old", studies=[_study("old")])
    m.update_viewer(tab.tab_id, active_instance_uid="old.1", frame_index=4, viewer_state={"wl": 100})
    tab.has_measurements = True
    assert m.replace_active(origin=TAB_ORIGIN_SERVER, cache_session_id="new-cache") == ""
    assert m.active is tab
    assert len(m) == 1
    assert tab.origin == TAB_ORIGIN_SERVER
    assert tab.root == ""
    assert tab.cache_session_id == "new-cache"
    assert tab.studies == []
    assert tab.active_instance_uid == ""
    assert tab.frame_index == 0
    assert tab.viewer_state_json == "{}"
    assert not tab.has_measurements


@pytest.mark.parametrize("shared", [False, True])
def test_replace_active_only_returns_unreferenced_cache_for_purge(shared) -> None:
    m = _manager()
    active = m.open_tab(origin=TAB_ORIGIN_SERVER, cache_session_id="old")
    if shared:
        m.open_tab(origin=TAB_ORIGIN_SERVER, cache_session_id="old", activate=False)
    assert m.replace_active(origin=TAB_ORIGIN_FOLDER, root="/new") == ("" if shared else "old")
    assert m.active is active


def test_replace_active_with_same_cache_does_not_purge_it() -> None:
    m = _manager()
    m.open_tab(origin=TAB_ORIGIN_SERVER, cache_session_id="shared")
    assert m.replace_active(origin=TAB_ORIGIN_SERVER, cache_session_id="shared") == ""


def test_replace_active_validates_before_mutating() -> None:
    m = _manager()
    with pytest.raises(TabSessionError):
        m.replace_active(origin=TAB_ORIGIN_FOLDER)
    tab = m.open_tab(origin=TAB_ORIGIN_FOLDER, root="/old", studies=[_study("old")])
    with pytest.raises(TabSessionError):
        m.replace_active(origin=TAB_ORIGIN_FOLDER, root="/new", cache_session_id="invalid")
    assert tab.root == "/old"
    assert tab.studies == [_study("old")]
