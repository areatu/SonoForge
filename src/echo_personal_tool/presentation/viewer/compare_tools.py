"""Tables and ratios of the two-caliper comparison tools (distance and area).

The generic «D1 / D2» tool, the stenosis tool and the dedicated AR-jet tools run
the same two-step interaction: the user draws the first caliper (or contour) and
then the second one.  Only three details differ — the prompt of each step, the
labels stored in the measurement list and the direction of the ratio: the AR
tools keep the regurgitant jet over the LVOT, the generic ones keep the smaller
value over the larger one.  Those tables live here so ``ViewerWidget`` stays a
consumer of them and the report, the calculator inputs and the overlay all read
the same labels.

A calibrated spectral zone also belongs to this module: the viewer asks it to
merge the user's Doppler calibration into the vendor panel geometry, because the
result decides whether a region is measured in millimetres or in milliseconds.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TypeVar

from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi
from echo_personal_tool.domain.models.frame_panels import (
    FramePanelLayout,
    PanelKind,
    UltrasoundPanel,
)
from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement

#: Tool kind -> (first caliper/contour label, second one, derived percentage).
LABELS: dict[str, tuple[str, str, str]] = {
    "diameter": ("D1", "D2", "%D"),
    "stenosis_diameter": ("D1", "D2", "%D"),
    "ar_jet_diameter": ("AR Jet D1", "LVOTd", "AR Jet %D"),
    "area": ("S1", "S2", "%S"),
    "ar_jet_area": ("AR Jet S1", "LVOT S", "AR Jet %S"),
}

#: Tool kind -> the prompt shown when the tool starts.
START_HINTS: dict[str, str] = {
    "diameter": "viewer.dcmp_click_start",
    "ar_jet_diameter": "viewer.ar_jet_dcmp_click_start",
    "area": "viewer.acmp_click_start",
    "ar_jet_area": "viewer.ar_jet_acmp_click_start",
}

#: Distance tools -> (end of the first segment, start of the second, its end).
#: The AR jet workflow measures the jet first and the LVOT second, so it needs
#: its own wording rather than the generic «D1 / D2» hints.
DIAMETER_HINTS: dict[str, tuple[str, str, str]] = {
    "diameter": ("viewer.dcmp_click_end", "viewer.dcmp_second_start", "viewer.dcmp_second_end"),
    "stenosis": (
        "viewer.stenosis_d_click_end",
        "viewer.stenosis_d_second_start",
        "viewer.stenosis_d_second_end",
    ),
    "ar_jet": (
        "viewer.ar_jet_dcmp_click_end",
        "viewer.ar_jet_dcmp_second_start",
        "viewer.ar_jet_dcmp_second_end",
    ),
}

#: Area tools -> (start of the second contour, the result line).
AREA_HINTS: dict[str, tuple[str, str]] = {
    "area": ("viewer.acmp_second_start", "viewer.acmp_result"),
    "ar_jet_area": ("viewer.ar_jet_acmp_second_start", "viewer.ar_jet_acmp_result"),
}

_KeyT = TypeVar("_KeyT")

#: Kinds whose two calipers are distances and whose labels follow ``LABELS``.
DIAMETER_KINDS = frozenset({"diameter", "stenosis_diameter", "ar_jet_diameter"})

#: Kinds whose two contours are areas.
AREA_KINDS = frozenset({"area", "ar_jet_area"})


def compare_labels(kind: str) -> tuple[str, str, str]:
    """The three labels of ``kind``; the generic distance labels otherwise."""
    return LABELS.get(kind, LABELS["diameter"])


def start_hint(kind: str) -> str:
    """The prompt key shown when ``kind`` starts, the generic one as fallback."""
    return START_HINTS.get(kind, START_HINTS["diameter"])


def live_caliper_label(kind: str, first_segment_done: bool) -> str | None:
    """The label of the caliper being drawn, or ``None`` outside the tools."""
    if kind not in DIAMETER_KINDS:
        return None
    first, second, _ = compare_labels(kind)
    return second if first_segment_done else first


def percent_d(kind: str, d1_mm: float | None, d2_mm: float | None) -> float | None:
    """``%D`` for ``kind``: jet / LVOT for AR, smaller / larger otherwise."""
    if d1_mm is None or d2_mm is None:
        return None
    if kind == "ar_jet_diameter":
        return d1_mm / d2_mm * 100.0 if d2_mm > 0 else None
    bigger = max(d1_mm, d2_mm)
    return min(d1_mm, d2_mm) / bigger * 100.0 if bigger > 0 else None


def percent_s(kind: str, area1_cm2: float | None, area2_cm2: float | None) -> float:
    """``%S`` for ``kind``: jet / LVOT for AR, smaller / larger otherwise.

    The area workflow reports a percentage even before it has both contours, so
    a missing area yields ``0.0`` rather than ``None`` — that is what the
    overlay and the report line expect.
    """
    if area1_cm2 is None or area2_cm2 is None:
        return 0.0
    if kind == "ar_jet_area":
        return area1_cm2 / area2_cm2 * 100.0 if area2_cm2 > 0 else 0.0
    bigger = max(area1_cm2, area2_cm2)
    return min(area1_cm2, area2_cm2) / bigger * 100.0 if bigger > 0 else 0.0


def stored_widths(
    measurements: Mapping[_KeyT, LinearMeasurement],
    first_label: str,
    second_label: str,
) -> tuple[float | None, float | None, int | None, str]:
    """The two stored widths of a distance tool plus where they were drawn."""
    d1_mm: float | None = None
    d2_mm: float | None = None
    frame: int | None = None
    instance_uid = ""
    for key, measurement in measurements.items():
        if not isinstance(key, tuple) or key[0] not in (first_label, second_label):
            continue
        if measurement.label == first_label:
            d1_mm = measurement.millimeter_length
        elif measurement.label == second_label:
            d2_mm = measurement.millimeter_length
        else:
            continue
        frame = measurement.frame_index
        instance_uid = measurement.sop_instance_uid
    return d1_mm, d2_mm, frame, instance_uid


def resolve_frame_panels(
    layout: FramePanelLayout | None,
    zone: DopplerSpectrogramRoi | None,
) -> FramePanelLayout | None:
    """Vendor panel geometry with the manually calibrated spectral zone applied.

    Samsung tags many Doppler stills with the B-mode region, so a frame can be
    «B-mode only» for the parser while showing a spectrum.  A manual Doppler
    calibration (or the wizard in progress) marks that part of the frame as
    Doppler, so nothing downstream — measurement availability, spacing, the
    calibration hint — can take it back to B-mode.
    """
    if zone is None:
        return layout
    if layout is None:
        return FramePanelLayout((UltrasoundPanel(kind=PanelKind.DOPPLER, bounds=zone),))
    return layout.with_doppler_zone(zone)
