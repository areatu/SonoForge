"""S-03: the Orthanc selection owner, without a dialog or Qt event loop."""

from __future__ import annotations

from echo_personal_tool.application.study_selection import StudySelection


def _selection() -> StudySelection:
    return StudySelection()


def test_whole_study_before_its_series_arrive_keeps_an_empty_plan_entry() -> None:
    selection = _selection()
    selection.select_study("u1")

    assert selection.download_plan({}) == [("u1", [])]
    assert selection.is_whole("u1") is True

    selection.sync_known_series("u1", ["s1", "s2"])

    assert selection.download_plan({"u1": ["s1", "s2"]}) == [("u1", ["s1", "s2"])]
    assert selection.selected_series("u1") == {"s1", "s2"}


def test_unchecking_one_series_makes_the_study_partial_and_back() -> None:
    selection = _selection()
    selection.select_study("u1", ["s1", "s2"])
    known = ["s1", "s2"]

    assert selection.check_state("u1", known) == (True, False)

    selected = selection.set_series_selected("u1", "s1", False, known)

    assert selected == {"s2"}
    assert selection.is_whole("u1") is False
    assert selection.check_state("u1", known) == (False, True)
    assert selection.download_plan({"u1": known}) == [("u1", ["s2"])]

    selection.set_series_selected("u1", "s1", True, known)

    assert selection.is_whole("u1") is True
    assert selection.check_state("u1", known) == (True, False)
    assert selection.download_plan({"u1": known}) == [("u1", ["s1", "s2"])]


def test_last_series_unchecked_stays_an_explicit_empty_selection() -> None:
    """Current behaviour is pinned: the row stays selected with zero series.

    The dialog's ``_update_load_button`` counts plan entries, not series, so
    this state keeps the load button enabled.  Fixing that is a UX decision of
    its own; the owner move must not change it silently.
    """
    selection = _selection()
    selection.select_study("u1", ["s1"])

    selection.set_series_selected("u1", "s1", False, ["s1"])

    assert bool(selection) is True
    assert selection.is_whole("u1") is False
    assert selection.selected_series("u1") == set()
    assert selection.study_uids() == ["u1"]
    assert selection.download_plan({"u1": ["s1"]}) == [("u1", [])]


def test_deselecting_a_study_removes_whole_and_partial_state() -> None:
    selection = _selection()
    selection.select_study("u1", ["s1"])
    selection.set_series_selected("u1", "s2", True, ["s1", "s2"])

    selection.deselect_study("u1")

    assert not selection
    assert selection.study_uids() == []
    assert selection.download_plan({"u1": ["s1", "s2"]}) == []


def test_sync_known_series_does_not_rewrite_a_partial_choice() -> None:
    selection = _selection()
    selection.select_study("u1", ["s1", "s2", "s3"])
    selection.set_series_selected("u1", "s2", False, ["s1", "s2", "s3"])

    selection.sync_known_series("u1", ["s1", "s2", "s3", "s4"])

    assert selection.selected_series("u1") == {"s1", "s3"}


def test_plan_skips_studies_hidden_by_the_filter_but_keeps_them_selected() -> None:
    selection = _selection()
    selection.select_study("u1", ["s1"])
    selection.select_study("u2", ["s2"])

    plan = selection.download_plan({"u1": ["s1"], "u2": ["s2"]}, excluded={"u2"})

    assert plan == [("u1", ["s1"])]
    assert selection.is_whole("u2") is True
    assert selection.whole_studies() == {"u1", "u2"}


def test_off_list_whole_study_is_reported_but_absent_from_the_visible_plan() -> None:
    selection = _selection()
    selection.select_study("history-study")

    assert selection.whole_studies() == {"history-study"}
    assert selection.download_plan({}) == [("history-study", [])]


def test_returned_sets_are_copies_and_cannot_corrupt_the_owner() -> None:
    selection = _selection()
    selection.select_study("u1", ["s1"])

    selection.selected_series("u1").add("s2")
    selection.whole_studies().discard("u1")

    assert selection.selected_series("u1") == {"s1"}
    assert selection.is_whole("u1") is True


def test_partial_selection_without_known_series_is_sorted_for_stability() -> None:
    selection = _selection()
    selection.select_study("u1")
    selection.set_series_selected("u1", "s9", True, [])
    selection.set_series_selected("u1", "s1", True, [])

    assert selection.download_plan({}) == [("u1", ["s1", "s9"])]


def test_check_state_without_known_series_uses_only_the_whole_flag() -> None:
    selection = _selection()
    selection.select_study("u1")
    selection.select_study("u2")
    selection.set_series_selected("u2", "s1", True, [])

    assert selection.check_state("u1", []) == (True, False)
    assert selection.check_state("u2", []) == (False, False)
    assert selection.check_state("missing", []) == (False, False)


def test_blank_series_uids_are_ignored_but_the_study_stays_selected() -> None:
    selection = _selection()
    selection.select_study("u1", ["", "s1"])
    selection.sync_known_series("u1", ["", "s2"])

    assert selection.study_uids() == ["u1"]
    # A whole study mirrors the freshly loaded list, exactly as the dialog did.
    assert selection.selected_series("u1") == {"s2"}
    assert selection.download_plan({"u1": ["", "s2"]}) == [("u1", ["s2"])]


def test_clear_forgets_every_study_and_series() -> None:
    selection = _selection()
    selection.select_study("u1", ["s1"])
    selection.select_study("u2")

    selection.clear()

    assert not selection
    assert selection.study_uids() == []
    assert selection.download_plan({"u1": ["s1"]}) == []
