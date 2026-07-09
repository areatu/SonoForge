"""Separate window for STE strain visualization — quad-view layout."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np
import pyqtgraph as pg
from scipy.interpolate import CubicSpline
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QButtonGroup,
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
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from echo_personal_tool.domain.models.speckle import StrainResult

from echo_personal_tool.ui.strain_curves_view import StrainCurvesView

logger = logging.getLogger(__name__)

# Russian AHA segment names (Samsung style)
AHA_SEGMENT_NAMES_RU: dict[int, str] = {
    1: "БазПерг",   # Basal septal
    2: "Базбок",    # Basal lateral
    3: "СрПерг",    # Mid septal
    4: "Србок",     # Mid lateral
    5: "АпПер",     # Apical septal
    6: "АпЛат",     # Apical lateral
}


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

        # PyQtGraph plot widget
        self._plot = pg.PlotWidget()
        self._plot.setBackground("black")
        self._plot.hideAxis("left")
        self._plot.hideAxis("bottom")
        self._plot.setAspectLocked(True)
        self._plot.setMouseEnabled(x=False, y=False)
        self._plot.setMinimumHeight(200)
        layout.addWidget(self._plot, stretch=2)

        # ECG trace area
        self._ecg_plot = pg.PlotWidget()
        self._ecg_plot.setBackground("black")
        self._ecg_plot.hideAxis("left")
        self._ecg_plot.hideAxis("bottom")
        self._ecg_plot.setMaximumHeight(60)
        self._ecg_plot.setMinimumHeight(40)
        layout.addWidget(self._ecg_plot, stretch=0)

        # Bottom row: HR + frame counter
        footer = QHBoxLayout()
        self._hr_label = QLabel("HR: --")
        self._hr_label.setStyleSheet("color: #4caf50; font-size: 10px;")
        footer.addWidget(self._hr_label)
        footer.addStretch()
        self._frame_label = QLabel("--/--")
        self._frame_label.setStyleSheet("color: #9e9e9e; font-size: 10px;")
        footer.addWidget(self._frame_label)
        layout.addLayout(footer)

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
            self._kernel_scatter = pg.ScatterPlotItem(
                x=x, y=y, pen=None, brush=colors, symbol="s", size=6
            )
        else:
            self._kernel_scatter = pg.ScatterPlotItem(
                x=x, y=y, pen=pg.mkPen("w", width=0.5),
                brush=pg.mkBrush(255, 255, 255, 180), symbol="s", size=6
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
            (self._kernel_positions[:, 0] - click_x) ** 2 +
            (self._kernel_positions[:, 1] - click_y) ** 2
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
                x=x, y=y, pen=pg.mkPen("#ffd54f", width=2),
                brush=pg.mkBrush(255, 213, 79, 150), symbol="o", size=16
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

    def show_ecg_trace(self, ecg_data: np.ndarray | None, frame_time_ms: float = 33.3, current_frame: int = 0) -> None:
        """Display ECG trace with frame marker."""
        if self._ecg_item is not None:
            self._ecg_plot.removeItem(self._ecg_item)
            self._ecg_item = None
        if self._ecg_marker is not None:
            self._ecg_plot.removeItem(self._ecg_marker)
            self._ecg_marker = None

        if ecg_data is None or len(ecg_data) == 0:
            return

        n = len(ecg_data)
        t = np.arange(n) * frame_time_ms

        pen = pg.mkPen("#4caf50", width=1)
        self._ecg_item = pg.PlotDataItem(t, ecg_data, pen=pen)
        self._ecg_plot.addItem(self._ecg_item)

        # Frame marker
        marker_x = current_frame * frame_time_ms
        self._ecg_marker = pg.InfiniteLine(
            pos=marker_x, angle=90, pen=pg.mkPen("#ffd54f", width=1, style=Qt.PenStyle.DashLine)
        )
        self._ecg_plot.addItem(self._ecg_marker)

        self._ecg_plot.setXRange(0, t[-1] if len(t) > 0 else 1000)

    def clear(self) -> None:
        if self._ed_contour_item is not None:
            self._plot.removeItem(self._ed_contour_item)
            self._ed_contour_item = None
        if self._es_contour_item is not None:
            self._plot.removeItem(self._es_contour_item)
            self._es_contour_item = None
        if self._kernel_scatter is not None:
            self._plot.removeItem(self._kernel_scatter)
            self._kernel_scatter = None
        for item in self._segment_labels:
            self._plot.removeItem(item)
        self._segment_labels.clear()
        if self._ecg_item is not None:
            self._ecg_plot.removeItem(self._ecg_item)
            self._ecg_item = None
        if self._ecg_marker is not None:
            self._ecg_plot.removeItem(self._ecg_marker)
            self._ecg_marker = None
        self._info_label.setText("")
        self._hr_label.setText("HR: --")
        self._frame_label.setText("--/--")


class BullseyeWidget(QWidget):
    """17-segment AHA Bull's Eye plot with color-coded strain values."""

    # AHA 17-segment model: (ring, angle_index) -> segment_id
    # Rings: 0=apex, 1=apical, 2=mid, 3=basal
    # Angles: 0=anteroseptal, 1=anterior, 2=anterolateral,
    #         3=inferolateral, 4=inferior, 5=inferoseptal
    SEGMENT_GEOMETRY: dict[int, tuple[int, int]] = {
        # Apex (1 segment)
        17: (0, 0),
        # Apical (4 segments)
        13: (1, 0),  # apical anterior
        16: (1, 1),  # apical lateral
        14: (1, 2),  # apical inferior
        12: (1, 3),  # apical septal
        # Mid (6 segments)
        7: (2, 0),   # mid anterior
        8: (2, 1),   # anterolateral
        11: (2, 2),  # inferolateral
        10: (2, 3),  # mid inferior
        9: (2, 4),   # inferoseptal
        3: (2, 5),   # mid septal
        # Basal (6 segments)
        1: (3, 0),   # basal anterior
        2: (3, 1),   # anterolateral
        6: (3, 2),   # inferolateral
        5: (3, 3),   # basal inferior
        4: (3, 4),   # inferoseptal
        15: (3, 5),  # basal septal
    }

    # Russian labels for outer perimeter
    SEGMENT_LABELS_RU: dict[int, str] = {
        1: "Пер", 2: "Лат", 6: "Лат",
        5: "Нижн", 4: "Задн", 15: "Пер",
        7: "Пер", 8: "Лат", 11: "Лат",
        10: "Нижн", 9: "Задн", 3: "Пер",
        13: "АпПер", 16: "АпЛат", 14: "АпНижн", 12: "АпПер",
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

    def paintEvent(self, event) -> None:
        """Custom paint using QPainter for filled segments."""
        from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
        from PySide6.QtCore import QPointF

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

        # Draw filled segments
        for seg_id, (ring, angle_idx) in self.SEGMENT_GEOMETRY.items():
            strain = self._segment_strains.get(seg_id, None)

            # Check if segment is accepted by QC
            is_accepted = True
            if hasattr(self, '_qc_accepted_segments') and self._qc_accepted_segments is not None:
                is_accepted = seg_id in self._qc_accepted_segments

            if not is_accepted:
                # Rejected segment: dark gray
                color = QColor(60, 60, 60)
            elif strain is not None:
                color = self._strain_to_color(strain)
            else:
                color = QColor(40, 40, 40)  # dark gray = no data

            # Calculate polygon
            if ring == 0:
                # Apex: full circle
                polygon = QPolygonF()
                for a in range(360):
                    rad = np.radians(a)
                    polygon.append(QPointF(cx + r_apex * np.cos(rad), cy + r_apex * np.sin(rad)))
            else:
                # Other rings: arc segments
                n_segments = 6 if ring >= 2 else 4
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
            n_segments_ring = 6 if ring >= 2 else 4
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

            # Draw segment value
            strain = self._segment_strains.get(seg_id, None)
            if strain is not None:
                painter.setPen(QPen(QColor(255, 255, 255), 1))
                painter.drawText(QPointF(lx - 15, ly + 4), f"{strain:.1f}")

        # Draw outer labels (segment names)
        font.setPointSize(9)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QPen(QColor(180, 180, 180), 1))

        outer_labels = {
            0: "Пер", 1: "Лат", 2: "Лат",
            3: "Нижн", 4: "Задн", 5: "Пер",
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

    def _strain_to_color(self, strain: float) -> QColor:
        """Map strain value to color (red=negative, white=zero, blue=positive)."""
        # Clamp to [-25, 10] range
        clamped = max(-25.0, min(10.0, strain))

        if clamped < 0:
            # Red to white (negative strain = abnormal)
            t = (clamped + 25) / 25  # 0 to 1
            r = 255
            g = int(255 * t)
            b = int(255 * t)
        else:
            # White to blue (positive strain)
            t = clamped / 10  # 0 to 1
            r = int(255 * (1 - t))
            g = int(255 * (1 - t))
            b = 255

        return QColor(r, g, b)

    def update_data(
        self,
        segment_strain: dict[int, float],
        segment_quality: dict[int, float] | None = None,
    ) -> None:
        """Update bull's eye with strain data."""
        self._segment_strains = segment_strain.copy()
        self._segment_quality = (segment_quality or {}).copy()
        self._qc_accepted_segments: set[int] | None = None
        self.update()  # Trigger repaint

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
        self.update()


class SummaryTable(QWidget):
    """Summary metrics table — Samsung-style layout with 9 rows."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(240)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        title = QLabel("Сводная таблица")
        title.setStyleSheet("font-weight: bold; color: #e0e0e0; font-size: 12px;")
        layout.addWidget(title)

        self._rows: dict[str, tuple[QLabel, QLabel, str]] = {}
        row_defs = [
            ("gls", "Сред.ГлобПродДеф", "%"),
            ("gls_a4c", "A4C ГлобПродДеф", "%"),
            ("gls_a2c", "A2C ГлобПродДеф", "%"),
            ("gls_dao", "ДАО ГлобПродДеф", "%"),
            ("ef", "ФВ [дв-плоск]", "%"),
            ("edv", "КДО [дв-плоск]", "мл"),
            ("esv", "КСО [дв-плоск]", "мл"),
            ("autozak", "АвтоЗАК", "мс"),
            ("hr", "ЧСС", "bpm"),
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
                elif unit == "мл":
                    val_label.setText(f"{val:.1f} мл")
                elif unit == "мс":
                    val_label.setText(f"{val:.0f} мс")
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

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(180)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        # View mode (contour vs curves)
        group_view_mode = QGroupBox("Вид")
        group_view_mode.setStyleSheet("QGroupBox { font-weight: bold; color: #e0e0e0; }")
        view_mode_layout = QVBoxLayout()

        self._mode_contour = QRadioButton("Cine + контур")
        self._mode_contour.setChecked(True)
        self._mode_contour.setStyleSheet("color: #e0e0e0;")
        self._mode_contour.toggled.connect(lambda c: self.display_mode_changed.emit("contour") if c else None)
        view_mode_layout.addWidget(self._mode_contour)

        self._mode_curves = QRadioButton("Кривые деформации")
        self._mode_curves.setStyleSheet("color: #e0e0e0;")
        self._mode_curves.toggled.connect(lambda c: self.display_mode_changed.emit("curves") if c else None)
        view_mode_layout.addWidget(self._mode_curves)

        group_view_mode.setLayout(view_mode_layout)
        layout.addWidget(group_view_mode)

        # Strain metric (Samsung-style: Deformation / SR / Peak)
        group_metric = QGroupBox("Параметр")
        group_metric.setStyleSheet("QGroupBox { font-weight: bold; color: #e0e0e0; }")
        metric_layout = QVBoxLayout()

        self._metric_deformation = QRadioButton("Деформация")
        self._metric_deformation.setChecked(True)
        self._metric_deformation.setStyleSheet("color: #e0e0e0;")
        self._metric_deformation.toggled.connect(
            lambda c: self.strain_metric_changed.emit("deformation") if c else None
        )
        metric_layout.addWidget(self._metric_deformation)

        self._metric_sr = QRadioButton("Скорость деформ.")
        self._metric_sr.setStyleSheet("color: #e0e0e0;")
        self._metric_sr.toggled.connect(
            lambda c: self.strain_metric_changed.emit("strain_rate") if c else None
        )
        metric_layout.addWidget(self._metric_sr)

        self._metric_peak = QRadioButton("Пик.изм.деформации")
        self._metric_peak.setStyleSheet("color: #e0e0e0;")
        self._metric_peak.toggled.connect(
            lambda c: self.strain_metric_changed.emit("peak") if c else None
        )
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
        group_qc = QGroupBox("Quality Control")
        group_qc.setStyleSheet("QGroupBox { font-weight: bold; color: #e0e0e0; }")
        qc_layout = QVBoxLayout()
        qc_layout.setSpacing(2)

        self._qc_checkboxes: dict[int, QCheckBox] = {}
        # AHA segment names in Russian (matching Bull's Eye)
        qc_segments = [
            (1, "БазПерг"), (2, "Базбок"), (3, "СрПерг"), (4, "Србок"),
            (5, "АпПер"), (6, "АпЛат"), (7, "СрПер"), (8, "СрЛат"),
            (9, "СрЗад"), (10, "СрНиж"), (11, "СрНижЛат"),
            (12, "АпЗад"), (13, "АпПерВерх"), (14, "АпНиж"),
            (15, "БазЗад"), (16, "АпЛат"), (17, "Апекс"),
        ]
        for seg_id, seg_name in qc_segments:
            cb = QCheckBox(seg_name)
            cb.setChecked(True)
            cb.setStyleSheet("color: #e0e0e0; font-size: 10px;")
            cb.toggled.connect(lambda checked, sid=seg_id: self.qc_segment_toggled.emit(sid, checked))
            qc_layout.addWidget(cb)
            self._qc_checkboxes[seg_id] = cb

        group_qc.setLayout(qc_layout)

        # Wrap in scroll area for many checkboxes
        qc_scroll = QScrollArea()
        qc_scroll.setWidget(group_qc)
        qc_scroll.setWidgetResizable(True)
        qc_scroll.setMaximumHeight(150)
        qc_scroll.setFrameShape(QFrame.Shape.NoFrame)
        layout.addWidget(qc_scroll)

        # Actions
        group_actions = QGroupBox("Действия")
        group_actions.setStyleSheet("QGroupBox { font-weight: bold; color: #e0e0e0; }")
        actions_layout = QVBoxLayout()

        self._btn_edit_mode = QPushButton("Режим редактирования")
        self._btn_edit_mode.setCheckable(True)
        self._btn_edit_mode.toggled.connect(lambda c: self.display_mode_changed.emit("edit_mode" if c else "contour"))
        actions_layout.addWidget(self._btn_edit_mode)

        self._btn_undo = QPushButton("Отменить (Ctrl+Z)")
        self._btn_undo.setEnabled(False)
        actions_layout.addWidget(self._btn_undo)

        self._btn_redo = QPushButton("Повторить (Ctrl+Y)")
        self._btn_redo.setEnabled(False)
        actions_layout.addWidget(self._btn_redo)

        self._btn_save = QPushButton("Сохранить JSON")
        actions_layout.addWidget(self._btn_save)

        self._btn_export_png = QPushButton("Экспорт PNG")
        actions_layout.addWidget(self._btn_export_png)

        self._btn_export_csv = QPushButton("Экспорт CSV")
        actions_layout.addWidget(self._btn_export_csv)

        self._btn_close = QPushButton("Закрыть")
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


class StrainWindow(QMainWindow):
    """Separate window for STE strain visualization with quad-view layout."""

    closed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Strain Analysis")
        self.setMinimumSize(1200, 800)
        self.resize(1400, 900)

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
        self._control._btn_undo.clicked.connect(self._undo_kernel_move)
        self._control._btn_redo.clicked.connect(self._redo_kernel_move)
        self._control._btn_save.clicked.connect(self._save_json)
        self._control._btn_export_png.clicked.connect(self._export_png)
        self._control._btn_export_csv.clicked.connect(self._export_csv)
        self._control._btn_close.clicked.connect(self.close)
        splitter.addWidget(self._control)

        # Content area
        content = QWidget()
        content_layout = QHBoxLayout(content)
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

        splitter.addWidget(content)
        splitter.setSizes([180, 1220])

        main_layout.addWidget(splitter)

        # State
        self._result: StrainResult | None = None
        self._qc_accepted_segments: set[int] = set(range(1, 18))  # All segments accepted by default

        # Undo/Redo stacks for kernel movements
        self._undo_stack: list[tuple[int, float, float, float, float]] = []  # (idx, old_x, old_y, new_x, new_y)
        self._redo_stack: list[tuple[int, float, float, float, float]] = []

        # Connect panel signals
        self._panel_a4c.kernel_moved.connect(lambda idx, x, y: self._on_kernel_moved("A4C", idx, x, y))

    def show_result(self, result: StrainResult) -> None:
        """Display strain results in quad-view layout."""
        self._result = result

        # Update quality gate info
        self._control.update_quality(
            result.kernels_accepted_count,
            result.kernels_total_count,
            result.kernels_rejected_count,
        )

        # Compute per-view GLS from segment strains
        gls_a4c = None
        gls_a2c = None
        gls_dao = None
        if result.segment_strain:
            a4c_segs = [v for k, v in result.segment_strain.items() if k <= 6]
            a2c_segs = [v for k, v in result.segment_strain.items() if 7 <= k <= 11]
            dao_segs = [v for k, v in result.segment_strain.items() if k >= 12]
            if a4c_segs:
                gls_a4c = float(np.min(a4c_segs))
            if a2c_segs:
                gls_a2c = float(np.min(a2c_segs))
            if dao_segs:
                gls_dao = float(np.min(dao_segs))

        # Update summary table
        self._summary.update_values(
            gls=result.gls,
            gls_a4c=gls_a4c,
            gls_a2c=gls_a2c,
            gls_dao=gls_dao,
            hr=result.heart_rate_bpm if result.heart_rate_bpm > 0 else None,
        )

        # Update Bull's Eye plot
        if result.segment_strain:
            self._panel_bullseye.update_data(
                result.segment_strain,
                result.segment_quality,
            )

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
        self._panel_a4c.set_frame(result.es_index, n_frames)

        # ECG trace (generate synthetic if not available)
        ecg = self._generate_synthetic_ecg(n_frames, result.heart_rate_bpm)
        self._panel_a4c.show_ecg_trace(ecg, current_frame=result.es_index)

        # Placeholder panels — show same data for now
        self._panel_a2c.set_title_info(f"GLS: {result.gls:.1f}%")
        self._panel_dao.set_title_info(f"GLS: {result.gls:.1f}%")

        # Update curves view
        self._curves_view.set_strain_data(result)

        if not self.isVisible():
            self.show()
        self.raise_()
        self.activateWindow()

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
            title_info = f"GLS Rate: --"
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
                strain for seg_id, strain in self._result.segment_strain.items()
                if seg_id in self._qc_accepted_segments
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
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить данные деформации", "", "JSON files (*.json)"
        )
        if not path:
            return

        import json
        from pathlib import Path

        data = {
            "gls": self._result.gls,
            "heart_rate_bpm": self._result.heart_rate_bpm,
            "ed_index": self._result.ed_index,
            "es_index": self._result.es_index,
            "kernels_accepted": self._result.kernels_accepted_count,
            "kernels_rejected": self._result.kernels_rejected_count,
            "kernels_total": self._result.kernels_total_count,
            "segment_strain": {str(k): v for k, v in (self._result.segment_strain or {}).items()},
            "segment_quality": {str(k): v for k, v in (self._result.segment_quality or {}).items()},
            "qc_accepted_segments": list(self._qc_accepted_segments),
        }

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
        from PySide6.QtGui import QPixmap

        path, _ = QFileDialog.getSaveFileName(
            self, "Экспорт PNG", "", "PNG files (*.png)"
        )
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
        """Export strain values per segment to CSV."""
        if self._result is None or self._result.segment_strain is None:
            return

        from PySide6.QtWidgets import QFileDialog
        import csv

        path, _ = QFileDialog.getSaveFileName(
            self, "Экспорт CSV", "", "CSV files (*.csv)"
        )
        if not path:
            return

        # Segment names
        segment_names = {
            1: "Basal septal", 2: "Basal lateral", 3: "Mid septal", 4: "Mid lateral",
            5: "Apical septal", 6: "Apical lateral",
            7: "Mid anterior", 8: "Anterolateral", 9: "Inferoseptal",
            10: "Mid inferior", 11: "Inferolateral",
            12: "Apical septal", 13: "Apical anterior", 14: "Apical inferior",
            15: "Basal septal", 16: "Apical lateral", 17: "Apex",
        }

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Segment ID", "Segment Name", "Strain (%)", "Quality", "Accepted"])
            for seg_id in sorted(self._result.segment_strain.keys()):
                strain = self._result.segment_strain[seg_id]
                quality = self._result.segment_quality.get(seg_id, 0.0) if self._result.segment_quality else 0.0
                accepted = seg_id in self._qc_accepted_segments
                name = segment_names.get(seg_id, f"Segment {seg_id}")
                writer.writerow([seg_id, name, f"{strain:.2f}", f"{quality:.3f}", accepted])

        logger.info("Exported CSV to %s", path)

    def closeEvent(self, event) -> None:
        self.closed.emit()
        super().closeEvent(event)
