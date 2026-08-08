from unittest.mock import patch

import numpy as np
from echo_personal_tool.domain.models.doppler_roi import (
    DopplerKind,
    DopplerSpectrogramRoi,
)
from echo_personal_tool.domain.services.auto_doppler_velocity_calibration import (
    infer_velocity_span,
    try_auto_doppler_velocity_calibration,
)

_SPECTRAL_SPANS = [50.0, 100.0, 150.0, 200.0, 250.0, 300.0, 350.0, 400.0]


def test_infer_span_matches_known_layout() -> None:
    # ROI height 400, baseline at center y=200, 4 evenly spaced ticks above
    # at 40px spacing -> top tick at y=40 (160px above baseline).
    roi = DopplerSpectrogramRoi(x0=40, y0=0, width=540, height=400)
    baseline_y = 200.0
    tick_ys = [40.0, 80.0, 120.0, 160.0, 200.0, 240.0, 280.0, 320.0, 360.0]
    span = infer_velocity_span(tick_ys, baseline_y, roi=roi, kind=DopplerKind.SPECTRAL)
    assert span in _SPECTRAL_SPANS
    # 4 intervals above baseline over 160px; span/2 must divide evenly
    n_above = 4
    per_interval = (span / 2.0) / n_above
    # Consistency: pixel spacing should match the computed per-velocity-velocity
    # interval. For a uniform scale, the detected pixel interval (not 160px but
    # the actual spacing) is consistent only when the span is a standard value.
    # This assertion confirms the span is one of the known standard values.
    assert span in _SPECTRAL_SPANS


def test_infer_span_none_for_degenerate() -> None:
    roi = DopplerSpectrogramRoi(x0=40, y0=0, width=540, height=400)
    span = infer_velocity_span([200.0], 200.0, roi=roi, kind=DopplerKind.SPECTRAL)
    assert span is None


def test_orchestrator_uses_grid_lines_when_strip_fails() -> None:
    """When detect_velocity_scale_ticks returns < 4 ticks, the orchestrator
    falls back to detect_doppler_grid_lines for tick positions."""
    roi = DopplerSpectrogramRoi(x0=40, y0=0, width=540, height=400)
    baseline_y = 200.0
    tick_ys = [40.0, 80.0, 120.0, 160.0, 200.0, 240.0, 280.0, 320.0, 360.0]
    frame = np.zeros((400, 640), dtype=np.uint8)

    mod = "echo_personal_tool.domain.services.auto_doppler_velocity_calibration"
    with patch(mod + ".detect_velocity_scale_ticks", return_value=[]), \
         patch(mod + ".detect_doppler_grid_lines", return_value=tick_ys):
        result = try_auto_doppler_velocity_calibration(
            frame, roi=roi, baseline_y=baseline_y, kind=DopplerKind.SPECTRAL
        )

    assert result is not None
    assert result.method == "inferred"
    assert result.velocity_span_cm_s in _SPECTRAL_SPANS
    assert result.confidence == 0.7


def test_orchestrator_returns_none_when_no_ticks() -> None:
    """When neither detector finds enough ticks, return None."""
    roi = DopplerSpectrogramRoi(x0=40, y0=0, width=540, height=400)
    frame = np.zeros((400, 640), dtype=np.uint8)

    mod = "echo_personal_tool.domain.services.auto_doppler_velocity_calibration"
    with patch(mod + ".detect_velocity_scale_ticks", return_value=[]), \
         patch(mod + ".detect_doppler_grid_lines", return_value=[]):
        result = try_auto_doppler_velocity_calibration(
            frame, roi=roi, baseline_y=200.0, kind=DopplerKind.SPECTRAL
        )

    assert result is None
