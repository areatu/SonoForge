"""Unit tests for measurement results overlay formatter."""

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
from echo_personal_tool.domain.services.measurement_results_formatter import (
    _append,
    _best_lav_index,
    _get_norm_store,
    _html_append,
    _indexed_linear_label,
    _is_outside,
    format_results_overlay,
    format_results_overlay_html,
    invalidate_norm_cache,
)


def _snap(**kwargs) -> MeasurementSnapshot:
    return MeasurementSnapshot(**kwargs)


class TestAppend:
    def test_appends_when_value_not_none(self) -> None:
        lines: list[str] = []
        _append(lines, "E", 80.0, "cm/s")
        assert len(lines) == 1
        assert "80" in lines[0]
        assert "cm/s" in lines[0]

    def test_skips_none_value(self) -> None:
        lines: list[str] = []
        _append(lines, "E", None, "cm/s")
        assert len(lines) == 0

    def test_catalog_measurement_id_decimals(self) -> None:
        lines: list[str] = []
        _append(lines, "DVI", 1.333, "", measurement_id="av.dvi")
        assert "1.33" in lines[0]

    def test_empty_suffix(self) -> None:
        lines: list[str] = []
        _append(lines, "E/A", 1.5, "")
        assert lines[0].endswith("1.5")


class TestIsOutside:
    def test_none_norm_returns_false(self) -> None:
        assert _is_outside(None, 100.0) is False

    def test_within_range(self) -> None:
        norm = type("Norm", (), {"low": 50.0, "high": 100.0})()
        assert _is_outside(norm, 75.0) is False

    def test_below_low(self) -> None:
        norm = type("Norm", (), {"low": 50.0, "high": 100.0})()
        assert _is_outside(norm, 40.0) is True

    def test_above_high(self) -> None:
        norm = type("Norm", (), {"low": 50.0, "high": 100.0})()
        assert _is_outside(norm, 110.0) is True

    def test_no_low(self) -> None:
        norm = type("Norm", (), {"low": None, "high": 100.0})()
        assert _is_outside(norm, 10.0) is False
        assert _is_outside(norm, 110.0) is True

    def test_no_high(self) -> None:
        norm = type("Norm", (), {"low": 50.0, "high": None})()
        assert _is_outside(norm, 200.0) is False
        assert _is_outside(norm, 10.0) is True


class TestBestLavIndex:
    def test_unconfirmed_biplane_index_falls_through_to_4c(self) -> None:
        snapshot = MeasurementSnapshot(
            indexed=IndexedMeasurements(bsa_m2=1.8, lav_bi_index_ml_m2=30.0, lav_4c_index_ml_m2=33.0),
            la_simpson=ChamberSimpsonResult(
                chamber="LA",
                method="simpson_mean_monoplan",
                a4c=LvViewMetrics(esv_ml=60.0),
                a2c=LvViewMetrics(esv_ml=66.0),
            ),
        )
        assert _best_lav_index(snapshot) == 33.0

    def test_confirmed_biplane_index_is_preferred(self) -> None:
        snapshot = MeasurementSnapshot(
            indexed=IndexedMeasurements(bsa_m2=1.8, lav_bi_index_ml_m2=30.0, lav_4c_index_ml_m2=33.0),
            la_simpson=ChamberSimpsonResult(
                chamber="LA",
                method="simpson_biplan",
                biplane_es_ml=55.0,
                biplane_verified=True,
            ),
        )
        assert _best_lav_index(snapshot) == 30.0

    def test_returns_none_when_all_none(self) -> None:
        snapshot = MeasurementSnapshot(indexed=IndexedMeasurements(bsa_m2=1.8))
        assert _best_lav_index(snapshot) is None


class TestIndexedLinearLabel:
    def test_known_label(self) -> None:
        result = _indexed_linear_label("ivsd")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_unknown_label(self) -> None:
        result = _indexed_linear_label("XYZ")
        assert "XYZ" in result


