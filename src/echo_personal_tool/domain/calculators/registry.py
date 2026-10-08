"""Declarative calculator registry (Э11).

A calculator is data: its inputs (with units and plausible ranges), its
outputs (each with the formula shown to the user and the inputs it needs),
the assumptions and the literature it rests on.  The panel, the report and
the tests are all driven by this registry, so adding a calculator means adding
a :class:`CalculatorSpec` here plus the pure formula in
``domain/calculations/`` — no UI code.

Stage 11а (decision D-25) ships the continuity family: LVOT area, SV, SVi,
CO, CI, AVA (VTI and Vmax), AVAi and DVI.  Stage 11б adds PISA for MR and AR
(flow rate, EROA, RVol, RF).  Stage 11в adds MVA (PHT and PISA), pulmonary
pressures and resistance (PASP, mPAP, PVR), Qp:Qs, Teichholz volumes/EF and a
plain orifice-area card (LVOT, RVOT, any diameter), and LV/RV dP/dt from the
MR/TR jets.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from echo_personal_tool.domain.calculations.continuity import (
    ava_continuity_cm2,
    cardiac_output_l_min,
    circle_area_cm2,
    dimensionless_index,
    indexed_to_bsa,
    lvot_area_cm2,
    qp_qs_ratio,
    stroke_volume_ml,
)
from echo_personal_tool.domain.calculations.contractility import lv_dpdt_mmhg_s, rv_dpdt_mmhg_s
from echo_personal_tool.domain.calculations.mitral_stenosis import mva_pht_cm2, mva_pisa_cm2
from echo_personal_tool.domain.calculations.pisa import (
    eroa_cm2,
    pisa_flow_rate_ml_s,
    regurgitant_fraction_ar_percent,
    regurgitant_fraction_mr_percent,
    regurgitant_volume_ml,
)
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

Values = Mapping[str, float]

SECTION_CONTINUITY = "continuity"
SECTION_MR = "mr"
SECTION_AR = "ar"
SECTION_MS = "ms"
SECTION_RIGHT = "right"
SECTION_LV = "lv"
SECTION_DPDT = "dpdt"
SECTION_ORIFICE = "orifice"
SECTION_PATIENT = "patient"


@dataclass(frozen=True)
class InputSpec:
    """One calculator input.

    ``label`` is the scanner-style abbreviation shown everywhere (latin, like
    the measurement menu); ``name_key`` is the i18n key of the full name.
    Values are entered and shown in ``unit``.  ``plausible`` bounds only raise
    a warning — an unusual value is still calculated (paediatrics, dilated
    LVOT), it is never clamped or rejected.
    """

    id: str
    label: str
    name_key: str
    unit: str
    decimals: int
    plausible: tuple[float, float]
    #: Hard bounds of the input editor (typos such as 200 cm for LVOTd).
    editor_range: tuple[float, float]
    #: Heading the panel groups the input under (``calc.section.<section>``).
    section: str = SECTION_CONTINUITY
    #: Nothing in the study provides it (PISA aliasing velocity: the colour
    #: scale is not in the DICOM header) — the panel asks for manual entry.
    manual_only: bool = False


@dataclass(frozen=True)
class OutputSpec:
    id: str
    label: str
    name_key: str
    unit: str
    decimals: int
    #: Formula in scanner terms, language-neutral (shown on the card).
    formula: str
    #: Input ids and/or ids of outputs computed earlier in the same calculator.
    requires: tuple[str, ...]
    compute: Callable[[Values], float | None]
    #: Parameter ids in the structured reference whose gradations the card
    #: shows (several when thresholds depend on context, e.g. primary vs
    #: secondary MR).  No grade is assigned automatically.
    reference_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class CalculatorSpec:
    id: str
    title_key: str
    outputs: tuple[OutputSpec, ...]
    assumptions_key: str
    references: tuple[str, ...]

    def output(self, output_id: str) -> OutputSpec | None:
        return next((item for item in self.outputs if item.id == output_id), None)

    @property
    def input_ids(self) -> tuple[str, ...]:
        """Every input the calculator reads, in first-use order."""
        seen: list[str] = []
        for output in self.outputs:
            for item in self.input_closure(output.id):
                if item not in seen:
                    seen.append(item)
        return tuple(seen)

    def input_closure(self, output_id: str) -> tuple[str, ...]:
        """Inputs an output depends on, following output→output references."""
        output_ids = {item.id for item in self.outputs}
        result: list[str] = []

        def visit(item_id: str) -> None:
            if item_id in output_ids:
                spec = self.output(item_id)
                assert spec is not None
                for dependency in spec.requires:
                    visit(dependency)
            elif item_id not in result:
                result.append(item_id)

        visit(output_id)
        return tuple(result)


INPUTS: tuple[InputSpec, ...] = (
    InputSpec("lvot_d", "LVOTd", "calc.input.lvot_d", "cm", 2, (1.5, 3.0), (0.3, 6.0)),
    InputSpec("lvot_vti", "LVOT VTI", "calc.input.lvot_vti", "cm", 1, (5.0, 40.0), (0.5, 200.0)),
    InputSpec("av_vti", "AV VTI", "calc.input.av_vti", "cm", 1, (10.0, 200.0), (0.5, 400.0)),
    InputSpec("lvot_vmax", "LVOT Vmax", "calc.input.lvot_vmax", "cm/s", 0, (30.0, 250.0), (1.0, 800.0)),
    InputSpec("av_vmax", "AV Vmax", "calc.input.av_vmax", "m/s", 2, (0.5, 7.0), (0.05, 10.0)),
    # PISA MR (Э11б): radius from the "PISA MR" caliper on a colour frame.
    InputSpec("pisa_r_mr", "PISA r MR", "calc.input.pisa_r_mr", "cm", 2, (0.3, 1.5), (0.05, 3.0), SECTION_MR),
    InputSpec("va_mr", "Va MR", "calc.input.va_mr", "cm/s", 0, (15.0, 70.0), (1.0, 150.0), SECTION_MR, True),
    InputSpec("mr_vmax", "MR Vmax", "calc.input.mr_vmax", "m/s", 2, (3.0, 7.0), (0.1, 10.0), SECTION_MR),
    InputSpec("mr_vti", "MR VTI", "calc.input.mr_vti", "cm", 1, (50.0, 250.0), (1.0, 500.0), SECTION_MR),
    InputSpec("pisa_r_ar", "PISA r AR", "calc.input.pisa_r_ar", "cm", 2, (0.2, 1.2), (0.05, 3.0), SECTION_AR),
    InputSpec("va_ar", "Va AR", "calc.input.va_ar", "cm/s", 0, (15.0, 70.0), (1.0, 150.0), SECTION_AR, True),
    InputSpec("ar_vmax", "AR Vmax", "calc.input.ar_vmax", "m/s", 2, (2.5, 6.5), (0.1, 10.0), SECTION_AR),
    InputSpec("ar_vti", "AR VTI", "calc.input.ar_vti", "cm", 1, (50.0, 300.0), (1.0, 600.0), SECTION_AR),
    # Mitral stenosis (Э11в): PHT interval, PISA radius ("PISA MS" caliper),
    # aliasing velocity and funnel angle typed by the user, CW peak velocity.
    InputSpec("mv_pht", "MV PHT", "calc.input.mv_pht", "ms", 0, (30.0, 500.0), (5.0, 1500.0), SECTION_MS),
    InputSpec("pisa_r_ms", "PISA r MS", "calc.input.pisa_r_ms", "cm", 2, (0.3, 2.0), (0.05, 3.0), SECTION_MS),
    InputSpec("va_ms", "Va MS", "calc.input.va_ms", "cm/s", 0, (15.0, 70.0), (1.0, 150.0), SECTION_MS, True),
    InputSpec("mv_vmax", "MV Vmax", "calc.input.mv_vmax", "m/s", 2, (1.0, 3.5), (0.1, 10.0), SECTION_MS),
    InputSpec("ms_angle", "α MS", "calc.input.ms_angle", "°", 0, (60.0, 180.0), (10.0, 180.0), SECTION_MS, True),
    # Right heart and pulmonary haemodynamics (Э11в).  RVOTd is the diameter at
    # the PW sample site of RVOT VTI (caliper "RVOTd"), not the RV-size "RVOT".
    InputSpec("rvot_d", "RVOTd", "calc.input.rvot_d", "cm", 2, (1.5, 3.5), (0.3, 6.0), SECTION_RIGHT),
    InputSpec("rvot_vti", "RVOT VTI", "calc.input.rvot_vti", "cm", 1, (5.0, 40.0), (0.5, 200.0), SECTION_RIGHT),
    InputSpec("tr_vmax", "TR Vmax", "calc.input.tr_vmax", "m/s", 2, (1.5, 6.0), (0.1, 10.0), SECTION_RIGHT),
    InputSpec("rap", "RAP", "calc.input.rap", "mmHg", 0, (0.0, 20.0), (0.0, 40.0), SECTION_RIGHT, True),
    InputSpec("rvot_at", "RVOT AT", "calc.input.rvot_at", "ms", 0, (50.0, 170.0), (5.0, 500.0), SECTION_RIGHT),
    # LV linear dimensions (2D or M-mode calipers LVEDD / LVESD).
    InputSpec("lvedd", "LVEDD", "calc.input.lvedd", "cm", 2, (3.0, 7.0), (0.5, 12.0), SECTION_LV),
    InputSpec("lvesd", "LVESD", "calc.input.lvesd", "cm", 2, (2.0, 5.5), (0.3, 10.0), SECTION_LV),
    # dP/dt: Δt between fixed velocities on the regurgitant CW jet ("MR dP/dt",
    # "TR dP/dt" Doppler intervals).  Plausible ranges ≈ dP/dt 400–3200 (LV) and
    # 200–1500 mmHg/s (RV).
    InputSpec("mr_dpdt_dt", "MR dP/dt Δt", "calc.input.mr_dpdt_dt", "ms", 0, (10.0, 120.0), (2.0, 400.0), SECTION_DPDT),
    InputSpec("tr_dpdt_dt", "TR dP/dt Δt", "calc.input.tr_dpdt_dt", "ms", 0, (8.0, 80.0), (2.0, 400.0), SECTION_DPDT),
    # Any other circular orifice (pulmonary annulus, conduit…): typed only.
    InputSpec("orifice_d", "D", "calc.input.orifice_d", "cm", 2, (0.5, 4.0), (0.05, 10.0), SECTION_ORIFICE, True),
    InputSpec("hr", "HR", "calc.input.hr", "bpm", 0, (30.0, 200.0), (10.0, 300.0), SECTION_PATIENT),
    InputSpec("height", "Height", "calc.input.height", "cm", 0, (50.0, 230.0), (20.0, 260.0), SECTION_PATIENT),
    InputSpec("weight", "Weight", "calc.input.weight", "kg", 1, (3.0, 250.0), (0.5, 400.0), SECTION_PATIENT),
    InputSpec("bsa", "BSA", "calc.input.bsa", "m²", 2, (0.3, 3.0), (0.05, 4.0), SECTION_PATIENT),
)

_INPUT_BY_ID = {item.id: item for item in INPUTS}


def input_spec(input_id: str) -> InputSpec | None:
    return _INPUT_BY_ID.get(input_id)


_REF_QUINONES_2002 = (
    "Quiñones MA et al. Recommendations for quantification of Doppler echocardiography. "
    "J Am Soc Echocardiogr 2002;15:167–184"
)
_REF_ZOGHBI_2017 = (
    "Zoghbi WA et al. Recommendations for noninvasive evaluation of native valvular regurgitation: "
    "a report from the ASE developed in collaboration with the SCMR. J Am Soc Echocardiogr 2017;30:303–371"
)
_REF_BAUMGARTNER_2009 = (
    "Baumgartner H et al. Echocardiographic assessment of valve stenosis: EAE/ASE recommendations "
    "for clinical practice. J Am Soc Echocardiogr 2009;22:1–23"
)
_REF_RUDSKI_2010 = (
    "Rudski LG et al. Guidelines for the echocardiographic assessment of the right heart in adults. "
    "J Am Soc Echocardiogr 2010;23:685–713"
)
_REF_CHEMLA_2004 = (
    "Chemla D et al. New formula for predicting mean pulmonary artery pressure using systolic "
    "pulmonary artery pressure. Chest 2004;126:1313–1317"
)
_REF_MAHAN_1983 = (
    "Mahan G et al. Estimation of pulmonary artery pressure by pulsed Doppler echocardiography. "
    "Circulation 1983;68(Suppl III):III-367"
)
_REF_ABBAS_2003 = (
    "Abbas AE et al. A simple method for noninvasive estimation of pulmonary vascular resistance. "
    "J Am Coll Cardiol 2003;41:1021–1027"
)
_REF_HUMBERT_2022 = (
    "Humbert M et al. 2022 ESC/ERS Guidelines for the diagnosis and treatment of pulmonary "
    "hypertension. Eur Heart J 2022;43:3618–3731"
)
_REF_TEICHHOLZ_1976 = (
    "Teichholz LE et al. Problems in echocardiographic volume determinations: echocardiographic-"
    "angiographic correlations in the presence or absence of asynergy. Am J Cardiol 1976;37:7–11"
)
_REF_LANG_2015 = (
    "Lang RM et al. Recommendations for cardiac chamber quantification by echocardiography in adults: "
    "an update from the ASE and the EACVI. J Am Soc Echocardiogr 2015;28:1–39"
)
_REF_BARGIGGIA_1989 = (
    "Bargiggia GS et al. A new method for estimating left ventricular dP/dt by continuous wave "
    "Doppler-echocardiography. Validation studies at cardiac catheterization. Circulation 1989;80:1287–1292"
)
_REF_ASE_RIGHT_HEART_2025 = (
    "Guidelines for the echocardiographic assessment of the right heart in adults and special "
    "considerations in pulmonary hypertension: recommendations from the ASE. J Am Soc Echocardiogr 2025;38(3)"
)
_REF_BAUMGARTNER_2017 = (
    "Baumgartner H et al. Recommendations on the echocardiographic assessment of aortic valve "
    "stenosis: a focused update from the EACVI and the ASE. J Am Soc Echocardiogr 2017;30:372–392"
)


def _area(values: Values) -> float | None:
    return lvot_area_cm2(values.get("lvot_d"))


def _sv(values: Values) -> float | None:
    return stroke_volume_ml(values.get("lvot_area"), values.get("lvot_vti"))


def _av_vmax_cm_s(values: Values) -> float | None:
    av_vmax = values.get("av_vmax")
    return None if av_vmax is None else av_vmax * 100.0


_LVOT_AREA = OutputSpec(
    "lvot_area",
    "LVOT area",
    "calc.output.lvot_area",
    "cm²",
    2,
    "π × (LVOTd / 2)²",
    ("lvot_d",),
    _area,
)

STROKE_VOLUME = CalculatorSpec(
    id="stroke_volume",
    title_key="calc.title.stroke_volume",
    outputs=(
        _LVOT_AREA,
        OutputSpec("sv", "SV", "calc.output.sv", "mL", 1, "LVOT area × LVOT VTI", ("lvot_area", "lvot_vti"), _sv),
        OutputSpec(
            "svi",
            "SVi",
            "calc.output.svi",
            "mL/m²",
            1,
            "SV / BSA",
            ("sv", "bsa"),
            lambda v: indexed_to_bsa(v.get("sv"), v.get("bsa")),
        ),
        OutputSpec(
            "co",
            "CO",
            "calc.output.co",
            "L/min",
            2,
            "SV × HR / 1000",
            ("sv", "hr"),
            lambda v: cardiac_output_l_min(v.get("sv"), v.get("hr")),
        ),
        OutputSpec(
            "ci",
            "CI",
            "calc.output.ci",
            "L/min/m²",
            2,
            "CO / BSA",
            ("co", "bsa"),
            lambda v: indexed_to_bsa(v.get("co"), v.get("bsa")),
        ),
    ),
    assumptions_key="calc.assumptions.stroke_volume",
    references=(_REF_QUINONES_2002, _REF_BAUMGARTNER_2017),
)

AORTIC_VALVE_AREA = CalculatorSpec(
    id="aortic_valve_area",
    title_key="calc.title.aortic_valve_area",
    outputs=(
        _LVOT_AREA,
        OutputSpec(
            "ava_vti",
            "AVA (VTI)",
            "calc.output.ava_vti",
            "cm²",
            2,
            "LVOT area × LVOT VTI / AV VTI",
            ("lvot_area", "lvot_vti", "av_vti"),
            lambda v: ava_continuity_cm2(v.get("lvot_area"), v.get("lvot_vti"), v.get("av_vti")),
            reference_ids=("as_ava",),
        ),
        OutputSpec(
            "ava_vmax",
            "AVA (Vmax)",
            "calc.output.ava_vmax",
            "cm²",
            2,
            "LVOT area × LVOT Vmax / AV Vmax",
            ("lvot_area", "lvot_vmax", "av_vmax"),
            lambda v: ava_continuity_cm2(v.get("lvot_area"), v.get("lvot_vmax"), _av_vmax_cm_s(v)),
            reference_ids=("as_ava",),
        ),
        OutputSpec(
            "avai",
            "AVAi",
            "calc.output.avai",
            "cm²/m²",
            2,
            "AVA (VTI) / BSA",
            ("ava_vti", "bsa"),
            lambda v: indexed_to_bsa(v.get("ava_vti"), v.get("bsa")),
            reference_ids=("as_ava_indexed",),
        ),
        OutputSpec(
            "dvi_vti",
            "DVI (VTI)",
            "calc.output.dvi_vti",
            "",
            2,
            "LVOT VTI / AV VTI",
            ("lvot_vti", "av_vti"),
            lambda v: dimensionless_index(v.get("lvot_vti"), v.get("av_vti")),
            reference_ids=("as_dsi",),
        ),
        OutputSpec(
            "dvi_vmax",
            "DVI (Vmax)",
            "calc.output.dvi_vmax",
            "",
            2,
            "LVOT Vmax / AV Vmax",
            ("lvot_vmax", "av_vmax"),
            lambda v: dimensionless_index(v.get("lvot_vmax"), _av_vmax_cm_s(v)),
            reference_ids=("as_dsi",),
        ),
    ),
    assumptions_key="calc.assumptions.aortic_valve_area",
    references=(_REF_BAUMGARTNER_2017,),
)


def _cm_s(input_id: str) -> Callable[[Values], float | None]:
    """CW jet velocities are entered in m/s (scanner convention); formulas use cm/s."""

    def convert(values: Values) -> float | None:
        value = values.get(input_id)
        return None if value is None else value * 100.0

    return convert


def _lvot_sv(values: Values) -> float | None:
    return stroke_volume_ml(lvot_area_cm2(values.get("lvot_d")), values.get("lvot_vti"))


def _pisa_calculator(valve: str) -> CalculatorSpec:
    """MR and AR share the method; only labels, inputs, RF definition and thresholds differ."""
    key = valve.lower()
    upper = valve.upper()
    jet_cm_s = _cm_s(f"{key}_vmax")
    flow_id, eroa_id, rvol_id, rf_id = (f"pisa_flow_{key}", f"eroa_{key}", f"rvol_{key}", f"rf_{key}")
    if key == "mr":
        refs_eroa = ("mr_eroa_primary", "mr_eroa_secondary")
        refs_rvol = ("mr_rvol_primary", "mr_rvol_secondary")
        refs_rf = ("mr_rf_primary", "mr_rf_secondary")
        rf_formula = "RVol / (RVol + SV LVOT) × 100"

        def rf(v: Values) -> float | None:
            return regurgitant_fraction_mr_percent(v.get(rvol_id), _lvot_sv(v))

    else:
        refs_eroa, refs_rvol, refs_rf = ("ar_eroa",), ("ar_rvol",), ("ar_rf",)
        rf_formula = "RVol / SV LVOT × 100"

        def rf(v: Values) -> float | None:
            return regurgitant_fraction_ar_percent(v.get(rvol_id), _lvot_sv(v))

    return CalculatorSpec(
        id=f"pisa_{key}",
        title_key=f"calc.title.pisa_{key}",
        outputs=(
            OutputSpec(
                flow_id,
                f"{upper} flow rate",
                f"calc.output.pisa_flow_{key}",
                "mL/s",
                0,
                f"2π × (PISA r {upper})² × Va {upper}",
                (f"pisa_r_{key}", f"va_{key}"),
                lambda v: pisa_flow_rate_ml_s(v.get(f"pisa_r_{key}"), v.get(f"va_{key}")),
            ),
            OutputSpec(
                eroa_id,
                f"{upper} EROA",
                f"calc.output.eroa_{key}",
                "cm²",
                2,
                f"{upper} flow rate / {upper} Vmax",
                (flow_id, f"{key}_vmax"),
                lambda v: eroa_cm2(v.get(flow_id), jet_cm_s(v)),
                reference_ids=refs_eroa,
            ),
            OutputSpec(
                rvol_id,
                f"{upper} RVol",
                f"calc.output.rvol_{key}",
                "mL",
                0,
                f"{upper} EROA × {upper} VTI",
                (eroa_id, f"{key}_vti"),
                lambda v: regurgitant_volume_ml(v.get(eroa_id), v.get(f"{key}_vti")),
                reference_ids=refs_rvol,
            ),
            OutputSpec(
                rf_id,
                f"{upper} RF",
                f"calc.output.rf_{key}",
                "%",
                0,
                rf_formula,
                (rvol_id, "lvot_d", "lvot_vti"),
                rf,
                reference_ids=refs_rf,
            ),
        ),
        assumptions_key=f"calc.assumptions.pisa_{key}",
        references=(_REF_ZOGHBI_2017,),
    )


PISA_MR = _pisa_calculator("MR")
PISA_AR = _pisa_calculator("AR")


MITRAL_VALVE_AREA = CalculatorSpec(
    id="mitral_valve_area",
    title_key="calc.title.mitral_valve_area",
    outputs=(
        OutputSpec(
            "mva_pht",
            "MVA (PHT)",
            "calc.output.mva_pht",
            "cm²",
            2,
            "220 / MV PHT",
            ("mv_pht",),
            lambda v: mva_pht_cm2(v.get("mv_pht")),
            reference_ids=("ms_area", "ms_pht"),
        ),
        OutputSpec(
            "mva_pisa",
            "MVA (PISA)",
            "calc.output.mva_pisa",
            "cm²",
            2,
            "2π × (PISA r MS)² × α MS / 180 × Va MS / MV Vmax",
            ("pisa_r_ms", "va_ms", "mv_vmax", "ms_angle"),
            lambda v: mva_pisa_cm2(v.get("pisa_r_ms"), v.get("va_ms"), _cm_s("mv_vmax")(v), v.get("ms_angle")),
            reference_ids=("ms_area",),
        ),
    ),
    assumptions_key="calc.assumptions.mitral_valve_area",
    references=(_REF_BAUMGARTNER_2009,),
)


PULMONARY_PRESSURE = CalculatorSpec(
    id="pulmonary_pressure",
    title_key="calc.title.pulmonary_pressure",
    outputs=(
        OutputSpec(
            "tr_pg",
            "TR PGmax",
            "calc.output.tr_pg",
            "mmHg",
            0,
            "4 × TR Vmax²",
            ("tr_vmax",),
            lambda v: tr_gradient_mmhg(v.get("tr_vmax")),
            reference_ids=("tr_vmax_ph",),
        ),
        OutputSpec(
            "pasp",
            "PASP",
            "calc.output.pasp",
            "mmHg",
            0,
            "TR PGmax + RAP",
            ("tr_pg", "rap"),
            lambda v: pasp_mmhg(v.get("tr_pg"), v.get("rap")),
            reference_ids=("spap",),
        ),
        OutputSpec(
            "mpap_pasp",
            "mPAP (PASP)",
            "calc.output.mpap_pasp",
            "mmHg",
            0,
            "0.61 × PASP + 2",
            ("pasp",),
            lambda v: mpap_chemla_mmhg(v.get("pasp")),
            reference_ids=("mpap",),
        ),
        OutputSpec(
            "mpap_at",
            "mPAP (AT)",
            "calc.output.mpap_at",
            "mmHg",
            0,
            "79 − 0.45 × RVOT AT",
            ("rvot_at",),
            lambda v: mpap_mahan_mmhg(v.get("rvot_at")),
            reference_ids=("mpap",),
        ),
        OutputSpec(
            "pvr",
            "PVR",
            "calc.output.pvr",
            "WU",
            2,
            "10 × TR Vmax / RVOT VTI + 0.16",
            ("tr_vmax", "rvot_vti"),
            lambda v: pvr_abbas_wu(v.get("tr_vmax"), v.get("rvot_vti")),
            reference_ids=("pvr",),
        ),
    ),
    assumptions_key="calc.assumptions.pulmonary_pressure",
    references=(_REF_RUDSKI_2010, _REF_CHEMLA_2004, _REF_MAHAN_1983, _REF_ABBAS_2003, _REF_HUMBERT_2022),
)


_RVOT_AREA = OutputSpec(
    "rvot_area",
    "RVOT area",
    "calc.output.rvot_area",
    "cm²",
    2,
    "π × (RVOTd / 2)²",
    ("rvot_d",),
    lambda v: circle_area_cm2(v.get("rvot_d")),
)

QP_QS = CalculatorSpec(
    id="qp_qs",
    title_key="calc.title.qp_qs",
    outputs=(
        _RVOT_AREA,
        OutputSpec(
            "qp",
            "Qp (SV RVOT)",
            "calc.output.qp",
            "mL",
            1,
            "RVOT area × RVOT VTI",
            ("rvot_area", "rvot_vti"),
            lambda v: stroke_volume_ml(v.get("rvot_area"), v.get("rvot_vti")),
        ),
        _LVOT_AREA,
        OutputSpec(
            "qs",
            "Qs (SV LVOT)",
            "calc.output.qs",
            "mL",
            1,
            "LVOT area × LVOT VTI",
            ("lvot_area", "lvot_vti"),
            lambda v: stroke_volume_ml(v.get("lvot_area"), v.get("lvot_vti")),
        ),
        OutputSpec(
            "qp_qs",
            "Qp:Qs",
            "calc.output.qp_qs",
            "",
            2,
            "Qp / Qs",
            ("qp", "qs"),
            lambda v: qp_qs_ratio(v.get("qp"), v.get("qs")),
            reference_ids=("qp_qs",),
        ),
    ),
    assumptions_key="calc.assumptions.qp_qs",
    references=(_REF_QUINONES_2002,),
)


def _teichholz_sv(values: Values) -> float | None:
    edv, esv = values.get("edv_teich"), values.get("esv_teich")
    if edv is None or esv is None or esv >= edv:
        return None
    return edv - esv


TEICHHOLZ = CalculatorSpec(
    id="teichholz",
    title_key="calc.title.teichholz",
    outputs=(
        OutputSpec(
            "edv_teich",
            "EDV (Teichholz)",
            "calc.output.edv_teich",
            "mL",
            0,
            "7 / (2.4 + LVEDD) × LVEDD³",
            ("lvedd",),
            lambda v: volume_from_cm_ml(v.get("lvedd")),
        ),
        OutputSpec(
            "esv_teich",
            "ESV (Teichholz)",
            "calc.output.esv_teich",
            "mL",
            0,
            "7 / (2.4 + LVESD) × LVESD³",
            ("lvesd",),
            lambda v: volume_from_cm_ml(v.get("lvesd")),
        ),
        OutputSpec(
            "sv_teich",
            "SV (Teichholz)",
            "calc.output.sv_teich",
            "mL",
            0,
            "EDV − ESV",
            ("edv_teich", "esv_teich"),
            _teichholz_sv,
        ),
        OutputSpec(
            "ef_teich",
            "EF (Teichholz)",
            "calc.output.ef_teich",
            "%",
            0,
            "(EDV − ESV) / EDV × 100",
            ("edv_teich", "esv_teich"),
            lambda v: ejection_fraction_percent(v.get("edv_teich"), v.get("esv_teich")),
        ),
        OutputSpec(
            "fs",
            "FS",
            "calc.output.fs",
            "%",
            0,
            "(LVEDD − LVESD) / LVEDD × 100",
            ("lvedd", "lvesd"),
            lambda v: fractional_shortening_percent(v.get("lvedd"), v.get("lvesd")),
        ),
    ),
    assumptions_key="calc.assumptions.teichholz",
    references=(_REF_TEICHHOLZ_1976, _REF_LANG_2015),
)


ORIFICE_AREA = CalculatorSpec(
    id="orifice_area",
    title_key="calc.title.orifice_area",
    outputs=(
        _LVOT_AREA,
        _RVOT_AREA,
        OutputSpec(
            "area_d",
            "Area (D)",
            "calc.output.area_d",
            "cm²",
            2,
            "π × (D / 2)²",
            ("orifice_d",),
            lambda v: circle_area_cm2(v.get("orifice_d")),
        ),
    ),
    assumptions_key="calc.assumptions.orifice_area",
    references=(_REF_QUINONES_2002,),
)

DPDT = CalculatorSpec(
    id="dpdt",
    title_key="calc.title.dpdt",
    outputs=(
        OutputSpec(
            "lv_dpdt",
            "LV dP/dt",
            "calc.output.lv_dpdt",
            "mmHg/s",
            0,
            "32 mmHg / Δt(MR 1→3 m/s)",
            ("mr_dpdt_dt",),
            lambda v: lv_dpdt_mmhg_s(v.get("mr_dpdt_dt")),
            reference_ids=("lv_dpdt",),
        ),
        OutputSpec(
            "rv_dpdt",
            "RV dP/dt",
            "calc.output.rv_dpdt",
            "mmHg/s",
            0,
            "12 mmHg / Δt(TR 1→2 m/s)",
            ("tr_dpdt_dt",),
            lambda v: rv_dpdt_mmhg_s(v.get("tr_dpdt_dt")),
            reference_ids=("rv_dpdt",),
        ),
    ),
    assumptions_key="calc.assumptions.dpdt",
    references=(_REF_BARGIGGIA_1989, _REF_RUDSKI_2010, _REF_ASE_RIGHT_HEART_2025),
)

CALCULATORS: tuple[CalculatorSpec, ...] = (
    STROKE_VOLUME,
    AORTIC_VALVE_AREA,
    PISA_MR,
    PISA_AR,
    MITRAL_VALVE_AREA,
    PULMONARY_PRESSURE,
    QP_QS,
    TEICHHOLZ,
    DPDT,
    ORIFICE_AREA,
)

_CALCULATOR_BY_ID = {item.id: item for item in CALCULATORS}


def calculator_spec(calculator_id: str) -> CalculatorSpec | None:
    return _CALCULATOR_BY_ID.get(calculator_id)


def all_input_ids() -> tuple[str, ...]:
    """Inputs of every calculator plus the BSA sources, in display order."""
    used: set[str] = set()
    for calculator in CALCULATORS:
        used.update(calculator.input_ids)
    if "bsa" in used:
        used.update({"height", "weight"})
    return tuple(item.id for item in INPUTS if item.id in used)
