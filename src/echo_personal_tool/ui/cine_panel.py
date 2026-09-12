"""Single cine panel with image viewer, contour overlay, and info labels."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.presentation.segment_labels import short_segment_label
from echo_personal_tool.presentation.speckle_overlay import segment_label_anchors
from echo_personal_tool.ui.strain_helpers import _smooth_contour


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

    # -- Playback (contour/kernel animation) -----------------------------------

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

    # -- Per-frame tracked overlay (animated kernels + live contour) ------------

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

    # -- ECG strip -------------------------------------------------------------

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
        """Draw short segment names next to the wall they measure.

        Same labels as on the cine overlay (`presentation.segment_labels`), so a
        segment reads the same way in the strain window and in the viewer.
        """
        # Clear old labels
        for item in self._segment_labels:
            self._plot.removeItem(item)
        self._segment_labels.clear()

        if len(positions) == 0 or len(kernels) == 0:
            return

        for segment, x, y in segment_label_anchors(kernels, positions):
            text_item = pg.TextItem(
                short_segment_label(segment),
                color=(235, 247, 255),
                anchor=(0.5, 0.5),
                border=pg.mkPen(6, 10, 16, 170),
                fill=pg.mkBrush(6, 10, 16, 120),
            )
            text_item.setPos(x, y)
            font = QFont("sans-serif", 8)
            font.setBold(True)
            text_item.setFont(font)
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
