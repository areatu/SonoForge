"""Unit tests for the measurement summary panel."""

from __future__ import annotations

from echo_personal_tool.domain.models import (
    DopplerIntervalMarker,
    DopplerMeasurementDTO,
    DopplerPeakMarker,
    DopplerTrace,
)
from echo_personal_tool.presentation.measurement_panel import MeasurementPanel


def test_measurement_panel_displays_doppler_raw_values(qtbot) -> None:
    panel = MeasurementPanel()
    qtbot.addWidget(panel)

    dto = DopplerMeasurementDTO(
        peaks=(DopplerPeakMarker(label="E", time_ms=120.0, velocity_cm_s=85.0),),
        intervals=(
            DopplerIntervalMarker(label="DT", start_time_ms=80.0, end_time_ms=260.0),
        ),
        traces=(DopplerTrace(label="VTI", points=((0.0, 0.0), (10.0, 2.0))),),
    )

    panel.set_doppler_measurement(dto)

    text = panel._summary_label.text()
    assert "E: 85 cm/s @ 120 ms" in text
    assert "DT: 260 ms (80-260 ms)" in text
    assert "VTI: 2 points" in text
    assert "LV geometry: —" in text


def test_measurement_panel_updates_from_viewer_state(qtbot) -> None:
    from echo_personal_tool.domain.models import ViewerState

    panel = MeasurementPanel()
    qtbot.addWidget(panel)

    dto = DopplerMeasurementDTO(
        peaks=(),
        intervals=(),
        traces=(),
    )

    panel.update_from_state(
        ViewerState(
            instance=None,
            current_frame_index=0,
            total_frames=0,
            frame_time_ms=None,
            is_playing=False,
            ed_frame_index=None,
            es_frame_index=None,
            doppler_measurement=dto,
        )
    )

    assert panel._summary_label.text().startswith("Measurements")
    assert "Doppler markers:" in panel._summary_label.text()
