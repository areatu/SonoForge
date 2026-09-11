"""How accurate is the frame-to-frame contour tracking, and can we tell without truth?

Two questions, one harness (clinical review Q6):

1. **Accuracy (needs truth).** The kinematic phantom knows where every material
   point went, so the tracked endo/epi kernels can be compared with the exact
   trajectories: median / p95 / max error in millimetres, per layer and per
   frame, for every noise level.
2. **Verification quality (no truth).** Every analysed frame of the *finished*
   trajectory (after interpolation, outlier repair and smoothing) is matched
   back to the end-diastolic frame; the distance by which the round trip misses
   the drawn contour is the tracker's own error estimate — the quantity the
   report shows. This harness prints how well that estimate separates good
   node-frames from bad ones (precision/recall for a true error above 1 mm and
   above 2 mm), which is what licenses the QC gate.

   The flag is asked in the raw image while the strain is measured in the
   motion-compensated frame, so probe translation lands in the round trip but
   not in the strain: the ``rigid``/``zero`` variants therefore measure the flag
   against an error it does not test and are reported for completeness, not
   used to license the gate (their false alarms are the compensation's, not the
   tracker's).

Run::

    LD_LIBRARY_PATH=tools/qtstub/lib QT_QPA_PLATFORM=offscreen \
        ./.venv/bin/python bench/ste_contour_tracking.py [--json OUT]

The phantom grid is quick-mode by default; ``--full`` uses the production-size
phantom (600x800, 46 frames) at the cost of minutes per variant.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests" / "fixtures"))

from ste_phantom import StePhantom, StePhantomConfig  # noqa: E402

# The round trip is judged against a gate of ~5 mm (0.5 x the 24 px search
# radius at a typical 0.4 mm/px), so the interesting question is not only
# whether it finds 1-2 mm errors (it cannot: they are below its resolution) but
# whether it is reliable *at its own resolution*.
ERROR_LIMITS_MM = (1.0, 2.0, 5.0, 10.0)
# Same variant definitions as bench/ste_phantom.py: "gradient" and "zero" are
# not phantom modes but parameterisations of long_axis / rigid.
VARIANTS = (
    # (name, config overrides)
    ("uniform_40db", dict(mode="uniform", noise_db=40.0, decorrelation=0.25)),
    ("uniform_20db", dict(mode="uniform", noise_db=20.0, decorrelation=0.35)),
    ("uniform_10db", dict(mode="uniform", noise_db=10.0, decorrelation=0.25)),
    ("long_axis_20db", dict(mode="long_axis", noise_db=20.0, decorrelation=0.35)),
    ("long_axis_10db", dict(mode="long_axis", noise_db=10.0, decorrelation=0.25)),
    ("gradient_20db", dict(mode="long_axis", apex_base_gradient=0.9, noise_db=20.0, decorrelation=0.35)),
    ("rigid_20db", dict(mode="rigid", rotation_deg=10.0, translation_px=(15.0, -15.0), noise_db=20.0, decorrelation=0.35)),
    ("zero_20db", dict(mode="rigid", decorrelation=0.6, noise_db=20.0)),
)


@dataclass
class VariantResult:
    name: str
    mode: str
    noise_db: float
    truth_gls: float
    gls: float
    qc_status: str
    qc_score: float
    endo_error_mm: dict[str, float] = field(default_factory=dict)
    epi_error_mm: dict[str, float] = field(default_factory=dict)
    closure_median_mm: float = 0.0
    closure_p95_mm: float = 0.0
    rejected_fraction: float = 0.0
    unverified_fraction: float = 0.0
    verified_error_mm: dict[str, float] = field(default_factory=dict)
    rejected_error_mm: dict[str, float] = field(default_factory=dict)
    detection: dict[str, dict[str, float]] = field(default_factory=dict)


def _percentiles(values: np.ndarray) -> dict[str, float]:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return {"p50": float("nan"), "p95": float("nan"), "max": float("nan"), "n": 0}
    return {
        "p50": float(np.percentile(finite, 50)),
        "p95": float(np.percentile(finite, 95)),
        "max": float(np.max(finite)),
        "n": int(finite.size),
    }


def run_variant(name: str, overrides: dict, full: bool) -> VariantResult | None:
    from echo_personal_tool.application.workers.speckle_worker import SpeckleTrackingWorker
    from echo_personal_tool.domain.models.speckle import SpeckleConfig
    from echo_personal_tool.domain.services.speckle_tracking import verification_gate_px

    common = dict(cavity_long_mm=90.0, cavity_short_mm=60.0, wall_mm=8.0, apex_margin_mm=30.0) if full else {}
    # ``full`` is the production-size default configuration (600x800, 46 frames);
    # quick() halves the geometry for CI.
    phantom_config = (
        StePhantomConfig(**{**overrides, **common}) if full else StePhantomConfig.quick(**overrides)
    )
    mode = str(overrides.get("mode", "long_axis"))
    noise_db = float(overrides.get("noise_db", 20.0))
    phantom = StePhantom(phantom_config)
    frames = phantom.frames()
    payload: dict = {}
    worker = SpeckleTrackingWorker(
        frames=frames,
        zone=phantom.zone(),
        pixel_spacing=(phantom_config.pixel_spacing_mm, phantom_config.pixel_spacing_mm),
        frame_time_ms=phantom_config.frame_time_ms,
        manual_ed=0,
        manual_es=phantom_config.es_index,
        view="A4C",
        config=SpeckleConfig.preset_standard(),
    )
    worker.signals.finished.connect(lambda result: payload.setdefault("result", result))
    worker.signals.error.connect(lambda message: payload.setdefault("error", message))
    worker.run()
    if "error" in payload:
        print(f"  {name}: ERROR {payload['error']}")
        return None

    result = payload["result"]
    truth = phantom.ground_truth()
    positions = np.asarray(result.tracked_positions_all, dtype=np.float64)
    closure = np.asarray(result.closure_all_frames, dtype=np.float64)
    kernels = list(result.kernels)
    centers = np.array([kernel.center for kernel in kernels], dtype=np.float64)
    truth_positions = np.stack([phantom.deform(centers, t) for t in range(positions.shape[0])])
    delta = positions - truth_positions
    if mode == "rigid":
        # The pipeline removes the frame-level global translation before the
        # strain is computed, so for a moving probe the contour is compared in
        # that compensated frame; without this the table would report the
        # (deliberately subtracted) probe motion as tracking error.
        delta = delta - np.nanmean(delta, axis=1, keepdims=True)
    error_mm = np.linalg.norm(delta, axis=2) * phantom_config.pixel_spacing_mm

    window_end = int(result.tracking_window_end)
    window = slice(0, window_end + 1)
    endo = np.array([i for i, k in enumerate(kernels) if k.layer == "endo"])
    epi = np.array([i for i, k in enumerate(kernels) if k.layer == "epi"])
    error_window = error_mm[window]
    closure_window = closure[window]

    verified = np.isfinite(closure_window)
    # The verdict must use the same gate the report uses, so the harness imports
    # the shipped predicate instead of restating the constant.
    rejection_gate_px = verification_gate_px(SpeckleConfig.preset_standard())
    rejected = verified & (closure_window > rejection_gate_px)

    out = VariantResult(
        name=name,
        mode=mode,
        noise_db=noise_db,
        truth_gls=float(np.nanmin(truth.line_curve)),
        gls=float(result.gls),
        qc_status=str(result.qc_status),
        qc_score=float(result.qc_score),
        endo_error_mm=_percentiles(error_window[:, endo]),
        epi_error_mm=_percentiles(error_window[:, epi]),
        closure_median_mm=float(result.qc_closure_median_mm),
        closure_p95_mm=float(result.qc_closure_p95_mm),
        rejected_fraction=float(result.qc_rejected_fraction),
        unverified_fraction=float(result.qc_unverified_fraction),
        verified_error_mm=_percentiles(error_window[verified & ~rejected]),
        rejected_error_mm=_percentiles(error_window[rejected]),
    )
    for limit in ERROR_LIMITS_MM:
        bad = error_window > limit
        for label, flag in (("rejected", rejected), ("rejected_or_unverified", ~(verified & ~rejected))):
            true_positive = int(np.sum(flag & bad))
            false_positive = int(np.sum(flag & ~bad))
            false_negative = int(np.sum(~flag & bad))
            out.detection[f"{label}_gt{limit:g}mm"] = {
                "precision": true_positive / max(true_positive + false_positive, 1),
                "recall": true_positive / max(true_positive + false_negative, 1),
                "flagged": int(flag.sum()),
                "bad": int(bad.sum()),
            }
    return out


def print_report(results: list[VariantResult]) -> None:
    print("\n=== contour tracking accuracy (phantom ground truth) ===")
    header = (
        f"{'variant':16} {'GLS':>7} {'truth':>7} {'status':>7} {'endo err mm':>19} {'epi err mm':>19}"
        f" {'closure mm':>13} {'rej %':>6}"
    )
    print(header)
    for r in results:
        endo, epi = r.endo_error_mm, r.epi_error_mm
        print(
            f"{r.name:16} {r.gls:7.2f} {r.truth_gls:7.2f} {r.qc_status:>7}"
            f" {endo['p50']:6.2f}/{endo['p95']:5.2f}/{endo['max']:5.2f}"
            f" {epi['p50']:6.2f}/{epi['p95']:5.2f}/{epi['max']:5.2f}"
            f" {r.closure_median_mm:6.2f}/{r.closure_p95_mm:5.2f} {r.rejected_fraction * 100:6.1f}"
        )

    print("\n=== verification quality: verified vs rejected node-frames ===")
    print(f"{'variant':16} {'verified p50/p95/max':>24} {'rejected p50/p95/max':>24} {'n_rej':>6}")
    for r in results:
        v, j = r.verified_error_mm, r.rejected_error_mm
        print(
            f"{r.name:16} {v['p50']:7.2f}/{v['p95']:6.2f}/{v['max']:7.2f}"
            f" {j['p50']:7.2f}/{j['p95']:6.2f}/{j['max']:7.2f} {j['n']:6d}"
        )

    print("\n=== does the truth-free flag find node-frames that are more than X mm off? ===")
    print("    (a false alarm is only an error against the *strain* frame; the rows marked")
    print("     probe-motion carry the global shift the flag is not supposed to test)")
    print(f"{'variant':16} {'error > 1 mm':>18} {'> 2 mm':>18} {'> 5 mm':>18} {'> 10 mm':>18}   (precision/recall)")
    for r in results:
        mark = " *" if r.mode == "rigid" else "  "
        cells = "".join(
            f" {r.detection[f'rejected_gt{limit:g}mm']['precision']:8.2f}/{r.detection[f'rejected_gt{limit:g}mm']['recall']:.2f}"
            for limit in ERROR_LIMITS_MM
        )
        print(f"{r.name:16}{cells}{mark}")

    print("\n=== summary ===")
    clean = [r for r in results if r.noise_db >= 20.0 and "zero" not in r.name and "rigid" not in r.name]
    noisy = [r for r in results if r.noise_db <= 10.0]
    if clean:
        print(
            "clean (>= 20 dB): rejected "
            f"{min(r.rejected_fraction for r in clean) * 100:.1f}-{max(r.rejected_fraction for r in clean) * 100:.1f} %,"
            f" closure median <= {max(r.closure_median_mm for r in clean):.2f} mm,"
            f" endo error p95 <= {max(r.endo_error_mm['p95'] for r in clean):.2f} mm"
        )
    flagged = [r for r in results if r.mode != "rigid"]
    for limit in ERROR_LIMITS_MM:
        key = f"rejected_gt{limit:g}mm"
        cells = [r.detection[key] for r in flagged]
        print(
            f"flag on non-translating variants, error > {limit:g} mm: precision "
            f"{min(d['precision'] for d in cells):.2f}-{max(d['precision'] for d in cells):.2f}, recall "
            f"{min(d['recall'] for d in cells):.2f}-{max(d['recall'] for d in cells):.2f}"
        )
    if noisy:
        print(
            "noisy (<= 10 dB): rejected "
            f"{min(r.rejected_fraction for r in noisy) * 100:.1f}-{max(r.rejected_fraction for r in noisy) * 100:.1f} %,"
            f" closure median <= {max(r.closure_median_mm for r in noisy):.2f} mm,"
            f" endo error p95 <= {max(r.endo_error_mm['p95'] for r in noisy):.2f} mm"
        )


def _gate_px_for_report() -> float:
    from echo_personal_tool.domain.models.speckle import SpeckleConfig
    from echo_personal_tool.domain.services.speckle_tracking import verification_gate_px

    return verification_gate_px(SpeckleConfig.preset_standard())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true", help="production-size phantom (slow)")
    parser.add_argument("--json", type=Path, default=None, help="write the raw results to this JSON file")
    parser.add_argument("--only", default=None, help="run only variants whose name contains this substring")
    args = parser.parse_args()

    variants = [v for v in VARIANTS if not args.only or args.only in v[0]]
    results: list[VariantResult] = []
    for name, overrides in variants:
        print(f"running {name} …", flush=True)
        out = run_variant(name, dict(overrides), args.full)
        if out is not None:
            results.append(out)

    print_report(results)

    if args.json:
        payload = {
            "generated": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
            "full_spec": bool(args.full),
            "limits_mm": list(ERROR_LIMITS_MM),
        "rejection_gate_px": _gate_px_for_report(),
            "results": [
                {
                    "name": r.name,
                    "mode": r.mode,
                    "noise_db": r.noise_db,
                    "gls": r.gls,
                    "truth_gls": r.truth_gls,
                    "qc_status": r.qc_status,
                    "qc_score": r.qc_score,
                    "endo_error_mm": r.endo_error_mm,
                    "epi_error_mm": r.epi_error_mm,
                    "closure_median_mm": r.closure_median_mm,
                    "closure_p95_mm": r.closure_p95_mm,
                    "rejected_fraction": r.rejected_fraction,
                    "unverified_fraction": r.unverified_fraction,
                    "verified_error_mm": r.verified_error_mm,
                    "rejected_error_mm": r.rejected_error_mm,
                    "detection": r.detection,
                }
                for r in results
            ],
        }
        args.json.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nJSON written to {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
