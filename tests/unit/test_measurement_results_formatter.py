"""Tests for measurement overlay formatting."""

from __future__ import annotations

from echo_personal_tool.domain.models import LvViewMetrics
from echo_personal_tool.domain.models.measurements import (
    ChamberSimpsonResult,
    DopplerResults,
    MeasurementSnapshot,
)
from echo_personal_tool.domain.services.measurement_results_formatter import (
    format_results_overlay,
)


def test_overlay_includes_rwt() -> None:
    text = format_results_overlay(MeasurementSnapshot(rwt=0.42))
    assert "ОТС: 0.42" in text


def test_overlay_includes_la_simpson_lav() -> None:
    snapshot = MeasurementSnapshot(
        spacing_calibrated=True,
        la_simpson=ChamberSimpsonResult(
            chamber="LA",
            a4c=LvViewMetrics(esv_ml=42.5),
            area_cm2=18.2,
        ),
    )
    text = format_results_overlay(snapshot)
    assert "ОЛП 4C: 42.5 mL" in text
    assert "S ЛП: 18.20 cm²" in text


def test_overlay_includes_ra_simpson_rav() -> None:
    snapshot = MeasurementSnapshot(
        spacing_calibrated=True,
        ra_simpson=ChamberSimpsonResult(
            chamber="RA",
            a4c=LvViewMetrics(esv_ml=35.0),
            area_cm2=15.0,
        ),
    )
    text = format_results_overlay(snapshot)
    assert "ОПП 4C: 35.0 mL" in text
    assert "S ПП: 15.00 cm²" in text


def test_overlay_inter_file_computation_uses_study_wide_ratios() -> None:
    """E-peak on file A, e' peaks on file B → E/e' mean computed, but E not shown in file B's overlay."""
    # Study-wide DTO has E + e' peaks → E/e' mean = 90 / 13 ≈ 6.92
    study_doppler = DopplerResults(
        e_cm_s=90.0,
        e_prime_sept_cm_s=10.0,
        e_prime_lat_cm_s=14.0,
        e_prime_avg_cm_s=12.0,
        e_over_e_prime=7.5,
        e_over_e_prime_sept=9.0,
        e_over_e_prime_lat=6.43,
    )
    # Per-instance DTO (file B = TDI) has only e' peaks, no E
    display_doppler = DopplerResults(
        e_prime_sept_cm_s=10.0,
        e_prime_lat_cm_s=14.0,
    )
    snapshot = MeasurementSnapshot(
        doppler=study_doppler,
        display_doppler=display_doppler,
    )
    text = format_results_overlay(snapshot)
    # Individual peaks from display_doppler (per-instance):
    assert "e' септ: 10.0" in text
    assert "e' лат: 14.0" in text
    # E-peak NOT shown (it's from file A, not in display_doppler):
    assert "E: " not in text
    assert "E: 90" not in text
    # Computed ratios from study-wide doppler:
    assert "E/e'" in text
    assert "7.5" in text


def test_overlay_falls_back_to_study_wide_when_display_doppler_none() -> None:
    """When display_doppler is None, individual peaks come from study-wide doppler."""
    study_doppler = DopplerResults(
        e_cm_s=90.0,
        e_prime_sept_cm_s=10.0,
        e_over_e_prime=9.0,
    )
    snapshot = MeasurementSnapshot(
        doppler=study_doppler,
        display_doppler=None,
    )
    text = format_results_overlay(snapshot)
    assert "E: 90.0" in text
    assert "e' септ: 10.0" in text
    assert "7.5" not in text  # wrong value
    assert "9.0" in text
