"""Which truth-free number may the report quote as "this tracking is confirmed"?

Clinical review Q6 asked how far the inter-frame contour tracking can be trusted.
Two candidate trust flags are available without ground truth:

* the **round-trip closure error** (match the finished trajectory back to end
  diastole and measure the miss distance) — the flag the module ships;
* the **match quality** of the forward match (NCC) — the number clinicians
  already see in the report and might reasonably read as "tracking is fine".

This harness measures both against the phantom's exact kinematics: for every
node-frame it computes the true position error (mm) and then reports, for each
candidate flag, how many of the truly bad node-frames it catches (recall) and
how many of the flagged ones are actually bad (precision), plus the error
distribution inside the "trusted" and "flagged" groups.

Run::

    LD_LIBRARY_PATH=tools/qtstub/lib QT_QPA_PLATFORM=offscreen \\
        ./.venv/bin/python bench/ste_trust_flags.py [--json OUT]

The measured conclusion (uniform phantom, 0.45 mm/px) is what licenses the
shipped choice: the closure gate separates the groups, NCC does not — at every
noise level the NCC flag catches *none* of the badly tracked node-frames that
the closure flag catches, so NCC must not be presented as a verification.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests" / "fixtures"))

from ste_phantom import StePhantom, StePhantomConfig  # noqa: E402

ERROR_LIMITS_MM = (2.0, 5.0)
NCC_LIMITS = (0.3, 0.5, 0.7)


@dataclass
class FlagScore:
    name: str
    flagged_fraction: float
    trusted_p95_mm: float
    flagged_p95_mm: float
    detection: dict[str, dict[str, float]]


def _score(flag: np.ndarray, bad: np.ndarray, error_mm: np.ndarray, name: str) -> FlagScore:
    true_positive = int(np.sum(flag & bad))
    false_positive = int(np.sum(flag & ~bad))
    false_negative = int(np.sum(~flag & bad))
    trusted = error_mm[~flag]
    flagged = error_mm[flag]
    return FlagScore(
        name=name,
        flagged_fraction=float(np.mean(flag)) if flag.size else 0.0,
        trusted_p95_mm=float(np.percentile(trusted, 95)) if trusted.size else float("nan"),
        flagged_p95_mm=float(np.percentile(flagged, 95)) if flagged.size else float("nan"),
        detection={
            "precision": true_positive / max(true_positive + false_positive, 1),
            "recall": true_positive / max(true_positive + false_negative, 1),
            "flagged": int(flag.sum()),
            "bad": int(bad.sum()),
        },
    )


def run_variant(noise_db: float, decorrelation: float) -> tuple[float, dict[str, FlagScore]] | None:
    from echo_personal_tool.application.workers.speckle_worker import SpeckleTrackingWorker
    from echo_personal_tool.domain.models.speckle import SpeckleConfig

    config = StePhantomConfig.quick(mode="uniform", noise_db=noise_db, decorrelation=decorrelation)
    phantom = StePhantom(config)
    payload: dict = {}
    worker = SpeckleTrackingWorker(
        frames=phantom.frames(),
        zone=phantom.zone(),
        pixel_spacing=(config.pixel_spacing_mm, config.pixel_spacing_mm),
        frame_time_ms=config.frame_time_ms,
        manual_ed=0,
        manual_es=config.es_index,
        view="A4C",
        config=SpeckleConfig.preset_standard(),
    )
    worker.signals.finished.connect(lambda result: payload.setdefault("result", result))
    worker.signals.error.connect(lambda message: payload.setdefault("error", message))
    worker.run()
    if "error" in payload:
        print(f"  {noise_db:.0f} dB: ERROR {payload['error']}")
        return None

    result = payload["result"]
    positions = np.asarray(result.tracked_positions_all, dtype=np.float64)
    closure = np.asarray(result.closure_all_frames, dtype=np.float64)
    ncc = np.asarray(result.ncc_all_frames, dtype=np.float64)
    gate_px = float(result.closure_gate_px)

    centers = np.array([kernel.center for kernel in result.kernels], dtype=np.float64)
    truth = np.stack([phantom.deform(centers, t) for t in range(positions.shape[0])])
    error_mm = np.linalg.norm(positions - truth, axis=2) * config.pixel_spacing_mm

    # Same window the QC report uses (end diastole .. end systole), so the
    # flagged shares below can be compared with ``qc_rejected_fraction``: a
    # share measured over the whole tracked window would be a different number
    # than the one the clinician's report shows.
    window = slice(int(result.ed_index), int(result.es_index) + 1)
    error = error_mm[window]
    closure = closure[window]
    ncc = ncc[window]
    # The shares below are over all node-frames of the window, so the candidate
    # flags stay comparable with each other; the QC report states its rejection
    # share among the *verified* ones, so both are printed to keep the two
    # definitions from being read as a disagreement.
    verified_all = np.isfinite(closure_all_window := np.asarray(result.closure_all_frames)[window])
    rejected_all = verified_all & (closure_all_window > float(result.closure_gate_px))
    print(
        f"    GLS {result.gls:.2f} % | status {result.qc_status} | closure rejected: "
        f"{rejected_all.sum() / max(int(verified_all.sum()), 1) * 100:.1f} % of verified node-frames "
        f"(QC reports {result.qc_rejected_fraction * 100:.1f} %), {rejected_all.mean() * 100:.1f} % of all"
    )

    verified = np.isfinite(closure)
    scores: dict[str, FlagScore] = {}
    for limit in ERROR_LIMITS_MM:
        bad = error > limit
        scores[f"closure_gt{limit:g}mm"] = _score(verified & (closure > gate_px), bad, error, f"closure>{limit:g}mm")
    for limit in ERROR_LIMITS_MM:
        bad = error > limit
        for ncc_limit in NCC_LIMITS:
            scores[f"ncc{ncc_limit:g}_gt{limit:g}mm"] = _score(
                np.isfinite(ncc) & (ncc < ncc_limit), bad, error, f"ncc<{ncc_limit:g}>{limit:g}mm"
            )
    return gate_px, scores


def print_report(rows: list[tuple[float, float, dict[str, FlagScore]]]) -> None:
    for noise_db, gate_px, scores in rows:
        print(f"\n=== {noise_db:.0f} dB (closure gate {gate_px:.0f} px) ===")
        print(f"{'flag':22} {'flagged %':>10} {'trusted p95':>12} {'flagged p95':>12} {'precision':>10} {'recall':>7}")
        for name, score in scores.items():
            print(
                f"{name:22} {score.flagged_fraction * 100:10.1f} {score.trusted_p95_mm:12.2f}"
                f" {score.flagged_p95_mm:12.2f} {score.detection['precision']:10.2f} {score.detection['recall']:7.2f}"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, default=None, help="write the raw scores to this JSON file")
    args = parser.parse_args()

    rows = []
    for noise_db, decorrelation in ((40.0, 0.25), (20.0, 0.35), (10.0, 0.25)):
        print(f"running uniform {noise_db:.0f} dB …", flush=True)
        outcome = run_variant(noise_db, decorrelation)
        if outcome is not None:
            rows.append((noise_db, outcome[0], outcome[1]))

    print_report(rows)

    if args.json:
        payload = {
            "generated": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
            "limits_mm": list(ERROR_LIMITS_MM),
            "ncc_limits": list(NCC_LIMITS),
            "results": [
                {
                    "noise_db": noise_db,
                    "closure_gate_px": gate_px,
                    "flags": {
                        name: {
                            "flagged_fraction": score.flagged_fraction,
                            "trusted_p95_mm": score.trusted_p95_mm,
                            "flagged_p95_mm": score.flagged_p95_mm,
                            "detection": score.detection,
                        }
                        for name, score in scores.items()
                    },
                }
                for noise_db, gate_px, scores in rows
            ],
        }
        args.json.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nJSON written to {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
