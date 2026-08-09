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

from echo_personal_tool.domain.models.properties_snapshot import (
    PropertiesSnapshot,
    RegionSummary,
)
from echo_personal_tool.infrastructure.i18n import tr


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

        # Instance group
        self._instance_group = QGroupBox(tr("properties.group.instance"))
        self._instance_form = QFormLayout(self._instance_group)
        self._instance_form.setSpacing(2)
        self._form.addRow(self._instance_group)

        # Timing group
        self._timing_group = QGroupBox(tr("properties.group.timing"))
        self._timing_form = QFormLayout(self._timing_group)
        self._timing_form.setSpacing(2)
        self._form.addRow(self._timing_group)

        # Spatial group
        self._spatial_group = QGroupBox(tr("properties.group.spatial"))
        self._spatial_form = QFormLayout(self._spatial_group)
        self._spatial_form.setSpacing(2)
        self._form.addRow(self._spatial_group)

        # Ultrasound regions group
        self._regions_group = QGroupBox(tr("properties.group.regions"))
        self._regions_form = QFormLayout(self._regions_group)
        self._regions_form.setSpacing(2)
        self._form.addRow(self._regions_group)

        # Calibration status group
        self._calibration_group = QGroupBox(tr("properties.group.calibration"))
        self._calibration_form = QFormLayout(self._calibration_group)
        self._calibration_form.setSpacing(2)
        self._form.addRow(self._calibration_group)

        # Patient group
        self._patient_group = QGroupBox(tr("properties.group.patient"))
        self._patient_form = QFormLayout(self._patient_group)
        self._patient_form.setSpacing(2)
        self._form.addRow(self._patient_group)

        # Measurement group
        self._measurement_group = QGroupBox(tr("properties.group.measurement"))
        self._measurement_form = QFormLayout(self._measurement_group)
        self._measurement_form.setSpacing(2)
        self._form.addRow(self._measurement_group)

        # Contour group
        self._contour_group = QGroupBox(tr("properties.group.contour"))
        self._contour_form = QFormLayout(self._contour_group)
        self._contour_form.setSpacing(2)
        self._form.addRow(self._contour_group)

        # Hide all groups initially
        self._instance_group.hide()
        self._timing_group.hide()
        self._spatial_group.hide()
        self._regions_group.hide()
        self._calibration_group.hide()
        self._patient_group.hide()
        self._measurement_group.hide()
        self._contour_group.hide()

    def update_from_snapshot(self, snapshot: PropertiesSnapshot) -> None:
        """Update all groups from a PropertiesSnapshot."""
        self._clear_form(self._instance_form)
        self._clear_form(self._timing_form)
        self._clear_form(self._spatial_form)
        self._clear_form(self._regions_form)
        self._clear_form(self._calibration_form)
        self._clear_form(self._patient_form)

        # Instance
        self._instance_form.addRow(tr("properties.modality"), QLabel(snapshot.modality))
        if snapshot.series_description:
            self._instance_form.addRow(tr("properties.series"), QLabel(snapshot.series_description))
        if snapshot.number_of_frames > 1:
            self._instance_form.addRow(tr("properties.frames"), QLabel(str(snapshot.number_of_frames)))
        if snapshot.manufacturer:
            self._instance_form.addRow(tr("properties.manufacturer"), QLabel(snapshot.manufacturer))
        if snapshot.manufacturer_model:
            self._instance_form.addRow(tr("properties.model"), QLabel(snapshot.manufacturer_model))
        if snapshot.software_versions:
            self._instance_form.addRow(tr("properties.software"), QLabel(snapshot.software_versions))
        if snapshot.image_type:
            self._instance_form.addRow(tr("properties.image_type"), QLabel("\\".join(snapshot.image_type)))
        self._instance_group.show()

        # Timing
        if snapshot.frame_time_ms is not None:
            self._timing_form.addRow(tr("properties.frame_time"), QLabel(f"{snapshot.frame_time_ms:.1f} ms"))
        if snapshot.cine_rate_fps is not None:
            self._timing_form.addRow(tr("properties.cine_rate"), QLabel(f"{snapshot.cine_rate_fps:.1f} fps"))
        if snapshot.heart_rate_bpm is not None:
            self._timing_form.addRow(tr("properties.heart_rate"), QLabel(f"{snapshot.heart_rate_bpm:.0f} bpm"))
        ftv = tr("properties.yes") if snapshot.frame_time_vector_present else tr("properties.no")
        self._timing_form.addRow(tr("properties.frame_time_vector"), QLabel(ftv))
        if (
            snapshot.frame_time_ms is not None
            or snapshot.cine_rate_fps is not None
            or snapshot.heart_rate_bpm is not None
        ):
            self._timing_group.show()
        else:
            self._timing_group.hide()

        # Spatial
        if snapshot.pixel_spacing_mm is not None:
            row, col = snapshot.pixel_spacing_mm
            self._spatial_form.addRow(tr("properties.spacing"), QLabel(f"{row:.3f}×{col:.3f} mm"))
        if snapshot.pixel_spacing_source:
            self._spatial_form.addRow(tr("properties.source"), QLabel(snapshot.pixel_spacing_source))
        if snapshot.transducer_frequency_mhz is not None:
            self._spatial_form.addRow(
                tr("properties.transducer_freq"),
                QLabel(f"{snapshot.transducer_frequency_mhz:.1f} MHz"),
            )
        if snapshot.pixel_spacing_mm is not None or snapshot.transducer_frequency_mhz is not None:
            self._spatial_group.show()
        else:
            self._spatial_group.hide()

        # Regions
        if snapshot.regions:
            for region in snapshot.regions:
                self._add_region_row(region)
            self._regions_group.show()
        else:
            self._regions_group.hide()

        # Calibration status
        self._add_calibration_row(tr("properties.calibration.depth"), snapshot.depth_calibrated, "DICOM")
        self._add_mmode_calibration_row(snapshot)
        self._add_doppler_calibration_row(snapshot)
        self._calibration_group.show()

        # Patient
        if snapshot.patient_height_m is not None and snapshot.patient_height_m > 0:
            self._patient_form.addRow(tr("properties.height"), QLabel(f"{snapshot.patient_height_m * 100:.0f} cm"))
        if snapshot.patient_weight_kg is not None and snapshot.patient_weight_kg > 0:
            self._patient_form.addRow(tr("properties.weight"), QLabel(f"{snapshot.patient_weight_kg:.1f} kg"))
        if (
            snapshot.patient_height_m is not None
            and snapshot.patient_height_m > 0
            and snapshot.patient_weight_kg is not None
            and snapshot.patient_weight_kg > 0
        ):
            bmi = snapshot.patient_weight_kg / (snapshot.patient_height_m**2)
            self._patient_form.addRow(tr("properties.bmi"), QLabel(f"{bmi:.1f}"))
        if snapshot.bsa_m2 is not None:
            self._patient_form.addRow(tr("properties.bsa"), QLabel(f"{snapshot.bsa_m2:.2f} m²"))
        if (
            snapshot.patient_height_m is not None
            and snapshot.patient_height_m > 0
            or snapshot.patient_weight_kg is not None
            and snapshot.patient_weight_kg > 0
        ):
            self._patient_group.show()
        else:
            self._patient_group.hide()

    def _add_region_row(self, region: RegionSummary) -> None:
        """Add a region summary row to the regions group."""
        x_min, x_max, y_min, y_max = region.bounds
        label = f"[{region.index}] {region.spatial_format}"
        if region.data_type:
            label += f" ({region.data_type})"
        self._regions_form.addRow(label, QLabel(f"X[{x_min}..{x_max}] Y[{y_min}..{y_max}]"))

        parts: list[str] = []
        if region.delta_x is not None:
            parts.append(f"Δx={region.delta_x:.4f}")
        else:
            parts.append("Δx=—")
        if region.units_x is not None:
            parts.append(f"unitsX={region.units_x}")
        if region.delta_y is not None:
            parts.append(f"Δy={region.delta_y:.4f}")
        else:
            parts.append("Δy=—")
        if region.units_y is not None:
            parts.append(f"unitsY={region.units_y}")
        self._regions_form.addRow("    ", QLabel("  ".join(parts)))

        if region.ref_y0 is not None:
            self._regions_form.addRow("    ", QLabel(f"RefY0: {region.ref_y0}"))

    def _add_calibration_row(self, label: str, calibrated: bool, source: str) -> None:
        """Add a calibration status row."""
        if calibrated:
            status = tr("properties.calibration.complete", source=source)
        else:
            status = tr("properties.calibration.missing")
        self._calibration_form.addRow(f"{label}", QLabel(status))

    def _add_mmode_calibration_row(self, snapshot: PropertiesSnapshot) -> None:
        """Add M-mode calibration status row."""
        if snapshot.mmode_calibrated:
            parts = []
            if snapshot.mmode_vertical_mm_per_pixel is not None:
                parts.append(f"{snapshot.mmode_vertical_mm_per_pixel:.2f} mm/px")
            if snapshot.mmode_horizontal_ms_per_pixel is not None:
                parts.append(f"{snapshot.mmode_horizontal_ms_per_pixel:.2f} ms/px")

            source = ""
            if snapshot.mmode_has_depth_from_dicom and snapshot.mmode_has_time_from_dicom:
                source = " (DICOM)"
            elif snapshot.mmode_has_time_from_dicom:
                source = " (FrameTime)" if not snapshot.mmode_has_depth_from_dicom else ""

            status = ", ".join(parts) + source if parts else tr("properties.calibration.mmode_complete")
        elif snapshot.mmode_has_time_scale:
            status = tr("properties.calibration.mmode_partial")
        else:
            status = tr("properties.calibration.missing")
        label = QLabel(status)
        label.setObjectName("mmode_calibration")
        self._calibration_form.addRow(tr("properties.calibration.mmode"), label)

    def _add_doppler_calibration_row(self, snapshot: PropertiesSnapshot) -> None:
        """Add Doppler calibration status row."""
        if not snapshot.doppler_calibrated and not snapshot.doppler_partial:
            self._calibration_form.addRow(
                tr("properties.calibration.doppler"), QLabel(tr("properties.calibration.doppler_na"))
            )
            return
        if snapshot.doppler_calibrated:
            status = tr("properties.calibration.doppler_complete")
            if snapshot.doppler_has_time_from_dicom and snapshot.doppler_has_velocity_from_dicom:
                status += " (DICOM)"
        elif snapshot.doppler_partial:
            parts = []
            if not snapshot.doppler_has_time_from_dicom:
                parts.append(tr("properties.calibration.doppler_partial_no_time"))
            if not snapshot.doppler_has_velocity_from_dicom:
                parts.append(tr("properties.calibration.doppler_partial_no_velocity"))
            status = "Partial — " + ", ".join(parts) if parts else "Partial"
        else:
            status = tr("properties.calibration.missing")
        self._calibration_form.addRow(tr("properties.calibration.doppler"), QLabel(status))

    # Legacy API for backward compatibility
    def update_instance_info(
        self,
        *,
        modality: str = "",
        series_desc: str = "",
        frame_rate: float | None = None,
        pixel_spacing: str = "",
        number_of_frames: int = 0,
        patient_height_m: float | None = None,
        patient_weight_kg: float | None = None,
        media_format: str = "",
        frame_time_ms: float | None = None,
    ) -> None:
        """Update the instance information section (legacy API)."""
        self._clear_form(self._instance_form)
        self._clear_form(self._timing_form)
        self._clear_form(self._spatial_form)
        self._clear_form(self._regions_form)
        self._clear_form(self._calibration_form)
        self._clear_form(self._patient_form)

        if not modality and not series_desc:
            self._instance_group.hide()
            self._timing_group.hide()
            self._spatial_group.hide()
            self._regions_group.hide()
            self._calibration_group.hide()
            self._patient_group.hide()
            return

        if modality:
            self._instance_form.addRow(tr("properties.modality"), QLabel(modality))
        if media_format and media_format != "dicom":
            self._instance_form.addRow("Format:", QLabel(media_format.upper()))
        if series_desc:
            self._instance_form.addRow(tr("properties.series"), QLabel(series_desc))
        if frame_rate and frame_rate > 0:
            self._instance_form.addRow(tr("properties.cine_rate"), QLabel(f"{frame_rate:.1f} fps"))
        if frame_time_ms and frame_time_ms > 0:
            self._instance_form.addRow(tr("properties.frame_time"), QLabel(f"{frame_time_ms:.1f} ms"))
        if number_of_frames > 1:
            self._instance_form.addRow(tr("properties.frames"), QLabel(str(number_of_frames)))
        if pixel_spacing:
            self._instance_form.addRow(tr("properties.spacing"), QLabel(pixel_spacing))
        self._instance_group.show()

        # Hide new groups for legacy API
        self._timing_group.hide()
        self._spatial_group.hide()
        self._regions_group.hide()
        self._calibration_group.hide()

        # Patient
        if patient_height_m is not None and patient_height_m > 0:
            self._patient_form.addRow(tr("properties.height"), QLabel(f"{patient_height_m * 100:.0f} cm"))
        if patient_weight_kg is not None and patient_weight_kg > 0:
            self._patient_form.addRow(tr("properties.weight"), QLabel(f"{patient_weight_kg:.1f} kg"))
        if patient_height_m and patient_weight_kg and patient_height_m > 0 and patient_weight_kg > 0:
            bmi = patient_weight_kg / (patient_height_m**2)
            self._patient_form.addRow(tr("properties.bmi"), QLabel(f"{bmi:.1f}"))
        if (patient_height_m is not None and patient_height_m > 0) or (
            patient_weight_kg is not None and patient_weight_kg > 0
        ):
            self._patient_group.show()
        else:
            self._patient_group.hide()

    def update_measurement_info(
        self,
        *,
        label: str = "",
        value_mm: float | None = None,
        start: tuple[float, float] | None = None,
        end: tuple[float, float] | None = None,
    ) -> None:
        """Update the measurement information section."""
        self._clear_form(self._measurement_form)
        if not label:
            self._measurement_group.hide()
            return
        self._measurement_form.addRow("Label:", QLabel(label))
        if value_mm is not None:
            self._measurement_form.addRow("Value:", QLabel(f"{value_mm:.1f} mm"))
        if start and end:
            dx = end[0] - start[0]
            dy = end[1] - start[1]
            pixel_len = (dx**2 + dy**2) ** 0.5
            self._measurement_form.addRow("Pixel length:", QLabel(f"{pixel_len:.1f} px"))
        self._measurement_group.show()

    def update_contour_info(
        self,
        *,
        chamber: str = "",
        phase: str = "",
        point_count: int = 0,
        area_px: float | None = None,
    ) -> None:
        """Update the contour information section."""
        self._clear_form(self._contour_form)
        if not chamber and not phase:
            self._contour_group.hide()
            return
        if chamber:
            self._contour_form.addRow("Chamber:", QLabel(chamber))
        if phase:
            self._contour_form.addRow("Phase:", QLabel(phase))
        if point_count:
            self._contour_form.addRow("Points:", QLabel(str(point_count)))
        if area_px is not None:
            self._contour_form.addRow("Area:", QLabel(f"{area_px:.1f} px²"))
        self._contour_group.show()

    def clear_all(self) -> None:
        """Hide all sections."""
        self._instance_group.hide()
        self._timing_group.hide()
        self._spatial_group.hide()
        self._regions_group.hide()
        self._calibration_group.hide()
        self._patient_group.hide()
        self._measurement_group.hide()
        self._contour_group.hide()

    def _clear_form(self, form: QFormLayout) -> None:
        """Remove all rows from a form layout."""
        while form.rowCount() > 0:
            form.removeRow(0)
