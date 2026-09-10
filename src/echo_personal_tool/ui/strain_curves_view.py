"""Strain curves view — vendor-style per-segment deformation graphs.

Design follows the reference curves of commercial STE packages
(GE EchoPAC / QLAB look):
  * one graph per analysed view, stacked vertically;
  * the GLOBAL (mean) curve is drawn bold white on top of thin, translucent
    segment curves — the eye reads the global deformation first;
  * the segment legend sits INSIDE the top-right corner of each graph with the
    short clinical names (БазПерг, СрПерг, …) and a colour chip, exactly like
    the vendor windows;
  * strain is plotted from ED (0 %) over the cardiac cycle; a dashed zero
    reference line and an end-systole marker are drawn;
  * a real-ECG trace strip (when present) is aligned under the graph on the
    same time axis, with a moving frame marker;
  * views without data show a clean placeholder instead of an empty grid.
"""

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

# Vendor-style per-segment palette (A4C 6-segment scheme used by our tracker).
# Basal / mid / apical rings follow the strain bull's-eye colour families
# (yellow-orange, cyan-magenta, green-blue) used by clinical packages.
SEGMENT_COLORS: dict[int, tuple[int, int, int]] = {
    1: (255, 235, 59),  # БазПерг  — yellow
    2: (255, 152, 0),  # Базбок   — orange
    3: (38, 198, 218),  # СрПерг   — cyan
    4: (233, 30, 99),  # Србок    — magenta
    5: (102, 187, 106),  # АпПер    — green
    6: (66, 165, 245),  # АпЛат    — blue
}

SEGMENT_NAMES_RU: dict[int, str] = {
    1: tr("strain.seg_basal_sept"),
    2: tr("strain.seg_basal_lat"),
    3: tr("strain.seg_mid_sept"),
    4: tr("strain.seg_mid_lat"),
    5: tr("strain.seg_apical_septal"),
    6: tr("strain.seg_apical_lat"),
}

# View segment ranges
VIEW_SEGMENTS: dict[str, list[int]] = {
    "A4C": [1, 2, 3, 4, 5, 6],
    "A2C": [7, 8, 9, 10, 11],
    "DAO": [12, 13, 14, 15, 16],
}

# White global curve colour
_GLOBAL_COLOR = (255, 255, 255)


