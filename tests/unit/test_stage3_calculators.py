"""Э11 stage 3: MVA (PHT, PISA), pulmonary haemodynamics, Qp:Qs, Teichholz, orifice area.

Hand-checkable worked example used throughout:

* MV PHT 220 ms → MVA 220/220 = 1.00 cm².
* PISA MS: r 1.0 cm, Va 40 cm/s, MV Vmax 1.6 m/s, α 120° →
  2π·1²·40 · 120/180 / 160 = 1.05 cm².
* TR Vmax 3.0 m/s → TR PGmax 36 mmHg; RAP 8 → PASP 44 mmHg;
  mPAP (Chemla) 0.61·44 + 2 = 28.8; RVOT AT 100 ms → mPAP (Mahan) 79 − 45 = 34.
* PVR (Abbas): 10 · 3.0 / 15 + 0.16 = 2.16 WU.
* Qp:Qs: RVOTd 2.4 cm, RVOT VTI 25 cm → Qp 113.1 mL; LVOTd 2.0, VTI 20 →
  Qs 62.8 mL; ratio 1.80.
* Teichholz: LVEDD 5.0 cm → 7/7.4·125 = 118.2 mL; LVESD 3.2 cm → 41.0 mL;
  SV 77.3 mL, EF 65.4 %, FS 36 %.
"""

from __future__ import annotations

import math

import pytest

from echo_personal_tool.application.calculator_inputs import evaluate_standalone, resolve_study_inputs
from echo_personal_tool.domain.calculations.continuity import circle_area_cm2, qp_qs_ratio
from echo_personal_tool.domain.calculations.doppler_metrics import compute
from echo_personal_tool.domain.calculations.mitral_stenosis import mva_pht_cm2, mva_pisa_cm2
from echo_personal_tool.domain.calculations.pulmonary_hemodynamics import (
    mpap_chemla_mmhg,
    mpap_mahan_mmhg,
    pasp_mmhg,
    pvr_abbas_wu,
    tr_gradient_mmhg,
)
from echo_personal_tool.domain.calculations.teichholz import (
    ejection_fraction_percent,
    fractional_shortening_percent,
    volume_from_cm_ml,
)
from echo_personal_tool.domain.calculators import CALCULATORS, calculator_spec, evaluate, input_spec
from echo_personal_tool.domain.calculators.models import SOURCE_MANUAL, SOURCE_MEASURED, SOURCE_MISSING
from echo_personal_tool.domain.calculators.reference_hints import reference_hint
from echo_personal_tool.domain.calculators.text import source_text, warning_text
from echo_personal_tool.domain.models.doppler import (
    DopplerIntervalMarker,
    DopplerMeasurementDTO,
    DopplerPeakMarker,
    DopplerTrace,
)
from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
from echo_personal_tool.domain.models.measurements import DopplerResults, MeasurementSnapshot
from echo_personal_tool.domain.services.report_builder import (
    GROUP_CALCULATIONS,
    GROUP_MITRAL_VALVE,
    GROUP_RIGHT_VENTRICLE,
    build_report_groups,
    group_for_label,
)
from echo_personal_tool.infrastructure.i18n import set_language

_MS = {"mv_pht": 220.0, "pisa_r_ms": 1.0, "va_ms": 40.0, "mv_vmax": 1.6, "ms_angle": 120.0}
_PULM = {"tr_vmax": 3.0, "rap": 8.0, "rvot_at": 100.0, "rvot_vti": 15.0}
_SHUNT = {"rvot_d": 2.4, "rvot_vti": 25.0, "lvot_d": 2.0, "lvot_vti": 20.0}
_LV = {"lvedd": 5.0, "lvesd": 3.2}


@pytest.fixture(autouse=True)
def _english():
    set_language("en")
    yield
    set_language("en")


def _outputs(values: dict[str, float], calculator_id: str) -> dict[str, str]:
    result = evaluate_standalone(values).result(calculator_id)
    assert result is not None
    return {output.id: output.formatted() for output in result.outputs}


