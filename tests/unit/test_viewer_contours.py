"""Isolated contract tests for the ViewerContours owner (A5)."""

from __future__ import annotations

from dataclasses import replace

from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.presentation.viewer.contours import ContourStateAttribute, ViewerContours


def _contour(**overrides) -> Contour:
    values = {
        "phase": "ED",
        "view": "A4C",
        "chamber": "LV",
        "frame_index": 3,
        "sop_instance_uid": "1.2.3.a",
        "points": [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)],
    }
    values.update(overrides)
    return Contour(**values)


def test_defaults_are_empty_and_click_tool_is_selected() -> None:
    state = ViewerContours()

    assert state.stored == []
    assert state.visible == []
    assert state.mode_active is False
    assert state.mode_kind is None
    assert state.stage is None
    assert state.active_chamber == "LV"
    assert state.active_view == "A4C"
    assert state.area_tool_mode == "click"
    assert state.lv_input == "landmarks"
    assert state.atrial_input == "landmarks"


def test_set_stored_copies_the_sequence() -> None:
    state = ViewerContours()
    original = [_contour()]

    state.set_stored(original)
    original.clear()

    assert len(state.stored) == 1


def test_find_index_matches_identity_and_replaces_in_place() -> None:
    state = ViewerContours()
    original = _contour()
    state.upsert(original)

    assert state.find_index(_contour()) == 0
    updated = replace(original, points=[(0.0, 0.0), (20.0, 0.0), (20.0, 20.0)])
    state.upsert(updated)

    assert state.stored == [updated]


def test_find_index_separates_planimeter_polygons_by_label() -> None:
    state = ViewerContours()
    first = _contour(chamber="AREA", phase="GEN", measurement_label="LV")
    second = _contour(chamber="AREA", phase="GEN", measurement_label="LA")
    state.upsert(first)

    assert state.find_index(second) is None
    state.upsert(second)

    assert [item.measurement_label for item in state.stored] == ["LV", "LA"]


def test_different_frame_or_instance_is_not_the_same_contour() -> None:
    state = ViewerContours()
    state.upsert(_contour())

    assert state.find_index(_contour(frame_index=4)) is None
    assert state.find_index(_contour(sop_instance_uid="1.2.3.b")) is None


def test_clear_active_drops_drawing_but_keeps_stored_contours() -> None:
    state = ViewerContours()
    stored = _contour()
    state.upsert(stored)
    state.mode_active = True
    state.mode_kind = "closed"
    state.stage = "polygon"
    state.active_phase = "GEN"
    state.active_arc_points = [(1.0, 2.0)]
    state.freehand_recording = True
    state.freehand_open_arc = True
    state.freehand_points = [(3.0, 4.0)]
    state.active_mitral_septal = (1.0, 2.0)
    state.active_mitral_annulus = ((1.0, 2.0), (3.0, 4.0))
    state.active_apex_landmark = (5.0, 6.0)
    state.remember_click((7.0, 8.0))

    state.clear_active()

    assert state.stored == [stored]
    assert state.mode_active is False
    assert state.mode_kind is None
    assert state.stage is None
    assert state.active_phase is None
    assert state.active_arc_points == []
    assert state.freehand_recording is False
    assert state.freehand_open_arc is False
    assert state.freehand_points == []
    assert state.active_mitral_septal is None
    assert state.active_mitral_annulus is None
    assert state.active_apex_landmark is None
    assert state.last_click_ms is None


def test_click_tracking_remembers_and_forgets_point_screens() -> None:
    state = ViewerContours()
    state.first_point_screen = (1.0, 2.0)
    state.last_point_screen = (3.0, 4.0)

    state.remember_click((5.0, 6.0))
    assert state.last_click_screen == (5.0, 6.0)
    assert state.last_click_ms is not None

    state.forget_point_screens()
    assert state.first_point_screen is None
    assert state.last_point_screen is None
    assert state.last_click_screen == (5.0, 6.0)


def test_reset_clicks_does_not_touch_the_active_contour() -> None:
    state = ViewerContours()
    state.mode_active = True
    state.active_arc_points = [(1.0, 2.0)]
    state.remember_click((3.0, 4.0))

    state.reset_clicks()

    assert state.mode_active is True
    assert state.active_arc_points == [(1.0, 2.0)]
    assert state.last_click_ms is None


def test_descriptor_reads_and_writes_the_owner() -> None:
    class Holder:
        contour_state = ViewerContours()
        stored_contours = ContourStateAttribute("stored")

    holder = Holder()
    contour = _contour()

    holder.stored_contours = [contour]
    assert holder.contour_state.stored == [contour]
    assert holder.stored_contours == [contour]
