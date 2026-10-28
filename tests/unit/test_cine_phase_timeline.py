"""Unit tests for ECG / ECG-free cine phase labelling.

Synthetic signals stand in for real clips: their ED/ES frames are known exactly,
so a one-frame regression in the detector is visible.  No Qt, no DICOM files.
"""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.services.cine_phase_timeline import (
    PHASE_DIASTOLE,
    PHASE_SYSTOLE,
    PHASE_UNKNOWN,
    PhaseTimeline,
    build_phase_timeline,
    burned_ecg_signal,
    dark_pool_signal,
)

N_FRAMES = 72
PERIOD = 24
FRAME_MS = 33.3
ED_FRAMES = (3, 27, 51)
ES_FRAMES = (15, 39, 63)


def area_curve(n: int = N_FRAMES, period: int = PERIOD, ed: int = 3) -> np.ndarray:
    """Cosinusoidal LV area: ED = maximum, ES = minimum."""
    return np.cos(2 * np.pi * (np.arange(n) - ed) / period)


def ecg_r_peaks(offset_ms: float = 0.0) -> np.ndarray:
    """Three R-peaks with RR = 800 ms (= 24 frames at 33.3 ms)."""
    return np.asarray([100.0, 900.0, 1700.0]) + offset_ms


def cine_with_dark_pool(n: int = N_FRAMES, period: int = PERIOD) -> np.ndarray:
    """Bright myocardium, dark elliptical cavity shrinking in systole."""
    yy, xx = np.mgrid[:64, :64]
    frames = []
    for t in range(n):
        radius = 12 + 6 * np.cos(2 * np.pi * (t - 3) / period)
        cavity = ((xx - 32) / radius) ** 2 + ((yy - 32) / (radius * 1.3)) ** 2 < 1
        image = np.full((64, 64, 3), 170, dtype=np.uint8)
        image[cavity] = 20
        frames.append(image)
    return np.asarray(frames)


def green_ecg_cine(n: int = N_FRAMES, width: int = 96) -> np.ndarray:
    """A static green ECG trace with three sharp spikes in the lower band."""
    height = 64
    image = np.zeros((n, height, width, 3), dtype=np.uint8)
    trace = np.full(width, 52.0)
    for beat in range(3):
        centre = int((beat + 0.5) * width / 3)
        trace[centre - 2 : centre + 3] -= np.array([4, 9, 14, 9, 4])
    for t in range(n):
        for x in range(width):
            image[t, int(trace[x]), x, 1] = 200
    return image


