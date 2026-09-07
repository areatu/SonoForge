"""Per-frame render breakdown on the main thread (why is a frame expensive?).

Wraps the real ViewerWidget call chain with timers and plays the cine through the real
AppController, then prints where the main-thread budget goes:

    show_frame_fast total
      ├─ _update_levels
      │    ├─ compute_display_levels (percentiles over the whole frame)
      │    ├─ _is_levels_outlier     (float64 mean/std over the whole frame)
      │    ├─ _ensure_display_buffer
      │    └─ ImageItem.setImage     (LUT + texture upload)
      └─ viewport repaint (raster/GL)

Usage:
    QT_QPA_PLATFORM=offscreen python probe_render_breakdown.py <cine.dcm> --frames 60
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("ECHO_PLAYBACK_DIAG", "1")

_REPO_SRC = str(Path(__file__).resolve().parents[2] / "src")
if _REPO_SRC not in sys.path:
    sys.path.insert(0, _REPO_SRC)

import numpy as np  # noqa: E402
import psutil  # noqa: E402
import pyqtgraph as pg  # noqa: E402

PROC = psutil.Process()
ACC: dict[str, float] = {}
CNT: dict[str, int] = {}


def _wrap(obj, name, key):
    orig = getattr(obj, name)

    def wrapper(*a, **kw):
        t0 = time.perf_counter()
        try:
            return orig(*a, **kw)
        finally:
            ACC[key] = ACC.get(key, 0.0) + (time.perf_counter() - t0)
            CNT[key] = CNT.get(key, 0) + 1

    setattr(obj, name, wrapper)
    return orig


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--frames", type=int, default=60)
    ap.add_argument("--frame-time", type=float, default=33.3)
    ap.add_argument("--seconds", type=float, default=6.0)
    ap.add_argument("--cache-mb", type=int, default=64)
    ap.add_argument("--format", default="dicom")
    ap.add_argument("--fix-session", action="store_true", help="prototype: process-wide session")
    ap.add_argument("--fix-levels", action="store_true",
                    help="prototype: dtype-aware W/L outlier heuristic (restores the levels cache for uint16)")
    args = ap.parse_args()
    path = Path(args.path).resolve()

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])

    from echo_personal_tool.application.app_controller import AppController
    from echo_personal_tool.application.frame_cache import FrameCache
    from echo_personal_tool.domain.models.metadata import InstanceMetadata
    from echo_personal_tool.presentation import viewer_widget as vw

    if args.fix_session:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import sessioncache_patch

        sessioncache_patch.apply(keep_warm=True)

    controller = AppController()
    cfg = controller.playback_config
    controller._frame_cache = FrameCache(
        evict_window=cfg.evict_window, max_cache_bytes=args.cache_mb * 1024 * 1024
    )

    if args.fix_levels:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import levelsfix_patch

        levelsfix_patch.apply()
        print("[fix-levels] display-levels cache restored (key order + dtype-aware outlier)")

    # ---- instrument BEFORE the widget is constructed ----
    from echo_personal_tool.application import app_controller as ac

    _wrap(ac, "resolve_cine_segment_roi_xyxy", "resolve_cine_segment_roi (controller)")
    _wrap(vw, "compute_display_levels", "compute_display_levels")
    _wrap(vw.ViewerWidget, "_update_levels", "_update_levels")
    _wrap(vw.ViewerWidget, "_is_levels_outlier", "_is_levels_outlier")
    _wrap(vw.ViewerWidget, "_ensure_display_buffer", "_ensure_display_buffer")
    _wrap(vw.ViewerWidget, "show_frame_fast", "show_frame_fast")
    _wrap(pg.ImageItem, "setImage", "ImageItem.setImage")

    viewer = vw.ViewerWidget()
    viewer.resize(1400, 820)
    viewer.show()

    paint_ms: list[float] = []
    frame_times: list[float] = []

    def on_frame(pixels):
        img = np.asarray(pixels)
        viewer.show_frame_fast(img)
        t1 = time.perf_counter()
        viewer._graphics.viewport().repaint()
        paint_ms.append((time.perf_counter() - t1) * 1000)
        frame_times.append(time.perf_counter())

    controller.frame_loaded.connect(on_frame)
    controller.state_manager.state_changed.connect(viewer.set_state)

    instance = InstanceMetadata(
        sop_instance_uid="1.2.3.4.5",
        series_uid="1.2.3.4",
        modality="US",
        number_of_frames=args.frames,
        pixel_spacing=(0.2, 0.2),
        frame_time_ms=args.frame_time,
        series_description="bench",
        path=path,
        media_format=args.format,
    )
    controller.load_instance(instance)
    deadline = time.perf_counter() + 20.0
    while controller._pending_decode_id != 0 and time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.002)

    # reset counters so warm-up/first-frame work does not pollute the playback stats
    ACC.clear()
    CNT.clear()
    paint_ms.clear()
    frame_times.clear()

    controller.set_playing(True)
    t_play = time.perf_counter()
    QTimer.singleShot(int(args.seconds * 1000), app.quit)
    rss_peak = PROC.memory_info().rss / 1e6
    while True:
        app.processEvents()
        rss_peak = max(rss_peak, PROC.memory_info().rss / 1e6)
        if not controller.state_manager.snapshot.is_playing and time.perf_counter() - t_play > 1.0:
            break
        if time.perf_counter() - t_play > args.seconds + 2.0:
            break
    elapsed = time.perf_counter() - t_play
    controller.set_playing(False)
    app.processEvents()

    n = max(len(frame_times), 1)
    fps = len(frame_times) / elapsed if elapsed > 0 else 0.0
    dtype = "?"
    if controller._frame_cache.is_loaded(0):
        f0 = controller._frame_cache.get(0)
        dtype = f"{f0.shape} {f0.dtype}"

    print(f"\n=== render breakdown: {path.name} ===")
    print(f"  frame: {dtype}   frames shown: {len(frame_times)} in {elapsed:.2f}s -> {fps:.2f} FPS")
    print(f"  peak RSS: {rss_peak:.0f} MB")
    print(f"  {'operation':32s} {'calls':>7s} {'ms/call':>9s} {'total ms':>10s} {'ms/frame':>9s}")

    def row(key):
        c = CNT.get(key, 0)
        tot = ACC.get(key, 0.0) * 1000
        per_call = tot / c if c else 0.0
        print(f"  {key:32s} {c:7d} {per_call:9.2f} {tot:10.1f} {tot / n:9.2f}")

    for key in (
        "resolve_cine_segment_roi (controller)",
        "show_frame_fast",
        "_update_levels",
        "compute_display_levels",
        "_is_levels_outlier",
        "_ensure_display_buffer",
        "ImageItem.setImage",
    ):
        if CNT.get(key):
            row(key)
    tot_paint = sum(paint_ms)
    print(f"  {'viewport repaint':32s} {len(paint_ms):7d} "
          f"{tot_paint / max(len(paint_ms), 1):9.2f} {tot_paint:10.1f} {tot_paint / n:9.2f}")
    budget = 1000.0 / args.frame_time
    main_ms = (
        ACC.get("show_frame_fast", 0.0) * 1000
        + ACC.get("resolve_cine_segment_roi (controller)", 0.0) * 1000
        + tot_paint
    ) / n
    print(f"  main-thread per frame: {main_ms:.2f} ms of {1000.0 / budget:.1f} ms budget "
          f"({100 * main_ms * budget / 1000:.0f}%)")
    if CNT.get("compute_display_levels", 0) > 0:
        ratio = CNT["compute_display_levels"] / n
        print(f"  levels recomputed on {100 * ratio:.0f}% of frames "
              f"(expected 0% once cached -> outlier heuristic misfiring)")


if __name__ == "__main__":
    main()
