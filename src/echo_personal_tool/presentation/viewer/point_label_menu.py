"""Right-click naming of a committed general-tools point (2026-11-17 list, item 1).

The viewer used to open the naming menu by itself right after a measurement
committed; the tools no longer do that, so the physician asks for the menu
where the point already is.  A right-press on a caliper end or on a node of an
area/volume polygon opens the same popup the tool raised before, and any name —
catalogued («ЛП ПЗР») or invented («сепарация перикарда») — travels with the
value into the report through the label-rename path.

The hit is searched in screen pixels, so the grab radius does not stretch with
zoom, and the nearest point wins between the two kinds: a crowded overlay
answers with one menu only.  The window owns the widget state and the popup;
this module owns the rule, which keeps ``ViewerWidget`` at its size ceiling
(issue 474) and makes the rule testable without a drawing.
"""

from __future__ import annotations

import math
from typing import Final, Protocol

from PySide6.QtCore import QPoint, QPointF, QRect

from echo_personal_tool.domain.calculations.planimeter import (
    GENERIC_AREA_CHAMBER,
    GENERIC_VOLUME_CHAMBER,
)
from echo_personal_tool.domain.doppler_catalog import format_velocity_measurement
from echo_personal_tool.domain.measurement_catalog import format_measurement, measurement_for_caliper
from echo_personal_tool.domain.models import Contour
from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
from echo_personal_tool.domain.services.nomenclature import is_renamable_caliper_label
from echo_personal_tool.domain.translation import tr
from echo_personal_tool.presentation.viewer.contours import ViewerContours
from echo_personal_tool.presentation.viewer.label_picker_owner import ViewerLabelPicker

#: Screen radius of the point-menu hit: the nearest caliper end / contour node
#: within it opens the naming menu on right-click.
POINT_HIT_RADIUS_PX: Final = 14.0

#: Chambers whose contours are the physician's own planimetry, not a protocol's.
_GENERIC_CHAMBERS: Final = frozenset({GENERIC_AREA_CHAMBER, GENERIC_VOLUME_CHAMBER})

#: What a right-click can name: one caliper (store key + measurement) or one contour.
LabelPoint = tuple[tuple[str, int], LinearMeasurement] | Contour


class PointNamingHost(Protocol):
    """The slice of ``ViewerWidget`` the point menu drives."""

    @property
    def contour_state(self) -> ViewerContours: ...

    @property
    def label_picker_owner(self) -> ViewerLabelPicker: ...

    @property
    def _stored_linear_measurements(self) -> dict[tuple[str, int], LinearMeasurement]: ...

    @property
    def _calibration_active(self) -> bool: ...

    @property
    def _linear_caliper_start(self) -> tuple[float, float] | None: ...

    def is_protocol_active(self) -> bool: ...

    def mapFromGlobal(self, pos: QPoint) -> QPoint: ...

    def mapToGlobal(self, pos: QPoint) -> QPoint: ...

    def _current_frame_index(self) -> int | None: ...

    def _map_image_point_to_viewer(self, point: tuple[float, float]) -> QPoint: ...

    def _graphics_content_geometry(self) -> QRect: ...

    @property
    def _length_display_unit(self) -> str: ...

    def _resolve_label_picker_context(self, *, doppler_measurement: bool = False) -> str: ...

    def _open_label_picker_for_contour(
        self,
        contour: Contour,
        *,
        anchor_point: tuple[float, float] | None = None,
        allow_free_text: bool = False,
    ) -> None: ...


