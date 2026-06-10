"""Right-side measurement summary panel."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from echo_personal_tool.domain.models.doppler import DopplerMeasurementDTO
from echo_personal_tool.domain.models.viewer_state import ViewerState


class MeasurementPanel(QWidget):
    """Show raw measurement values for the active instance."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._measurement: DopplerMeasurementDTO | None = None

        self._summary_label = QLabel()
        self._summary_label.setWordWrap(True)
        self._summary_label.setTextInteractionFlags(
            self._summary_label.textInteractionFlags()
        )

        layout = QVBoxLayout(self)
        layout.addWidget(self._summary_label)
        layout.addStretch(1)

        self._refresh_text()

    def set_doppler_measurement(self, dto: DopplerMeasurementDTO | None) -> None:
        self._measurement = dto
        self._refresh_text()

    def update_from_state(self, state: object) -> None:
        if not isinstance(state, ViewerState):
            return
        self.set_doppler_measurement(state.doppler_measurement)

    def _refresh_text(self) -> None:
        lines = ["Measurements", "", "Doppler markers:"]
        measurement = self._measurement
        if measurement is None:
            lines.append("  None")
        else:
            lines.extend(self._format_measurement(measurement))
        lines.extend(["", "LV geometry: —"])
        self._summary_label.setText("\n".join(lines))

    def _format_measurement(self, dto: DopplerMeasurementDTO) -> list[str]:
        lines: list[str] = []

        lines.append("  Peaks:")
        if dto.peaks:
            for peak in dto.peaks:
                lines.append(
                    f"    {peak.label}: {peak.velocity_cm_s:g} cm/s @ {peak.time_ms:g} ms"
                )
        else:
            lines.append("    None")

        lines.append("  Intervals:")
        if dto.intervals:
            for interval in dto.intervals:
                start = f"{interval.start_time_ms:g}"
                end = f"{interval.end_time_ms:g}"
                lines.append(f"    {interval.label}: {end} ms ({start}-{end} ms)")
        else:
            lines.append("    None")

        lines.append("  Traces:")
        if dto.traces:
            for trace in dto.traces:
                lines.append(f"    {trace.label}: {len(trace.points)} points")
        else:
            lines.append("    None")

        return lines
