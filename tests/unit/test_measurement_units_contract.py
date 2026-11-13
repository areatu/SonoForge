"""Area/volume units at the planimeter and report boundaries (#546).

The reference shapes are exact: a 10×10 px square is 100 px², the same square
at anisotropic spacing (0.5 mm row, 0.2 mm column) is 0.1 cm², and 20×20 px
through the 20-disk Simpson rule is a cubic-pixel volume, not millilitres.
"""

from __future__ import annotations

import math

import pytest

from echo_personal_tool.domain.calculations.lvef_simpson import (
    simpson_volume_ml_from_closed_polygon,
    simpson_volume_px3_from_closed_polygon,
)
from echo_personal_tool.domain.calculations.planimeter import (
    closed_polygon_area_cm2,
    closed_polygon_area_px2,
    closed_polygon_volume_px3,
    format_area_result,
    format_volume_result,
)
from echo_personal_tool.domain.measurement_units import (
    area_for_display,
    volume_for_display,
)
from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.models.measurements import (
    ChamberSimpsonResult,
    LvefResult,
    LvViewMetrics,
    MeasurementSnapshot,
)
from echo_personal_tool.domain.services.measurement_results_formatter import (
    chamber_volume_status_lines,
    format_results_overlay,
)
from echo_personal_tool.domain.services.planimeter_formatter import (
    planimeter_progress_text,
    planimeter_results_from_contours,
)
from echo_personal_tool.domain.services.report_builder import build_report_groups


def _square(size: float, chamber: str, label: str) -> Contour:
    return Contour(
        phase="ED",
        chamber=chamber,
        points=[(0.0, 0.0), (size, 0.0), (size, size), (0.0, size)],
        measurement_label=label,
    )


def test_reference_square_pixel_and_physical_area() -> None:
    square = _square(10.0, "AREA", "Area1")
    assert closed_polygon_area_px2(square) == pytest.approx(100.0)
    assert closed_polygon_area_cm2(square, (0.5, 0.2)) == pytest.approx(0.1)
    assert "100.00 px²" in format_area_result(square, (1.0, 1.0), spacing_calibrated=False)
    assert "0.10 cm²" in format_area_result(square, (0.5, 0.2), spacing_calibrated=True)


def test_reference_square_pixel_volume_is_cubic_pixels() -> None:
    square = _square(20.0, "VOL", "Vol1")
    expected_px3 = 20.0 * (math.pi / 4.0) * 20.0 * 20.0 * 1.0
    assert closed_polygon_volume_px3(square) == pytest.approx(expected_px3)
    assert "6283 px³" in format_volume_result(square, (1.0, 1.0), spacing_calibrated=False)


def test_unit_spacing_conversions_are_explicit() -> None:
    assert area_for_display(1.0, calibrated=False) == pytest.approx(100.0)
    assert area_for_display(1.0, calibrated=True) == pytest.approx(1.0)
    assert volume_for_display(1.0, calibrated=False) == pytest.approx(1000.0)
    assert volume_for_display(1.0, calibrated=True) == pytest.approx(1.0)
    assert area_for_display(None, calibrated=False) is None
    assert volume_for_display(None, calibrated=True) is None


def test_uncalibrated_overlay_and_report_use_the_same_pixel_value() -> None:
    area = _square(10.0, "AREA", "Area1")
    volume = _square(20.0, "VOL", "Vol1")
    results = planimeter_results_from_contours(
        (area, volume),
        (1.0, 1.0),
        spacing_calibrated=False,
    )
    snapshot = MeasurementSnapshot(planimeter=results, spacing_calibrated=False)

    overlay = format_results_overlay(snapshot)
    assert "100.00 px²" in overlay
    assert "6283 px³" in overlay

    report_rows = [(value.value, value.unit) for group in build_report_groups(snapshot) for value in group.values]
    assert ("100.00", "px²") in report_rows
    assert ("6283", "px³") in report_rows


def test_invalid_spacing_is_never_promoted_to_a_physical_result() -> None:
    square = _square(10.0, "AREA", "Area1")
    for spacing in ((float("nan"), 1.0), (1.0, float("inf")), (0.0, 1.0)):
        assert closed_polygon_area_cm2(square, spacing) is None


def test_planimeter_progress_uses_pixel_units() -> None:
    area = _square(10.0, "AREA", "Area1")
    volume = _square(20.0, "VOL", "Vol1")
    assert "100.00 px²" in (planimeter_progress_text(area, (1.0, 1.0), spacing_calibrated=False) or "")
    assert "6283 px³" in (planimeter_progress_text(volume, (1.0, 1.0), spacing_calibrated=False) or "")


def test_status_bar_and_overlay_share_the_uncalibrated_volume() -> None:
    la = ChamberSimpsonResult(chamber="LA", a4c=LvViewMetrics(esv_ml=50.0))
    snapshot = MeasurementSnapshot(la_simpson=la, spacing_calibrated=False)
    assert "LAV 4C: 50000 px³" in chamber_volume_status_lines(snapshot, chamber="LA", view="A4C")
    overlay = format_results_overlay(snapshot)
    assert "50000 px³" in overlay


def test_simpson_pixel_and_millilitre_paths_differ_only_by_the_scale() -> None:
    volume = _square(20.0, "VOL", "Vol1")
    px3 = simpson_volume_px3_from_closed_polygon(volume)
    ml = simpson_volume_ml_from_closed_polygon(volume, (1.0, 1.0))
    assert px3 is not None and ml is not None
    assert px3 == pytest.approx(ml * 1000.0)


def test_uncalibrated_lv_volume_is_the_same_in_overlay_and_report() -> None:
    snapshot = MeasurementSnapshot(
        lvef=LvefResult(a4c=LvViewMetrics(edv_ml=100.0), method="simpson_biplan"),
        spacing_calibrated=False,
    )
    assert "100000 px³" in format_results_overlay(snapshot)
    report_rows = [(value.value, value.unit) for group in build_report_groups(snapshot) for value in group.values]
    assert ("100000", "px³") in report_rows


def test_two_monoplane_volumes_do_not_become_a_biplane_status_line() -> None:
    la = ChamberSimpsonResult(
        chamber="LA",
        method="simpson_mean_monoplan",
        a4c=LvViewMetrics(esv_ml=50.0),
        a2c=LvViewMetrics(esv_ml=56.0),
    )
    snapshot = MeasurementSnapshot(la_simpson=la, spacing_calibrated=True)
    lines = chamber_volume_status_lines(snapshot, chamber="LA", view="A4C")
    assert "LAV 4C: 50 mL" in lines
    assert not any("Bi" in line for line in lines)
    assert "Biplan" not in format_results_overlay(snapshot)
