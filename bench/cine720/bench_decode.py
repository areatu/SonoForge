"""Decode-path benchmark for 1280x720 multiframe DICOM cines (uses repo code)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import psutil

_REPO_SRC = str(Path(__file__).resolve().parents[2] / "src")
if _REPO_SRC not in sys.path:
    sys.path.insert(0, _REPO_SRC)

from echo_personal_tool.infrastructure.dicom_session import DicomSession  # noqa: E402

PROC = psutil.Process()


def rss() -> float:
    return PROC.memory_info().rss / 1e6


def bench(path: Path) -> None:
    n_bytes = path.stat().st_size
    base_rss = rss()
    s = DicomSession()
    t0 = time.perf_counter()
    s.open(path)
    t_open = (time.perf_counter() - t0) * 1000
    rss_after_open = rss()
    n = s.frame_count

    t0 = time.perf_counter()
    first = s.decode_first_frame()
    t_first = (time.perf_counter() - t0) * 1000
    rss_after_first = rss()

    # single-frame random access, 30 frames spread over the cine
    idxs = np.linspace(0, n - 1, min(30, n)).astype(int)
    t0 = time.perf_counter()
    for i in idxs:
        s.decode_single_frame(int(i))
    t_single_total = (time.perf_counter() - t0) * 1000

    # sequential decode of the whole cine frame-by-frame (prefetch path)
    t0 = time.perf_counter()
    for i in range(n):
        s.decode_single_frame(i)
    t_seq = (time.perf_counter() - t0) * 1000
    rss_after_seq = rss()

    s.release_heavy()

    # decode_all_frames (bulk path, needs a fresh session)
    s2 = DicomSession()
    s2.open(path)
    t0 = time.perf_counter()
    frames = s2.decode_all_frames()
    t_all = (time.perf_counter() - t0) * 1000
    rss_after_all = rss()
    writable = bool(frames.flags.writeable)
    shape = frames.shape
    dtype = frames.dtype
    del frames
    s2.release_heavy()
    s2.release()
    s.release()

    frame_bytes = int(np.prod(shape[1:])) * np.dtype(dtype).itemsize
    print(f"\n=== {path.name} ===")
    print(f"  file size          : {n_bytes/1e6:8.2f} MB   frames={n}  frame={shape[1:]} {dtype}  {frame_bytes/1e6:.2f} MB/frame")
    print(f"  open()             : {t_open:8.1f} ms   (RSS {base_rss:.0f} -> {rss_after_open:.0f} MB, +{rss_after_open-base_rss:.0f})")
    print(f"  decode_first_frame : {t_first:8.1f} ms   (RSS {rss_after_first:.0f} MB)")
    print(f"  decode_single x{n}  : {t_seq:8.1f} ms  -> {t_seq/n:6.2f} ms/frame  {1000/(t_seq/n):7.1f} fps   (RSS {rss_after_seq:.0f} MB)")
    print(f"  random access x{len(idxs)} : {t_single_total:8.1f} ms  -> {t_single_total/len(idxs):6.2f} ms/frame")
    print(f"  decode_all_frames  : {t_all:8.1f} ms  -> {t_all/n:6.2f} ms/frame  {1000/(t_all/n):7.1f} fps  writeable={writable} (RSS peak {rss_after_all:.0f} MB)")
    print(f"  full-cine RAM if cached: {n*frame_bytes/1e6:.0f} MB")


if __name__ == "__main__":
    for p in sys.argv[1:]:
        bench(Path(p))