class TestFormatResultsOverlay:
    def test_none_snapshot(self) -> None:
        assert format_results_overlay(None) == ""

    def test_empty_snapshot(self) -> None:
        assert format_results_overlay(_snap()) == ""

    def test_with_doppler(self) -> None:
        snap = _snap(doppler=DopplerResults(e_cm_s=80.0, a_cm_s=60.0))
        result = format_results_overlay(snap)
        assert "E: 80 cm/s" in result

    def test_with_lvef(self) -> None:
        lvef = LvefResult(a4c=LvViewMetrics(edv_ml=120.0, esv_ml=50.0), lvef_percent=58.3)
        snap = _snap(lvef=lvef)
        result = format_results_overlay(snap)
        assert "58 %" in result

    def test_with_teichholz(self) -> None:
        snap = _snap(teichholz=TeichholzResult(edv_ml=130.0, esv_ml=55.0, lvef_percent=57.7))
        result = format_results_overlay(snap)
        assert "130 mL" in result

    def test_with_linear(self) -> None:
        m = LinearMeasurement(label="IVSd", pixel_length=10, millimeter_length=9.0)
        snap = _snap(linear_measurements=(m,))
        result = format_results_overlay(snap)
        assert "9" in result

    @pytest.mark.parametrize("label", ["%D", "%S"])
    def test_percent_labels_render_with_percent_unit(self, label: str) -> None:
        m = LinearMeasurement(label=label, pixel_length=0, millimeter_length=45.0)
        snap = _snap(linear_measurements=(m,))
        result = format_results_overlay(snap)
        assert "45.0%" in result
        assert "mm" not in result
        assert "стеноз" not in result

    def test_with_planimeter(self) -> None:
        p = PlanimeterResult(label="Area", kind="area", value=25.0, unit="cm²")
        snap = _snap(planimeter=(p,))
        result = format_results_overlay(snap)
        assert "25.0" in result

    def test_amplitude_only_overrides_time(self) -> None:
        snap = _snap(doppler=DopplerResults(dt_ms=200.0))
        result = format_results_overlay(snap, amplitude_only=True)
        # amplitude_only=True → time_calibrated=False → dt not shown
        assert "200.0" not in result

    def test_lvm_g(self) -> None:
        snap = _snap(lvm_g=185.0)
        result = format_results_overlay(snap)
        assert "185 g" in result

    def test_rwt(self) -> None:
        snap = _snap(rwt=0.42)
        result = format_results_overlay(snap)
        assert "0.42" in result

    def test_rv_fac(self) -> None:
        snap = _snap(rv_fac_percent=45.0)
        result = format_results_overlay(snap)
        assert "45 %" in result

    def test_diastology_grade(self) -> None:
        snap = _snap(diastology_grade="Grade II")
        result = format_results_overlay(snap)
        assert "Grade II" in result

    def test_spacing_uncalibrated_keeps_pixel_values(self) -> None:
        lvef = LvefResult(a4c=LvViewMetrics(edv_ml=100.0), lvef_percent=55.0)
        snap = _snap(lvef=lvef, spacing_calibrated=False)
        result = format_results_overlay(snap)
        assert "100000 px³" in result
        assert "100 mL" not in result

    def test_uncalibrated_atrial_area_keeps_pixel_value(self) -> None:
        la = ChamberSimpsonResult(chamber="LA", area_cm2=20.0)
        ra = ChamberSimpsonResult(chamber="RA", area_cm2=10.0)
        snap = _snap(la_simpson=la, ra_simpson=ra, spacing_calibrated=False)
        result = format_results_overlay(snap)
        assert "2000.00 px²" in result
        assert "1000.00 px²" in result
        assert "cm²" not in result

    def test_calibrated_atrial_area_stays_cm2(self) -> None:
        la = ChamberSimpsonResult(chamber="LA", area_cm2=20.0)
        snap = _snap(la_simpson=la, spacing_calibrated=True)
        result = format_results_overlay(snap)
        assert "20.00 cm²" in result


class TestFormatResultsOverlayHtml:
    def test_none_snapshot(self) -> None:
        assert format_results_overlay_html(None) == ""

    def test_with_doppler(self) -> None:
        snap = _snap(doppler=DopplerResults(e_cm_s=80.0, a_cm_s=60.0))
        result = format_results_overlay_html(snap)
        assert ">80<" in result
        assert "<br>" in result

    def test_with_lvef(self) -> None:
        lvef = LvefResult(a4c=LvViewMetrics(edv_ml=120.0), lvef_percent=58.3)
        snap = _snap(lvef=lvef)
        result = format_results_overlay_html(snap)
        assert ">58<" in result

    def test_with_linear_mm(self) -> None:
        m = LinearMeasurement(label="IVSd", pixel_length=10, millimeter_length=9.0)
        snap = _snap(linear_measurements=(m,))
        result = format_results_overlay_html(snap)
        assert "9" in result

    def test_with_linear_px_only(self) -> None:
        m = LinearMeasurement(label="IVSd", pixel_length=10, millimeter_length=None)
        snap = _snap(linear_measurements=(m,))
        result = format_results_overlay_html(snap)
        assert "px" in result

    def test_with_la_simpson(self) -> None:
        la = ChamberSimpsonResult(chamber="LA", a4c=LvViewMetrics(esv_ml=45.0), area_cm2=22.5)
        snap = _snap(la_simpson=la)
        result = format_results_overlay_html(snap)
        assert ">45<" in result

    def test_with_ra_simpson(self) -> None:
        ra = ChamberSimpsonResult(chamber="RA", area_cm2=18.0)
        snap = _snap(ra_simpson=ra)
        result = format_results_overlay_html(snap)
        assert "18.0" in result

    def test_with_indexed(self) -> None:
        from echo_personal_tool.domain.models.measurements import IndexedMeasurements

        idx = IndexedMeasurements(bsa_m2=1.85, lvmi_g_m2=95.0)
        snap = _snap(indexed=idx)
        result = format_results_overlay_html(snap)
        assert ">95<" in result

    def test_amplitude_only(self) -> None:
        snap = _snap(doppler=DopplerResults(dt_ms=200.0))
        result = format_results_overlay_html(snap, amplitude_only=True)
        assert "200.0" not in result


class TestHtmlAppend:
    def test_skips_none(self) -> None:
        parts: list[str] = []
        _html_append(parts, "E", None, "cm/s")
        assert len(parts) == 0

    def test_appends_value(self) -> None:
        parts: list[str] = []
        _html_append(parts, "E", 80.0, "cm/s")
        assert len(parts) == 1
        assert "80.0" in parts[0]

    def test_with_param_id(self) -> None:
        parts: list[str] = []
        _html_append(parts, "E", 80.0, "cm/s", param_id="ea_ratio")
        assert "ea_ratio" in parts[0]


class TestInvalidateNormCache:
    def test_next_access_reloads_the_norm_store(self) -> None:
        first = _get_norm_store()
        assert _get_norm_store() is first, "the store is cached between calls"

        invalidate_norm_cache()

        assert _get_norm_store() is not first, "after invalidation the norms are read again"
