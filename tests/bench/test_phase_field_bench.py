"""Phase-field accuracy + latency benchmarks (issue #641, plan А.3).

Measures :func:`build_phase_field` over deterministic synthetic clips: ED/ES
accuracy against the generator's ground truth (the phase equivalent of the
view-recognition accuracy half) and the wall-clock latency of the full
pipeline — signal extraction, the harmonic period search, circular anchor
detection and the bridges.  The generators encode the beat in a cosine area
curve (curve path) and in a moving dark blob (frame path, through the
dark-pool signal), so the accuracy numbers are exact and reproducible — no
model or real corpus is needed to detect a multiples-sized regression.

Run:  ECHO_BENCH=1 pytest tests/bench/test_phase_field_bench.py -v --benchmark-only
"""

from __future__ import annotations

import math
import os

import numpy as np
import pytest

from echo_personal_tool.domain.services.phase_field import (
    build_phase_field,
    phase_field_to_ed_es_mapping,
)

_bench = pytest.mark.bench

_skip_no_env = pytest.mark.skipif(
    os.environ.get("ECHO_BENCH", "") != "1",
    reason="Set ECHO_BENCH=1 to run benchmarks",
)

_FRAME_TIME_MS = 33.3
_PERIOD = 20


def _warped_area(n_frames: int, eds: list[int], noise: float = 0.02) -> np.ndarray:
    """Cosine area curve over the whole timeline: ED = maximum, ES at 35 %."""
    period = float(eds[1] - eds[0])
    t = np.arange(n_frames, dtype=np.float64)
    curve = np.zeros(n_frames, dtype=np.float64)
    for ed in eds:
        phase = np.mod(t - ed, period) / period
        curve = np.maximum(curve, np.cos(2.0 * math.pi * phase))
    rng = np.random.default_rng(0)
    return np.clip(curve, 0.0, None) + noise * rng.standard_normal(n_frames)


def _blob_clip(n_frames: int) -> tuple[np.ndarray, list[int]]:
    """Dark blob on a bright field: the dark-pool fraction peaks at every ED.

    The blob breathes with the same cosine phase as the curve generator —
    radius maximal at ``frame % _PERIOD == 4`` (ED), minimal at 35 % — and
    slides horizontally so the frames carry real motion.
    """
    size = 24
    centre = (size - 1) / 2.0
    frames = np.full((n_frames, size, size), 230.0, dtype=np.float32)
    truth = [4 + start for start in range(0, n_frames - 1, _PERIOD)]
    yy, xx = np.ogrid[:size, :size]
    for frame in range(n_frames):
        phase = ((frame - 4) % _PERIOD) / _PERIOD
        angle = 2.0 * math.pi * phase
        radius = 4.5 + 1.5 * math.cos(angle)
        shift = 2.0 * math.sin(angle)
        mask = (xx - centre - shift) ** 2 + (yy - centre) ** 2 <= radius**2
        frames[frame][mask] = 20.0
    return frames, truth


@_bench
@_skip_no_env
def test_bench_phase_field_area_curve_accuracy(benchmark) -> None:
    """ED accuracy on a 5-beat curve corpus (150 frames, 50 bpm)."""
    curve = _warped_area(150, [10, 44, 78, 112])

    def _build_and_check() -> None:
        field = build_phase_field(area_curve=curve, frame_time_ms=_FRAME_TIME_MS)
        assert field.warnings == () or field.warnings == ("partial_cycles",)
        cycles = [c for c in field.cycles if not c.partial]
        assert len(cycles) >= 3
        for cycle, ed in zip(cycles, [10, 44, 78, 112]):
            assert abs(cycle.ed_frame - ed) <= 1

    benchmark(_build_and_check)


@_bench
@_skip_no_env
def test_bench_phase_field_blob_clip_accuracy(benchmark) -> None:
    """Frame-path ED accuracy through the dark-pool signal (45 frames)."""
    frames, truth = _blob_clip(45)

    def _build_and_check() -> None:
        field = build_phase_field(frames=frames, frame_time_ms=_FRAME_TIME_MS)
        assert field.confidence >= 0.6
        for anchor in field.ed_frames:
            assert any(abs(anchor - ed) <= 1 for ed in truth)

    benchmark(_build_and_check)


@_bench
@_skip_no_env
def test_bench_phase_field_pipeline_latency_curve(benchmark) -> None:
    """Full pipeline latency on the 150-frame curve, bridge included."""
    curve = _warped_area(150, [10, 44, 78, 112])

    def _pipeline() -> None:
        field = build_phase_field(area_curve=curve, frame_time_ms=_FRAME_TIME_MS)
        mapping = phase_field_to_ed_es_mapping(field)
        assert mapping.source == "image"

    benchmark(_pipeline)
