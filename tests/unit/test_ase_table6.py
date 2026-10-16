"""Reconciliation of the catalog with ASE 2025 Table 6 (TP-0 PR-3, A-12).

The ASE 2025 reporting standard lists every measurement in a *measurement
dictionary* (Table 6): name, abbreviation, unit and the suggested number of
decimals.  This module checks that:

* the table itself is consistent (unique ids and abbreviations);
* every row of the table is either used by the catalog or explicitly listed
  as «not in the app» — a new row cannot be forgotten silently;
* the catalog points at existing rows, and a measurement with a row is
  marked as verified;
* the unit, the number of decimals and the EN abbreviation of a measurement
  match its row — every deviation is listed with a reason;
* the catalog keeps the A-12 rules: unique ids, RU and EN labels for every id,
  no Latin in RU outside the allowlist and no Cyrillic in EN.

Source: Taub CC, Stainback RF et al. *Guidelines for the Standardization of
Adult Echocardiography Reporting.* J Am Soc Echocardiogr 2025;38(9):735–774.
"""

from __future__ import annotations

import pytest

from echo_personal_tool.domain import ase_table6 as t6
from echo_personal_tool.domain import measurement_catalog as cat
from echo_personal_tool.domain.measurement_catalog import (
    CATALOG,
    MEASUREMENTS,
    SECTIONS,
    Quantity,
    ase_mode_unit,
    en_label_violations,
    ru_label_violations,
)

# Units the catalog knows; the table is written in the same notation.
_KNOWN_UNITS = {
    "",
    "%",
    "bpm",
    "cm",
    "cm/s",
    "cm²",
    "cm²/m²",
    "g",
    "g/m²",
    "l/min",
    "l/min/m²",
    "mL",
    "mL/m²",
    "m/s",
    "mm",
    "mmHg",
    "mmHg/s",
    "mmHg×bpm",
    "ms",
}

# Centimetres per second in metres per second — the factor between the ASE
# unit (m/s) and the app unit for PW/TDI velocities (cm/s).
_CM_PER_M = 100.0


def _rows_by_id() -> dict[str, t6.Table6Row]:
    return dict(t6.TABLE6_BY_ID)


def _used_rows() -> dict[str, list[str]]:
    used: dict[str, list[str]] = {}
    for spec in MEASUREMENTS.values():
        if spec.ase_row:
            used.setdefault(spec.ase_row, []).append(spec.id)
    return used


#: Measurements that point at a row of the table.
_WITH_ROW: tuple[str, ...] = tuple(sorted(spec.id for spec in MEASUREMENTS.values() if spec.ase_row))


# ── The table itself ────────────────────────────────────────────────


def test_table6_is_consistent() -> None:
    assert t6.validate_table6() == []


def test_row_ids_and_abbreviations_are_unique() -> None:
    ids = [row.id for row in t6.TABLE6_ROWS]
    assert len(ids) == len(set(ids))
    abbreviations = [row.abbreviation for row in t6.TABLE6_ROWS if row.abbreviation]
    assert len(abbreviations) == len(set(abbreviations))


def test_rows_use_the_units_of_the_project() -> None:
    """The table is written in the notation of the catalog (mL, mmHg, cm²)."""
    for row in t6.TABLE6_ROWS:
        assert row.unit in _KNOWN_UNITS, (row.id, row.unit)
        assert row.decimals >= 0, row.id


def test_every_row_is_used_or_explicitly_listed() -> None:
    """No row of the table is forgotten silently."""
    used = _used_rows()
    missing = [row.id for row in t6.TABLE6_ROWS if row.id not in used and row.id not in t6.TABLE6_NOT_IN_CATALOG]
    assert missing == []
    stale = [row_id for row_id in t6.TABLE6_NOT_IN_CATALOG if row_id in used]
    assert stale == []


# ── Catalog → table ─────────────────────────────────────────────────


