"""Phase-source routing tests (plan А.4, issue #642).

The acceptance criteria under test: switching sources is transparent (the
decision carries the route, its confidence and the warnings that explain it),
every consumer receives the same :class:`PhaseDecision` contract, and the
force-source override never silently second-guesses the user — it falls back
honestly and says so.
"""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.models.ecg import EcgLead, EcgWaveform, RPeakResult
from echo_personal_tool.domain.services.phase_source import (
    SOURCE_ECG,
    SOURCE_HYBRID,
    SOURCE_IMAGE,
    CinePhaseSource,
    PhaseDecision,
    PhaseRequest,
    resolve_phase_source,
)

_FRAME_TIME_MS = 33.3
_N_FRAMES = 90
_EDS = (5, 35, 65)


def _peaks(ed_frames: tuple[int, ...] = _EDS, confidence: float = 0.9) -> RPeakResult:
    """R-peak train over the synthetic beat: ED ≈ R-peak, RR = 30 frames."""
    times = np.asarray([f * _FRAME_TIME_MS for f in ed_frames], dtype=np.float64)
    rr = np.diff(times)
    return RPeakResult(
        r_peak_indices=np.arange(len(times)),
        r_peak_times_ms=times,
        heart_rate_bpm=75.0,
        rr_intervals_ms=rr,
        confidence=confidence,
    )


def _impulse_ecg(ed_frames: tuple[int, ...] = _EDS) -> EcgWaveform:
    """DICOM-shaped ECG with impulses at the R-peak times (250 Hz)."""
    fs = 250.0
    duration_ms = _N_FRAMES * _FRAME_TIME_MS + 500.0
    n = int(duration_ms * fs / 1000.0)
    signal = np.zeros(n)
    for frame in ed_frames:
        idx = int(frame * _FRAME_TIME_MS * fs / 1000.0)
        if 0 <= idx < n:
            signal[idx] = 10.0
    lead = EcgLead(name="II", samples=signal, sampling_frequency=fs, baseline=0, bits_stored=0)
    return EcgWaveform(leads=[lead], waveform_frequency=fs, number_of_waveform_channels=1)


def _area_curve(eds: tuple[int, ...] = _EDS, n: int = _N_FRAMES) -> np.ndarray:
    """Cosine cavity-area curve over the whole timeline: ED = maximum."""
    t = np.arange(n, dtype=np.float64)
    curve = np.zeros(n, dtype=np.float64)
    for ed in eds:
        phase = np.mod(t - ed, 30.0) / 30.0
        curve = np.maximum(curve, np.cos(2.0 * np.pi * phase))
    return np.clip(curve, 0.0, None) + 1e-6


class TestAutoRouting:
    def test_valid_ecg_tags_win(self) -> None:
        decision = resolve_phase_source(n_frames=_N_FRAMES, frame_time_ms=_FRAME_TIME_MS, ecg=_impulse_ecg())
        assert decision.source == SOURCE_ECG
        assert decision.mapping.source == "ecg"
        assert abs(decision.mapping.ed_frame_index - 5) <= 1
        assert decision.confidence == pytest.approx(decision.mapping.r_peak_result.confidence)
        assert decision.heart_rate_bpm is not None and decision.heart_rate_bpm > 0
        assert decision.warnings == ()

    def test_without_ecg_routes_to_image_field(self) -> None:
        decision = resolve_phase_source(
            n_frames=_N_FRAMES,
            frame_time_ms=_FRAME_TIME_MS,
            area_curve=_area_curve(),
        )
        assert decision.source == SOURCE_IMAGE
        assert decision.mapping.source == "image"
        assert abs(decision.mapping.ed_frame_index - 5) <= 1
        assert decision.confidence >= 0.5
        assert decision.phase_field is not None
        assert decision.heart_rate_bpm is not None and 55.0 < decision.heart_rate_bpm < 70.0
        assert "no_usable_ecg" in decision.warnings

    def test_agreeing_ecg_and_image_route_hybrid(self) -> None:
        decision = resolve_phase_source(
            n_frames=_N_FRAMES,
            frame_time_ms=_FRAME_TIME_MS,
            ecg=_impulse_ecg(),
            area_curve=_area_curve(),
        )
        assert decision.source == SOURCE_HYBRID
        assert decision.mapping.source == "ecg"  # ECG wins on the anchors
        assert abs(decision.mapping.ed_frame_index - 5) <= 1
        # The agreement bonus lifts the combined confidence over both inputs.
        assert decision.confidence >= 0.9
        assert decision.phase_field is not None
        assert "hybrid_agreement" in decision.warnings

    def test_disagreeing_image_field_keeps_ecg(self) -> None:
        # The curve's beats sit where the ECG's are not: the image field is
        # confident but points elsewhere, so the doctrine prefers the ECG.
        decision = resolve_phase_source(
            n_frames=_N_FRAMES,
            frame_time_ms=_FRAME_TIME_MS,
            ecg=_impulse_ecg(),
            area_curve=_area_curve(eds=(20, 50, 80)),
        )
        assert decision.source == SOURCE_ECG
        assert abs(decision.mapping.ed_frame_index - 5) <= 1
        assert "image_disagrees" in decision.warnings

    def test_low_confidence_image_field_keeps_ecg(self) -> None:
        decision = resolve_phase_source(
            n_frames=_N_FRAMES,
            frame_time_ms=_FRAME_TIME_MS,
            ecg=_impulse_ecg(),
            area_curve=np.linspace(0.0, 1.0, _N_FRAMES),  # monotone: no beat
        )
        assert decision.source == SOURCE_ECG
        assert "image_unavailable" in decision.warnings

    def test_image_route_without_any_signal_degrades_honestly(self) -> None:
        decision = resolve_phase_source(n_frames=_N_FRAMES, frame_time_ms=_FRAME_TIME_MS)
        assert decision.source == SOURCE_IMAGE
        assert decision.mapping.ed_frame_index == 0
        assert decision.mapping.es_frame_index == _N_FRAMES // 3
        assert decision.confidence == 0.0
        assert decision.heart_rate_bpm is None
        assert decision.phase_field is None
        assert "no_phase_source" in decision.warnings


