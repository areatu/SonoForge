"""Turnkey diastology (plan А.10, issue #648).

One call assembles the whole ASE diastology panel from the study's computed
Doppler results: the auto-filled fields (E, A, E/A, DT, e′, E/e′, e′/a′, TR,
PV, IVRT, LAVi — each with its repeat count), the four simplified criteria
with their verdicts, the grade and the honest gaps.

Extraction reuse (the issue's «через Doppler-сервисы»): the numbers here are
already the D-23 repeat means computed by ``doppler_metrics`` from the
markers the Doppler services produced (peaks, intervals, envelope traces).
The workflow only counts, compares and grades — it never invents a value.

Honest limits, stated where a vendor would state them: the criteria are the
simplified ASE 2016 majority rule (≥ 3 of 4 inputs required — fewer is
``GRADE_INSUFFICIENT`` with the missing list, not a guessed grade); a phase
timeline (А.3/А.4) is deliberately *not* mixed in — the Doppler clip and the
2D cine live on different time axes, so e′/a′ and IVRT are only ever taken
from Doppler markers of their own clips.
"""

from __future__ import annotations

from echo_personal_tool.domain.calculations.chamber_simpson import confirmed_biplane_index_ml_m2
from echo_personal_tool.domain.calculations.diastology_grade import (
    ASE_INPUT_ORDER,
    DiastolicCriterion,
    diastolic_criteria,
    grade_diastolic_code,
    grade_diastolic_function,
)
from echo_personal_tool.domain.calculations.doppler_metrics import interval_repeat_count, peak_repeat_count
from echo_personal_tool.domain.models.diastology import DiastologyAssessment, DiastologyField
from echo_personal_tool.domain.models.measurements import ChamberSimpsonResult, DopplerResults, IndexedMeasurements

__all__ = ["build_diastology_assessment", "diastology_for_snapshot"]


def _repeat_n(doppler: DopplerResults, *labels: str) -> int:
    return peak_repeat_count(doppler.peaks, *labels)


def diastology_for_snapshot(
    doppler: DopplerResults | None,
    *,
    indexed: IndexedMeasurements | None,
    la_simpson: ChamberSimpsonResult | None,
    language: str = "en",
) -> tuple[DiastologyAssessment | None, str | None]:
    """The snapshot wiring: (assessment, historical grade label) in one call.

    Grade semantics are preserved from the pre-А.10 controller: the label is
    computed only when both the Doppler results and the indexed panel exist;
    the assessment exists whenever the Doppler results do, so the panel and
    the report show the honest gaps even when the grade itself is
    insufficient.
    """
    if doppler is None:
        return None, None
    lav_i = None
    grade = None
    if indexed is not None:
        lav_i = confirmed_biplane_index_ml_m2(indexed.lav_bi_index_ml_m2, la_simpson) or indexed.lav_4c_index_ml_m2
        grade = grade_diastolic_function(
            e_over_e_prime=doppler.e_over_e_prime,
            lav_index_ml_m2=lav_i,
            tr_vmax_cm_s=doppler.tr_vmax_cm_s,
            e_prime_sept_cm_s=doppler.e_prime_sept_cm_s,
            e_prime_lat_cm_s=doppler.e_prime_lat_cm_s,
            language=language,
        )
    return build_diastology_assessment(doppler, lav_index_ml_m2=lav_i), grade


