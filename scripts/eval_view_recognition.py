"""Evaluate a trained view-recognition ONNX model on a labelled corpus (#639 step 2).

Runs the ONNX classifier over a manifest split, compares predictions to the
gold view labels and reports top-1 accuracy, per-class recall and confusion
counts through the pure step-5 helpers in
:mod:`echo_personal_tool.domain.services.view_recognition_metrics`.

Usage::

    python scripts/eval_view_recognition.py \
        --manifest models/view_recognition_manifest.json \
        --models-dir models \
        --split test

The script writes a JSON report to ``--report`` (default
``models/view_recognition_eval.json``).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from echo_personal_tool.domain.models.view_recognition import KNOWN_VIEWS
from echo_personal_tool.domain.services.view_recognition_metrics import (
    accuracy_summary,
)
from echo_personal_tool.infrastructure.view_recognition_dataset import (
    ViewRecognitionDataset,
    build_dicom_clip_provider,
    load_manifest,
)
from echo_personal_tool.infrastructure.view_recognition_onnx import OnnxViewRecognizer

DEFAULT_REPORT = PROJECT_ROOT / "models" / "view_recognition_eval.json"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--models-dir", type=Path, required=True)
    parser.add_argument("--split", default="test")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--synthetic", action="store_true")
    return parser.parse_args(argv)


def _synthetic_clip_provider(source_path: str) -> np.ndarray:
    frames = [np.full((224, 224), 0.5, dtype=np.float32) for _ in range(8)]
    return np.stack(frames)


def _resolve_clip_provider(synthetic: bool) -> Callable[[str], np.ndarray]:
    if synthetic:
        return _synthetic_clip_provider
    from echo_personal_tool.infrastructure.dicom_reader import DicomReaderImpl

    return build_dicom_clip_provider(DicomReaderImpl())


def evaluate(
    *,
    manifest_path: Path,
    models_dir: Path,
    split: str,
    clip_provider: Callable[[str], np.ndarray],
) -> dict[str, object]:
    """Run the ONNX recognizer over a split and return an accuracy report."""
    recognizer = OnnxViewRecognizer(models_dir=models_dir)
    if not recognizer.is_available():
        msg = f"ONNX view-recognition model is not available in {models_dir}"
        raise RuntimeError(msg)
    manifest = load_manifest(manifest_path)
    dataset = ViewRecognitionDataset(manifest, clip_provider, split=split)
    gold: list[str] = []
    predicted: list[str] = []
    for clip, label_index in dataset.clips():
        recognized = recognizer.recognize(list(clip))
        gold.append(KNOWN_VIEWS[label_index] if label_index >= 0 else "UNKNOWN")
        predicted.append(recognized.view)
    report = accuracy_summary(gold, predicted, KNOWN_VIEWS)
    return report


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report = evaluate(
        manifest_path=args.manifest,
        models_dir=args.models_dir,
        split=args.split,
        clip_provider=_resolve_clip_provider(args.synthetic),
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"top1={report['top1_accuracy']:.4f} total={report['total']} report={args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