class TestForceSource:
    def test_forced_image_ignores_ecg_and_says_so(self) -> None:
        decision = resolve_phase_source(
            n_frames=_N_FRAMES,
            frame_time_ms=_FRAME_TIME_MS,
            ecg=_impulse_ecg(),
            area_curve=_area_curve(),
            forced="image",
        )
        assert decision.source == SOURCE_IMAGE
        assert "ecg_ignored" in decision.warnings

    def test_forced_ecg_without_waveform_falls_back_honestly(self) -> None:
        decision = resolve_phase_source(
            n_frames=_N_FRAMES,
            frame_time_ms=_FRAME_TIME_MS,
            area_curve=_area_curve(),
            forced="ecg",
        )
        assert decision.source == SOURCE_IMAGE
        assert "forced_ecg_unavailable" in decision.warnings
        assert decision.confidence >= 0.5

    def test_forced_ecg_with_low_confidence_peaks_falls_back(self) -> None:
        decision = resolve_phase_source(
            n_frames=_N_FRAMES,
            frame_time_ms=_FRAME_TIME_MS,
            ecg=_impulse_ecg(),
            r_peak_result=_peaks(confidence=0.2),
            area_curve=_area_curve(),
            forced="ecg",
        )
        assert decision.source == SOURCE_IMAGE
        assert "forced_ecg_unavailable" in decision.warnings

    def test_forced_ecg_without_frame_time_cannot_map(self) -> None:
        # R-peaks exist, but without a time base the milliseconds cannot
        # become frame indices — the route is unusable, not silently wrong.
        decision = resolve_phase_source(
            n_frames=_N_FRAMES,
            frame_time_ms=None,
            ecg=_impulse_ecg(),
            area_curve=_area_curve(),
            forced="ecg",
        )
        assert decision.source == SOURCE_IMAGE
        assert "forced_ecg_unavailable" in decision.warnings

    def test_unknown_force_value_is_reported_and_treated_as_auto(self) -> None:
        decision = resolve_phase_source(
            n_frames=_N_FRAMES,
            frame_time_ms=_FRAME_TIME_MS,
            ecg=_impulse_ecg(),
            area_curve=_area_curve(),
            forced="doppler",
        )
        assert decision.source == SOURCE_HYBRID
        assert "unknown_force_source" in decision.warnings


class TestTransparentSwitching:
    def test_same_inputs_switch_route_only_via_forced(self) -> None:
        ecg = _impulse_ecg()
        curve = _area_curve()
        auto = resolve_phase_source(n_frames=_N_FRAMES, frame_time_ms=_FRAME_TIME_MS, ecg=ecg, area_curve=curve)
        image = resolve_phase_source(
            n_frames=_N_FRAMES, frame_time_ms=_FRAME_TIME_MS, ecg=ecg, area_curve=curve, forced="image"
        )
        # The routes differ, the contract does not: same fields, same types,
        # both explain themselves.
        assert auto.source == SOURCE_HYBRID and image.source == SOURCE_IMAGE
        assert isinstance(auto, PhaseDecision) and isinstance(image, PhaseDecision)
        assert image.warnings and "ecg_ignored" in image.warnings
        assert auto.phase_field is not None and image.phase_field is not None

    def test_uses_precomputed_r_peak_result_when_given(self) -> None:
        peaks = _peaks()
        decision = resolve_phase_source(
            n_frames=_N_FRAMES,
            frame_time_ms=_FRAME_TIME_MS,
            r_peak_result=peaks,
        )
        assert decision.source == SOURCE_ECG
        assert decision.mapping.r_peak_result is peaks


class TestContract:
    def test_port_and_function_agree(self) -> None:
        request = PhaseRequest(
            n_frames=_N_FRAMES,
            frame_time_ms=_FRAME_TIME_MS,
            ecg=_impulse_ecg(),
        )
        via_port = CinePhaseSource().resolve(request)
        via_function = resolve_phase_source(n_frames=_N_FRAMES, frame_time_ms=_FRAME_TIME_MS, ecg=request.ecg)
        assert via_port.source == via_function.source == SOURCE_ECG
        # Field-by-field: the mappings carry numpy arrays (RPeakResult), so
        # dataclass equality is not defined for them.
        for field_name in ("ed_frame_index", "es_frame_index", "cycle_start_frame", "cycle_end_frame", "source"):
            assert getattr(via_port.mapping, field_name) == getattr(via_function.mapping, field_name)
        assert via_port.warnings == via_function.warnings
        assert via_port.confidence == via_function.confidence

    def test_never_raises_on_degenerate_input(self) -> None:
        decision = resolve_phase_source(n_frames=0, frame_time_ms=None)
        assert decision.source == SOURCE_IMAGE
        assert decision.confidence == 0.0
        assert "no_frames" in decision.warnings

    def test_image_heart_rate_requires_time_base(self) -> None:
        decision = resolve_phase_source(n_frames=_N_FRAMES, frame_time_ms=None, area_curve=_area_curve())
        assert decision.source == SOURCE_IMAGE
        assert decision.heart_rate_bpm is None  # frames-only field cannot know bpm
        assert decision.phase_field is not None
