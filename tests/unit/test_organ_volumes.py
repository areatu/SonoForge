"""Organ volumes from three dimensions (item 11 of the 2026-11-06 list).

The owner asked for ordinary-ultrasound volumetry: three sizes and an organ
coefficient.  The bladder and the thyroid lobes get their rows automatically,
and the general «объём по трём измерениям» tool turns three consecutive
calipers into one row.  These tests pin the arithmetic *and* the row the
physician sees in the report.
"""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.measurement_catalog import MEASUREMENTS
from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
from echo_personal_tool.domain.services.organ_volumes import (
    VOLUME_COEFFICIENT_ELLIPSOID,
    VOLUME_COEFFICIENT_THYROID,
    bladder_volume_ml,
    organ_volume_ml,
    thyroid_lobe_volume_ml,
    volume_ml,
)
from echo_personal_tool.domain.services.report_builder import (
    GROUP_KIDNEY,
    GROUP_PLANIMETRY,
    GROUP_THYROID,
    PatientInfo,
    build_report_document,
)
from echo_personal_tool.infrastructure.i18n import set_language


def _caliper(label: str, millimeters: float) -> LinearMeasurement:
    return LinearMeasurement(label=label, pixel_length=millimeters * 2, millimeter_length=millimeters)


def _rows(snapshot: MeasurementSnapshot) -> dict[str, tuple[str, str, str]]:
    document = build_report_document(snapshot, PatientInfo(sex="M"), sex="M", profile_id="kidney")
    rows: dict[str, tuple[str, str, str]] = {}
    for group in document.groups:
        for value in group.values:
            rows[value.label] = (value.value, value.unit, group.key)
    return rows


# ── arithmetic ─────────────────────────────────────────────────────


def test_the_coefficients_are_the_agreed_ones() -> None:
    assert VOLUME_COEFFICIENT_ELLIPSOID == pytest.approx(0.523)
    assert VOLUME_COEFFICIENT_THYROID == pytest.approx(0.479)


def test_volume_is_millilitres_from_millimetres() -> None:
    # 0.523 · 100 · 80 · 60 mm³ = 251 040 mm³ = 251.04 mL
    assert bladder_volume_ml(100.0, 80.0, 60.0) == pytest.approx(251.04)
    assert thyroid_lobe_volume_ml(50.0, 25.0, 20.0) == pytest.approx(11.975)
    assert organ_volume_ml(100.0, 50.0, 40.0) == pytest.approx(104.6)


def test_a_missing_or_zero_dimension_has_no_volume() -> None:
    assert volume_ml((100.0, 0.0, 60.0), coefficient=0.523) is None
    with pytest.raises(ValueError):
        volume_ml((100.0, 60.0), coefficient=0.523)


# ── report rows ────────────────────────────────────────────────────


def test_the_bladder_gets_its_volume_row_from_three_sizes() -> None:
    set_language("ru")
    snapshot = MeasurementSnapshot(
        linear_measurements=(
            _caliper("BL-L", 100.0),
            _caliper("BL-W", 80.0),
            _caliper("BL-D", 60.0),
        )
    )
    rows = _rows(snapshot)
    label = MEASUREMENTS["bladder.volume"].label("ru").short
    assert rows[label] == ("251.0", "mL", GROUP_KIDNEY)


def test_the_old_bladder_height_still_produces_the_volume() -> None:
    """A document measured «МП высота» before the third size was renamed."""
    set_language("ru")
    snapshot = MeasurementSnapshot(
        linear_measurements=(
            _caliper("BL-L", 100.0),
            _caliper("BL-W", 80.0),
            _caliper("BL-H", 60.0),
        )
    )
    rows = _rows(snapshot)
    assert rows[MEASUREMENTS["bladder.volume"].label("ru").short][0] == "251.0"


def test_thyroid_lobes_and_total_use_brunn() -> None:
    set_language("ru")
    snapshot = MeasurementSnapshot(
        linear_measurements=(
            _caliper("TH-R-H", 50.0),
            _caliper("TH-R-W", 25.0),
            _caliper("TH-R-TH", 20.0),
            _caliper("TH-L-H", 45.0),
            _caliper("TH-L-W", 22.0),
            _caliper("TH-L-TH", 18.0),
        )
    )
    document = build_report_document(snapshot, PatientInfo(sex="M"), sex="M", profile_id="thyroid")
    rows = {value.label: (value.value, value.unit, group.key) for group in document.groups for value in group.values}
    assert rows[MEASUREMENTS["thyroid.r_volume"].label("ru").short] == ("12.0", "mL", GROUP_THYROID)
    assert rows[MEASUREMENTS["thyroid.l_volume"].label("ru").short] == ("8.5", "mL", GROUP_THYROID)
    assert rows[MEASUREMENTS["thyroid.volume"].label("ru").short] == ("20.5", "mL", GROUP_THYROID)


def test_the_general_volume_tool_reports_one_row_for_three_calipers() -> None:
    set_language("ru")
    snapshot = MeasurementSnapshot(
        linear_measurements=(
            _caliper("ORGAN-VOL-1", 100.0),
            _caliper("ORGAN-VOL-2", 50.0),
            _caliper("ORGAN-VOL-3", 40.0),
        )
    )
    rows = _rows(snapshot)
    assert rows[MEASUREMENTS["organ.volume"].label("ru").short] == ("104.6", "mL", GROUP_PLANIMETRY)


def test_two_general_volume_triplets_produce_two_rows() -> None:
    set_language("ru")
    snapshot = MeasurementSnapshot(
        linear_measurements=(
            _caliper("ORGAN-VOL-1", 100.0),
            _caliper("ORGAN-VOL-2", 50.0),
            _caliper("ORGAN-VOL-3", 40.0),
            _caliper("ORGAN-VOL-1", 20.0),
            _caliper("ORGAN-VOL-2", 10.0),
            _caliper("ORGAN-VOL-3", 5.0),
        )
    )
    document = build_report_document(snapshot, PatientInfo(sex="M"), sex="M", profile_id="kidney")
    label = MEASUREMENTS["organ.volume"].label("ru").short
    values = [
        value.value
        for group in document.groups
        if group.key == GROUP_PLANIMETRY
        for value in group.values
        if value.label == label
    ]
    assert values == ["104.6", "0.5"]


def test_uncalibrated_calipers_do_not_guess_a_volume() -> None:
    set_language("ru")
    snapshot = MeasurementSnapshot(
        linear_measurements=(
            LinearMeasurement(label="BL-L", pixel_length=100.0, millimeter_length=None),
            LinearMeasurement(label="BL-W", pixel_length=80.0, millimeter_length=None),
            LinearMeasurement(label="BL-D", pixel_length=60.0, millimeter_length=None),
        )
    )
    rows = _rows(snapshot)
    assert MEASUREMENTS["bladder.volume"].label("ru").short not in rows
