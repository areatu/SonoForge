"""STE phantom validation runner (plan rev.4 §3.7 KPI, §7.1 phantom).

Runs the *whole* STE pipeline (worker → tracking → node curves → segment
curves → metrics) on the kinematic phantom and prints, for every variant and
noise level, the measured values next to the exact ground truth:

    criterion                          gate (plan §3.7)
    |ΔGLS| uniform deformation         ≤ 1.0 pp
    |ΔGLS| apex↔base gradient          ≤ 2.0 pp
    per-segment RMS error              ≤ 2.5 pp
    time-to-peak error                 ≤ 1 frame
    rigid motion |ΔGLS|                ≤ 0.5 pp
    zero-strain |GLS|                  ≤ 0.5 pp

Usage::

    PYTHONPATH=src python bench/ste_phantom.py               # quick matrix
    PYTHONPATH=src python bench/ste_phantom.py --full        # full spec (§7.1)
    PYTHONPATH=src python bench/ste_phantom.py --json out.json

The script needs no GUI: it drives ``SpeckleTrackingWorker`` directly and
collects the result through its Qt signal, so PySide6 must be importable (a
headless Qt stub is enough, see ``tools/qtstub``).
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests" / "fixtures"))

from ste_phantom import PhantomGroundTruth, StePhantom, StePhantomConfig  # noqa: E402

from echo_personal_tool.application.workers.speckle_worker import (  # noqa: E402
    SpeckleTrackingWorker,
)
from echo_personal_tool.domain.models.speckle import SpeckleConfig  # noqa: E402

KPI = {
    "gls_uniform_pp": 1.0,
    "gls_gradient_pp": 2.0,
    "segment_rms_pp": 2.5,
    "ttp_frames": 1.0,
    "rigid_pp": 0.5,
    "zero_pp": 0.5,
}


@dataclass
class Variant:
    """One phantom configuration of the validation matrix."""

    name: str
    config: StePhantomConfig
    expectation: str  # "uniform" | "gradient" | "rigid" | "zero"
    notes: str = ""


@dataclass
class VariantResult:
    variant: str
    expectation: str
    noise_db: float
    decorrelation: float
    truth: dict
    measured: dict = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)
    runtime_s: float = 0.0
    error: str | None = None


def build_matrix(full: bool) -> list[Variant]:
    """Variant × noise matrix of plan §7.1."""
    base = (lambda **kw: StePhantomConfig(**kw)) if full else (lambda **kw: StePhantomConfig.quick(**kw))
    common = dict(cavity_long_mm=90.0, cavity_short_mm=60.0, wall_mm=8.0, apex_margin_mm=30.0) if full else {}
    variants = [
        Variant("uniform", base(mode="uniform", **common), "uniform", "isotropic scaling: identical true strain everywhere"),
        Variant("long_axis", base(mode="long_axis", **common), "uniform", "physiological wall motion, apex/base strain spread"),
        Variant("gradient", base(mode="long_axis", apex_base_gradient=0.9, **common), "gradient", "strong apex↔base strain gradient"),
        Variant("rigid", base(mode="rigid", rotation_deg=10.0, translation_px=(15.0, -15.0), **common), "rigid"),
        Variant("zero", base(mode="rigid", decorrelation=0.6, **common), "zero", "no deformation, only decorrelation"),
    ]
    out: list[Variant] = []
    for variant in variants:
        for noise_db in (0.0, 5.0, 10.0, 20.0):
            out.append(
                Variant(
                    name=f"{variant.name}_snr{int(noise_db)}",
                    config=variant.config.__class__(**{**variant.config.__dict__, "noise_db": noise_db}),
                    expectation=variant.expectation,
                    notes=variant.notes,
                )
            )
    return out


def run_variant(variant: Variant) -> VariantResult:
    """Run one phantom configuration through the full STE worker."""
    config = variant.config
    phantom = StePhantom(config)
    truth: PhantomGroundTruth = phantom.ground_truth()
    frames = phantom.frames()
    result: VariantResult = VariantResult(
        variant=variant.name,
        expectation=variant.expectation,
        noise_db=config.noise_db,
        decorrelation=config.decorrelation,
        truth=truth.to_dict(),
    )

    payload: dict = {}
    worker = SpeckleTrackingWorker(
        frames=frames,
        zone=phantom.zone(),
        pixel_spacing=(config.pixel_spacing_mm, config.pixel_spacing_mm),
        frame_time_ms=config.frame_time_ms,
        manual_ed=0,
        manual_es=config.es_index,
        view="A4C",
        config=SpeckleConfig.preset_standard(),
    )
    worker.signals.finished.connect(lambda r: payload.setdefault("result", r))
    worker.signals.error.connect(lambda message: payload.setdefault("error", message))
    started = time.perf_counter()
    worker.run()
    result.runtime_s = time.perf_counter() - started
    if "error" in payload:
        result.error = str(payload["error"])
        return result
    analysis = payload["result"]

    measured = {
        "gls": float(analysis.gls),
        "gls_segment_mean": float(getattr(analysis, "gls_segment_mean", float("nan"))),
        "ess": float(getattr(analysis, "ess", float("nan"))),
        "peak_frame": int(getattr(analysis, "gls_peak_frame", -1) or -1),
        "avc_index": int(getattr(analysis, "avc_index", -1)),
        "quality": float(getattr(analysis, "qc_score", float("nan"))),
        "quality_status": str(getattr(analysis, "qc_status", "?")),
        "tracking_quality": float(getattr(analysis, "tracking_quality_mean", float("nan"))),
        "kernels_accepted": int(getattr(analysis, "kernels_accepted_count", 0)),
        "kernels_total": int(getattr(analysis, "kernels_total_count", 0)),
        "segment_strain": {str(k): float(v) for k, v in dict(getattr(analysis, "segment_strain", {})).items()},
        "segment_spread_pp": abs(
            float(analysis.gls) - float(getattr(analysis, "gls_segment_mean", float("nan")))
        ),
        "qc_estimate_spread_pp": float(getattr(analysis, "qc_estimate_spread_pp", float("nan"))),
        "qc_sign_flip_fraction": float(getattr(analysis, "qc_sign_flip_fraction", float("nan"))),
        "qc_consistency_delta": float(getattr(analysis, "qc_consistency_delta", float("nan"))),
        "qc_coverage": float(getattr(analysis, "qc_coverage", float("nan"))),
        "qc_interpolated_fraction": float(getattr(analysis, "qc_interpolated_fraction", float("nan"))),
        "qc_reasons": list(getattr(analysis, "qc_reasons", ()) or ()),
        "segment_quality": {str(k): float(v) for k, v in dict(getattr(analysis, "segment_quality", {})).items()},
    }
    result.measured = measured

    node_curves = getattr(analysis, "node_curves", None)
    if node_curves is not None:
        curves = np.asarray(node_curves, dtype=np.float64)
        if curves.ndim == 2 and curves.size:
            es_index = int(min(max(truth.es_index, 0), curves.shape[0] - 1))
            measured["node_ess_median"] = float(np.nanmedian(curves[es_index]))
            measured["node_ess_spread_pp"] = float(
                np.nanmedian(np.abs(curves[es_index] - np.nanmedian(curves[es_index])))
            )
    errors: dict[str, float] = {}
    recorded = dict(measured["segment_strain"])
    for segment, value in truth.segment_values.items():
        if str(segment) in recorded:
            errors[str(segment)] = float(recorded[str(segment)] - value)
    if errors:
        result.metrics["segment_rms_pp"] = float(np.sqrt(np.mean(np.square(list(errors.values())))))
        result.metrics["segment_mae_pp"] = float(np.mean(np.abs(list(errors.values()))))
        result.metrics["segment_max_abs_pp"] = float(np.max(np.abs(list(errors.values()))))
    result.metrics["gls_bias_pp"] = float(measured["gls"] - truth.peak)
    result.metrics["gls_abs_error_pp"] = abs(result.metrics["gls_bias_pp"])
    if truth.time_to_peak_ms == truth.time_to_peak_ms and config.frame_time_ms > 0:
        result.metrics["ttp_error_frames"] = abs(
            float(getattr(analysis, "time_to_peak_ms", float("nan")) - truth.time_to_peak_ms)
        ) / config.frame_time_ms
    return result


def evaluate(result: VariantResult) -> tuple[bool, list[str]]:
    """Check one result against the KPI gates of plan §3.7."""
    findings: list[str] = []
    if result.error:
        return False, [f"pipeline error: {result.error}"]
    metrics = result.metrics
    gate = KPI["gls_uniform_pp"] if result.expectation == "uniform" else KPI["gls_gradient_pp"]
    if result.expectation in ("rigid", "zero"):
        gate = KPI["rigid_pp"] if result.expectation == "rigid" else KPI["zero_pp"]
    ok = True
    if metrics.get("gls_abs_error_pp", float("inf")) > gate:
        findings.append(f"GLS off by {metrics['gls_abs_error_pp']:.2f} pp (gate {gate:.1f})")
        ok = False
    if metrics.get("segment_rms_pp", 0.0) > KPI["segment_rms_pp"]:
        findings.append(f"segment RMS {metrics['segment_rms_pp']:.2f} pp (gate {KPI['segment_rms_pp']:.1f})")
        ok = False
    # TTP is defined for a curve that has a systolic peak; a phantom whose true
    # strain is identically zero has no peak time to compare against, and the
    # value is then pure tracking noise. It stays in the report, un-gated.
    truth_peak = float(result.truth.get("line_curve_peak", 0.0) or 0.0)
    if abs(truth_peak) >= 1.0 and metrics.get("ttp_error_frames", 0.0) > KPI["ttp_frames"]:
        findings.append(f"TTP off by {metrics['ttp_error_frames']:.2f} frames (gate {KPI['ttp_frames']:.1f})")
        ok = False
    return ok, findings


def print_report(results: list[VariantResult]) -> None:
    header = (
        f"{'variant':16s} {'expect':9s} {'truth GLS':>9s} {'measured':>9s} {'bias':>7s} "
        f"{'seg RMS':>8s} {'TTP err':>8s} {'qual':>5s} {'status':>8s} {'time':>6s}"
    )
    print(header)
    print("-" * len(header))
    for result in results:
        if result.error:
            print(f"{result.variant:16s} {result.expectation:9s}  ERROR: {result.error}")
            continue
        metrics = result.metrics
        print(
            f"{result.variant:16s} {result.expectation:9s} "
            f"{result.truth['line_curve_peak']:9.2f} {result.measured['gls']:9.2f} "
            f"{metrics.get('gls_bias_pp', float('nan')):+7.2f} "
            f"{metrics.get('segment_rms_pp', float('nan')):8.2f} "
            f"{metrics.get('ttp_error_frames', float('nan')):8.2f} "
            f"{result.measured['quality']:5.2f} {result.measured['quality_status']:>8s} "
            f"{result.runtime_s:5.1f}s"
        )

    passed = [r for r in results if not r.error]
    failures = [(r, *evaluate(r)) for r in passed]
    bad = [(r, findings) for r, ok, findings in failures if not ok]
    print()
    print(f"variants: {len(results)} | evaluated: {len(passed)} | KPI failures: {len(bad)}")
    for result, findings in bad:
        print(f"  ✗ {result.variant}: " + "; ".join(findings))
    if not bad and passed:
        print("  ✓ all KPI gates met")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true", help="full phantom spec (600×800, 46 frames) instead of the quick one")
    parser.add_argument("--json", type=Path, default=None, help="write the raw results to this JSON file")
    parser.add_argument("--only", default=None, help="run only variants whose name contains this substring")
    args = parser.parse_args()

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    del app

    variants = build_matrix(args.full)
    if args.only:
        variants = [v for v in variants if args.only in v.name]
    results: list[VariantResult] = []
    for variant in variants:
        print(f"… running {variant.name}", flush=True)
        results.append(run_variant(variant))
    print_report(results)

    if args.json:
        payload = {
            "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "full_spec": bool(args.full),
            "kpi": KPI,
            "results": [
                {
                    "variant": r.variant,
                    "expectation": r.expectation,
                    "noise_db": r.noise_db,
                    "decorrelation": r.decorrelation,
                    "runtime_s": r.runtime_s,
                    "truth": r.truth,
                    "measured": r.measured,
                    "metrics": r.metrics,
                    "error": r.error,
                }
                for r in results
            ],
        }
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nJSON written to {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
