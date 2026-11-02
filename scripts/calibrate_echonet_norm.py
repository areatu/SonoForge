#!/usr/bin/env python3
"""Compute EchoNet-Dynamic fixed mean/std from Tier-1 DICOM training set.

Reads DICOM files from a directory, applies the same preprocessing pipeline
(crop → resize to 112×112 → RGB), and computes dataset-wide channel mean/std.

Usage:
    python scripts/calibrate_echonet_norm.py --input-dir /path/to/tier1_dicom
    python scripts/calibrate_echonet_norm.py --input-dir /path/to/tier1_dicom --output-json models/model_manifest.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = PROJECT_ROOT / "models" / "model_manifest.json"


def _to_grayscale_frame(frame: np.ndarray) -> np.ndarray:
    """Convert a DICOM frame to 2D grayscale float32."""
    array = np.asarray(frame)
    if array.ndim == 2:
        return array.astype(np.float32)
    if array.ndim == 3 and array.shape[-1] in (3, 4):
        return np.mean(array[..., :3], axis=2).astype(np.float32)
    raise ValueError(f"unsupported frame shape: {array.shape}")


def _load_dicom_frames(input_dir: Path, max_frames: int = 500) -> list[np.ndarray]:
    """Load grayscale DICOM frames from directory."""
    try:
        import pydicom
    except ImportError:
        print("Error: pydicom required. Install via: pip install pydicom", file=sys.stderr)
        sys.exit(1)

    frames: list[np.ndarray] = []
    dicom_files = sorted(input_dir.rglob("*.dcm"))
    if not dicom_files:
        dicom_files = sorted(input_dir.rglob("*.dicom"))

    for dcm_path in dicom_files:
        if len(frames) >= max_frames:
            break
        try:
            ds = pydicom.dcmread(str(dcm_path), stop_before_pixels=False)
            if not hasattr(ds, "pixel_array"):
                continue
            pixel_array = ds.pixel_array
            if pixel_array.ndim == 4:
                for frame_idx in range(pixel_array.shape[0]):
                    if len(frames) >= max_frames:
                        break
                    frames.append(_to_grayscale_frame(pixel_array[frame_idx]))
            elif pixel_array.ndim == 3:
                if pixel_array.shape[-1] in (3, 4):
                    frames.append(_to_grayscale_frame(pixel_array))
                else:
                    for frame_idx in range(pixel_array.shape[0]):
                        if len(frames) >= max_frames:
                            break
                        frames.append(_to_grayscale_frame(pixel_array[frame_idx]))
            elif pixel_array.ndim == 2:
                frames.append(_to_grayscale_frame(pixel_array))
        except Exception:
            continue

    return frames


def _preprocess_frame(frame: np.ndarray, target_size: int = 112) -> np.ndarray:
    """Apply EchoNet preprocessing: resize to target_size, convert to RGB."""
    from scipy import ndimage

    array = frame.astype(np.float32)
    if array.max() > 255:
        array = array / array.max() * 255.0

    h, w = array.shape[:2]
    zoom_y = target_size / h
    zoom_x = target_size / w
    resized = ndimage.zoom(array, (zoom_y, zoom_x), order=3)

    rgb = np.stack([resized, resized, resized], axis=-1)
    return rgb


def compute_dataset_stats(
    input_dir: Path,
    target_size: int = 112,
    max_frames: int = 500,
) -> tuple[list[float], list[float]]:
    """Compute channel-wise mean and std across dataset."""
    frames = _load_dicom_frames(input_dir, max_frames=max_frames)
    if not frames:
        print(f"No DICOM frames found in {input_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded {len(frames)} frames from {input_dir}")

    all_pixels: list[np.ndarray] = []
    for frame in frames:
        processed = _preprocess_frame(frame, target_size=target_size)
        all_pixels.append(processed.reshape(-1, 3))

    concatenated = np.concatenate(all_pixels, axis=0)
    mean = concatenated.mean(axis=0) / 255.0
    std = concatenated.std(axis=0) / 255.0

    return mean.tolist(), std.tolist()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compute EchoNet-Dynamic fixed mean/std from Tier-1 DICOM set.",
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        required=True,
        help="Directory with Tier-1 DICOM files (recursive search).",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=MANIFEST_PATH,
        help="Path to model_manifest.json to update (default: models/model_manifest.json).",
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=500,
        help="Maximum number of frames to process (default: 500).",
    )
    args = parser.parse_args()

    if not args.input_dir.is_dir():
        print(f"Error: {args.input_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    mean, std = compute_dataset_stats(
        args.input_dir,
        max_frames=args.max_frames,
    )

    print(f"Computed mean: {[round(v, 6) for v in mean]}")
    print(f"Computed std:  {[round(v, 6) for v in std]}")

    if args.output_json.is_file():
        with args.output_json.open(encoding="utf-8") as f:
            manifest = json.load(f)
    else:
        manifest = {}

    preprocessing = manifest.setdefault("preprocessing", {})
    preprocessing["fixed_mean"] = [round(v, 6) for v in mean]
    preprocessing["fixed_std"] = [round(v, 6) for v in std]
    preprocessing["normalization_mode"] = "fixed_if_available"

    with args.output_json.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Updated {args.output_json}")


if __name__ == "__main__":
    main()
