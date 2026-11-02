"""Сборка проекции исследования из снимка (TP-3 PR-2b, §8.6 / S-11)."""

from __future__ import annotations

from echo_personal_tool.domain.calculators.engine import evaluate
from echo_personal_tool.domain.calculators.models import SOURCE_MEASURED, InputValue
from echo_personal_tool.domain.measurement_catalog import (
    CALIPER_TO_MEASUREMENT,
    MEASUREMENTS,
    REQ_SPATIAL,
)
from echo_personal_tool.domain.models import (
    ChamberSimpsonResult,
    DopplerFlowResult,
    DopplerResults,
    IndexedMeasurements,
    LaVolumeResult,
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
            _linear("LVOTd", 20.0),
            _linear("LA", 38.0),
        )
    )
    projection = build_study_projection(snapshot)
    assert projection.get("lv.ivsd").value == 10.0
    assert projection.get("lv.lvedd").value == 50.0
    assert projection.get("lv.lvpwd").value == 9.0
    assert projection.get("lv.lvesd").value == 32.0
    assert projection.get("lvot.d").value == 20.0
    assert projection.get("la.ap").value == 38.0
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


def test_chambers_map_from_simpson_area_length_and_indexes() -> None:
    snapshot = MeasurementSnapshot(
        la_simpson=ChamberSimpsonResult(
            chamber="LA",
            a4c=LvViewMetrics(esv_ml=60.0),
            a2c=LvViewMetrics(esv_ml=50.0),
        ),
        la_volume=LaVolumeResult(volume_ml=64.0, area_cm2=20.0, length_cm=5.0),
        indexed=IndexedMeasurements(
            bsa_m2=1.8,
            lav_bi_index_ml_m2=30.5,
            lav_4c_index_ml_m2=33.3,
            lav_area_length_index_ml_m2=35.5,
        ),
    )
    projection = build_study_projection(snapshot)
    assert projection.get("la.lav_a4c").value == 60.0
    assert projection.get("la.lav_a2c").value == 50.0
    assert projection.get("la.lav_bp").value == 55.0
    assert projection.get("la.lavi").value == 30.5


def test_doppler_flows_and_indices_map() -> None:
    snapshot = MeasurementSnapshot(
        doppler=DopplerResults(
            e_cm_s=80.0,
            a_cm_s=60.0,
            dt_ms=200.0,
            ivrt_ms=90.0,
            e_prime_sept_cm_s=7.0,
            e_prime_lat_cm_s=9.0,
            e_prime_avg_cm_s=8.0,
            e_a_ratio=1.33,
            e_over_e_prime=10.0,
            e_over_e_prime_sept=11.4,
            e_over_e_prime_lat=8.9,
            tr_vmax_cm_s=280.0,
            flow_results=(
                DopplerFlowResult(
                    site="AV",
                    vmax_cm_s=400.0,
                    pgmax_mmhg=64.0,
                    pgmean_mmhg=38.0,
                    vti_cm=90.0,
                ),
                DopplerFlowResult(site="LVOT", vti_cm=22.0),
            ),
        )
    )
    projection = build_study_projection(snapshot)
    assert projection.get("mv.e").value == 80.0
    assert projection.get("mv.a").value == 60.0
    assert projection.get("mv.dt").value == 200.0
    assert projection.get("lv.ivrt").value == 90.0
    assert projection.get("tdi.e_sept").value == 7.0
    assert projection.get("tdi.e_lat").value == 9.0
    assert projection.get("tr.vmax").value == 280.0
    assert projection.get("lvot.vti").value == 22.0
    assert projection.get("av.vmax").value == 400.0
    assert projection.get("av.vti").value == 90.0
    assert projection.get("av.pg_peak").value == 64.0
    assert projection.get("av.pg_mean").value == 38.0
    assert projection.get("mv.ea").value == 1.33
    assert projection.get("tdi.e_avg").value == 8.0
    assert projection.get("mv.e_e_avg").value == 10.0
    assert projection.get("tdi.e_e_sept").value == 11.4
    assert projection.get("tdi.e_e_lat").value == 8.9


def _calculations(**values: float):
    inputs = {input_id: InputValue(input_id, value, SOURCE_MEASURED) for input_id, value in values.items()}
    return evaluate(inputs)


def test_calculator_derived_keys_and_rap_input_map() -> None:
    snapshot = MeasurementSnapshot(
        calculations=_calculations(
            lvedd=5.0,
            lvesd=3.2,
            lvot_d=2.0,
            lvot_vti=22.0,
            av_vti=90.0,
            tr_vmax=2.8,
            rap=8.0,
            bsa=1.8,
        )
    )
    projection = build_study_projection(snapshot)
    assert projection.get("ra.rap").value == 8.0
    assert round(projection.get("lv.fs").value) == 36
    assert round(projection.get("lv.sv").value) == 69
    assert round(projection.get("lv.svi").value, 1) == 38.4
    assert round(projection.get("av.ava_vti").value, 2) == 0.77
    assert round(projection.get("av.avai").value, 2) == 0.43
    assert round(projection.get("av.dvi").value, 2) == 0.24
    assert round(projection.get("tr.pg").value, 1) == 31.4
    assert round(projection.get("pa.pasp").value, 1) == 39.4


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