def build_diastology_assessment(
    doppler: DopplerResults | None,
    *,
    lav_index_ml_m2: float | None = None,
) -> DiastologyAssessment:
    """Assemble the diastology panel + grade from one study's Doppler results.

    ``lav_index_ml_m2`` is the session's LAVi (the biplane-confirmed value the
    app controller resolves); the rest comes from the Doppler results. With
    ``doppler=None`` the assessment is empty with every ASE input missing.
    """
    if doppler is None:
        return DiastologyAssessment(
            fields=(),
            criteria=(),
            grade_code=None,
            missing_inputs=ASE_INPUT_ORDER,
        )

    tr_flow = doppler.flow("TR")
    pv_flow = doppler.flow("PV")
    fields = (
        DiastologyField("e", doppler.e_cm_s, "cm/s", _repeat_n(doppler, "e")),
        DiastologyField("a", doppler.a_cm_s, "cm/s", _repeat_n(doppler, "a")),
        DiastologyField("e_a", doppler.e_a_ratio, "", _repeat_n(doppler, "e", "a")),
        DiastologyField("dt", doppler.dt_ms, "ms", interval_repeat_count(doppler.intervals, "dt")),
        DiastologyField(
            "e_prime_sept", doppler.e_prime_sept_cm_s, "cm/s", _repeat_n(doppler, "e_prime_sept", "e_sept", "esept")
        ),
        DiastologyField(
            "e_prime_lat", doppler.e_prime_lat_cm_s, "cm/s", _repeat_n(doppler, "e_prime_lat", "e_lat", "elat")
        ),
        DiastologyField(
            "e_prime_avg",
            doppler.e_prime_avg_cm_s,
            "cm/s",
            _repeat_n(doppler, "e_prime_sept", "e_sept", "esept", "e_prime_lat", "e_lat", "elat"),
        ),
        DiastologyField("e_over_e_prime", doppler.e_over_e_prime, "", _repeat_n(doppler, "e")),
        DiastologyField("e_over_e_prime_sept", doppler.e_over_e_prime_sept, "", _repeat_n(doppler, "e")),
        DiastologyField("e_over_e_prime_lat", doppler.e_over_e_prime_lat, "", _repeat_n(doppler, "e")),
        DiastologyField(
            "e_prime_over_a_prime",
            doppler.e_prime_over_a_prime,
            "",
            _repeat_n(
                doppler,
                "e_prime_sept",
                "e_sept",
                "esept",
                "e_prime_lat",
                "e_lat",
                "elat",
                "a_prime_sept",
                "a_prime",
                "a_sept",
                "a_prime_sept",
                "a_prime_lat",
                "a_lat",
            ),
        ),
        DiastologyField("lav_index", lav_index_ml_m2, "mL/m²"),
        DiastologyField(
            "tr_vmax",
            doppler.tr_vmax_cm_s,
            "cm/s",
            tr_flow.vmax_repeats if tr_flow is not None else 0,
        ),
        DiastologyField(
            "tr_pgmax",
            tr_flow.pgmax_mmhg if tr_flow is not None else None,
            "mmHg",
            tr_flow.vmax_repeats if tr_flow is not None else 0,
        ),
        DiastologyField(
            "pv_vmax",
            pv_flow.vmax_cm_s if pv_flow is not None else None,
            "cm/s",
            pv_flow.vmax_repeats if pv_flow is not None else 0,
        ),
        DiastologyField("ivrt", doppler.ivrt_ms, "ms", interval_repeat_count(doppler.intervals, "ivrt")),
    )

    criteria = _criteria_rows(
        e_over_e_prime=doppler.e_over_e_prime,
        lav_index_ml_m2=lav_index_ml_m2,
        tr_vmax_cm_s=doppler.tr_vmax_cm_s,
        e_prime_sept_cm_s=doppler.e_prime_sept_cm_s,
        e_prime_lat_cm_s=doppler.e_prime_lat_cm_s,
    )
    grade_code = grade_diastolic_code(
        e_over_e_prime=doppler.e_over_e_prime,
        lav_index_ml_m2=lav_index_ml_m2,
        tr_vmax_cm_s=doppler.tr_vmax_cm_s,
        e_prime_sept_cm_s=doppler.e_prime_sept_cm_s,
        e_prime_lat_cm_s=doppler.e_prime_lat_cm_s,
    )
    present = {row.id for row in criteria}
    missing = tuple(item for item in ASE_INPUT_ORDER if item not in present)

    return DiastologyAssessment(
        fields=fields,
        criteria=criteria,
        grade_code=grade_code,
        missing_inputs=missing,
    )


def _criteria_rows(
    *,
    e_over_e_prime: float | None,
    lav_index_ml_m2: float | None,
    tr_vmax_cm_s: float | None,
    e_prime_sept_cm_s: float | None,
    e_prime_lat_cm_s: float | None,
) -> tuple[DiastolicCriterion, ...]:
    """The criteria rows, via the grade module's own table (one truth)."""
    return diastolic_criteria(
        e_over_e_prime=e_over_e_prime,
        lav_index_ml_m2=lav_index_ml_m2,
        tr_vmax_cm_s=tr_vmax_cm_s,
        e_prime_sept_cm_s=e_prime_sept_cm_s,
        e_prime_lat_cm_s=e_prime_lat_cm_s,
    )