def test_catalog_points_at_existing_rows() -> None:
    rows = _rows_by_id()
    for spec in MEASUREMENTS.values():
        if spec.ase_row is not None:
            assert spec.ase_row in rows, spec.id


def test_measurements_with_a_row_are_verified() -> None:
    for spec in MEASUREMENTS.values():
        if spec.ase_row is not None:
            assert spec.ase_ref == "Table 6", spec.id
            assert spec.verified, spec.id


def test_verified_measurements_name_their_source() -> None:
    for spec in MEASUREMENTS.values():
        if spec.verified:
            assert spec.ase_ref, spec.id


@pytest.mark.parametrize("measurement_id", sorted(_WITH_ROW))
def test_unit_of_a_measurement_matches_its_row(measurement_id: str) -> None:
    spec = MEASUREMENTS[measurement_id]
    row = cat.ase_table6_row(spec.ase_row)
    assert row is not None
    unit = ase_mode_unit(spec)
    if unit == row.unit:
        return
    assert measurement_id in t6.ASE_UNIT_DEVIATIONS, (measurement_id, unit, row.unit)
    assert t6.ASE_UNIT_DEVIATIONS[measurement_id].strip(), measurement_id


@pytest.mark.parametrize("measurement_id", sorted(_WITH_ROW))
def test_decimals_of_a_measurement_match_its_row(measurement_id: str) -> None:
    """The app never rounds coarser than ASE recommends."""
    spec = MEASUREMENTS[measurement_id]
    row = cat.ase_table6_row(spec.ase_row)
    assert row is not None
    unit = ase_mode_unit(spec)
    decimals = spec.decimals_for(unit)
    if unit == row.unit:
        assert decimals == row.decimals, (measurement_id, decimals, row.decimals)
        return
    # The unit differs (cm/s instead of m/s): the resolution of the app unit
    # must not be coarser than the resolution of the ASE unit.
    app_step = 10.0**-decimals
    ase_step = 10.0**-row.decimals * (_CM_PER_M if row.unit == "m/s" and unit == "cm/s" else 1.0)
    assert app_step <= ase_step + 1e-9, (measurement_id, decimals, row.decimals)


@pytest.mark.parametrize("measurement_id", sorted(_WITH_ROW))
def test_en_label_of_a_measurement_uses_the_ase_abbreviation(measurement_id: str) -> None:
    spec = MEASUREMENTS[measurement_id]
    row = cat.ase_table6_row(spec.ase_row)
    assert row is not None
    short = spec.label("en").short
    if short == row.abbreviation:
        return
    assert measurement_id in t6.EN_LABEL_EXCEPTIONS, (measurement_id, short, row.abbreviation)
    assert t6.EN_LABEL_EXCEPTIONS[measurement_id].strip(), measurement_id


def test_exception_lists_have_no_stale_entries() -> None:
    """Every documented exception is really needed."""
    rows = _rows_by_id()
    for measurement_id, reason in t6.EN_LABEL_EXCEPTIONS.items():
        spec = MEASUREMENTS[measurement_id]
        row = rows[spec.ase_row or ""]
        assert spec.label("en").short != row.abbreviation, measurement_id
        assert reason.strip(), measurement_id
    for measurement_id, reason in t6.ASE_UNIT_DEVIATIONS.items():
        spec = MEASUREMENTS[measurement_id]
        row = rows[spec.ase_row or ""]
        assert ase_mode_unit(spec) != row.unit, measurement_id
        assert reason.strip(), measurement_id


def test_ase_mode_unit_follows_the_unit_decisions() -> None:
    """cm for linear dimensions, m/s for CW, cm/s for PW and TDI (D-05/D-12)."""
    assert ase_mode_unit(MEASUREMENTS["lv.lvedd"]) == "cm"
    assert ase_mode_unit(MEASUREMENTS["av.vmax"]) == "m/s"
    assert ase_mode_unit(MEASUREMENTS["mv.e"]) == "cm/s"
    assert ase_mode_unit(MEASUREMENTS["tdi.e_sept"]) == "cm/s"
    assert ase_mode_unit(MEASUREMENTS["lv.rwt"]) == ""


