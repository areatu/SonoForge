"""Viewport ⇄ page mapping for :class:`PySide6.QtPdfWidgets.QPdfView` (UI-4.0 spike).

``QPdfView`` exposes no public geometry API: the page rectangle and the
points→pixels transform live in ``QPdfViewPrivate`` (qtwebengine
``src/pdfwidgets/qpdfview.cpp``, Qt 6.11). This module reproduces that layout
from public state (document margins, page spacing, zoom mode/factor, scroll
bars, ``QPdfDocument.pagePointSize``) so the report preview can hit-test the
value-cell anchors returned by
:func:`echo_personal_tool.infrastructure.measurement_report_pdf.render_report`.

The model mirrors Qt's code path exactly:

* ``page100_px = round(pt * screen_resolution)`` — the "100 %" pixel size;
* ``Custom``: ``page_px = round(pt * screen_resolution * zoomFactor)``,
  transform scale ``screen_resolution * zoomFactor``;
* ``FitToWidth``: ``pageScale = (viewport_w - ml - mr) / page100_px.w``,
  ``page_px = round(page100_px * pageScale)``;
* ``FitInView``: fit ``page100_px`` into
  ``viewport_w - ml - mr`` × ``viewport_h - pageSpacing`` keeping aspect ratio
  (note: the height budget subtracts the page spacing, **not** the top/bottom
  margins — that asymmetry is why a naive min-fit model is ~1 % off);
* page X is centred as ``(max(totalWidth, viewport_w) - page_px.w) // 2``
  (integer division, margins included only in ``totalWidth``);
* page Y starts at the top margin and stacks with ``pageSpacing``;
* mouse → points is ``transform⁻¹(pos + scroll − page_origin)``, the same
  expression ``QPdfView::mouseMoveEvent`` uses for its link hit-tests.

Everything here is pure Python over measured view state — verified
pixel-by-pixel by ``hover_probe.py`` (error ≤ 1 px in every tested mode).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from PySide6.QtPdfWidgets import QPdfView

    from echo_personal_tool.infrastructure.measurement_report_pdf import PageRect, ValueId


@dataclass(frozen=True)
class PageGeometry:
    """One page rectangle in viewport widget coordinates."""

    page: int
    x: float
    y: float
    w: float
    h: float
    #: Points → pixels scale of this page (Qt ``screenScaleTransform``).
    scale: float

    def contains_pt(self, x_pt: float, y_pt: float, *, tolerance_pt: float = 2.0) -> bool:
        return -tolerance_pt <= x_pt <= self.pt_w + tolerance_pt and -tolerance_pt <= y_pt <= self.pt_h + tolerance_pt

    @property
    def pt_w(self) -> float:
        return self.w / self.scale

    @property
    def pt_h(self) -> float:
        return self.h / self.scale


def _qround(value: float) -> int:
    """C++ qRound: round half away from zero."""
    return int(math.floor(value + 0.5)) if value >= 0 else -int(math.floor(-value + 0.5))


def screen_resolution(view: QPdfView) -> float:
    """``QPdfViewPrivate`` captures ``logicalDotsPerInch() / 72`` at construction.

    Qt keeps that value for the lifetime of the view (even across screens with
    different DPI), so the mapping must use the same source: read the primary
    screen once when the view is created and pass it to every call here.
    """
    from PySide6.QtGui import QGuiApplication

    return QGuiApplication.primaryScreen().logicalDotsPerInch() / 72.0


def document_geometry(
    view: QPdfView,
    *,
    screen_res: float,
    page_sizes_pt: Sequence[tuple[float, float]],
    current_page: int = 0,
) -> list[PageGeometry]:
    """Page rectangles in widget coordinates, one per laid-out page.

    ``page_sizes_pt`` — ``(width, height)`` in points per page
    (``QPdfDocument.pagePointSize``). ``current_page`` matters in
    ``SinglePage`` mode: Qt lays out only the current page.
    """
    from PySide6.QtPdfWidgets import QPdfView

    margins = view.documentMargins()
    ml, mt = margins.left(), margins.top()
    spacing = view.pageSpacing()
    vp = view.viewport()
    vp_w, vp_h = vp.width(), vp.height()
    scroll_x = view.horizontalScrollBar().value()
    scroll_y = view.verticalScrollBar().value()

    mode = view.zoomMode()
    zoom = view.zoomFactor()

    if view.pageMode() == QPdfView.PageMode.SinglePage:
        pages = [current_page]
    else:
        pages = list(range(len(page_sizes_pt)))

    sizes: dict[int, tuple[int, int, float]] = {}
    for page in pages:
        pt_w, pt_h = page_sizes_pt[page]
        page100_w = _qround(pt_w * screen_res)
        page100_h = _qround(pt_h * screen_res)
        if mode == QPdfView.ZoomMode.Custom:
            px_w = _qround(pt_w * screen_res * zoom)
            px_h = _qround(pt_h * screen_res * zoom)
            scale = screen_res * zoom
        elif mode == QPdfView.ZoomMode.FitToWidth:
            page_scale = (vp_w - ml - margins.right()) / page100_w
            px_w = _qround(page100_w * page_scale)
            px_h = _qround(page100_h * page_scale)
            scale = screen_res * page_scale
        else:  # FitInView
            avail_w = vp_w - ml - margins.right()
            avail_h = vp_h - spacing
            factor = min(avail_w / page100_w, avail_h / page100_h)
            px_w = _qround(page100_w * factor)
            px_h = _qround(page100_h * factor)
            scale = screen_res * (px_w / page100_w)
        sizes[page] = (px_w, px_h, scale)

    total_width = max(px[0] for px in sizes.values()) + ml + margins.right()
    page_y = mt
    out: list[PageGeometry] = []
    for page in pages:
        px_w, px_h, scale = sizes[page]
        page_x = (max(total_width, vp_w) - px_w) // 2
        out.append(
            PageGeometry(
                page=page,
                x=page_x - scroll_x,
                y=page_y - scroll_y,
                w=px_w,
                h=px_h,
                scale=scale,
            )
        )
        page_y += px_h + spacing
    return out


def viewport_point_to_page_pt(
    geom: PageGeometry,
    x_widget: float,
    y_widget: float,
) -> tuple[float, float]:
    """Widget point → page points (origin top-left of the page)."""
    return (x_widget - geom.x) / geom.scale, (y_widget - geom.y) / geom.scale


def page_rect_to_viewport(geom: PageGeometry, rect: PageRect):
    """Map a :class:`PageRect` (page points, top-left origin) to widget pixels."""
    from PySide6.QtCore import QRectF

    return QRectF(
        geom.x + rect.x * geom.scale,
        geom.y + rect.y * geom.scale,
        rect.w * geom.scale,
        rect.h * geom.scale,
    )


def hit_test_anchors(
    geoms: Sequence[PageGeometry],
    x_widget: float,
    y_widget: float,
    anchors: dict[ValueId, list[PageRect]],
    *,
    tolerance_pt: float = 2.0,
) -> ValueId | None:
    """Which value cell is under the pointer, or ``None``.

    Tolerance is in points and forgiving on purpose: the rendered glyphs sit
    inside their cell rectangle, but the pointer can land on the cell edge.
    """
    for geom in geoms:
        x_pt, y_pt = viewport_point_to_page_pt(geom, x_widget, y_widget)
        if not geom.contains_pt(x_pt, y_pt, tolerance_pt=tolerance_pt):
            continue
        for value_id, rects in anchors.items():
            for rect in rects:
                if rect.page != geom.page:
                    continue
                if (
                    rect.x - tolerance_pt <= x_pt <= rect.x + rect.w + tolerance_pt
                    and rect.y - tolerance_pt <= y_pt <= rect.y + rect.h + tolerance_pt
                ):
                    return value_id
    return None
