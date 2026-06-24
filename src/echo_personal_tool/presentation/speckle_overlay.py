"""Speckle tracking overlay on 2D viewer: kernels, displacements, strain map."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import ColorMap
from PySide6.QtWidgets import QWidget

from echo_personal_tool.domain.models.speckle import (
    MyocardialZone,
    TrackingKernel,
)


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
        self._endo_fill = pg.PlotDataItem(
            pen=pg.mkPen(Qt.PenStyle.NoPen), brush=brush_fill
        )
        self._endo_fill.setZValue(1)
        self._plot.addItem(self._endo_fill)

        self._kernel_scatter = pg.ScatterPlotItem(
            size=8, pen=pg.mkPen("w", width=0.5), brush=pg.mkBrush(0, 255, 0, 180), symbol="o"
        )
        self._kernel_scatter.setZValue(10)
        self._plot.addItem(self._kernel_scatter)

        self._displacement_arrows: list[pg.PlotDataItem] = []
        self._strain_items: list[pg.PlotDataItem] = []

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

        self._endo_fill.setData(endo_x, endo_y)

    def show_kernels(
        self,
        kernels: list[TrackingKernel],
        valid_mask: np.ndarray | None = None,
        ncc_scores: np.ndarray | None = None,
    ) -> None:
        """Draw tracking kernels colored by NCC quality."""
        if not kernels:
            self._kernel_scatter.setData([], [])
            return

        x = np.array([k.center[0] for k in kernels])
        y = np.array([k.center[1] for k in kernels])

        if valid_mask is not None and ncc_scores is not None:
            colors = []
            for i in range(len(kernels)):
                if not valid_mask[i]:
                    colors.append(pg.mkBrush(255, 0, 0, 180))
                elif ncc_scores[i] > 0.8:
                    colors.append(pg.mkBrush(0, 255, 0, 180))
                else:
                    colors.append(pg.mkBrush(255, 255, 0, 180))
            self._kernel_scatter.setData(x, y, brush=colors)
        else:
            self._kernel_scatter.setData(x, y)

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

    def show_strain_color_map(
        self,
        kernels: list[TrackingKernel],
        strain_values: np.ndarray,
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
            norm = (strain_values[i] - min_strain) / (max_strain - min_strain + 1e-10)
            r, g, b, a = cmap.map(norm)
            item = pg.ScatterPlotItem(
                x=[kernel.center[0]],
                y=[kernel.center[1]],
                size=12,
                brush=pg.mkBrush(int(r * 255), int(g * 255), int(b * 255), 180),
                symbol="s",
            )
            item.setZValue(12)
            self._plot.addItem(item)
            self._strain_items.append(item)

    def clear(self) -> None:
        """Remove all overlay items."""
        self._zone_item.setData([], [])
        self._endo_fill.setData([], [])
        self._kernel_scatter.setData([], [])
        for item in self._displacement_arrows:
            self._plot.removeItem(item)
        self._displacement_arrows.clear()
        for item in self._strain_items:
            self._plot.removeItem(item)
        self._strain_items.clear()

    def _on_kernel_clicked(self, scatter, points) -> None:
        if points:
            idx = points[0].index()
            self.kernel_clicked.emit(idx)
