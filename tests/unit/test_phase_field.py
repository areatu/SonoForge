"""Unit tests for the ECG-independent phase field (plan А.3, issue #641).

Acceptance criteria of the issue, as executable invariants on synthetic
clips whose ground truth is exact by construction:

* φ(t) is monotone inside every cycle and wraps to 0 at each ED;
* ED (maximal cavity) / ES (minimal cavity) land within ±1 frame of the
  ground truth and of an "ECG annotation" (ED at the R-peak, ES at the 0.35
  systolic prior — the same convention ``ecg_ed_es_mapper`` uses);
* phase shift and time inversion do not change the strain curve that the
  detected cycles produce;
* the confidence metric gates weak signals instead of guessing.

Pure domain tests: no Qt, no file I/O.
"""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.services.cardiac_cycle_detector import average_strain_curves
from echo_personal_tool.domain.services.ecg_ed_es_mapper import detect_ed_es_for_cine
from echo_personal_tool.domain.services.phase_field import (
    PhaseField,
    build_phase_field,
    cavity_area_from_masks,
    extract_phase_candidates,
    optical_flow_magnitude_signal,
    phase_field_ed_es_fallback,
    phase_field_to_cardiac_cycles,
    phase_field_to_ed_es_mapping,
)

# ── Synthetic clips with exact ground truth ─────────────────────────────────


def _warped_area(
    n_frames: int,
    ed_frames: list[int],
    *,
    systole_fraction: float = 0.35,
    noise: float = 0.0,
    seed: int = 7,
) -> np.ndarray:
    """Cavity-area curve: maximum at each ED, minimum at ED + fraction·RR.

    The contraction/filling shape is a piecewise cosine extended over the
    whole timeline (every frame lies inside a warped beat), so the mechanical
    minimum sits exactly at ``ed + systole_fraction · period`` — the same
    convention the ECG path of ``ecg_ed_es_mapper`` assumes.
    """
    rng = np.random.default_rng(seed)
    period = float(ed_frames[1] - ed_frames[0])
    t = np.arange(n_frames, dtype=np.float64)
    frac = np.mod((t - ed_frames[0]) / period, 1.0)
    systole = frac <= systole_fraction
    curve = np.where(
        systole,
        np.cos(np.pi * frac / systole_fraction),
        -np.cos(np.pi * (frac - systole_fraction) / (1.0 - systole_fraction)),
    )
    if noise > 0:
        curve = curve + noise * rng.standard_normal(n_frames)
    return curve


def _blob_clip(
    n_frames: int,
    size: int = 64,
    period: int = 20,
    *,
    background: float = 180.0,
    blob: float = 40.0,
) -> tuple[np.ndarray, list[int]]:
    """Grayscale clip of a dark LV-like pool whose radius beats with the clip.

    Returns ``(frames, ed_frames)``: the pool is widest at the ED frames.
    """
    center = size / 2.0
    ed_frames = [4, 4 + period, 4 + 2 * period]
    frames = np.full((n_frames, size, size), background, dtype=np.float32)
    rows, cols = np.mgrid[0:size, 0:size]
    for index in range(n_frames):
        phase = 2.0 * np.pi * (index - ed_frames[0]) / period
        radius = size * 0.22 + size * 0.07 * np.cos(phase)
        mask = (rows - center) ** 2 + (cols - center) ** 2 <= radius**2
        frames[index][mask] = blob
    return frames, ed_frames


def _moving_square_clip(n_frames: int, size: int = 64, period: int = 20) -> np.ndarray:
    """Uniform background with a small bright square translating back and forth.

    Dark fraction and mean intensity stay flat (the square never changes
    size), so only optical flow can see the motion — the polarity-free
    supporting-evidence path of the plan.
    """
    frames = np.full((n_frames, size, size), 128.0, dtype=np.float32)
    for index in range(n_frames):
        phase = 2.0 * np.pi * index / period
        x = int(round(24.0 + 10.0 * np.sin(phase)))
        frames[index, 28:36, x : x + 8] = 220.0
    return frames


def _complete_cycles(field: PhaseField) -> list:
    return [c for c in field.cycles if not c.partial]


# ── φ(t) monotonicity and wrap (acceptance #1) ──────────────────────────────


