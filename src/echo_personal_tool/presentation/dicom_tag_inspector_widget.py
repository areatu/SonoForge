"""DICOM tag inspector table for the current instance."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QHeaderView, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from echo_personal_tool.infrastructure.dicom_tag_inspector import DicomTagRow, read_all_dicom_tag_rows


class DicomTagInspectorWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["Tag", "Keyword", "VR", "Value", "Description"])
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self._table)

    def load_instance(self, path: Path | None) -> None:
        self._table.setRowCount(0)
        if path is None or not path.is_file():
            return
        try:
            rows = read_all_dicom_tag_rows(path)
        except Exception:  # noqa: BLE001 — show empty table on parse errors
            return
        self._populate(rows)

    def _populate(self, rows: list[DicomTagRow]) -> None:
        self._table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = (row.tag_hex, row.keyword, row.vr, row.value, row.description)
            for column_index, value in enumerate(values):
                self._table.setItem(row_index, column_index, QTableWidgetItem(value))