# ── formulas ────────────────────────────────────────────────────────────────
def test_mva_formulas() -> None:
    assert mva_pht_cm2(220.0) == pytest.approx(1.0)
    assert mva_pht_cm2(110.0) == pytest.approx(2.0)
    expected = 2 * math.pi * 40.0 * (120.0 / 180.0) / 160.0
    assert mva_pisa_cm2(1.0, 40.0, 160.0, 120.0) == pytest.approx(expected)
    # α = 180° is the flat-orifice form; above 180° is meaningless.
    assert mva_pisa_cm2(1.0, 40.0, 160.0, 180.0) == pytest.approx(2 * math.pi * 40.0 / 160.0)
    assert mva_pisa_cm2(1.0, 40.0, 160.0, 200.0) is None
    for bad in (None, 0.0, -1.0, math.nan):
        assert mva_pht_cm2(bad) is None
        assert mva_pisa_cm2(bad, 40.0, 160.0, 120.0) is None
        assert mva_pisa_cm2(1.0, 40.0, 160.0, bad) is None


def test_pulmonary_formulas() -> None:
    assert tr_gradient_mmhg(3.0) == pytest.approx(36.0)
    assert pasp_mmhg(36.0, 8.0) == pytest.approx(44.0)
    # RAP 0 mmHg is a legitimate value; a negative one is not.
    assert pasp_mmhg(36.0, 0.0) == pytest.approx(36.0)
    assert pasp_mmhg(36.0, -1.0) is None
    assert pasp_mmhg(36.0, None) is None
    assert mpap_chemla_mmhg(44.0) == pytest.approx(28.84)
    assert mpap_mahan_mmhg(100.0) == pytest.approx(34.0)
    assert mpap_mahan_mmhg(200.0) is None  # outside the regression
    assert pvr_abbas_wu(3.0, 15.0) == pytest.approx(2.16)
    assert pvr_abbas_wu(None, 15.0) is None


def test_shunt_teichholz_and_area_formulas() -> None:
    assert circle_area_cm2(2.0) == pytest.approx(math.pi)
    assert circle_area_cm2(0.0) is None
    assert qp_qs_ratio(113.1, 62.8) == pytest.approx(1.80, abs=0.01)
    assert volume_from_cm_ml(5.0) == pytest.approx(7.0 / 7.4 * 125.0)
    assert volume_from_cm_ml(None) is None
    assert fractional_shortening_percent(5.0, 3.2) == pytest.approx(36.0)
    assert fractional_shortening_percent(4.0, 4.2) is None
    assert ejection_fraction_percent(118.2, 41.0) == pytest.approx(65.3, abs=0.1)
    assert ejection_fraction_percent(70.0, 79.0) is None


# ── registry and evaluation ─────────────────────────────────────────────────
def test_stage3_calculators_are_registered_in_order() -> None:
    assert [spec.id for spec in CALCULATORS] == [
        "stroke_volume",
        "aortic_valve_area",
        "pisa_mr",
        "pisa_ar",
        "mitral_valve_area",
        "pulmonary_pressure",
        "qp_qs",
        "teichholz",
        "dpdt",
        "orifice_area",
    ]
    for input_id in ("va_ms", "ms_angle", "rap", "orifice_d"):
        assert input_spec(input_id).manual_only, input_id
    for input_id in ("mv_pht", "pisa_r_ms", "mv_vmax", "rvot_d", "rvot_vti", "tr_vmax", "rvot_at", "lvedd", "lvesd"):
        assert not input_spec(input_id).manual_only, input_id
    pulmonary = calculator_spec("pulmonary_pressure")
    assert pulmonary.input_closure("mpap_pasp") == ("tr_vmax", "rap")


def test_worked_example() -> None:
    assert _outputs(_MS, "mitral_valve_area") == {"mva_pht": "1.00", "mva_pisa": "1.05"}
    assert _outputs(_PULM, "pulmonary_pressure") == {
        "tr_pg": "36",
        "pasp": "44",
        "mpap_pasp": "29",
        "mpap_at": "34",
        "pvr": "2.16",
    }
    assert _outputs(_SHUNT, "qp_qs") == {
        "rvot_area": "4.52",
        "qp": "113.1",
        "lvot_area": "3.14",
        "qs": "62.8",
        "qp_qs": "1.80",
    }
    assert _outputs(_LV, "teichholz") == {
        "edv_teich": "118",
        "esv_teich": "41",
        "sv_teich": "77",
        "ef_teich": "65",
        "fs": "36",
    }
    assert _outputs({"lvot_d": 2.0, "rvot_d": 2.4, "orifice_d": 2.2}, "orifice_area") == {
        "lvot_area": "3.14",
        "rvot_area": "4.52",
        "area_d": "3.80",
    }