class TestImageOnlyPath:
    def test_area_curve_labels_every_phase(self) -> None:
        timeline = build_phase_timeline(n_frames=N_FRAMES, frame_time_ms=FRAME_MS, area_curve=area_curve())
        assert timeline.source == "area"
        assert timeline.confidence >= 0.5
        assert [(c.ed_frame, c.es_frame) for c in timeline.cycles[:2]] == list(zip(ED_FRAMES[:2], ES_FRAMES[:2]))
        assert timeline.phase_at(3) == PHASE_SYSTOLE
        assert timeline.phase_at(14) == PHASE_SYSTOLE
        assert timeline.phase_at(15) == PHASE_DIASTOLE
        assert timeline.phase_at(26) == PHASE_DIASTOLE
        assert timeline.phase_at(0) == PHASE_UNKNOWN  # before the first ED
        assert timeline.heart_rate_bpm is not None
        assert 70 < timeline.heart_rate_bpm < 80

    def test_dark_pool_from_pixels_finds_ed_es(self) -> None:
        frames = cine_with_dark_pool()
        pool = dark_pool_signal(frames[..., 0])
        assert int(np.argmax(pool[:PERIOD])) == 3
        assert int(np.argmin(pool[:PERIOD])) == 15
        timeline = build_phase_timeline(n_frames=N_FRAMES, frame_time_ms=FRAME_MS, frames=frames)
        assert timeline.source in {"dark_pool", "intensity", "motion"}
        assert timeline.confidence >= 0.35
        assert timeline.cycles[0].ed_frame == pytest.approx(3, abs=1)
        assert timeline.cycles[0].es_frame == pytest.approx(15, abs=1)

    def test_aligned_burned_ecg_peaks_are_used_without_waveform(self) -> None:
        frames = green_ecg_cine()
        peaks = burned_ecg_signal(frames, FRAME_MS, N_FRAMES)
        assert peaks is not None and len(peaks) == 3
        timeline = build_phase_timeline(n_frames=N_FRAMES, frame_time_ms=FRAME_MS, burned_ecg_r_peaks_ms=peaks)
        assert timeline.source.startswith("burned_ecg")
        assert "burned_ecg" in timeline.warnings
        assert len(timeline.cycles) >= 1
        assert all(0 <= c.ed_frame < c.es_frame <= c.end_frame for c in timeline.cycles)

    def test_manual_anchor_resolves_polarity(self) -> None:
        # An unlabelled vendor index whose sign is inverted relative to area:
        # ED is the *minimum*, ES the maximum.  One user click marks frame 15
        # as ES and must flip the interpretation back to ED=3 / ES=15.
        inverted = -area_curve()
        anchored = build_phase_timeline(
            n_frames=N_FRAMES,
            frame_time_ms=FRAME_MS,
            unlabelled_curve=inverted,
            manual_anchor=(15, "es"),
        )
        assert anchored.source == "unlabelled"
        assert anchored.cycles[0].ed_frame == pytest.approx(3, abs=1)
        assert anchored.cycles[0].es_frame == pytest.approx(15, abs=1)
        assert anchored.phase_at(4) == PHASE_SYSTOLE
        assert anchored.phase_at(20) == PHASE_DIASTOLE

    def test_flat_or_noisy_clip_is_honestly_unknown(self) -> None:
        flat = build_phase_timeline(n_frames=N_FRAMES, frame_time_ms=FRAME_MS, area_curve=np.ones(N_FRAMES))
        noisy = build_phase_timeline(
            n_frames=60,
            frame_time_ms=FRAME_MS,
            area_curve=np.random.default_rng(4).normal(size=60),
        )
        for timeline in (flat, noisy):
            assert timeline.source == "unavailable"
            assert timeline.confidence == 0.0
            assert set(timeline.labels) == {PHASE_UNKNOWN}
            assert timeline.markers() == ()
            assert "phase_unavailable" in timeline.warnings

    def test_short_clip_and_missing_inputs(self) -> None:
        assert build_phase_timeline(n_frames=0).n_frames == 0
        short = build_phase_timeline(n_frames=3, frame_time_ms=FRAME_MS, area_curve=np.arange(3))
        assert short.source == "unavailable"
        empty = build_phase_timeline(n_frames=30, frame_time_ms=FRAME_MS)
        assert empty.source == "unavailable"

    def test_nans_in_sparse_curve_are_interpolated(self) -> None:
        sparse = np.full(N_FRAMES, np.nan)
        sparse[3:52] = area_curve()[3:52]
        timeline = build_phase_timeline(n_frames=N_FRAMES, frame_time_ms=FRAME_MS, area_curve=sparse)
        assert timeline.source == "area"
        assert timeline.cycles[0].ed_frame == pytest.approx(3, abs=1)

    def test_sparse_frame_value_table_is_not_mistaken_for_a_dense_curve(self) -> None:
        table = np.column_stack([np.arange(20, 60), area_curve()[20:60]])
        timeline = build_phase_timeline(n_frames=N_FRAMES, frame_time_ms=FRAME_MS, area_curve=table)
        assert timeline.source == "area"
        assert timeline.cycles[0].ed_frame >= 20

    def test_unknown_frame_time_keeps_frame_reasoning(self) -> None:
        timeline = build_phase_timeline(n_frames=N_FRAMES, area_curve=area_curve())
        assert "frame_time_unknown" in timeline.warnings
        assert timeline.heart_rate_bpm is None
        assert timeline.phase_at(4) == PHASE_SYSTOLE