class TestPhiMonotonicity:
    def test_phi_monotone_inside_every_cycle(self) -> None:
        curve = _warped_area(90, [5, 35, 65])
        field = build_phase_frame_field(curve)
        cycles = _complete_cycles(field)
        assert len(cycles) == 2
        for cycle in cycles:
            segment = field.phi[cycle.ed_frame : cycle.end_frame]
            assert segment[0] == pytest.approx(0.0, abs=1e-9)
            assert np.all(np.diff(segment) >= -1e-12)
            assert float(segment[-1]) < 1.0

    def test_phi_wraps_to_zero_at_each_ed(self) -> None:
        curve = _warped_area(90, [5, 35, 65])
        field = build_phase_frame_field(curve)
        for ed in field.ed_frames:
            assert field.phase_at(int(ed)) == pytest.approx(0.0, abs=1e-9)

    def test_phi_at_es_is_the_measured_systole_fraction(self) -> None:
        curve = _warped_area(90, [5, 35, 65])
        field = build_phase_frame_field(curve)
        for cycle in _complete_cycles(field):
            fraction = field.phase_at(cycle.es_frame)
            assert fraction == pytest.approx(cycle.systole_fraction, abs=1e-9)
            # The synthetic beat contracts over 35% of the cycle: the measured
            # mechanical ES must land near that prior, not at a half-beat.
            assert 0.25 <= fraction <= 0.45

    def test_phi_stays_in_unit_interval_everywhere(self) -> None:
        curve = _warped_area(120, [8, 38, 68, 98], noise=0.03)
        field = build_phase_frame_field(curve)
        assert np.all(field.phi >= 0.0)
        assert np.all(field.phi < 1.0)


# ── ED/ES accuracy (acceptance #2) ──────────────────────────────────────────


class TestEdEsAccuracy:
    def test_ed_es_within_one_frame_of_ground_truth(self) -> None:
        curve = _warped_area(90, [5, 35, 65], noise=0.02)
        field = build_phase_frame_field(curve)
        cycles = _complete_cycles(field)
        assert len(cycles) == 2
        for cycle, ed in zip(cycles, [5, 35]):
            assert abs(cycle.ed_frame - ed) <= 1
            true_es = ed + int(0.35 * 30 + 0.5)
            assert abs(cycle.es_frame - true_es) <= 1

    def test_noisy_multi_cycle_clip_keeps_ed_es(self) -> None:
        curve = _warped_area(150, [8, 43, 78, 113], noise=0.05, seed=11)
        field = build_phase_frame_field(curve)
        cycles = _complete_cycles(field)
        # The beat 113 -> 148 closes inside the clip, so all four anchors
        # form complete cycles.
        assert len(cycles) == 4
        for cycle, ed in zip(cycles, [8, 43, 78, 113]):
            assert abs(cycle.ed_frame - ed) <= 1

    def test_ed_matches_ecg_annotation_within_one_frame(self) -> None:
        # Clinical convention of the ECG path: ED ≈ R-peak.  The synthetic
        # R-peaks are the ED frames themselves, so the image-only field must
        # reproduce them without ever seeing the ECG.
        r_peaks = [5, 35, 65]
        curve = _warped_area(90, r_peaks, noise=0.02)
        field = build_phase_frame_field(curve)
        detected = list(field.ed_frames)
        assert len(detected) == len(r_peaks)
        for detected_ed, r_peak in zip(detected, r_peaks):
            assert abs(detected_ed - r_peak) <= 1

    def test_es_matches_ecg_systolic_prior_within_one_frame(self) -> None:
        r_peaks = [5, 35, 65]
        curve = _warped_area(90, r_peaks, noise=0.02)
        field = build_phase_frame_field(curve)
        for cycle, ed in zip(_complete_cycles(field), r_peaks):
            ecg_es_prior = ed + int(0.35 * 30 + 0.5)
            assert abs(cycle.es_frame - ecg_es_prior) <= 1


# ── Invariant tests: phase shift and inversion (acceptance / step 5) ────────


