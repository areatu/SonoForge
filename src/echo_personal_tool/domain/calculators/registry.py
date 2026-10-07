"""Declarative calculator registry (Э11).

A calculator is data: its inputs (with units and plausible ranges), its
outputs (each with the formula shown to the user and the inputs it needs),
the assumptions and the literature it rests on.  The panel, the report and
the tests are all driven by this registry, so adding a calculator means adding
a :class:`CalculatorSpec` here plus the pure formula in
``domain/calculations/`` — no UI code.

Stage 11а (decision D-25) ships the continuity family: LVOT area, SV, SVi,
CO, CI, AVA (VTI and Vmax), AVAi and DVI.  Stage 11б adds PISA for MR and AR
(flow rate, EROA, RVol, RF).  MVA/PASP/Qp:Qs (11в) follow the same pattern.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from echo_personal_tool.domain.calculations.continuity import (
    ava_continuity_cm2,
    cardiac_output_l_min,
    dimensionless_index,
    indexed_to_bsa,
    lvot_area_cm2,
    stroke_volume_ml,
)
from echo_personal_tool.domain.calculations.pisa import (
    eroa_cm2,
    pisa_flow_rate_ml_s,
    regurgitant_fraction_ar_percent,
    regurgitant_fraction_mr_percent,
    regurgitant_volume_ml,
)

Values = Mapping[str, float]

SECTION_CONTINUITY = "continuity"
SECTION_MR = "mr"
SECTION_AR = "ar"
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

CALCULATORS: tuple[CalculatorSpec, ...] = (STROKE_VOLUME, AORTIC_VALVE_AREA, PISA_MR, PISA_AR)

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
