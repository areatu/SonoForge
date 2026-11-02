"""QH-1a.2 contract tests for the comparison pair (Э10), model level.

These are Qt-free unit tests of :class:`MultiViewSession`: the comparison context
must hold two distinct sources simultaneously (clip A from tab 1 + clip B from
tab 2), an explicit replace/clear bumps the pair generation so stale responses
are discarded, and a still-referenced source must not be deleted underneath the
open comparison window. The GUI/tab-lifecycle wiring is a later slice that needs
the Qt test environment; this pins the contract it must satisfy (spec §5.1 QH-1a).
"""

from types import SimpleNamespace

from echo_personal_tool.domain.models.multiview import (
    ClipComparison,
    MultiViewSession,
    PaneId,
)


def _instance(uid: str, fps: int = 25):
    return SimpleNamespace(
        sop_instance_uid=uid,
        number_of_frames=10,
        frame_time_ms=1000 // fps,
        frame_time_vector=None,
    )


def _with_clip(session: MultiViewSession, pane_id: PaneId, study_uid: str, uid: str, fps: int = 25, size=(640, 480)):
    pane = session.pane(pane_id)
    pane.instance = _instance(uid, fps)
    pane.study_uid = study_uid
    pane.frame_size = size
    return session


def test_e10_pair_from_two_tabs_is_comparable_and_retained():
    s = MultiViewSession()
    _with_clip(s, PaneId.LEFT, "STUDY_A", "SOP_A")
    _with_clip(s, PaneId.RIGHT, "STUDY_B", "SOP_B")
    # Э10: clip A from tab 1 + clip B from tab 2 must be comparable and both
    # sources must be held by the open pair at once.
    assert s.clips_are_comparable()
    assert s.compare_clips() is ClipComparison.OK
    assert s.references_source("STUDY_A", "SOP_A")
    assert s.references_source("STUDY_B", "SOP_B")
    assert not s.references_source("STUDY_C")


def test_active_tab_switch_preserves_pair_without_bumping_generation():
    s = MultiViewSession()
    _with_clip(s, PaneId.LEFT, "STUDY_A", "SOP_A")
    _with_clip(s, PaneId.RIGHT, "STUDY_B", "SOP_B")
    # Switching the *active* tab is not a replace/clear: the pair generation stays
    # put and both references survive, so the controller must not call
    # reset_session on a plain tab switch (the §2.2 gap).
    assert s.generation == 0
    assert s.accepts(0)
    assert s.references_source("STUDY_A", "SOP_A")
    assert s.references_source("STUDY_B", "SOP_B")


def test_explicit_replace_bumps_pair_generation_and_discards_stale_responses():
    s = MultiViewSession()
    _with_clip(s, PaneId.LEFT, "STUDY_A", "SOP_A")
    _with_clip(s, PaneId.RIGHT, "STUDY_B", "SOP_B")
    before = s.generation
    after = s.bump_generation()  # explicit replace/clear of a pane
    assert after == before + 1
    # A late response tagged with the stale pair generation is discarded.
    assert not s.accepts(before)
    assert s.accepts(after)


def test_closing_owner_tab_must_not_delete_still_referenced_source():
    s = MultiViewSession()
    _with_clip(s, PaneId.LEFT, "STUDY_A", "SOP_A")
    _with_clip(s, PaneId.RIGHT, "STUDY_B", "SOP_B")
    # STUDY_A/SOP_A is still referenced by the open comparison pair, so a
    # tab-close / Z3-clear handler must refuse to delete it.
    assert s.references_source("STUDY_A", "SOP_A")
    # After an explicit clear of that pane (with a generation bump), the reference
    # is released and the source may be deleted.
    s.pane(PaneId.LEFT).instance = None
    s.pane(PaneId.LEFT).study_uid = None
    s.bump_generation()
    assert not s.references_source("STUDY_A", "SOP_A")
    assert s.references_source("STUDY_B", "SOP_B")


def test_incompatible_pair_is_reported_not_comparable():
    s = MultiViewSession()
    _with_clip(s, PaneId.LEFT, "STUDY_A", "SOP_A", fps=25)
    _with_clip(s, PaneId.RIGHT, "STUDY_B", "SOP_B", fps=50)  # fps mismatch
    assert not s.clips_are_comparable()
    assert s.compare_clips() is ClipComparison.FPS_MISMATCH