class TestEcgPath:
    def test_r_peaks_give_ed_and_area_gives_es(self) -> None:
        timeline = build_phase_timeline(
            n_frames=N_FRAMES,
            frame_time_ms=FRAME_MS,
            area_curve=area_curve(),
            ecg_r_peaks_ms=ecg_r_peaks(),
        )
        assert timeline.source == "ecg+area"
        assert timeline.confidence >= 0.8
        assert [c.ed_frame for c in timeline.cycles[:2]] == [3, 27]
        assert [c.es_frame for c in timeline.cycles[:2]] == [15, 39]
        assert "ecg_not_aligned" not in timeline.warnings

    def test_trigger_offset_is_recovered_automatically(self) -> None:
        timeline = build_phase_timeline(
            n_frames=N_FRAMES,
            frame_time_ms=FRAME_MS,
            area_curve=area_curve(),
            ecg_r_peaks_ms=ecg_r_peaks(offset_ms=5 * FRAME_MS),
        )
        assert [c.ed_frame for c in timeline.cycles[:2]] == [3, 27]
        assert "ecg_not_aligned" not in timeline.warnings

    def test_explicit_trigger_offset_is_trusted(self) -> None:
        timeline = build_phase_timeline(
            n_frames=N_FRAMES,
            frame_time_ms=FRAME_MS,
            area_curve=area_curve(),
            ecg_r_peaks_ms=ecg_r_peaks(offset_ms=5 * FRAME_MS),
            ecg_offset_ms=5 * FRAME_MS,
        )
        assert timeline.source == "ecg+area"
        assert [c.ed_frame for c in timeline.cycles[:2]] == [3, 27]

    def test_ecg_without_image_uses_documented_prior(self) -> None:
        timeline = build_phase_timeline(
            n_frames=N_FRAMES,
            frame_time_ms=FRAME_MS,
            ecg_r_peaks_ms=ecg_r_peaks(),
        )
        assert timeline.source == "ecg+prior"
        assert "ecg_not_aligned" in timeline.warnings
        assert "es_from_prior" in timeline.warnings
        assert [c.ed_frame for c in timeline.cycles[:2]] == [3, 27]
        assert all(c.es_frame > c.ed_frame for c in timeline.cycles)

    def test_irregular_rhythm_uses_per_beat_rr(self) -> None:
        peaks = np.asarray([100.0, 760.0, 1740.0])  # 660, 980 ms — AF-like
        timeline = build_phase_timeline(
            n_frames=N_FRAMES,
            frame_time_ms=FRAME_MS,
            area_curve=area_curve(),
            ecg_r_peaks_ms=peaks,
        )
        assert "irregular_rhythm" in timeline.warnings
        ed = [c.ed_frame for c in timeline.cycles]
        assert ed[1] - ed[0] != pytest.approx(ed[2] - ed[1], abs=1) or len(ed) < 3

    def test_trailing_partial_cycle_is_flagged(self) -> None:
        # 1.75 beats: one complete cycle and a truncated tail after the last ED.
        timeline = build_phase_timeline(
            n_frames=42,
            frame_time_ms=FRAME_MS,
            area_curve=area_curve(n=42),
        )
        assert len(timeline.cycles) >= 2
        assert not timeline.cycles[0].partial
        assert timeline.cycles[-1].partial
        assert timeline.cycles[-1].end_frame == 42
        assert "partial_cycles" in timeline.warnings


