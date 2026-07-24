"""Unit tests for measurement results overlay formatter."""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
from echo_personal_tool.domain.models.measurements import (
    ChamberSimpsonResult,
    DopplerResults,
    LvefResult,
    LvViewMetrics,
    MeasurementSnapshot,
    PlanimeterResult,
    TeichholzResult,
)
from echo_personal_tool.domain.services.measurement_results_formatter import (
    _append,
    _best_lav_index,
    _html_append,
    _is_outside,
    _indexed_linear_label,
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
        assert "80.0" in lines[0]
        assert "cm/s" in lines[0]

    def test_skips_none_value(self) -> None:
        lines: list[str] = []
        _append(lines, "E", None, "cm/s")
        assert len(lines) == 0

    def test_custom_decimals(self) -> None:
        lines: list[str] = []
        _append(lines, "E/A", 1.333, "", decimals=2)
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
    def test_returns_first_available(self) -> None:
        idx = type("Idx", (), {
            "lav_bi_index_ml_m2": 30.0,
            "lav_area_length_index_ml_m2": None,
            "lav_4c_index_ml_m2": None,
        })()
        assert _best_lav_index(idx) == 30.0

    def test_returns_none_when_all_none(self) -> None:
        idx = type("Idx", (), {
            "lav_bi_index_ml_m2": None,
            "lav_area_length_index_ml_m2": None,
            "lav_4c_index_ml_m2": None,
        })()
        assert _best_lav_index(idx) is None


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
        assert "80.0" in result

    def test_with_lvef(self) -> None:
        lvef = LvefResult(a4c=LvViewMetrics(edv_ml=120.0, esv_ml=50.0), lvef_percent=58.3)
        snap = _snap(lvef=lvef)
        result = format_results_overlay(snap)
        assert "58.3" in result

    def test_with_teichholz(self) -> None:
        snap = _snap(teichholz=TeichholzResult(edv_ml=130.0, esv_ml=55.0, lvef_percent=57.7))
        result = format_results_overlay(snap)
        assert "130.0" in result

    def test_with_linear(self) -> None:
        m = LinearMeasurement(label="IVSd", pixel_length=10, millimeter_length=9.0)
        snap = _snap(linear_measurements=(m,))
        result = format_results_overlay(snap)
        assert "9.0" in result

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
        assert "185.0" in result

    def test_rwt(self) -> None:
        snap = _snap(rwt=0.42)
        result = format_results_overlay(snap)
        assert "0.42" in result

    def test_rv_fac(self) -> None:
        snap = _snap(rv_fac_percent=45.0)
        result = format_results_overlay(snap)
        assert "45.0" in result

    def test_diastology_grade(self) -> None:
        snap = _snap(diastology_grade="Grade II")
        result = format_results_overlay(snap)
        assert "Grade II" in result

    def test_spacing_uncalibrated(self) -> None:
        lvef = LvefResult(a4c=LvViewMetrics(edv_ml=100.0), lvef_percent=55.0)
        snap = _snap(lvef=lvef, spacing_calibrated=False)
        result = format_results_overlay(snap)
        assert "px³" in result


class TestFormatResultsOverlayHtml:
    def test_none_snapshot(self) -> None:
        assert format_results_overlay_html(None) == ""

    def test_with_doppler(self) -> None:
        snap = _snap(doppler=DopplerResults(e_cm_s=80.0, a_cm_s=60.0))
        result = format_results_overlay_html(snap)
        assert "80.0" in result
        assert "<br>" in result

    def test_with_lvef(self) -> None:
        lvef = LvefResult(a4c=LvViewMetrics(edv_ml=120.0), lvef_percent=58.3)
        snap = _snap(lvef=lvef)
        result = format_results_overlay_html(snap)
        assert "58.3" in result

    def test_with_linear_mm(self) -> None:
        m = LinearMeasurement(label="IVSd", pixel_length=10, millimeter_length=9.0)
        snap = _snap(linear_measurements=(m,))
        result = format_results_overlay_html(snap)
        assert "9.0" in result

    def test_with_linear_px_only(self) -> None:
        m = LinearMeasurement(label="IVSd", pixel_length=10, millimeter_length=None)
        snap = _snap(linear_measurements=(m,))
        result = format_results_overlay_html(snap)
        assert "px" in result

    def test_with_la_simpson(self) -> None:
        la = ChamberSimpsonResult(chamber="LA", a4c=LvViewMetrics(esv_ml=45.0), area_cm2=22.5)
        snap = _snap(la_simpson=la)
        result = format_results_overlay_html(snap)
        assert "45.0" in result

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
        assert "1.85" in result

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
    def test_does_not_raise(self) -> None:
        invalidate_norm_cache()
