"""Unit tests for the measurement summary panel."""

from __future__ import annotations

from echo_personal_tool.domain.models import (
    DopplerResults,
    LinearMeasurement,
    LvefResult,
    LvViewMetrics,
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
            a4c=LvViewMetrics(edv_ml=120.0, esv_ml=45.0),
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
    assert "Объёмы ЛЖ (Симпсон)" in text
    assert "КДО ЛЖ 4C" in text
    assert "КСО ЛЖ 4C" in text
    assert "ФВ ЛЖ" in text
    assert "62.5" in text
    assert "Метод: simpson_monoplan" in text
    assert "LV volumes (Teichholz)" in text
    assert "Linear geometry" in text
    assert "LVEDD: 50.0 mm (100.0 px)" in text


def test_measurement_panel_hides_empty_sections(qtbot) -> None:
    panel = MeasurementPanel()
    qtbot.addWidget(panel)

    panel.set_measurement_snapshot(MeasurementSnapshot())

    text = panel._summary_label.text()
    assert "—" not in text
    assert "Doppler" not in text
    assert "Объёмы ЛЖ" not in text
    assert "No measurements yet" in text


def test_measurement_panel_shows_partial_doppler_fields_only(qtbot) -> None:
    panel = MeasurementPanel()
    qtbot.addWidget(panel)

    panel.set_measurement_snapshot(MeasurementSnapshot(doppler=DopplerResults(e_cm_s=72.0)))

    text = panel._summary_label.text()
    assert "E: 72.0 cm/s" in text
    assert "A:" not in text
    assert "—" not in text


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
            doppler_measurement=None,
            contours=(),
            linear_measurements=(),
            measurement_snapshot=snapshot,
        )
    )

    assert panel._summary_label.text().startswith("Measurements")
    assert "E: 72.0 cm/s" in panel._summary_label.text()


def test_measurement_panel_shows_russian_lv_metrics_partial_ed(qtbot) -> None:
    panel = MeasurementPanel()
    qtbot.addWidget(panel)

    panel.set_measurement_snapshot(
        MeasurementSnapshot(
            lvef=LvefResult(
                a4c=LvViewMetrics(length_ed_mm=82.3, edv_ml=124.5),
            ),
        )
    )

    text = panel._summary_label.text()
    assert "Объёмы ЛЖ (Симпсон)" in text
    assert "Длина ЛЖ 4C" in text
    assert "КДО ЛЖ 4C" in text
    assert "КСО ЛЖ 4C" not in text
    assert "ФВ ЛЖ" not in text


def test_measurement_panel_shows_lvef_when_ed_es_pair_complete(qtbot) -> None:
    panel = MeasurementPanel()
    qtbot.addWidget(panel)

    panel.set_measurement_snapshot(
        MeasurementSnapshot(
            lvef=LvefResult(
                a4c=LvViewMetrics(
                    length_ed_mm=82.0,
                    length_es_mm=78.0,
                    edv_ml=120.0,
                    esv_ml=45.0,
                ),
                lvef_percent=62.5,
                method="simpson_monoplan",
            ),
        )
    )

    text = panel._summary_label.text()
    assert "КСО ЛЖ 4C" in text
    assert "ФВ ЛЖ" in text
    assert "62.5" in text


def test_measurement_panel_shows_uncalibrated_simpson_without_pixel_spacing(qtbot) -> None:
    panel = MeasurementPanel()
    qtbot.addWidget(panel)
    panel.set_measurement_snapshot(
        MeasurementSnapshot(
            lvef=LvefResult(
                a4c=LvViewMetrics(length_ed_mm=82.3, edv_ml=124.5),
            ),
            spacing_calibrated=False,
        )
    )
    text = panel._summary_label.text()
    assert "нет PixelSpacing" in text
    assert "Длина ЛЖ 4C: 82.3 px" in text
    assert "КДО ЛЖ 4C: 124.5 px³" in text