def test_pasp_waits_for_typed_rap_but_shows_the_gradient() -> None:
    result = evaluate_standalone({"tr_vmax": 3.0}).result("pulmonary_pressure")
    assert result.output("tr_pg").value == pytest.approx(36.0)
    assert result.output("pasp").value is None
    assert result.output("pasp").missing == ("rap",)
    # RAP 0 counts as a value.
    zero = evaluate_standalone({"tr_vmax": 3.0, "rap": 0.0}).result("pulmonary_pressure")
    assert zero.output("pasp").value == pytest.approx(36.0)


def test_teichholz_swapped_diameters_warn_and_leave_ef_empty() -> None:
    result = evaluate_standalone({"lvedd": 4.0, "lvesd": 4.2}).result("teichholz")
    assert result.output("ef_teich").value is None
    assert result.output("fs").value is None
    assert result.output("sv_teich").value is None
    assert [w.code for w in result.warnings] == ["lvesd_not_below_lvedd"]
    assert "LVESD is not smaller than LVEDD" in warning_text(result.warnings[0])


# ── study inputs ────────────────────────────────────────────────────────────
def _caliper(label: str, mm: float, pixels: float = 30.0) -> LinearMeasurement:
    return LinearMeasurement(label=label, pixel_length=pixels, millimeter_length=mm)


def _trace(label: str, vti_cm: float, mid: str) -> DopplerTrace:
    return DopplerTrace(label=label, points=((0.0, 0.0), (150.0, vti_cm / 0.15), (300.0, 0.0)), measurement_id=mid)


def test_study_inputs_from_calipers_doppler_and_intervals() -> None:
    dto = DopplerMeasurementDTO(
        peaks=(
            DopplerPeakMarker("MV Vmax", 100.0, 160.0, "mv", "CW"),
            DopplerPeakMarker("TR Vmax", 100.0, -300.0, "tr", "CW"),
        ),
        intervals=(
            DopplerIntervalMarker("MV PHT", 100.0, 320.0, "pht"),
            DopplerIntervalMarker("RVOT AT", 50.0, 150.0, "at"),
        ),
        traces=(_trace("RVOT VTI", 15.0, "rv"),),
    )
    inputs = resolve_study_inputs(
        doppler=compute(dto),
        linear_measurements=[
            _caliper("PISA MS", 10.0),
            _caliper("RVOTd", 24.0),
            # M-mode Teichholz stores calipers without pixels.
            _caliper("LVEDD", 50.0, pixels=0.0),
            _caliper("LVESD", 32.0, pixels=0.0),
        ],
        manual={"rap": 8.0},
    )
    assert inputs["mv_pht"].value == pytest.approx(220.0)
    assert inputs["rvot_at"].value == pytest.approx(100.0)
    assert inputs["mv_vmax"].value == pytest.approx(1.6)
    assert inputs["tr_vmax"].value == pytest.approx(3.0)
    assert inputs["rvot_vti"].value == pytest.approx(15.0, abs=0.1)
    assert inputs["pisa_r_ms"].value == pytest.approx(1.0)
    assert inputs["rvot_d"].value == pytest.approx(2.4)
    assert inputs["lvedd"].value == pytest.approx(5.0)
    assert inputs["lvesd"].value == pytest.approx(3.2)
    for input_id in ("mv_pht", "tr_vmax", "rvot_d", "lvedd"):
        assert inputs[input_id].source == SOURCE_MEASURED, input_id
    assert inputs["rap"].source == SOURCE_MANUAL
    for input_id in ("va_ms", "ms_angle", "orifice_d"):
        assert inputs[input_id].source == SOURCE_MISSING, input_id
    assert source_text(inputs["ms_angle"]) == "type it in: angle between the leaflets on the colour frame"
    calculations = evaluate(inputs)
    assert calculations.result("mitral_valve_area").output("mva_pht").value == pytest.approx(1.0)
    assert not calculations.result("mitral_valve_area").output("mva_pisa").computed
    assert calculations.result("pulmonary_pressure").output("pasp").value == pytest.approx(44.0)
    assert calculations.result("pulmonary_pressure").output("pvr").value == pytest.approx(2.16, abs=0.01)
    assert calculations.result("teichholz").output("ef_teich").value == pytest.approx(65.4, abs=0.1)


def test_rv_size_caliper_rvot_is_not_the_qp_diameter() -> None:
    inputs = resolve_study_inputs(doppler=None, linear_measurements=[_caliper("RVOT", 30.0)])
    assert inputs["rvot_d"].value is None


def test_legacy_tr_vmax_field_is_used_without_a_tr_flow_result() -> None:
    inputs = resolve_study_inputs(doppler=DopplerResults(tr_vmax_cm_s=280.0))
    assert inputs["tr_vmax"].value == pytest.approx(2.8)


