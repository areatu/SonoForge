"""LA strain — reservoir/conduit/booster (plan А.6, issue #644).

Pure-domain tests: the curve from tracked positions, the phase metrics, the
A-onset detection and the end-to-end synthetic-gold tracking test (a cine with
a known LA roof motion must reproduce the known strain numbers within
tolerance — the acceptance item «согласие с референсами (gold)»).
"""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.models.speckle import SpeckleConfig
from echo_personal_tool.domain.services.la_strain import (
    A_ONSET_FALLBACK_FRACTION,
    build_la_arc_kernels,
    compute_la_phase_metrics,
    compute_la_strain_curve,
    detect_a_onset,
    select_la_strain_contour,
    track_la_arc,
)

SPACING = (0.5, 0.5)


def _arc_polyline_length(rx: float, ry: float) -> float:
    """Length of the fixture arc polyline — the reference the strain compares to."""
    pts = _arc_points(rx, ry)
    return float(np.sum(np.linalg.norm(np.diff(pts, axis=0), axis=1)))


def _arc_strain_pct(ry: float, *, reference_ry: float = 40.0) -> float:
    """Expected strain of an arc grown from ``reference_ry`` to ``ry``."""
    return (_arc_polyline_length(50.0, ry) / _arc_polyline_length(50.0, reference_ry) - 1.0) * 100.0


def _piecewise_curve(n: int = 30) -> np.ndarray:
    """A physiologic-shaped LA strain curve: reservoir → conduit → plateau → booster."""
    t = np.arange(n).astype(float)
    return np.piecewise(
        t,
        [t < 10, (t >= 10) & (t < 16), (t >= 16) & (t < 21), (t >= 21) & (t < 25), t >= 25],
        [
            lambda x: 28.0 * x / 10.0,
            lambda x: 28.0 - 20.0 * (x - 10.0) / 6.0,
            lambda x: 8.0,
            lambda x: 8.0 - 20.0 * (x - 21.0) / 4.0,
            lambda x: -12.0,
        ],
    )


def _arc_points(rx: float, ry: float, center: tuple[float, float] = (100.0, 130.0), n: int = 9):
    """Roof arc of an ellipse from the septal to the lateral annulus corner."""
    cx, cy = center
    angles = np.linspace(np.pi, 0.0, n)
    return np.stack([cx + rx * np.cos(angles), cy - ry * np.sin(angles)], axis=1)


def _synthetic_la_cine(
    *,
    n_frames: int = 24,
    size: int = 200,
    seed: int = 7,
) -> tuple[np.ndarray, np.ndarray]:
    """A textured cine whose bright LA roof arc moves with a known strain.

    Returns ``(frames, ed_arc)``. The arc is drawn at frame t with ``ry(t)``
    following: reservoir +15 % (frames 0-9), conduit down to +6 % (10-15),
    diastasis (16-19), booster to −10 % (20-23). ED arc = the frame-0 arc.
    """
    rng = np.random.default_rng(seed)
    base = rng.uniform(40.0, 120.0, size=(size, size)).astype(np.float32)
    frames = np.stack([base + rng.normal(0.0, 6.0, size=(size, size)) for _ in range(n_frames)])
    yy, xx = np.mgrid[0:size, 0:size]

    def ry_at(t: int) -> float:
        if t < 10:
            return 40.0 * (1.0 + 0.15 * t / 9.0)
        if t < 16:
            return 46.0 - 6.0 * (t - 10.0) / 6.0 * (1.0 - 0.06 / 0.15)
        if t < 20:
            return 42.4
        return 42.4 - (42.4 - 36.0) * (t - 20.0) / 3.0

    for t in range(n_frames):
        pts = _arc_points(50.0, ry_at(t))
        for x, y in pts:
            xi, yi = int(round(x)), int(round(y))
            if 1 <= yi < size - 1 and 1 <= xi < size - 1:
                frames[t, yi - 1 : yi + 2, xi - 1 : xi + 2] = 230.0
    return frames.astype(np.float32), _arc_points(50.0, 40.0)


class TestBuildKernels:
    def test_one_kernel_per_node_ordered_along_the_arc(self) -> None:
        arc = _arc_points(50.0, 40.0)
        kernels = build_la_arc_kernels(arc, kernel_radius=6)
        assert len(kernels) == arc.shape[0]
        assert [kernel.node_index for kernel in kernels] == list(range(arc.shape[0]))
        assert all(kernel.aha_segment == 0 for kernel in kernels)
        assert kernels[0].center == pytest.approx(tuple(arc[0]), abs=1e-6)


