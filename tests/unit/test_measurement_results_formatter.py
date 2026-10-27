"""Tests for measurement overlay formatting."""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.models import LvViewMetrics
from echo_personal_tool.domain.models.linear_measurement import (
    PERCENT_LABELS,
    LinearMeasurement,
)
from echo_personal_tool.domain.models.measurements import (
    ChamberSimpsonResult,
    DopplerFlowResult,
    DopplerResults,
    LvefResult,
    MeasurementSnapshot,
)
from echo_personal_tool.domain.services.measurement_results_formatter import (
    format_results_overlay,
    format_results_overlay_html,
)


def test_overlay_hides_legacy_unverified_simpson_notice() -> None:
    """Old Simpson records do not put a distracting warning over the image."""
    from echo_personal_tool.domain.services.provenance_notes import (
        all_provenance_notes,
        evaluate_simpson_record_status,
    )
    from echo_personal_tool.domain.services.simpson_freshness import SimpsonBasis

    status = evaluate_simpson_record_status(None, SimpsonBasis(pixel_spacing=(0.3, 0.3)))
    snapshot = MeasurementSnapshot(simpson_record_status=status)

    # Reports can still show the provenance warning; only the image overlays omit it.
    assert all_provenance_notes(snapshot)
    assert format_results_overlay(snapshot) == ""
    assert format_results_overlay_html(snapshot) == ""


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
    assert "ОЛП · 4-кам.: 42.5 mL" in text
    assert "Площадь ЛП: 18.20 cm²" in text


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
    assert "ОПП: 35.0 mL" in text
    assert "Площадь ПП: 15.00 cm²" in text


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
    assert "e′ септ.: 10.0" in text
    assert "e′ лат.: 14.0" in text
    # E-peak NOT shown (it's from file A, not in display_doppler):
    assert "E: " not in text
    assert "E: 90" not in text
    # Computed ratios from study-wide doppler:
    assert "E/e′" in text
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
    assert "e′ септ.: 10.0" in text
    assert "7.5" not in text  # wrong value
    assert "9.0" in text


def test_overlay_uses_flow_specific_vmax_and_pgmax_labels() -> None:
    snapshot = MeasurementSnapshot(
        doppler=DopplerResults(
            flow_results=(
                DopplerFlowResult(site="AR", vmax_cm_s=420.0, pgmax_mmhg=70.6),
                DopplerFlowResult(site="LVOT", vmax_cm_s=95.0, vti_cm=21.0),
            )
        )
    )

    text = format_results_overlay(snapshot, time_calibrated=True)

    # Unknown mode: a 420 cm/s jet reads in m/s, a 95 cm/s flow in cm/s (Э2).
    assert "AR Vmax: 4.20 m/s" in text
    assert "AR PGmax: 70.6 mmHg" in text
    assert "LVOT Vmax: 95.0 cm/s" in text
    assert "LVOT VTI: 21.0 cm" in text
    assert "Vpeak" not in text
    assert "PGpeak" not in text


def test_overlay_includes_biplane_volumes() -> None:
    from echo_personal_tool.infrastructure.i18n import set_language

    lvef = LvefResult(
        a4c=LvViewMetrics(edv_ml=31.5, esv_ml=16.1),
        lvef_percent=48.8,
        method="simpson_biplan",
        edv_bi_ml=37.8,
        esv_bi_ml=20.2,
    )
    snapshot = MeasurementSnapshot(lvef=lvef, spacing_calibrated=True)
    text = format_results_overlay(snapshot)
    assert "КДО ЛЖ Биплан: 37.8 mL" in text
    assert "КСО ЛЖ Биплан: 20.2 mL" in text

    set_language("en")
    try:
        html = format_results_overlay_html(snapshot)
        assert "LVEDV (biplane)" in html
        assert "LVESV (biplane)" in html
        assert "37.8" in html
        assert "20.2" in html
    finally:
        set_language("ru")


def _plain(html: str) -> str:
    import re

    return re.sub(r"<[^>]+>", "", html)


def test_percent_calipers_are_shown_in_percent() -> None:
    """Stenosis/comparison calipers hold a percentage, not a length."""
    for label in sorted(PERCENT_LABELS):
        snapshot = MeasurementSnapshot(
            spacing_calibrated=True,
            linear_measurements=(LinearMeasurement(label=label, pixel_length=0.0, millimeter_length=80.0),),
        )
        text = _plain(format_results_overlay_html(snapshot, sex_male=True, length_display_unit="mm"))
        assert "80.0" in text, label
        assert "80.0  mm" not in text, label
        assert "80.0  %" in text, label


@pytest.mark.parametrize(("language", "label", "unit"), [("ru", "ЧСС", "уд/мин"), ("en", "HR", "bpm")])
def test_doppler_heart_rate_is_localized_and_requires_time_scale(language, label, unit) -> None:
    from echo_personal_tool.infrastructure.i18n import set_language

    set_language(language)
    snapshot = MeasurementSnapshot(doppler=DopplerResults(heart_rate_bpm=75.0))

    for formatter in (format_results_overlay, format_results_overlay_html):
        assert label not in formatter(snapshot, time_calibrated=False)
        text = _plain(formatter(snapshot, time_calibrated=True))
        assert label in text and "75" in text and unit in text


def test_doppler_heart_rate_overlay_uses_current_clip_not_another_clip() -> None:
    snapshot = MeasurementSnapshot(
        doppler=DopplerResults(heart_rate_bpm=75.0),
        display_doppler=DopplerResults(),
    )
    for formatter in (format_results_overlay, format_results_overlay_html):
        assert "ЧСС по допплеру" not in formatter(snapshot, time_calibrated=True)


@pytest.mark.parametrize("language", ["ru", "en"])
@pytest.mark.parametrize("freshness", ["stale", "unverified", "unavailable"])
def test_record_notices_never_cover_the_image_but_remain_in_reports(language, freshness) -> None:
    from echo_personal_tool.domain.models.result_provenance import BsaRecordStatus
    from echo_personal_tool.domain.services.derived_freshness import DerivedFreshness
    from echo_personal_tool.domain.services.doppler_freshness import DopplerFreshness
    from echo_personal_tool.domain.services.provenance_notes import all_provenance_notes
    from echo_personal_tool.domain.services.simpson_freshness import SimpsonFreshness
    from echo_personal_tool.infrastructure.i18n import set_language

    set_language(language)
    snapshot = MeasurementSnapshot(
        rwt=0.42,
        simpson_record_status=SimpsonFreshness(freshness, ("calibration_changed",)),
        doppler_record_status=DopplerFreshness(freshness, ("input_changed",)),
        derived_record_status=DerivedFreshness(freshness, ("input_changed",)),
        bsa_record_status=BsaRecordStatus(freshness, ("input_changed",), None, None),
    )
    notes = all_provenance_notes(snapshot)
    assert len(notes) == 4
    for formatter in (format_results_overlay, format_results_overlay_html):
        text = formatter(snapshot)
        assert "0.42" in text
        for note in notes:
            assert note not in text
        assert "⚠" not in text
