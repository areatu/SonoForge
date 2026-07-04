"""Properties panel for selected element (measurement, contour, instance)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class PropertiesPanel(QWidget):
    """Context-sensitive panel showing properties of the selected element."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._content = QWidget()
        self._form = QFormLayout(self._content)
        self._form.setSpacing(4)
        self._form.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(self._content)
        layout.addWidget(scroll)

        self._instance_group: QGroupBox | None = None
        self._measurement_group: QGroupBox | None = None
        self._contour_group: QGroupBox | None = None

    def update_instance_info(
        self,
        *,
        patient_name: str = "",
        patient_id: str = "",
        study_date: str = "",
        modality: str = "",
        series_desc: str = "",
        instance_number: int = 0,
        frame_rate: float | None = None,
        rows: int = 0,
        columns: int = 0,
        pixel_spacing: str = "",
    ) -> None:
        """Update the instance information section."""
        self._clear_group(self._instance_group)
        self._instance_group = QGroupBox("Instance")
        form = QFormLayout(self._instance_group)
        form.setSpacing(2)
        if patient_name:
            form.addRow("Patient:", QLabel(patient_name))
        if patient_id:
            form.addRow("ID:", QLabel(patient_id))
        if study_date:
            form.addRow("Date:", QLabel(study_date))
        if modality:
            form.addRow("Modality:", QLabel(modality))
        if series_desc:
            form.addRow("Series:", QLabel(series_desc))
        if instance_number:
            form.addRow("Instance #:", QLabel(str(instance_number)))
        if frame_rate and frame_rate > 0:
            form.addRow("Frame rate:", QLabel(f"{frame_rate:.1f} fps"))
        if rows and columns:
            form.addRow("Size:", QLabel(f"{columns}×{rows}"))
        if pixel_spacing:
            form.addRow("Spacing:", QLabel(pixel_spacing))
        self._form.addRow(self._instance_group)

    def update_measurement_info(
        self,
        *,
        label: str = "",
        value_mm: float | None = None,
        start: tuple[float, float] | None = None,
        end: tuple[float, float] | None = None,
    ) -> None:
        """Update the measurement information section."""
        self._clear_group(self._measurement_group)
        if not label:
            return
        self._measurement_group = QGroupBox("Measurement")
        form = QFormLayout(self._measurement_group)
        form.setSpacing(2)
        form.addRow("Label:", QLabel(label))
        if value_mm is not None:
            form.addRow("Value:", QLabel(f"{value_mm:.1f} mm"))
        if start and end:
            dx = end[0] - start[0]
            dy = end[1] - start[1]
            pixel_len = (dx**2 + dy**2) ** 0.5
            form.addRow("Pixel length:", QLabel(f"{pixel_len:.1f} px"))
        self._form.addRow(self._measurement_group)

    def update_contour_info(
        self,
        *,
        chamber: str = "",
        phase: str = "",
        point_count: int = 0,
        area_px: float | None = None,
    ) -> None:
        """Update the contour information section."""
        self._clear_group(self._contour_group)
        if not chamber and not phase:
            return
        self._contour_group = QGroupBox("Contour")
        form = QFormLayout(self._contour_group)
        form.setSpacing(2)
        if chamber:
            form.addRow("Chamber:", QLabel(chamber))
        if phase:
            form.addRow("Phase:", QLabel(phase))
        if point_count:
            form.addRow("Points:", QLabel(str(point_count)))
        if area_px is not None:
            form.addRow("Area:", QLabel(f"{area_px:.1f} px²"))
        self._form.addRow(self._contour_group)

    def clear_all(self) -> None:
        """Clear all sections."""
        self._clear_group(self._instance_group)
        self._clear_group(self._measurement_group)
        self._clear_group(self._contour_group)
        self._instance_group = None
        self._measurement_group = None
        self._contour_group = None

    def _clear_group(self, group: QGroupBox | None) -> None:
        if group is not None:
            idx = self._form.indexOf(group)
            if idx >= 0:
                self._form.removeRow(idx)
            group.deleteLater()
