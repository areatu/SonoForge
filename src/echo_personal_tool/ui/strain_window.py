"""Separate window for STE strain visualization — quad-view layout."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QSignalBlocker, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from scipy.interpolate import CubicSpline

from echo_personal_tool.infrastructure.i18n import tr

if TYPE_CHECKING:
    from echo_personal_tool.domain.models.speckle import StrainResult

from echo_personal_tool.domain.models.ste_analysis import StrainAnalysis, StrainStudy
from echo_personal_tool.domain.services.segment_map import (
    SEGMENT_NAMES,
    view_segment_ids,
)
from echo_personal_tool.ui.strain_curves_view import StrainCurvesView

logger = logging.getLogger(__name__)


def segment_name(segment_id: int) -> str:
    """Standard AHA name of a segment id (empty for unknown ids)."""
    return SEGMENT_NAMES.get(int(segment_id), f"Segment {segment_id}")

# Localised names of the six segments of the analysed view. The dict is keyed
# by the standard 18-segment AHA ids (issue #C2/#C11); ``strain.seg_<id>``
# covers all 18 so any view can be labelled.
AHA_SEGMENT_NAMES_RU: dict[int, str] = {seg: tr(f"strain.seg_{seg}") for seg in view_segment_ids("A4C")}


def _smooth_contour(points: np.ndarray, n_output: int = 64) -> np.ndarray:
    """Smooth contour using cubic spline interpolation."""
    if len(points) < 4:
        return points

    # Close the contour
    closed = np.vstack([points, points[:1]])

    # Parameterize by cumulative arc length
    diffs = np.diff(closed, axis=0)
    dists = np.linalg.norm(diffs, axis=1)
    t = np.zeros(len(closed))
    t[1:] = np.cumsum(dists)
    total_len = t[-1]

    if total_len < 1e-6:
        return points

    t_norm = t / total_len

    # Fit cubic spline
    try:
        cs_x = CubicSpline(t_norm, closed[:, 0], bc_type="periodic")
        cs_y = CubicSpline(t_norm, closed[:, 1], bc_type="periodic")
    except Exception:
        return points

    # Interpolate
    t_new = np.linspace(0, 1, n_output, endpoint=False)
    x_new = cs_x(t_new)
    y_new = cs_y(t_new)

    return np.column_stack([x_new, y_new])


class CinePanel(QWidget):
    """Single cine panel with image viewer, contour overlay, and info labels."""

    kernel_moved = Signal(int, float, float)  # kernel_index, new_x, new_y
    kernel_selected = Signal(int)  # kernel_index

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._title = title
        self.setObjectName("cinePanel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        # Title + info row
        header = QHBoxLayout()
        self._title_label = QLabel(title)
        self._title_label.setStyleSheet("font-weight: bold; color: #e0e0e0; font-size: 12px;")
        header.addWidget(self._title_label)

        self._info_label = QLabel("")
        self._info_label.setStyleSheet("color: #80cbc4; font-size: 11px;")
        self._info_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        header.addWidget(self._info_label)
        layout.addLayout(header)

        # PyQtGraph plot widget. Image coordinates (x=column, y=row, origin at
        # the top-left) are used for contours/kernels, so the view is inverted
        # like the main echo viewer.
        self._plot = pg.PlotWidget()
        self._plot.setBackground("black")
        self._plot.hideAxis("left")
        self._plot.hideAxis("bottom")
        self._plot.setAspectLocked(True)
        self._plot.setMouseEnabled(x=False, y=False)
        self._plot.setMinimumHeight(200)
        self._plot.getViewBox().invertY(True)

        # Real ultrasound frame under the overlays
        self._image_item = pg.ImageItem(axisOrder="row-major")
        self._image_item.setAutoDownsample(False)
        self._image_item.setOpts(smooth=True)
        self._image_item.setZValue(0)
        self._image_item.hide()
        self._plot.addItem(self._image_item)
        self._frames: np.ndarray | None = None

        layout.addWidget(self._plot, stretch=2)

        # Frame scrubber (enabled when cine frames are supplied)
        self._frame_slider = QSlider(Qt.Orientation.Horizontal)
        self._frame_slider.setRange(0, 0)
        self._frame_slider.setEnabled(False)
        self._frame_slider.valueChanged.connect(self._on_frame_slider)
        layout.addWidget(self._frame_slider)

        # ECG trace area
        self._ecg_plot = pg.PlotWidget()
        self._ecg_plot.setBackground("black")
        self._ecg_plot.hideAxis("left")
        self._ecg_plot.hideAxis("bottom")
        self._ecg_plot.setMaximumHeight(60)
        self._ecg_plot.setMinimumHeight(40)
        layout.addWidget(self._ecg_plot, stretch=0)

        # Bottom row: play + HR + frame counter
        footer = QHBoxLayout()
        self._play_btn = QPushButton(tr("strain.play"))
        self._play_btn.setFixedWidth(100)
        self._play_btn.setEnabled(False)
        self._play_btn.clicked.connect(self._toggle_play)
        footer.addWidget(self._play_btn)
        self._hr_label = QLabel("HR: --")
        self._hr_label.setStyleSheet("color: #4caf50; font-size: 10px;")
        footer.addWidget(self._hr_label)
        footer.addStretch()
        self._frame_label = QLabel("--/--")
        self._frame_label.setStyleSheet("color: #9e9e9e; font-size: 10px;")
        footer.addWidget(self._frame_label)
        layout.addLayout(footer)

        # Playback timer for contour/kernel animation
        self._play_timer = QTimer(self)
        self._play_timer.setInterval(100)
        self._play_timer.timeout.connect(self._on_play_tick)

        # Contour items
        self._ed_contour_item: pg.PlotDataItem | None = None
        self._es_contour_item: pg.PlotDataItem | None = None
        self._kernel_scatter: pg.ScatterPlotItem | None = None
        self._selected_kernel_item: pg.ScatterPlotItem | None = None
        self._segment_labels: list[pg.TextItem] = []
        self._ecg_item: pg.PlotDataItem | None = None
        self._ecg_marker: pg.InfiniteLine | None = None

        # Manual kernel editing state
        self._kernel_positions: np.ndarray | None = None
        self._selected_kernel_idx: int | None = None
        self._edit_mode: bool = False

        # Per-frame tracking overlay (animation)
        self._tracked_positions_all: np.ndarray | None = None
        self._kernel_layers: list[str] = []
        self._tracked_ed_index: int = 0
        self._tracked_es_index: int = 0
        self._anim_contour_item: pg.PlotDataItem | None = None
        self._anim_scatter: pg.ScatterPlotItem | None = None

        # ECG state
        self._ecg_data: np.ndarray | None = None
        self._ecg_time_ms: np.ndarray | None = None
        self._ecg_frame_time_ms: float = 33.3
        self._ecg_rpeak_items: list[pg.InfiniteLine] = []

        # Enable mouse events for kernel editing
        self._plot.scene().sigMouseClicked.connect(self._on_mouse_clicked)

    @property
    def plot(self) -> pg.PlotWidget:
        return self._plot

    def set_title_info(self, text: str) -> None:
        self._info_label.setText(text)

    def set_hr(self, hr: float) -> None:
        self._hr_label.setText(f"HR: {hr:.0f}")

    def set_frame(self, current: int, total: int) -> None:
        self._frame_label.setText(f"{current}/{total}")

    def set_frames(self, frames: np.ndarray | None, index: int = 0) -> None:
        """Set the cine frame buffer and show the frame at ``index``."""
        self._frames = frames
        if frames is None or frames.ndim < 3 or frames.shape[0] == 0:
            self._image_item.hide()
            self._frame_slider.setEnabled(False)
            self._frame_slider.setRange(0, 0)
            self._play_btn.setEnabled(False)
            self._stop_playback()
            return
        last = frames.shape[0] - 1
        self._frame_slider.setRange(0, last)
        self._frame_slider.setEnabled(True)
        self._play_btn.setEnabled(frames.shape[0] > 1)
        self._show_frame(int(np.clip(index, 0, last)))

    def _on_frame_slider(self, value: int) -> None:
        self._show_frame(int(value))

    def _show_frame(self, index: int) -> None:
        if self._frames is None or not (0 <= index < self._frames.shape[0]):
            return
        img = self._frames[index]
        self._image_item.setImage(np.ascontiguousarray(img), autoLevels=True)
        self._image_item.show()
        h, w = img.shape[:2]
        self._plot.setRange(xRange=(0, w), yRange=(0, h), padding=0.0)
        self.set_frame(index + 1, self._frames.shape[0])
        self._update_ecg_marker(index)
        self._render_tracked_frame(index)

    # ── Playback (contour/kernel animation) ────────────────────────────────

    def _toggle_play(self) -> None:
        if self._play_timer.isActive():
            self._stop_playback()
            return
        if self._frames is None or self._frames.shape[0] < 2:
            return
        if self._frame_slider.value() >= self._frame_slider.maximum():
            self._frame_slider.setValue(self._frame_slider.minimum())
        self._play_btn.setText(tr("strain.pause"))
        self._play_timer.start()

    def _on_play_tick(self) -> None:
        if self._frames is None:
            self._stop_playback()
            return
        nxt = self._frame_slider.value() + 1
        if nxt > self._frame_slider.maximum():
            nxt = self._frame_slider.minimum()
        self._frame_slider.setValue(nxt)

    def _stop_playback(self) -> None:
        self._play_timer.stop()
        self._play_btn.setText(tr("strain.play"))

    # ── Per-frame tracked overlay (animated kernels + live contour) ────────

    def set_tracked_overlay(
        self,
        positions_all: np.ndarray | None,
        layers: list[str] | None = None,
        ed_index: int = 0,
        es_index: int = 0,
    ) -> None:
        """Enable per-frame kernel/contour animation from the full-cine tracking."""
        self._tracked_positions_all = positions_all
        self._kernel_layers = layers or []
        self._tracked_ed_index = ed_index
        self._tracked_es_index = es_index
        if positions_all is not None and positions_all.ndim == 3:
            self._render_tracked_frame(self._frame_slider.value())

    def _render_tracked_frame(self, index: int) -> None:
        if self._tracked_positions_all is None or self._tracked_positions_all.ndim != 3:
            return
        pos = self._tracked_positions_all
        if index < 0 or index >= pos.shape[0]:
            return
        if self._anim_contour_item is not None:
            self._plot.removeItem(self._anim_contour_item)
            self._anim_contour_item = None
        if self._anim_scatter is not None:
            self._plot.removeItem(self._anim_scatter)
            self._anim_scatter = None

        frame_pos = pos[index]  # (K, 2)
        k = frame_pos.shape[0]
        layers = self._kernel_layers
        valid = ~(np.isnan(frame_pos[:, 0]) | np.isnan(frame_pos[:, 1]))
        if not valid.any():
            return

        # Live endo contour (thin yellow) through valid endo kernels
        endo_idx = [i for i in range(k) if i < len(layers) and layers[i] == "endo" and valid[i]]
        if len(endo_idx) >= 3:
            pts = frame_pos[endo_idx]
            smoothed = _smooth_contour(pts, n_output=64)
            x = np.append(smoothed[:, 0], smoothed[0, 0])
            y = np.append(smoothed[:, 1], smoothed[0, 1])
            self._anim_contour_item = pg.PlotDataItem(x, y, pen=pg.mkPen("#ffd54f", width=1))
            self._anim_contour_item.setZValue(6)
            self._plot.addItem(self._anim_contour_item)

        # Kernels colored by layer (green=endo, yellow=mid, blue=epi, red=lost)
        brushes = []
        for i in range(k):
            if not valid[i]:
                brushes.append(pg.mkBrush(255, 0, 0, 220))
            elif i < len(layers) and layers[i] == "endo":
                brushes.append(pg.mkBrush(76, 175, 80, 220))
            elif i < len(layers) and layers[i] == "epi":
                brushes.append(pg.mkBrush(66, 165, 245, 220))
            else:
                brushes.append(pg.mkBrush(255, 213, 79, 220))
        self._anim_scatter = pg.ScatterPlotItem(
            x=frame_pos[valid, 0],
            y=frame_pos[valid, 1],
            pen=None,
            brush=brushes,
            symbol="s",
            size=4,
        )
        self._anim_scatter.setZValue(10)
        self._plot.addItem(self._anim_scatter)

    # ── ECG strip ───────────────────────────────────────────────────────────

    def set_ecg_visible(self, visible: bool) -> None:
        """Show/hide the ECG trace row (hidden when the clip has no ECG)."""
        self._ecg_plot.setVisible(visible)

    def _update_ecg_marker(self, frame_index: int) -> None:
        if self._ecg_marker is None or self._ecg_frame_time_ms <= 0:
            return
        self._ecg_marker.setPos(float(frame_index) * self._ecg_frame_time_ms)

    def show_contour(self, points: np.ndarray, color: str = "#ff1744", smooth: bool = True) -> None:
        """Draw closed contour on the plot with optional cubic spline smoothing."""
        # Remove old ED contour
        if self._ed_contour_item is not None:
            self._plot.removeItem(self._ed_contour_item)
            self._ed_contour_item = None

        if len(points) < 3:
            return

        if smooth:
            pts = _smooth_contour(points, n_output=64)
        else:
            pts = points

        x = np.append(pts[:, 0], pts[0, 0])
        y = np.append(pts[:, 1], pts[0, 1])
        pen = pg.mkPen(color, width=3)
        self._ed_contour_item = pg.PlotDataItem(x, y, pen=pen)
        self._ed_contour_item.setZValue(5)
        self._plot.addItem(self._ed_contour_item)

    def show_es_contour(self, points: np.ndarray, color: str = "#00e676", smooth: bool = True) -> None:
        """Draw ES contour (green) on the plot."""
        if self._es_contour_item is not None:
            self._plot.removeItem(self._es_contour_item)
            self._es_contour_item = None

        if points is None or len(points) < 3:
            return

        if smooth:
            pts = _smooth_contour(points, n_output=64)
        else:
            pts = points

        x = np.append(pts[:, 0], pts[0, 0])
        y = np.append(pts[:, 1], pts[0, 1])
        pen = pg.mkPen(color, width=2, style=Qt.PenStyle.DashLine)
        self._es_contour_item = pg.PlotDataItem(x, y, pen=pen)
        self._es_contour_item.setZValue(4)
        self._plot.addItem(self._es_contour_item)

    def show_kernels(
        self,
        positions: np.ndarray,
        ncc_scores: np.ndarray | None = None,
        valid_mask: np.ndarray | None = None,
    ) -> None:
        """Draw tracking kernels as squares, colored by quality."""
        if self._kernel_scatter is not None:
            self._plot.removeItem(self._kernel_scatter)

        if len(positions) == 0:
            return

        x = positions[:, 0]
        y = positions[:, 1]

        if ncc_scores is not None and valid_mask is not None:
            colors = []
            for i in range(len(positions)):
                score = float(ncc_scores[i]) if i < len(ncc_scores) else 0.0
                is_valid = valid_mask[i] if i < len(valid_mask) else False
                if not is_valid or score < 0.3:
                    colors.append(pg.mkBrush(255, 0, 0, 200))  # red = rejected
                elif score < 0.5:
                    colors.append(pg.mkBrush(255, 193, 7, 200))  # yellow = low
                else:
                    colors.append(pg.mkBrush(255, 255, 255, 200))  # white = good
            self._kernel_scatter = pg.ScatterPlotItem(x=x, y=y, pen=None, brush=colors, symbol="s", size=6)
        else:
            self._kernel_scatter = pg.ScatterPlotItem(
                x=x, y=y, pen=pg.mkPen("w", width=0.5), brush=pg.mkBrush(255, 255, 255, 180), symbol="s", size=6
            )

        self._kernel_scatter.setZValue(10)
        self._plot.addItem(self._kernel_scatter)

        # Store positions for mouse interaction
        self._kernel_positions = positions.copy()

    def set_edit_mode(self, enabled: bool) -> None:
        """Enable/disable manual kernel editing mode."""
        self._edit_mode = enabled
        if not enabled:
            self._deselect_kernel()

    def _on_mouse_clicked(self, event) -> None:
        """Handle mouse click for kernel selection."""
        if not self._edit_mode or self._kernel_positions is None:
            return

        # Get click position in plot coordinates
        pos = event.scenePos()
        view_box = self._plot.getViewBox()
        if view_box is None:
            return

        # Convert to plot coordinates
        point = self._plot.mapToScene(pos)
        # Use ViewBox.mapSceneToView for accurate coordinates
        mouse_point = view_box.mapSceneToView(pos)
        click_x = mouse_point.x()
        click_y = mouse_point.y()

        # Find nearest kernel
        if len(self._kernel_positions) == 0:
            return

        distances = np.sqrt(
            (self._kernel_positions[:, 0] - click_x) ** 2 + (self._kernel_positions[:, 1] - click_y) ** 2
        )
        min_idx = np.argmin(distances)
        min_dist = distances[min_idx]

        # Select if within threshold (15 pixels)
        if min_dist < 15:
            self._select_kernel(min_idx)
        else:
            self._deselect_kernel()

    def _select_kernel(self, idx: int) -> None:
        """Highlight selected kernel."""
        self._selected_kernel_idx = idx

        # Remove old selection highlight
        if self._selected_kernel_item is not None:
            self._plot.removeItem(self._selected_kernel_item)

        # Draw yellow highlight around selected kernel
        if self._kernel_positions is not None and idx < len(self._kernel_positions):
            x = [self._kernel_positions[idx, 0]]
            y = [self._kernel_positions[idx, 1]]
            self._selected_kernel_item = pg.ScatterPlotItem(
                x=x, y=y, pen=pg.mkPen("#ffd54f", width=2), brush=pg.mkBrush(255, 213, 79, 150), symbol="o", size=16
            )
            self._selected_kernel_item.setZValue(15)
            self._plot.addItem(self._selected_kernel_item)

        self.kernel_selected.emit(idx)

    def _deselect_kernel(self) -> None:
        """Clear kernel selection."""
        self._selected_kernel_idx = None
        if self._selected_kernel_item is not None:
            self._plot.removeItem(self._selected_kernel_item)
            self._selected_kernel_item = None

    def move_selected_kernel(self, new_x: float, new_y: float) -> None:
        """Move the selected kernel to a new position."""
        if self._selected_kernel_idx is None or self._kernel_positions is None:
            return

        idx = self._selected_kernel_idx
        if idx >= len(self._kernel_positions):
            return

        # Update position
        old_x, old_y = self._kernel_positions[idx]
        self._kernel_positions[idx, 0] = new_x
        self._kernel_positions[idx, 1] = new_y

        # Update visual
        self._select_kernel(idx)

        # Emit signal
        self.kernel_moved.emit(idx, new_x, new_y)

    def show_segment_labels(
        self,
        kernels: list,
        positions: np.ndarray,
    ) -> None:
        """Draw segment name labels near kernel clusters (Russian names)."""
        # Clear old labels
        for item in self._segment_labels:
            self._plot.removeItem(item)
        self._segment_labels.clear()

        if len(positions) == 0 or len(kernels) == 0:
            return

        # Group positions by segment
        segment_positions: dict[int, list[int]] = {}
        for i, kernel in enumerate(kernels):
            seg = kernel.aha_segment
            if seg > 0 and i < len(positions):
                segment_positions.setdefault(seg, []).append(i)

        for seg, indices in segment_positions.items():
            label_text = AHA_SEGMENT_NAMES_RU.get(seg, f"Seg{seg}")
            pts = positions[indices]
            centroid = pts.mean(axis=0)

            text_item = pg.TextItem(
                label_text,
                color=(200, 200, 200),
                anchor=(0.5, 0.5),
            )
            text_item.setPos(centroid[0], centroid[1])
            text_item.setFont(QFont("sans-serif", 8))
            text_item.setZValue(20)
            self._plot.addItem(text_item)
            self._segment_labels.append(text_item)

    def show_ecg_trace(
        self,
        ecg_data: np.ndarray | None,
        frame_time_ms: float = 33.3,
        current_frame: int = 0,
        *,
        ecg_sample_rate: float | None = None,
        r_peak_times_ms: np.ndarray | None = None,
        ed_frame: int | None = None,
        es_frame: int | None = None,
    ) -> None:
        """Display ECG trace with frame marker, R-peaks and ED/ES markers.

        Only real ECG data should be passed (never a synthetic one); callers
        hide the strip via :meth:`set_ecg_visible` when no ECG is available.
        """
        if self._ecg_item is not None:
            self._ecg_plot.removeItem(self._ecg_item)
            self._ecg_item = None
        if self._ecg_marker is not None:
            self._ecg_plot.removeItem(self._ecg_marker)
            self._ecg_marker = None
        for item in self._ecg_rpeak_items:
            self._ecg_plot.removeItem(item)
        self._ecg_rpeak_items.clear()
        for item in getattr(self, "_ecg_phase_items", []):
            self._ecg_plot.removeItem(item)
        self._ecg_phase_items = []

        if ecg_data is None or len(ecg_data) == 0:
            self._ecg_data = None
            self._ecg_time_ms = None
            return

        n = len(ecg_data)
        if ecg_sample_rate and ecg_sample_rate > 0:
            t = np.arange(n) / ecg_sample_rate * 1000.0
        else:
            t = np.arange(n) * frame_time_ms
        self._ecg_data = ecg_data
        self._ecg_time_ms = t
        self._ecg_frame_time_ms = max(float(frame_time_ms), 0.001)

        pen = pg.mkPen("#4caf50", width=1)
        self._ecg_item = pg.PlotDataItem(t, ecg_data, pen=pen)
        self._ecg_plot.addItem(self._ecg_item)

        # R-peak markers (real QRS phases)
        if r_peak_times_ms is not None:
            for rt in r_peak_times_ms:
                line = pg.InfiniteLine(
                    pos=float(rt),
                    angle=90,
                    pen=pg.mkPen("#ff6f00", width=1, style=Qt.PenStyle.DotLine),
                )
                line.setZValue(15)
                self._ecg_plot.addItem(line)
                self._ecg_rpeak_items.append(line)

        # ED (green) / ES (yellow) phase markers
        self._ecg_phase_items = []
        if ed_frame is not None:
            line = pg.InfiniteLine(
                pos=ed_frame * self._ecg_frame_time_ms,
                angle=90,
                pen=pg.mkPen("#00e676", width=1, style=Qt.PenStyle.DashLine),
            )
            self._ecg_plot.addItem(line)
            self._ecg_phase_items.append(line)
        if es_frame is not None:
            line = pg.InfiniteLine(
                pos=es_frame * self._ecg_frame_time_ms,
                angle=90,
                pen=pg.mkPen("#ffd54f", width=1, style=Qt.PenStyle.DashLine),
            )
            self._ecg_plot.addItem(line)
            self._ecg_phase_items.append(line)

        # Frame marker (moves with playback)
        marker_x = current_frame * self._ecg_frame_time_ms
        self._ecg_marker = pg.InfiniteLine(
            pos=marker_x, angle=90, pen=pg.mkPen("#ff1744", width=1, style=Qt.PenStyle.DashLine)
        )
        self._ecg_plot.addItem(self._ecg_marker)

        self._ecg_plot.setXRange(0, t[-1] if len(t) > 0 else 1000)

    def clear(self) -> None:
        self._stop_playback()
        if self._ed_contour_item is not None:
            self._plot.removeItem(self._ed_contour_item)
            self._ed_contour_item = None
        if self._es_contour_item is not None:
            self._plot.removeItem(self._es_contour_item)
            self._es_contour_item = None
        if self._kernel_scatter is not None:
            self._plot.removeItem(self._kernel_scatter)
            self._kernel_scatter = None
        if self._anim_contour_item is not None:
            self._plot.removeItem(self._anim_contour_item)
            self._anim_contour_item = None
        if self._anim_scatter is not None:
            self._plot.removeItem(self._anim_scatter)
            self._anim_scatter = None
        self._tracked_positions_all = None
        for item in self._segment_labels:
            self._plot.removeItem(item)
        self._segment_labels.clear()
        if self._ecg_item is not None:
            self._ecg_plot.removeItem(self._ecg_item)
            self._ecg_item = None
        if self._ecg_marker is not None:
            self._ecg_plot.removeItem(self._ecg_marker)
            self._ecg_marker = None
        for item in self._ecg_rpeak_items:
            self._ecg_plot.removeItem(item)
        self._ecg_rpeak_items.clear()
        for item in getattr(self, "_ecg_phase_items", []):
            self._ecg_plot.removeItem(item)
        self._ecg_phase_items = []
        self._ecg_data = None
        self._ecg_time_ms = None
        self._info_label.setText("")
        self._hr_label.setText("HR: --")
        self._frame_label.setText("--/--")


class BullseyeWidget(QWidget):
    """Standard 18-segment AHA bull's-eye with colour-coded strain values.

    Geometry follows the standard AHA layout (issue #C11): each ring is drawn
    clockwise starting at the anterior wall (12 o'clock), so the segment ids
    the worker assigns appear at their anatomical positions:

    * basal 1, 6, 5, 4, 3, 2 — anterior, anterolateral, inferolateral,
      inferior, inferoseptal, anteroseptal;
    * mid 7, 12, 11, 10, 9, 8;
    * apical 13, 18, 17, 16, 15, 14.

    The 18-segment model has no separate apex segment, so the centre cap is
    drawn as an unlabelled "not measured" region instead of inventing a value
    for it (the old map showed segment 15 as *basal* septal, which put real
    numbers on the wrong wall).
    """

    # (ring, angle_index) -> segment_id. Rings: 0=apex cap, 1=apical, 2=mid, 3=basal
    SEGMENT_GEOMETRY: dict[int, tuple[int, int]] = {
        # Apical ring (6 segments, clockwise from anterior)
        13: (1, 0),
        18: (1, 1),
        17: (1, 2),
        16: (1, 3),
        15: (1, 4),
        14: (1, 5),
        # Mid ring
        7: (2, 0),
        12: (2, 1),
        11: (2, 2),
        10: (2, 3),
        9: (2, 4),
        8: (2, 5),
        # Basal ring
        1: (3, 0),
        6: (3, 1),
        5: (3, 2),
        4: (3, 3),
        3: (3, 4),
        2: (3, 5),
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(250)
        self.setMinimumWidth(250)

        self._segment_items: dict[int, pg.PlotDataItem] = {}
        self._label_items: dict[int, pg.TextItem] = {}
        self._value_items: dict[int, pg.TextItem] = {}
        self._colorbar_item: pg.PlotDataItem | None = None

        # Default: all segments white (no data)
        self._segment_strains: dict[int, float] = {}
        self._segment_quality: dict[int, float] = {}
        self._segment_ttp: dict[int, float] = {}
        self._ttp_mode = False

    def paintEvent(self, event) -> None:
        """Custom paint using QPainter for filled segments."""
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        r_max = min(w, h) * 0.42

        # Ring radii
        r_apex = r_max * 0.15
        r_apical = r_max * 0.38
        r_mid = r_max * 0.68
        r_basal = r_max * 1.0

        ring_radii = [r_apex, r_apical, r_mid, r_basal]

        # Draw filled segments (strain or time-to-peak, whichever was selected)
        ttp_mode = bool(getattr(self, "_ttp_mode", False))
        values = self._segment_ttp if ttp_mode else self._segment_strains
        for seg_id, (ring, angle_idx) in self.SEGMENT_GEOMETRY.items():
            strain = values.get(seg_id, None)

            # Check if segment is accepted by QC
            is_accepted = True
            if hasattr(self, "_qc_accepted_segments") and self._qc_accepted_segments is not None:
                is_accepted = seg_id in self._qc_accepted_segments

            if strain is None:
                # No data for this segment: hatched/dark instead of a plausible
                # looking colour (issue #C11 — never colour a segment that was
                # not measured).
                color = QColor(40, 40, 40)
            elif not is_accepted:
                color = QColor(60, 60, 60)  # rejected by QC
            elif ttp_mode:
                color = self._ttp_to_color(strain)
            else:
                color = self._strain_to_color(strain)

            # Calculate polygon
            if ring == 0:
                # Apex cap: the 18-segment model has no apex segment, so the
                # centre is always drawn as "not measured".
                color = QColor(30, 30, 30)
                polygon = QPolygonF()
                for a in range(360):
                    rad = np.radians(a)
                    polygon.append(QPointF(cx + r_apex * np.cos(rad), cy + r_apex * np.sin(rad)))
            else:
                # Other rings: arc segments
                n_segments = 6
                angle_span = 360 / n_segments
                # Offset: segments start from 12 o'clock, rotate -90 degrees
                start_angle = -90 + angle_idx * angle_span
                end_angle = start_angle + angle_span

                inner_r = ring_radii[ring - 1]
                outer_r = ring_radii[ring]

                polygon = QPolygonF()
                # Outer arc
                for a in range(int(start_angle), int(end_angle) + 1):
                    rad = np.radians(a)
                    polygon.append(QPointF(cx + outer_r * np.cos(rad), cy + outer_r * np.sin(rad)))
                # Inner arc (reversed)
                for a in range(int(end_angle), int(start_angle) - 1, -1):
                    rad = np.radians(a)
                    polygon.append(QPointF(cx + inner_r * np.cos(rad), cy + inner_r * np.sin(rad)))

            painter.setPen(QPen(QColor(80, 80, 80), 1))
            painter.setBrush(color)
            painter.drawPolygon(polygon)

        # Draw segment labels and values
        painter.setPen(QPen(QColor(220, 220, 220), 1))
        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)

        for seg_id, (ring, angle_idx) in self.SEGMENT_GEOMETRY.items():
            # Calculate label position (centroid of segment)
            n_segments_ring = 6
            angle_span = 360 / n_segments_ring
            mid_angle = np.radians(-90 + angle_idx * angle_span + angle_span / 2)

            if ring == 0:
                label_r = r_apex * 0.5
            else:
                inner_r = ring_radii[ring - 1]
                outer_r = ring_radii[ring]
                label_r = (inner_r + outer_r) / 2

            lx = cx + label_r * np.cos(mid_angle)
            ly = cy + label_r * np.sin(mid_angle)

            # Draw segment value (ms for the TTP map, % for strain)
            strain = self._segment_ttp.get(seg_id) if ttp_mode else self._segment_strains.get(seg_id)
            if strain is not None:
                painter.setPen(QPen(QColor(255, 255, 255), 1))
                text = f"{strain:.0f}" if ttp_mode else f"{strain:.1f}"
                painter.drawText(QPointF(lx - 15, ly + 4), text)

        # Draw outer labels (segment names)
        font.setPointSize(9)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QPen(QColor(180, 180, 180), 1))

        # Clockwise from the anterior wall, matching SEGMENT_GEOMETRY.
        outer_labels = {
            0: tr("strain.lbl_anterior"),
            1: tr("strain.lbl_lateral"),
            2: tr("strain.lbl_inferior_lateral"),
            3: tr("strain.lbl_inferior"),
            4: tr("strain.lbl_septal_inferior"),
            5: tr("strain.lbl_septal"),
        }
        for i, label in outer_labels.items():
            angle = np.radians(-90 + i * 60 + 30)
            lx = cx + (r_basal + 18) * np.cos(angle)
            ly = cy + (r_basal + 18) * np.sin(angle)
            painter.drawText(QPointF(lx - 10, ly + 4), label)

        # Draw concentric circles
        painter.setPen(QPen(QColor(100, 100, 100), 1))
        for r in ring_radii:
            painter.drawEllipse(QPointF(cx, cy), r, r)

        # Draw radial lines
        for angle_deg in range(0, 360, 60):
            rad = np.radians(angle_deg - 90)
            painter.drawLine(
                QPointF(cx + r_apex * np.cos(rad), cy + r_apex * np.sin(rad)),
                QPointF(cx + r_basal * np.cos(rad), cy + r_basal * np.sin(rad)),
            )

        # Draw center dot
        painter.setPen(QPen(QColor(100, 100, 100), 1))
        painter.setBrush(QColor(60, 60, 60))
        painter.drawEllipse(QPointF(cx, cy), 4, 4)

        painter.end()

    # GE/EchoPAC bull's-eye ramp: bright red = normal (|ε| > 16 %), then light
    # red, pink, pale pink; positive strain is blue (user-chosen palette).
    # (value_threshold, RGB) from the most negative end upwards.
    STRAIN_RAMP: tuple[tuple[float, tuple[int, int, int]], ...] = (
        (-16.0, (214, 24, 24)),  # normal — bright red
        (-11.0, (238, 106, 106)),  # light red
        (-6.0, (247, 176, 186)),  # light pink
        (0.0, (252, 224, 228)),  # pale pink — borderline/zero
        (float("inf"), (66, 133, 244)),  # any positive strain — blue
    )

    # Time-to-peak ramp (blue → yellow → red): late activation is red, which is
    # the vendor convention for the TTP bull's-eye.
    TTP_RAMP: tuple[tuple[float, tuple[int, int, int]], ...] = (
        (0.0, (38, 96, 214)),
        (200.0, (58, 190, 220)),
        (330.0, (255, 214, 64)),
        (430.0, (240, 120, 30)),
        (float("inf"), (206, 40, 40)),
    )

    @staticmethod
    def _ramp_color(value: float, ramp: tuple[tuple[float, tuple[int, int, int]], ...]) -> QColor:
        from PySide6.QtGui import QColor

        for threshold, color in ramp:
            if value <= threshold:
                return QColor(*color)
        return QColor(*ramp[-1][1])

    def _strain_to_color(self, strain: float) -> QColor:
        """Map strain value to colour with the clinical bull's-eye palette."""
        return self._ramp_color(float(strain), self.STRAIN_RAMP)

    def _ttp_to_color(self, ttp_ms: float) -> QColor:
        """Map a time-to-peak value (ms from ED) to the TTP palette."""
        return self._ramp_color(float(ttp_ms), self.TTP_RAMP)

    def update_data(
        self,
        segment_strain: dict[int, float],
        segment_quality: dict[int, float] | None = None,
        segment_ttp_ms: dict[int, float] | None = None,
    ) -> None:
        """Update bull's eye with strain data (and the TTP map when supplied)."""
        self._segment_strains = segment_strain.copy()
        self._segment_quality = (segment_quality or {}).copy()
        self._segment_ttp = {int(k): float(v) for k, v in (segment_ttp_ms or {}).items()}
        self._qc_accepted_segments: set[int] | None = None
        self.update()  # Trigger repaint

    def set_ttp_mode(self, enabled: bool) -> None:
        """Switch the bull's-eye between strain and time-to-peak colourization."""
        self._ttp_mode = bool(enabled)
        self.update()

    def update_qc(
        self,
        segment_strain: dict[int, float],
        segment_quality: dict[int, float] | None,
        accepted_segments: set[int],
    ) -> None:
        """Update bull's eye with quality control information."""
        self._segment_strains = segment_strain.copy()
        self._segment_quality = (segment_quality or {}).copy()
        self._qc_accepted_segments = accepted_segments.copy()
        self.update()  # Trigger repaint

    def clear(self) -> None:
        self._segment_strains.clear()
        self._segment_quality.clear()
        self._segment_ttp.clear()
        self.update()


class SummaryTable(QWidget):
    """Summary metrics table — Clinical-style layout with 9 rows."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(240)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        title = QLabel(tr("strain.summary_table"))
        title.setStyleSheet("font-weight: bold; color: #e0e0e0; font-size: 12px;")
        layout.addWidget(title)

        self._rows: dict[str, tuple[QLabel, QLabel, str]] = {}
        row_defs = [
            ("gls", tr("strain.gls_global"), "%"),
            ("ess", tr("strain.ess"), "%"),
            ("ttp", tr("strain.ttp"), tr("strain.unit_ms")),
            ("psi", tr("strain.psi"), "%"),
            ("drift", tr("strain.drift"), "%"),
            ("gls_a4c", tr("strain.gls_a4c"), "%"),
            ("gls_a2c", tr("strain.gls_a2c"), "%"),
            ("gls_dao", tr("strain.gls_dao"), "%"),
            ("gls_av", tr("strain.gls_av"), "%"),
            ("ef", tr("strain.ef"), "%"),
            ("edv", tr("strain.edv"), tr("strain.unit_ml")),
            ("esv", tr("strain.esv"), tr("strain.unit_ml")),
            ("autozak", tr("strain.autozak"), tr("strain.unit_ms")),
            ("hr", tr("strain.hr"), "bpm"),
        ]
        for key, label_text, unit in row_defs:
            row = QHBoxLayout()
            lbl = QLabel(label_text)
            lbl.setStyleSheet("color: #bdbdbd; font-size: 11px;")
            val = QLabel("--")
            val.setStyleSheet("color: #ffd54f; font-weight: bold; font-size: 11px;")
            val.setAlignment(Qt.AlignmentFlag.AlignRight)
            val.setMinimumWidth(60)
            row.addWidget(lbl)
            row.addStretch()
            row.addWidget(val)
            layout.addLayout(row)
            self._rows[key] = (lbl, val, unit)

        layout.addStretch()

    def update_values(self, **kwargs: float | str | None) -> None:
        """Update table values. Accepts: gls, gls_a4c, gls_a2c, gls_dao, ef, edv, esv, autozak, hr."""
        for key, val in kwargs.items():
            if key in self._rows:
                _, val_label, unit = self._rows[key]
                if val is None:
                    val_label.setText("--")
                elif isinstance(val, str):
                    val_label.setText(val)
                elif unit == "%":
                    val_label.setText(f"{val:.1f}%")
                elif unit == tr("strain.unit_ml"):
                    val_label.setText(f"{val:.1f} {tr('strain.unit_ml')}")
                elif unit == tr("strain.unit_ms"):
                    val_label.setText(f"{val:.0f} {tr('strain.unit_ms')}")
                elif unit == "bpm":
                    val_label.setText(f"{val:.0f} bpm")
                else:
                    val_label.setText(f"{val:.1f}")


class ControlPanel(QWidget):
    """Left-side control panel for Strain Window."""

    view_toggled = Signal(str, bool)  # view_name, checked
    display_mode_changed = Signal(str)  # "contour", "curves", "sr", "peak"
    strain_metric_changed = Signal(str)  # "deformation", "strain_rate", "peak"
    qc_segment_toggled = Signal(int, bool)  # segment_id, accepted
    position_selected = Signal(str)  # "A4C" | "A2C" | "A3C"
    ttp_mode_toggled = Signal(bool)  # bull's-eye: strain vs time-to-peak

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(180)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        # View mode (contour vs curves)
        group_view_mode = QGroupBox(tr("strain.view_mode"))
        group_view_mode.setStyleSheet("QGroupBox { font-weight: bold; color: #e0e0e0; }")
        view_mode_layout = QVBoxLayout()

        self._mode_contour = QRadioButton(tr("strain.mode_cine_contour"))
        self._mode_contour.setChecked(True)
        self._mode_contour.setStyleSheet("color: #e0e0e0;")
        self._mode_contour.toggled.connect(lambda c: self.display_mode_changed.emit("contour") if c else None)
        view_mode_layout.addWidget(self._mode_contour)

        self._mode_curves = QRadioButton(tr("strain.mode_curves"))
        self._mode_curves.setStyleSheet("color: #e0e0e0;")
        self._mode_curves.toggled.connect(lambda c: self.display_mode_changed.emit("curves") if c else None)
        view_mode_layout.addWidget(self._mode_curves)

        group_view_mode.setLayout(view_mode_layout)
        layout.addWidget(group_view_mode)

        # Strain metric (Clinical-style: Deformation / SR / Peak)
        group_metric = QGroupBox(tr("strain.metric"))
        group_metric.setStyleSheet("QGroupBox { font-weight: bold; color: #e0e0e0; }")
        metric_layout = QVBoxLayout()

        self._metric_deformation = QRadioButton(tr("strain.metric_deformation"))
        self._metric_deformation.setChecked(True)
        self._metric_deformation.setStyleSheet("color: #e0e0e0;")
        self._metric_deformation.toggled.connect(
            lambda c: self.strain_metric_changed.emit("deformation") if c else None
        )
        metric_layout.addWidget(self._metric_deformation)

        self._metric_sr = QRadioButton(tr("strain.metric_sr"))
        self._metric_sr.setStyleSheet("color: #e0e0e0;")
        self._metric_sr.toggled.connect(lambda c: self.strain_metric_changed.emit("strain_rate") if c else None)
        metric_layout.addWidget(self._metric_sr)

        self._metric_peak = QRadioButton(tr("strain.metric_peak"))
        self._metric_peak.setStyleSheet("color: #e0e0e0;")
        self._metric_peak.toggled.connect(lambda c: self.strain_metric_changed.emit("peak") if c else None)
        metric_layout.addWidget(self._metric_peak)

        group_metric.setLayout(metric_layout)
        layout.addWidget(group_metric)

        # View toggles
        group_views = QGroupBox("Views")
        group_views.setStyleSheet("QGroupBox { font-weight: bold; color: #e0e0e0; }")
        views_layout = QVBoxLayout()

        self._cb_a4c = QCheckBox("A4C")
        self._cb_a4c.setChecked(True)
        self._cb_a4c.setStyleSheet("color: #e0e0e0;")
        self._cb_a4c.toggled.connect(lambda c: self.view_toggled.emit("A4C", c))
        views_layout.addWidget(self._cb_a4c)

        self._cb_a2c = QCheckBox("A2C")
        self._cb_a2c.setChecked(True)
        self._cb_a2c.setStyleSheet("color: #e0e0e0;")
        self._cb_a2c.toggled.connect(lambda c: self.view_toggled.emit("A2C", c))
        views_layout.addWidget(self._cb_a2c)

        self._cb_dao = QCheckBox("DAO (A3C)")
        self._cb_dao.setChecked(True)
        self._cb_dao.setStyleSheet("color: #e0e0e0;")
        self._cb_dao.toggled.connect(lambda c: self.view_toggled.emit("DAO", c))
        views_layout.addWidget(self._cb_dao)

        group_views.setLayout(views_layout)
        layout.addWidget(group_views)

        # Position (view) selection — which clip the contours came from
        group_position = QGroupBox(tr("strain.position"))
        group_position.setStyleSheet("QGroupBox { font-weight: bold; color: #e0e0e0; }")
        position_layout = QVBoxLayout()

        self._pos_a4c = QRadioButton("A4C")
        self._pos_a4c.setChecked(True)
        self._pos_a4c.setStyleSheet("color: #e0e0e0;")
        self._pos_a4c.toggled.connect(lambda c: self.position_selected.emit("A4C") if c else None)
        position_layout.addWidget(self._pos_a4c)

        self._pos_a2c = QRadioButton("A2C")
        self._pos_a2c.setStyleSheet("color: #e0e0e0;")
        self._pos_a2c.toggled.connect(lambda c: self.position_selected.emit("A2C") if c else None)
        position_layout.addWidget(self._pos_a2c)

        self._pos_a3c = QRadioButton(tr("strain.position_a3c"))
        self._pos_a3c.setStyleSheet("color: #e0e0e0;")
        self._pos_a3c.toggled.connect(lambda c: self.position_selected.emit("A3C") if c else None)
        # Bull's-eye mode: strain (default) or time-to-peak map.
        self._cb_ttp = QCheckBox(tr("strain.bullseye_ttp"))
        self._cb_ttp.setToolTip(tr("strain.bullseye_ttp_hint"))
        self._cb_ttp.toggled.connect(self.ttp_mode_toggled.emit)
        position_layout.addWidget(self._pos_a3c)
        position_layout.addWidget(self._cb_ttp)

        group_position.setLayout(position_layout)
        layout.addWidget(group_position)

        # Quality info
        group_quality = QGroupBox("Quality Gate")
        group_quality.setStyleSheet("QGroupBox { font-weight: bold; color: #e0e0e0; }")
        quality_layout = QVBoxLayout()

        self._quality_label = QLabel("-- / --")
        self._quality_label.setStyleSheet("color: #80cbc4; font-size: 11px;")
        quality_layout.addWidget(self._quality_label)

        self._rejected_label = QLabel("")
        self._rejected_label.setStyleSheet("color: #ff9800; font-size: 10px;")
        self._rejected_label.setWordWrap(True)
        quality_layout.addWidget(self._rejected_label)

        group_quality.setLayout(quality_layout)
        layout.addWidget(group_quality)

        # Quality Control (per-segment checkboxes)
        self._qc_group = QGroupBox("Quality Control")
        self._qc_group.setStyleSheet("QGroupBox { font-weight: bold; color: #e0e0e0; }")
        self._qc_layout = QVBoxLayout()
        self._qc_layout.setSpacing(2)

        self._qc_checkboxes: dict[int, QCheckBox] = {}
        # Will be populated when results arrive
        self._qc_placeholder = QLabel(tr("strain.load_results"))
        self._qc_placeholder.setStyleSheet("color: #9e9e9e; font-size: 10px;")
        self._qc_layout.addWidget(self._qc_placeholder)

        self._qc_group.setLayout(self._qc_layout)

        # Wrap in scroll area for many checkboxes
        qc_scroll = QScrollArea()
        qc_scroll.setWidget(self._qc_group)
        qc_scroll.setWidgetResizable(True)
        qc_scroll.setMaximumHeight(150)
        qc_scroll.setFrameShape(QFrame.Shape.NoFrame)
        layout.addWidget(qc_scroll)

        # Actions
        group_actions = QGroupBox(tr("strain.actions"))
        group_actions.setStyleSheet("QGroupBox { font-weight: bold; color: #e0e0e0; }")
        actions_layout = QVBoxLayout()

        self._btn_edit_mode = QPushButton(tr("strain.btn_edit_mode"))
        self._btn_edit_mode.setCheckable(True)
        self._btn_edit_mode.toggled.connect(lambda c: self.display_mode_changed.emit("edit_mode" if c else "contour"))
        actions_layout.addWidget(self._btn_edit_mode)

        self._btn_undo = QPushButton(tr("strain.btn_undo"))
        self._btn_undo.setEnabled(False)
        actions_layout.addWidget(self._btn_undo)

        self._btn_redo = QPushButton(tr("strain.btn_redo"))
        self._btn_redo.setEnabled(False)
        actions_layout.addWidget(self._btn_redo)

        self._btn_save = QPushButton(tr("strain.btn_save_json"))
        actions_layout.addWidget(self._btn_save)

        self._btn_export_png = QPushButton(tr("strain.btn_export_png"))
        actions_layout.addWidget(self._btn_export_png)

        self._btn_export_csv = QPushButton(tr("strain.btn_export_csv"))
        actions_layout.addWidget(self._btn_export_csv)

        self._btn_close = QPushButton(tr("strain.btn_close"))
        actions_layout.addWidget(self._btn_close)

        group_actions.setLayout(actions_layout)
        layout.addWidget(group_actions)

        layout.addStretch()

    def update_quality(self, accepted: int, total: int, rejected: int) -> None:
        if total > 0:
            pct = (accepted / total) * 100.0
            self._quality_label.setText(f"{accepted} / {total} ({pct:.0f}%)")
        else:
            self._quality_label.setText("-- / --")

        if rejected > 0:
            self._rejected_label.setText(f"{rejected} kernels rejected")
        else:
            self._rejected_label.setText("")

    def set_position(self, view: str) -> None:
        """Set the selected position radio without re-emitting."""
        view = view.upper()
        radio = {"A4C": self._pos_a4c, "A2C": self._pos_a2c, "A3C": self._pos_a3c}.get(view)
        if radio is not None:
            with QSignalBlocker(radio):
                radio.setChecked(True)


class StrainWindow(QMainWindow):
    """Separate window for STE strain visualization with quad-view layout."""

    closed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Strain Analysis")
        self.setMinimumSize(1200, 800)
        self.resize(1400, 900)
        try:
            from PySide6.QtCore import QSettings

            geo = QSettings("SonoForge", "StrainWindow").value("geometry")
            if geo is not None:
                self.restoreGeometry(geo)
        except Exception:  # noqa: BLE001
            pass

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        # Splitter: control panel | content
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Control panel
        self._control = ControlPanel()
        self._control.view_toggled.connect(self._on_view_toggled)
        self._control.display_mode_changed.connect(self._on_display_mode_changed)
        self._control.strain_metric_changed.connect(self._on_strain_metric_changed)
        self._control.qc_segment_toggled.connect(self._on_qc_segment_toggled)
        self._control.position_selected.connect(self._on_position_selected)
        self._control._btn_undo.clicked.connect(self._undo_kernel_move)
        self._control._btn_redo.clicked.connect(self._redo_kernel_move)
        self._control._btn_save.clicked.connect(self._save_json)
        self._control._btn_export_png.clicked.connect(self._export_png)
        self._control._btn_export_csv.clicked.connect(self._export_csv)
        self._control._btn_close.clicked.connect(self.close)
        splitter.addWidget(self._control)

        # Content area: meta bar on top, stacked views + summary below
        content = QWidget()
        content_outer = QVBoxLayout(content)
        content_outer.setContentsMargins(0, 0, 0, 0)
        content_outer.setSpacing(3)

        self._meta_label = QLabel("")
        self._meta_label.setStyleSheet(
            "QLabel { color: #cfd8dc; font-size: 11px; font-weight: bold; "
            "background: #16212b; padding: 3px 8px; border-radius: 3px; }"
        )
        content_outer.addWidget(self._meta_label)

        content_inner = QWidget()
        content_layout = QHBoxLayout(content_inner)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(4)

        # Stacked widget for contour/curves modes
        self._stacked = QStackedWidget()

        # Contour mode (2x2 grid)
        contour_widget = QWidget()
        contour_layout = QGridLayout(contour_widget)
        contour_layout.setContentsMargins(0, 0, 0, 0)
        contour_layout.setSpacing(4)

        self._panel_a4c = CinePanel("A4C")
        self._panel_a2c = CinePanel("A2C")
        self._panel_dao = CinePanel("DAO (A3C)")
        self._panel_bullseye = BullseyeWidget()
        self._control.ttp_mode_toggled.connect(self._panel_bullseye.set_ttp_mode)

        contour_layout.addWidget(self._panel_a4c, 0, 0)
        contour_layout.addWidget(self._panel_a2c, 0, 1)
        contour_layout.addWidget(self._panel_dao, 1, 0)
        contour_layout.addWidget(self._panel_bullseye, 1, 1)

        self._stacked.addWidget(contour_widget)  # index 0

        # Curves mode
        self._curves_view = StrainCurvesView()
        self._stacked.addWidget(self._curves_view)  # index 1

        content_layout.addWidget(self._stacked, stretch=3)

        # Summary table
        self._summary = SummaryTable()
        content_layout.addWidget(self._summary, stretch=1)

        content_outer.addWidget(content_inner, stretch=1)

        splitter.addWidget(content)
        splitter.setSizes([180, 1220])

        main_layout.addWidget(splitter)

        # State
        self._result: StrainResult | None = None
        self._position: str = "A4C"
        # Multi-view study: every analysed view is kept, so the report can show
        # per-view GLS, the three-view average (GLS_AV) and the 18-segment merge.
        self._study: StrainStudy = StrainStudy()
        self._qc_accepted_segments: set[int] = set(range(1, 18))  # All segments accepted by default

        # Undo/Redo stacks for kernel movements
        self._undo_stack: list[tuple[int, float, float, float, float]] = []  # (idx, old_x, old_y, new_x, new_y)
        self._redo_stack: list[tuple[int, float, float, float, float]] = []

        # Connect panel signals
        self._panel_a4c.kernel_moved.connect(lambda idx, x, y: self._on_kernel_moved("A4C", idx, x, y))

    def show_result(self, result: StrainResult, *, frames: np.ndarray | None = None) -> None:
        """Display strain results in the STE window.

        Args:
            result: computed StrainResult.
            frames: optional full cine (N, H, W[, C]) used as the ultrasound
                background of the A4C panel. Positions in the result are in the
                same pixel coordinate space, so overlays line up with the image.
        """
        self._result = result
        # Record this view in the study; the newest run of a view wins.
        analysis = StrainAnalysis.from_result(result)
        self._analysis = analysis
        self._study = self._study.with_view(analysis)

        disp_idx: int | None = None
        n_all = len(result.longitudinal) if result.longitudinal is not None else 0
        if frames is not None and frames.ndim >= 3 and frames.shape[0] == n_all:
            ed = result.ed_index
            if 0 <= ed < frames.shape[0]:
                disp_idx = ed

        # ── Meta bar ────────────────────────────────────────────────────────
        parts: list[str] = [f"{tr('strain.view_label')} {self._analysis.view}", f"GLS {result.gls:.1f}%"]
        gls_av = self._study.gls_average()
        if gls_av is not None and len(self._study.views_valid()) > 1:
            parts.append(tr("strain.gls_av_meta", value=f"{gls_av:.1f}", n=str(len(self._study.views_valid()))))
        # Honest QC (issue #3): NCC fidelity and measurement validity are
        # different things. Never label a high NCC as "quality" without the
        # validity status next to it.
        status = getattr(result, "qc_status", "") or "invalid"
        if status == "valid":
            parts.append(f"● {tr('strain.qc_status_valid')}")
        elif status == "review":
            parts.append(f"⚠ {tr('strain.qc_status_review')}")
        else:
            parts.append(f"■ {tr('strain.qc_status_invalid')}")
        if result.tracking_quality_mean:
            parts.append(tr("strain.qc_fidelity", pct=f"{result.tracking_quality_mean * 100.0:.0f}"))
        avc_source = getattr(result, "avc_source", "") or ""
        if avc_source:
            parts.append(
                tr(
                    "strain.avc_source",
                    source=tr(f"strain.avc_{avc_source}"),
                    frame=str(getattr(result, "avc_index", 0)),
                )
            )
        drift = float(getattr(result, "drift_measured", float("nan")))
        if np.isfinite(drift) and abs(drift) > 2.0:
            parts.append(tr("strain.drift_warning", value=f"{drift:+.1f}"))
        if getattr(result, "is_post_systolic", False):
            parts.append(tr("strain.post_systolic"))
        qc_reasons = getattr(result, "qc_reasons", ()) or ()
        if qc_reasons:
            reason_text = ", ".join(tr(key) for key in qc_reasons[:2])
            parts.append(f"{tr('strain.qc_reasons')}: {reason_text}")
        elif not result.qc_physiology_ok and result.qc_physiology_reasons:
            parts.append(f"⚠ {result.qc_physiology_reasons[0]}")
        total_k = result.kernels_total_count
        if total_k:
            parts.append(f"kernels {result.kernels_accepted_count}/{total_k}")
        source_map = {
            "manual": "manual",
            "manual_ed+auto": "manual ED + auto ES",
            "manual_es+auto": "manual ES + auto ED",
            "ecg": "ECG",
            "simpson": "Simpson",
            "image": "image",
            "image_fallback": "image",
        }
        source_label = source_map.get(result.ed_es_source, result.ed_es_source)
        parts.append(f"ED/ES {result.ed_index}/{result.es_index} ({source_label})")
        parts.append(f"Позиция: {self._position}")
        if result.drift_compensation_applied:
            parts.append("drift on")
        if result.heart_rate_bpm > 0:
            parts.append(f"HR {result.heart_rate_bpm:.0f} bpm")
        self._meta_label.setText("   |   ".join(parts))

        # Update quality gate info
        self._control.update_quality(
            result.kernels_accepted_count,
            result.kernels_total_count,
            result.kernels_rejected_count,
        )

        # Per-view GLS: only the analysed view can have a value — the segments
        # of the other views were never measured, and the old id-range split
        # (<=6 / 7..11 / >=12) mixed walls of different views (issues #C2/#C11).
        # Per-view GLS: filled from the recorded analyses, so a view analysed
        # earlier keeps its value (and the average of the views is meaningful).
        # A view that was never analysed stays empty — never a fabricated 0.
        view = self._analysis.view
        gls_a4c = self._study.view_gls("A4C")
        gls_a2c = self._study.view_gls("A2C")
        gls_dao = self._study.view_gls("A3C")

        # Update summary table — GLS (peak of the global curve) next to ESS
        # (value at AVC), time to peak, post-systolic index and the measured
        # baseline drift, so the systolic value can never be mistaken for the
        # peak one (plan §3.5).
        def _finite(value) -> float | None:
            try:
                number = float(value)
            except (TypeError, ValueError):
                return None
            return number if np.isfinite(number) else None

        self._summary.update_values(
            gls=result.gls,
            gls_a4c=gls_a4c,
            gls_a2c=gls_a2c,
            gls_dao=gls_dao,
            gls_av=self._study.gls_average(),
            ess=_finite(getattr(result, "ess", None)),
            ttp=_finite(getattr(result, "time_to_peak_ms", None)),
            psi=_finite(getattr(result, "post_systolic_index", None)),
            drift=_finite(getattr(result, "drift_measured", None)),
            hr=result.heart_rate_bpm if result.heart_rate_bpm > 0 else None,
        )

        # Update Bull's Eye plot
        if result.segment_strain:
            self._panel_bullseye.update_data(
                result.segment_strain,
                result.segment_quality,
                getattr(result, "segment_ttp_ms", None),
            )

            # Populate QC checkboxes for available segments
            self._populate_qc_checkboxes(result.segment_strain)

        # Get endo kernels and positions
        endo_indices = [i for i, k in enumerate(result.kernels) if k.layer == "endo"]
        endo_kernels = [result.kernels[i] for i in endo_indices]

        # Update A4C panel (main view)
        self._panel_a4c.set_title_info(f"GLS: {result.gls:.1f}%")

        # ED contour (red, smoothed)
        if result.ed_contour is not None and len(result.ed_contour) >= 3:
            self._panel_a4c.show_contour(result.ed_contour, color="#ff1744", smooth=True)

        # ES contour (green, dashed)
        if result.es_contour is not None and len(result.es_contour) >= 3:
            self._panel_a4c.show_es_contour(result.es_contour, color="#00e676", smooth=True)

        # Tracking kernels with quality coloring
        if result.tracked_ed_positions is not None:
            endo_positions = result.tracked_ed_positions[endo_indices]
            if result.es_ncc_scores is not None and result.es_valid_mask is not None:
                endo_ncc = result.es_ncc_scores[endo_indices]
                endo_valid = result.es_valid_mask[endo_indices]
                self._panel_a4c.show_kernels(endo_positions, endo_ncc, endo_valid)
            else:
                self._panel_a4c.show_kernels(endo_positions)

            # Segment labels (Russian names)
            self._panel_a4c.show_segment_labels(endo_kernels, endo_positions)

        # HR and frame info
        self._panel_a4c.set_hr(result.heart_rate_bpm)
        n_frames = len(result.longitudinal) if result.longitudinal is not None else 0
        # Real ultrasound background (frame where kernels/ED contour are anchored)
        self._panel_a4c.set_frames(frames, index=disp_idx if disp_idx is not None else 0)
        self._panel_a4c.set_frame((disp_idx if disp_idx is not None else result.es_index) + 1, n_frames)

        # Per-frame animated overlay (kernels + live endo contour follow the wall)
        layers = [k.layer for k in result.kernels]
        self._panel_a4c.set_tracked_overlay(
            result.tracked_positions_all,
            layers=layers,
            ed_index=result.ed_index,
            es_index=result.es_index,
        )

        # ECG trace: real DICOM ECG only. No real ECG → strip hidden entirely
        # (no synthetic placeholder — issue #2).
        has_ecg = result.ecg_trace_for_display is not None and len(result.ecg_trace_for_display) > 0
        if has_ecg:
            ecg = result.ecg_trace_for_display
            sample_rate: float | None = None
            if result.ecg_waveform is not None and result.ecg_waveform.primary_lead is not None:
                sample_rate = float(result.ecg_waveform.primary_lead.sampling_frequency)
            r_peak_times: np.ndarray | None = None
            if result.r_peak_result is not None and result.r_peak_result.r_peak_times_ms is not None:
                r_peak_times = result.r_peak_result.r_peak_times_ms
            self._panel_a4c.show_ecg_trace(
                ecg,
                frame_time_ms=result.frame_time_ms,
                current_frame=result.es_index,
                ecg_sample_rate=sample_rate,
                r_peak_times_ms=r_peak_times,
                ed_frame=result.ed_index,
                es_frame=result.es_index,
            )
            self._panel_a4c.set_ecg_visible(True)
        else:
            self._panel_a4c.set_ecg_visible(False)

        # A2C/DAO are not analysed in the single-view pass
        self._panel_a2c.set_title_info(tr("strain.no_data"))
        self._panel_dao.set_title_info(tr("strain.no_data"))

        # Update curves view (ECG strip hidden there too when absent)
        self._curves_view.set_strain_data(result)

        if not self.isVisible():
            self.show()
        self.raise_()
        self.activateWindow()

    def set_position(self, view: str) -> None:
        """Record which echo view (A4C/A2C/A3C) the contours came from."""
        view = view.upper()
        if view not in ("A4C", "A2C", "A3C"):
            return
        self._position = view
        self._control.set_position(view)
        self._curves_view.set_active_view(view)
        if self._result is not None:
            parts = self._meta_label.text().split("   |   ")
            parts = [p for p in parts if not p.startswith("Позиция:")]
            parts.append(f"Позиция: {self._position}")
            self._meta_label.setText("   |   ".join(parts))

    def show_curves(self) -> None:
        """Switch the stacked view to the strain-curves page."""
        self._stacked.setCurrentIndex(1)
        self._control._mode_curves.setChecked(True)
        if self._result is not None:
            self._curves_view.set_strain_data(self._result)

    def _on_position_selected(self, view: str) -> None:
        self._position = view
        self._curves_view.set_active_view(view)
        if self._result is not None and self._stacked.currentIndex() == 1:
            self._curves_view.set_strain_data(self._result)

    def _generate_synthetic_ecg(self, n_frames: int, hr_bpm: float) -> np.ndarray:
        """Generate synthetic ECG trace for visualization."""
        if n_frames < 2 or hr_bpm <= 0:
            return np.zeros(max(n_frames, 100))

        frame_time_s = 33.3 / 1000.0  # assuming ~30fps
        hr_hz = hr_bpm / 60.0
        period_frames = int(1.0 / (hr_hz * frame_time_s))

        ecg = np.zeros(n_frames)
        for i in range(n_frames):
            phase = (i % period_frames) / period_frames
            # Simple PQRST approximation
            if 0.0 <= phase < 0.1:  # P wave
                ecg[i] = 0.15 * np.sin(np.pi * phase / 0.1)
            elif 0.15 <= phase < 0.18:  # Q wave
                ecg[i] = -0.1
            elif 0.18 <= phase < 0.25:  # R wave
                ecg[i] = 1.0 * np.sin(np.pi * (phase - 0.18) / 0.07)
            elif 0.25 <= phase < 0.28:  # S wave
                ecg[i] = -0.2
            elif 0.35 <= phase < 0.5:  # T wave
                ecg[i] = 0.3 * np.sin(np.pi * (phase - 0.35) / 0.15)

        return ecg

    def _on_kernel_moved(self, view: str, kernel_idx: int, new_x: float, new_y: float) -> None:
        """Handle kernel movement from panel."""
        if self._result is None or self._result.tracked_ed_positions is None:
            return

        # Find the actual kernel index in the full array
        endo_indices = [i for i, k in enumerate(self._result.kernels) if k.layer == "endo"]
        if kernel_idx >= len(endo_indices):
            return

        actual_idx = endo_indices[kernel_idx]
        old_x = float(self._result.tracked_ed_positions[actual_idx, 0])
        old_y = float(self._result.tracked_ed_positions[actual_idx, 1])

        # Update position
        self._result.tracked_ed_positions[actual_idx, 0] = new_x
        self._result.tracked_ed_positions[actual_idx, 1] = new_y

        # Add to undo stack
        self._undo_stack.append((actual_idx, old_x, old_y, new_x, new_y))
        self._redo_stack.clear()  # Clear redo stack on new action

        # Update undo/redo button states
        self._control._btn_undo.setEnabled(len(self._undo_stack) > 0)
        self._control._btn_redo.setEnabled(False)

        logger.info("Kernel %d moved: (%.1f, %.1f) -> (%.1f, %.1f)", actual_idx, old_x, old_y, new_x, new_y)

    def _populate_qc_checkboxes(self, segment_strain: dict[int, float]) -> None:
        """Populate QC checkboxes only for segments with data."""
        # Remove placeholder
        if self._control._qc_placeholder is not None:
            self._control._qc_layout.removeWidget(self._control._qc_placeholder)
            self._control._qc_placeholder.deleteLater()
            self._control._qc_placeholder = None

        # Clear old checkboxes
        for cb in self._control._qc_checkboxes.values():
            self._control._qc_layout.removeWidget(cb)
            cb.deleteLater()
        self._control._qc_checkboxes.clear()

        # AHA segment names
        segment_names = {
            1: tr("strain.seg_basal_septal"),
            2: tr("strain.seg_basal_lateral"),
            3: tr("strain.seg_mid_septal"),
            4: tr("strain.seg_mid_lateral"),
            5: tr("strain.seg_apical_septal"),
            6: tr("strain.seg_apical_lateral"),
        }

        # Create checkboxes for segments with data
        for seg_id in sorted(segment_strain.keys()):
            seg_name = segment_names.get(seg_id, tr("strain.segment_fallback", id=str(seg_id)))
            cb = QCheckBox(seg_name)
            cb.setChecked(True)
            cb.setStyleSheet("color: #e0e0e0; font-size: 10px;")
            cb.toggled.connect(lambda checked, sid=seg_id: self._control.qc_segment_toggled.emit(sid, checked))
            self._control._qc_layout.addWidget(cb)
            self._control._qc_checkboxes[seg_id] = cb

        # Add stretch at end
        self._control._qc_layout.addStretch()

    def _undo_kernel_move(self) -> None:
        """Undo the last kernel movement."""
        if not self._undo_stack or self._result is None:
            return

        idx, old_x, old_y, new_x, new_y = self._undo_stack.pop()

        # Restore position
        self._result.tracked_ed_positions[idx, 0] = old_x
        self._result.tracked_ed_positions[idx, 1] = old_y

        # Add to redo stack
        self._redo_stack.append((idx, old_x, old_y, new_x, new_y))

        # Update button states
        self._control._btn_undo.setEnabled(len(self._undo_stack) > 0)
        self._control._btn_redo.setEnabled(len(self._redo_stack) > 0)

        # Re-render
        self._update_panel_a4c()

    def _redo_kernel_move(self) -> None:
        """Redo the last undone kernel movement."""
        if not self._redo_stack or self._result is None:
            return

        idx, old_x, old_y, new_x, new_y = self._redo_stack.pop()

        # Apply position
        self._result.tracked_ed_positions[idx, 0] = new_x
        self._result.tracked_ed_positions[idx, 1] = new_y

        # Add to undo stack
        self._undo_stack.append((idx, old_x, old_y, new_x, new_y))

        # Update button states
        self._control._btn_undo.setEnabled(len(self._undo_stack) > 0)
        self._control._btn_redo.setEnabled(len(self._redo_stack) > 0)

        # Re-render
        self._update_panel_a4c()

    def _update_panel_a4c(self) -> None:
        """Re-render A4C panel with current data."""
        if self._result is None:
            return

        # Update kernels
        endo_indices = [i for i, k in enumerate(self._result.kernels) if k.layer == "endo"]
        endo_kernels = [self._result.kernels[i] for i in endo_indices]

        if self._result.tracked_ed_positions is not None:
            endo_positions = self._result.tracked_ed_positions[endo_indices]
            if self._result.es_ncc_scores is not None and self._result.es_valid_mask is not None:
                endo_ncc = self._result.es_ncc_scores[endo_indices]
                endo_valid = self._result.es_valid_mask[endo_indices]
                self._panel_a4c.show_kernels(endo_positions, endo_ncc, endo_valid)
            else:
                self._panel_a4c.show_kernels(endo_positions)

            # Update segment labels
            self._panel_a4c.show_segment_labels(endo_kernels, endo_positions)

    def _on_view_toggled(self, view: str, checked: bool) -> None:
        """Handle view checkbox toggle."""
        panel_map = {
            "A4C": self._panel_a4c,
            "A2C": self._panel_a2c,
            "DAO": self._panel_dao,
        }
        panel = panel_map.get(view)
        if panel is not None:
            panel.setVisible(checked)

    def _on_display_mode_changed(self, mode: str) -> None:
        """Switch between contour, curves, and edit mode."""
        if mode == "contour":
            self._stacked.setCurrentIndex(0)
            self._panel_a4c.set_edit_mode(False)
        elif mode == "curves":
            self._stacked.setCurrentIndex(1)
            # Update curves view with current result
            if self._result is not None:
                self._curves_view.set_strain_data(self._result)
        elif mode == "edit_mode":
            self._stacked.setCurrentIndex(0)
            self._panel_a4c.set_edit_mode(True)

    def _on_strain_metric_changed(self, metric: str) -> None:
        """Switch between deformation, strain rate, and peak strain display."""
        if self._result is None:
            return

        # Store current metric for re-rendering
        self._current_metric = metric

        # Update title info based on metric
        if metric == "deformation":
            title_info = f"GLS: {self._result.gls:.1f}%"
            unit = "%"
        elif metric == "strain_rate":
            title_info = "GLS Rate: --"
            unit = "1/s"
        elif metric == "peak":
            title_info = f"Peak GLS: {self._result.gls:.1f}%"
            unit = "%"
        else:
            return

        self._panel_a4c.set_title_info(title_info)

        # Update bull's eye if available
        if self._result.segment_strain:
            if metric == "strain_rate" and self._result.strain_rate is not None:
                # For SR mode, we would show strain rate per segment
                # For now, show strain as placeholder
                self._panel_bullseye.update_data(
                    self._result.segment_strain,
                    self._result.segment_quality,
                )
            else:
                self._panel_bullseye.update_data(
                    self._result.segment_strain,
                    self._result.segment_quality,
                )

    def _on_qc_segment_toggled(self, segment_id: int, accepted: bool) -> None:
        """Handle quality control checkbox toggle for a segment."""
        if accepted:
            self._qc_accepted_segments.add(segment_id)
        else:
            self._qc_accepted_segments.discard(segment_id)

        # Recalculate GLS excluding rejected segments
        if self._result is not None and self._result.segment_strain:
            accepted_strains = [
                strain for seg_id, strain in self._result.segment_strain.items() if seg_id in self._qc_accepted_segments
            ]
            if accepted_strains:
                gls_qc = float(np.min(accepted_strains))
            else:
                gls_qc = self._result.gls  # Fallback to original GLS

            # Update summary table with QC-adjusted GLS
            self._summary.update_values(gls=gls_qc)

            # Update bull's eye (mark rejected segments as gray)
            self._panel_bullseye.update_qc(
                self._result.segment_strain,
                self._result.segment_quality,
                self._qc_accepted_segments,
            )

    def _save_json(self) -> None:
        """Save deformation data to JSON file."""
        if self._result is None:
            return

        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getSaveFileName(self, tr("strain.save_dialog_title"), "", "JSON files (*.json)")
        if not path:
            return

        import json

        # Export the analysis record with its definitions, frame anchors and QC,
        # not a bare list of numbers: a strain value without the definition and
        # the view it was measured in cannot be reproduced or compared with a
        # vendor report. Curves are included so the file is self-contained.
        analysis = getattr(self, "_analysis", None) or StrainAnalysis.from_result(self._result)
        analysis_dict = analysis.to_dict(with_curves=True)
        analysis_dict["qc_accepted_segments"] = sorted(int(seg) for seg in self._qc_accepted_segments)
        data = {
            "kind": "sonoforge.ste.analysis",
            "analysis": analysis_dict,
            "study": self._study.to_dict(),
        }
        # Keep the legacy flat keys for consumers written against the old file.
        legacy_keys = {
            "gls": self._result.gls,
            "heart_rate_bpm": self._result.heart_rate_bpm,
            "position": self._position,
            "ed_index": self._result.ed_index,
            "es_index": self._result.es_index,
            "avc_index": analysis.avc_index,
            "ess": analysis.ess,
            "time_to_peak_ms": analysis.time_to_peak_ms,
            "post_systolic_index": analysis.post_systolic_index,
            "drift_measured": analysis.drift,
            "qc_status": analysis.qc_status,
            "qc_reasons": list(analysis.qc_reasons),
            "kernels_accepted": self._result.kernels_accepted_count,
            "kernels_rejected": self._result.kernels_rejected_count,
            "kernels_total": self._result.kernels_total_count,
            "segment_strain": {str(k): v for k, v in (self._result.segment_strain or {}).items()},
            "segment_quality": {str(k): v for k, v in (self._result.segment_quality or {}).items()},
            "segment_ttp_ms": {str(k): v for k, v in (analysis.segment_ttp_ms or {}).items()},
            "segment_ess": {str(k): v for k, v in (analysis.segment_ess or {}).items()},
        }
        data.update(legacy_keys)

        # Add kernel positions if available
        if self._result.tracked_ed_positions is not None:
            data["kernel_positions_ed"] = self._result.tracked_ed_positions.tolist()
        if self._result.tracked_es_positions is not None:
            data["kernel_positions_es"] = self._result.tracked_es_positions.tolist()

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info("Saved deformation data to %s", path)

    def _export_png(self) -> None:
        """Export current view as PNG screenshot."""
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getSaveFileName(self, tr("strain.export_png_title"), "", "PNG files (*.png)")
        if not path:
            return

        # Capture the content area
        content = self._stacked.currentWidget()
        if content is None:
            return

        pixmap = content.grab()
        pixmap.save(path, "PNG")
        logger.info("Exported PNG to %s", path)

    def _export_csv(self) -> None:
        """Export the measured segments with their metrics to CSV.

        One row per standard AHA segment with the value, time to peak,
        end-systolic value, tracking quality, the view it came from and whether
        it passed QC — the table a report or a paper actually needs.
        """
        if self._result is None or self._result.segment_strain is None:
            return

        import csv

        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getSaveFileName(self, tr("strain.export_csv_title"), "", "CSV files (*.csv)")
        if not path:
            return

        analysis = getattr(self, "_analysis", None) or StrainAnalysis.from_result(self._result)
        sources = self._study.segment_sources()

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "Segment ID",
                    "Segment Name",
                    "Strain (%)",
                    "ESS (%)",
                    "Time to peak (ms)",
                    "Quality (NCC)",
                    "View",
                    "Accepted",
                ]
            )
            for seg_id in sorted(self._result.segment_strain.keys()):
                strain = self._result.segment_strain[seg_id]
                quality = (self._result.segment_quality or {}).get(seg_id, float("nan"))
                ess = analysis.segment_ess.get(seg_id)
                ttp = analysis.segment_ttp_ms.get(seg_id)
                accepted = seg_id in self._qc_accepted_segments
                writer.writerow(
                    [
                        seg_id,
                        segment_name(seg_id),
                        f"{strain:.2f}",
                        "" if ess is None else f"{ess:.2f}",
                        "" if ttp is None or not np.isfinite(ttp) else f"{ttp:.0f}",
                        "" if quality is None or not np.isfinite(quality) else f"{quality:.3f}",
                        sources.get(seg_id, self._analysis.view),
                        accepted,
                    ]
                )
            # Provenance block: definitions + anchors, so the file stands alone.
            writer.writerow([])
            writer.writerow(["# GLS definition", analysis.definition_gls])
            writer.writerow(["# ESS definition", analysis.definition_ess])
            writer.writerow(["# TTP definition", analysis.definition_ttp])
            writer.writerow(["# Layer", analysis.layer])
            writer.writerow(["# View", analysis.view])
            writer.writerow(["# ED frame", analysis.ed_index])
            writer.writerow(["# ES frame", analysis.es_index])
            writer.writerow(["# AVC frame", analysis.avc_index])
            writer.writerow(["# AVC source", analysis.avc_source])
            writer.writerow(["# QC status", analysis.qc_status])
            writer.writerow(["# QC reasons", "|".join(analysis.qc_reasons)])
            writer.writerow(["# Coverage", f"{analysis.qc_coverage:.3f}"])
            writer.writerow(["# GLS", "" if analysis.gls is None else f"{analysis.gls:.2f}"])
            writer.writerow(["# GLS_AV", "" if self._study.gls_average() is None else f"{self._study.gls_average():.2f}"])

        logger.info("Exported CSV to %s", path)

    def closeEvent(self, event) -> None:
        try:
            from PySide6.QtCore import QSettings

            settings = QSettings("SonoForge", "StrainWindow")
            settings.setValue("geometry", self.saveGeometry())
        except Exception:  # noqa: BLE001
            pass
        self.closed.emit()
        super().closeEvent(event)
