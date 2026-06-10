"""Unit tests for the measurement summary panel."""

from __future__ import annotations

from echo_personal_tool.domain.models import (
    DopplerResults,
    LinearMeasurement,
    LvefResult,
    MeasurementSnapshot,
    TeichholzResult,
    ViewerState,
)
from echo_personal_tool.presentation.measurement_panel import MeasurementPanel


def test_measurement_panel_displays_computed_snapshot(qtbot) -> None:
    panel = MeasurementPanel()
    qtbot.addWidget(panel)

    snapshot = MeasurementSnapshot(
        doppler=DopplerResults(
            e_cm_s=85.0,
            a_cm_s=60.0,
            e_a_ratio=1.4,
            dt_ms=180.0,
            ivrt_ms=80.0,
            at_ms=120.0,
            e_prime_sept_cm_s=8.0,
            e_prime_lat_cm_s=10.0,
            e_prime_avg_cm_s=9.0,
            e_over_e_prime=9.4,
            vti_cm=22.5,
            vpeak_cm_s=250.0,
            vmean_cm_s=150.0,
            pgpeak_mmhg=25.0,
            pgmean_mmhg=12.0,
        ),
        lvef=LvefResult(
            edv_ml=120.0,
            esv_ml=45.0,
            lvef_percent=62.5,
            method="simpson_monoplan",
        ),
        teichholz=TeichholzResult(edv_ml=110.0, esv_ml=50.0, lvef_percent=54.5),
        linear_measurements=(
            LinearMeasurement(
                label="LVEDD",
                pixel_length=100.0,
                millimeter_length=50.0,
            ),
            LinearMeasurement(
                label="LVESD",
                pixel_length=80.0,
                millimeter_length=40.0,
            ),
        ),
    )

    panel.set_measurement_snapshot(snapshot)

    text = panel._summary_label.text()
    assert "Doppler" in text
    assert "E: 85.0 cm/s" in text
    assert "E/A: 1.40" in text
    assert "PGpeak: 25.0 mmHg" in text
    assert "LV volumes (Simpson)" in text
    assert "Method: simpson_monoplan" in text
    assert "LV volumes (Teichholz)" in text
    assert "Linear geometry" in text
    assert "LVEDD: 50.0 mm (100.0 px)" in text


def test_measurement_panel_updates_from_viewer_state(qtbot) -> None:
    panel = MeasurementPanel()
    qtbot.addWidget(panel)

    snapshot = MeasurementSnapshot(doppler=DopplerResults(e_cm_s=72.0))

    panel.update_from_state(
        ViewerState(
            instance=None,
            current_frame_index=0,
            total_frames=0,
            frame_time_ms=None,
            is_playing=False,
            ed_frame_index=None,
            es_frame_index=None,
            doppler_measurement=None,
            contours=(),
            linear_measurements=(),
            measurement_snapshot=snapshot,
        )
    )

    assert panel._summary_label.text().startswith("Measurements")
    assert "E: 72.0 cm/s" in panel._summary_label.text()
