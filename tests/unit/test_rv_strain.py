"""RV strain — free-wall GLS (plan А.7, issue #645).

Pure-domain tests: the GLS read from the curve (peak negative ED→ES, honest
gaps), the free-wall contour selection (an FAC cavity trace is never picked)
and the end-to-end synthetic-gold tracking test — a cine whose bright free
wall shortens by a known amount must reproduce the known strain number within
tolerance (the acceptance item «согласие с референсами»).
"""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.models.contour import RV_FREE_WALL_CHAMBER, Contour
from echo_personal_tool.domain.models.speckle import SpeckleConfig
from echo_personal_tool.domain.services.rv_strain import (
    compute_rv_gls,
    select_rv_free_wall_contour,
    track_rv_free_wall,
)

SPACING = (0.5, 0.5)


def _wall_points(x: float = 150.0, y0: float = 40.0, y1: float = 160.0, n: int = 9) -> np.ndarray:
    """A straight vertical free wall (annulus at the top, apex at the bottom)."""
    ys = np.linspace(y0, y1, n)
    return np.stack([np.full(n, x), ys], axis=1)


def _polyline_length(pts: np.ndarray) -> float:
    return float(np.sum(np.linalg.norm(np.diff(pts, axis=0), axis=1)))


def _synthetic_rv_cine(
    *,
    n_frames: int = 20,
    size: int = 220,
    systole_end: int = 10,
    shortening: float = 0.20,
    seed: int = 11,
) -> tuple[np.ndarray, np.ndarray, float]:
    """A textured cine whose bright free wall shortens by a known fraction.

    Returns ``(frames, ed_wall, expected_gls_pct)``. The wall scales toward
    its centroid by ``1 - shortening`` linearly over frames 0..systole_end
    (systole) and relaxes back afterwards — under a uniform scale the polyline
    length scales by the same factor, so the expected strain is
    ``-shortening · 100 %`` exactly.
    """
    rng = np.random.default_rng(seed)
    base = rng.uniform(40.0, 160.0, size=(size, size)).astype(np.float32)
    frames = np.zeros((n_frames, size, size), dtype=np.float32)
    yy = np.arange(size, dtype=np.float64)
    ed_wall = _wall_points(x=150.0, y0=40.0, y1=160.0)
    centroid_y = float(ed_wall[:, 1].mean())
    expected_gls_pct = -shortening * 100.0

    def scale_at(t: int) -> float:
        if t <= systole_end:
            return 1.0 - shortening * t / systole_end
        if t < n_frames:
            return (1.0 - shortening) + shortening * (t - systole_end) / (n_frames - 1 - systole_end)
        return 1.0

    # The whole field compresses with the wall (the background texture is the
    # motion carrier — a narrow bright band alone leaves the end kernels with
    # nothing structured to follow): row *y* of frame *t* shows the ED
    # texture row the wall maps there. The bright band is painted over the
    # compressed wall afterwards so the nodes sit on the wall itself.
    for t in range(n_frames):
        scale = scale_at(t)
        y_ed = centroid_y + (yy - centroid_y) / scale
        moved = np.stack([np.interp(y_ed, yy, base[:, x]) for x in range(size)], axis=1)
        frames[t] = moved + rng.normal(0.0, 4.0, size=(size, size))
        wall_t = centroid_y + (ed_wall[:, 1] - centroid_y) * scale
        for y in range(max(int(wall_t.min()) - 6, 0), min(int(wall_t.max()) + 6, size - 1)):
            frames[t, y, 148:153] = 230.0
    return frames.astype(np.float32), ed_wall, expected_gls_pct