class TestStrainCurve:
    def test_curve_is_zero_at_ed_and_tracks_arc_growth(self) -> None:
        arc = _arc_points(50.0, 40.0)
        grown = _arc_points(50.0, 46.0)  # +15 % ry ≈ +13 % arc length
        positions = np.stack([arc, arc, grown, arc])  # frame 2 carries the growth
        curve = compute_la_strain_curve(positions, ed_index=0, pixel_spacing=SPACING)
        assert curve[0] == pytest.approx(0.0, abs=1e-9)
        # ry +15 % on this relatively flat roof arc is ≈ +6.4 % of arc length
        # — the strain follows the arc, not the half-axis.
        assert curve[2] == pytest.approx(_arc_strain_pct(46.0), abs=0.2)
        assert curve[3] == pytest.approx(0.0, abs=1e-9)

    def test_degenerate_arc_yields_nan_not_zero(self) -> None:
        collapsed = np.full((4, 3, 2), 50.0)  # every node at the same point
        curve = compute_la_strain_curve(collapsed, ed_index=0, pixel_spacing=SPACING)
        assert np.isnan(curve).all()

    def test_anisotropic_spacing_scales_the_curve(self) -> None:
        arc = _arc_points(50.0, 40.0)
        grown = _arc_points(50.0, 46.0)
        positions = np.stack([arc, grown])
        iso = compute_la_strain_curve(positions, 0, (0.5, 0.5))
        stretched = compute_la_strain_curve(positions, 0, (1.0, 0.5))
        # A horizontally stretched arc gains more length per unit growth —
        # the mm scale must matter, not cancel.
        assert stretched[1] > iso[1]


class TestMetrics:
    def test_reservoir_conduit_booster_from_the_curve(self) -> None:
        metrics = compute_la_phase_metrics(_piecewise_curve(), ed_index=0, end_index=29)
        assert metrics is not None
        assert metrics.reservoir_pct == pytest.approx(28.0, abs=0.6)
        assert metrics.reservoir_index == pytest.approx(10, abs=1)
        assert metrics.a_onset_source == "curve"
        assert metrics.a_onset_index is not None and 19 <= metrics.a_onset_index <= 21
        assert metrics.conduit_pct == pytest.approx(20.0, abs=1.5)
        assert metrics.booster_pct == pytest.approx(20.0, abs=1.5)

    def test_mvo_narrows_the_reservoir_window(self) -> None:
        curve = _piecewise_curve()
        curve[12] = 35.0  # a late artefact the MVO window must ignore
        plain = compute_la_phase_metrics(curve, ed_index=0, end_index=29)
        gated = compute_la_phase_metrics(curve, ed_index=0, end_index=29, mvo_index=11)
        assert plain is not None and gated is not None
        assert plain.reservoir_pct == pytest.approx(35.0, abs=0.1)
        assert gated.reservoir_pct == pytest.approx(28.0, abs=0.6)

    def test_flat_curve_falls_back_to_window_fraction(self) -> None:
        curve = np.concatenate([np.linspace(0.0, 25.0, 10), np.linspace(25.0, -10.0, 21)[1:]])
        metrics = compute_la_phase_metrics(curve, ed_index=0, end_index=29)
        assert metrics is not None
        assert metrics.a_onset_source == "window_fraction"
        assert metrics.a_onset_index is not None
        expected = 9 + A_ONSET_FALLBACK_FRACTION * (29 - 9)
        assert metrics.a_onset_index == pytest.approx(expected, abs=1)
        assert "la_strain.a_onset_estimated" in metrics.warnings

    def test_too_short_diastole_keeps_conduit_and_booster_missing(self) -> None:
        curve = np.linspace(0.0, 25.0, 12)
        metrics = compute_la_phase_metrics(curve, ed_index=0, end_index=11)
        assert metrics is not None
        assert metrics.reservoir_pct == pytest.approx(25.0, abs=0.1)
        assert metrics.conduit_pct is None and metrics.booster_pct is None

    def test_degenerate_curve_returns_none(self) -> None:
        assert compute_la_phase_metrics(np.full(6, np.nan), ed_index=0, end_index=5) is None
        assert compute_la_phase_metrics(np.zeros(4), ed_index=0, end_index=2) is None


class TestDetectAOnset:
    def test_last_local_max_wins(self) -> None:
        curve = np.array([0, 5, 10, 8, 9, 9, 9, 2, -4, -8.0])
        index, source = detect_a_onset(curve, reservoir_index=2, end_index=9)
        assert source == "curve"
        assert index in (4, 5)  # the plateau before the booster decline

    def test_monotone_decline_has_no_onset(self) -> None:
        index, source = detect_a_onset(np.linspace(10.0, -10.0, 12), reservoir_index=0, end_index=11)
        assert index is None and source == "none"

    def test_window_too_short(self) -> None:
        index, source = detect_a_onset(np.linspace(10.0, -10.0, 8), reservoir_index=6, end_index=7)
        assert index is None and source == "none"


