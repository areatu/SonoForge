"""Strain curves view — per-segment curves with ECG, Clinical-style layout."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.infrastructure.i18n import tr

if TYPE_CHECKING:
    from echo_personal_tool.domain.models.speckle import StrainResult

logger = logging.getLogger(__name__)

# Segment colors matching Clinical style
SEGMENT_COLORS: dict[int, tuple[int, int, int]] = {
    1: (0, 200, 255),  # БазПерг - cyan
    2: (0, 150, 255),  # Базбок - blue
    3: (0, 255, 100),  # СрПерг - green
    4: (255, 255, 0),  # Србок - yellow
    5: (255, 100, 0),  # АпПер - orange
    6: (255, 0, 100),  # АпЛат - pink
}

SEGMENT_NAMES_RU: dict[int, str] = {
    1: tr("strain.seg_basal_sept"),
    2: tr("strain.seg_basal_lat"),
    3: tr("strain.seg_mid_sept"),
    4: tr("strain.seg_mid_lat"),
    5: tr("strain.seg_apical_sept"),
    6: tr("strain.seg_apical_lat"),
}

# View segment ranges
VIEW_SEGMENTS: dict[str, list[int]] = {
    "A4C": [1, 2, 3, 4, 5, 6],
    "A2C": [7, 8, 9, 10, 11],
    "DAO": [12, 13, 14, 15, 16],
}


class SegmentCurvePanel(QWidget):
    """Single panel showing per-segment strain curves for one view."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._title = title
        self._curves: dict[int, pg.PlotDataItem] = {}
        self._mean_curve: pg.PlotDataItem | None = None
        self._es_marker: pg.InfiniteLine | None = None
        self._ecg_item: pg.PlotDataItem | None = None
        self._ecg_marker: pg.InfiniteLine | None = None
        self._label_items: list[pg.TextItem] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        # Title: view name + GLS value
        header = QHBoxLayout()
        title_label = QLabel(title)
        title_label.setStyleSheet("font-weight: bold; color: #e0e0e0; font-size: 11px;")
        header.addWidget(title_label)
        header.addStretch()
        self._gls_label = QLabel("")
        self._gls_label.setStyleSheet("color: #ffd54f; font-weight: bold; font-size: 12px;")
        header.addWidget(self._gls_label)
        layout.addLayout(header)

        # Segment labels row
        self._labels_layout = QHBoxLayout()
        self._labels_layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self._labels_layout)

        # Main curve plot
        self._plot = pg.PlotWidget()
        self._plot.setBackground("black")
        self._plot.setLabel("left", "%")
        self._plot.setLabel("bottom", tr("strain.time_axis"))
        self._plot.showGrid(x=True, y=True, alpha=0.2)
        self._plot.setMinimumHeight(120)
        self._plot.setMaximumHeight(200)

        # Zero line
        pen_zero = pg.mkPen("#666666", style=Qt.PenStyle.DashLine)
        self._plot.addItem(pg.InfiniteLine(pos=0, angle=0, pen=pen_zero))

        layout.addWidget(self._plot, stretch=1)

        # ECG trace (hidden when the clip has no real ECG)
        self._ecg_plot = pg.PlotWidget()
        self._ecg_plot.setBackground("black")
        self._ecg_plot.hideAxis("left")
        self._ecg_plot.hideAxis("bottom")
        self._ecg_plot.setMaximumHeight(40)
        self._ecg_plot.setMinimumHeight(30)
        self._ecg_plot.setVisible(False)
        layout.addWidget(self._ecg_plot, stretch=0)

    def set_strain_data(
        self,
        segment_strains: dict[int, np.ndarray],
        ed_index: int = 0,
        es_index: int = 0,
        frame_time_ms: float = 33.3,
    ) -> None:
        """Plot per-segment strain curves."""
        # Clear old curves
        for curve in self._curves.values():
            self._plot.removeItem(curve)
        self._curves.clear()
        if self._mean_curve is not None:
            self._plot.removeItem(self._mean_curve)
            self._mean_curve = None

        if not segment_strains:
            return

        # Find common frame range
        all_lengths = [len(v) for v in segment_strains.values()]
        if not all_lengths:
            return
        max_len = max(all_lengths)

        # Plot each segment curve (thin 1px lines, vendor style)
        for seg_id, strain_curve in segment_strains.items():
            if seg_id not in SEGMENT_COLORS:
                continue
            color = SEGMENT_COLORS[seg_id]
            x = np.arange(len(strain_curve)) * frame_time_ms
            pen = pg.mkPen(color, width=1)
            curve = self._plot.plot(x, strain_curve, pen=pen)
            self._curves[seg_id] = curve

        # Compute and plot mean curve
        if len(segment_strains) > 1:
            # Align to common length
            curves_array = np.full((len(segment_strains), max_len), np.nan)
            for i, curve in enumerate(segment_strains.values()):
                curves_array[i, : len(curve)] = curve
            mean_curve = np.nanmean(curves_array, axis=0)
            x_mean = np.arange(max_len) * frame_time_ms
            pen_mean = pg.mkPen(255, 255, 255, width=1.5, style=Qt.PenStyle.DashLine)
            self._mean_curve = self._plot.plot(x_mean, mean_curve, pen=pen_mean)

        # ES marker
        if self._es_marker is not None:
            self._plot.removeItem(self._es_marker)
        es_x = es_index * frame_time_ms
        self._es_marker = pg.InfiniteLine(
            pos=es_x,
            angle=90,
            pen=pg.mkPen("#ffd54f", width=2, style=Qt.PenStyle.DashLine),
        )
        self._plot.addItem(self._es_marker)

        # Set X range (timeline) and auto-scale Y to the actual data
        self._plot.setXRange(0, max_len * frame_time_ms, padding=0.02)
        self._plot.enableAutoRange(axis=pg.ViewBox.YAxis, enable=True)

    def set_gls(self, gls: float | None) -> None:
        """Show the view's GLS value in the header (large, vendor style)."""
        if gls is None:
            self._gls_label.setText("")
        else:
            self._gls_label.setText(f"GLS {gls:.1f}%")

    def set_ecg_visible(self, visible: bool) -> None:
        """Show/hide the ECG trace row (hidden when no real ECG)."""
        self._ecg_plot.setVisible(visible)
        if not visible:
            if self._ecg_item is not None:
                self._ecg_plot.removeItem(self._ecg_item)
                self._ecg_item = None
            if self._ecg_marker is not None:
                self._ecg_plot.removeItem(self._ecg_marker)
                self._ecg_marker = None

    def set_ecg_trace(
        self,
        ecg_data: np.ndarray,
        frame_time_ms: float = 33.3,
        current_frame: int = 0,
        *,
        ecg_sample_rate: float | None = None,
    ) -> None:
        """Display ECG trace with frame marker (real ECG only)."""
        if self._ecg_item is not None:
            self._ecg_plot.removeItem(self._ecg_item)
            self._ecg_item = None
        if self._ecg_marker is not None:
            self._ecg_plot.removeItem(self._ecg_marker)
            self._ecg_marker = None

        if ecg_data is None or len(ecg_data) == 0:
            self.set_ecg_visible(False)
            return

        n = len(ecg_data)
        if ecg_sample_rate and ecg_sample_rate > 0:
            t = np.arange(n) / ecg_sample_rate * 1000.0
        else:
            t = np.arange(n) * frame_time_ms

        pen = pg.mkPen("#4caf50", width=1)
        self._ecg_item = self._ecg_plot.plot(t, ecg_data, pen=pen)

        # Frame marker
        marker_x = current_frame * frame_time_ms
        self._ecg_marker = pg.InfiniteLine(
            pos=marker_x,
            angle=90,
            pen=pg.mkPen("#ffd54f", width=1, style=Qt.PenStyle.DashLine),
        )
        self._ecg_plot.addItem(self._ecg_marker)

        self._ecg_plot.setXRange(0, t[-1] if len(t) > 0 else 1000)

    def clear(self) -> None:
        for curve in self._curves.values():
            self._plot.removeItem(curve)
        self._curves.clear()
        if self._mean_curve is not None:
            self._plot.removeItem(self._mean_curve)
            self._mean_curve = None
        if self._es_marker is not None:
            self._plot.removeItem(self._es_marker)
            self._es_marker = None
        if self._ecg_item is not None:
            self._ecg_plot.removeItem(self._ecg_item)
            self._ecg_item = None
        if self._ecg_marker is not None:
            self._ecg_plot.removeItem(self._ecg_marker)
            self._ecg_marker = None