class TestTimelineValueObject:
    def test_segments_and_markers_cover_the_clip(self) -> None:
        timeline = build_phase_timeline(n_frames=N_FRAMES, frame_time_ms=FRAME_MS, area_curve=area_curve())
        segments = timeline.segments()
        assert segments[0].start_frame == 0
        assert segments[-1].end_frame == N_FRAMES
        assert all(s.start_frame < s.end_frame for s in segments)
        assert all(segments[i].end_frame <= segments[i + 1].start_frame for i in range(len(segments) - 1))
        markers = timeline.markers()
        assert {m.kind for m in markers} == {"ed", "es"}
        assert any(m.frame == 3 and m.kind == "ed" for m in markers)
        assert any(m.frame == 15 and m.kind == "es" for m in markers)

    def test_manual_edit_and_serialisation_roundtrip(self) -> None:
        timeline = build_phase_timeline(n_frames=N_FRAMES, frame_time_ms=FRAME_MS, area_curve=area_curve())
        manual = timeline.with_manual_ed_es(0, ed_frame=4, es_frame=16)
        assert manual.cycles[0].source == "manual"
        assert manual.cycles[0].confidence == 1.0
        assert manual.phase_at(3) == PHASE_UNKNOWN
        assert manual.phase_at(4) == PHASE_SYSTOLE
        assert manual.phase_at(16) == PHASE_DIASTOLE
        assert timeline.cycles[0].ed_frame == 3  # original is immutable
        restored = PhaseTimeline.from_dict(manual.to_dict())
        assert restored == manual

    def test_invalid_inputs_never_raise(self) -> None:
        timeline = build_phase_timeline(
            n_frames=10,
            frame_time_ms=-1,
            frames=np.zeros((10, 8, 8)),
            area_curve=np.full(10, np.nan),
            ecg_r_peaks_ms=np.asarray([np.nan, np.nan]),
        )
        assert timeline.source == "unavailable"
        assert len(timeline.labels) == 10


class TestConservativeImageEvidence:
    def test_gain_and_offset_oscillation_is_not_a_heartbeat(self) -> None:
        texture = np.random.default_rng(41).uniform(20, 130, (64, 64))
        frames = np.asarray(
            [
                texture * (1 + 0.25 * np.cos(2 * np.pi * t / PERIOD)) + 10 * np.sin(2 * np.pi * t / PERIOD)
                for t in range(N_FRAMES)
            ]
        )
        timeline = build_phase_timeline(n_frames=N_FRAMES, frame_time_ms=FRAME_MS, frames=frames)
        assert timeline.source == "unavailable"
        assert timeline.markers() == ()

    def test_off_centre_pool_with_black_surround_and_gain_drift(self) -> None:
        yy, xx = np.mgrid[:64, :64]
        frames = []
        for t in range(N_FRAMES):
            radius = 9 + 4 * np.cos(2 * np.pi * (t - 3) / PERIOD)
            cavity = ((xx - 25) / radius) ** 2 + ((yy - 29) / (1.2 * radius)) ** 2 < 1
            image = np.zeros((64, 64), dtype=np.float32)
            image[7:54, 9:55] = 170
            image[cavity] = 20
            frames.append(image * (1 + 0.25 * np.sin(2 * np.pi * t / 17)) + 7 * np.cos(t / 11))
        timeline = build_phase_timeline(n_frames=N_FRAMES, frame_time_ms=FRAME_MS, frames=np.asarray(frames))
        assert timeline.source == "dark_pool"
        assert timeline.confidence >= 0.35
        for cycle, ed, es in zip(timeline.cycles, ED_FRAMES, ES_FRAMES):
            assert cycle.ed_frame == pytest.approx(ed, abs=1)
            assert cycle.es_frame == pytest.approx(es, abs=1)

    def test_motion_alone_never_sets_ed_es(self, monkeypatch) -> None:
        import echo_personal_tool.domain.services.cine_phase_timeline as detector

        empty = np.zeros(0)
        monkeypatch.setattr(detector, "image_phase_signals", lambda frames: (empty, empty, area_curve()))
        timeline = build_phase_timeline(n_frames=N_FRAMES, frame_time_ms=FRAME_MS, frames=np.zeros((N_FRAMES, 8, 8)))
        assert timeline.markers() == ()
        assert timeline.source == "unavailable"

    def test_static_burned_ecg_has_no_known_video_time_base(self) -> None:
        timeline = build_phase_timeline(n_frames=N_FRAMES, frame_time_ms=FRAME_MS, frames=green_ecg_cine())
        assert timeline.markers() == ()
        assert timeline.source == "unavailable"

    def test_subcardiac_drift_is_not_an_acf_boundary_peak(self) -> None:
        timeline = build_phase_timeline(n_frames=240, frame_time_ms=FRAME_MS, area_curve=area_curve(n=240, period=180))
        assert timeline.markers() == ()

    def test_rejected_confidence_never_exposes_coloured_segments_or_chips(self) -> None:
        timeline = build_phase_timeline(
            n_frames=N_FRAMES, frame_time_ms=FRAME_MS, area_curve=area_curve(), min_confidence=0.99
        )
        assert "low_confidence" in timeline.warnings
        assert set(timeline.labels) == {PHASE_UNKNOWN}
        assert timeline.markers() == ()
        assert {segment.phase for segment in timeline.segments()} == {PHASE_UNKNOWN}

    def test_legacy_low_confidence_document_cannot_bypass_rendering_gate(self) -> None:
        data = build_phase_timeline(n_frames=N_FRAMES, frame_time_ms=FRAME_MS, area_curve=area_curve()).to_dict()
        data["labels"] = [PHASE_UNKNOWN] * N_FRAMES
        timeline = PhaseTimeline.from_dict(data)
        assert timeline.cycles  # old documents can still carry rejected guesses
        assert timeline.markers() == ()
        assert {segment.phase for segment in timeline.segments()} == {PHASE_UNKNOWN}

    @pytest.mark.parametrize("fps", [15, 20, 30, 60, 100])
    def test_temporal_resolution_is_preserved(self, fps) -> None:
        period = round(0.8 * fps)
        ed = round(0.1 * period)
        timeline = build_phase_timeline(
            n_frames=3 * period,
            frame_time_ms=1000 / fps,
            area_curve=area_curve(n=3 * period, period=period, ed=ed),
        )
        assert len(timeline.cycles) >= 2
        assert timeline.cycles[0].ed_frame == pytest.approx(ed, abs=1)
        assert timeline.cycles[0].es_frame == pytest.approx(ed + period / 2, abs=1)


