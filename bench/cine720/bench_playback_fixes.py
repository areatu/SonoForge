"""Verify the frame-period compensation bug and quantify candidate fixes.

Baseline:  _last_frame_shown_at is set AFTER the synchronous render, so the real
           frame period = interval + main-thread work (never compensates).
Fix A    : stamp the tick START -> period = max(interval, work).
Fix B    : + skip the per-frame ROI detection that DICOM throws away.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_REPO_SRC = str(Path(__file__).resolve().parents[2] / "src")
if _REPO_SRC not in sys.path:
    sys.path.insert(0, _REPO_SRC)

import numpy as np  # noqa: E402
import psutil  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("path")
ap.add_argument("--frames", type=int, default=60)
ap.add_argument("--seconds", type=float, default=8.0)
ap.add_argument("--cache-mb", type=int, default=64)
ap.add_argument("--fix-timing", action="store_true")
ap.add_argument("--fix-roi", action="store_true")
ap.add_argument("--warm-session", action="store_true")
ap.add_argument("--fix-session", action="store_true", help="process-wide path-keyed session (prototype fix)")
ap.add_argument("--fix-levels", action="store_true", help="restore the display-levels cache (grayscale W/L)")
ap.add_argument("--hot", action="store_true", help="pre-load whole cine (hot cache)")
ap.add_argument("--label", default="")
ap.add_argument("--format", default="dicom")
args = ap.parse_args()

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

if args.fix_session:
    import sessioncache_patch
    sessioncache_patch.apply(keep_warm=True)
if args.fix_levels:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import levelsfix_patch

    levelsfix_patch.apply()

from echo_personal_tool.application import app_controller as ac  # noqa: E402
from echo_personal_tool.application.frame_cache import FrameCache  # noqa: E402
from echo_personal_tool.domain.models.metadata import InstanceMetadata  # noqa: E402

if args.warm_session:
    from echo_personal_tool.infrastructure import dicom_session as ds_mod
    ds_mod.DicomSession.release_heavy = lambda self: None
if args.fix_roi:
    ac.AppController._maybe_cache_cine_roi_from_frame = lambda self, frame, idx: None

_orig = ac.AppController._advance_playback


def advance(self):
    t0 = time.perf_counter()
    _orig(self)
    if args.fix_timing:
        # emulate "stamp at tick start" so the next tick is scheduled at t0+interval
        if self._last_frame_shown_at > t0:
            self._last_frame_shown_at = t0
        self._reschedule_playback_timer()


ac.AppController._advance_playback = advance

controller = ac.AppController()
controller._frame_cache = FrameCache(
    evict_window=controller.playback_config.evict_window,
    max_cache_bytes=args.cache_mb * 1024 * 1024,
)

from echo_personal_tool.presentation.viewer_widget import ViewerWidget  # noqa: E402

viewer = ViewerWidget()
viewer.resize(1400, 820)
viewer.show()

stats = {"render": [], "paint": [], "ft": [], "idx": []}


def on_frame(pixels):
    img = np.asarray(pixels)
    t0 = time.perf_counter()
    viewer.show_frame_fast(img)
    t1 = time.perf_counter()
    viewer._graphics.viewport().repaint()
    t2 = time.perf_counter()
    stats["render"].append((t1 - t0) * 1000)
    stats["paint"].append((t2 - t1) * 1000)
    stats["ft"].append(t2)
    stats["idx"].append(controller.state_manager.snapshot.current_frame_index)


controller.frame_loaded.connect(on_frame)
controller.state_manager.state_changed.connect(viewer.set_state)

inst = InstanceMetadata(
    sop_instance_uid="1.2.3.4.5", series_uid="1.2.3.4", modality="US",
    number_of_frames=args.frames, pixel_spacing=(0.2, 0.2), frame_time_ms=33.3,
    series_description="bench", path=Path(args.path), media_format=args.format,
)
controller.load_instance(inst)
deadline = time.perf_counter() + 40
while controller._pending_decode_id != 0 and time.perf_counter() < deadline:
    app.processEvents(); time.sleep(0.002)
if args.hot:
    controller._frame_cache.load_all_frames()
rss0 = psutil.Process().memory_info().rss / 1e6
controller.set_playing(True)
t_play = time.perf_counter()
QTimer.singleShot(int(args.seconds * 1000), app.quit)
peak = rss0
while time.perf_counter() - t_play < args.seconds + 1:
    app.processEvents()
    peak = max(peak, psutil.Process().memory_info().rss / 1e6)
controller.set_playing(False)
app.processEvents()
el = time.perf_counter() - t_play

ft = stats["ft"]
gaps = np.diff(ft) * 1000 if len(ft) > 1 else np.array([0.0])
idx = stats["idx"]
jumps = sum(1 for i in range(1, len(idx)) if (idx[i] - idx[i - 1]) % args.frames not in (0, 1))
r = np.array(stats["render"] or [0.0]); p = np.array(stats["paint"] or [0.0])
print(f"\n=== {args.label or Path(args.path).name} ===")
print(f"  fixes: timing={args.fix_timing} roi={args.fix_roi} warm={args.warm_session} session={args.fix_session} hot={args.hot} cache={args.cache_mb}MB")
print(f"  FPS {len(ft)/el:6.2f} (target 30)   frames={len(ft)} in {el:.1f}s   non-adjacent jumps={jumps}")
print(f"  gap ms: avg {gaps.mean():6.2f} p95 {np.percentile(gaps,95):6.2f} max {gaps.max():7.2f}")
print(f"  render avg {r.mean():5.2f} ms | paint avg {p.mean():5.2f} ms | main-thread {(r.mean()+p.mean()):5.2f} ms")
print(f"  cache {len(controller._frame_cache._frame_store)}/{controller._frame_cache.frame_count()} frames "
      f"({controller._frame_cache.memory_bytes()/1e6:.0f} MB) | RSS {rss0:.0f}->{psutil.Process().memory_info().rss/1e6:.0f} MB peak {peak:.0f} MB")
