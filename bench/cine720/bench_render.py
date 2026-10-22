"""Per-frame CPU cost breakdown at 1280x720 (render + hidden work in the tick path)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_REPO_SRC = str(Path(__file__).resolve().parents[2] / "src")
if _REPO_SRC not in sys.path:
    sys.path.insert(0, _REPO_SRC)

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from echo_personal_tool.domain.services.segment_roi import resolve_cine_segment_roi_xyxy  # noqa: E402
from echo_personal_tool.infrastructure.pixel_utils import (  # noqa: E402
    apply_window_level_rgb,
    compute_display_levels,
    to_display_rgb,
    to_grayscale_array,
    to_grayscale_uint8,
)

H, W = 720, 1280
rgb = np.random.randint(0, 255, (H, W, 3), dtype=np.uint8)
gray16 = np.random.randint(0, 4095, (H, W), dtype=np.uint16)
gray8 = np.random.randint(0, 255, (H, W), dtype=np.uint8)


def timeit(fn, n=20, warmup=3):
    for _ in range(warmup):
        fn()
    ts = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        ts.append((time.perf_counter() - t0) * 1000)
    ts = np.array(ts)
    return ts.mean(), np.percentile(ts, 95), ts.max()


def row(name, res, budget_ms=33.3):
    m, p, x = res
    print(f"  {name:44s} avg {m:7.2f} ms   p95 {p:7.2f}   max {x:7.2f}   ({100*m/budget_ms:5.1f}% of 33.3 ms budget)")


print("== CPU cost per frame @1280x720 (2-core Xeon 2.6GHz, Debian 12) ==")
row("resolve_cine_segment_roi_xyxy (RGB)  [discarded for DICOM!]", timeit(lambda: resolve_cine_segment_roi_xyxy(rgb)))
row("resolve_cine_segment_roi_xyxy (gray16)", timeit(lambda: resolve_cine_segment_roi_xyxy(gray16)))
row("to_grayscale_uint8 (RGB->gray)", timeit(lambda: to_grayscale_uint8(rgb)))
row("to_grayscale_array (RGB->float32)", timeit(lambda: to_grayscale_array(rgb)))
row("to_display_rgb (RGB, ascontiguous copy)", timeit(lambda: to_display_rgb(rgb, channel_order="rgb")))
row("apply_window_level_rgb (colour W/L)", timeit(lambda: apply_window_level_rgb(rgb, 20.0, 200.0)))
row("compute_display_levels (float32 percentiles)", timeit(lambda: compute_display_levels(gray8, dr_low_pct=5.0, dr_high_pct=100.0, window_scale=1.0, level_offset=0.0)))
lut = np.arange(256, dtype=np.uint8)
dst = np.empty((H, W), np.uint8)
row("cv2.LUT gray8 (W/L, into prealloc buf)", timeit(lambda: cv2.LUT(gray8, lut, dst=dst)))
lut16 = np.arange(65536, dtype=np.uint8)
dst16 = np.empty((H, W), np.uint8)
row("np.take lut16 (16-bit W/L)", timeit(lambda: np.take(lut16, gray16, out=dst16)))
row("cv2.resize 720p->viewport (smooth scale)", timeit(lambda: cv2.resize(rgb, (1400, 790), interpolation=cv2.INTER_LINEAR)))

# ---- Qt / pyqtgraph side ----
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
import pyqtgraph as pg  # noqa: E402

gv = pg.GraphicsLayoutWidget()
gv.resize(1400, 820)
vb = gv.addPlot()
vb.setAspectLocked(True)
vb.invertY()
item = pg.ImageItem(axisOrder="row-major")
item.setAutoDownsample(False)
vb.addItem(item)
gv.show()
app.processEvents()


def setimage_rgb():
    item.setImage(rgb, autoLevels=False)
    item.setLevels((0, 255))


def setimage_gray():
    item.setImage(gray8, autoLevels=False)
    item.setLevels((0, 255))


def setimage_rgb_paint():
    item.setImage(rgb, autoLevels=False)
    item.setLevels((0, 255))
    gv.viewport().repaint()


def setimage_gray_paint():
    item.setImage(gray8, autoLevels=False)
    item.setLevels((0, 255))
    gv.viewport().repaint()


def setimage_gray_paint_nosmooth():
    item.setOpts(smooth=False)
    item.setImage(gray8, autoLevels=False)
    item.setLevels((0, 255))
    gv.viewport().repaint()


print("== pyqtgraph setImage (+ synchronous viewport repaint, 1400x820 offscreen raster) ==")
row("setImage RGB only (no paint)", timeit(setimage_rgb))
row("setImage gray only (no paint)", timeit(setimage_gray))
row("setImage RGB + repaint (smooth=True)", timeit(setimage_rgb_paint))
row("setImage gray + repaint (smooth=True)", timeit(setimage_gray_paint))
row("setImage gray + repaint (smooth=False)", timeit(setimage_gray_paint_nosmooth))

# QImage conversion cost, as pyqtgraph does internally
from PySide6.QtGui import QImage  # noqa: E402


def qimage_copy():
    img = QImage(rgb.data, W, H, 3 * W, QImage.Format.Format_RGB888)
    return img.copy()


row("QImage(Format_RGB888).copy() (720p RGB)", timeit(qimage_copy))