class TestTrackingGold:
    """The synthetic-gold acceptance: a known motion must reproduce itself."""

    @pytest.fixture(scope="class")
    def gold(self) -> tuple[np.ndarray, np.ndarray]:
        return _synthetic_la_cine()

    def _metrics(self, gold: tuple[np.ndarray, np.ndarray]):
        frames, ed_arc = gold
        tracked = track_la_arc(frames, ed_arc, anchor_index=0, config=SpeckleConfig.preset_standard(), kernel_radius=6)
        assert tracked is not None
        positions, ncc_mean, valid_fraction = tracked
        assert valid_fraction > 0.8
        assert ncc_mean > 0.5
        curve = compute_la_strain_curve(positions, ed_index=0, pixel_spacing=SPACING)
        return compute_la_phase_metrics(curve, ed_index=0, end_index=frames.shape[0] - 1)

    def test_reservoir_matches_the_known_motion(self, gold: tuple[np.ndarray, np.ndarray]) -> None:
        metrics = self._metrics(gold)
        assert metrics is not None
        # The fixture's reservoir ends at ry 46 vs 40 at ED; on this roof arc
        # that is ≈ +6.4 % of arc length (the strain follows the arc).
        assert metrics.reservoir_pct == pytest.approx(_arc_strain_pct(46.0), abs=3.0)
        assert metrics.reservoir_index >= 8

    def test_booster_reaches_the_known_negative(self, gold: tuple[np.ndarray, np.ndarray]) -> None:
        metrics = self._metrics(gold)
        assert metrics is not None
        # Booster = strain at the diastasis plateau (ry 42.4 ≈ +2.5 %) minus
        # the contracted minimum (ry 36 ≈ −4.1 %).
        expected = _arc_strain_pct(42.4) - _arc_strain_pct(36.0)
        assert metrics.booster_pct is not None
        assert metrics.booster_pct == pytest.approx(expected, abs=4.0)

    def test_curve_zero_at_ed(self, gold: tuple[np.ndarray, np.ndarray]) -> None:
        frames, ed_arc = gold
        tracked = track_la_arc(frames, ed_arc, 0, SpeckleConfig.preset_standard(), kernel_radius=6)
        assert tracked is not None
        curve = compute_la_strain_curve(tracked[0], ed_index=0, pixel_spacing=SPACING)
        assert curve[0] == pytest.approx(0.0, abs=1e-9)

    def test_anchor_away_from_ed_still_zeros_at_ed(self, gold: tuple[np.ndarray, np.ndarray]) -> None:
        frames, ed_arc = gold
        # An ES-drawn contour anchors at frame 12; the curve is still zeroed at ED.
        tracked = track_la_arc(frames, ed_arc, 12, SpeckleConfig.preset_standard(), kernel_radius=6)
        assert tracked is not None
        curve = compute_la_strain_curve(tracked[0], ed_index=0, pixel_spacing=SPACING)
        assert curve[0] == pytest.approx(0.0, abs=1e-9)


class TestSelectContour:
    def _contour(self, **kwargs: object) -> Contour:
        defaults: dict[str, object] = {
            "phase": "ed",
            "view": "A4C",
            "chamber": "LA",
            "points": [(10.0, 20.0), (30.0, 20.0), (50.0, 20.0)],
            "frame_index": 5,
            "sop_instance_uid": "uid-1",
        }
        defaults.update(kwargs)
        return Contour(**defaults)  # type: ignore[arg-type]

    def test_prefers_ed_of_this_instance_and_view(self) -> None:
        contours = (
            self._contour(phase="es", frame_index=9),
            self._contour(),
            self._contour(view="A2C"),
            self._contour(sop_instance_uid="uid-other"),
        )
        chosen = select_la_strain_contour(contours, sop_instance_uid="uid-1", view="A4C")
        assert chosen is not None
        points, frame = chosen
        assert frame == 5
        assert points[0][0] == pytest.approx(10.0)

    def test_es_used_when_no_ed(self) -> None:
        chosen = select_la_strain_contour(
            (self._contour(phase="es", frame_index=9),), sop_instance_uid="uid-1", view="A4C"
        )
        assert chosen is not None and chosen[1] == 9

    def test_pending_or_frameless_or_foreign_are_skipped(self) -> None:
        contours = (
            self._contour(review_pending=True),
            self._contour(frame_index=None),
            self._contour(sop_instance_uid="other"),
            self._contour(chamber="LV"),
        )
        assert select_la_strain_contour(contours, sop_instance_uid="uid-1", view="A4C") is None
