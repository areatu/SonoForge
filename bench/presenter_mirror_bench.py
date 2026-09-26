"""Micro-benchmark for the Presenter mode content-forwarding path.

Run:  QT_QPA_PLATFORM=offscreen python bench/presenter_mirror_bench.py

The presenter architecture forwards decoded frames to an independently
rendered ViewerWidget on the audience display (no pixel grabs — grabs
cannot composite GL viewports).  The relevant cost is therefore the
marginal main-thread load of the second render, relative to the frame
budget of the speaker's own playback.

Measured here:

1. ``show_frame`` (static step) and ``show_frame_fast`` (playback step)
   cost on the presentation viewer across typical frame sizes;
2. a worst-case mixed loop approximating 30 fps playback with a second
   live viewer, compared against the 33.3 ms frame budget.

Historical note: the previous grab-based mirror burned 2+ full-widget
grabs per second on a static scene and up to 30/s during playback, and
with a GL viewport every grab was a framebuffer readback that blanked
the speaker's picture.  That design is gone; this bench pins the numbers
of its replacement.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
from PySide6.QtWidgets import QApplication


def echo_frame(w: int, h: int) -> np.ndarray:
    yy, xx = np.mgrid[0:h, 0:w]
    r = np.hypot(xx - w / 2, yy + 40)
    ang = np.arctan2(xx - w / 2, yy + 40)
    sector = (r < h * 0.98) & (np.abs(ang - np.pi / 2) < 0.55)
    img = 40 + 120 * sector * (0.4 + 0.6 * np.abs(np.sin(r / 14) * np.cos(ang * 9)))
    return np.clip(img + np.random.default_rng(7).normal(0, 9, (h, w)), 0, 255).astype(np.uint8)


def bench(fn, frames, repeats=30) -> tuple[float, float]:
    times = []
    for i in range(repeats):
        frame = frames[i % len(frames)]
        t0 = time.perf_counter()
        fn(frame)
        times.append((time.perf_counter() - t0) * 1000.0)
    return sum(times) / len(times), max(times)


def main() -> int:
    from echo_personal_tool.presentation.presenter_view import PresenterWindow

    app = QApplication.instance() or QApplication([])
    print(f"platform: {app.platformName()}")

    window = PresenterWindow(app.primaryScreen(), speaker_viewer_provider=lambda: None)
    viewer = window.viewer()
    window.start()
    app.processEvents()

    print()
    print("== Presentation-viewer render cost (marginal main-thread load) ==")
    print(f"{'frame':>12} {'show_frame avg/max ms':>22} {'show_frame_fast avg/max ms':>27}")
    for w, h in ((960, 540), (1400, 900), (1920, 1080)):
        frames = [echo_frame(w, h), echo_frame(w, h)]  # 2 alternating frames
        avg_s, max_s = bench(viewer.show_frame, frames)
        avg_f, max_f = bench(viewer.show_frame_fast, frames)
        print(
            f"{w}x{h:>6} {avg_s:10.2f} / {max_s:6.2f} {avg_f:14.2f} / {max_f:6.2f}"
        )

    print()
    print("== Worst case: 1s of continuous playback forwarding (both viewers live) ==")
    frames = [echo_frame(960, 540, ), echo_frame(960, 540)]
    n = 0
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 1.0:
        viewer.show_frame_fast(frames[n % 2])
        n += 1
    elapsed = time.perf_counter() - t0
    per_frame = elapsed / n * 1000.0
    print(f"{n} forward_frames in {elapsed:.2f}s -> {per_frame:.2f} ms/frame "
          f"(33.3 ms budget at 30 fps; headroom {'OK' if per_frame < 33 else 'OVER'})")

    window.stop()
    print()
    print("Note: on the real machine the presentation viewer renders on the")
    print("second display through its own GL context (shared via", end="")
    print(" AA_ShareOpenGLContexts), so this cost overlaps GPU copy, not the")
    print("speaker's render path.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