class TestPartialEcgBeats:
    def test_final_es_uses_true_rr_not_truncated_tail(self) -> None:
        timeline = build_phase_timeline(
            n_frames=N_FRAMES,
            frame_time_ms=FRAME_MS,
            area_curve=area_curve(),
            ecg_r_peaks_ms=ecg_r_peaks(),
        )
        assert [c.es_frame for c in timeline.cycles] == list(ES_FRAMES)
        assert all(c.source == "ecg+area" for c in timeline.cycles)

    def test_tail_without_a_mechanical_minimum_is_not_invented(self) -> None:
        timeline = build_phase_timeline(
            n_frames=35,
            frame_time_ms=FRAME_MS,
            area_curve=area_curve(n=35),
        )
        assert len(timeline.cycles) == 1
        assert timeline.phase_at(30) == PHASE_UNKNOWN

    def test_ecg_prior_outside_tail_is_not_clamped_to_last_frame(self) -> None:
        timeline = build_phase_timeline(
            n_frames=10,
            frame_time_ms=FRAME_MS,
            ecg_r_peaks_ms=ecg_r_peaks(),
            align_ecg=False,
        )
        assert timeline.markers() == ()

    def test_implausible_ecg_rr_cannot_create_phase_markers(self) -> None:
        timeline = build_phase_timeline(
            n_frames=N_FRAMES,
            frame_time_ms=FRAME_MS,
            ecg_r_peaks_ms=np.asarray([100, 200, 300, 400]),
        )
        assert timeline.markers() == ()

    def test_missing_frame_time_is_inferred_for_ecg_path(self) -> None:
        # 60 fps cine (48 frames/beat at 800 ms RR) with missing DICOM FrameTime.
        n = 144
        period = 48
        timeline = build_phase_timeline(
            n_frames=n,
            frame_time_ms=None,
            area_curve=area_curve(n=n, period=period, ed=6),
            ecg_r_peaks_ms=np.asarray([100.0, 900.0, 1700.0]),
        )
        assert timeline.source == "ecg+area"
        assert timeline.frame_time_ms is None
        assert "frame_time_inferred" in timeline.warnings
        assert timeline.cycles[0].ed_frame == pytest.approx(6, abs=1)
