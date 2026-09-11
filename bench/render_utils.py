"""Shared rendering helpers for the STE documentation figures.

Every figure draws a B-mode frame plus an overlay that lives in *image
coordinates*: ``x`` is the column, ``y`` is the row. pyqtgraph's ``ImageItem``
defaults to ``axisOrder="col-major"``, which reads the array as ``(x, y)`` — and
therefore draws the picture **transposed** relative to the overlay. The result is
a figure where the contours sit correctly ("apex up, mitral line down") while the
myocardium underneath is rotated by 90°, which is exactly how the first version
of the STE verification screenshots was generated: the numbers were right, the
picture lied about them.

The application never has this problem because every product path asks for
``axisOrder="row-major"`` (``presentation/viewer_widget.py``,
``ui/strain_window.py``, ``presentation/doppler_widget.py``,
``presentation/mmode_widget.py``). These helpers do the same and can *prove* it:
:func:`verify_render_orientation` renders a single off-centre mark through the
same code path and checks where it lands, so a figure cannot be published with
the image and the measurements disagreeing.
"""

from __future__ import annotations

import numpy as np

#: The orientation mark: one bright square, deliberately off the diagonal —
#: rows 20..30, columns 70..80, i.e. the **upper right** of the frame. Under a
#: transposed render it lands in the lower left, which cannot be mistaken for
#: the expected result (a symmetric probe would survive the transposition).
PROBE_ROWS = (20, 30)
PROBE_COLS = (70, 80)
PROBE_SIZE = 100

#: Where the mark must appear, in relative figure coordinates (fx, fy).
PROBE_EXPECTED = (0.75, 0.25)
PROBE_TOLERANCE = 0.12


def make_image_item(frame: np.ndarray, rect: tuple[float, float, float, float] | None = None):
    """``ImageItem`` for a ``(rows, cols)`` frame in the application convention.

    ``axisOrder="row-major"`` makes the first array axis the *y* (row) axis, so
    overlay geometry computed in image coordinates lands on the right pixels.
    """
    import pyqtgraph as pg
    from PySide6.QtCore import QRectF

    item = pg.ImageItem(axisOrder="row-major")
    item.setImage(np.ascontiguousarray(frame), autoLevels=True)
    if rect is None:
        height, width = frame.shape[:2]
        rect = (0.0, 0.0, float(width), float(height))
    item.setRect(QRectF(*rect))
    return item


def probe_frame() -> np.ndarray:
    """Frame carrying exactly one bright mark, in the upper right quadrant."""
    frame = np.zeros((PROBE_SIZE, PROBE_SIZE), dtype=np.uint8)
    frame[PROBE_ROWS[0] : PROBE_ROWS[1], PROBE_COLS[0] : PROBE_COLS[1]] = 255
    return frame


def bright_mark_position(path: str, threshold: int = 200) -> tuple[float, float]:
    """Relative position (``fx``, ``fy``) of the bright mark in a rendered figure.

    The threshold sits above the anti-aliased axis tick labels, which are light
    enough to pass a naive "bright pixel" test and would drag the centroid.
    """
    from PySide6.QtGui import QImage

    image = QImage(path)
    if image.isNull():
        raise RuntimeError(f"cannot read the rendered figure: {path}")
    width, height = image.width(), image.height()
    xs: list[float] = []
    ys: list[float] = []
    for py in range(height):
        for px in range(width):
            if image.pixelColor(px, py).red() >= threshold:
                xs.append(px / width)
                ys.append(py / height)
    if not xs:
        raise RuntimeError(f"no bright mark found in {path}")
    return float(np.mean(xs)), float(np.mean(ys))


def check_orientation(path: str) -> tuple[float, float]:
    """Raise when the figure shows the frame transposed or y-flipped.

    Returns the measured mark position for logging. The probe mark belongs in
    the upper right; a transposed render puts it in the lower left and a flipped
    y axis in the lower right.
    """
    fx, fy = bright_mark_position(path)
    expected_x, expected_y = PROBE_EXPECTED
    if abs(fx - expected_x) > PROBE_TOLERANCE or abs(fy - expected_y) > PROBE_TOLERANCE:
        seen = []
        if fx < 0.5 - PROBE_TOLERANCE:
            seen.append("mirror/transpose in x (mark on the wrong side)")
        if fy > 0.5 + PROBE_TOLERANCE:
            seen.append("flip/transpose in y (mark should be in the upper part)")
        reason = "; ".join(seen) or "mark is not where the overlay coordinates put it"
        raise RuntimeError(
            f"figure {path} disagrees with the overlay convention: mark at (fx={fx:.2f}, fy={fy:.2f}), "
            f"expected (fx={expected_x:.2f}, fy={expected_y:.2f}) — {reason}. "
            "Use render_utils.make_image_item (axisOrder='row-major'), as the application does."
        )
    return fx, fy


def render_probe(path: str, *, row_major: bool = True) -> str:
    """Render the orientation probe to ``path`` and return the path.

    ``row_major=False`` forces the wrong convention on purpose — the negative
    control used by the unit test to prove that :func:`check_orientation` really
    catches a transposed figure.
    """
    import pyqtgraph as pg
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    plot = pg.PlotWidget()
    plot.setBackground("k")
    plot.invertY(True)
    plot.setAspectLocked(True)
    # orientation-ok: the negative control has to break the convention on purpose
    item = make_image_item(probe_frame()) if row_major else pg.ImageItem(probe_frame())
    plot.addItem(item)
    plot.setXRange(0, PROBE_SIZE, padding=0)
    plot.setYRange(0, PROBE_SIZE, padding=0)
    plot.resize(400, 400)
    plot.show()
    app.processEvents()
    plot.grab().save(path)
    plot.close()
    return path


def verify_render_orientation(tmp_path: str = "/tmp/ste_render_orientation.png") -> None:
    """Cheap self-check to run before publishing a figure (one 100×100 grab)."""
    check_orientation(render_probe(tmp_path))
