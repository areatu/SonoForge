"""Synthetic kinematic phantom for the STE module (plan rev.4 §7.1).

Purpose
-------
Every part of the STE pipeline (border propagation, kernel tracking, node and
segment curves, QC, metrics) has to be checked against a case where the true
motion is known exactly. Vendor clips cannot do that: they give a number, not a
ground truth, and there are no clips in CI.

The phantom generates an apical-view cine from an **exact, invertible
displacement field** and therefore knows:

* the true trajectory of every material point (so the tracked positions can be
  compared directly, not only the derived strain);
* the true strain curve of the endocardial material line, computed with the very
  same definition the module reports (clinical Lagrange strain,
  ``(L − L0)/L0``), so ``measured − true`` isolates tracking/geometry error;
* the true per-segment curves, ESS, peak and time-to-peak;
* an AHA segment map for the ground-truth endocardial arc.

Deformation modes
-----------------
``uniform``   — isotropic scaling (incompressible-free). Every material line is
                scaled by exactly the same factor, so the true strain is the
                same everywhere: the reference case for the "−20 %" KPI.
``long_axis`` — physiological: shortening along the long axis about the annulus
                plane with transverse (wall-thickening) compensation
                ``s_x = 1 / (1 + e)``. Strain varies along the arc by geometry,
                the ground truth is the analytic arc strain.
``gradient``  — ``long_axis`` with an apex↔base strain gradient
                (``apex_base_gradient``), used to check that the segment map
                puts the deformation in the right segments.

Optional rigid motion (rotation about the cavity centre and translation) is
applied *on top* of the deformation and must not change any strain value.

Image simulation
----------------
Reference speckle pattern (Rayleigh amplitude) × reflectivity map (dark cavity,
brighter myocardium, specular mitral annulus and epicardium), then per frame:
warp by the exact map, progressive decorrelation (replacing a growing fraction
of the speckle field), out-of-plane loss, Gaussian noise at the requested SNR,
and finally a slight blur — i.e. the failure modes the tracker meets in reality.

Usage
-----
>>> phantom = StePhantom(StePhantomConfig.quick())
>>> frames = phantom.frames()               # (n_frames, H, W) uint8
>>> truth = phantom.ground_truth()          # curves/metrics for comparison
>>> zone = phantom.zone()                   # MyocardialZone for the worker
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import cv2
import numpy as np
from scipy.ndimage import gaussian_filter, map_coordinates

from echo_personal_tool.domain.models.speckle import MyocardialZone
from echo_personal_tool.domain.services.segment_map import assign_segments_from_arc
from echo_personal_tool.domain.services.strain_computation import (
    aggregate_segment_curves,
    compute_node_longitudinal_curves,
    global_curve_from_node_curves,
    lagrangian_strain_pct,
)
from echo_personal_tool.domain.services.strain_metrics import compute_strain_metrics


@dataclass(frozen=True)
class StePhantomConfig:
    """Geometry, motion and image parameters of the phantom."""

    # ── image
    width: int = 360
    height: int = 320
    n_frames: int = 46
    pixel_spacing_mm: float = 0.45
    rr_ms: float = 900.0
    seed: int = 7

    # ── geometry (mm)
    cavity_long_mm: float = 90.0
    cavity_short_mm: float = 60.0
    wall_mm: float = 8.0
    apex_margin_mm: float = 30.0  # free space above the apex

    # ── motion
    peak_strain: float = -0.20  # Lagrange strain at the peak frame (fraction)
    peak_time_frac: float = 0.35  # peak position in the cycle (0..1)
    apex_base_gradient: float = 0.0  # extra strain from apex (−) to base (+)
    circumferential_ratio: float = 0.75  # circumferential / longitudinal strain (in plane)
    mode: str = "long_axis"  # "long_axis" | "uniform" | "rigid"
    # Clinical anchoring of the deformation: a real apical clip shows a nearly
    # still apex (fixed against the liver/chest wall) and an annulus that
    # descends toward it. "annulus" keeps the annulus plane fixed and moves the
    # apex instead — useful to show that the *measurement* is frame-independent.
    anchor: str = "apex"  # "apex" | "annulus"
    # Deformation is confined to the heart: the surrounding tissue (chest wall,
    # lungs) stays put, as it does in a real clip. Without this the whole image
    # translates with the heart and the consumer's global-motion compensation
    # would subtract genuine cardiac motion.
    static_background: bool = True
    # Width of the transition band in which the surrounding tissue progressively
    # stops following the heart, as a multiple of the systolic excursion. It has
    # to be wide: the band carries a displacement of tens of pixels, and a steep
    # weight ramp would fold the warped image (a tear) — and a folded map has no
    # inverse at all. Two excursions keep the blend's Jacobian positive while
    # still leaving the image border static.
    deform_halo: float = 2.0
    rotation_deg: float = 0.0  # rigid rotation amplitude about the cavity centre
    translation_px: tuple[float, float] = (0.0, 0.0)  # rigid translation per frame
    post_systolic_frac: float = 0.0  # delay of the peak beyond AVC, as a cycle fraction

    # ── image quality
    speckle_sigma_px: float = 1.6  # speckle size (blur of the speckle field)
    noise_db: float = 20.0  # speckle SNR in dB (0 → very noisy)
    decorrelation: float = 0.35  # fraction of speckle replaced over the clip
    out_of_plane: float = 0.0  # extra per-frame speckle replacement
    # Material reflectivity structure: real myocardium is not a smooth shell —
    # trabeculae, fibre orientation and fibrosis give bright/dark patches that
    # move *with* the wall. Without them a block inside the wall matches equally
    # well at any position *along* the wall (aperture problem) and the tracked
    # position slides tangentially by several millimetres, which no tracker can
    # recover because the information is simply not in the image.
    tissue_grain_contrast: float = 0.35  # relative amplitude of the patches
    tissue_grain_mm: float = 4.0  # patch size in millimetres
    background_level: float = 0.18  # brightness outside the myocardium
    cavity_level: float = 0.10  # brightness of the blood pool
    myocardium_level: float = 0.62  # brightness of the myocardium
    blur_sigma_px: float = 0.4  # final PSF blur

    @classmethod
    def quick(cls, **overrides) -> StePhantomConfig:
        """Small, fast configuration for CI (plan §7.1: 200×200, ~10 frames).

        The heart is scaled to half size so the whole ventricle fits the small
        image at the same pixel spacing. Pixel spacing and strain are
        scale-invariant, and halving the geometry also halves the per-frame
        motion in pixels (≈2.5 px/frame, as in a real 46-frame clip) instead of
        asking the tracker for an unrealistically fast wall.
        """
        base = cls(
            width=200,
            height=200,
            n_frames=20,
            pixel_spacing_mm=0.45,
            cavity_long_mm=45.0,
            cavity_short_mm=30.0,
            wall_mm=5.0,
            apex_margin_mm=20.0,  # room above the apex for probe translation in tests
        )
        return replace(base, **overrides) if overrides else base

    @property
    def frame_time_ms(self) -> float:
        return float(self.rr_ms) / max(int(self.n_frames), 1)

    @property
    def avc_index(self) -> int:
        """Frame of aortic valve closure (coincides with the peak by default)."""
        return int(round(float(self.peak_time_frac) * (self.n_frames - 1)))

    @property
    def es_index(self) -> int:
        """Frame of the strain peak (may be post-systolic)."""
        frac = min(float(self.peak_time_frac) + float(self.post_systolic_frac), 0.95)
        return int(round(frac * (self.n_frames - 1))) if frac > 0 else 0


def _strain_profile(n_frames: int, peak: float, peak_frac: float, post_systolic_frac: float) -> np.ndarray:
    """Physiological strain curve: systolic shortening, then recovery to 0.

    Shortening follows a half-sine up to the peak, then recovers to baseline as
    the ventricle refills, so the curve starts and ends at zero — the property
    that makes the drift measurement meaningful. The profile is written as a
    closed-form function of the frame index: reading values back from the array
    while filling it (the first implementation) silently returned zero for the
    recovery branch and froze the deformation after the peak.
    """
    frames = np.arange(n_frames, dtype=np.float64)
    last = float(max(n_frames - 1, 1))
    peak_frame = float(peak_frac) * last
    post_frame = float(peak_frac + post_systolic_frac) * last

    def value(frame: np.ndarray) -> np.ndarray:
        out = np.zeros_like(frame)
        systolic = frame <= peak_frame
        if peak_frame > 0:
            out[systolic] = peak * np.sin(0.5 * np.pi * frame[systolic] / peak_frame)
        if post_frame > peak_frame:
            late = (~systolic) & (frame <= post_frame)
            out[late] = peak + 0.35 * peak * np.sin(
                0.5 * np.pi * (frame[late] - peak_frame) / (post_frame - peak_frame)
            )
        start_value = peak + (0.35 * peak if post_frame > peak_frame else 0.0)
        recovery = frame > post_frame
        if np.any(recovery):
            span = max(last - post_frame, 1e-9)
            phase = (frame[recovery] - post_frame) / span
            out[recovery] = start_value * (1.0 - phase**1.5)
        return out

    return value(frames)


@dataclass
class PhantomGroundTruth:
    """Everything the phantom knows about the truth (the comparison target)."""

    config: StePhantomConfig
    long_axis_strain: np.ndarray  # applied long-axis strain per frame (fraction)
    arc_curve: np.ndarray  # definition A: Lagrange strain of the whole endocardial arc, %
    line_curve: np.ndarray  # definition B (clinical GLS): mean of the node curves at each frame, %
    epi_curve: np.ndarray
    node_curves: np.ndarray  # (n_frames, n_nodes) true node curves, %
    segment_curves: dict[int, np.ndarray]
    segment_values: dict[int, float]  # peak per segment, %
    segment_ttp_ms: dict[int, float]
    ess: float
    peak: float
    time_to_peak_ms: float
    drift: float
    avc_index: int
    es_index: int
    endo_points_ed: np.ndarray
    endo_points_es: np.ndarray
    apex_index: int
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        """JSON-serialisable summary (used by bench/ste_phantom.py)."""
        return {
            "peak_strain_requested": self.config.peak_strain,
            "long_axis_strain_at_es": float(self.long_axis_strain[self.config.es_index]),
            "arc_curve_peak": float(np.nanmin(self.arc_curve)),
            "line_curve_peak": self.peak,
            "ess": self.ess,
            "time_to_peak_ms": self.time_to_peak_ms,
            "drift": self.drift,
            "avc_index": self.avc_index,
            "es_index": self.es_index,
            "segment_peak_values": {str(k): v for k, v in sorted(self.segment_values.items())},
            "segment_ttp_ms": {str(k): v for k, v in sorted(self.segment_ttp_ms.items())},
            "notes": list(self.notes),
        }


class StePhantom:
    """Apical-view phantom with an exact ground truth."""

    MIN_ARC_NODES = 48

    def __init__(self, config: StePhantomConfig | None = None) -> None:
        self.config = config or StePhantomConfig()
        cfg = self.config
        if cfg.n_frames < 3:
            raise ValueError("a phantom needs at least three frames")
        self._rng = np.random.default_rng(cfg.seed)
        self._px = float(cfg.pixel_spacing_mm)

        # ── geometry in pixels (apex at the top of the image, as in an apical view)
        self._cx = cfg.width / 2.0
        self._apex_y = cfg.apex_margin_mm / self._px
        self._base_y = self._apex_y + cfg.cavity_long_mm / self._px
        self._a_endo = cfg.cavity_short_mm / 2.0 / self._px
        self._a_epi = self._a_endo + cfg.wall_mm / self._px
        self._long_px = cfg.cavity_long_mm / self._px
        self._long_epi_px = (cfg.cavity_long_mm + cfg.wall_mm) / self._px

        self._strain = _strain_profile(cfg.n_frames, cfg.peak_strain, cfg.peak_time_frac, cfg.post_systolic_frac)
        self._endo_ed = self._arc(n_nodes=max(self.MIN_ARC_NODES, 65), epi=False)
        self._epi_ed = self._arc(n_nodes=max(self.MIN_ARC_NODES, 65), epi=True)
        self._cavity_centre_ed = np.array([self._cx, self._apex_y + self._long_px / 2.0])
        self._weight_map: np.ndarray | None = None
        self._moving: np.ndarray | None = None

    # ── geometry ────────────────────────────────────────────────────────────

    def _arc(self, n_nodes: int, *, epi: bool) -> np.ndarray:
        """Reference (ED) endocardial/epicardial arc, annulus → apex → annulus."""
        theta = np.linspace(0.0, np.pi, n_nodes)
        a = self._a_epi if epi else self._a_endo
        length = self._long_epi_px if epi else self._long_px
        x = self._cx + a * np.cos(theta)
        y = self._base_y - length * np.sin(theta)
        return np.column_stack([x, y])

    def reference_endo_arc(self, n_nodes: int = MIN_ARC_NODES) -> np.ndarray:
        """ED endocardial arc with ``n_nodes`` nodes in arc order (for tests)."""
        return self._arc(int(n_nodes), epi=False)

    def reference_epi_arc(self, n_nodes: int = MIN_ARC_NODES) -> np.ndarray:
        return self._arc(int(n_nodes), epi=True)

    def zone(self) -> MyocardialZone:
        """The myocardial zone the worker would receive (drawn at ED)."""
        return MyocardialZone(
            endo_points=self.reference_endo_arc().copy(),
            epi_points=self.reference_epi_arc().copy(),
            thickness_mm=self.config.wall_mm,
            pixel_spacing=(self._px, self._px),
        )

    def apex_index(self, n_nodes: int = MIN_ARC_NODES) -> int:
        return int(n_nodes) // 2

    # ── exact deformation ───────────────────────────────────────────────────

    def long_axis_strain(self) -> np.ndarray:
        """The applied (reference) long-axis strain curve, as a fraction."""
        return self._strain.copy()

    def _local_long_strain(self, d: np.ndarray | float, frame: int) -> np.ndarray | float:  # noqa: D401
        """Long-axis strain at distance ``d`` from the anchor plane (fraction).

        ``apex_base_gradient > 0`` gives the normal apex-dominant pattern
        (apical segments shorten more); a negative gradient models apical
        sparing, the pattern that makes a global GLS look "normal" while the
        apex is akinetic.
        """
        e = float(self._strain[frame])
        if self.config.apex_base_gradient and self._long_epi_px > 1e-6:
            # Positive gradient = apex-dominant shortening (the normal pattern):
            # apical segments reach a larger |strain| than basal ones.
            relative = np.asarray(d, dtype=np.float64) / self._long_epi_px
            local = e * (1.0 + self.config.apex_base_gradient * (0.5 - relative))
            return local
        return e

    def _rigid(self, frame: int) -> tuple[np.ndarray, float, np.ndarray]:
        """Rigid part of the map: rotation centre, angle and translation.

        The rigid component grows linearly during the cycle (as the whole heart
        swings in the chest), so ED — frame 0 — stays the reference and every
        later frame carries a genuine rigid offset. Rigid motion must leave all
        strain values unchanged; that is invariant §7.2.1.
        """
        cfg = self.config
        progress = frame / max(cfg.n_frames - 1, 1)
        angle = float(np.radians(cfg.rotation_deg) * progress)
        translation = np.asarray(cfg.translation_px, dtype=np.float64) * progress
        centre = self._cavity_centre_deformed(frame)
        return centre, angle, translation

    def region_weight(self, points: np.ndarray) -> np.ndarray:
        """How much of the material motion a point carries (1 heart, 0 outside).

        The deformation is confined to the heart and a smooth halo around it
        (``deform_halo``, as a fraction of the cavity semi-axis); tissue beyond
        that stays static, exactly like the chest wall in a real clip. A
        whole-image motion estimator therefore sees no spurious global motion
        while the myocardium itself moves fully.
        """
        if not self.config.static_background:
            return np.ones(len(np.asarray(points)), dtype=np.float64)
        return self._sample_weight_map(np.asarray(points, dtype=np.float64))

    def _build_weight_map(self) -> None:
        """Static-background weight for the whole image (1 heart, 0 far tissue)."""
        cfg = self.config
        mask = np.zeros((cfg.height, cfg.width), dtype=np.uint8)
        # 1) the ventricle itself: the epicardial arc closed across the annulus.
        epi_closed = np.vstack([self._epi_ed, self._epi_ed[::-1][-1:]])
        cv2.fillPoly(mask, [epi_closed.astype(np.int32)], 1)
        # 2) the mitral annulus band. The annulus is part of the heart and
        # descends with the base, so the tissue band at and above the annulus
        # plane must move too. Leaving it static made the basal kernel patches
        # half static tissue: their matches found no displacement at all while
        # the wall around them moved 20 px, and those columns dominated the
        # arc-length strain (plan §7.5, F10). The band is added as a separate
        # polygon because extending the ventricular outline crosses the
        # epicardial arc and makes the fill self-intersect.
        margin = float(self._max_motion_px())
        x_lo = float(min(self._epi_ed[:, 0].min(), self._endo_ed[:, 0].min()))
        x_hi = float(max(self._epi_ed[:, 0].max(), self._endo_ed[:, 0].max()))
        band = np.array(
            [
                [x_lo, self._base_y - margin],
                [x_hi, self._base_y - margin],
                [x_hi, self._base_y + margin],
                [x_lo, self._base_y + margin],
            ],
            dtype=np.int32,
        )
        cv2.fillPoly(mask, [band], 1)
        halo_px = self._halo_px()
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        dilated = cv2.dilate(mask, kernel)
        outside = cv2.distanceTransform((1 - dilated).astype(np.uint8), cv2.DIST_L2, 3)
        weight = np.clip(1.0 - outside / max(halo_px, 1e-6), 0.0, 1.0)
        # Inside the heart the motion is complete; only the outside tapers.
        weight[mask > 0] = 1.0
        weight = np.where(weight >= 1.0, 1.0, weight * weight * (3.0 - 2.0 * weight))
        self._weight_map = weight.astype(np.float64)
        # Every pixel that can possibly be reached by moving tissue. Outside it
        # the map is the identity, so the (expensive) inverse family solve can
        # be skipped — this is what keeps ``frames()`` fast on a full sector.
        margin = self._max_motion_px() + halo_px
        margin_px = int(2 * round(margin) + 1)
        big_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (margin_px, margin_px))
        self._moving = cv2.dilate(mask, big_kernel) > 0

    def _halo_px(self) -> float:
        """Ramp width (px) over which the surrounding tissue stops moving."""
        cfg = self.config
        strain = float(np.max(np.abs(self._strain))) if self._strain.size else 0.0
        excursion = strain * self._long_px * (1.0 + 0.5 * abs(float(cfg.apex_base_gradient)))
        return max(4.0, float(cfg.deform_halo) * excursion)

    def _max_motion_px(self) -> float:
        """Upper bound (px) on how far a material point travels from ED."""
        cfg = self.config
        strain = float(np.max(np.abs(self._strain))) if self._strain.size else 0.0
        span = self._long_epi_px * (1.0 + strain * (1.0 + 0.5 * abs(float(cfg.apex_base_gradient))))
        rigid = float(np.linalg.norm(cfg.translation_px)) + np.radians(abs(cfg.rotation_deg)) * span
        return float(span * strain + rigid + 2.0)

    def _sample_weight_map(self, points: np.ndarray) -> np.ndarray:
        if self._weight_map is None:
            self._build_weight_map()
        cfg = self.config
        x = np.clip(points[:, 0], 0.0, cfg.width - 1.0)
        y = np.clip(points[:, 1], 0.0, cfg.height - 1.0)
        vals = map_coordinates(self._weight_map, np.stack([y, x]), order=1, mode="nearest")
        return np.clip(np.asarray(vals, dtype=np.float64), 0.0, 1.0)

    def _cavity_centre_deformed(self, frame: int) -> np.ndarray:
        return self._pure_deform(self._cavity_centre_ed[None, :], frame)[0]

    # ── wall coordinates ───────────────────────────────────────────────────
    #
    # The ventricle is described by the one-parameter family of "wall levels"
    #
    #     x = cx + (a0 + q·w)·cos θ ,   y = base − (L0 + q·w)·sin θ
    #
    # with q = 0 on the endocardium, q = 1 on the epicardium (negative inside
    # the cavity, > 1 outside the heart).  Both the deformation and its inverse
    # are trivial in (θ, q), which is what lets the phantom keep the wall
    # thickness physiological: the endocardial surface scales with the
    # longitudinal/tangential strain while the radial direction scales by the
    # incompressibility factor 1/(λ_t·λ_l), i.e. the wall *thickens* in systole
    # (radial strain ≈ +45 % for GLS −20 %).  The previous version applied one
    # isotropic scale to every point, which thinned the wall by 20 % — an
    # impossible heart that made the honest QC report "no radial thickening".

    # ── exact deformation: elliptical-polar wall model ──────────────────────
    #
    # Coordinates. Relative to the annulus-plane centre every point has an
    # *elliptical* radius ``r`` and a ray angle ``phi``::
    #
    #     dx = x - cx, dy = base_y - y
    #     r  = hypot(dx / a0, dy / l0),  phi = atan2(dy / l0, dx / a0)
    #
    # so ``r = 1`` is the endocardial contour, ``r < 1`` the cavity and
    # ``r > 1`` the wall; ``r - 1`` is the wall offset that has to thicken.
    #
    # The map scales three things, all graded by the long-axis level
    # ``sin(phi)`` of the ray (1 at the apex, 0 at the annulus plane), so every
    # transmural layer at one level shortens alike — the assumption behind
    # layer strain reporting:
    #
    #  * longitudinal, by ``lambda_l = 1 + e_l`` about the anchor plane;
    #  * transverse, by ``lambda_t = 1 + circumferential_ratio * e_l``;
    #  * the wall offset, by ``lambda_r = 1 / (lambda_l * lambda_t)`` — the
    #    radial strain incompressibility demands, so the cavity shrinks while
    #    the wall thickens.
    #
    # The image of ``r = 1`` is exactly the resulting endocardial ellipse, the
    # map is a bijection of the whole plane and its inverse is closed form. The
    # previous ``(theta, q)`` family collapsed the isolevels inside the cavity
    # (the iso-ellipses shrink towards the axis), so the warped blood pool
    # disagreed with the endocardial border next to it and the tracker followed
    # that artefact; it also mapped the tissue band below the annulus plane onto
    # the wrong side of the heart.

    def _elliptical_frame(self, points: np.ndarray) -> tuple[np.ndarray, ...]:
        """``(dx, dy, r, phi)`` of ED points in the reference geometry."""
        pts = np.asarray(points, dtype=np.float64)
        dx = pts[:, 0] - self._cx
        dy = self._base_y - pts[:, 1]
        r = np.maximum(np.hypot(dx / self._a_endo, dy / self._long_px), 1e-9)
        phi = np.arctan2(dy / self._long_px, dx / self._a_endo)
        return dx, dy, r, phi

    def _local_long_strain(self, phi: np.ndarray, frame: int) -> np.ndarray:
        """Long-axis strain (fraction) of the wall level met by the rays ``phi``.

        ``apex_base_gradient > 0`` gives the normal apex-dominant pattern
        (apical segments shorten more); a negative gradient models apical
        sparing, the pattern that makes a global GLS look "normal" while the
        apex is akinetic.
        """
        e = float(self._strain[frame])
        gradient = float(self.config.apex_base_gradient)
        rays = np.asarray(phi, dtype=np.float64)
        if not gradient:
            return np.full(rays.shape, e, dtype=np.float64)
        # ``sin(phi)`` is 1 at the apex and 0 at the annulus plane.
        return e * (1.0 + gradient * (np.sin(rays) - 0.5))

    def _strain_factors(self, phi: np.ndarray, frame: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """``(lambda_l, lambda_t, lambda_r)`` of the rays ``phi`` at ``frame``."""
        local = self._local_long_strain(phi, frame)
        # Tangential (circumferential) strain is coupled to the longitudinal one
        # through ``circumferential_ratio``; in the uniform mode the map stays a
        # pure similarity, so every material line shortens by exactly ``e``.
        lambda_l = 1.0 + local
        lambda_t = 1.0 + (local if self.config.mode == "uniform" else self.config.circumferential_ratio * local)
        lambda_r = 1.0 / np.maximum(lambda_l * lambda_t, 1e-6)
        return lambda_l, lambda_t, lambda_r

    def _deform_long_axis(self, points: np.ndarray, frame: int) -> np.ndarray:
        """Apply the pure deformation part (no rigid motion) to points."""
        cfg = self.config
        pts = np.asarray(points, dtype=np.float64)
        if cfg.mode == "rigid":
            return pts.copy()
        dx, _, r, phi = self._elliptical_frame(pts)
        lambda_l, lambda_t, lambda_r = self._strain_factors(phi, frame)
        # Radial strain acts on the offset from the endocardium only: inside the
        # cavity the elliptical radius is preserved, so the blood pool simply
        # shrinks with the cavity instead of collapsing onto the axis.
        radial = np.where(r > 1.0, lambda_r, 1.0)
        gain = radial + (1.0 - radial) / r
        anchor = self._apex_y if cfg.anchor == "apex" else self._base_y
        base = anchor + lambda_l * (self._base_y - anchor)
        x = self._cx + lambda_t * gain * dx
        y = base - lambda_l * gain * (self._base_y - pts[:, 1])
        return np.column_stack([x, y])

    def _pure_deform(self, points: np.ndarray, frame: int) -> np.ndarray:
        """Deformation before the static-background blend (identity for rigid)."""
        return self._deform_long_axis(points, frame)

    def _blended_map(self, points: np.ndarray, frame: int) -> np.ndarray:
        """The material map the image warp uses: pure deformation + static blend."""
        pts = np.asarray(points, dtype=np.float64)
        moved = self._deform_long_axis(pts, frame)
        weight = self.region_weight(pts)[:, None]
        return pts + weight * (moved - pts)

    def deform(self, points: np.ndarray, frame: int) -> np.ndarray:
        """Exact position of material ``points`` at ``frame`` (rigid part included)."""
        pts = np.asarray(points, dtype=np.float64)
        deformed = self._blended_map(pts, frame)
        centre, angle, translation = self._rigid(frame)
        if angle:
            cos_a, sin_a = np.cos(angle), np.sin(angle)
            relative = deformed - centre
            deformed = (
                np.column_stack(
                    [
                        relative[:, 0] * cos_a - relative[:, 1] * sin_a,
                        relative[:, 0] * sin_a + relative[:, 1] * cos_a,
                    ]
                )
                + centre
            )
        return deformed + translation

    def ground_truth_positions(self, n_nodes: int = MIN_ARC_NODES) -> np.ndarray:
        """True (n_frames, n_nodes, 2) endocardial node trajectories."""
        reference = self.reference_endo_arc(n_nodes)
        return np.stack([self.deform(reference, frame) for frame in range(self.config.n_frames)])

    # ── ground-truth strain ─────────────────────────────────────────────────

    def ground_truth_curve(self, n_nodes: int = MIN_ARC_NODES) -> np.ndarray:
        """True strain curve of the endocardial material line (module definition)."""
        reference = self.reference_endo_arc(n_nodes)
        l0 = float(np.sum(np.linalg.norm(np.diff(reference, axis=0), axis=1)))
        curve = np.zeros(self.config.n_frames, dtype=np.float64)
        for frame in range(self.config.n_frames):
            pts = self.deform(reference, frame)
            length = float(np.sum(np.linalg.norm(np.diff(pts, axis=0), axis=1)))
            curve[frame] = lagrangian_strain_pct(length, l0)
        return curve

    def ground_truth(self, n_nodes: int = MIN_ARC_NODES) -> PhantomGroundTruth:
        """Full ground truth: node/segment curves and the metrics derived from them."""
        n_nodes = int(n_nodes)
        reference = self.reference_endo_arc(n_nodes)
        positions = np.stack([self.deform(reference, frame) for frame in range(self.config.n_frames)])
        node_curves = compute_node_longitudinal_curves(positions, 0, (self._px, self._px))
        assignment = assign_segments_from_arc(reference, "A4C")
        segment_curves = aggregate_segment_curves(node_curves, list(assignment.node_segments))
        arc_curve = self.ground_truth_curve(n_nodes)
        line_curve = global_curve_from_node_curves(node_curves)
        epi_reference = self.reference_epi_arc(n_nodes)
        epi_curve = np.zeros(self.config.n_frames, dtype=np.float64)
        l0_epi = float(np.sum(np.linalg.norm(np.diff(epi_reference, axis=0), axis=1)))
        for frame in range(self.config.n_frames):
            pts = self.deform(epi_reference, frame)
            length = float(np.sum(np.linalg.norm(np.diff(pts, axis=0), axis=1)))
            epi_curve[frame] = lagrangian_strain_pct(length, l0_epi)

        metrics = compute_strain_metrics(
            line_curve,
            ed_index=0,
            avc_index=self.config.avc_index,
            window_end=self.config.n_frames - 1,
            frame_time_ms=self.config.frame_time_ms,
        )
        segment_values: dict[int, float] = {}
        segment_ttp: dict[int, float] = {}
        for segment, curve in segment_curves.items():
            seg_metrics = compute_strain_metrics(
                curve,
                ed_index=0,
                avc_index=self.config.avc_index,
                window_end=self.config.n_frames - 1,
                frame_time_ms=self.config.frame_time_ms,
            )
            segment_values[int(segment)] = float(seg_metrics.peak)
            segment_ttp[int(segment)] = float(seg_metrics.time_to_peak_ms)

        notes: list[str] = []
        if self.config.mode == "uniform":
            notes.append("uniform mode: the true strain is identical on every material line")
        else:
            notes.append(
                "long-axis mode: both strain definitions follow from the exact geometry; "
                "definition A (whole arc) and definition B (mean of node curves) differ by design"
            )
        if self.config.decorrelation or self.config.out_of_plane:
            notes.append("progressive speckle decorrelation is enabled (tracking stress test)")

        return PhantomGroundTruth(
            config=self.config,
            long_axis_strain=self._strain.copy(),
            arc_curve=arc_curve,
            line_curve=line_curve,
            epi_curve=epi_curve,
            node_curves=node_curves,
            segment_curves=segment_curves,
            segment_values=segment_values,
            segment_ttp_ms=segment_ttp,
            ess=float(metrics.ess),
            peak=float(metrics.peak),
            time_to_peak_ms=float(metrics.time_to_peak_ms),
            drift=float(metrics.drift),
            avc_index=self.config.avc_index,
            es_index=self.config.es_index,
            endo_points_ed=positions[0].copy(),
            endo_points_es=positions[self.config.es_index].copy(),
            apex_index=self.apex_index(n_nodes),
            notes=tuple(notes),
        )

    def uniform_expected_strain(self) -> float:
        """Exact strain of the ``uniform`` mode at the peak frame, in percent."""
        return float(self._strain[self.config.es_index] * 100.0)

    # ── image simulation ────────────────────────────────────────────────────

    def _speckle_field(self, sigma: float) -> np.ndarray:
        """Unit-variance speckle pattern (Rayleigh amplitude, zero-mean detail)."""
        cfg = self.config
        noise = self._rng.normal(0.0, 1.0, (cfg.height, cfg.width)) + 1j * self._rng.normal(
            0.0, 1.0, (cfg.height, cfg.width)
        )
        pattern = np.abs(gaussian_filter(noise, sigma))
        std = float(pattern.std())
        return (pattern - pattern.mean()) / (std if std > 1e-9 else 1.0)

    def _tissue_grain(self) -> np.ndarray:
        """Low-frequency material reflectivity pattern (fixed to the tissue)."""
        cfg = self.config
        rng = np.random.default_rng(cfg.seed + 3)
        sigma = max(float(cfg.tissue_grain_mm) / self._px / 2.0, 0.5)
        grain = gaussian_filter(rng.normal(0.0, 1.0, (cfg.height, cfg.width)), sigma)
        std = float(grain.std())
        return grain / (std if std > 1e-9 else 1.0)

    def _reflectivity(self) -> np.ndarray:
        """Reference-ED tissue reflectivity map (what the speckle multiplies)."""
        cfg = self.config
        yy, xx = np.mgrid[0 : cfg.height, 0 : cfg.width].astype(np.float64)
        inside_epi = ((xx - self._cx) / self._a_epi) ** 2 + ((yy - self._base_y) / self._long_epi_px) ** 2 <= 1.0
        inside_endo = ((xx - self._cx) / self._a_endo) ** 2 + ((yy - self._base_y) / self._long_px) ** 2 <= 1.0
        cavity = inside_endo & (yy <= self._base_y)
        myocardium = inside_epi & ~cavity
        image = np.full((cfg.height, cfg.width), cfg.background_level, dtype=np.float64)
        image[cavity] = cfg.cavity_level
        image[myocardium] = cfg.myocardium_level
        # Slight transmural gradient (endo brighter than epi, as on many scanners)
        image[myocardium] *= (
            1.0
            - 0.25
            * np.clip(
                (np.sqrt(((xx - self._cx) / self._a_epi) ** 2 + ((yy - self._base_y) / self._long_epi_px) ** 2) - 0.6)
                / 0.4,
                0.0,
                1.0,
            )[myocardium]
        )
        # Material patches inside the wall (trabeculae/fibre structure).
        if cfg.tissue_grain_contrast > 0:
            grain = self._tissue_grain()
            image[myocardium] *= 1.0 + cfg.tissue_grain_contrast * grain[myocardium]
        # Specular epicardium and mitral annulus line
        edge_epi = (
            np.abs(np.sqrt(((xx - self._cx) / self._a_epi) ** 2 + ((yy - self._base_y) / self._long_epi_px) ** 2) - 1.0)
            < 0.02
        )
        image[edge_epi & (yy <= self._base_y)] = 0.95
        annulus_line = np.abs(yy - self._base_y) <= 1.0
        image[annulus_line & (np.abs(xx - self._cx) <= self._a_epi)] = 0.9
        return image

    def _noise_sigma(self) -> float:
        db = float(self.config.noise_db)
        if db >= 60.0:
            return 0.0
        signal = max(float(self.config.myocardium_level), 1e-6)
        return signal / (10 ** (db / 20.0))

    def frames(self) -> np.ndarray:
        """Generate the cine (n_frames, H, W) as uint8."""
        cfg = self.config
        reference = self._reflectivity()
        base_speckle = self._speckle_field(cfg.speckle_sigma_px)
        out = np.zeros((cfg.n_frames, cfg.height, cfg.width), dtype=np.uint8)
        rng = np.random.default_rng(cfg.seed + 1)
        yy, xx = np.mgrid[0 : cfg.height, 0 : cfg.width].astype(np.float64)
        for frame in range(cfg.n_frames):
            warped_coords = self._inverse_map(xx, yy, frame)
            texture = map_coordinates(base_speckle, warped_coords, order=1, mode="reflect")
            # Progressive decorrelation + out-of-plane: replace part of the
            # speckle field by an independent realisation (this is what makes a
            # tracker lose its kernel), the rest keeps following the material.
            progress = frame / max(cfg.n_frames - 1, 1)
            replaced = float(np.clip(cfg.decorrelation * progress + cfg.out_of_plane * frame, 0.0, 1.0))
            if replaced > 1e-6:
                fresh = rng.normal(0.0, 1.0, texture.shape) + 1j * rng.normal(0.0, 1.0, texture.shape)
                fresh = np.abs(gaussian_filter(fresh, cfg.speckle_sigma_px))
                fresh = (fresh - fresh.mean()) / max(float(fresh.std()), 1e-9)
                texture = (1.0 - replaced) * texture + replaced * fresh
            # Tissue reflectivity follows the material too, so the myocardium
            # brightens/thickens with the wall instead of staying a static mask.
            reflectivity = self._warped_reflectivity(reference, frame)
            image = reflectivity * (1.0 + 0.45 * texture)
            sigma = self._noise_sigma()
            if sigma > 1e-9:
                image = image + rng.normal(0.0, sigma, image.shape)
            image = gaussian_filter(image, cfg.blur_sigma_px)
            out[frame] = np.clip(image * 255.0, 0.0, 255.0).astype(np.uint8)
        return out

    def _warped_reflectivity(self, reference: np.ndarray, frame: int) -> np.ndarray:
        """Reflectivity map in the deformed configuration (sampled at ED)."""
        cfg = self.config
        if cfg.mode == "rigid" and not cfg.rotation_deg and not np.any(cfg.translation_px):
            return reference
        yy, xx = np.mgrid[0 : cfg.height, 0 : cfg.width].astype(np.float64)
        coords = self._inverse_map(xx, yy, frame)
        return map_coordinates(reference, coords, order=1, mode="constant", cval=float(cfg.background_level))

    def _pure_inverse(self, points: np.ndarray, frame: int) -> np.ndarray:
        """Exact inverse of the pure (unblended) deformation, in closed form.

        The map preserves the ray angle and scales the elliptical radius --
        ``r`` inside the cavity (the blood pool keeps its relative position) and
        ``1 + (r - 1) * lambda_r`` in the wall. The angle comes from a short
        fixed point: the deformed axes are normalised by the very factors that
        depend on that angle, and the substitution cancels them everywhere
        except in the level gradient, where it converges in two steps.
        """
        cfg = self.config
        pts = np.asarray(points, dtype=np.float64)
        if cfg.mode == "rigid":
            return pts.copy()
        anchor = self._apex_y if cfg.anchor == "apex" else self._base_y
        phi = np.arctan2(
            (self._base_y - pts[:, 1]) / self._long_px,
            (pts[:, 0] - self._cx) / self._a_endo,
        )
        for _ in range(5):
            lambda_l, lambda_t, _ = self._strain_factors(phi, frame)
            base = anchor + lambda_l * (self._base_y - anchor)
            u = (pts[:, 0] - self._cx) / (self._a_endo * lambda_t)
            v = (base - pts[:, 1]) / (self._long_px * lambda_l)
            phi = np.arctan2(v, u)
        lambda_l, lambda_t, lambda_r = self._strain_factors(phi, frame)
        base = anchor + lambda_l * (self._base_y - anchor)
        radius = np.hypot(
            (pts[:, 0] - self._cx) / (self._a_endo * lambda_t),
            (base - pts[:, 1]) / (self._long_px * lambda_l),
        )
        # Branch on the *deformed* radius: it is r itself inside the cavity and
        # 1 + (r - 1) * lambda_r in the wall, so it inverts directly.
        pure = np.where(radius > 1.0, 1.0 + (radius - 1.0) / lambda_r, radius)
        dx = pure * self._a_endo * np.cos(phi)
        dy = pure * self._long_px * np.sin(phi)
        return np.column_stack([self._cx + dx, self._base_y - dy])

    def _inverse_map(self, xx: np.ndarray, yy: np.ndarray, frame: int) -> np.ndarray:
        """Reference coordinates of the material that lands at (x, y) in ``frame``.

        The deformation is blended with a static background (weight 1 inside the
        heart, 0 outside the halo), so the inverse is taken in two steps: the
        exact inverse of the pure deformation, then one correction step for the
        blend. The correction is idempotent where the weight is 0 or 1 (the
        heart and the far field), which is everything that carries speckle of
        interest; the transition band is smooth and stays within a pixel.
        """
        cfg = self.config
        x = np.asarray(xx, dtype=np.float64).copy()
        y = np.asarray(yy, dtype=np.float64).copy()
        centre, angle, translation = self._rigid(frame)
        if angle or np.any(translation):
            y = y - translation[1]
            x = x - translation[0]
            if angle:
                cos_a, sin_a = np.cos(-angle), np.sin(-angle)
                rx = x - centre[0]
                ry = y - centre[1]
                x = centre[0] + rx * cos_a - ry * sin_a
                y = centre[1] + rx * sin_a + ry * cos_a
        if cfg.mode == "rigid":
            return np.stack([y, x])
        shape = np.shape(x)
        points = np.column_stack([x.ravel(), y.ravel()])
        inverse = points.copy()
        if self._moving is None:
            self._build_weight_map()
        moving = (
            map_coordinates(
                self._moving.astype(np.float64),
                np.stack([np.clip(points[:, 1], 0.0, cfg.height - 1.0), np.clip(points[:, 0], 0.0, cfg.width - 1.0)]),
                order=1,
                mode="nearest",
            )
            > 0.5
        )
        if np.any(moving):
            inverse[moving] = self._invert_blended(points[moving], frame)
        return np.stack([inverse[:, 1].reshape(shape), inverse[:, 0].reshape(shape)])

    def _invert_blended(self, points: np.ndarray, frame: int) -> np.ndarray:
        """Reference positions of the material that lands at ``points``.

        Where the blend weight is 0 or 1 the *pure* inverse is already the
        answer, so only the halo band needs work. There the plain fixed point
        ``x <- p - w(F(x) - x)`` can diverge: the weight ramp is a few pixels
        wide while the excursion it scales is up to tens of pixels, so the
        iteration Jacobian is far from contractive. A damped Newton step on the
        (tiny) band is used instead; it converges in a handful of iterations
        because the band is smooth and small.
        """
        pts = np.asarray(points, dtype=np.float64)
        # Far from the heart the weight is exactly zero, so the map is the
        # identity there — the pure deformation must *not* be applied to it.
        solved = pts.copy()
        active = self.region_weight(pts) > 1e-6
        if not np.any(active):
            return solved
        moving = pts[active]
        solved[active] = self._pure_inverse(moving, frame)
        weight = self.region_weight(solved[active])
        band = np.flatnonzero((weight > 1e-6) & (weight < 1.0 - 1e-6))
        if band.size:
            x = solved[active][band]
            target = moving[band]
            h = 0.25
            for _ in range(7):
                residual = self._blended_map(x, frame) - target
                if float(np.max(np.abs(residual))) < 1e-6:
                    break
                jac = np.empty((x.shape[0], 2, 2), dtype=np.float64)
                for axis in range(2):
                    offset = np.zeros_like(x)
                    offset[:, axis] = h
                    jac[:, :, axis] = (self._blended_map(x + offset, frame) - target - residual) / h
                det = jac[:, 0, 0] * jac[:, 1, 1] - jac[:, 0, 1] * jac[:, 1, 0]
                det = np.where(np.abs(det) < 1e-9, 1e-9, det)
                step_x = (jac[:, 1, 1] * residual[:, 0] - jac[:, 0, 1] * residual[:, 1]) / det
                step_y = (jac[:, 0, 0] * residual[:, 1] - jac[:, 1, 0] * residual[:, 0]) / det
                x = x - 0.7 * np.column_stack([step_x, step_y])
            block = solved[active]
            block[band] = x
            solved[active] = block
        return solved

    def myocardium_round_trip_error(self, frame: int, n_nodes: int = 65) -> float:
        """Round-trip error (px) of the image map *inside the myocardium*.

        The inverse map is only approximate in the transition band of the
        static background; inside the wall (where every tracked kernel and every
        ground-truth curve lives) it must close to a small fraction of a pixel,
        otherwise the simulated speckle would not follow the material.
        """
        points = np.vstack([self.reference_endo_arc(n_nodes), self.reference_epi_arc(n_nodes)])
        deformed = self.deform(points, frame)
        back = self._inverse_map(deformed[:, 0], deformed[:, 1], frame)
        return float(np.max(np.linalg.norm(np.column_stack([back[1], back[0]]) - points, axis=1)))

    def map_round_trip_error(self, frame: int, n: int = 64) -> float:
        """Max distance (px) between a point and its inverse-mapped round trip."""
        row = np.linspace(0.05 * self.config.height, 0.95 * self.config.height, n)
        col = np.linspace(0.05 * self.config.width, 0.95 * self.config.width, n)
        grid_row, grid_col = np.meshgrid(row, col, indexing="ij")
        points = np.column_stack([grid_col.ravel(), grid_row.ravel()])
        deformed = self.deform(points, frame)
        back = self._inverse_map(deformed[:, 0], deformed[:, 1], frame)
        return float(np.max(np.linalg.norm(np.column_stack([back[1], back[0]]) - points, axis=1)))