def find_point(
    host: PointNamingHost,
    global_pos: QPointF,
) -> tuple[LabelPoint, tuple[float, float]] | None:
    """What committed point sits under the cursor, and where it is in the image.

    ``None`` while a contour is being drawn — the gesture owns the right-press
    then — or when no renameable point is within :data:`POINT_HIT_RADIUS_PX`.
    """
    if host.contour_state.mode_active or host.contour_state.freehand_recording:
        return None
    local = host.mapFromGlobal(global_pos.toPoint())
    frame = host._current_frame_index()
    best: tuple[float, LabelPoint, tuple[float, float]] | None = None

    def consider(distance: float, payload: LabelPoint, point: tuple[float, float]) -> None:
        nonlocal best
        if distance <= POINT_HIT_RADIUS_PX and (best is None or distance < best[0]):
            best = (distance, payload, point)

    def screen_distance(image_point: tuple[float, float]) -> float:
        viewer_point = host._map_image_point_to_viewer(image_point)
        dx: float = float(viewer_point.x() - local.x())
        dy: float = float(viewer_point.y() - local.y())
        return math.hypot(dx, dy)

    for key, measurement in host._stored_linear_measurements.items():
        if not is_renamable_caliper_label(measurement.label):
            continue
        if frame is not None and measurement.frame_index not in (None, frame):
            continue
        for point in (measurement.start, measurement.end):
            if point is None:
                continue
            consider(screen_distance(point), (key, measurement), point)
    for contour in host.contour_state.visible:
        if contour.chamber.upper() not in _GENERIC_CHAMBERS:
            continue
        for point in contour.points:
            consider(screen_distance(point), contour, point)
    if best is None:
        return None
    return best[1], best[2]


def offer_point(host: PointNamingHost, global_pos: QPointF) -> bool:
    """Open the naming menu over a committed general-tools point.

    ``True`` when the menu was raised, so the caller stops the right-press
    there instead of arming the radial gesture.
    """
    if host.contour_state.mode_active or host.contour_state.freehand_recording:
        return False
    # An armed generic caliper is repeat mode, not a drawing in progress; only
    # a half-placed segment or a running calibration must win the click.
    if host._calibration_active or host._linear_caliper_start is not None:
        return False
    if not host.label_picker_owner.enabled or host.is_protocol_active():
        return False
    hit = find_point(host, global_pos)
    if hit is None:
        return False
    payload, point = hit
    if isinstance(payload, Contour):
        host._open_label_picker_for_contour(payload, anchor_point=point, allow_free_text=True)
    else:
        key, measurement = payload
        offer_caliper(host, key, measurement, anchor_point=point, allow_free_text=True)
    return True


def offer_at_image_point(host: PointNamingHost, image_point: tuple[float, float]) -> bool:
    """``offer_point`` for a right-press exactly on *image_point*.

    The public entry the tests use: it round-trips through the widget mapping,
    so the grab radius is exact whatever the view transform and the window
    position are.
    """
    viewer_point = host._map_image_point_to_viewer(image_point)
    return offer_point(host, QPointF(host.mapToGlobal(viewer_point)))


def offer_caliper(
    host: PointNamingHost,
    key: tuple[str, int],
    measurement: LinearMeasurement,
    *,
    anchor_point: tuple[float, float] | None = None,
    allow_free_text: bool = False,
) -> None:
    """Show the naming popup for one caliper; no gates, the callers decide."""
    point = anchor_point if anchor_point is not None else measurement.end
    if point is None:
        # A caliper without a placed end point has nothing to anchor a popup to.
        return
    anchor = host._map_image_point_to_viewer(point)
    host.label_picker_owner.offer(
        target=("caliper", key),
        value_text=caliper_value_text(host, measurement),
        context=host._resolve_label_picker_context(doppler_measurement=measurement.doppler),
        anchor=anchor,
        bounds=host._graphics_content_geometry(),
        allow_free_text=allow_free_text,
    )


def caliper_value_text(host: PointNamingHost, measurement: LinearMeasurement) -> str:
    """Value line of the popup: mm/cm, ms or the velocity with its unit."""
    mid = measurement_for_caliper(measurement.label)
    if measurement.doppler:
        if measurement.velocity_cm_s is not None:
            vel_str, unit = format_velocity_measurement(
                mid or "doppler.vmax", abs(measurement.velocity_cm_s), measurement.doppler_mode
            )
            return f"{vel_str} {unit}"
        if measurement.time_ms is not None:
            return f"{format_measurement(mid or 'doppler.pht', measurement.time_ms, 'ms')} {tr('unit.ms')}"
        return ""
    if measurement.millimeter_length is not None:
        mm = float(measurement.millimeter_length)
        if host._length_display_unit == "cm":
            return f"{format_measurement(mid or 'caliper.length', mm / 10.0, 'cm')} {tr('unit.cm')}"
        fallback_id = "caliper.length_submm" if measurement.submillimeter else "caliper.length"
        return f"{format_measurement(mid or fallback_id, mm, 'mm')} {tr('unit.mm')}"
    return f"{format_measurement(mid or 'caliper.length', measurement.pixel_length, 'px')} px"