class TestComputeRvGls:
    def test_peak_negative_inside_the_systolic_window(self) -> None:
        curve = np.array([0.0, -6.0, -14.0, -20.0, -16.0, -4.0, -2.0])
        metrics = compute_rv_gls(curve, ed_index=0, es_index=4)
        assert metrics is not None
        assert metrics.gls_pct == pytest.approx(-20.0)
        assert metrics.gls_index == 3
        assert metrics.warnings == ()

    def test_no_es_window_is_no_metric(self) -> None:
        """A window without systole cannot carry a systolic peak."""
        assert compute_rv_gls(np.array([0.0, -5.0, -10.0]), ed_index=0, es_index=1) is None

    def test_no_finite_sample_is_no_metric(self) -> None:
        curve = np.array([np.nan, np.nan, np.nan, np.nan, np.nan])
        assert compute_rv_gls(curve, ed_index=0, es_index=4) is None

    def test_lost_frame_never_wins_the_peak(self) -> None:
        curve = np.array([0.0, -8.0, np.nan, -18.0, -6.0])
        metrics = compute_rv_gls(curve, ed_index=0, es_index=4)
        assert metrics is not None
        assert metrics.gls_pct == pytest.approx(-18.0)
        assert metrics.gls_index == 3

    def test_flat_window_warns_but_keeps_the_measurement(self) -> None:
        curve = np.array([0.0, -0.4, -0.5, -0.3, -0.1])
        metrics = compute_rv_gls(curve, ed_index=0, es_index=4)
        assert metrics is not None
        assert metrics.gls_pct == pytest.approx(-0.5)
        assert "rv_strain.no_systolic_shortening" in metrics.warnings


class TestSelection:
    def test_free_wall_trace_is_selected_ed_first(self) -> None:
        ed = Contour(
            phase="ed",
            view="A4C",
            chamber=RV_FREE_WALL_CHAMBER,
            points=[tuple(p) for p in _wall_points()],
            frame_index=3,
        )
        choice = select_rv_free_wall_contour((ed,), sop_instance_uid=None, view="A4C")
        assert choice is not None
        pts, frame = choice
        assert frame == 3
        assert pts.shape == (9, 2)

    def test_es_trace_loses_to_ed(self) -> None:
        ed = Contour(
            phase="ed",
            view="A4C",
            chamber=RV_FREE_WALL_CHAMBER,
            points=[tuple(p) for p in _wall_points()],
            frame_index=3,
        )
        es = Contour(
            phase="es",
            view="A4C",
            chamber=RV_FREE_WALL_CHAMBER,
            points=[tuple(p) for p in _wall_points()],
            frame_index=5,
        )
        choice = select_rv_free_wall_contour((es, ed), sop_instance_uid=None, view="A4C")
        assert choice is not None
        assert choice[1] == 3

    def test_fac_cavity_trace_is_never_picked(self) -> None:
        """The RV FAC area trace is chamber RV — a different contour kind."""
        fac = Contour(
            phase="ed",
            view="A4C",
            chamber="RV",
            points=[tuple(p) for p in _wall_points()],
            frame_index=3,
        )
        assert select_rv_free_wall_contour((fac,), sop_instance_uid=None, view="A4C") is None

    def test_other_clip_other_view_pending_are_skipped(self) -> None:
        uid = "1.2.3"
        good = Contour(
            phase="ed",
            view="A4C",
            chamber=RV_FREE_WALL_CHAMBER,
            points=[tuple(p) for p in _wall_points()],
            frame_index=2,
            sop_instance_uid=uid,
        )
        foreign = Contour(
            phase="ed",
            view="A4C",
            chamber=RV_FREE_WALL_CHAMBER,
            points=[tuple(p) for p in _wall_points()],
            frame_index=8,
            sop_instance_uid="9.9.9",
        )
        other_view = Contour(
            phase="ed",
            view="A2C",
            chamber=RV_FREE_WALL_CHAMBER,
            points=[tuple(p) for p in _wall_points()],
            frame_index=9,
        )
        pending = Contour(
            phase="ed",
            view="A4C",
            chamber=RV_FREE_WALL_CHAMBER,
            points=[tuple(p) for p in _wall_points()],
            frame_index=7,
            review_pending=True,
        )
        no_frame = Contour(
            phase="ed",
            view="A4C",
            chamber=RV_FREE_WALL_CHAMBER,
            points=[tuple(p) for p in _wall_points()],
            frame_index=None,
        )
        choice = select_rv_free_wall_contour(
            (foreign, other_view, pending, no_frame, good), sop_instance_uid=uid, view="A4C"
        )
        assert choice is not None
        assert choice[1] == 2


