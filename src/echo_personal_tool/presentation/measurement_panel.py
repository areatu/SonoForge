"""Right-side measurement summary panel."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from echo_personal_tool.domain.calculations.doppler_metrics import compute
from echo_personal_tool.domain.models.doppler import DopplerMeasurementDTO
from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
from echo_personal_tool.domain.models.viewer_state import ViewerState


class MeasurementPanel(QWidget):
    """Show computed measurement values for the active instance."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._measurement_snapshot: MeasurementSnapshot | None = None

        self._summary_label = QLabel()
        self._summary_label.setWordWrap(True)
        self._summary_label.setTextInteractionFlags(
            self._summary_label.textInteractionFlags()
        )

        layout = QVBoxLayout(self)
        layout.addWidget(self._summary_label)
        layout.addStretch(1)

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

    def _refresh_text(self) -> None:
        snapshot = self._measurement_snapshot
        lines = ["Measurements", ""]
        lines.extend(self._format_doppler_section(snapshot))
        lines.extend(["", *self._format_lvef_section(snapshot)])
        lines.extend(["", *self._format_teichholz_section(snapshot)])
        lines.extend(["", *self._format_linear_section(snapshot)])
        self._summary_label.setText("\n".join(lines))

    def _format_doppler_section(self, snapshot: MeasurementSnapshot | None) -> list[str]:
        lines = ["Doppler"]
        doppler = snapshot.doppler if snapshot is not None else None
        if doppler is None:
            lines.extend(
                [
                    "  E: —",
                    "  A: —",
                    "  E/A: —",
                    "  DT: —",
                    "  IVRT: —",
                    "  AT: —",
                    "  e' sept: —",
                    "  e' lat: —",
                    "  e' avg: —",
                    "  E/e': —",
                    "  VTI: —",
                    "  Vpeak: —",
                    "  Vmean: —",
                    "  PGpeak: —",
                    "  PGmean: —",
                ]
            )
            return lines

        lines.extend(
            [
                self._line("E", doppler.e_cm_s, " cm/s"),
                self._line("A", doppler.a_cm_s, " cm/s"),
                self._line("E/A", doppler.e_a_ratio, decimals=2),
                self._line("DT", doppler.dt_ms, " ms"),
                self._line("IVRT", doppler.ivrt_ms, " ms"),
                self._line("AT", doppler.at_ms, " ms"),
                self._line("e' sept", doppler.e_prime_sept_cm_s, " cm/s"),
                self._line("e' lat", doppler.e_prime_lat_cm_s, " cm/s"),
                self._line("e' avg", doppler.e_prime_avg_cm_s, " cm/s"),
                self._line("E/e'", doppler.e_over_e_prime, decimals=2),
                self._line("VTI", doppler.vti_cm, " cm"),
                self._line("Vpeak", doppler.vpeak_cm_s, " cm/s"),
                self._line("Vmean", doppler.vmean_cm_s, " cm/s"),
                self._line("PGpeak", doppler.pgpeak_mmhg, " mmHg"),
                self._line("PGmean", doppler.pgmean_mmhg, " mmHg"),
            ]
        )
        return lines

    def _format_lvef_section(self, snapshot: MeasurementSnapshot | None) -> list[str]:
        lvef = snapshot.lvef if snapshot is not None else None
        lines = ["LV volumes (Simpson)"]
        if lvef is None:
            lines.extend(["  EDV: —", "  ESV: —", "  LVEF: —", "  Method: —"])
            return lines

        lines.extend(
            [
                self._line("EDV", lvef.edv_ml, " mL"),
                self._line("ESV", lvef.esv_ml, " mL"),
                self._line("LVEF", lvef.lvef_percent, " %"),
                f"  Method: {lvef.method}",
            ]
        )
        return lines

    def _format_teichholz_section(self, snapshot: MeasurementSnapshot | None) -> list[str]:
        teichholz = snapshot.teichholz if snapshot is not None else None
        lines = ["LV volumes (Teichholz)"]
        if teichholz is None:
            lines.extend(["  EDV: —", "  ESV: —", "  LVEF: —"])
            return lines

        lines.extend(
            [
                self._line("EDV", teichholz.edv_ml, " mL"),
                self._line("ESV", teichholz.esv_ml, " mL"),
                self._line("LVEF", teichholz.lvef_percent, " %"),
            ]
        )
        return lines

    def _format_linear_section(self, snapshot: MeasurementSnapshot | None) -> list[str]:
        lines = ["Linear geometry"]
        measurements = snapshot.linear_measurements if snapshot is not None else ()
        if not measurements:
            lines.append("  —")
            return lines

        for measurement in measurements:
            lines.append(f"  {measurement.display_text()}")
        return lines

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