class TestInvariants:
    def test_circular_phase_shift_is_exactly_equivariant(self) -> None:
        curve = _warped_area(90, [5, 35, 65], noise=0.02)
        field = build_phase_frame_field(curve)
        shift = 7
        n = curve.size
        shifted_field = build_phase_frame_field(np.roll(curve, shift))

        # φ(t) itself is equivariant: shifting the clip shifts the field.
        assert np.allclose(shifted_field.phi, np.roll(field.phi, shift), atol=1e-6)
        # The refined period carries a small least-squares jitter (exact
        # equivariance holds at the integer median anchor gap, which φ uses).
        assert shifted_field.period_frames == pytest.approx(field.period_frames, abs=0.1)
        assert set(shifted_field.ed_frames) == {(e + shift) % n for e in field.ed_frames}

    def test_circular_phase_shift_maps_cycles_and_strain(self) -> None:
        curve = _warped_area(90, [5, 35, 65], noise=0.02)
        field = build_phase_frame_field(curve)
        shift = 7
        n = curve.size
        shifted_field = build_phase_frame_field(np.roll(curve, shift))

        original_complete = _complete_cycles(field)
        shifted_complete = _complete_cycles(shifted_field)
        assert len(shifted_complete) == len(original_complete)
        for original_cycle, shifted_cycle in zip(original_complete, shifted_complete):
            assert shifted_cycle.duration_frames == original_cycle.duration_frames
            assert abs(shifted_cycle.ed_frame - (original_cycle.ed_frame + shift)) % n <= 1
            assert abs(shifted_cycle.es_frame - (original_cycle.es_frame + shift)) % n <= 1

        # The strain averaged over the detected cycles is the same curve —
        # up to the beat-to-beat noise of the synthetic clip itself.
        original_strain = _cycle_strain(curve, original_complete, n)
        shifted_strain = _cycle_strain(np.roll(curve, shift), shifted_complete, n)
        assert np.allclose(original_strain, shifted_strain, atol=0.05)

    def test_time_inversion_maps_ed_es_and_keeps_strain_values(self) -> None:
        curve = _warped_area(90, [5, 35, 65], noise=0.02)
        field = build_phase_frame_field(curve)
        reversed_field = build_phase_frame_field(curve[::-1].copy())
        original_cycles = sorted(_complete_cycles(field), key=lambda c: c.ed_frame)
        reversed_cycles = sorted(_complete_cycles(reversed_field), key=lambda c: c.ed_frame)
        assert len(original_cycles) == len(reversed_cycles) == 2

        n = curve.size
        # Time reversal maps a cycle [ed, end) to [n-1-end, n-1-ed): the first
        # reversed cycle is the last original one, traversed backwards.
        for reversed_cycle, original_cycle in zip(reversed_cycles, original_cycles[::-1]):
            assert abs(reversed_cycle.ed_frame - (n - 1 - original_cycle.end_frame)) <= 1
            assert abs(reversed_cycle.es_frame - (n - 1 - original_cycle.es_frame)) <= 1
            assert abs(reversed_cycle.end_frame - (n - 1 - original_cycle.ed_frame)) <= 1

        # The strain values measured at the anchors do not move: the ES anchor
        # maps to the very same physical frame (exact equality), and both ED
        # anchors sit on the same mechanical apex.
        for reversed_cycle, original_cycle in zip(reversed_cycles, original_cycles[::-1]):
            assert curve[original_cycle.es_frame] == pytest.approx(curve[::-1][reversed_cycle.es_frame], abs=1e-9)
            apex = float(np.max(curve))
            assert curve[original_cycle.ed_frame] == pytest.approx(apex, abs=0.05)
            assert curve[::-1][reversed_cycle.ed_frame] == pytest.approx(apex, abs=0.05)

    def test_inversion_does_not_flip_polarity_of_phase(self) -> None:
        # ED must stay the maximal-cavity frame after reversal: a phase model
        # that confused polarity would compute strain between wrong frames.
        curve = _warped_area(90, [5, 35, 65])
        field = build_phase_frame_field(curve)
        reversed_field = build_phase_frame_field(curve[::-1].copy())
        original_es_values = [float(curve[c.es_frame]) for c in _complete_cycles(field)]
        reversed_es_values = [float(curve[::-1][c.es_frame]) for c in _complete_cycles(reversed_field)]
        assert len(original_es_values) == len(reversed_es_values) == 2
        for original_value, reversed_value in zip(original_es_values, reversed_es_values):
            assert original_value == pytest.approx(min(original_es_values), abs=1e-6)
            assert reversed_value == pytest.approx(min(reversed_es_values), abs=1e-6)

    def test_strain_averaging_over_cycles_is_shift_invariant_without_partial(self) -> None:
        # A clip that starts exactly at an ED has no leading partial cycle;
        # circular shift then permutes complete cycles only.
        curve = _warped_area(90, [0, 30, 60], noise=0.01)
        field = build_phase_frame_field(curve)
        shifted_field = build_phase_frame_field(np.roll(curve, 10))
        n = curve.size
        assert np.allclose(shifted_field.phi, np.roll(field.phi, 10), atol=1e-6)
        original_strain = _cycle_strain(curve, _complete_cycles(field), n)
        shifted_strain = _cycle_strain(np.roll(curve, 10), _complete_cycles(shifted_field), n)
        assert np.allclose(original_strain, shifted_strain, atol=0.05)


