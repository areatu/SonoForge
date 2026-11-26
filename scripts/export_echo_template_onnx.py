#!/usr/bin/env python3
"""Export a local ML.3 checkpoint as an immutable SHA-verified experimental bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for entry in (ROOT, ROOT / "src"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import numpy as np  # noqa: E402
from scripts.echo_template_network import build_template_network  # noqa: E402
from scripts.generate_synthetic_echo_corpus import validate_output  # noqa: E402

from echo_personal_tool.domain.services.cardiac_atlas import CoupledShapeModel  # noqa: E402
from echo_personal_tool.domain.services.echo_template_contract import (  # noqa: E402
    TEMPLATE_OUTPUTS,
    TEMPLATE_VIEWS,
    validate_atlases,
)


def artifact(path: Path) -> dict:
    return {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def export_bundle(args) -> Path:
    import onnx
    import onnxruntime as ort
    import torch

    output = validate_output(args.output)
    if not 5 <= args.runs <= 200 or not 0 < args.max_p95_ms <= 200:
        raise ValueError("verification needs 5..200 runs and CPU budget <=200ms")
    torch.set_num_threads(1)
    checkpoint = torch.load(args.checkpoint, map_location="cpu", weights_only=True)
    if checkpoint.get("schema_version") != 1 or checkpoint["class_names"] != list(TEMPLATE_VIEWS):
        raise ValueError("unsupported checkpoint")
    atlases = {k: CoupledShapeModel.from_dict(v) for k, v in checkpoint["atlases"].items()}
    validate_atlases(atlases)
    model = build_template_network().eval()
    model.load_state_dict(checkpoint["state_dict"], strict=True)
    size = int(checkpoint["input_size"])
    if size < 64 or size > 512 or size % 32:
        raise ValueError("invalid input size")
    output.mkdir(parents=True)
    path = output / "echo_template.onnx"
    torch.manual_seed(0)
    sample = torch.randn(1, 3, size, size)
    with torch.no_grad():
        torch.onnx.export(
            model,
            sample,
            path,
            input_names=["image"],
            output_names=list(TEMPLATE_OUTPUTS),
            dynamic_axes={"image": {0: "batch"}, **{name: {0: "batch"} for name in TEMPLATE_OUTPUTS}},
            opset_version=17,
            do_constant_folding=True,
        )
        expected = [value.numpy() for value in model(sample)]
    onnx.checker.check_model(onnx.load(path), full_check=True)
    if path.stat().st_size > 12 * 1024 * 1024:
        raise ValueError("FP32 model exceeds 12 MiB target")
    options = ort.SessionOptions()
    options.intra_op_num_threads = options.inter_op_num_threads = 1
    session = ort.InferenceSession(str(path), sess_options=options, providers=["CPUExecutionProvider"])
    inputs = {"image": sample.numpy()}
    actual = session.run(list(TEMPLATE_OUTPUTS), inputs)
    errors = {name: float(np.max(np.abs(a - b))) for name, a, b in zip(TEMPLATE_OUTPUTS, expected, actual)}
    if max(errors.values()) > 1e-4:
        raise ValueError("torch/ONNX head parity exceeds 1e-4")
    for _ in range(3):
        session.run(None, inputs)
    times = []
    for _ in range(args.runs):
        start = time.perf_counter()
        session.run(None, inputs)
        times.append((time.perf_counter() - start) * 1000)
    p95 = float(np.percentile(times, 95))
    if p95 >= args.max_p95_ms:
        raise ValueError("ONNX CPU inference exceeds requested budget")
    atlas_records = {}
    for view, atlas in atlases.items():
        target = output / f"atlas_{view.lower()}.json"
        target.write_text(json.dumps(atlas.to_dict(), sort_keys=True), encoding="utf-8")
        atlas_records[view] = artifact(target)
    report = {
        "ort_cpu_p50_ms": float(np.median(times)),
        "ort_cpu_p95_ms": p95,
        "runs": args.runs,
        "threads": 1,
        "machine": platform.machine(),
        "onnx_bytes": path.stat().st_size,
        "head_max_abs_errors": errors,
        "includes_preprocess_decode": False,
        "clinical_validated": False,
        "torch_version": str(torch.__version__),
        "ort_version": ort.__version__,
    }
    (output / "export_verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    manifest = {
        "echo_template": {
            "schema_version": 1,
            "architecture": checkpoint["architecture"],
            "class_names": list(TEMPLATE_VIEWS),
            "input_size": size,
            "preprocessing": "sector_ecg_iyx_v1",
            "model": artifact(path),
            "atlases": atlas_records,
            "ood": {"min_cosine": 0.25, "min_confidence": 0.35, "max_entropy": 0.88},
            "clinical_validated": False,
            "candidate_only": True,
            "verification": artifact(output / "export_verification.json"),
        }
    }
    (output / "model_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return output / "model_manifest.json"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--max-p95-ms", type=float, default=200)
    args = parser.parse_args(argv)
    try:
        path = export_bundle(args)
    except (ValueError, OSError, ImportError, KeyError) as exc:
        sys.stderr.write(f"Template export failed: {type(exc).__name__}\n")
        return 2
    sys.stdout.write(f"Experimental bundle: {path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
