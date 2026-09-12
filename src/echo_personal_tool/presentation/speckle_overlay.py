"""Speckle tracking overlay on 2D viewer: kernels, displacements, strain map."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from pyqtgraph import ColorMap
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QWidget

from echo_personal_tool.domain.models.speckle import (
    MyocardialZone,
    TrackingKernel,
)
from echo_personal_tool.presentation.segment_labels import short_segment_label


def segment_label_anchors(
    kernels: list[TrackingKernel],
    positions: np.ndarray | None,
    *,
    layer: str = "endo",
    offset_px: float = 22.0,
) -> list[tuple[int, float, float]]:
    """Anchor of each segment name: next to its nodes, outside the wall.

    Returns ``(segment_id, x, y)`` sorted by segment id. The anchor is the mean
    position of the segment's nodes moved *away from the cavity* by
    ``offset_px``, so the name lands beyond the myocardium instead of on top of
    the border the reader is judging. Kernels without an AHA segment, without a
    finite position or from another layer are skipped; a degenerate direction
    falls back to a fixed one, keeping the overlay deterministic.
    """
    if not kernels or positions is None or len(positions) == 0:
        return []

    node_points: list[np.ndarray] = []
    per_segment: dict[int, list[np.ndarray]] = {}
    for i, kernel in enumerate(kernels):
        if kernel.layer != layer or i >= len(positions):
            continue
        x, y = float(positions[i, 0]), float(positions[i, 1])
        if not (np.isfinite(x) and np.isfinite(y)):
            continue
        segment = int(kernel.aha_segment)
        if segment <= 0:
            continue
        point = np.array([x, y], dtype=np.float64)
        per_segment.setdefault(segment, []).append(point)
        node_points.append(point)
    if not per_segment:
        return []

    cavity = np.mean(np.vstack(node_points), axis=0)
    anchors: list[tuple[int, float, float]] = []
    for segment, points in sorted(per_segment.items()):
        node = np.mean(np.vstack(points), axis=0)
        direction = node - cavity
        norm = float(np.linalg.norm(direction))
        direction = np.array([0.0, 1.0]) if norm < 1e-9 else direction / norm
        anchor = node + direction * float(offset_px)
        anchors.append((segment, float(anchor[0]), float(anchor[1])))
    return anchors


class SpeckleOverlay(QWidget):
    """Render speckle tracking results on a PyQtGraph plot."""

    kernel_clicked = Signal(int)

    def __init__(self, plot: pg.PlotWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._plot = plot

        pen_zone = pg.mkPen("#42a5f5", width=1, style=Qt.PenStyle.DashLine)
        self._zone_item = pg.PlotDataItem(pen=pen_zone)
        self._zone_item.setZValue(2)
        self._plot.addItem(self._zone_item)

        brush_fill = pg.mkBrush(66, 165, 245, 30)
        self._endo_fill = pg.PlotDataItem(pen=None, brush=brush_fill)
        self._endo_fill.setZValue(1)
        self._plot.addItem(self._endo_fill)

        self._kernel_scatter = pg.ScatterPlotItem(
            size=8, pen=pg.mkPen("w", width=0.5), brush=pg.mkBrush(0, 255, 0, 180), symbol="o"
        )
        self._kernel_scatter.setZValue(10)
        self._plot.addItem(self._kernel_scatter)

        self._displacement_arrows: list[pg.PlotDataItem] = []
        self._strain_items: list[pg.PlotDataItem] = []
        self._phase_contour_items: list[pg.PlotDataItem] = []
        self._verification_items: list[pg.PlotDataItem] = []
        # Segment names drawn next to the wall they belong to (vendor style: the
        # reader matches a number on the image to a segment without a legend).
        self._segment_labels: list[pg.TextItem] = []
        # Which parts of the drawn contour the tracker could confirm by matching
        # there and back (clinical review Q6). EACVI/ASE ask for a display where
        # the reader can visually check tracking quality against the image loop,
        # and the round trip is the only truth-free evidence available.
        self._verification_rejected_scatter = pg.ScatterPlotItem(
            size=13, symbol="x", pen=pg.mkPen("#ff1744", width=2.0), brush=None
        )
        self._verification_rejected_scatter.setZValue(14)
        self._plot.addItem(self._verification_rejected_scatter)
        self._verification_unverified_scatter = pg.ScatterPlotItem(
            size=13, symbol="o", pen=pg.mkPen("#ffb300", width=1.6), brush=None
        )
        self._verification_unverified_scatter.setZValue(13)
        self._plot.addItem(self._verification_unverified_scatter)
        self._verification_legend = pg.TextItem(anchor=(0, 1), color="#ffd54f")
        legend_font = QFont()
        legend_font.setPointSize(9)
        self._verification_legend.setFont(legend_font)
        self._verification_legend.setZValue(15)
        self._plot.addItem(self._verification_legend)
        self._verification_legend.hide()

        self._kernel_scatter.sigClicked.connect(self._on_kernel_clicked)

    def show_myocardial_zone(self, zone: MyocardialZone) -> None:
        """Draw the dual-contour myocardial zone."""
        endo = zone.endo_points
        epi = zone.epi_points

        endo_x = np.append(endo[:, 0], endo[0, 0])
        endo_y = np.append(endo[:, 1], endo[0, 1])
        epi_x = np.append(epi[:, 0], epi[0, 0])
        epi_y = np.append(epi[:, 1], epi[0, 1])

        zone_x = np.concatenate([epi_x, endo_x[::-1]])
        zone_y = np.concatenate([epi_y, endo_y[::-1]])
        self._zone_item.setData(zone_x, zone_y)

        self._endo_fill.setData(zone_x, zone_y)

    def show_myocardial_zone_dynamic(self, endo_pts: np.ndarray) -> None:
        """Draw myocardial zone from current frame's endo kernel positions.

        Expands endo contour outward by a fixed pixel amount to approximate
        the myocardial zone at the current frame.
        """
        if len(endo_pts) < 3:
            self._zone_item.setData([], [])
            self._endo_fill.setData([], [])
            return

        centroid = np.mean(endo_pts, axis=0)
        normals = np.zeros_like(endo_pts)
        n = len(endo_pts)
        for i in range(n):
            if i == 0:
                tangent = endo_pts[1] - endo_pts[0]
            elif i == n - 1:
                tangent = endo_pts[-1] - endo_pts[-2]
            else:
                tangent = endo_pts[i + 1] - endo_pts[i - 1]
            normals[i] = np.array([-tangent[1], tangent[0]])
        norms = np.linalg.norm(normals, axis=1, keepdims=True)
        norms[norms < 1e-10] = 1.0
        normals = normals / norms

        to_center = centroid - endo_pts
        dot = np.sum(normals * to_center, axis=1)
        normals[dot > 0] *= -1.0

        wall_px = 20.0
        epi_pts = endo_pts + normals * wall_px

        endo_x = np.append(endo_pts[:, 0], endo_pts[0, 0])
        endo_y = np.append(endo_pts[:, 1], endo_pts[0, 1])
        epi_x = np.append(epi_pts[:, 0], epi_pts[0, 0])
        epi_y = np.append(epi_pts[:, 1], epi_pts[0, 1])

        zone_x = np.concatenate([epi_x, endo_x[::-1]])
        zone_y = np.concatenate([epi_y, endo_y[::-1]])
        self._zone_item.setData(zone_x, zone_y)
        self._endo_fill.setData(zone_x, zone_y)

    def show_kernels(
        self,
        kernels: list[TrackingKernel],
        valid_mask: np.ndarray | None = None,
        ncc_scores: np.ndarray | None = None,
        positions: np.ndarray | None = None,
    ) -> None:
        """Draw tracking kernels colored by NCC quality and myocardial layer."""
        if not kernels:
            self._kernel_scatter.setData([], [])
            return

        if positions is not None and len(positions) == len(kernels):
            x = np.array(positions[:, 0], dtype=np.float64, copy=True)
            y = np.array(positions[:, 1], dtype=np.float64, copy=True)
            for i, kernel in enumerate(kernels):
                if not np.isfinite(x[i]) or not np.isfinite(y[i]):
                    x[i] = float(kernel.center[0])
                    y[i] = float(kernel.center[1])
        else:
            x = np.array([k.center[0] for k in kernels])
            y = np.array([k.center[1] for k in kernels])

        layer_default = {
            "endo": pg.mkBrush(76, 175, 80, 200),
            "mid": pg.mkBrush(255, 193, 7, 200),
            "epi": pg.mkBrush(3, 169, 244, 200),
        }

        if valid_mask is not None and ncc_scores is not None:
            colors = []
            for i, kernel in enumerate(kernels):
                score = float(ncc_scores[i])
                is_invalid = (not valid_mask[i]) or (not np.isfinite(score))
                if is_invalid or score < 0.5:
                    colors.append(pg.mkBrush(183, 28, 28, 220))
                elif score >= 0.7:
                    colors.append(layer_default.get(kernel.layer, pg.mkBrush(0, 255, 0, 180)))
                else:
                    base = layer_default.get(kernel.layer, pg.mkBrush(255, 255, 0, 180))
                    colors.append(base)
            self._kernel_scatter.setData(x, y, brush=colors, size=9)
        else:
            brushes = [layer_default.get(k.layer, pg.mkBrush(0, 255, 0, 180)) for k in kernels]
            self._kernel_scatter.setData(x, y, brush=brushes, size=9)

    def show_displacements(
        self,
        kernels: list[TrackingKernel],
        displacements: np.ndarray,
        scale: float = 5.0,
    ) -> None:
        """Draw quiver arrows showing displacement direction and magnitude."""
        for item in self._displacement_arrows:
            self._plot.removeItem(item)
        self._displacement_arrows.clear()

        if not kernels or len(displacements) == 0:
            return

        for i, kernel in enumerate(kernels):
            dx = displacements[i, 0] * scale
            dy = displacements[i, 1] * scale
            if abs(dx) < 0.1 and abs(dy) < 0.1:
                continue
            arrow = pg.PlotDataItem(
                [kernel.center[0], kernel.center[0] + dx],
                [kernel.center[1], kernel.center[1] + dy],
                pen=pg.mkPen("#ffeb3b", width=1.5),
            )
            arrow.setZValue(11)
            self._plot.addItem(arrow)
            self._displacement_arrows.append(arrow)

    def show_ed_es_displacements(
        self,
        ed_contour: np.ndarray,
        es_contour: np.ndarray,
    ) -> None:
        """Draw arrows from ED to ES contour points (endo motion)."""
        for item in self._displacement_arrows:
            self._plot.removeItem(item)
        self._displacement_arrows.clear()

        if ed_contour is None or es_contour is None:
            for item in self._displacement_arrows:
                self._plot.removeItem(item)
            self._displacement_arrows.clear()
            return
        n = min(len(ed_contour), len(es_contour))
        if n < 2:
            return

        for j in range(n):
            x0, y0 = float(ed_contour[j, 0]), float(ed_contour[j, 1])
            x1, y1 = float(es_contour[j, 0]), float(es_contour[j, 1])
            if abs(x1 - x0) < 0.1 and abs(y1 - y0) < 0.1:
                continue
            arrow = pg.PlotDataItem(
                [x0, x1],
                [y0, y1],
                pen=pg.mkPen("#ffeb3b", width=1.5),
            )
            arrow.setZValue(11)
            self._plot.addItem(arrow)
            self._displacement_arrows.append(arrow)

    def show_strain_color_map(
        self,
        kernels: list[TrackingKernel],
        strain_values: np.ndarray,
        positions: np.ndarray | None = None,
    ) -> None:
        """Color-coded strain map along the myocardial border."""
        for item in self._strain_items:
            self._plot.removeItem(item)
        self._strain_items.clear()

        if not kernels or len(strain_values) == 0:
            return

        min_strain = min(strain_values.min(), -25.0)
        max_strain = max(strain_values.max(), 10.0)

        cmap = ColorMap(
            [0.0, 0.5, 1.0],
            [
                [0, 0, 255, 200],
                [255, 255, 255, 200],
                [255, 0, 0, 200],
            ],
        )

        for i, kernel in enumerate(kernels):
            if i >= len(strain_values):
                break
            if kernel.layer != "endo":
                continue
            if positions is not None and i < len(positions):
                px, py = float(positions[i, 0]), float(positions[i, 1])
            else:
                px, py = kernel.center[0], kernel.center[1]
            norm = (strain_values[i] - min_strain) / (max_strain - min_strain + 1e-10)
            r, g, b, a = cmap.map(norm)
            item = pg.ScatterPlotItem(
                x=[px],
                y=[py],
                size=12,
                brush=pg.mkBrush(int(r * 255), int(g * 255), int(b * 255), 180),
                symbol="s",
            )
            item.setZValue(12)
            self._plot.addItem(item)
            self._strain_items.append(item)

    def show_segment_labels(
        self,
        kernels: list[TrackingKernel],
        positions: np.ndarray | None = None,
        *,
        layer: str = "endo",
        offset_px: float = 22.0,
    ) -> int:
        """Name the visible wall segments on the image (vendor-style short names).

        The vendors label the wall they measure ("Inf. septum base"), so the
        reader can tie a number to a place; the overlay follows suit with
        :func:`segment_label_anchors` for placement and short localised names.
        Labels belong to the overlay and disappear with it (:meth:`clear`).
        Returns the number of labels drawn.
        """
        for item in self._segment_labels:
            self._plot.removeItem(item)
        self._segment_labels.clear()

        for segment, x, y in segment_label_anchors(kernels, positions, layer=layer, offset_px=offset_px):
            item = pg.TextItem(
                short_segment_label(segment),
                color=(235, 247, 255),
                anchor=(0.5, 0.5),
                border=pg.mkPen(6, 10, 16, 170),
                fill=pg.mkBrush(6, 10, 16, 120),
            )
            font = QFont("sans-serif", 8)
            font.setBold(True)
            item.setFont(font)
            item.setPos(x, y)
            item.setZValue(21)
            self._plot.addItem(item)
            self._segment_labels.append(item)
        return len(self._segment_labels)

    def show_verification_marks(
        self,
        positions: np.ndarray | None,
        rejected: np.ndarray | None,
        unverified: np.ndarray | None,
        legend: str = "",
    ) -> None:
        """Mark the nodes the round trip could not confirm (clinical review Q6).

        ``rejected`` / ``unverified`` are boolean masks over the kernels: the
        patch at the drawn position did not match back onto the contour the
        operator drew at end diastole, or the backward match produced no verdict
        at all. Confirmed nodes stay unmarked — the marks are meant to draw the
        eye exactly where the number on screen is not backed by the image.
        """
        if positions is None or rejected is None or unverified is None or len(positions) == 0:
            self._verification_rejected_scatter.setData([], [])
            self._verification_unverified_scatter.setData([], [])
            self._verification_legend.hide()
            return

        x = np.asarray(positions[:, 0], dtype=np.float64)
        y = np.asarray(positions[:, 1], dtype=np.float64)
        finite = np.isfinite(x) & np.isfinite(y)
        rejected = np.asarray(rejected, dtype=bool) & finite
        unverified = np.asarray(unverified, dtype=bool) & finite
        self._verification_rejected_scatter.setData(x[rejected], y[rejected])
        self._verification_unverified_scatter.setData(x[unverified], y[unverified])

        if legend and (rejected.any() or unverified.any()):
            self._verification_legend.setText(legend, color="#ffd54f")
            view_range = self._plot.viewRange()
            self._verification_legend.setPos(
                float(view_range[0][0]),
                float(view_range[1][0]) + 0.06 * float(view_range[1][1] - view_range[1][0]),
            )
            self._verification_legend.show()
        else:
            self._verification_legend.hide()

    def show_phase_contours(
        self,
        ed_contour: np.ndarray | None,
        es_contour: np.ndarray | None,
    ) -> None:
        """Draw ED (green) and ES (red) endocardial contours for phase verification."""
        for item in self._phase_contour_items:
            self._plot.removeItem(item)
        self._phase_contour_items.clear()

        if ed_contour is not None and len(ed_contour) >= 3:
            x = np.append(ed_contour[:, 0], ed_contour[0, 0])
            y = np.append(ed_contour[:, 1], ed_contour[0, 1])
            pen_ed = pg.mkPen("#00e676", width=2, style=Qt.PenStyle.DashLine)
            item = pg.PlotDataItem(x, y, pen=pen_ed)
            item.setZValue(15)
            self._plot.addItem(item)
            self._phase_contour_items.append(item)

        if es_contour is not None and len(es_contour) >= 3:
            x = np.append(es_contour[:, 0], es_contour[0, 0])
            y = np.append(es_contour[:, 1], es_contour[0, 1])
            pen_es = pg.mkPen("#ff1744", width=2, style=Qt.PenStyle.DashLine)
            item = pg.PlotDataItem(x, y, pen=pen_es)
            item.setZValue(15)
            self._plot.addItem(item)
            self._phase_contour_items.append(item)

    def clear(self) -> None:
        """Remove all overlay items."""
        self._zone_item.setData([], [])
        self._endo_fill.setData([], [])
        self._verification_rejected_scatter.setData([], [])
        self._verification_unverified_scatter.setData([], [])
        self._verification_legend.hide()
        self._kernel_scatter.setData([], [])
        for item in self._displacement_arrows:
            self._plot.removeItem(item)
        self._displacement_arrows.clear()
        for item in self._strain_items:
            self._plot.removeItem(item)
        self._strain_items.clear()
        for item in self._phase_contour_items:
            self._plot.removeItem(item)
        self._phase_contour_items.clear()
        for item in self._segment_labels:
            self._plot.removeItem(item)
        self._segment_labels.clear()

    def _on_kernel_clicked(self, scatter, points) -> None:
        if points:
            idx = points[0].index()
            self.kernel_clicked.emit(idx)

    def show_ncc_heatmap(
        self,
        kernels: list[TrackingKernel],
        ncc_scores: np.ndarray,
        positions: np.ndarray | None = None,
    ) -> None:
        """Color-coded NCC quality heatmap along the myocardial border."""
        for item in self._strain_items:
            self._plot.removeItem(item)
        self._strain_items.clear()

        if not kernels or len(ncc_scores) == 0:
            return

        min_ncc = max(ncc_scores.min(), 0.0)
        max_ncc = min(ncc_scores.max(), 1.0)

        cmap = ColorMap(
            [0.0, 0.5, 1.0],
            [
                [255, 0, 0, 200],
                [255, 255, 0, 200],
                [0, 255, 0, 200],
            ],
        )

        for i, kernel in enumerate(kernels):
            if i >= len(ncc_scores):
                break
            score = float(ncc_scores[i])
            if positions is not None and i < len(positions):
                px, py = float(positions[i, 0]), float(positions[i, 1])
            else:
                px, py = kernel.center[0], kernel.center[1]
            norm = (score - min_ncc) / (max_ncc - min_ncc + 1e-10)
            r, g, b, a = cmap.map(norm)
            item = pg.ScatterPlotItem(
                x=[px],
                y=[py],
                size=12,
                brush=pg.mkBrush(int(r * 255), int(g * 255), int(b * 255), 180),
                symbol="s",
            )
            item.setZValue(12)
            self._plot.addItem(item)
            self._strain_items.append(item)