def _cycle_strain(curve: np.ndarray, cycles: list, n: int) -> np.ndarray:
    """Resample the cavity-area strain proxy over the detected cycles.

    Downstream (strain/STE) consumes the phase field exactly this way:
    ``average_strain_curves`` over the cycle boundaries the field produced.
    """
    boundaries = [(c.ed_frame, c.end_frame - 1) for c in cycles if c.end_frame - 1 < n]
    assert boundaries
    return average_strain_curves([np.asarray(curve, dtype=np.float64)], boundaries, 32)


def build_phase_frame_field(curve: np.ndarray) -> PhaseField:
    """Build a phase field from a supplied cavity-area curve alone."""
    return build_phase_field(n_frames=int(curve.size), area_curve=curve)


# ── Confidence metric (acceptance #3) ───────────────────────────────────────


class TestConfidence:
    def test_strong_periodic_signal_is_confident(self) -> None:
        curve = _warped_area(90, [5, 35, 65])
        field = build_phase_frame_field(curve)
        assert 0.0 <= field.confidence <= 1.0
        assert field.confidence >= 0.6

    def test_flat_signal_yields_no_cycles(self) -> None:
        field = build_phase_frame_field(np.full(90, 3.0))
        assert field.cycles == ()
        assert field.confidence == 0.0
        assert "no_periodic_signal" in field.warnings

    def test_noise_only_signal_is_rejected(self) -> None:
        rng = np.random.default_rng(3)
        field = build_phase_frame_field(rng.standard_normal(90))
        assert field.cycles == ()
        assert field.confidence < 0.35

    def test_weak_signal_is_gated_not_guessed(self) -> None:
        curve = _warped_area(90, [5, 35, 65], noise=0.9, seed=5)
        field = build_phase_frame_field(curve)
        if field.confidence < 0.35:
            assert field.cycles == ()
            assert "low_confidence" in field.warnings
            assert np.all(field.phi == 0.0)
        else:
            assert field.cycles

    def test_flow_only_clip_never_creates_phase(self) -> None:
        frames = _moving_square_clip(40)
        field = build_phase_field(frames=frames)
        assert field.cycles == ()
        assert "motion_only" in field.warnings

    def test_confidence_grows_with_signal_quality(self) -> None:
        clean = build_phase_frame_field(_warped_area(90, [5, 35, 65]))
        noisy = build_phase_frame_field(_warped_area(90, [5, 35, 65], noise=0.25, seed=9))
        assert clean.confidence >= noisy.confidence


# ── Signals: LV masks, image proxies, optical flow ─────────────────────────


