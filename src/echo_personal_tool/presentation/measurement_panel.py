"""Right-side measurement summary panel."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget

from echo_personal_tool.domain.calculations.doppler_metrics import compute
from echo_personal_tool.domain.models.doppler import DopplerMeasurementDTO
from echo_personal_tool.domain.models.measurements import LvViewMetrics, MeasurementSnapshot
from echo_personal_tool.domain.models.viewer_state import ViewerState
from echo_personal_tool.presentation.measurement_tools_panel import MeasurementToolsPanel


class MeasurementPanel(QWidget):
    """Show computed measurement values for the active instance."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._measurement_snapshot: MeasurementSnapshot | None = None

        self.tools = MeasurementToolsPanel()

        tools_header = QLabel("Measurement tools")
        tools_header.setStyleSheet("font-weight: bold; font-size: 13px;")

        self._summary_label = QLabel()
        self._summary_label.setWordWrap(True)
        self._summary_label.setTextInteractionFlags(
            self._summary_label.textInteractionFlags()
        )

        summary_container = QWidget()
        summary_layout = QVBoxLayout(summary_container)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.addWidget(self._summary_label)

        summary_scroll = QScrollArea()
        summary_scroll.setWidgetResizable(True)
        summary_scroll.setFrameShape(QFrame.Shape.NoFrame)
        summary_scroll.setWidget(summary_container)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(tools_header)
        layout.addWidget(self.tools)
        layout.addWidget(summary_scroll, stretch=1)

        self.setMinimumWidth(300)
        self.tools.setMinimumHeight(280)

        self._refresh_text()

    def set_measurement_snapshot(self, snapshot: MeasurementSnapshot | None) -> None:
        self._measurement_snapshot = snapshot
        self._refresh_text()

    def set_doppler_measurement(self, dto: DopplerMeasurementDTO | None) -> None:
        if dto is None:
            self.set_measurement_snapshot(None)
            return
        self.set_measurement_snapshot(MeasurementSnapshot(doppler=compute(dto)))

    def update_from_state(self, state: object) -> None:
        if not isinstance(state, ViewerState):
            return
        self.set_measurement_snapshot(state.measurement_snapshot)
        spacing = state.effective_pixel_spacing
        if spacing is not None:
            source = state.pixel_spacing_source_label or "unknown"
            self.setToolTip(
                f"Pixel spacing: {spacing[0]:.3f} × {spacing[1]:.3f} mm/px ({source})"
            )
        else:
            self.setToolTip("Pixel spacing: — (K — ручная калибровка по шкале глубины)")

    def _refresh_text(self) -> None:
        snapshot = self._measurement_snapshot
        sections: list[list[str]] = []

        doppler_lines = self._format_doppler_section(snapshot)
        if doppler_lines:
            sections.append(doppler_lines)

        lvef_lines = self._format_lvef_section(snapshot)
        if lvef_lines:
            sections.append(lvef_lines)

        teichholz_lines = self._format_teichholz_section(snapshot)
        if teichholz_lines:
            sections.append(teichholz_lines)

        la_lines = self._format_la_section(snapshot)
        if la_lines:
            sections.append(la_lines)

        linear_lines = self._format_linear_section(snapshot)
        if linear_lines:
            sections.append(linear_lines)

        if not sections:
            self._summary_label.setText("Measurements\n\n  No measurements yet")
            return

        lines = ["Measurements"]
        for index, section in enumerate(sections):
            if index > 0:
                lines.append("")
            lines.extend(section)
        self._summary_label.setText("\n".join(lines))

    def _format_doppler_section(self, snapshot: MeasurementSnapshot | None) -> list[str]:
        doppler = snapshot.doppler if snapshot is not None else None
        if doppler is None:
            return []

        field_lines = [
            self._optional_line("E", doppler.e_cm_s, " cm/s"),
            self._optional_line("A", doppler.a_cm_s, " cm/s"),
            self._optional_line("E/A", doppler.e_a_ratio, decimals=2),
            self._optional_line("DT", doppler.dt_ms, " ms"),
            self._optional_line("IVRT", doppler.ivrt_ms, " ms"),
            self._optional_line("AT", doppler.at_ms, " ms"),
            self._optional_line("e' sept", doppler.e_prime_sept_cm_s, " cm/s"),
            self._optional_line("e' lat", doppler.e_prime_lat_cm_s, " cm/s"),
            self._optional_line("e' avg", doppler.e_prime_avg_cm_s, " cm/s"),
            self._optional_line("E/e'", doppler.e_over_e_prime, decimals=2),
            self._optional_line("VTI", doppler.vti_cm, " cm"),
            self._optional_line("Vpeak", doppler.vpeak_cm_s, " cm/s"),
            self._optional_line("Vmean", doppler.vmean_cm_s, " cm/s"),
            self._optional_line("PGpeak", doppler.pgpeak_mmhg, " mmHg"),
            self._optional_line("PGmean", doppler.pgmean_mmhg, " mmHg"),
        ]
        lines = [line for line in field_lines if line is not None]
        if not lines:
            return []
        return ["Doppler", *lines]

    def _format_lvef_section(self, snapshot: MeasurementSnapshot | None) -> list[str]:
        lvef = snapshot.lvef if snapshot is not None else None
        if lvef is None:
            return []

        lines = ["Объёмы ЛЖ (Симпсон)"]
        if snapshot is not None and not snapshot.spacing_calibrated:
            lines.append("  (нет PixelSpacing — длина в px, объём в px³)")

        def append_view(view_label: str, metrics: LvViewMetrics | None) -> None:
            if metrics is None:
                return
            length = (
                metrics.length_ed_mm
                if metrics.length_ed_mm is not None
                else metrics.length_es_mm
            )
            length_suffix = " mm" if snapshot is None or snapshot.spacing_calibrated else " px"
            volume_suffix = " mL" if snapshot is None or snapshot.spacing_calibrated else " px³"
            length_line = self._optional_line(f"Длина ЛЖ {view_label}", length, length_suffix)
            if length_line:
                lines.append(length_line)
            kdo = self._optional_line(f"КДО ЛЖ {view_label}", metrics.edv_ml, volume_suffix)
            if kdo:
                lines.append(kdo)
            kso = self._optional_line(f"КСО ЛЖ {view_label}", metrics.esv_ml, volume_suffix)
            if kso:
                lines.append(kso)

        append_view("4C", lvef.a4c)
        append_view("2C", lvef.a2c)

        if lvef.lvef_percent is not None:
            lines.append(self._line("ФВ ЛЖ", lvef.lvef_percent, " %"))
        if lvef.method is not None:
            lines.append(f"  Метод: {lvef.method}")

        return lines if len(lines) > 1 else []

    def _format_teichholz_section(self, snapshot: MeasurementSnapshot | None) -> list[str]:
        teichholz = snapshot.teichholz if snapshot is not None else None
        if teichholz is None:
            return []

        return [
            "LV volumes (Teichholz)",
            self._line("EDV", teichholz.edv_ml, " mL"),
            self._line("ESV", teichholz.esv_ml, " mL"),
            self._line("LVEF", teichholz.lvef_percent, " %"),
        ]

    def _format_la_section(self, snapshot: MeasurementSnapshot | None) -> list[str]:
        la = snapshot.la_volume if snapshot is not None else None
        if la is None:
            return []

        lines = ["Left atrium (area-length)"]
        area_line = self._optional_line("LA area", la.area_cm2, " cm²")
        length_line = self._optional_line("LA length", la.length_cm, " cm")
        volume_line = self._optional_line("LAV", la.volume_ml, " mL")
        for line in (area_line, length_line, volume_line):
            if line is not None:
                lines.append(line)
        if len(lines) == 1:
            return []
        return lines

    def _format_linear_section(self, snapshot: MeasurementSnapshot | None) -> list[str]:
        measurements = snapshot.linear_measurements if snapshot is not None else ()
        if not measurements:
            return []

        return [
            "Linear geometry",
            *(f"  {measurement.display_text()}" for measurement in measurements),
        ]

    def _optional_line(
        self,
        label: str,
        value: float | None,
        suffix: str = "",
        *,
        decimals: int = 1,
    ) -> str | None:
        if value is None:
            return None
        return self._line(label, value, suffix, decimals=decimals)

    def _line(
        self,
        label: str,
        value: float | None,
        suffix: str = "",
        *,
        decimals: int = 1,
    ) -> str:
        if value is None:
            return f"  {label}: —"
        return f"  {label}: {value:.{decimals}f}{suffix}"
