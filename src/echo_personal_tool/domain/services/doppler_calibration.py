"""Build Doppler axis mapping from calibration state."""

from __future__ import annotations

from echo_personal_tool.domain.models.doppler_axis import DopplerAxisMapping
from echo_personal_tool.domain.models.doppler_roi import (
    DopplerCalibrationState,
    DopplerKind,
    DopplerSpectrogramRoi,
)


def is_calibration_complete(state: DopplerCalibrationState | None) -> bool:
    return state is not None and state.is_complete()


def build_axis_mapping(state: DopplerCalibrationState) -> DopplerAxisMapping:
    """Map plot pixels inside ROI to time (ms) and signed velocity (cm/s)."""
    roi = state.roi
    half = state.velocity_span_cm_s / 2.0
    return DopplerAxisMapping(
        roi=roi,
        baseline_y_px=state.baseline_y_px,
        time_origin_ms=state.time_origin_ms,
        time_span_ms=state.time_span_ms,
        velocity_span_cm_s=state.velocity_span_cm_s,
        velocity_min_cm_s=-half,
        velocity_max_cm_s=half,
        plot_width=roi.width,
        plot_height=roi.height,
        plot_origin_x=roi.x0,
        plot_origin_y=roi.y0,
    )


def calibration_from_roi_and_baseline(
    roi: DopplerSpectrogramRoi,
    baseline_y_px: float,
    *,
    velocity_span_cm_s: float | None = None,
    time_span_ms: float = 1000.0,
    time_origin_ms: float = 0.0,
    kind: DopplerKind = DopplerKind.SPECTRAL,
) -> DopplerCalibrationState:
    span = velocity_span_cm_s if velocity_span_cm_s is not None else kind.default_velocity_span_cm_s
    return DopplerCalibrationState(
        roi=roi,
        baseline_y_px=baseline_y_px,
        time_origin_ms=time_origin_ms,
        time_span_ms=time_span_ms,
        velocity_span_cm_s=span,
        kind=kind,
    )


def roi_from_corners(
    corner_a: tuple[float, float],
    corner_b: tuple[float, float],
) -> DopplerSpectrogramRoi:
    x0 = min(corner_a[0], corner_b[0])
    y0 = min(corner_a[1], corner_b[1])
    x1 = max(corner_a[0], corner_b[0])
    y1 = max(corner_a[1], corner_b[1])
    return DopplerSpectrogramRoi(x0=x0, y0=y0, width=max(1.0, x1 - x0), height=max(1.0, y1 - y0))
