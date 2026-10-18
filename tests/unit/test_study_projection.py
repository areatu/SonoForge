"""Сборка проекции исследования из снимка (TP-3 PR-2b, §8.6 / S-11)."""

from __future__ import annotations

from echo_personal_tool.domain.measurement_catalog import (
    CALIPER_TO_MEASUREMENT,
    MEASUREMENTS,
    REQ_SPATIAL,
)
from echo_personal_tool.domain.models import (
    IndexedMeasurements,
    LinearMeasurement,
    LvefResult,
    LvViewMetrics,
    MeasurementSnapshot,
)
from echo_personal_tool.domain.models.linear_measurement import _LABEL_I18N_KEY
from echo_personal_tool.domain.protocol_definitions import PROTOCOLS
from echo_personal_tool.domain.services.study_projection import (
    MAPPED_KEYS,
    UNMAPPED_KEYS,
    build_study_projection,
)


def _linear(label: str, mm: float) -> LinearMeasurement:
    return LinearMeasurement(label=label, pixel_length=mm, millimeter_length=mm)


def test_linear_labels_map_to_catalog_keys() -> None:
    snapshot = MeasurementSnapshot(
        linear_measurements=(
            _linear("IVSd", 10.0),
            _linear("LVEDD", 50.0),
            _linear("LVPWd", 9.0),
            _linear("LVESD", 32.0),
        )
    )
    projection = build_study_projection(snapshot)
    assert projection.get("lv.ivsd").value == 10.0
    assert projection.get("lv.lvedd").value == 50.0
    assert projection.get("lv.lvpwd").value == 9.0
    assert projection.get("lv.lvesd").value == 32.0
    assert projection.get("lv.lvedd").origin == ""


def test_authored_keys_get_protocol_origin() -> None:
    snapshot = MeasurementSnapshot(linear_measurements=(_linear("LVEDD", 50.0),))
    projection = build_study_projection(
        snapshot,
        protocol_id="lv_linear",
        authored=frozenset({"lv.lvedd"}),
    )
    assert projection.get("lv.lvedd").origin == "lv_linear"


def test_simpson_views_and_biplane_map() -> None:
    snapshot = MeasurementSnapshot(
        lvef=LvefResult(
            a4c=LvViewMetrics(edv_ml=100.0, esv_ml=40.0),
            a2c=LvViewMetrics(edv_ml=98.0, esv_ml=38.0),
            lvef_percent=60.0,
            method="simpson_biplan",
            edv_bi_ml=99.0,
            esv_bi_ml=39.0,
        )
    )
    projection = build_study_projection(snapshot)
    assert projection.get("lv.edv_a4c").value == 100.0
    assert projection.get("lv.esv_a4c").value == 40.0
    assert projection.get("lv.edv_a2c").value == 98.0
    assert projection.get("lv.esv_a2c").value == 38.0
    assert projection.get("lv.edv_bp").value == 99.0
    assert projection.get("lv.esv_bp").value == 39.0
    assert projection.get("lv.ef_bp").value == 60.0


def test_derived_mass_rwt_and_index_map() -> None:
    snapshot = MeasurementSnapshot(
        lvm_g=162.0,
        rwt=0.36,
        indexed=IndexedMeasurements(bsa_m2=1.8, lvmi_g_m2=90.0),
    )
    projection = build_study_projection(snapshot)
    assert projection.get("lv.mass").value == 162.0
    assert projection.get("lv.rwt").value == 0.36
    assert projection.get("lv.mass_i").value == 90.0


def test_missing_values_are_absent() -> None:
    projection = build_study_projection(MeasurementSnapshot())
    assert projection.get("lv.lvedd") is None
    assert projection.values == {}


def test_context_is_passed_through() -> None:
    projection = build_study_projection(
        MeasurementSnapshot(),
        clip_modes=frozenset({"cw"}),
        clip_view="A4C",
        unmet=frozenset({"spatial_calibration"}),
    )
    assert projection.clip_modes == frozenset({"cw"})
    assert projection.clip_view == "A4C"
    assert projection.unmet == frozenset({"spatial_calibration"})


def test_unmet_is_derived_from_spacing_when_not_given() -> None:
    assert build_study_projection(MeasurementSnapshot()).unmet == frozenset()
    uncalibrated = build_study_projection(MeasurementSnapshot(spacing_calibrated=False))
    assert uncalibrated.unmet == frozenset({REQ_SPATIAL})


def _protocol_keys() -> set[str]:
    keys: set[str] = set()
    for spec in PROTOCOLS:
        for step in spec.steps:
            keys.update(step.satisfied_keys)
        keys.update(spec.derived)
    return keys


def test_protocol_keys_are_all_classified() -> None:
    keys = _protocol_keys()
    classified = MAPPED_KEYS | set(UNMAPPED_KEYS)
    assert keys <= classified, f"unclassified protocol keys: {sorted(keys - classified)}"
    assert MAPPED_KEYS.isdisjoint(UNMAPPED_KEYS)
    for key in classified:
        assert key in MEASUREMENTS, key


def test_builder_emits_mapped_keys_only() -> None:
    snapshot = MeasurementSnapshot(
        linear_measurements=(
            _linear("IVSd", 10.0),
            _linear("LVEDD", 50.0),
            _linear("LVPWd", 9.0),
            _linear("LVESD", 32.0),
        ),
        lvef=LvefResult(a4c=LvViewMetrics(edv_ml=100.0, esv_ml=40.0)),
        lvm_g=162.0,
        rwt=0.36,
        indexed=IndexedMeasurements(bsa_m2=1.8, lvmi_g_m2=90.0),
    )
    projection = build_study_projection(snapshot)
    assert set(projection.values) <= MAPPED_KEYS


def test_caliper_map_shares_labels_with_i18n() -> None:
    assert set(CALIPER_TO_MEASUREMENT) <= set(_LABEL_I18N_KEY)
    assert all(measurement in MEASUREMENTS for measurement in CALIPER_TO_MEASUREMENT.values())
