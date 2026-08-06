"""Strain curve visualization widget: longitudinal + radial strain plots."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class StrainCurveWidget(QWidget):
    """PyQtGraph plot showing strain curves over the cardiac cycle."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._gls_label = QLabel("GLS: --")
        self._gls_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #2196f3;")
        layout.addWidget(self._gls_label)

        self._plot = pg.PlotWidget()
        self._plot.setLabel("left", "Strain (%)")
        self._plot.setLabel("bottom", "Frame")
        self._plot.addLegend()
        self._plot.showGrid(x=True, y=True, alpha=0.3)
        self._plot.setMinimumHeight(180)
        layout.addWidget(self._plot)

        self._longitudinal_curve = self._plot.plot(pen=pg.mkPen("#2196f3", width=2), name="Longitudinal")
        self._radial_curve = self._plot.plot(pen=pg.mkPen("#f44336", width=2), name="Radial")

        self._ed_line: pg.InfiniteLine | None = None
        self._es_line: pg.InfiniteLine | None = None
        pen_zero = pg.mkPen("#9e9e9e", style=Qt.PenStyle.DashLine)
        self._zero_line = pg.InfiniteLine(pos=0, angle=0, pen=pen_zero)
        self._plot.addItem(self._zero_line)

    def set_strain_data(
        self,
        longitudinal_strain: np.ndarray,
        radial_strain: np.ndarray,
        ed_index: int = 0,
        es_index: int = 0,
        *,
        window_start: int | None = None,
        window_end: int | None = None,
    ) -> None:
        """Plot longitudinal (blue) and radial (red) strain curves.

        Args:
            longitudinal_strain: (N,) longitudinal strain values in %.
            radial_strain: (N,) radial strain values in %.
            ed_index: end-diastole frame index for vertical marker.
            es_index: end-systole frame index for vertical marker.
            window_start: optional first frame to display (inclusive).
            window_end: optional last frame to display (inclusive).
        """
        if len(longitudinal_strain) == 0:
            self.clear()
            return

        if (
            window_start is not None
            and window_end is not None
            and window_end >= window_start
            and window_end < len(longitudinal_strain)
        ):
            frames = np.arange(window_start, window_end + 1)
            long_data = longitudinal_strain[window_start : window_end + 1]
            radial_data = radial_strain[window_start : window_end + 1]
        else:
            frames = np.arange(len(longitudinal_strain))
            long_data = longitudinal_strain
            radial_data = radial_strain

        self._longitudinal_curve.setData(frames, long_data)
        self._radial_curve.setData(frames, radial_data)
        self._plot.setXRange(float(frames[0]), float(frames[-1]), padding=0.02)

        if self._ed_line is not None:
            self._plot.removeItem(self._ed_line)
        if self._es_line is not None:
            self._plot.removeItem(self._es_line)

        self._ed_line = pg.InfiniteLine(
            pos=ed_index,
            angle=90,
            pen=pg.mkPen("#4caf50", width=1, style=Qt.PenStyle.DashLine),
            label="ED",
        )
        self._es_line = pg.InfiniteLine(
            pos=es_index,
            angle=90,
            pen=pg.mkPen("#ff9800", width=1, style=Qt.PenStyle.DashLine),
            label="ES",
        )
        self._plot.addItem(self._ed_line)
        self._plot.addItem(self._es_line)

    def set_gls_value(self, gls: float) -> None:
        """Display GLS value as text annotation."""
        self._gls_label.setText(f"GLS: {gls:.1f}%")

    def clear(self) -> None:
        """Clear all plot data."""
        self._longitudinal_curve.setData([], [])
        self._radial_curve.setData([], [])
        self._gls_label.setText("GLS: --")
        if self._ed_line is not None:
            self._plot.removeItem(self._ed_line)
            self._ed_line = None
        if self._es_line is not None:
            self._plot.removeItem(self._es_line)
            self._es_line = None
