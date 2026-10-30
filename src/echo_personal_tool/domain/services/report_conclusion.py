"""Conservative, source-versioned conclusion findings from a study snapshot.

The rules are deliberately narrower than the measurement report: a missing
observation is never normal, conflicting valve metrics become a review item,
and the rendered block contains qualitative phrases only.  This is a draft
for physician review, not an autonomous diagnosis.  See
``docs/superpowers/specs/2026-10-30-report-conclusion-autofill-ru.md``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Final

from echo_personal_tool.domain.calculations.body_surface import resolve_bsa_basis
from echo_personal_tool.domain.calculators.models import SOURCE_MANUAL, CalculationsSnapshot, CalculatorResult
from echo_personal_tool.domain.models.measurements import MeasurementSnapshot, StrainReport
from echo_personal_tool.domain.services.bsa_freshness import evaluate_bsa_freshness
from echo_personal_tool.domain.services.doppler_repeats import mean_of_last
from echo_personal_tool.domain.services.report_builder import is_female, is_male
from echo_personal_tool.domain.services.strain_metrics import (
    AVC_SOURCE_AREA,
    AVC_SOURCE_ECG,
    AVC_SOURCE_ES,
    AVC_SOURCE_MANUAL,
    AVC_SOURCE_STRAIN_PEAK,
)
from echo_personal_tool.domain.translation import tr_for_language

RULESET_VERSION: Final[str] = "adult-tte-conservative-1"

SOURCE_CHAMBERS_2015: Final[str] = "ASE/EACVI 2015 chamber quantification"
SOURCE_RIGHT_HEART_2025: Final[str] = "ASE 2025 right heart"
SOURCE_AS_2017: Final[str] = "EACVI/ASE 2017 aortic stenosis"
SOURCE_REGURGITATION_2017: Final[str] = "ASE/SCMR 2017 native valvular regurgitation"
SOURCE_MS_2023: Final[str] = "ASE 2023 rheumatic heart disease"
SOURCE_STRAIN_2025: Final[str] = "ASE/EACVI/industry 2025 strain standardization"

_NORMAL: Final[int] = 40
_MILD: Final[int] = 30
_MODERATE: Final[int] = 20
_SEVERE: Final[int] = 10
_REVIEW: Final[int] = 0
_VIEWS: Final[frozenset[str]] = frozenset({"A4C", "A2C", "A3C"})
_AVC_SOURCES: Final[frozenset[str]] = frozenset(
    {AVC_SOURCE_MANUAL, AVC_SOURCE_ECG, AVC_SOURCE_AREA, AVC_SOURCE_STRAIN_PEAK, AVC_SOURCE_ES}
)


@dataclass(frozen=True)
class ConclusionFinding:
    """One stable, localized finding. ``priority`` is internal, never printed."""

    id: str
    text_key: str
    priority: int
    evidence: tuple[str, ...]
    sources: tuple[str, ...]


@dataclass(frozen=True)
class ConclusionDraft:
    findings: tuple[ConclusionFinding, ...] = ()
    notices: tuple[str, ...] = ()
    ruleset_version: str = RULESET_VERSION


@dataclass(frozen=True)
class ConclusionMerge:
    text: str
    generated_block: str
    changed: bool
    status_key: str
    preserved_edited_block: bool = False


def build_conclusion(
    snapshot: MeasurementSnapshot | None,
    *,
    sex: str = "",
    age_years: float | None = None,
) -> ConclusionDraft:
    """Build findings from typed measurements only; never parse report rows."""

    if snapshot is None or (age_years is not None and math.isfinite(age_years) and age_years < 18.0):
        return ConclusionDraft()
    if snapshot.calculations is not None and snapshot.calculations.standalone:
        return ConclusionDraft()

    findings: list[ConclusionFinding] = []
    notices: list[str] = []
    bsa_fresh = _bsa_is_fresh(snapshot)
    if snapshot.indexed is not None and not bsa_fresh:
        notices.append("report.conclusion.notice.bsa")

    findings.extend(_lv_findings(snapshot, sex=sex, bsa_fresh=bsa_fresh))
    strain_finding, strain_notice = _strain_finding(snapshot.strain)
    if strain_finding is not None:
        findings.append(strain_finding)
    if strain_notice is not None:
        notices.append(strain_notice)
    findings.extend(_atrial_findings(snapshot, bsa_fresh=bsa_fresh))
    findings.extend(_right_ventricle_findings(snapshot))
    findings.extend(_valve_findings(snapshot))
    ph = _ph_finding(snapshot)
    if ph is not None:
        findings.append(ph)

    ordered = tuple(sorted(findings, key=lambda item: (item.priority, item.id)))
    unique_notices = tuple(dict.fromkeys(notices))
    if ordered:
        unique_notices += ("report.conclusion.notice.review",)
    return ConclusionDraft(findings=ordered, notices=unique_notices)


def render_conclusion(draft: ConclusionDraft, language: str) -> str:
    """Render a qualitative bullet block. No numeric values are formatted."""

    if not draft.findings:
        return ""
    lines = [f"• {tr_for_language(item.text_key, language)}" for item in draft.findings]
    lines.extend(f"• {tr_for_language(key, language)}" for key in draft.notices)
    return "\n".join(lines)


def merge_conclusion(existing: str, generated: str, previous_generated: str = "") -> ConclusionMerge:
    """Append a block, or replace only the exact unedited managed block."""

    current = existing or ""
    if not generated:
        return ConclusionMerge(current, previous_generated, False, "report.conclusion.status.no_data")
    managed_start = _managed_block_start(current, previous_generated) if previous_generated else None
    if managed_start is not None:
        if previous_generated == generated:
            return ConclusionMerge(current, previous_generated, False, "report.conclusion.status.unchanged")
        end = managed_start + len(previous_generated)
        return ConclusionMerge(
            current[:managed_start] + generated + current[end:],
            generated,
            True,
            "report.conclusion.status.updated",
        )
    if _managed_block_start(current, generated) is not None:
        return ConclusionMerge(current, previous_generated, False, "report.conclusion.status.unchanged")
    edited = bool(previous_generated)
    return ConclusionMerge(
        _append_block(current, generated),
        generated,
        True,
        "report.conclusion.status.appended_after_edit" if edited else "report.conclusion.status.added",
        edited,
    )


def _managed_block_start(text: str, block: str) -> int | None:
    """Return the start of one exact whole-line block, or ``None``.

    A substring inside an edited line is not a managed block: replacing it
    would silently rewrite the physician's manual edit.
    """
    if not block:
        return None
    start = 0
    found: int | None = None
    while True:
        index = text.find(block, start)
        if index < 0:
            return found
        end = index + len(block)
        whole_lines = (index == 0 or text[index - 1] == "\n") and (end == len(text) or text[end] == "\n")
        if whole_lines:
            if found is not None:
                return None
            found = index
        start = index + 1


def _append_block(existing: str, block: str) -> str:
    if not existing:
        return block
    if existing.endswith("\n\n"):
        return existing + block
    if existing.endswith("\n"):
        return existing + "\n" + block
    return existing + "\n\n" + block


def _finite(value: float | None, *, minimum: float = 0.0, maximum: float | None = None) -> float | None:
    if value is None or not math.isfinite(value) or value <= minimum:
        return None
    if maximum is not None and value > maximum:
        return None
    return float(value)


def _bsa_is_fresh(snapshot: MeasurementSnapshot) -> bool:
    indexed = snapshot.indexed
    if indexed is None or _finite(indexed.bsa_m2) is None:
        return False
    manual_bsa = None
    calculations = snapshot.calculations
    if calculations is not None:
        item = calculations.input("bsa")
        if item is not None and item.source == SOURCE_MANUAL:
            manual_bsa = item.value
    current = resolve_bsa_basis(
        height_cm=snapshot.height_cm,
        weight_kg=snapshot.weight_kg,
        manual_bsa_m2=manual_bsa,
    )
    if current.value is None or not evaluate_bsa_freshness(indexed.bsa_basis, current).is_fresh:
        return False
    return math.isclose(indexed.bsa_m2, current.value, rel_tol=1e-9, abs_tol=0.0)


def _linear_mean(snapshot: MeasurementSnapshot, *labels: str) -> float | None:
    if not snapshot.spacing_calibrated:
        return None
    wanted = {label.casefold().strip() for label in labels}
    values: list[float] = []
    for item in snapshot.linear_measurements:
        value = item.millimeter_length
        if not item.doppler and item.label.casefold().strip() in wanted and _finite(value) is not None:
            assert value is not None
            values.append(float(value))
    return mean_of_last(values)


def _finding(
    finding_id: str,
    key: str,
    priority: int,
    evidence: tuple[str, ...],
    sources: tuple[str, ...],
) -> ConclusionFinding:
    return ConclusionFinding(finding_id, f"report.conclusion.finding.{key}", priority, evidence, sources)


def _ef_category(value: float, sex: str) -> str | None:
    if value < 30.0:
        return "severe"
    if value < 41.0:
        return "moderate"
    if is_female(sex):
        return "normal" if value >= 54.0 else "mild"
    if is_male(sex):
        return "normal" if value >= 52.0 else "mild"
    if value >= 54.0:
        return "normal"
    if value < 52.0:
        return "mild"
    return None


def _lv_findings(snapshot: MeasurementSnapshot, *, sex: str, bsa_fresh: bool) -> list[ConclusionFinding]:
    findings: list[ConclusionFinding] = []
    sources = (SOURCE_CHAMBERS_2015,)
    lvef = snapshot.lvef
    if snapshot.spacing_calibrated and lvef is not None and lvef.method in {"simpson_biplan", "simpson_monoplan"}:
        ef = _finite(lvef.lvef_percent, maximum=100.0)
        if ef is not None:
            category = _ef_category(ef, sex)
            teich = snapshot.teichholz
            teich_category = _ef_category(teich.lvef_percent, sex) if teich is not None else None
            if teich_category is not None and category is not None and teich_category != category:
                findings.append(_finding("lv.ef", "lv_ef.review", _REVIEW, ("lvef", "teichholz_ef"), sources))
            elif category is not None:
                method = "biplane" if lvef.method == "simpson_biplan" else "monoplane"
                priority = {"normal": _NORMAL, "mild": _MILD, "moderate": _MODERATE, "severe": _SEVERE}[category]
                findings.append(_finding("lv.ef", f"lv_ef.{category}.{method}", priority, ("lvef",), sources))
            else:
                findings.append(_finding("lv.ef", "lv_ef.review", _REVIEW, ("lvef",), sources))

    if bsa_fresh and lvef is not None and lvef.method == "simpson_biplan" and snapshot.indexed is not None:
        edvi = _finite(snapshot.indexed.simpson_edvi_ml_m2)
        if edvi is not None and (is_female(sex) or is_male(sex)):
            category = _lv_size_category(edvi, female=is_female(sex))
            if category is not None:
                priority = {"normal": _NORMAL, "mild": _MILD, "moderate": _MODERATE, "severe": _SEVERE}[category]
                findings.append(_finding("lv.size", f"lv_size.{category}", priority, ("lvedvi",), sources))
            else:
                findings.append(_finding("lv.size", "lv_size.review", _REVIEW, ("lvedvi",), sources))

    findings.extend(_wall_findings(snapshot, sex=sex))
    if bsa_fresh and snapshot.indexed is not None and (is_female(sex) or is_male(sex)):
        lvmi = _finite(snapshot.indexed.lvmi_g_m2)
        limit = 95.0 if is_female(sex) else 115.0
        if lvmi is not None and lvmi > limit:
            findings.append(_finding("lv.mass", "lv_mass.increased", _MILD, ("lvmi",), sources))
    rwt = _finite(snapshot.rwt)
    if rwt is not None and rwt > 0.42:
        findings.append(_finding("lv.rwt", "lv_rwt.increased", _MILD, ("rwt",), sources))
    return findings


def _lv_size_category(value: float, *, female: bool) -> str | None:
    low, normal, mild, moderate = (29.0, 61.0, 70.0, 80.0) if female else (34.0, 74.0, 89.0, 100.0)
    if value < low:
        return None
    if value <= normal:
        return "normal"
    if value <= mild:
        return "mild"
    if value <= moderate:
        return "moderate"
    return "severe"


def _wall_findings(snapshot: MeasurementSnapshot, *, sex: str) -> list[ConclusionFinding]:
    if not (is_female(sex) or is_male(sex)):
        return []
    ivs = _linear_mean(snapshot, "IVSd")
    pw = _linear_mean(snapshot, "LVPWd")
    if ivs is None or pw is None:
        return []
    upper = 10.0 if is_female(sex) else 11.0
    evidence = ("ivsd", "lvpwd")
    sources = (SOURCE_CHAMBERS_2015,)
    if ivs < 6.0 or pw < 6.0:
        return [_finding("lv.wall", "lv_wall.review", _REVIEW, evidence, sources)]
    thickness = max(ivs, pw)
    if thickness <= upper:
        return [_finding("lv.wall", "lv_wall.normal", _NORMAL, evidence, sources)]
    mild_limit, moderate_limit = (13.0, 15.0) if is_female(sex) else (14.0, 16.0)
    if thickness < mild_limit:
        return [_finding("lv.wall", "lv_wall.mild", _MILD, evidence, sources)]
    if thickness < moderate_limit:
        return [_finding("lv.wall", "lv_wall.moderate", _MODERATE, evidence, sources)]
    return [_finding("lv.wall", "lv_wall.severe", _SEVERE, evidence, sources)]


def _strain_finding(strain: StrainReport | None) -> tuple[ConclusionFinding | None, str | None]:
    if strain is None or not strain.has_values:
        return None, None
    views = {view for view, _value in strain.gls_by_view}
    qc = dict(strain.qc_by_view)
    avc = dict(strain.avc_source_by_view)
    values = [value for _view, value in strain.gls_by_view]
    complete = (
        views == _VIEWS
        and set(strain.views_valid) == _VIEWS
        and all(qc.get(view) == "valid" for view in _VIEWS)
        and strain.segments_missing == 0
        and strain.contour_source == "manual"
        and all(avc.get(view) in _AVC_SOURCES for view in _VIEWS)
        and all(math.isfinite(value) and value < 0.0 for value in values)
    )
    average = strain.gls_average
    if not complete or average is None or not math.isfinite(average) or average >= 0.0:
        return None, "report.conclusion.notice.strain_qc"
    if not math.isclose(average, sum(values) / len(values), rel_tol=0.0, abs_tol=0.05):
        return None, "report.conclusion.notice.strain_qc"
    magnitude = -average
    sources = (SOURCE_STRAIN_2025,)
    if magnitude > 20.0:
        finding = _finding("lv.gls", "gls.normal", _NORMAL, ("gls",), sources)
    elif magnitude >= 18.0:
        finding = _finding("lv.gls", "gls.borderline", _REVIEW, ("gls",), sources)
    else:
        finding = _finding("lv.gls", "gls.reduced", _MILD, ("gls",), sources)
    return finding, "report.conclusion.notice.strain_method"


def _atrial_findings(snapshot: MeasurementSnapshot, *, bsa_fresh: bool) -> list[ConclusionFinding]:
    findings: list[ConclusionFinding] = []
    if not bsa_fresh or snapshot.indexed is None:
        return findings
    la = snapshot.la_simpson
    if (
        la is not None
        and la.method == "simpson_biplan"
        and la.a4c is not None
        and la.a2c is not None
        and _finite(la.a4c.esv_ml) is not None
        and _finite(la.a2c.esv_ml) is not None
    ):
        lavi = _finite(snapshot.indexed.lav_bi_index_ml_m2)
        if lavi is not None:
            if lavi <= 34.0:
                category, priority = "normal", _NORMAL
            elif lavi < 42.0:
                category, priority = "mild", _MILD
            elif lavi < 49.0:
                category, priority = "moderate", _MODERATE
            else:
                category, priority = "severe", _SEVERE
            findings.append(
                _finding("la.size", f"la_size.{category}", priority, ("lavi_biplane",), (SOURCE_CHAMBERS_2015,))
            )
    ra = snapshot.ra_simpson
    if ra is not None and ra.a4c is not None:
        esv = _finite(ra.a4c.esv_ml)
        bsa = _finite(snapshot.indexed.bsa_m2)
        if esv is not None and bsa is not None:
            ravi = esv / bsa
            if ravi < 30.0:
                category, priority = "normal", _NORMAL
            elif ravi <= 36.0:
                category, priority = "mild", _MILD
            elif ravi <= 41.0:
                category, priority = "moderate", _MODERATE
            else:
                category, priority = "severe", _SEVERE
            findings.append(
                _finding("ra.size", f"ra_size.{category}", priority, ("ravi_a4c_es",), (SOURCE_RIGHT_HEART_2025,))
            )
    return findings


def _right_ventricle_findings(snapshot: MeasurementSnapshot) -> list[ConclusionFinding]:
    findings: list[ConclusionFinding] = []
    sources = (SOURCE_RIGHT_HEART_2025,)
    basal = _linear_mean(snapshot, "RV basal", "RVD1", "RVD basal")
    if basal is not None:
        if basal < 41.0:
            category, priority = "normal", _NORMAL
        elif basal <= 44.0:
            category, priority = "mild", _MILD
        elif basal <= 49.0:
            category, priority = "moderate", _MODERATE
        else:
            category, priority = "severe", _SEVERE
        findings.append(_finding("rv.size", f"rv_size.{category}", priority, ("rv_basal",), sources))

    tapse = _linear_mean(snapshot, "TAPSE")
    fac = _finite(snapshot.rv_fac_percent, minimum=-1.0, maximum=100.0) if snapshot.spacing_calibrated else None
    if fac is not None and fac < 0.0:
        fac = None
    tapse_category = _tapse_category(tapse) if tapse is not None else None
    fac_category = _fac_category(fac) if fac is not None else None
    if tapse_category is not None and fac_category is not None:
        if tapse_category == fac_category:
            priority = {"normal": _NORMAL, "mild": _MILD, "moderate": _MODERATE, "severe": _SEVERE}[tapse_category]
            findings.append(
                _finding("rv.function", f"rv_function.{tapse_category}", priority, ("tapse", "rv_fac"), sources)
            )
        else:
            findings.append(_finding("rv.function", "rv_function.review", _REVIEW, ("tapse", "rv_fac"), sources))
    elif tapse_category is not None:
        priority = {"normal": _NORMAL, "mild": _MILD, "moderate": _MODERATE, "severe": _SEVERE}[tapse_category]
        findings.append(_finding("rv.tapse", f"rv_tapse.{tapse_category}", priority, ("tapse",), sources))
    elif fac_category is not None:
        priority = {"normal": _NORMAL, "mild": _MILD, "moderate": _MODERATE, "severe": _SEVERE}[fac_category]
        findings.append(_finding("rv.fac", f"rv_fac.{fac_category}", priority, ("rv_fac",), sources))
    return findings


def _tapse_category(value: float) -> str:
    if value > 17.0:
        return "normal"
    if value > 13.0:
        return "mild"
    if value > 10.0:
        return "moderate"
    return "severe"


def _fac_category(value: float) -> str:
    if value > 35.0:
        return "normal"
    if value > 29.0:
        return "mild"
    if value > 22.0:
        return "moderate"
    return "severe"


def _result(snapshot: MeasurementSnapshot, calculator_id: str) -> CalculatorResult | None:
    calculations: CalculationsSnapshot | None = snapshot.calculations
    return calculations.result(calculator_id) if calculations is not None else None


def _output(result: CalculatorResult | None, output_id: str) -> float | None:
    if result is None:
        return None
    output = result.output(output_id)
    return _finite(output.value) if output is not None else None


def _input(snapshot: MeasurementSnapshot, input_id: str) -> float | None:
    calculations = snapshot.calculations
    if calculations is None:
        return None
    item = calculations.input(input_id)
    if item is None or not item.available:
        return None
    return _finite(item.value)


def _mean_gradient(snapshot: MeasurementSnapshot, site: str) -> float | None:
    flow = snapshot.doppler.flow(site) if snapshot.doppler is not None else None
    return _finite(flow.pgmean_mmhg) if flow is not None else None


def _valve_findings(snapshot: MeasurementSnapshot) -> list[ConclusionFinding]:
    findings: list[ConclusionFinding] = []
    as_finding = _as_finding(snapshot)
    if as_finding is not None:
        findings.append(as_finding)
    ar_present = _regurg_outputs(snapshot, "ar")
    mr_present = _regurg_outputs(snapshot, "mr")
    if ar_present and mr_present:
        findings.append(
            _finding(
                "regurgitation.combined",
                "regurgitation.combined_review",
                _REVIEW,
                ("ar_pisa", "mr_pisa"),
                (SOURCE_REGURGITATION_2017,),
            )
        )
    else:
        ar = _ar_finding(snapshot)
        mr = _mr_finding(snapshot)
        if ar is not None:
            findings.append(ar)
        if mr is not None:
            findings.append(mr)
    ms = _ms_finding(snapshot)
    if ms is not None:
        findings.append(ms)
    return findings


def _as_finding(snapshot: MeasurementSnapshot) -> ConclusionFinding | None:
    result = _result(snapshot, "aortic_valve_area")
    vmax = _input(snapshot, "av_vmax")
    gradient = _mean_gradient(snapshot, "AV")
    ava_vti = _output(result, "ava_vti")
    ava_vmax = _output(result, "ava_vmax")
    ava = ava_vti if ava_vti is not None else ava_vmax
    dvi = _output(result, "dvi_vti")
    if dvi is None:
        dvi = _output(result, "dvi_vmax")
    evidence = ("av_vmax", "av_mean_gradient", "ava", "dvi")
    sources = (SOURCE_AS_2017,)
    if vmax is None and gradient is None and ava is None and dvi is None:
        return None
    if result is not None and result.warnings:
        return _finding("av.stenosis", "as.review", _REVIEW, evidence, sources)
    if ava_vti is not None and ava_vmax is not None and _ava_band(ava_vti) != _ava_band(ava_vmax):
        return _finding("av.stenosis", "as.review", _REVIEW, evidence, sources)

    if (
        vmax is not None
        and gradient is not None
        and ava is not None
        and dvi is not None
        and vmax < 2.5
        and gradient < 20.0
        and ava > 1.5
        and dvi > 0.50
    ):
        return _finding("av.stenosis", "as.no_obstruction", _NORMAL, evidence, sources)

    category = _as_grade(vmax, gradient, ava, dvi)
    if category is None:
        return _finding("av.stenosis", "as.review", _REVIEW, evidence, sources)
    if category == "severe" and vmax is not None and gradient is not None and vmax >= 5.0 and gradient >= 60.0:
        return _finding("av.stenosis", "as.very_severe", _SEVERE, evidence, sources)
    priority = {"mild": _MILD, "moderate": _MODERATE, "severe": _SEVERE}[category]
    return _finding("av.stenosis", f"as.{category}", priority, evidence, sources)


def _ava_band(value: float) -> str:
    if value > 1.5:
        return "large"
    if value >= 1.0:
        return "moderate"
    return "small"


def _as_grade(vmax: float | None, gradient: float | None, ava: float | None, dvi: float | None) -> str | None:
    """Concordant AS grade; low gradient/large AVA alone never grade stenosis."""

    severe_votes = sum(
        (
            vmax is not None and vmax >= 4.0,
            gradient is not None and gradient >= 40.0,
            ava is not None and ava < 1.0,
        )
    )
    moderate_votes = sum(
        (
            vmax is not None and 3.0 <= vmax < 4.0,
            gradient is not None and 20.0 <= gradient < 40.0,
            ava is not None and 1.0 <= ava <= 1.5,
        )
    )
    if severe_votes >= 2:
        if (
            (vmax is not None and vmax < 4.0)
            or (gradient is not None and gradient < 40.0)
            or (ava is not None and ava >= 1.0)
        ):
            return None
        if dvi is not None and dvi >= 0.25:
            return None
        return "severe"
    if moderate_votes >= 2:
        if (
            (vmax is not None and not 3.0 <= vmax < 4.0)
            or (gradient is not None and not 20.0 <= gradient < 40.0)
            or (ava is not None and not 1.0 <= ava <= 1.5)
        ):
            return None
        if dvi is not None and not 0.25 <= dvi <= 0.50:
            return None
        return "moderate"
    if (
        vmax is not None
        and 2.5 <= vmax < 3.0
        and (gradient is not None or ava is not None)
        and (gradient is None or gradient < 20.0)
        and (ava is None or ava > 1.5)
        and (dvi is None or dvi > 0.50)
    ):
        return "mild"
    return None


def _regurg_outputs(snapshot: MeasurementSnapshot, valve: str) -> bool:
    result = _result(snapshot, f"pisa_{valve}")
    if result is None:
        return False
    return any(_output(result, name) is not None for name in (f"eroa_{valve}", f"rvol_{valve}", f"rf_{valve}"))


def _ar_finding(snapshot: MeasurementSnapshot) -> ConclusionFinding | None:
    result = _result(snapshot, "pisa_ar")
    eroa = _output(result, "eroa_ar")
    rvol = _output(result, "rvol_ar")
    rf = _output(result, "rf_ar")
    if eroa is None and rvol is None and rf is None:
        return None
    evidence = ("ar_eroa", "ar_rvol", "ar_rf")
    sources = (SOURCE_REGURGITATION_2017,)
    if result is not None and result.warnings:
        return _finding("av.regurgitation", "ar.review", _REVIEW, evidence, sources)
    if eroa is None or rvol is None or rf is None:
        return _finding("av.regurgitation", "ar.review", _REVIEW, evidence, sources)
    if eroa < 0.10 and rvol < 30.0 and rf < 30.0:
        return _finding("av.regurgitation", "ar.mild", _MILD, evidence, sources)
    if 0.10 <= eroa < 0.30 and 30.0 <= rvol < 60.0 and 30.0 <= rf < 50.0:
        return _finding("av.regurgitation", "ar.moderate", _MODERATE, evidence, sources)
    if eroa >= 0.30 and rvol >= 60.0 and rf >= 50.0:
        return _finding("av.regurgitation", "ar.severe", _SEVERE, evidence, sources)
    return _finding("av.regurgitation", "ar.review", _REVIEW, evidence, sources)


def _mr_finding(snapshot: MeasurementSnapshot) -> ConclusionFinding | None:
    result = _result(snapshot, "pisa_mr")
    eroa = _output(result, "eroa_mr")
    rvol = _output(result, "rvol_mr")
    rf = _output(result, "rf_mr")
    if eroa is None and rvol is None and rf is None:
        return None
    evidence = ("mr_eroa", "mr_rvol", "mr_rf")
    sources = (SOURCE_REGURGITATION_2017,)
    if result is not None and result.warnings:
        return _finding("mv.regurgitation", "mr.review", _REVIEW, evidence, sources)
    if eroa is None or rvol is None or rf is None:
        return _finding("mv.regurgitation", "mr.review", _REVIEW, evidence, sources)
    if eroa < 0.20 and rvol < 30.0 and rf < 30.0:
        return _finding("mv.regurgitation", "mr.mild", _MILD, evidence, sources)
    if eroa >= 0.40 and rvol >= 60.0 and rf >= 50.0:
        return _finding("mv.regurgitation", "mr.severe", _SEVERE, evidence, sources)
    return _finding("mv.regurgitation", "mr.review", _REVIEW, evidence, sources)


def _ms_finding(snapshot: MeasurementSnapshot) -> ConclusionFinding | None:
    result = _result(snapshot, "mitral_valve_area")
    pht = _output(result, "mva_pht")
    pisa = _output(result, "mva_pisa")
    gradient = _mean_gradient(snapshot, "MV")
    if pht is None and pisa is None and gradient is None:
        return None
    evidence = ("mva", "mv_mean_gradient")
    sources = (SOURCE_MS_2023,)
    if result is not None and result.warnings:
        return _finding("mv.stenosis", "ms.review", _REVIEW, evidence, sources)
    areas = [value for value in (pht, pisa) if value is not None]
    if not areas or gradient is None:
        return _finding("mv.stenosis", "ms.review", _REVIEW, evidence, sources)
    categories = {_ms_area_category(value) for value in areas}
    if len(categories) != 1:
        return _finding("mv.stenosis", "ms.review", _REVIEW, evidence, sources)
    category = categories.pop()
    if category != _ms_gradient_category(gradient):
        return _finding("mv.stenosis", "ms.review", _REVIEW, evidence, sources)
    priority = {"mild": _MILD, "moderate": _MODERATE, "severe": _SEVERE}[category]
    return _finding("mv.stenosis", f"ms.{category}", priority, evidence, sources)


def _ms_area_category(value: float) -> str:
    if value > 2.5:
        return "mild"
    if value > 1.5:
        return "moderate"
    return "severe"


def _ms_gradient_category(value: float) -> str:
    if value < 5.0:
        return "mild"
    if value < 10.0:
        return "moderate"
    return "severe"


def _ph_finding(snapshot: MeasurementSnapshot) -> ConclusionFinding | None:
    tr_vmax = _input(snapshot, "tr_vmax")
    if tr_vmax is None and snapshot.doppler is not None:
        flow = snapshot.doppler.flow("TR")
        if flow is not None:
            tr_vmax = _finite(flow.vmax_cm_s)
            if tr_vmax is not None:
                tr_vmax /= 100.0
        elif snapshot.doppler.tr_vmax_cm_s is not None:
            legacy = _finite(snapshot.doppler.tr_vmax_cm_s)
            tr_vmax = legacy / 100.0 if legacy is not None else None
    if tr_vmax is None:
        return None
    result = _result(snapshot, "pulmonary_pressure")
    if result is not None and result.warnings:
        return _finding("ph.probability", "ph.review", _REVIEW, ("tr_vmax",), (SOURCE_RIGHT_HEART_2025,))
    if tr_vmax > 3.4:
        return _finding("ph.probability", "ph.high", _MODERATE, ("tr_vmax",), (SOURCE_RIGHT_HEART_2025,))
    if tr_vmax >= 2.9:
        return _finding("ph.probability", "ph.intermediate", _REVIEW, ("tr_vmax",), (SOURCE_RIGHT_HEART_2025,))
    return None


def with_notice(draft: ConclusionDraft, notice_key: str) -> ConclusionDraft:
    """Return a copy with one additional notice, preserving order."""

    if notice_key in draft.notices:
        return draft
    return replace(draft, notices=draft.notices + (notice_key,))
