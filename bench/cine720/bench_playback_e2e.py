"""End-to-end 720p cine playback harness (real AppController + real ViewerWidget, offscreen Qt).

Measures: achieved FPS, tick jitter, cache hit/miss, main-thread render cost, RSS.
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

PROC = psutil.Process()


def rss() -> float:
    return PROC.memory_info().rss / 1e6


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--frames", type=int, default=60)
    ap.add_argument("--frame-time", type=float, default=33.3)
    ap.add_argument("--seconds", type=float, default=8.0)
    ap.add_argument("--cache-mb", type=int, default=64)
    ap.add_argument(
        "--ram-cap-mb",
        type=int,
        default=0,
        help="cap the share of RAM the cache tuning may claim (simulates a small machine)",
    )
    ap.add_argument(
        "--decode-slow-ms",
        type=float,
        default=0.0,
        help="extra wall time per frame decode (simulates a weak CPU; forces real cache misses)",
    )
    ap.add_argument("--profile", choices=["auto", "low", "high"], default="auto")
    ap.add_argument("--warm-session", action="store_true", help="disable release_heavy() after each batch")
    ap.add_argument("--no-render", action="store_true", help="skip viewer render (decode/cache only)")
    ap.add_argument("--label", default="")
    ap.add_argument("--format", default="dicom")
    args = ap.parse_args()

    path = Path(args.path).resolve()

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])

    from echo_personal_tool.application.app_controller import AppController
    from echo_personal_tool.application.frame_cache import FrameCache
    from echo_personal_tool.domain.models.metadata import InstanceMetadata
    from echo_personal_tool.infrastructure.system_profiler import PlaybackConfig

    if args.warm_session:
        from echo_personal_tool.infrastructure import dicom_session as ds_mod

        ds_mod.DicomSession.release_heavy = lambda self: None

    if args.decode_slow_ms > 0:
        # Weak-CPU emulation. Patched on the class (not an instance) so it also applies
        # inside the QThreadPool worker threads that decode prefetch batches.
        from echo_personal_tool.infrastructure import dicom_session as _ds

        _real_decode_single = _ds.DicomSession.decode_single_frame
        _slow_ms = args.decode_slow_ms

        def _slow_decode_single(self, index, *a, **kw):
            time.sleep(_slow_ms / 1000.0)
            return _real_decode_single(self, index, *a, **kw)

        _ds.DicomSession.decode_single_frame = _slow_decode_single

    controller = AppController()
    cfg = controller.playback_config
    if args.profile == "low":
        cfg = PlaybackConfig(5, 3, 5, 2, 12, 80, 3)
    elif args.profile == "high":
        cfg = PlaybackConfig(10, 5, 8, 4, 20, 50, 8)
    controller._playback_config = cfg
    controller._adaptive_batch_size = cfg.batch_size
    controller._frame_cache = FrameCache(evict_window=cfg.evict_window, max_cache_bytes=args.cache_mb * 1024 * 1024)
    if args.ram_cap_mb > 0:
        # _tune_playback_cache() grows the budget towards this ceiling; capping it is how a
        # memory-starved machine is simulated (and how cache misses are forced on purpose).
        controller._cache_ram_cap_bytes = args.ram_cap_mb * 1024 * 1024

    viewer = None
    if not args.no_render:
        from echo_personal_tool.presentation.viewer_widget import ViewerWidget

        viewer = ViewerWidget()
        viewer.resize(1400, 820)
        viewer.show()

    stats = {
        "render_ms": [],
        "paint_ms": [],
        "frame_times": [],
        "indices": [],
        "cache_frames": [],
        "cache_mb": [],
        "miss_polls": [0],
    }

    def on_frame(pixels):
        t0 = time.perf_counter()
        img = np.asarray(pixels)
        if viewer is not None:
            viewer.show_frame_fast(img)
            t1 = time.perf_counter()
            viewer._graphics.viewport().repaint()
            t2 = time.perf_counter()
            stats["render_ms"].append((t1 - t0) * 1000)
            stats["paint_ms"].append((t2 - t1) * 1000)
        else:
            stats["render_ms"].append(0.0)
            stats["paint_ms"].append(0.0)
        now = time.perf_counter()
        if stats.get("first_advance_ms") and stats["first_advance_ms"][0] is None:
            stats["first_advance_ms"][0] = (now - stats["t_play"]) * 1000
        stats["frame_times"].append(now)
        stats["indices"].append(controller.state_manager.snapshot.current_frame_index)
        stats["cache_frames"].append(len(controller._frame_cache._frame_store))
        stats["cache_mb"].append(controller._frame_cache.memory_bytes() / 1e6)

    controller.frame_loaded.connect(on_frame)
    if viewer is not None:
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

    rss_start = rss()
    t_load = time.perf_counter()
    controller.load_instance(instance)
    # wait for first frame
    deadline = time.perf_counter() + 20.0
    while controller._pending_decode_id != 0 and time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.002)
    load_ms = (time.perf_counter() - t_load) * 1000
    first_frame_ms = load_ms

    controller.set_playing(True)
    t_play = time.perf_counter()
    stats["t_play"] = t_play
    stats["first_advance_ms"] = [None]

    def stop():
        app.quit()

    QTimer.singleShot(int(args.seconds * 1000), stop)
    rss_peak = rss_start
    while True:
        app.processEvents()
        rss_peak = max(rss_peak, rss())
        if not controller.state_manager.snapshot.is_playing and time.perf_counter() - t_play > 1.0:
            break
        if time.perf_counter() - t_play > args.seconds + 2.0:
            break
    elapsed = time.perf_counter() - t_play
    from echo_personal_tool.infrastructure.playback_diagnostics import diagnostics as _diag
    report = None
    if _diag.enabled:
        _diag.snapshot_memory()
        report = _diag.stop()
    controller.set_playing(False)
    app.processEvents()

    # ---- analysis ----
    ft = stats["frame_times"]
    n_shown = len(ft)
    fps = n_shown / elapsed if elapsed > 0 else 0
    target_fps = 1000.0 / args.frame_time
    gaps = [(ft[i] - ft[i - 1]) * 1000 for i in range(1, len(ft))]
    idx = stats["indices"]
    advances = sum(1 for i in range(1, len(idx)) if idx[i] != idx[i - 1])
    skips = sum(1 for i in range(1, len(idx)) if (idx[i] - idx[i - 1]) % args.frames not in (0, 1))
    wrap_jank = 0
    if gaps:
        target_ms = args.frame_time
        over = sum(1 for g in gaps if g > target_ms * 1.5)
        p95 = float(np.percentile(gaps, 95))
        mx = max(gaps)
    else:
        over = p95 = mx = 0.0

    cache = controller._frame_cache
    label = args.label or path.name
    print(f"\n=== {label} ===")
    print(f"  ram cap: {controller._cache_ram_cap_bytes / 1e6:.0f} MB, "
          f"cache budget after tuning: {controller._frame_cache.memory_budget / 1e6:.0f} MB, "
          f"window {controller._frame_cache.evict_window}")
    print(f"  config: profile={args.profile} radius={cfg.prefetch_radius} batch={cfg.batch_size} "
          f"min_buffer={cfg.min_buffer} evict_window={cfg.evict_window} cache_mb={args.cache_mb} "
          f"warm_session={args.warm_session} render={not args.no_render}")
    print(f"  cine  : {args.frames} frames @ {args.frame_time} ms ({target_fps:.1f} fps target), frame {cache.get(0).shape if cache.is_loaded(0) else '?'}")
    print(f"  first frame latency : {first_frame_ms:7.1f} ms   (open+decode frame 0)")
    fa = stats["first_advance_ms"][0]
    print(f"  play->first advance : {fa if fa is None else round(fa,1)} ms")
    print(f"  playback duration   : {elapsed:7.2f} s")
    print(f"  frames shown        : {n_shown} (advances={advances}, non-adjacent jumps={skips})")
    print(f"  achieved FPS        : {fps:7.2f}  (deficit {fps-target_fps:+.2f})")
    if gaps:
        print(f"  inter-frame gap ms  : avg {sum(gaps)/len(gaps):6.2f}  p95 {p95:6.2f}  max {mx:7.2f}  "
              f"overdue>1.5x: {over}/{len(gaps)} ({100*over/len(gaps):.1f}%)")
        worst = sorted(range(len(gaps)), key=lambda i: -gaps[i])[:3]
        print("  worst gaps        : " + ", ".join(
            f"{gaps[i]:.0f} ms after frame {idx[i]} (next {idx[i + 1]})" for i in worst))
    if stats["render_ms"] and not args.no_render:
        r = stats["render_ms"]; p = stats["paint_ms"]
        print(f"  render (show_frame_fast) ms: avg {sum(r)/len(r):6.2f}  p95 {np.percentile(r,95):6.2f}  max {max(r):7.2f}")
        print(f"  paint (viewport repaint) ms: avg {sum(p)/len(p):6.2f}  p95 {np.percentile(p,95):6.2f}  max {max(p):7.2f}")
        print(f"  main-thread total     ms: avg {(sum(r)+sum(p))/len(r):6.2f}  -> UI budget {100*(sum(r)+sum(p))/len(r)/args.frame_time:.0f}% of frame interval")
    if stats["cache_mb"]:
        print(f"  frame cache: frames avg {sum(stats['cache_frames'])/len(stats['cache_frames']):5.1f} / max {max(stats['cache_frames'])}, "
              f"MB avg {sum(stats['cache_mb'])/len(stats['cache_mb']):6.1f} / max {max(stats['cache_mb']):6.1f}")
    print(f"  RSS: start {rss_start:.0f} MB -> end {rss():.0f} MB, peak {rss_peak:.0f} MB")
    print(f"  final cache: {len(cache._frame_store)}/{cache.frame_count()} frames, {cache.memory_bytes()/1e6:.1f} MB")
    if report is not None:
        txt = report.summary()
        keep = [ln for ln in txt.splitlines() if any(k in ln for k in
                ("Tick phases","cache_hit","cache_miss","skip_next","lag_skip","batches:","total decoded",
                 "avg batch","avg per frame","throughput","jitter","Prefetch cancel","frames shown:",
                 "amplification","round trip","runs:","frames:","Playback buffer","avg:","p95:","max:",
                 "min:","empty at tick"))]
        print("  --- diagnostics ---")
        for ln in keep:
            print("   ", ln.strip())


if __name__ == "__main__":
    main()