class TestTraceToContour:
    """The finished freehand trace becomes its contour kind (plan А.7)."""

    def test_free_wall_trace_is_an_open_line_without_annulus(self) -> None:
        from echo_personal_tool.domain.services.contour_geometry import freehand_open_arc_contour

        contour = freehand_open_arc_contour(
            [tuple(p) for p in _wall_points()],
            chamber=RV_FREE_WALL_CHAMBER,
            phase="ed",
            view="A4C",
            frame_index=4,
            unassisted=True,
        )
        assert contour.chamber == RV_FREE_WALL_CHAMBER
        assert contour.mitral_annulus is None  # a wall is not a cavity — nothing closes it
        assert contour.apex_landmark is None
        assert contour.is_open_arc is False  # and so it never reaches the edge snap
        assert contour.frame_index == 4
        assert contour.unassisted is True
        assert len(contour.points) >= 3

    def test_cavity_trace_keeps_the_annulus_chord(self) -> None:
        from echo_personal_tool.domain.services.contour_geometry import freehand_open_arc_contour

        pts = [tuple(p) for p in _wall_points()]
        contour = freehand_open_arc_contour(
            pts,
            chamber="LA",
            phase="es",
            view="A4C",
            frame_index=2,
            unassisted=False,
        )
        assert contour.mitral_annulus == (pts[0], pts[-1])  # the cavity contract (А.6)
        assert contour.apex_landmark is not None
        assert contour.is_open_arc is True


class TestSyntheticGold:
    def test_known_wall_shortening_reproduces_the_gls(self) -> None:
        """The gold test: a wall shortening by 20 % reads ≈ −20 % RV GLS."""
        frames, ed_wall, expected = _synthetic_rv_cine()
        tracked = track_rv_free_wall(
            frames,
            ed_wall,
            0,
            SpeckleConfig.preset_standard(),
            kernel_radius=6,
        )
        assert tracked is not None
        positions, ncc_mean, _valid = tracked
        assert ncc_mean > 0.5
        from echo_personal_tool.domain.services.arc_strain import arc_strain_curve

        curve = arc_strain_curve(positions, ed_index=0, pixel_spacing=SPACING)
        assert curve[0] == pytest.approx(0.0, abs=1e-9)
        metrics = compute_rv_gls(curve, ed_index=0, es_index=10)
        assert metrics is not None
        assert metrics.gls_pct == pytest.approx(expected, abs=4.0)

    def test_too_short_trace_is_not_tracked(self) -> None:
        frames, _wall, _expected = _synthetic_rv_cine()
        assert (
            track_rv_free_wall(frames, _wall_points(n=2), 0, SpeckleConfig.preset_standard(), kernel_radius=6) is None
        )


