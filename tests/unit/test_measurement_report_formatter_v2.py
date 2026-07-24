"""Unit tests for measurement report formatter."""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
from echo_personal_tool.domain.models.measurements import (
    ChamberSimpsonResult,
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


def _snap(**kwargs) -> MeasurementSnapshot:
    return MeasurementSnapshot(**kwargs)


class TestDedupeLinearMeasurementsLatest:
    def test_deduplicates_by_label(self) -> None:
        m1 = LinearMeasurement(label="IVSd", pixel_length=10, millimeter_length=8.0)
        m2 = LinearMeasurement(label="IVSd", pixel_length=12, millimeter_length=10.0)
        m3 = LinearMeasurement(label="LVEDD", pixel_length=20, millimeter_length=16.0)
        result = dedupe_linear_measurements_latest((m1, m2, m3))
        assert len(result) == 2
        labels = {m.label for m in result}
        assert labels == {"IVSd", "LVEDD"}

    def test_empty_input(self) -> None:
        assert dedupe_linear_measurements_latest(()) == ()

    def test_keeps_last_occurrence(self) -> None:
        m1 = LinearMeasurement(label="IVSd", pixel_length=10, millimeter_length=8.0)
        m2 = LinearMeasurement(label="IVSd", pixel_length=12, millimeter_length=10.0)
        result = dedupe_linear_measurements_latest((m1, m2))
        assert result[0].millimeter_length == 10.0


class TestFormatMeasurementReport:
    def test_none_snapshot(self) -> None:
        assert format_measurement_report(None) == "Нет измерений."

    def test_empty_snapshot(self) -> None:
        result = format_measurement_report(_snap())
        assert "Нет измерений." in result

    def test_with_doppler(self) -> None:
        snap = _snap(doppler=DopplerResults(e_cm_s=80.0, a_cm_s=60.0, e_a_ratio=1.33))
        result = format_measurement_report(snap)
        assert "Допплер" in result
        assert "80.0" in result

    def test_with_lvef(self) -> None:
        lvef = LvefResult(
            a4c=LvViewMetrics(edv_ml=120.0, esv_ml=50.0),
            lvef_percent=58.3,
            method="simpson_biplan",
        )
        snap = _snap(lvef=lvef, spacing_calibrated=True)
        result = format_measurement_report(snap)
        assert "Симпсон" in result
        assert "58.3" in result
        assert "simpson_biplan" in result

    def test_with_teichholz(self) -> None:
        snap = _snap(teichholz=TeichholzResult(edv_ml=130.0, esv_ml=55.0, lvef_percent=57.7))
        result = format_measurement_report(snap)
        assert "Teichholz" in result
        assert "130.0" in result

    def test_with_la_simpson(self) -> None:
        la = ChamberSimpsonResult(
            chamber="LA",
            a4c=LvViewMetrics(esv_ml=45.0),
            area_cm2=22.5,
        )
        snap = _snap(la_simpson=la, spacing_calibrated=True)
        result = format_measurement_report(snap)
        assert "Левое предсердие" in result

    def test_with_la_volume_fallback(self) -> None:
        from echo_personal_tool.domain.models.measurements import LaVolumeResult
        snap = _snap(la_volume=LaVolumeResult(volume_ml=50.0))
        result = format_measurement_report(snap)
        assert "Левое предсердие" in result

    def test_with_ra_simpson(self) -> None:
        ra = ChamberSimpsonResult(chamber="RA", area_cm2=18.0)
        snap = _snap(ra_simpson=ra, spacing_calibrated=True)
        result = format_measurement_report(snap)
        assert "Правое предсердие" in result

    def test_with_rv_fac(self) -> None:
        snap = _snap(rv_fac_percent=45.0)
        result = format_measurement_report(snap)
        assert "Правый желудочек" in result
        assert "45.0" in result

    def test_with_rv_simpson(self) -> None:
        rv = ChamberSimpsonResult(chamber="RV", max_volume_ml=90.0)
        snap = _snap(rv_simpson=rv)
        result = format_measurement_report(snap)
        assert "Объём ПЖ" in result

    def test_with_lvm(self) -> None:
        snap = _snap(lvm_g=185.0, rwt=0.42)
        result = format_measurement_report(snap)
        assert "Масса ЛЖ" in result
        assert "185.0" in result
        assert "0.42" in result

    def test_with_diastology(self) -> None:
        snap = _snap(diastology_grade="Grade II")
        result = format_measurement_report(snap)
        assert "Диастолическая функция" in result
        assert "Grade II" in result

    def test_with_linear_measurements(self) -> None:
        m = LinearMeasurement(label="IVSd", pixel_length=10, millimeter_length=9.0)
        snap = _snap(linear_measurements=(m,))
        result = format_measurement_report(snap)
        assert "Линейные измерения" in result

    def test_with_planimeter(self) -> None:
        p = PlanimeterResult(label="Площадь", kind="area", value=25.0, unit="cm²")
        snap = _snap(planimeter=(p,))
        result = format_measurement_report(snap)
        assert "Планиметрия" in result

    def test_with_indexed(self) -> None:
        idx = IndexedMeasurements(bsa_m2=1.85, lvmi_g_m2=95.0)
        snap = _snap(indexed=idx, height_cm=175.0, weight_kg=80.0)
        result = format_measurement_report(snap)
        assert "Индексированные" in result
        assert "175" in result

    def test_spacing_uncalibrated(self) -> None:
        lvef = LvefResult(a4c=LvViewMetrics(edv_ml=100.0), lvef_percent=55.0)
        snap = _snap(lvef=lvef, spacing_calibrated=False)
        result = format_measurement_report(snap)
        assert "px³" in result
