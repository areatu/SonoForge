"""Z-score rows of the report (plan А.12, issue #650) — the protocol projection.

A paediatric or fetal protocol does not quote adult millimetre ranges: the
key linear sizes and indexed volumes are re-read as Z-scores against the
norm tables of :mod:`pediatric_norms` (BSA for children, gestational weeks
for fetal).  The rows live in their own module because ``report_builder``
sits at its module-size limit.

Honesty rules:

* a value with no covering norm band produces no row (no extrapolation);
* a fetal protocol without a gestational age produces no rows;
* every row names the table it used — the shipped tables are *seeds* and
  the source string keeps them from passing for a verified reference.
"""

from __future__ import annotations

from echo_personal_tool.domain.measurement_catalog import measurement_for_caliper
from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
from echo_personal_tool.domain.services.pediatric_norms import PediatricNorms, cached_norms
from echo_personal_tool.domain.services.report_document import PatientInfo, ReportValue
from echo_personal_tool.domain.services.report_groups import (
    GROUP_AORTIC_VALVE,
    GROUP_FETAL,
    GROUP_LEFT_ATRIUM,
    GROUP_LEFT_VENTRICLE,
)
from echo_personal_tool.domain.translation import tr

#: The report group each Z-scored parameter prints under (mirrors where the
#: base measurement row lands on the sheet — aorta rows print in the
#: aortic-valve group).
_Z_GROUP_BY_PREFIX: dict[str, str] = {
    "lv.": GROUP_LEFT_VENTRICLE,
    "ao.": GROUP_AORTIC_VALVE,
    "la.": GROUP_LEFT_ATRIUM,
    "fetal.": GROUP_FETAL,
}

#: Percentile tags the growth chart draws (they must exist in the norms).
CHART_PERCENTILES: tuple[float, ...] = (3.0, 10.0, 25.0, 50.0, 75.0, 90.0, 97.0)

PEDIATRIC_PROFILE_SUFFIX = "pediatric_echo"
FETAL_PROFILE_SUFFIX = "fetal_echo"


def _group_for(measurement_id: str) -> str:
    for prefix, group in _Z_GROUP_BY_PREFIX.items():
        if measurement_id.startswith(prefix):
            return group
    return GROUP_LEFT_VENTRICLE


def _linear_value_for(snapshot: MeasurementSnapshot, measurement_id: str) -> float | None:
    """The last recorded millimetre value of a catalog linear parameter.

    ``measurement_for_caliper`` maps the caliper label to the catalog id —
    the same resolution the base report row uses, so a Z-score is always
    computed from exactly the value printed above it.  Several records of
    one parameter: the last recorded value wins (the freshest correction).
    """
    value: float | None = None
    for item in snapshot.linear_measurements:
        if item.millimeter_length is None or snapshot.spacing_calibrated is not True:
            continue
        if measurement_for_caliper(item.label) == measurement_id:
            value = item.millimeter_length
    return value


def _indexed_value_for(snapshot: MeasurementSnapshot, measurement_id: str) -> float | None:
    indexed = snapshot.indexed
    if indexed is None:
        return None
    if measurement_id == "lv.edvi":
        return indexed.simpson_edvi_ml_m2
    if measurement_id == "la.lavi":
        return indexed.lav_4c_index_ml_m2
    if measurement_id == "lv.mass_i":
        return indexed.lvmi_g_m2
    return None


def _bsa_of(snapshot: MeasurementSnapshot, patient: PatientInfo) -> float | None:
    if patient.bsa_m2 and patient.bsa_m2 > 0:
        return patient.bsa_m2
    indexed = snapshot.indexed
    if indexed is not None and indexed.bsa_m2 > 0:
        return indexed.bsa_m2
    return None


def zscore_report_values(
    snapshot: MeasurementSnapshot,
    patient: PatientInfo,
    norms: PediatricNorms | None = None,
    *,
    study_profile_id: str = "",
) -> tuple[ReportValue, ...]:
    """The Z-score rows of one protocol, labels already translated.

    Paediatric profile: BSA-indexed linear sizes and volumes.  Fetal
    profile: gestational-age biometry.  Anything else gets nothing — an
    adult protocol must not print Z-scores against paediatric tables.
    ``norms`` defaults to the shipped table (see :mod:`pediatric_norms`).
    """
    table = norms if norms is not None else cached_norms()
    if study_profile_id.endswith(PEDIATRIC_PROFILE_SUFFIX):
        axis_input = _bsa_of(snapshot, patient)
        ids = [mid for mid in table.measurement_ids() if not mid.startswith("fetal.")]
    elif study_profile_id.endswith(FETAL_PROFILE_SUFFIX):
        axis_input = patient.gestational_weeks
        ids = [mid for mid in table.measurement_ids() if mid.startswith("fetal.")]
    else:
        return ()
    values: list[ReportValue] = []
    for mid in ids:
        raw = _linear_value_for(snapshot, mid)
        if raw is None:
            raw = _indexed_value_for(snapshot, mid)
        if raw is None or axis_input is None:
            continue
        is_fetal = mid.startswith("fetal.")
        result = table.zscore_for(
            mid,
            raw,
            bsa_m2=None if is_fetal else axis_input,
            gestational_weeks=axis_input if is_fetal else None,
        )
        if result is None:
            continue
        text = result.display()
        if result.on_edge:
            text = tr("zscore.edge_marker") + " " + text
        values.append(
            ReportValue(
                label=f"{tr('zscore.row_prefix')} · {mid}",
                value=text,
                parameter_id=mid,
                group=_group_for(mid),
                norm=result.source,
            )
        )
    return tuple(values)