class TestCavityFallback:
    """The FAC-style closed RV cavity contour as a strain source (follow-up).

    The physician asked to reuse the cavity outline he already draws for FAC
    instead of tracing a second, dedicated free-wall arc. The wall is derived
    geometrically: the septum is the cavity side facing the LV, so the free
    wall is the arc of the cavity border facing away from the LV centroid of
    the same clip. A dedicated RV_FW trace always wins; without an LV contour
    the septal side is unknowable and nothing is selected.
    """

    @staticmethod
    def _cavity_points(cx: float, cy: float, rx: float = 60.0, ry: float = 50.0, n: int = 32) -> list[tuple[float, float]]:
        angles = np.linspace(0.0, 2.0 * np.pi, n, endpoint=False)
        return [(float(cx + rx * np.cos(a)), float(cy + ry * np.sin(a))) for a in angles]

    def test_cavity_contour_with_lv_yields_the_far_arc(self) -> None:
        # RV cavity right of centre, LV far to the left: the free wall is the
        # right side of the cavity border.
        cavity = self._cavity_points(300.0, 200.0)
        lv = Contour(phase="ed", view="A4C", chamber="LV", points=self._cavity_points(80.0, 200.0), frame_index=3)
        rv = Contour(phase="ed", view="A4C", chamber="RV", points=cavity, frame_index=3)
        choice = select_rv_free_wall_contour((rv, lv), sop_instance_uid=None, view="A4C")
        assert choice is not None
        arc, frame = choice
        assert frame == 3
        assert len(arc) >= 6
        assert float(arc[:, 0].min()) >= 300.0  # only points at/behind the far edge

    def test_cavity_without_lv_contour_selects_nothing(self) -> None:
        """No LV on the clip → septum unknowable → an honest refusal."""
        rv = Contour(phase="ed", view="A4C", chamber="RV", points=self._cavity_points(300.0, 200.0), frame_index=3)
        assert select_rv_free_wall_contour((rv,), sop_instance_uid=None, view="A4C") is None

    def test_dedicated_trace_wins_over_the_cavity(self) -> None:
        wall = _wall_points()
        rv_fw = Contour(phase="ed", view="A4C", chamber=RV_FREE_WALL_CHAMBER, points=[tuple(p) for p in wall], frame_index=2)
        rv = Contour(phase="ed", view="A4C", chamber="RV", points=self._cavity_points(300.0, 200.0), frame_index=3)
        lv = Contour(phase="ed", view="A4C", chamber="LV", points=self._cavity_points(80.0, 200.0), frame_index=3)
        choice = select_rv_free_wall_contour((rv, lv, rv_fw), sop_instance_uid=None, view="A4C")
        assert choice is not None
        pts, frame = choice
        assert frame == 2
        assert pts.shape == wall.shape

    def test_es_cavity_loses_to_ed_cavity(self) -> None:
        ed_lv = Contour(phase="ed", view="A4C", chamber="LV", points=self._cavity_points(80.0, 200.0), frame_index=3)
        ed_rv = Contour(phase="ed", view="A4C", chamber="RV", points=self._cavity_points(300.0, 200.0), frame_index=3)
        es_rv = Contour(phase="es", view="A4C", chamber="RV", points=self._cavity_points(300.0, 200.0), frame_index=8)
        choice = select_rv_free_wall_contour((es_rv, ed_rv, ed_lv), sop_instance_uid=None, view="A4C")
        assert choice is not None
        assert choice[1] == 3

    def test_degenerate_geometry_is_refused(self) -> None:
        """A cavity whose wall cannot be told from the septum produces nothing."""
        cavity = self._cavity_points(300.0, 200.0)
        same_spot_lv = Contour(phase="ed", view="A4C", chamber="LV", points=self._cavity_points(300.0, 200.0), frame_index=3)
        rv = Contour(phase="ed", view="A4C", chamber="RV", points=cavity, frame_index=3)
        assert select_rv_free_wall_contour((rv, same_spot_lv), sop_instance_uid=None, view="A4C") is None

    def test_free_wall_arc_extraction_units(self) -> None:
        from echo_personal_tool.domain.services.rv_strain import free_wall_arc_from_cavity

        cavity = np.asarray(self._cavity_points(300.0, 200.0))
        arc = free_wall_arc_from_cavity(cavity, np.asarray([80.0, 200.0]))
        assert arc is not None and len(arc) >= 6
        assert free_wall_arc_from_cavity(cavity[:4], np.asarray([80.0, 200.0])) is None
        assert free_wall_arc_from_cavity(cavity, np.asarray([300.0, 200.0])) is None  # no separation