def test_velocity_decimals_in_metres_per_second_follow_ase() -> None:
    """In m/s the rounding is the one of the ASE row (TP-1 «см (ASE)» mode)."""
    assert MEASUREMENTS["mv.e"].decimals_for("cm/s") == 0
    assert MEASUREMENTS["mv.e"].decimals_for("m/s") == 2
    assert MEASUREMENTS["av.vmax"].decimals_for("m/s") == 1


# ── A-12: autotest of the catalog ───────────────────────────────────


def _all_labels():
    for collection in (CATALOG, MEASUREMENTS, SECTIONS):
        for item in collection.values():
            for language in cat.LANGUAGES:
                label = item.labels[language]
                yield item.id, language, label.short
                yield item.id, language, label.full


def test_ids_are_unique_across_the_catalog() -> None:
    tool_ids = [tool.id for tool in CATALOG.values()]
    assert len(tool_ids) == len(set(tool_ids))
    measurement_ids = list(MEASUREMENTS)
    assert len(measurement_ids) == len(set(measurement_ids))
    section_ids = list(SECTIONS)
    assert len(section_ids) == len(set(section_ids))


def test_every_id_has_ru_and_en_labels() -> None:
    for item_id, language, text in _all_labels():
        assert text.strip() == text and text, (item_id, language)


def test_ru_labels_have_no_latin_outside_the_allowlist() -> None:
    bad = [
        (item_id, text, ru_label_violations(text))
        for item_id, language, text in _all_labels()
        if language == "ru" and ru_label_violations(text)
    ]
    assert bad == []


def test_en_labels_have_no_cyrillic() -> None:
    bad = [
        (item_id, text) for item_id, language, text in _all_labels() if language == "en" and en_label_violations(text)
    ]
    assert bad == []


def test_indexed_measurements_keep_the_ru_prefix() -> None:
    for spec in MEASUREMENTS.values():
        if spec.indexed:
            assert spec.label("ru").short.startswith("и"), spec.id
            assert spec.quantity.value.startswith("indexed_"), spec.id


def test_untranslated_terms_stay_in_latin() -> None:
    """Q-03: DT, IVRT, VTI и DVI не переводятся."""
    assert MEASUREMENTS["mv.dt"].label("ru").short == "DT"
    assert MEASUREMENTS["lv.ivrt"].label("ru").short == "IVRT"
    assert MEASUREMENTS["av.dvi"].label("ru").short == "DVI"
    assert MEASUREMENTS["av.vti"].label("ru").short == "VTI АК"
    assert MEASUREMENTS["lvot.vti"].label("ru").short == "VTI ВТЛЖ"


def test_pasp_is_systolic_dla_in_russian() -> None:
    assert MEASUREMENTS["pa.pasp"].label("ru").short == "Сист. ДЛА"


def test_biplane_is_not_translated_as_an_adverb() -> None:
    for item_id, language, text in _all_labels():
        if language == "ru":
            assert "бипланово" not in text.lower(), item_id


def test_quantities_of_the_ase_rows_match_the_catalog() -> None:
    """A row of the table fixes the physical quantity of the measurement."""
    expected = {
        "lv.lvedd": Quantity.LENGTH,
        "lv.lvedv": Quantity.VOLUME,
        "lv.lvedvi": Quantity.INDEXED_VOLUME,
        "lv.rwt": Quantity.RATIO,
        "mv.pht": Quantity.TIME,
        "tr.peak_pg": Quantity.PRESSURE,
        "mr.dpdt": Quantity.PRESSURE_RATE,
        "hr": Quantity.RATE,
    }
    for row_id, quantity in expected.items():
        spec = next(spec for spec in MEASUREMENTS.values() if spec.ase_row == row_id)
        assert spec.quantity is quantity, (row_id, spec.id)