# ── reference data ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("language", ["en", "ru"])
def test_secondary_mr_uses_04_and_60_with_a_note(language: str) -> None:
    eroa = reference_hint("mr_eroa_secondary", language)
    rvol = reference_hint("mr_rvol_secondary", language)
    assert [g.range_text for g in eroa.gradations] == ["≤0.2", "0.2–0.39", "≥0.4"]
    assert [g.range_text for g in rvol.gradations] == ["≤30.0", "30.0–59.0", "≥60.0"]
    assert "0.3" in eroa.note or "0,3" in eroa.note
    assert "45" in rvol.note
    assert reference_hint("mr_eroa_primary", language).note == ""


@pytest.mark.parametrize("language", ["en", "ru"])
def test_new_reference_parameters(language: str) -> None:
    pvr = reference_hint("pvr", language)
    assert pvr is not None and pvr.gradations[0].range_text == "≤2.0"
    qp_qs = reference_hint("qp_qs", language)
    assert qp_qs is not None and qp_qs.gradations[0].range_text == "≥1.5"


def test_note_survives_store_and_constructor_round_trips(tmp_path) -> None:
    from echo_personal_tool.constructor.models.reference_model import ParameterModel
    from echo_personal_tool.domain.services.reference_data_store import ReferenceDataStore, _param_to_dict

    store = ReferenceDataStore(language="en").load()
    param = next(p for *_rest, p in store.search("mr_eroa_secondary") if p.id == "mr_eroa_secondary")
    assert param.note
    assert _param_to_dict(param)["note"] == param.note
    model = ParameterModel.from_dict(_param_to_dict(param))
    assert model.note == param.note
    assert model.to_dict()["note"] == param.note
    assert "note" not in ParameterModel(id="x", name="X").to_dict()


# ── report and menu ─────────────────────────────────────────────────────────
def test_new_calipers_land_in_their_groups() -> None:
    assert group_for_label("PISA MS") == GROUP_MITRAL_VALVE
    assert group_for_label("RVOTd") == GROUP_RIGHT_VENTRICLE


def test_report_lists_stage3_outputs_once() -> None:
    manual = {**_MS, **_PULM, **_SHUNT, **_LV, "orifice_d": 2.2}
    calculations = evaluate(resolve_study_inputs(doppler=None, manual=manual))
    groups = {g.key: g for g in build_report_groups(MeasurementSnapshot(calculations=calculations))}
    group = groups[GROUP_CALCULATIONS]
    labels = [v.label for v in group.values]
    rows = {v.label: (v.value, v.unit) for v in group.values}
    assert rows["MVA (PHT)"] == ("1.00", "cm²")
    assert rows["PASP"] == ("44", "mmHg")
    assert rows["PVR"] == ("1.36", "WU")  # RVOT VTI 25 cm from the shunt inputs wins
    assert rows["Qp:Qs"] == ("1.80", "")
    assert rows["EF (Teichholz)"] == ("65", "%")
    assert rows["Area (D)"] == ("3.80", "cm²")
    # Shared outputs (LVOT/RVOT area) appear once.
    assert labels.count("LVOT area") == 1
    assert labels.count("RVOT area") == 1
    assert any(note.startswith("LV by Teichholz") for note in group.notes)


@pytest.mark.gui
def test_menu_offers_pisa_ms_and_rvotd_calipers() -> None:
    from echo_personal_tool.presentation.measures_menu import tool_menu_catalog

    calipers = {button.caliper_label for _key, buttons in tool_menu_catalog() for button in buttons}
    assert {"PISA MS", "RVOTd"} <= calipers


@pytest.mark.gui
def test_panel_shows_reference_note_and_stage3_cards() -> None:
    from PySide6.QtWidgets import QApplication, QGroupBox, QLabel

    from echo_personal_tool.presentation.calculators_panel import MODE_STANDALONE, CalculatorsPanel

    _app = QApplication.instance() or QApplication([])
    panel = CalculatorsPanel()
    panel.set_mode(MODE_STANDALONE)
    for card in ("mitral_valve_area", "pulmonary_pressure", "qp_qs", "teichholz", "orifice_area"):
        assert panel.findChild(QGroupBox, f"calcCard_{card}") is not None, card
    hints = panel.findChild(QLabel, "calcHints_pisa_mr").text()
    assert "Elliptical orifice" in hints
    assert "<i>*" in hints
