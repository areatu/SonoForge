"""Table widget for per-segment strain and tracking quality."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from echo_personal_tool.domain.services.aha_segments import A4C_SEGMENT_NAMES


class SegmentQualityPanel(QWidget):
    """Display A4C segment strain and quality metrics."""

    _LOW_QUALITY_BG = QColor(127, 17, 22)
    _LOW_QUALITY_FG = QColor(255, 255, 255)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._table = QTableWidget(len(A4C_SEGMENT_NAMES), 3, self)
        self._table.setHorizontalHeaderLabels(["Segment", "Strain %", "Quality"])
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        for row, segment_id in enumerate(sorted(A4C_SEGMENT_NAMES)):
            segment_name = A4C_SEGMENT_NAMES[segment_id]
            self._table.setItem(row, 0, QTableWidgetItem(segment_name))
            self._table.setItem(row, 1, QTableWidgetItem("--"))
            self._table.setItem(row, 2, QTableWidgetItem("--"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._table)

    def update_results(
        self,
        segment_strain: dict[int, float],
        segment_quality: dict[int, float],
    ) -> None:
        """Update table values and highlight low-quality rows."""
        default_bg = self.palette().base().color()
        default_fg = self.palette().text().color()

        for row, segment_id in enumerate(sorted(A4C_SEGMENT_NAMES)):
            strain_value = segment_strain.get(segment_id)
            quality_value = segment_quality.get(segment_id)
            strain_text = "--" if strain_value is None else f"{strain_value:.1f}"
            quality_text = "--" if quality_value is None else f"{quality_value:.2f}"

            if quality_value is not None and quality_value < 0.4:
                background = self._LOW_QUALITY_BG
                foreground = self._LOW_QUALITY_FG
            else:
                background = default_bg
                foreground = default_fg

            strain_item = self._table.item(row, 1)
            quality_item = self._table.item(row, 2)
            if strain_item is not None:
                strain_item.setText(strain_text)
            if quality_item is not None:
                quality_item.setText(quality_text)

            for col in range(self._table.columnCount()):
                item = self._table.item(row, col)
                if item is not None:
                    item.setBackground(background)
                    item.setForeground(foreground)
