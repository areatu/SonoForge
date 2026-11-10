"""Shared observable-state snapshot for the viewer guard-clause tests (#327).

The tests in this slice used to be ``# Should not raise`` with no assertion at
all: a deleted handler, a wrong guard and a correct early return all looked
identical. ``guard_snapshot`` turns them into characterization tests: the
handler must leave these observable fields alone. Only public seams are read
(``w.contract.<name>`` and Qt widget state), never ``w._name``.

Some fields are created lazily by the widget (for example the debug ROI item),
so every read is tolerant of a missing attribute; ``None`` means "not created
yet", which is itself an observable state.
"""

from __future__ import annotations

from typing import Any


def guard_snapshot(w: Any) -> tuple[Any, ...]:
    """Fields a guard-clause handler must not change.

    Booleans and lengths are used instead of the objects themselves so the
    tuple compares without numpy/Qt equality surprises.
    """
    c = w.contract

    def field(name: str, default: Any = None) -> Any:
        return getattr(c, name, default)

    return (
        field("current_frame") is None,
        bool(field("calibration_active", False)),
        field("calibration_kind"),
        field("calibration_start_y"),
        field("drag_session"),
        field("doppler_cal_step"),
        bool(field("debug_overlay_visible", False)),
        field("debug_roi_item") is None,
        tuple(field("frame_overlay_lines", ())),
        len(field("contour_items", ())),
        field("cached_levels_key"),
        field("frame_panel_layout") is None,
        field("active_caliper_label_item") is None,
        getattr(getattr(w, "mmode", None), "line_item", None) is None,
        field("speckle_result") is None,
        field("current_state") is None,
        bool(field("results_overlay_custom_position", False)),
        field("doppler_calibration_state") is None,
        bool(field("doppler_axis_calibrated", False)),
        bool(field("doppler_velocity_confirmed", False)),
        c.timeline_slider.value(),
        c.window_slider.value(),
        c.level_slider.value(),
        c.dr_slider.value(),
    )
