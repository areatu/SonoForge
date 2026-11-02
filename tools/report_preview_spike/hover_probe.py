"""Pixel verification of the QPdfView geometry model (UI-4.0 spike).

The report preview hit-tests value-cell anchors on ``QPdfView``, which exposes
no geometry API. ``view_map.py`` reproduces the private Qt layout; this probe
checks it against what the widget actually paints:

1. a probe PDF is built with solid black markers at known page coordinates
   (the marker flowable records its own painted rectangle — ground truth);
2. for each viewport size × zoom mode × page mode the view is grabbed and every
   marker's pixel bounding box is compared with the model prediction;
3. hit-test round trip: the predicted marker centre must hit-test back to the
   same marker through ``view_map.hit_test_anchors``.

Also records how long the first paint takes after a document swap
(``QPdfView`` renders on a worker thread — relevant for the 500 ms budget).

Run (headless container: see README for Qt system stubs)::

    python tools/report_preview_spike/hover_probe.py [--save-shots DIR]
"""

from __future__ import annotations

import argparse
import sys
import time
from io import BytesIO
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import view_map  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.platypus import Flowable, PageBreak, SimpleDocTemplate, Spacer  # noqa: E402

from echo_personal_tool.infrastructure.measurement_report_pdf import PageRect  # noqa: E402

#: ``(id, x, y_top, w, h)`` in page points; ids are ValueId stand-ins.
MARKERS: tuple[tuple[tuple[int, int], float, float, float, float], ...] = (
    ((0, 0), 60, 60, 40, 20),
    ((0, 1), 500, 60, 30, 20),
    ((0, 2), 60, 700, 40, 20),
    ((0, 3), 300, 400, 50, 25),
    ((1, 0), 250, 100, 50, 25),
    ((1, 1), 60, 60, 30, 15),
)

#: tolerance in pixels: blob edges are antialias-quantised (a half-covered edge
#: pixel falls below the darkness threshold, so a blob bbox is up to ~1 px
#: smaller than the geometric rect on each side)
PIXEL_TOLERANCE = 2.0

#: a blob further than this from the prediction is a missing/late render, not noise
MATCH_RADIUS_PX = 20.0


class Marker(Flowable):
    """Solid rect at an absolute page position; records where it painted."""

    def __init__(self, value_id, x_pt: float, y_top: float, w: float, h: float) -> None:
        super().__init__()
        self.value_id = value_id
        self.x, self.y, self.w, self.h = x_pt, y_top, w, h
        self.recorded: PageRect | None = None

    def wrap(self, availWidth, availHeight):
        return (0, 0)

    def draw(self) -> None:
        canv = self.canv
        page_h = canv._pagesize[1]
        origin_x, origin_y = canv.absolutePosition(0, 0)
        canv.saveState()
        canv.translate(self.x - origin_x, (page_h - self.y - self.h) - origin_y)
        canv.setFillColorRGB(0, 0, 0)
        canv.rect(0, 0, self.w, self.h, stroke=0, fill=1)
        canv.restoreState()
        self.recorded = PageRect(page=canv.getPageNumber() - 1, x=self.x, y=self.y, w=self.w, h=self.h)


def build_probe_pdf() -> tuple[bytes, dict, list[tuple[float, float]]]:
    """PDF bytes, ``{ValueId: [PageRect]}`` anchors and per-page sizes."""
    markers = [Marker(*spec) for spec in MARKERS]
    story: list = []
    for index, marker in enumerate(markers):
        if index == 4:
            story.append(PageBreak())
        story.append(marker)
        story.append(Spacer(1, 1))
    buffer = BytesIO()
    SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    ).build(story)
    anchors = {marker.value_id: [marker.recorded] for marker in markers}
    return buffer.getvalue(), anchors, [(A4[0], A4[1])] * 2


def blob_boxes(image) -> list[tuple[float, float, float, float]]:
    """Bounding boxes of solid dark blobs (x0, y0, x1, y1) in pixels."""
    runs: list[tuple[int, int, int]] = []
    for y in range(image.height()):
        run = None
        for x in range(image.width()):
            color = image.pixelColor(x, y)
            dark = color.red() < 100 and color.green() < 100 and color.blue() < 100
            if dark:
                run = [x, x] if run is None else [run[0], x]
            elif run:
                runs.append((y, run[0], run[1]))
                run = None
        if run:
            runs.append((y, run[0], run[1]))
    boxes: list[list[int]] = []
    for y, x0, x1 in runs:
        hit = None
        for box in boxes:
            if x0 <= box[1] + 3 and box[0] <= x1 + 3 and y <= box[3] + 3:
                hit = box
                break
        if hit is None:
            boxes.append([x0, x1, y, y])
        else:
            hit[0] = min(hit[0], x0)
            hit[1] = max(hit[1], x1)
            hit[2] = min(hit[2], y)
            hit[3] = max(hit[3], y)
    return [(b[0], b[2], b[1], b[3]) for b in boxes if b[1] - b[0] >= 5 and b[3] - b[2] >= 5]


