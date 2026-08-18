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


def test_infer_span_none_for_degenerate() -> None:
    roi = DopplerSpectrogramRoi(x0=40, y0=0, width=540, height=400)
    span = infer_velocity_span([200.0], 200.0, roi=roi, kind=DopplerKind.SPECTRAL)
    assert span is None


def test_infer_span_none_when_ambiguous() -> None:
    """A 4-tick-per-side layout is consistent with several standard spans
    (e.g. 100/200/400), so inference must refuse rather than guess."""
    roi = DopplerSpectrogramRoi(x0=40, y0=0, width=540, height=400)
    tick_ys = [40.0, 80.0, 120.0, 160.0, 200.0, 240.0, 280.0, 320.0, 360.0]
    span = infer_velocity_span(tick_ys, 200.0, roi=roi, kind=DopplerKind.SPECTRAL)
    assert span is None


def test_infer_span_none_when_ambiguous_above_only() -> None:
    roi = DopplerSpectrogramRoi(x0=40, y0=0, width=540, height=400)
    span = infer_velocity_span([40.0, 80.0, 120.0, 160.0], 200.0, roi=roi, kind=DopplerKind.SPECTRAL)
    assert span is None


def test_infer_span_none_when_ambiguous_below_only() -> None:
    roi = DopplerSpectrogramRoi(x0=40, y0=0, width=540, height=400)
    span = infer_velocity_span([240.0, 280.0, 320.0, 360.0], 200.0, roi=roi, kind=DopplerKind.SPECTRAL)
    assert span is None


def test_infer_span_returns_value_when_unambiguous() -> None:
    """7 ticks at 25px spacing below a baseline only match S=350."""
    roi = DopplerSpectrogramRoi(x0=40, y0=0, width=540, height=400)
    tick_ys = [25.0, 50.0, 75.0, 100.0, 125.0, 150.0, 175.0]
    span = infer_velocity_span(tick_ys, 0.0, roi=roi, kind=DopplerKind.SPECTRAL)
    assert span == 350.0


def test_orchestrator_uses_grid_lines_when_strip_fails() -> None:
    """When find_best_scale_column and detect_velocity_scale_ticks return < 4
    ticks, the orchestrator falls back to detect_doppler_grid_lines."""
    roi = DopplerSpectrogramRoi(x0=40, y0=0, width=540, height=400)
    baseline_y = 200.0
    tick_ys = [40.0, 80.0, 120.0, 160.0, 200.0, 240.0, 280.0, 320.0, 360.0]
    frame = np.zeros((400, 640), dtype=np.uint8)

    mod = "echo_personal_tool.domain.services.auto_doppler_velocity_calibration"
    with (
        patch(mod + ".find_best_scale_column", return_value=[]),
        patch(mod + ".detect_velocity_scale_ticks", return_value=[]),
        patch(mod + ".detect_doppler_grid_lines", return_value=tick_ys),
        patch(mod + ".infer_velocity_span", return_value=200.0),
    ):
        result = try_auto_doppler_velocity_calibration(frame, roi=roi, baseline_y=baseline_y, kind=DopplerKind.SPECTRAL)

    assert result is not None
    assert result.method == "inferred"
    assert result.velocity_span_cm_s == 200.0
    assert result.confidence == 0.7


def test_orchestrator_returns_none_when_no_ticks() -> None:
    """When no detector finds enough ticks, return None."""
    roi = DopplerSpectrogramRoi(x0=40, y0=0, width=540, height=400)
    frame = np.zeros((400, 640), dtype=np.uint8)

    mod = "echo_personal_tool.domain.services.auto_doppler_velocity_calibration"
    with (
        patch(mod + ".find_best_scale_column", return_value=[]),
        patch(mod + ".detect_velocity_scale_ticks", return_value=[]),
        patch(mod + ".detect_doppler_grid_lines", return_value=[]),
    ):
        result = try_auto_doppler_velocity_calibration(frame, roi=roi, baseline_y=200.0, kind=DopplerKind.SPECTRAL)

    assert result is None