class SegmentCurvePanel(QWidget):
    """One vendor-style deformation graph for a single view.

    Header row: view name (left) + GLS (right). The graph itself carries a
    top-right legend, a bold white global curve and thin segment curves.
    """

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._title = title
        self._curves: dict[int, pg.PlotDataItem] = {}
        self._mean_curve: pg.PlotDataItem | None = None
        self._es_marker: pg.InfiniteLine | None = None
        self._ecg_item: pg.PlotDataItem | None = None
        self._ecg_marker: pg.InfiniteLine | None = None
        self._label_items: list[pg.TextItem] = []
        self._legend: pg.LegendItem | None = None
        self._placeholder: QLabel | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)

        # ── Header: «A4C · Продольная деформация»  +  GLS ────────────────
        header = QHBoxLayout()
        title_label = QLabel(title)
        title_label.setStyleSheet("font-weight: bold; color: #eceff1; font-size: 13px;")
        header.addWidget(title_label)
        metric_label = QLabel(tr("strain.metric_deformation").lower())
        metric_label.setStyleSheet("color: #90a4ae; font-size: 11px;")
        header.addWidget(metric_label)
        header.addStretch()
        self._gls_label = QLabel("")
        self._gls_label.setStyleSheet("color: #ffd54f; font-weight: bold; font-size: 15px;")
        header.addWidget(self._gls_label)
        layout.addLayout(header)

        # ── Graph ─────────────────────────────────────────────────────────
        self._plot = pg.PlotWidget()
        self._plot.setBackground("#0b0e11")
        self._plot.setLabel("left", tr("strain.axis_pct"))
        self._plot.setLabel("bottom", tr("strain.time_axis"))
        self._plot.showGrid(x=True, y=True, alpha=0.15)
        self._plot.setMinimumHeight(200)
        self._plot.setMouseEnabled(x=False, y=False)

        # Subdued y ticks — strain is negative in systole, so the y axis is
        # auto-scaled to the data (vendor graphs put the 0 line mid-way).
        self._plot.getAxis("left").setTextPen("#90a4ae")
        self._plot.getAxis("bottom").setTextPen("#90a4ae")

        # Zero reference line
        pen_zero = pg.mkPen("#37474f", width=1, style=Qt.PenStyle.DashLine)
        self._plot.addItem(pg.InfiniteLine(pos=0, angle=0, pen=pen_zero))

        # Placeholder for empty views ("нет данных")
        self._placeholder = QLabel(tr("strain.no_data"))
        self._placeholder.setStyleSheet("color: #546e7a; font-size: 12px;")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setMinimumHeight(200)

        # Wrap plot + placeholder in a stack so the empty view looks clean.
        from PySide6.QtWidgets import QStackedLayout

        self._stack = QStackedLayout()
        self._stack.addWidget(self._plot)
        self._stack.addWidget(self._placeholder)
        container = QWidget()
        container.setLayout(self._stack)
        layout.addWidget(container, stretch=1)

        # ── ECG strip (hidden unless a real ECG exists) ────────────────────
        self._ecg_plot = pg.PlotWidget()
        self._ecg_plot.setBackground("#0b0e11")
        self._ecg_plot.hideAxis("left")
        self._ecg_plot.hideAxis("bottom")
        self._ecg_plot.setMaximumHeight(46)
        self._ecg_plot.setMinimumHeight(36)
        self._ecg_plot.setVisible(False)
        layout.addWidget(self._ecg_plot, stretch=0)

    # ── data ──────────────────────────────────────────────────────────────

    def set_strain_data(
        self,
        segment_strains: dict[int, np.ndarray],
        ed_index: int = 0,
        es_index: int = 0,
        frame_time_ms: float = 33.3,
    ) -> None:
        """Plot per-segment strain curves + bold global curve (vendor style)."""
        self._clear_plot_items()
        self._stack.setCurrentWidget(self._plot)
        self._legend = None

        if not segment_strains:
            self._stack.setCurrentWidget(self._placeholder)
            return

        max_len = max(len(v) for v in segment_strains.values())
        if max_len < 2:
            return

        x = np.arange(max_len) * frame_time_ms

        # Thin, translucent segment curves (drawn first, under the global one)
        for seg_id, strain_curve in segment_strains.items():
            if seg_id not in SEGMENT_COLORS:
                continue
            color = SEGMENT_COLORS[seg_id]
            # Normalize every curve to the same x-grid
            xx = np.arange(len(strain_curve)) * frame_time_ms
            curve = self._plot.plot(xx, strain_curve, pen=pg.mkPen(color, width=1))
            curve.setOpacity(0.75)
            curve.setZValue(2)
            self._curves[seg_id] = curve

        if not self._curves:
            self._stack.setCurrentWidget(self._placeholder)
            return

        # Global (mean) curve — bold white, vendor emphasis
        raw_curves = [(seg_id, c) for seg_id, c in segment_strains.items() if seg_id in SEGMENT_COLORS]
        curves_array = np.full((len(raw_curves), max_len), np.nan)
        for i, (seg_id, strain_curve) in enumerate(raw_curves):
            curves_array[i, : len(strain_curve)] = strain_curve
        mean_curve = np.nanmean(curves_array, axis=0)
        self._mean_curve = self._plot.plot(
            x,
            mean_curve,
            pen=pg.mkPen(_GLOBAL_COLOR, width=2.2),
        )
        self._mean_curve.setZValue(3)

        # Legend inside the graph top-right corner (vendor position)
        self._legend = pg.LegendItem(offset=(4, 4))
        self._legend.setParentItem(self._plot.getPlotItem())
        self._legend.anchor(itemPos=(1, 0), parentPos=(1, 0), offset=(-6, 4))
        self._legend.setBrush(pg.mkBrush(20, 26, 32, 210))
        self._legend.setPen(pg.mkPen("#37474f"))
        for seg_id in sorted(self._curves):
            sample = pg.PlotDataItem(pen=pg.mkPen(SEGMENT_COLORS[seg_id], width=3))
            self._legend.addItem(sample, SEGMENT_NAMES_RU.get(seg_id, f"Seg{seg_id}"))
        mean_sample = pg.PlotDataItem(pen=pg.mkPen(_GLOBAL_COLOR, width=3))
        self._legend.addItem(mean_sample, tr("strain.legend_global"))

        # End-systole marker (dashed vertical line, like the vendor's phase bar)
        if self._es_marker is not None:
            self._plot.removeItem(self._es_marker)
        es_x = es_index * frame_time_ms
        self._es_marker = pg.InfiniteLine(
            pos=es_x,
            angle=90,
            pen=pg.mkPen("#ffd54f", width=1, style=Qt.PenStyle.DashLine),
        )
        self._es_marker.setZValue(4)
        self._plot.addItem(self._es_marker)

        # Time axis aligned with the ECG strip; the y range is set explicitly
        # (and auto-range disabled afterwards) so the curve fills most of the
        # plot height and stays centred, instead of hugging an edge.
        self._plot.setXRange(0, max_len * frame_time_ms, padding=0.02)
        self._plot.enableAutoRange(axis=pg.ViewBox.YAxis, enable=False)
        self._plot.setYRange(
            *self._auto_y_bounds(np.concatenate([c for _, c in raw_curves if len(c)]), mean_curve),
            padding=0.0,
        )

    @staticmethod
    def _auto_y_bounds(seg_flat: np.ndarray, mean: np.ndarray) -> tuple[float, float]:
        """Y range sized so the curves fill most of the plot height, centered.

        Symmetric padding around the data span keeps the zero line inside and
        the curve centred — the deformation occupies the majority of the
        window instead of hugging one edge.
        """
        finite = np.concatenate(
            [seg_flat[~np.isnan(seg_flat)] if seg_flat.size else np.array([]), mean[~np.isnan(mean)]]
        )
        if finite.size == 0:
            return (-10.0, 0.0)
        lo = float(np.nanmin(finite))
        hi = float(np.nanmax(finite))
        span = max(hi - lo, 1.0)
        pad = span * 0.13
        lo -= pad
        hi += pad
        # Centring fallbacks: keep the zero line in view and a sensible band
        # when the data barely moves (e.g. flat tracking).
        if hi - lo < 8.0:
            mid = (hi + lo) / 2.0
            lo, hi = mid - 4.0, mid + 4.0
        if lo > 0.0:
            lo = -1.0
        return (lo, hi)

    def _clear_plot_items(self) -> None:
        for curve in self._curves.values():
            self._plot.removeItem(curve)
        self._curves.clear()
        if self._mean_curve is not None:
            self._plot.removeItem(self._mean_curve)
            self._mean_curve = None
        if self._legend is not None:
            self._plot.removeItem(self._legend)
            self._legend = None

    def set_gls(self, gls: float | None) -> None:
        """Show the view's GLS value in the header (large, yellow)."""
        if gls is None:
            self._gls_label.setText("")
        else:
            self._gls_label.setText(f"GLS {gls:.1f}%")

    # ── ECG ───────────────────────────────────────────────────────────────

    def set_ecg_visible(self, visible: bool) -> None:
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
        """Display the real ECG strip aligned to the strain time axis."""
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

        marker_x = current_frame * frame_time_ms
        self._ecg_marker = pg.InfiniteLine(
            pos=marker_x,
            angle=90,
            pen=pg.mkPen("#ffd54f", width=1, style=Qt.PenStyle.DashLine),
        )
        self._ecg_plot.addItem(self._ecg_marker)

        # Same time span as the strain plot so the strips line up
        self._ecg_plot.setXRange(0, t[-1] if len(t) > 0 else 1000, padding=0.02)

    def set_ecg_marker_frame(self, frame_index: int, frame_time_ms: float = 33.3) -> None:
        """Move the ECG frame marker (used by animation in the cine panel)."""
        if self._ecg_marker is not None and frame_time_ms > 0:
            self._ecg_marker.setPos(float(frame_index) * frame_time_ms)

    def clear(self) -> None:
        self._clear_plot_items()
        if self._es_marker is not None:
            self._plot.removeItem(self._es_marker)
            self._es_marker = None
        if self._ecg_item is not None:
            self._ecg_plot.removeItem(self._ecg_item)
            self._ecg_item = None
        if self._ecg_marker is not None:
            self._ecg_plot.removeItem(self._ecg_marker)
            self._ecg_marker = None
        self._stack.setCurrentWidget(self._placeholder)