class TestSignals:
    def test_cavity_area_from_masks_tracks_beat(self) -> None:
        frames, ed_frames = _blob_clip(45)
        masks = frames < 100.0
        area = cavity_area_from_masks(masks)
        assert area.size == 45
        assert int(np.argmax(area)) == ed_frames[0]
        # The blob clip beats sinusoidally: systole spans half the cycle
        # (pixel grid makes the exact minimum tie across ±1 frame).
        minimum = int(np.argmin(area[ed_frames[0] : ed_frames[1]])) + ed_frames[0]
        assert abs(minimum - (ed_frames[0] + (ed_frames[1] - ed_frames[0]) // 2)) <= 1

    def test_mask_area_alone_builds_a_field(self) -> None:
        frames, _ed_frames = _blob_clip(45)
        field = build_phase_field(lv_masks=frames < 100.0, frame_time_ms=30.0)
        assert field.source_signal == "area"
        assert _complete_cycles(field)
        assert field.heart_rate_bpm is not None
        # 20-frame beat at 30 ms → 100 bpm.
        assert 85.0 <= (field.heart_rate_bpm or 0.0) <= 115.0

    def test_dark_pool_from_frames_finds_ed_es(self) -> None:
        frames, ed_frames = _blob_clip(45, period=20)
        field = build_phase_field(frames=frames, frame_time_ms=33.3)
        assert field.source_signal in ("dark_pool", "intensity", "area")
        # Circular anchor detection sees all three EDs, including the one on
        # the clip edge; the cycle starting at the last ED cannot close inside
        # the clip and stays a trailing partial.
        assert len(field.ed_frames) == 3
        for anchor in field.ed_frames:
            assert any(abs(anchor - ed) <= 1 for ed in ed_frames)
        complete_eds = [c.ed_frame for c in _complete_cycles(field)]
        assert len(complete_eds) >= 2
        for detected_ed in complete_eds:
            assert any(abs(detected_ed - ed) <= 1 for ed in ed_frames)

    def test_extract_candidates_from_frames(self) -> None:
        frames, _ed_frames = _blob_clip(45)
        candidates = extract_phase_candidates(frames=frames)
        assert "dark_pool" in candidates
        assert "intensity" in candidates
        assert candidates["dark_pool"].size == 45
        # Carriers are ED-oriented: the dark pool is maximal at the widest pool.
        assert float(np.argmax(candidates["dark_pool"])) == int(np.argmax(candidates["intensity"]))

    def test_optical_flow_sees_motion_and_static_is_empty(self) -> None:
        moving = optical_flow_magnitude_signal(_moving_square_clip(40))
        assert moving.size == 40
        assert float(np.ptp(moving)) > 0.0
        static = optical_flow_magnitude_signal(np.full((20, 48, 48), 120.0, dtype=np.float32))
        assert static.size == 0

    def test_static_gain_ramp_on_motionless_clip_never_beats(self) -> None:
        # Shared doctrine: a periodic gain adjustment on a motionless clip
        # must not become a heartbeat.  Per-frame normalisation leaves only
        # non-periodic noise wiggle, which the periodicity gate rejects.
        rng = np.random.default_rng(4)
        base = np.full((30, 48, 48), 140.0, dtype=np.float32) + rng.normal(0, 2.0, (30, 48, 48))
        gain = np.linspace(1.0, 1.6, 30)[:, None, None]
        field = build_phase_field(frames=base * gain, frame_time_ms=33.3)
        assert field.cycles == ()
        assert field.confidence < 0.35


# ── Degenerate inputs never raise ───────────────────────────────────────────


class TestDegenerateInputs:
    def test_too_few_frames(self) -> None:
        field = build_phase_field(n_frames=3)
        assert field.n_frames == 3
        assert field.cycles == ()
        assert "no_frames" in field.warnings
        assert field.phi.size == 3

    def test_curve_length_mismatch_is_reported(self) -> None:
        curve = _warped_area(90, [5, 35, 65])
        field = build_phase_field(n_frames=90, area_curve=curve[:80])
        assert "area_length_mismatch" in field.warnings
        assert field.cycles == ()

    def test_nan_holes_in_area_curve_are_interpolated(self) -> None:
        curve = _warped_area(90, [5, 35, 65])
        curve[10:14] = np.nan
        field = build_phase_frame_field(curve)
        assert len(_complete_cycles(field)) == 2

    def test_bad_frame_time_is_reported(self) -> None:
        curve = _warped_area(90, [5, 35, 65])
        field = build_phase_frame_field(curve)
        assert "frame_time_unknown" in field.warnings
        field_bad = build_phase_field(n_frames=90, area_curve=curve, frame_time_ms=0.0)
        assert "frame_time_unknown" in field_bad.warnings

    def test_phase_at_out_of_range(self) -> None:
        curve = _warped_area(90, [5, 35, 65])
        field = build_phase_frame_field(curve)
        assert field.phase_at(-1) == 0.0
        assert field.phase_at(90) == 0.0


# ── Serialisation ───────────────────────────────────────────────────────────


class TestSerialization:
    def test_round_trip(self) -> None:
        curve = _warped_area(90, [5, 35, 65], noise=0.02)
        field = build_phase_field(n_frames=90, area_curve=curve, frame_time_ms=33.3, min_confidence=0.0)
        restored = PhaseField.from_dict(field.to_dict())
        assert restored.n_frames == field.n_frames
        assert restored.frame_time_ms == field.frame_time_ms
        assert restored.ed_frames == field.ed_frames
        assert restored.es_frames == field.es_frames
        assert restored.cycles == field.cycles
        assert restored.source_signal == field.source_signal
        assert restored.confidence == pytest.approx(field.confidence)
        assert restored.warnings == field.warnings
        assert np.allclose(restored.phi, field.phi, atol=1e-5)

    def test_round_trip_of_rejected_field(self) -> None:
        field = build_phase_field(n_frames=90, area_curve=np.full(90, 1.0))
        restored = PhaseField.from_dict(field.to_dict())
        assert restored.cycles == ()
        assert restored.phi.size == 90


# ── Bridges (plan А.3 step 4) ───────────────────────────────────────────────


class TestBridges:
    def test_mapping_uses_best_cycle(self) -> None:
        curve = _warped_area(90, [5, 35, 65])
        field = build_phase_frame_field(curve)
        best = field.best_cycle()
        assert best is not None
        mapping = phase_field_to_ed_es_mapping(field)
        assert mapping.source == "image"
        assert mapping.ed_frame_index == best.ed_frame
        assert mapping.es_frame_index == best.es_frame
        assert mapping.cycle_start_frame == best.ed_frame

    def test_mapping_without_cycles_falls_back_like_the_mapper(self) -> None:
        field = build_phase_frame_field(np.full(90, 5.0))
        mapping = phase_field_to_ed_es_mapping(field)
        assert mapping.source == "image"
        assert mapping.ed_frame_index == 0
        assert mapping.es_frame_index == 90 // 3

    def test_fallback_plugs_into_detect_ed_es_for_cine(self) -> None:
        curve = _warped_area(90, [5, 35, 65], noise=0.02)
        field = build_phase_frame_field(curve)
        best = field.best_cycle()
        assert best is not None
        fallback = phase_field_ed_es_fallback(area_curve=curve)
        mapping = detect_ed_es_for_cine(None, 33.3, 90, image_fallback=fallback)
        assert mapping.source == "image"
        assert mapping.ed_frame_index == best.ed_frame
        assert mapping.es_frame_index == best.es_frame

    def test_cardiac_cycles_need_frame_time(self) -> None:
        curve = _warped_area(90, [5, 35, 65])
        field = build_phase_frame_field(curve)
        assert phase_field_to_cardiac_cycles(field) == []
        field_timed = build_phase_field(n_frames=90, area_curve=curve, frame_time_ms=33.3)
        cycles = phase_field_to_cardiac_cycles(field_timed)
        assert len(cycles) == len(_complete_cycles(field_timed))
        for bridge_cycle, domain_cycle in zip(cycles, _complete_cycles(field_timed)):
            assert bridge_cycle.source == "image"
            assert bridge_cycle.start_ms == pytest.approx(domain_cycle.ed_frame * 33.3)
            assert bridge_cycle.es_ms == pytest.approx(domain_cycle.es_frame * 33.3)
            assert bridge_cycle.rr_ms == pytest.approx(domain_cycle.duration_frames * 33.3)

    def test_fallback_on_unusable_input_matches_mapper_sentinel(self) -> None:
        fallback = phase_field_ed_es_fallback(area_curve=np.full(50, 2.0))
        mapping = detect_ed_es_for_cine(None, 33.3, 50, image_fallback=fallback)
        assert mapping.source == "image"
        assert mapping.ed_frame_index == 0
        assert mapping.es_frame_index == 50 // 3


# ── Heart rate from the field ───────────────────────────────────────────────


class TestHeartRate:
    def test_heart_rate_from_period(self) -> None:
        curve = _warped_area(90, [5, 35, 65])
        field = build_phase_field(n_frames=90, area_curve=curve, frame_time_ms=33.3)
        hr = field.heart_rate_bpm
        assert hr is not None
        # 30-frame beat at 33.3 ms → RR ≈ 1 s → 60 bpm; ±1 frame of slop.
        assert 55.0 <= hr <= 70.0

    def test_heart_rate_is_none_without_time(self) -> None:
        curve = _warped_area(90, [5, 35, 65])
        field = build_phase_frame_field(curve)
        assert field.heart_rate_bpm is None
