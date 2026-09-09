"""Benchmark DICOM load + decode + thumbnail on gold/ folder."""

import os
import sys
import time
from pathlib import Path

GOLD = Path("/home/areatu/ECHO2026_src/gold")


def bench_one(path: Path) -> dict:
    from pydicom import dcmread

    t0 = time.perf_counter()
    ds = dcmread(str(path), stop_before_pixels=False)
    t_read = time.perf_counter() - t0

    # Decode frames
    import numpy as np

    t1 = time.perf_counter()
    try:
        pixel_data = ds.pixel_array
        n_frames = pixel_data.shape[0] if pixel_data.ndim == 3 or (pixel_data.ndim == 4 and pixel_data.shape[-1] in (1, 3)) else 1
    except Exception:
        n_frames = 0
        pixel_data = None
    t_decode = time.perf_counter() - t1

    # Thumbnail from first frame
    t2 = time.perf_counter()
    try:
        if pixel_data is not None:
            frame = pixel_data[0] if n_frames > 0 else pixel_data
            if frame.ndim == 3:
                gray = frame[:, :, 0] if frame.shape[-1] >= 1 else frame.mean(axis=-1)
            else:
                gray = frame
            thumb = gray[::4, ::4]
        else:
            thumb = None
    except Exception:
        thumb = None
    t_thumb = time.perf_counter() - t2

    size_mb = path.stat().st_size / (1024 * 1024)
    return {
        "name": path.name,
        "size_mb": round(size_mb, 1),
        "frames": n_frames,
        "read_ms": round(t_read * 1000, 1),
        "decode_ms": round(t_decode * 1000, 1),
        "thumb_ms": round(t_thumb * 1000, 1),
        "total_ms": round((t_read + t_decode + t_thumb) * 1000, 1),
    }


def main():
    files = sorted(GOLD.glob("*.dcm"))[:30]
    if not files:
        print("No .dcm files in", GOLD)
        sys.exit(1)

    print(f"Benchmarking {len(files)} DICOM files from {GOLD}")
    print(f"{'Name':<20} {'Size':>6} {'Frames':>6} {'Read':>8} {'Decode':>8} {'Thumb':>8} {'Total':>8}")
    print("-" * 80)

    results = []
    for f in files:
        r = bench_one(f)
        results.append(r)
        print(f"{r['name']:<20} {r['size_mb']:>5.1f}M {r['frames']:>6} {r['read_ms']:>7.0f}ms {r['decode_ms']:>7.0f}ms {r['thumb_ms']:>7.0f}ms {r['total_ms']:>7.0f}ms")

    total_read = sum(r["read_ms"] for r in results)
    total_decode = sum(r["decode_ms"] for r in results)
    total_thumb = sum(r["thumb_ms"] for r in results)
    total_all = sum(r["total_ms"] for r in results)
    total_size = sum(r["size_mb"] for r in results)

    print("-" * 80)
    print(f"{'TOTAL':<20} {total_size:>5.1f}M {'':>6} {total_read:>7.0f}ms {total_decode:>7.0f}ms {total_thumb:>7.0f}ms {total_all:>7.0f}ms")
    print(f"\nAvg per file: {total_all / len(results):.0f}ms  |  Throughput: {total_size / (total_all / 1000):.1f} MB/s")


if __name__ == "__main__":
    main()
