"""Gold annotation store benchmarks.

Measures save, load, merge, dedup, and manifest rebuild operations
for the gold annotation JSON store.

Run:  ECHO_BENCH=1 pytest tests/bench/test_gold_store_bench.py -v --benchmark-only
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from echo_personal_tool.domain.services.gold_store import (
    dedupe_gold_frames,
    load_gold,
    make_gold_frame,
    make_gold_study,
    merge_frame_into_gold,
    rebuild_manifest_from_gold_dir,
    save_gold,
)

_bench = pytest.mark.bench
_skip_bench = pytest.mark.skipif(
    os.environ.get("ECHO_BENCH", "") != "1",
    reason="Set ECHO_BENCH=1 to run benchmarks",
)


def _make_study_with_frames(n_frames: int = 10) -> dict:
    """Build a gold study dict with n_frames annotated frames."""
    study = make_gold_study(
        study_id="bench-study-1",
        instance_path="/data/study/img.dcm",
        pixel_spacing_mm=[0.3, 0.3],
    )
    for i in range(n_frames):
        frame = make_gold_frame(
            frame_index=i * 5,
            phase="ED" if i % 2 == 0 else "ES",
            points=[[10.0, 20.0], [30.0, 40.0], [50.0, 60.0]],
            mitral_annulus=[[15.0, 25.0], [35.0, 45.0]],
            sop_instance_uid=f"1.2.3.{i}",
            instance_path="/data/study/img.dcm",
        )
        study = merge_frame_into_gold(study, frame)
    return study


# ── Save / Load ─────────────────────────────────────────────────────


@_bench
@_skip_bench
def test_bench_gold_save_10_frames(benchmark, tmp_path: Path) -> None:
    """Save gold JSON with 10 frames."""
    study = _make_study_with_frames(10)
    path = tmp_path / "gold" / "lv_bench-1.json"

    def _save() -> None:
        save_gold(path, study)

    benchmark(_save)


@_bench
@_skip_bench
def test_bench_gold_save_50_frames(benchmark, tmp_path: Path) -> None:
    """Save gold JSON with 50 frames (large study)."""
    study = _make_study_with_frames(50)
    path = tmp_path / "gold" / "lv_bench-50.json"

    def _save() -> None:
        save_gold(path, study)

    benchmark(_save)


@_bench
@_skip_bench
def test_bench_gold_load_10_frames(benchmark, tmp_path: Path) -> None:
    """Load gold JSON with 10 frames."""
    study = _make_study_with_frames(10)
    path = tmp_path / "gold" / "lv_bench-10.json"
    save_gold(path, study)

    def _load() -> dict:
        return load_gold(path)

    benchmark(_load)


@_bench
@_skip_bench
def test_bench_gold_load_50_frames(benchmark, tmp_path: Path) -> None:
    """Load gold JSON with 50 frames."""
    study = _make_study_with_frames(50)
    path = tmp_path / "gold" / "lv_bench-50.json"
    save_gold(path, study)

    def _load() -> dict:
        return load_gold(path)

    benchmark(_load)


@_bench
@_skip_bench
def test_bench_gold_roundtrip_20_frames(benchmark, tmp_path: Path) -> None:
    """Full save -> load roundtrip for 20-frame study."""
    study = _make_study_with_frames(20)
    path = tmp_path / "gold" / "lv_rt.json"

    def _roundtrip() -> dict:
        save_gold(path, study)
        return load_gold(path)

    result = benchmark(_roundtrip)
    assert len(result["frames"]) == 20


# ── Merge ───────────────────────────────────────────────────────────


@_bench
@_skip_bench
def test_bench_gold_merge_new_frame(benchmark, tmp_path: Path) -> None:
    """Merge a new frame into existing study (append path)."""
    study = _make_study_with_frames(10)
    frame = make_gold_frame(
        frame_index=99,
        phase="ED",
        points=[[10.0, 20.0], [30.0, 40.0], [50.0, 60.0]],
        mitral_annulus=[[15.0, 25.0], [35.0, 45.0]],
        sop_instance_uid="1.2.3.99",
    )

    def _merge() -> dict:
        return merge_frame_into_gold(study, frame)

    benchmark(_merge)


@_bench
@_skip_bench
def test_bench_gold_merge_replace_frame(benchmark, tmp_path: Path) -> None:
    """Merge frame that replaces existing (same instance + phase)."""
    study = _make_study_with_frames(10)
    frame = make_gold_frame(
        frame_index=0,
        phase="ED",
        points=[[11.0, 21.0], [31.0, 41.0], [51.0, 61.0]],
        mitral_annulus=[[16.0, 26.0], [36.0, 46.0]],
        sop_instance_uid="1.2.3.0",
        instance_path="/data/study/img.dcm",
    )

    def _replace() -> dict:
        return merge_frame_into_gold(study, frame)

    benchmark(_replace)


@_bench
@_skip_bench
def test_bench_gold_merge_50_frame_study(benchmark, tmp_path: Path) -> None:
    """Merge into a 50-frame study (linear scan cost)."""
    study = _make_study_with_frames(50)
    frame = make_gold_frame(
        frame_index=100,
        phase="ES",
        points=[[10.0, 20.0], [30.0, 40.0], [50.0, 60.0]],
        mitral_annulus=[[15.0, 25.0], [35.0, 45.0]],
        sop_instance_uid="1.2.3.100",
    )

    def _merge() -> dict:
        return merge_frame_into_gold(study, frame)

    benchmark(_merge)


# ── Dedup ───────────────────────────────────────────────────────────


@_bench
@_skip_bench
def test_bench_gold_dedupe_20_frames(benchmark, tmp_path: Path) -> None:
    """Deduplicate 20 frames (some with same instance + phase)."""
    study = _make_study_with_frames(20)
    # Add duplicate frames
    for i in range(10):
        frame = make_gold_frame(
            frame_index=i * 5,
            phase="ED" if i % 2 == 0 else "ES",
            points=[[10.0, 20.0], [30.0, 40.0], [50.0, 60.0]],
            mitral_annulus=[[15.0, 25.0], [35.0, 45.0]],
            sop_instance_uid=f"1.2.3.{i}",
            instance_path="/data/study/img.dcm",
        )
        study["frames"].append(frame)

    def _dedupe() -> list:
        return dedupe_gold_frames(study["frames"], study=study)

    benchmark(_dedupe)


@_bench
@_skip_bench
def test_bench_gold_dedupe_100_frames(benchmark, tmp_path: Path) -> None:
    """Deduplicate 100 frames (mixed instances)."""
    study = _make_study_with_frames(50)
    for i in range(50):
        frame = make_gold_frame(
            frame_index=i * 3,
            phase="ES",
            points=[[10.0, 20.0], [30.0, 40.0], [50.0, 60.0]],
            mitral_annulus=[[15.0, 25.0], [35.0, 45.0]],
            sop_instance_uid=f"1.2.3.{i}",
            instance_path=f"/data/study/inst_{i}.dcm",
        )
        study["frames"].append(frame)

    def _dedupe() -> list:
        return dedupe_gold_frames(study["frames"], study=study)

    benchmark(_dedupe)


# ── Manifest rebuild ────────────────────────────────────────────────


@_bench
@_skip_bench
def test_bench_gold_manifest_5_studies(benchmark, tmp_path: Path) -> None:
    """Rebuild manifest from 5 gold study files."""
    gold_dir = tmp_path / "gold"
    gold_dir.mkdir(parents=True)
    for s_idx in range(5):
        study = make_gold_study(
            study_id=f"study-{s_idx:03d}",
            instance_path=f"/data/study-{s_idx}/img.dcm",
            pixel_spacing_mm=[0.3, 0.3],
        )
        for f_idx in range(4):
            frame = make_gold_frame(
                frame_index=f_idx * 10,
                phase="ED" if f_idx % 2 == 0 else "ES",
                points=[[10.0, 20.0], [30.0, 40.0], [50.0, 60.0]],
                mitral_annulus=[[15.0, 25.0], [35.0, 45.0]],
                sop_instance_uid=f"1.2.{s_idx}.{f_idx}",
            )
            study = merge_frame_into_gold(study, frame)
        save_gold(gold_dir / f"lv_study-{s_idx:03d}.json", study)

    def _rebuild() -> dict:
        return rebuild_manifest_from_gold_dir(tmp_path)

    result = benchmark(_rebuild)
    assert len(result["studies"]) == 5


@_bench
@_skip_bench
def test_bench_gold_manifest_20_studies(benchmark, tmp_path: Path) -> None:
    """Rebuild manifest from 20 gold study files."""
    gold_dir = tmp_path / "gold"
    gold_dir.mkdir(parents=True)
    for s_idx in range(20):
        study = make_gold_study(
            study_id=f"study-{s_idx:03d}",
            instance_path=f"/data/study-{s_idx}/img.dcm",
            pixel_spacing_mm=[0.3, 0.3],
        )
        for f_idx in range(6):
            frame = make_gold_frame(
                frame_index=f_idx * 5,
                phase="ED" if f_idx % 2 == 0 else "ES",
                points=[[10.0, 20.0], [30.0, 40.0], [50.0, 60.0]],
                mitral_annulus=[[15.0, 25.0], [35.0, 45.0]],
                sop_instance_uid=f"1.2.{s_idx}.{f_idx}",
            )
            study = merge_frame_into_gold(study, frame)
        save_gold(gold_dir / f"lv_study-{s_idx:03d}.json", study)

    def _rebuild() -> dict:
        return rebuild_manifest_from_gold_dir(tmp_path)

    result = benchmark(_rebuild)
    assert len(result["studies"]) == 20


# ── Save + merge + reload cycle ─────────────────────────────────────


@_bench
@_skip_bench
def test_bench_gold_save_merge_reload_cycle(benchmark, tmp_path: Path) -> None:
    """Full cycle: save study -> merge new frame -> reload."""
    study = _make_study_with_frames(10)
    path = tmp_path / "gold" / "lv_cycle.json"
    save_gold(path, study)

    frame = make_gold_frame(
        frame_index=100,
        phase="ES",
        points=[[10.0, 20.0], [30.0, 40.0], [50.0, 60.0]],
        mitral_annulus=[[15.0, 25.0], [35.0, 45.0]],
        sop_instance_uid="1.2.3.100",
    )

    def _cycle() -> dict:
        current = load_gold(path)
        merged = merge_frame_into_gold(current, frame)
        save_gold(path, merged)
        return load_gold(path)

    result = benchmark(_cycle)
    assert len(result["frames"]) == 11
