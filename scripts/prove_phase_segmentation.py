"""Offline proof that ECG-independent phase segmentation works (А.3, #641).

Run: ``python scripts/prove_phase_segmentation.py``

Renders synthetic cine clips whose ground truth is exact by construction
(dark LV-like pool beating with a known period), runs the production
``build_phase_field`` pipeline on them, and prints a per-scenario table of
detected vs true ED/ES frames with the confidences the field reports. Any
detection outside the ±1-frame acceptance band, any non-monotone φ inside a
cycle, or any wrap miss at ED fails the script (exit code 1).

This is the demonstration companion of ``tests/unit/test_phase_field.py``
(which asserts the same invariants inside the CI test suite): a user-visible,
runnable answer to «как доказать, что работает» — same code path as the app,
no Qt, no fixtures.
"""

from __future__ import annotations

import sys

import numpy as np

from echo_personal_tool.domain.services.phase_field import PhaseField, build_phase_field

sys.path.insert(0, "tests/unit")
from test_phase_field import _blob_clip, _warped_area  # noqa: E402

TOLERANCE_FRAMES = 1


def _check_phi(field: PhaseField) -> list[str]:
    """The φ(t) invariants, exactly as ``tests/unit/test_phase_field.py``.

    Monotone from 0 inside every *complete* cycle; 0 at every detected ED
    anchor (``field.ed_frames``); everywhere within [0, 1). Partial cycles
    (extrapolated clip ends) carry no monotonicity claim — the field's own
    honesty about what lies beyond the measured beats.
    """
    problems: list[str] = []
    for cycle in (c for c in field.cycles if not c.partial):
        segment = field.phi[cycle.ed_frame : cycle.end_frame]
        if segment.size > 1:
            if abs(float(segment[0])) > 1e-6:
                problems.append(f"phi at cycle ED {cycle.ed_frame} = {segment[0]:.3f} (must be 0)")
            if np.any(np.diff(segment) < -1e-9):
                problems.append(f"phi not monotone in [{cycle.ed_frame}, {cycle.end_frame})")
    for ed in field.ed_frames:
        if abs(float(field.phi[int(ed)])) > 1e-6:
            problems.append(f"phi at detected ED {int(ed)} = {field.phi[int(ed)]:.3f} (must be 0)")
    if np.any((field.phi < -1e-9) | (field.phi > 1.0 + 1e-9)):
        problems.append("phi outside [0, 1)")
    return problems


def _run_scenario(name: str, frames: np.ndarray, ed_frames: list[int], period: int, **kwargs) -> bool:
    """One clip → one table row; ``True`` when every invariant holds.

    The blob's mechanical minimum (radius cos) sits at half a period after
    each ED — that is the ES ground truth for these clips.
    """
    truth_ed = ed_frames[0]
    truth_es = ed_frames[0] + period // 2
    field = build_phase_field(frames=frames, frame_time_ms=20.0, **kwargs)
    cycle = field.best_cycle()
    problems = _check_phi(field)
    ed_delta = es_delta = None
    if cycle is None:
        problems.append("no cycle detected (confidence gate rejected the clip)")
    else:
        ed_delta = cycle.ed_frame - truth_ed
        es_delta = cycle.es_frame - truth_es
        if abs(ed_delta) > TOLERANCE_FRAMES:
            problems.append(f"ED off by {ed_delta}")
        if abs(es_delta) > TOLERANCE_FRAMES:
            problems.append(f"ES off by {es_delta}")
    ed_text = "--" if ed_delta is None else f"{ed_delta:+d}"
    es_text = "--" if es_delta is None else f"{es_delta:+d}"
    conf = field.confidence * 100.0
    verdict = "OK" if not problems else "FAIL: " + "; ".join(problems)
    print(  # noqa: T201
        f"{name:<28} ED {ed_text}  ES {es_text}  φ-инварианты "
        f"{'ok' if not problems else 'нарушены'}  conf {conf:5.1f}%  signal={field.source_signal:<10} {verdict}"
    )
    return not problems


def main() -> int:
    print("Доказательство фазовой сегментации (А.3): синтетические клипы с точной ground truth")  # noqa: T201
    print("(допуск ±1 кадр; φ монотонна внутри цикла и обнуляется в каждом КД)\n")  # noqa: T201
    ok = True

    frames, ed_frames = _blob_clip(64, period=20)
    ok &= _run_scenario("чистый клип, 3 цикла", frames, ed_frames, 20)

    frames, ed_frames = _blob_clip(64, period=20)
    noisy = frames + np.random.default_rng(3).normal(0.0, 25.0, frames.shape).astype(np.float32)
    ok &= _run_scenario("шум σ=25", noisy, ed_frames, 20)

    frames, ed_frames = _blob_clip(64, period=14)
    ok &= _run_scenario("ЧСС 214 (период 14)", frames, ed_frames, 14)

    # The А.5 hook: a burned-ECG strip in the frame bottom must be excluded
    # from the phase evidence without moving the detected phases.
    frames, ed_frames = _blob_clip(64, period=20)
    strip = np.zeros(frames.shape[1:], dtype=bool)
    strip[56:64, :] = True
    for index in range(frames.shape[0]):
        frames[index][strip] = 20.0 + 15.0 * np.sin(0.9 * index)  # a fake "ECG" band
    ok &= _run_scenario("вшитая ЭКГ + exclude_mask", frames, ed_frames, 20, exclude_mask=strip)

    # The area-curve path: what a segmentation (or a stored Simpson curve) feeds.
    area = _warped_area(64, [4, 24, 44])
    field = build_phase_field(area_curve=area, frame_time_ms=20.0)
    cycle = field.best_cycle()
    es_ok = cycle is not None and abs(cycle.es_frame - 11) <= TOLERANCE_FRAMES
    ed_ok = cycle is not None and abs(cycle.ed_frame - 4) <= TOLERANCE_FRAMES
    phi_ok = not _check_phi(field)
    conf = field.confidence * 100.0
    verdict = "OK" if (es_ok and ed_ok and phi_ok) else "FAIL"
    print(  # noqa: T201
        f"кривая площади (Simpson-путь)  ED {'OK' if ed_ok else 'FAIL'}  ES {'OK' if es_ok else 'FAIL'}  "
        f"φ-инварианты {'ok' if phi_ok else 'нарушены'}  conf {conf:5.1f}%  signal={field.source_signal:<10} {verdict}")
    ok &= es_ok and ed_ok and phi_ok

    print()  # noqa: T201
    if ok:
        print("ИТОГ: все сценарии в допуске ±1 кадр, φ-инварианты выполнены — фазовая сегментация работает.")  # noqa: T201
        return 0
    print("ИТОГ: есть нарушения — см. строки FAIL выше.")  # noqa: T201
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