def wait_painted(view, app, max_ms: float = 3000.0):
    """Grab until dark content appears; returns (wait_ms, pixmap)."""
    start = time.perf_counter()
    while True:
        app.processEvents()
        pix = view.grab()
        boxes = blob_boxes(pix.toImage())
        if boxes:
            return (time.perf_counter() - start) * 1000, pix, boxes
        if (time.perf_counter() - start) * 1000 > max_ms:
            return (time.perf_counter() - start) * 1000, pix, []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save-shots", type=Path, default=None)
    args = parser.parse_args()

    from PySide6.QtCore import QBuffer, QIODevice, QPointF
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtPdfWidgets import QPdfView
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])

    pdf_bytes, anchors, page_sizes = build_probe_pdf()
    device = QBuffer()
    device.setData(pdf_bytes)
    device.open(QIODevice.OpenModeFlag.ReadOnly)
    document = QPdfDocument()
    document.load(device)
    assert document.status() == QPdfDocument.Status.Ready

    view = QPdfView()
    view.setDocument(document)
    screen_res = view_map.screen_resolution(view)

    configs = []
    for size in ((600, 800), (1000, 1200)):
        for mode, name in (
            (QPdfView.ZoomMode.FitToWidth, "FitToWidth"),
            (QPdfView.ZoomMode.FitInView, "FitInView"),
        ):
            configs.append((size, mode, name, QPdfView.PageMode.SinglePage, None))
        configs.append((size, QPdfView.ZoomMode.Custom, "Custom 1.0", QPdfView.PageMode.SinglePage, 1.0))
        configs.append((size, QPdfView.ZoomMode.Custom, "Custom 0.5", QPdfView.PageMode.SinglePage, 0.5))
        configs.append((size, QPdfView.ZoomMode.Custom, "Custom 0.5", QPdfView.PageMode.MultiPage, 0.5))
        configs.append((size, QPdfView.ZoomMode.FitToWidth, "FitToWidth", QPdfView.PageMode.MultiPage, None))
    configs.append(((600, 800), QPdfView.ZoomMode.Custom, "Custom 1.0 scroll=120", QPdfView.PageMode.SinglePage, 1.0))

    worst = 0.0
    total_markers = 0
    hit_ok = 0
    print(f"screen_resolution = {screen_res:.4f} px/pt  (logicalDPI/72, captured like QPdfView does)")
    print()
    header = f"{'config':44} {'wait ms':>8} {'checked':>8} {'max err px':>11} {'hit-test':>9}"
    print(header)
    print("-" * len(header))

    for size, mode, zoom_name, page_mode, zoom in configs:
        view.setPageMode(page_mode)
        view.setZoomMode(mode)
        if zoom is not None:
            view.setZoomFactor(zoom)
        view.resize(*size)
        view.show()
        # SinglePage geometry follows pageNavigator().currentPage(): reset it,
        # otherwise a MultiPage config earlier in the loop leaves page 1 current
        # and the next SinglePage config lays out the wrong page.
        view.pageNavigator().jump(0, QPointF())
        app.processEvents()
        if "scroll=" in zoom_name:
            view.verticalScrollBar().setValue(120)
        wait_ms, pix, boxes = wait_painted(view, app)
        for _ in range(5):
            app.processEvents()  # let straggling renders land
        pix = view.grab()
        boxes = blob_boxes(pix.toImage()) or boxes

        geoms = view_map.document_geometry(
            view,
            screen_res=screen_res,
            page_sizes_pt=page_sizes,
            current_page=view.pageNavigator().currentPage(),
        )
        label = f"{size[0]}x{size[1]} {zoom_name} {'multi' if page_mode == QPdfView.PageMode.MultiPage else 'single'}"

        checked = 0
        matched = 0
        config_worst = 0.0
        for value_id, rects in anchors.items():
            rect = rects[0]
            geom = next((g for g in geoms if g.page == rect.page), None)
            if geom is None:
                continue
            predicted = view_map.page_rect_to_viewport(geom, rect)
            center = (predicted.center().x(), predicted.center().y())
            if not (0 <= center[0] < view.viewport().width() and 0 <= center[1] < view.viewport().height()):
                continue  # off-screen in this config
            checked += 1
            total_markers += 1
            box = min(
                boxes,
                key=lambda b: abs((b[0] + b[2]) / 2 - center[0]) + abs((b[1] + b[3]) / 2 - center[1]),
            )
            center_gap = abs((box[0] + box[2]) / 2 - center[0]) + abs((box[1] + box[3]) / 2 - center[1])
            error = max(
                abs(box[0] - predicted.left()),
                abs(box[1] - predicted.top()),
                abs(box[2] - predicted.right()),
                abs(box[3] - predicted.bottom()),
            )
            if center_gap <= MATCH_RADIUS_PX:
                config_worst = max(config_worst, error)
                if error <= PIXEL_TOLERANCE:
                    matched += 1
            else:
                config_worst = max(config_worst, error)
            # hit-test round trip at the predicted centre
            hit = view_map.hit_test_anchors(geoms, center[0], center[1], anchors, tolerance_pt=4.0)
            if hit == value_id:
                hit_ok += 1

        worst = max(worst, config_worst)
        if args.save_shots:
            args.save_shots.mkdir(parents=True, exist_ok=True)
            pix.save(str(args.save_shots / f"hover_{label.replace(' ', '_').replace('/', '-')}.png"))
        print(f"{label:44} {wait_ms:>8.0f} {matched:>4}/{checked:<3} {config_worst:>10.2f} {matched:>6}/{checked}")

    print()
    print(f"markers checked: {total_markers}, hit-test correct: {hit_ok}")
    print(f"worst prediction error: {worst:.2f} px (tolerance {PIXEL_TOLERANCE})")
    verdict = worst <= PIXEL_TOLERANCE and hit_ok == total_markers and total_markers > 0
    print(f"verdict: {'PASS — view_map model matches QPdfView painting' if verdict else 'FAIL'}")
    return 0 if verdict else 1


if __name__ == "__main__":
    raise SystemExit(main())