class StrainCurvesView(QWidget):
    """Vendor-style strain curves — analysed view panels stacked vertically."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(10)

        # Panels: only the views that exist are populated; the rest show the
        # clean «нет данных» placeholder (single-view analysis = only A4C).
        self._panel_a4c = SegmentCurvePanel("A4C")
        self._panel_a2c = SegmentCurvePanel("A2C")
        self._panel_dao = SegmentCurvePanel(tr("strain.view_dao"))

        layout.addWidget(self._panel_a4c, stretch=1)
        layout.addWidget(self._panel_a2c, stretch=1)
        layout.addWidget(self._panel_dao, stretch=1)

        # Which panels correspond to the currently analysed position. Only the
        # analysed view holds data; the others collapse to a clean placeholder.
        self._active_view: str = "A4C"
        self._visible_when_data: dict[str, SegmentCurvePanel] = {
            "A4C": self._panel_a4c,
            "A2C": self._panel_a2c,
            "DAO": self._panel_dao,
        }
        # Before any result: show clean placeholders, not empty grids.
        for panel in self._visible_when_data.values():
            panel.clear()

    def set_active_view(self, view: str) -> None:
        """Mark which view the result belongs to (A4C/A2C/A3C)."""
        view = view.upper()
        if view not in ("A4C", "A2C", "A3C"):
            return
        self._active_view = "DAO" if view == "A3C" else view

    def set_strain_data(
        self,
        result: StrainResult,
        frame_time_ms: float = 33.3,
    ) -> None:
        """Update the panels with per-segment strain curves from the result."""
        has_model_curves = bool(getattr(result, "segment_curves", None))
        # ``per_kernel_longitudinal`` was only needed because the view used to
        # re-derive the curves itself; with model curves present it is not
        # required any more (single source of truth, issue #C3).
        if result.segment_strain is None or (not has_model_curves and result.per_kernel_longitudinal is None):
            self.clear()
            return

        n_frames = len(result.longitudinal) if result.longitudinal is not None else 0
        # Single source of truth (issue #C3): plot the segment curves the worker
        # computed with the model's strain definition. The local re-computation
        # below stays only as a fallback for results produced by older code
        # paths / tests that do not carry ``segment_curves``.
        if getattr(result, "segment_curves", None):
            segment_curves = {int(k): np.asarray(v, dtype=np.float64) for k, v in result.segment_curves.items()}
        else:
            segment_curves = self._segment_curves_from_tracking(result, n_frames)

        ecg = (
            result.ecg_trace_for_display
            if result.ecg_trace_for_display is not None and len(result.ecg_trace_for_display)
            else None
        )
        ecg_sample_rate: float | None = None
        if ecg is not None and result.ecg_waveform is not None and result.ecg_waveform.primary_lead is not None:
            ecg_sample_rate = float(result.ecg_waveform.primary_lead.sampling_frequency)

        def _gls_for(seg_ids: list[int]) -> float | None:
            values = [result.segment_strain[s] for s in seg_ids if s in (result.segment_strain or {})]
            return float(np.mean(values)) if values else None

        # Vendor look: the analysed view gets the whole height; the other
        # panels hide instead of leaving half-empty placeholder stacks.
        for panel in self._visible_when_data.values():
            panel.show()
        analysed = self._visible_when_data.get(self._active_view, self._panel_a4c)
        seg_ids = VIEW_SEGMENTS.get(self._active_view, VIEW_SEGMENTS["A4C"])
        active_curves = {k: v for k, v in segment_curves.items() if k in seg_ids}
        self._update_panel(
            analysed,
            _gls_for(seg_ids),
            active_curves,
            result,
            frame_time_ms,
            ecg,
            ecg_sample_rate,
        )
        for panel in self._visible_when_data.values():
            if panel is not analysed:
                panel.clear()
                panel.set_gls(None)
                panel.set_ecg_visible(False)
                panel.hide()

    @staticmethod
    def _segment_curves_from_tracking(
        result: StrainResult,
        n_frames: int,
    ) -> dict[int, np.ndarray]:
        """Mean per-segment longitudinal curve from the tracked kernels.

        Kernels of one AHA segment are connected in arc order and the relative
        arc-length change is integrated frame by frame (Green–Lagrange
        longitudinal strain of the segment).
        """
        if result.tracked_positions_all is None or n_frames == 0:
            return {}

        segment_kernels: dict[int, list[int]] = {}
        for i, kernel in enumerate(result.kernels):
            if kernel.layer == "endo" and kernel.aha_segment > 0:
                segment_kernels.setdefault(kernel.aha_segment, []).append(i)

        # Reference ED positions for sorting kernels in arc order per segment
        ed = result.ed_index
        if not (0 <= ed < n_frames):
            return {}
        ed_pos = result.tracked_positions_all[ed]

        segment_curves: dict[int, np.ndarray] = {}
        all_endo = [i for i, k in enumerate(result.kernels) if k.layer == "endo" and k.aha_segment > 0]
        for seg_id, kernel_indices in segment_kernels.items():
            if len(kernel_indices) < 1:
                continue
            # Arc order, not raster order: sorting by (x, y) walked across the
            # cavity and measured the chord instead of the wall.
            arc_order = sorted(all_endo, key=lambda i: result.kernels[i].node_index)
            node_rank = {idx: rank for rank, idx in enumerate(arc_order)}
            if len(kernel_indices) == 1:
                # Single-kernel segment: connect it through its neighbours on
                # the whole endo arc so its strain is still well defined.
                pos = node_rank.get(kernel_indices[0], 0)
                pair = (arc_order[max(pos - 1, 0)], arc_order[min(pos + 1, len(arc_order) - 1)])
                if pair[0] == pair[1]:
                    continue
                kernel_indices = list(pair)
            else:
                kernel_indices = sorted(kernel_indices, key=lambda i: node_rank.get(i, 0))

            def _arc(idx_list: list[int], t: int) -> float:
                pts = result.tracked_positions_all[t][idx_list]
                if np.any(np.isnan(pts)):
                    return np.nan
                return float(np.sum(np.linalg.norm(np.diff(pts, axis=0), axis=1)))

            l0 = _arc(kernel_indices, ed)
            if l0 is None or not np.isfinite(l0) or l0 <= 1e-6:
                # Fall back to a global curve from the whole endo contour
                all_idx = arc_order
                l0 = _arc(all_idx, ed)
                kernel_indices = all_idx
            curve = np.zeros(n_frames)
            for t in range(n_frames):
                lt = _arc(kernel_indices, t)
                if np.isfinite(lt) and l0 > 1e-6:
                    curve[t] = 0.5 * ((lt / l0) ** 2 - 1.0) * 100.0
            segment_curves[seg_id] = curve
        return segment_curves

    def _update_panel(
        self,
        panel: SegmentCurvePanel,
        gls: float | None,
        curves: dict[int, np.ndarray],
        result: StrainResult,
        frame_time_ms: float,
        ecg: np.ndarray | None,
        ecg_sample_rate: float | None,
    ) -> None:
        panel.set_gls(gls)
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

    def clear(self) -> None:
        self._panel_a4c.clear()
        self._panel_a2c.clear()
        self._panel_dao.clear()
        for panel in (self._panel_a4c, self._panel_a2c, self._panel_dao):
            panel.show()

    def _generate_synthetic_ecg(self, n_frames: int, hr_bpm: float) -> np.ndarray:
        """Legacy helper (no longer used by the curves view).

        Real DICOM ECG is displayed when present; this generator is kept only
        so callers/tests that still reference it keep working. Nothing in the
        UI calls it — synthetic ECG is never drawn (issue #2).
        """
        if n_frames < 2 or hr_bpm <= 0:
            return np.zeros(max(n_frames, 100))
        frame_time_s = 33.3 / 1000.0
        hr_hz = hr_bpm / 60.0
        period_frames = max(int(1.0 / (hr_hz * frame_time_s)), 1)
        ecg = np.zeros(max(n_frames, 100))
        for i in range(len(ecg)):
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
        return ecg[: max(n_frames, 100)]
