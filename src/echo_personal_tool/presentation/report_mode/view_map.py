"""Viewport ⇄ page mapping for :class:`PySide6.QtPdfWidgets.QPdfView` (UI-4 PR-1).

Moved from the UI-4.0 spike (``tools/report_preview_spike/view_map.py``), where
the model was verified pixel-by-pixel against the real widget (51/51 hit tests
in the right cell, worst rectangle error 1.86 px — see
``docs/spikes/2026-10-19-ui-4-0-report-preview-spike-ru.md`` §4).

``QPdfView`` exposes no public geometry API: the page rectangle and the
points→pixels transform live in ``QPdfViewPrivate`` (qtwebengine
``src/pdfwidgets/qpdfview.cpp``, Qt 6.11). This module reproduces that layout
from public state (document margins, page spacing, zoom mode/factor, scroll
bars, ``QPdfDocument.pagePointSize``) so the report preview can hit-test the
value-cell anchors returned by
:func:`echo_personal_tool.application.report_export.render_report`
— the «откуда значение» hover of PR-4 builds on :func:`hit_test_anchors`.

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

The maths lives in :func:`layout_pages`, a pure function over a
:class:`ViewLayout` snapshot — no Qt import, no widget — so the logic tests
pin it without a display. :func:`document_geometry` is the thin adapter that
reads a live ``QPdfView`` into that snapshot.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from PySide6.QtPdfWidgets import QPdfView
    from PySide6.QtWidgets import QWidget

    from echo_personal_tool.application.report_export import PageRect, ValueId

#: Zoom modes of the snapshot, named after ``QPdfView.ZoomMode``.
ZOOM_CUSTOM = "custom"
ZOOM_FIT_WIDTH = "fit_width"
ZOOM_FIT_IN_VIEW = "fit_in_view"


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


@dataclass(frozen=True)
class ViewLayout:
    """Everything the layout maths needs from a ``QPdfView``, as plain values."""

    viewport_w: int
    viewport_h: int
    margin_left: int
    margin_top: int
    margin_right: int
    page_spacing: int
    scroll_x: int = 0
    scroll_y: int = 0
    zoom_mode: str = ZOOM_FIT_WIDTH
    zoom_factor: float = 1.0
    single_page: bool = False
    current_page: int = 0


def _qround(value: float) -> int:
    """C++ qRound: round half away from zero."""
    return int(math.floor(value + 0.5)) if value >= 0 else -int(math.floor(-value + 0.5))


def layout_pages(
    view: ViewLayout,
    page_sizes_pt: Sequence[tuple[float, float]],
    *,
    screen_res: float,
) -> list[PageGeometry]:
    """Page rectangles in widget coordinates, one per laid-out page.

    ``page_sizes_pt`` — ``(width, height)`` in points per page
    (``QPdfDocument.pagePointSize``). In single-page mode Qt lays out only the
    current page; an out-of-range current page falls back to the first page so
    a stale navigator value can never break the mapping. An empty document
    lays out to an empty list.
    """
    if not page_sizes_pt:
        return []
    if view.single_page:
        current = view.current_page if 0 <= view.current_page < len(page_sizes_pt) else 0
        pages = [current]
    else:
        pages = list(range(len(page_sizes_pt)))

    sizes: dict[int, tuple[int, int, float]] = {}
    for page in pages:
        pt_w, pt_h = page_sizes_pt[page]
        page100_w = _qround(pt_w * screen_res)
        page100_h = _qround(pt_h * screen_res)
        if view.zoom_mode == ZOOM_CUSTOM:
            px_w = _qround(pt_w * screen_res * view.zoom_factor)
            px_h = _qround(pt_h * screen_res * view.zoom_factor)
            scale = screen_res * view.zoom_factor
        elif view.zoom_mode == ZOOM_FIT_WIDTH:
            page_scale = (view.viewport_w - view.margin_left - view.margin_right) / page100_w
            px_w = _qround(page100_w * page_scale)
            px_h = _qround(page100_h * page_scale)
            scale = screen_res * page_scale
        else:  # FitInView — also Qt's fallback for anything else
            avail_w = view.viewport_w - view.margin_left - view.margin_right
            avail_h = view.viewport_h - view.page_spacing
            factor = min(avail_w / page100_w, avail_h / page100_h)
            px_w = _qround(page100_w * factor)
            px_h = _qround(page100_h * factor)
            scale = screen_res * (px_w / page100_w)
        sizes[page] = (px_w, px_h, scale)

    total_width = max(px[0] for px in sizes.values()) + view.margin_left + view.margin_right
    page_y = view.margin_top
    out: list[PageGeometry] = []
    for page in pages:
        px_w, px_h, scale = sizes[page]
        page_x = (max(total_width, view.viewport_w) - px_w) // 2
        out.append(
            PageGeometry(
                page=page,
                x=page_x - view.scroll_x,
                y=page_y - view.scroll_y,
                w=px_w,
                h=px_h,
                scale=scale,
            )
        )
        page_y += px_h + view.page_spacing
    return out


def screen_resolution_for(widget: QWidget) -> float:
    """``logicalDotsPerInch() / 72`` of the widget's screen, read once.

    ``QPdfViewPrivate`` captures this value when the view is constructed and
    keeps it for the view's lifetime (even across screens with different DPI),
    so the caller must do the same: read it when the view is created and pass
    that one value to every mapping call (spike §4.2).
    """
    from PySide6.QtGui import QGuiApplication

    screen = widget.screen() or QGuiApplication.primaryScreen()
    return screen.logicalDotsPerInch() / 72.0


def document_geometry(
    view: QPdfView,
    *,
    screen_res: float,
    page_sizes_pt: Sequence[tuple[float, float]],
    current_page: int = 0,
) -> list[PageGeometry]:
    """Page rectangles of a live ``QPdfView`` (adapter over :func:`layout_pages`)."""
    from PySide6.QtPdfWidgets import QPdfView

    margins = view.documentMargins()
    viewport = view.viewport()
    mode = view.zoomMode()
    if mode == QPdfView.ZoomMode.Custom:
        zoom_mode = ZOOM_CUSTOM
    elif mode == QPdfView.ZoomMode.FitToWidth:
        zoom_mode = ZOOM_FIT_WIDTH
    else:
        zoom_mode = ZOOM_FIT_IN_VIEW
    snapshot = ViewLayout(
        viewport_w=viewport.width(),
        viewport_h=viewport.height(),
        margin_left=margins.left(),
        margin_top=margins.top(),
        margin_right=margins.right(),
        page_spacing=view.pageSpacing(),
        scroll_x=view.horizontalScrollBar().value(),
        scroll_y=view.verticalScrollBar().value(),
        zoom_mode=zoom_mode,
        zoom_factor=view.zoomFactor(),
        single_page=view.pageMode() == QPdfView.PageMode.SinglePage,
        current_page=current_page,
    )
    return layout_pages(snapshot, page_sizes_pt, screen_res=screen_res)


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