class StrainCurvesView(QWidget):
    """Full strain curves view with 3 panels (A4C, A2C, DAO) + segment labels."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Title
        title = QLabel("Strain Curves")
        title.setStyleSheet("font-weight: bold; color: #e0e0e0; font-size: 12px;")
        layout.addWidget(title)

        # Segment legend
        legend_layout = QHBoxLayout()
        for seg_id in [1, 2, 3, 4, 5, 6]:
            color = SEGMENT_COLORS.get(seg_id, (255, 255, 255))
            name = SEGMENT_NAMES_RU.get(seg_id, f"Seg{seg_id}")
            lbl = QLabel(f"■ {name}")
            lbl.setStyleSheet(f"color: rgb({color[0]},{color[1]},{color[2]}); font-size: 10px;")
            legend_layout.addWidget(lbl)
        lbl_mean = QLabel("┅ Mean")
        lbl_mean.setStyleSheet("color: #ffffff; font-size: 10px;")
        legend_layout.addWidget(lbl_mean)
        legend_layout.addStretch()
        layout.addLayout(legend_layout)

        # Three panels
        self._panel_a4c = SegmentCurvePanel("A4C")
        self._panel_a2c = SegmentCurvePanel("A2C")
        self._panel_dao = SegmentCurvePanel("DAO (A3C)")

        layout.addWidget(self._panel_a4c, stretch=1)
        layout.addWidget(self._panel_a2c, stretch=1)
        layout.addWidget(self._panel_dao, stretch=1)

    def set_strain_data(
        self,
        result: StrainResult,
        frame_time_ms: float = 33.3,
    ) -> None:
        """Update all panels with strain data from StrainResult."""
        if result.segment_strain is None or result.per_kernel_longitudinal is None:
            return

        # Compute per-segment strain curves
        # Group kernels by segment
        segment_kernels: dict[int, list[int]] = {}
        for i, kernel in enumerate(result.kernels):
            if kernel.layer == "endo" and kernel.aha_segment > 0:
                segment_kernels.setdefault(kernel.aha_segment, []).append(i)

        # For each segment, compute mean strain curve from kernel strains
        segment_curves: dict[int, np.ndarray] = {}
        n_frames = len(result.longitudinal) if result.longitudinal is not None else 0

        if result.tracked_positions_all is not None and n_frames > 0:
            ed_positions = result.tracked_positions_all[result.ed_index] if result.ed_index < n_frames else None
            if ed_positions is not None:
                for seg_id, kernel_indices in segment_kernels.items():
                    # Compute per-segment longitudinal strain curve
                    seg_strain = np.zeros(n_frames)
                    for t in range(n_frames):
                        frame_positions = result.tracked_positions_all[t]
                        if frame_positions is None:
                            continue
                        # Compute arc length change for this segment
                        ed_pts = ed_positions[kernel_indices]
                        t_pts = frame_positions[kernel_indices]
                        if len(ed_pts) < 2:
                            continue
                        l0 = np.sum(np.linalg.norm(np.diff(ed_pts, axis=0), axis=1))
                        lt = np.sum(np.linalg.norm(np.diff(t_pts, axis=0), axis=1))
                        if l0 > 1e-6:
                            ratio = lt / l0
                            seg_strain[t] = 0.5 * (ratio**2 - 1.0) * 100.0
                    segment_curves[seg_id] = seg_strain

        # ECG trace: real DICOM ECG only — no synthetic placeholder. When the
        # clip has no ECG the strip rows are hidden entirely.
        has_ecg = result.ecg_trace_for_display is not None and len(result.ecg_trace_for_display) > 0
        ecg_sample_rate: float | None = None
        if has_ecg:
            ecg = result.ecg_trace_for_display
            if result.ecg_waveform is not None and result.ecg_waveform.primary_lead is not None:
                ecg_sample_rate = float(result.ecg_waveform.primary_lead.sampling_frequency)
        else:
            ecg = None

        def _gls_for(seg_ids: list[int]) -> float | None:
            values = [result.segment_strain[s] for s in seg_ids if s in (result.segment_strain or {})]
            return float(np.mean(values)) if values else None

        def _update_panel(panel: SegmentCurvePanel, seg_ids: list[int], curves: dict[int, np.ndarray]) -> None:
            panel.set_gls(_gls_for(seg_ids))
            if curves:
                panel.set_strain_data(curves, result.ed_index, result.es_index, frame_time_ms)
                if ecg is not None:
                    panel.set_ecg_visible(True)
                    panel.set_ecg_trace(ecg, frame_time_ms, result.es_index, ecg_sample_rate=ecg_sample_rate)
                else:
                    panel.set_ecg_visible(False)
            else:
                panel.clear()
                panel.set_ecg_visible(False)

        _update_panel(
            self._panel_a4c,
            VIEW_SEGMENTS["A4C"],
            {k: v for k, v in segment_curves.items() if k in VIEW_SEGMENTS["A4C"]},
        )
        _update_panel(
            self._panel_a2c,
            VIEW_SEGMENTS["A2C"],
            {k: v for k, v in segment_curves.items() if k in VIEW_SEGMENTS["A2C"]},
        )
        _update_panel(
            self._panel_dao,
            VIEW_SEGMENTS["DAO"],
            {k: v for k, v in segment_curves.items() if k in VIEW_SEGMENTS["DAO"]},
        )

    def _generate_synthetic_ecg(self, n_frames: int, hr_bpm: float) -> np.ndarray:
        """Generate synthetic ECG trace."""
        if n_frames < 2 or hr_bpm <= 0:
            return np.zeros(max(n_frames, 100))

        frame_time_s = 33.3 / 1000.0
        hr_hz = hr_bpm / 60.0
        period_frames = int(1.0 / (hr_hz * frame_time_s))

        ecg = np.zeros(n_frames)
        for i in range(n_frames):
            phase = (i % period_frames) / period_frames
            if 0.0 <= phase < 0.1:
                ecg[i] = 0.15 * np.sin(np.pi * phase / 0.1)
            elif 0.15 <= phase < 0.18:
                ecg[i] = -0.1
            elif 0.18 <= phase < 0.25:
                ecg[i] = 1.0 * np.sin(np.pi * (phase - 0.18) / 0.07)
            elif 0.25 <= phase < 0.28:
                ecg[i] = -0.2
            elif 0.35 <= phase < 0.5:
                ecg[i] = 0.3 * np.sin(np.pi * (phase - 0.35) / 0.15)

        return ecg

    def clear(self) -> None:
        self._panel_a4c.clear()
        self._panel_a2c.clear()
        self._panel_dao.clear()
