"""Scroll/scrub latency at 720p: time from set_frame(idx) to frame_loaded(idx)."""

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

ap = argparse.ArgumentParser()
ap.add_argument("path")
ap.add_argument("--frames", type=int, default=60)
ap.add_argument("--steps", type=int, default=12)
ap.add_argument("--warm-session", action="store_true")
ap.add_argument("--fix-session", action="store_true")
ap.add_argument("--label", default="")
ap.add_argument("--format", default="dicom")
args = ap.parse_args()

if args.fix_session:
    import sessioncache_patch
    sessioncache_patch.apply(keep_warm=True)
if args.warm_session:
    from echo_personal_tool.infrastructure import dicom_session as ds_mod
    ds_mod.DicomSession.release_heavy = lambda self: None

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

from echo_personal_tool.application.app_controller import AppController  # noqa: E402
from echo_personal_tool.domain.models.metadata import InstanceMetadata  # noqa: E402

controller = AppController()
got = {}


def on_frame(pixels):
    got["t"] = time.perf_counter()
    got["idx"] = controller.state_manager.snapshot.current_frame_index


controller.frame_loaded.connect(on_frame)

inst = InstanceMetadata(
    sop_instance_uid="1.2.3.4.5", series_uid="1.2.3.4", modality="US",
    number_of_frames=args.frames, pixel_spacing=(0.2, 0.2), frame_time_ms=33.3,
    series_description="bench", path=Path(args.path), media_format=args.format,
)
t0 = time.perf_counter()
controller.load_instance(inst)
while controller._pending_decode_id != 0 and time.perf_counter() - t0 < 30:
    app.processEvents(); time.sleep(0.002)
open_ms = (time.perf_counter() - t0) * 1000

lat = []
targets = np.linspace(1, args.frames - 1, args.steps).astype(int)
for tgt in targets:
    got.clear()
    t0 = time.perf_counter()
    controller.state_manager.set_frame(int(tgt), scroll=True)
    while "t" not in got and time.perf_counter() - t0 < 5:
        app.processEvents()
        time.sleep(0.001)
    lat.append((got.get("t", time.perf_counter()) - t0) * 1000)

lat = np.array(lat)
print(f"\n=== SCROLL {args.label or Path(args.path).name} (warm={args.warm_session} sessionfix={args.fix_session}) ===")
print(f"  load_instance->first frame: {open_ms:7.1f} ms")
print(f"  scroll step latency ({args.steps} random seeks): avg {lat.mean():7.1f} ms  min {lat.min():7.1f}  max {lat.max():7.1f}")
print(f"  -> max scrub rate: {1000/lat.mean():5.1f} frames/s")
print(f"  per-step latencies: {[round(x) for x in lat]}")
