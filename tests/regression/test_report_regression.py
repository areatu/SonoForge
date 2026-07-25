"""Regression tests for measurement report formatting."""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
from echo_personal_tool.domain.models.measurements import (
    DopplerResults,
    IndexedMeasurements,
    LvefResult,
    LvViewMetrics,
    MeasurementSnapshot,
    PlanimeterResult,
    TeichholzResult,
)
from echo_personal_tool.domain.services.measurement_report_formatter import (
    dedupe_linear_measurements_latest,
    format_measurement_report,
)


def _snapshot(**kwargs) -> MeasurementSnapshot:
    defaults = {"spacing_calibrated": True}
    defaults.update(kwargs)
    return MeasurementSnapshot(**defaults)


class TestFormatMeasurementReportRegression:
    """Report formatting must produce identical text for known inputs."""

    def test_empty_snapshot(self) -> None:
        result = format_measurement_report(_snapshot())
        assert result == "Нет измерений."

    def test_none_snapshot(self) -> None:
        result = format_measurement_report(None)
        assert result == "Нет измерений."

    def test_doppler_section_single_value(self) -> None:
        snap = _snapshot(doppler=DopplerResults(e_cm_s=80.0))
        result = format_measurement_report(snap)
        assert "Допплер" in result
        assert "80.0 cm/s" in result

    def test_doppler_section_multiple_values(self) -> None:
        doppler = DopplerResults(
            e_cm_s=80.0,
            a_cm_s=60.0,
            e_a_ratio=1.33,
            dt_ms=180.0,
        )
        snap = _snapshot(doppler=doppler)
        result = format_measurement_report(snap)
        assert "E: 80.0 cm/s" in result
        assert "A: 60.0 cm/s" in result
        assert "E/A: 1.33" in result
        assert "DT: 180.0 ms" in result

    def test_lvef_section_calibrated(self) -> None:
        lvef = LvefResult(
            a4c=LvViewMetrics(edv_ml=120.0, esv_ml=50.0, length_ed_mm=45.0),
            lvef_percent=58.3,
            method="simpson_biplan",
        )
        snap = _snapshot(lvef=lvef)
        result = format_measurement_report(snap)
        assert "Объёмы ЛЖ (Симпсон)" in result
        assert "58.3 %" in result
        assert "Симпсон" in result

    def test_lvef_section_uncalibrated(self) -> None:
        lvef = LvefResult(
            a4c=LvViewMetrics(edv_ml=120.0, esv_ml=50.0),
            lvef_percent=58.3,
        )
        snap = _snapshot(lvef=lvef, spacing_calibrated=False)
        result = format_measurement_report(snap)
        assert "px³" in result
        assert "нет PixelSpacing" in result

    def test_lvef_section_cm_display(self) -> None:
        lvef = LvefResult(
            a4c=LvViewMetrics(length_ed_mm=45.0),
        )
        snap = _snapshot(lvef=lvef)
        result = format_measurement_report(snap, length_display_unit="cm")
        assert "4.5 cm" in result

    def test_teichholz_section(self) -> None:
        teichholz = TeichholzResult(edv_ml=150.0, esv_ml=60.0, lvef_percent=60.0)
        snap = _snapshot(teichholz=teichholz)
        result = format_measurement_report(snap)
        assert "Объёмы ЛЖ (Teichholz)" in result
        assert "150.0 mL" in result
        assert "60.0 mL" in result
        assert "60.0 %" in result

    def test_lvm_section(self) -> None:
        snap = _snapshot(lvm_g=180.5, rwt=0.42)
        result = format_measurement_report(snap)
        assert "Масса ЛЖ" in result
        assert "180.5 g" in result
        assert "ОТС" in result
        assert "0.42" in result

    def test_diastology_section(self) -> None:
        snap = _snapshot(diastology_grade="Нарушение релаксации")
        result = format_measurement_report(snap)
        assert "Диастолическая функция" in result
        assert "Нарушение релаксации" in result

    def test_linear_section(self) -> None:
        measurements = (
            LinearMeasurement(label="IVSd", pixel_length=10.0, millimeter_length=8.5),
            LinearMeasurement(label="LVEDD", pixel_length=20.0, millimeter_length=48.0),
        )
        snap = _snapshot(linear_measurements=measurements)
        result = format_measurement_report(snap)
        assert "Линейные измерения" in result
        assert "8.5 mm" in result
        assert "48.0 mm" in result

    def test_linear_section_no_mm(self) -> None:
        measurements = (
            LinearMeasurement(label="IVSd", pixel_length=10.0, millimeter_length=None),
        )
        snap = _snapshot(linear_measurements=measurements)
        result = format_measurement_report(snap)
        assert "10.0 px" in result

    def test_linear_section_cm_unit(self) -> None:
        measurements = (
            LinearMeasurement(label="LVEDD", pixel_length=20.0, millimeter_length=48.0),
        )
        snap = _snapshot(linear_measurements=measurements)
        result = format_measurement_report(snap, length_display_unit="cm")
        assert "4.80 cm" in result

    def test_planimeter_section(self) -> None:
        planimeter = (
            PlanimeterResult(label="S LV", kind="area", value=25.3, unit="cm²"),
            PlanimeterResult(label="V LV", kind="volume", value=120.5, unit="mL"),
        )
        snap = _snapshot(planimeter=planimeter)
        result = format_measurement_report(snap)
        assert "Планиметрия" in result
        assert "25.30 cm²" in result
        assert "120.5 mL" in result

    def test_indexed_section(self) -> None:
        indexed = IndexedMeasurements(
            bsa_m2=1.85,
            simpson_edvi_ml_m2=65.0,
            simpson_esvi_ml_m2=27.0,
        )
        snap = _snapshot(indexed=indexed, height_cm=175.0, weight_kg=80.0)
        result = format_measurement_report(snap)
        assert "Индексированные (BSA)" in result
        assert "1.85 m²" in result
        assert "175 cm" in result
        assert "80 kg" in result

    def test_full_report_structure(self) -> None:
        snap = _snapshot(
            doppler=DopplerResults(e_cm_s=80.0),
            lvef=LvefResult(lvef_percent=55.0),
            lvm_g=160.0,
            linear_measurements=(
                LinearMeasurement(label="IVSd", pixel_length=10.0, millimeter_length=9.0),
            ),
        )
        result = format_measurement_report(snap)
        lines = result.split("\n")
        assert lines[0] == "Результаты измерений"
        assert "" in lines  # Blank separator between sections

    def test_no_optional_lines_hidden(self) -> None:
        snap = _snapshot(doppler=DopplerResults())
        result = format_measurement_report(snap)
        assert result == "Нет измерений."


class TestDedupeLinearMeasurementsRegression:
    """dedupe_linear_measurements_latest keeps last per label."""

    def test_single_measurement(self) -> None:
        m = LinearMeasurement(label="IVSd", pixel_length=10.0, millimeter_length=9.0)
        result = dedupe_linear_measurements_latest((m,))
        assert len(result) == 1

    def test_duplicate_labels_keeps_last(self) -> None:
        m1 = LinearMeasurement(label="IVSd", pixel_length=10.0, millimeter_length=8.0)
        m2 = LinearMeasurement(label="IVSd", pixel_length=12.0, millimeter_length=9.5)
        result = dedupe_linear_measurements_latest((m1, m2))
        assert len(result) == 1
        assert result[0].millimeter_length == pytest.approx(9.5)

    def test_distinct_labels_kept(self) -> None:
        m1 = LinearMeasurement(label="IVSd", pixel_length=10.0, millimeter_length=8.0)
        m2 = LinearMeasurement(label="LVEDD", pixel_length=20.0, millimeter_length=48.0)
        result = dedupe_linear_measurements_latest((m1, m2))
        assert len(result) == 2

    def test_empty_measurements(self) -> None:
        result = dedupe_linear_measurements_latest(())
        assert len(result) == 0
