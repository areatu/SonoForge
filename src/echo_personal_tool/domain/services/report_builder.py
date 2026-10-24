"""Structured study report: measurements grouped by anatomical structure.

The report window and the PDF export both render :class:`ReportDocument`, so
grouping, units and the pathology flag are decided once, here, and not in two
places that could drift apart.

Norms come from the structured ASE reference data
(:class:`ReferenceDataStore`) — the same numbers the reference window shows —
with :mod:`ase_reference_norms` as a fallback for the plain linear calipers.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from echo_personal_tool.domain.calculators.models import CalculationsSnapshot
    from echo_personal_tool.domain.services.reference_data_store import ReferenceDataStore

from echo_personal_tool.domain.calculations.bernoulli import pressure_gradient_mmhg
from echo_personal_tool.domain.doppler_catalog import scale_velocity_for_display
from echo_personal_tool.domain.models.linear_measurement import PERCENT_LABELS
from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
from echo_personal_tool.domain.models.value_origin import (
    METHOD_DOPPLER_CALIPER,
    METHOD_LINEAR_CALIPER,
    METHOD_LINEAR_DERIVED,
    METHOD_PLANIMETER,
    METHOD_SIMPSON_BIPLANE,
    METHOD_SIMPSON_MONOPLANE,
    METHOD_TEICHHOLZ,
    METHOD_VESSEL,
    ClipSource,
    OriginInput,
    ValueOrigin,
    calculator_origin,
    derived_origin,
    measurement_origin,
)
from echo_personal_tool.domain.services.ase_reference_norms import (
    NormRange,
    is_outside_norm,
    linear_norm_for_label,
)
from echo_personal_tool.domain.services.doppler_repeats import report_sample_count
from echo_personal_tool.domain.services.measurement_results_formatter import _flow_results_for_display
from echo_personal_tool.domain.services.nomenclature import caliper_label as _cal
from echo_personal_tool.domain.services.nomenclature import catalog_label as _label_catalog
from echo_personal_tool.domain.services.nomenclature import flow_label as _flow
from echo_personal_tool.domain.services.nomenclature import indexed_label as _label_index
from echo_personal_tool.domain.services.nomenclature import length_decimals as _ld
from echo_personal_tool.domain.services.nomenclature import overlay_label as _label
from echo_personal_tool.domain.services.nomenclature import strain_label as _strain
from echo_personal_tool.domain.translation import tr

logger = logging.getLogger(__name__)

#: Anatomical groups in report order. The key is also the i18n suffix.
GROUP_LEFT_VENTRICLE = "lv"
GROUP_LEFT_ATRIUM = "la"
GROUP_RIGHT_VENTRICLE = "rv"
GROUP_RIGHT_ATRIUM = "ra"
GROUP_MITRAL_VALVE = "mv"
GROUP_AORTIC_VALVE = "av"
GROUP_TRICUSPID_VALVE = "tv"
GROUP_VESSELS = "vessels"
GROUP_PLANIMETRY = "planimetry"
GROUP_CALCULATIONS = "calculations"
GROUP_OTHER = "other"

GROUP_ORDER: tuple[str, ...] = (
    GROUP_LEFT_VENTRICLE,
    GROUP_LEFT_ATRIUM,
    GROUP_RIGHT_VENTRICLE,
    GROUP_RIGHT_ATRIUM,
    GROUP_MITRAL_VALVE,
    GROUP_AORTIC_VALVE,
    GROUP_TRICUSPID_VALVE,
    GROUP_VESSELS,
    GROUP_PLANIMETRY,
    GROUP_CALCULATIONS,
    GROUP_OTHER,
)

#: App measurement label → parameter id in the structured reference data.
_LABEL_TO_PARAM_ID = {
    "lvedd": "lvedd",
    "lvesd": "lvesd",
    "ivsd": "ivsd",
    "lvpwd": "lvpwd",
    "lvm": "lvm",
    "lvmi": "lvmi_hyp",
    "rwt": "rwt_hyp",
    "lvef": "lvef",
    "ef lv": "lvef",
    "фв лж": "lvef",
    "edvi": "lvedvi",
    "esvi": "lvesvi",
    "lav": "lav",
    "lavi": "lavi",
    "rav": "ra_volume",
    "s ra": "ra_area",
    "s pp": "ra_area",
    "rv basal": "rvd1",
    "rv mid": "rvd2",
    "tapse": "tapss",
    "fac": "fac_rv",
    "s' rv": "s_prime_rv",
    "gls": "gls",
    "la": "la_antpost",
    "lal": "la_antpost",
    "tr vmax": "tr_vmax",
    "ivrt": "ivrt",
    "e' sept": "e_prime_sept",
    "e' lat": "e_prime_lat",
    "e/e'": "e_e_prime_avg",
    "e/e' mean": "e_e_prime_avg",
    "e/e'mean": "e_e_prime_avg",
    # Same parameters under the catalog labels (TP-1 PR-1b, rule D-11).
    "e′ септ.": "e_prime_sept",
    "e′ septal": "e_prime_sept",
    "e′ лат.": "e_prime_lat",
    "e′ lateral": "e_prime_lat",
    "e/e′ ср.": "e_e_prime_avg",
    "mv average e/e′": "e_e_prime_avg",
    "vmax тр": "tr_vmax",
    "trmax vel": "tr_vmax",
    "кдр лж": "lvedd",
    "lvidd": "lvedd",
    "кср лж": "lvesd",
    "lvids": "lvesd",
    "мжп": "ivsd",
    "зслж": "lvpwd",
    "mv": "ms_area",
    "mv area": "ms_area",
    "pht": "ms_pht",
}

#: Reference data unit → app unit conversion for a few parameters whose stored
#: norm is expressed in another unit than the app reports.
_UNIT_SCALE = {"tr_vmax": 0.01}  # app: cm/s, reference: m/s


def reference_unit_scale(param_id: str) -> float:
    """App → reference conversion of one handbook parameter (UI-5 PR-1).

    The card of a norm reads the same table as the report instead of keeping
    its own copy: a value in cm/s must meet the m/s ranges of ``tr_vmax``.
    """
    return _UNIT_SCALE.get(param_id or "", 1.0)


@dataclass(frozen=True)
class ReportValue:
    """One measured parameter as the report shows it."""

    label: str
    value: str
    unit: str = ""
    norm: str = ""
    pathological: bool = False
    group: str = GROUP_OTHER
    #: Number of repeats that actually contributed to an averaged value (D-23).
    #: Kept separate from ``value`` so norms and machine consumers still see
    #: the unannotated numeric result.
    sample_count: int | None = None
    #: Recorded lineage for the «откуда значение» card (UI-4 PR-4).  ``None``
    #: means nothing was recorded: the card says so instead of guessing.
    origin: ValueOrigin | None = None

    @property
    def display_value(self) -> str:
        """Value plus the localized count of samples entering a repeat mean."""
        if self.sample_count is None or self.sample_count <= 1:
            return self.value
        return self.value + tr("domain.report.repeat_suffix", count=self.sample_count)


@dataclass(frozen=True)
class ReportGroup:
    title: str
    key: str
    values: tuple[ReportValue, ...]
    #: Footnotes printed under the group table (calculations: provenance of
    #: the inputs, assumptions, warnings and the RUO statement).
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class PatientInfo:
    """Editable report header; empty strings mean "not filled in"."""

    name: str = ""
    patient_id: str = ""
    birth_date: str = ""
    age: str = ""
    sex: str = ""
    study_date: str = ""
    height_cm: float | None = None
    weight_kg: float | None = None
    bsa_m2: float | None = None
    physician: str = ""
    institution: str = ""
    indication: str = ""
    conclusion: str = ""
    equipment: str = ""


@dataclass(frozen=True)
class ReportDocument:
    patient: PatientInfo = field(default_factory=PatientInfo)
    groups: tuple[ReportGroup, ...] = ()

    @property
    def has_measurements(self) -> bool:
        return any(group.values for group in self.groups)

    @property
    def pathological_values(self) -> tuple[ReportValue, ...]:
        return tuple(value for group in self.groups for value in group.values if value.pathological)


@lru_cache(maxsize=1)
def _reference_store() -> ReferenceDataStore | None:
    """Lazily loaded reference data (the YAML is parsed once per process)."""
    from echo_personal_tool.domain.services.reference_data_store import ReferenceDataStore

    try:
        return ReferenceDataStore().load()
    except Exception as exc:  # noqa: BLE001 - a broken reference file must not kill the report
        logger.warning("reference data unavailable; report norms will be partial (%s)", type(exc).__name__)
        return None


def _sex_norm(label: str, sex: str) -> NormRange | None:
    """Norm range for an app label, or None when the reference has none."""
    param_id = _LABEL_TO_PARAM_ID.get(label.casefold().strip())
    if param_id is None:
        return None
    store = _reference_store()
    if store is None:
        return None
    # lookup() only returns the location of a parameter; search() yields the
    # ParameterRef itself, which carries the sex-specific ranges.
    for _topic, _pathology, _gradation, param in store.search(param_id):
        if param.id != param_id:
            continue
        norm = param.norm_female if is_female(sex) else param.norm_male
        return norm if norm is not None else (param.norm_male or param.norm_female)
    return None


def norm_range_for(label: str, sex: str = "") -> NormRange | None:
    """Norm range for a measurement label (reference data, then ASE fallback)."""
    norm = _sex_norm(label, sex)
    if norm is not None:
        return norm
    return linear_norm_for_label(label)


def _scale_for(label: str) -> float:
    param_id = _LABEL_TO_PARAM_ID.get(label.casefold().strip())
    return _UNIT_SCALE.get(param_id or "", 1.0)


def _norm_decimals(*values: float) -> int:
    """Decimals that keep a norm readable: 0.32–0.42, 42–59, ≤280."""
    magnitude = max((abs(value) for value in values), default=0.0)
    if magnitude < 10.0:
        return 2
    if magnitude < 100.0:
        return 1
    return 0


def format_norm(norm: NormRange | None, *, scale: float = 1.0) -> str:
    """Human-readable norm in *app* units, e.g. ``42–59`` or ``≤34``.

    ``scale`` converts an app value into reference units (TR Vmax is measured in
    cm/s but the reference range is given in m/s), so the displayed bound is
    divided by it to come back to the unit the value is shown in.
    """
    if norm is None:
        return ""
    factor = 1.0 / scale if scale else 1.0
    low = norm.low * factor if norm.low is not None else None
    high = norm.high * factor if norm.high is not None else None
    decimals = _norm_decimals(*(v for v in (low, high) if v is not None))

    def _fmt(value: float) -> str:
        text = f"{value:.{decimals}f}"
        # Keep at least one decimal for small numbers (0.42 must not read "0.4").
        if decimals > 0 and abs(value) >= 10.0:
            text = text.rstrip("0").rstrip(".")
        return text or "0"

    if low is not None and high is not None:
        return f"{_fmt(low)}–{_fmt(high)}"
    if high is not None:
        return f"≤{_fmt(high)}"
    if low is not None:
        return f"≥{_fmt(low)}"
    return ""


def is_pathological(
    label: str,
    value: float | None,
    sex: str = "",
    *,
    norm_label: str | None = None,
    scale: float | None = None,
) -> tuple[bool, str]:
    """Return ``(outside_norm, norm_text)`` for a measured value.

    ``scale`` converts the passed value into reference units; it defaults
    to the label lookup (TR Vmax reads in cm/s against an m/s norm) and is
    overridden when the caller already displays reference units (TR Vmax
    in m/s under a CW mode passes ``scale=1.0``).
    """
    if value is None:
        return False, ""
    key = norm_label or label
    norm = norm_range_for(key, sex)
    if norm is None:
        return False, ""
    resolved_scale = _scale_for(key) if scale is None else scale
    return is_outside_norm(value * resolved_scale, norm), format_norm(norm, scale=resolved_scale)


def is_female(sex: str) -> bool:
    """Whether a DICOM-style sex code asks for the female reference range."""
    return sex.casefold().startswith(("f", "ж", "w"))


def is_male(sex: str) -> bool:
    """Whether a DICOM-style sex code asks for the male reference range."""
    return sex.casefold().startswith(("m", "м"))


def format_sex(sex: str) -> str:
    """Translated sex label for the report header (``M``/``F``/``Ж``…).

    DICOM also allows ``O`` (Other); it is neither sex, so it must not be
    reported as male.
    """
    text = (sex or "").strip()
    if is_female(text):
        return tr("report.sex_female")
    if is_male(text):
        return tr("report.sex_male")
    return tr("report.sex_unknown")


def group_for_label(label: str) -> str:
    """Anatomical group a measurement label belongs to.

    The order of the checks matters: ``MVd`` and ``MR`` belong to the mitral
    valve even though they contain letters that also match other rules.
    """
    text = label.casefold().strip()
    tokens = {token.strip(".,:;()") for token in text.replace("/", " ").split()}

    if tokens & {"mr", "mv", "mva", "mvd", "ms", "pht"} or "митр" in text or "mitral" in text:
        return GROUP_MITRAL_VALVE
    if tokens & {"e", "a", "e/a", "dt", "ivrt"} or text.startswith(("e'", "e/e'", "e/")):
        return GROUP_MITRAL_VALVE

    if tokens & {"tr", "tv", "ts"} or "трикусп" in text or "tricuspid" in text:
        return GROUP_TRICUSPID_VALVE
    if tokens & {"pv", "pr", "rvot", "paat"}:
        return GROUP_RIGHT_VENTRICLE
    if tokens & {"av", "ar", "ava", "annulus", "lvot", "lvotd", "vti", "vmax", "pgmax", "vmean", "pgmean"}:
        return GROUP_AORTIC_VALVE
    if text.startswith(("ao ", "ao_")) or "аорт" in text or "aort" in text:
        return GROUP_AORTIC_VALVE

    if any(keyword in text for keyword in ("psv", "edv", "ri", "s/d", "стен", "sten", "carot", "сонн", " vertebr")):
        return GROUP_VESSELS
    if text.startswith(("s1", "s2", "d1", "d2", "%s", "%d")):
        return GROUP_VESSELS

    if any(keyword in text for keyword in ("площадь", "объем", "объём", "area", "volume", "planim")):
        return GROUP_PLANIMETRY

    if any(keyword in text for keyword in ("ла ", "лп", "la ", "lav", "left atr", "левое предсерд")) or tokens & {
        "la",
        "lal",
        "lav",
        "lavi",
    }:
        return GROUP_LEFT_ATRIUM
    if tokens & {"ra", "rav"} or "пп" in tokens or "правое предсерд" in text or "right atr" in text:
        return GROUP_RIGHT_ATRIUM
    if any(
        keyword in text
        for keyword in ("rv", "rvedv", "rvesv", "tapse", "fac", "rв", "пж", "right vent", "правый желуд")
    ):
        return GROUP_RIGHT_VENTRICLE
    if any(
        keyword in text
        for keyword in (
            "lv",
            "lvedd",
            "lvidd",
            "lvesd",
            "lvids",
            "ivsd",
            "lvpwd",
            "lvm",
            "rwt",
            "gls",
            "кдо",
            "ксо",
            "кдр",
            "кср",
            "мжп",
            "зслж",
            "фв",
            "отс",
            "левый желуд",
            "left vent",
            "edvi",
            "esvi",
            "teich",
            "тейх",
            "диастол",
            "diastol",
        )
    ):
        return GROUP_LEFT_VENTRICLE
    return GROUP_OTHER


def _value(
    label: str,
    value: float | None,
    unit: str,
    *,
    sex: str = "",
    decimals: int = 1,
    group: str | None = None,
    default_group: str | None = None,
    norm_label: str | None = None,
    scale: float | None = None,
    sample_count: int | None = None,
    origin: ValueOrigin | None = None,
) -> ReportValue | None:
    """One report row; ``norm_label`` names the reference parameter to compare with.

    Row labels are translated (``ФВ ЛЖ`` / ``LVEF``), so the norm lookup cannot
    use them — the caller names the reference parameter instead.

    ``default_group`` is where the row goes when the label names no anatomy:
    a planimeter contour of a thrombus is still a planimetry measurement.

    ``scale`` overrides the app→reference unit conversion when the displayed
    value is already in reference units (CW velocities read in m/s).
    """
    if value is None:
        return None
    pathological, norm_text = is_pathological(label, value, sex, norm_label=norm_label, scale=scale)
    resolved = group or group_for_label(label)
    if resolved == GROUP_OTHER and default_group is not None:
        resolved = default_group
    return ReportValue(
        label=label,
        value=f"{value:.{decimals}f}",
        unit=unit,
        norm=norm_text,
        pathological=pathological,
        group=resolved,
        sample_count=sample_count,
        origin=origin,
    )


def _text_value(label: str, text: str, *, group: str | None = None) -> ReportValue:
    return ReportValue(label=label, value=text, group=group or group_for_label(label))


#: Labels of the calipers a Teichholz / Simpson LV volume is derived from.
_LVEDD_ALIASES = {"lvedd", "lvidd", "lv_edd", "lv_end_diastolic_diameter"}
_LVESD_ALIASES = {"lvesd", "lvids", "lv_esd", "lv_end_systolic_diameter"}


def _linear_caliper_origin(snapshot: MeasurementSnapshot, aliases: set[str], method_id: str) -> ValueOrigin | None:
    """Origin of a linear caliper whose label matches one of ``aliases``.

    The caliper carries the clip/frame it was drawn on, so a derived volume
    reports the real source instead of «происхождение не записано».
    """
    for measurement in snapshot.linear_measurements:
        if measurement.label.strip().casefold() in aliases:
            return measurement_origin(
                method_id,
                measurement_id=measurement.measurement_id,
                revision=measurement.revision,
                sop_instance_uid=measurement.sop_instance_uid,
                frame_index=measurement.frame_index,
            )
    return None


def _lineage_source(lineage: object) -> ClipSource | None:
    """The clip of a :class:`ContourLineage`, when the contour recorded one."""
    if lineage is None:
        return None
    uid = str(getattr(lineage, "sop_instance_uid", "") or "")
    if not uid:
        return None
    return ClipSource(uid, getattr(lineage, "frame_index", None))


def _caliper_pair_origin(snapshot: MeasurementSnapshot, method_id: str) -> ValueOrigin:
    """Origin of a value derived from *both* LV calipers (EF, stroke volume).

    Both clips are cited, in the order they appear in the study, and the
    identity is the diastolic caliper — the one the formula is anchored on.
    """
    sources: list[ClipSource] = []
    ids: list[str] = []
    for origin in (
        _linear_caliper_origin(snapshot, _LVEDD_ALIASES, method_id),
        _linear_caliper_origin(snapshot, _LVESD_ALIASES, method_id),
    ):
        if origin is None:
            continue
        for source in origin.sources:
            if source not in sources:
                sources.append(source)
        if origin.measurement_id and origin.measurement_id not in ids:
            ids.append(origin.measurement_id)
    return derived_origin(method_id, sources=tuple(sources), measurement_ids=tuple(ids))


def _planimeter_origin(item: object) -> ValueOrigin:
    """Origin of one planimeter result from the contour it was traced on."""
    lineage = getattr(item, "contour", None)
    if lineage is None:
        # A result stored before the lineage was kept: the method is known,
        # the clip was never recorded.
        return measurement_origin(METHOD_PLANIMETER)
    source = _lineage_source(lineage)
    return measurement_origin(
        METHOD_PLANIMETER,
        measurement_id=str(getattr(lineage, "measurement_id", "") or ""),
        revision=int(getattr(lineage, "revision", 0) or 0),
        sop_instance_uid=source.sop_instance_uid if source is not None else "",
        frame_index=source.frame_index if source is not None else None,
    )


def _simpson_origin(
    lvef: object,
    *,
    method_id: str,
    views: tuple[str, ...] | None = None,
    phase: str = "both",
) -> ValueOrigin:
    """Origin of a Simpson value from the contours it was traced from.

    ``phase`` selects the contours that took part: ``"ed"`` for the diastolic
    volume, ``"es"`` for the systolic one, ``"both"`` for EF and stroke
    volume. ``views`` narrows the citation to the views the value was actually
    computed from: a 4C volume must not cite the 2C clip, while a biplane
    volume is the sum of both. Lineage the contours did not record stays
    unrecorded — the helper never invents a clip.
    """
    sources: list[ClipSource] = []
    ids: list[str] = []
    for view, metrics in (("a4c", getattr(lvef, "a4c", None)), ("a2c", getattr(lvef, "a2c", None))):
        if metrics is None:
            continue
        if views is not None and view not in views:
            continue
        for name in ("ed_contour", "es_contour"):
            if phase == "ed" and name != "ed_contour":
                continue
            if phase == "es" and name != "es_contour":
                continue
            lineage = getattr(metrics, name, None)
            if lineage is None:
                continue
            source = _lineage_source(lineage)
            if source is not None and source not in sources:
                sources.append(source)
            identifier = str(getattr(lineage, "measurement_id", "") or "")
            if identifier and identifier not in ids:
                ids.append(identifier)
    return derived_origin(method_id, sources=tuple(sources), measurement_ids=tuple(ids))


def build_report_groups(
    snapshot: MeasurementSnapshot | None,
    *,
    sex: str = "",
    length_display_unit: str = "mm",
) -> tuple[ReportGroup, ...]:
    """Group every measurement of the study snapshot by anatomical structure."""
    if snapshot is None:
        return ()

    values: list[ReportValue] = []
    calibrated = snapshot.spacing_calibrated
    volume_unit = "mL" if calibrated else "px³"
    area_unit = "cm²" if calibrated else "px²"
    if calibrated:
        length_unit = "cm" if length_display_unit == "cm" else "mm"
        length_scale = 0.1 if length_display_unit == "cm" else 1.0
    else:
        length_unit = "px"
        length_scale = 1.0

    def scaled(value: float | None) -> float | None:
        return None if value is None else value * length_scale

    lvef = snapshot.lvef
    if lvef is not None:
        # Every value below comes from the endocardial contours of the study,
        # and those contours recorded their clip and frame. The origins are
        # read from that record — a contour whose lineage was not stored
        # leaves its value unrecorded rather than guessed from the snapshot.
        simpson_method = METHOD_SIMPSON_BIPLANE if lvef.method == "simpson_biplan" else METHOD_SIMPSON_MONOPLANE
        ed_origin = _simpson_origin(lvef, method_id=simpson_method, phase="ed")
        es_origin = _simpson_origin(lvef, method_id=simpson_method, phase="es")
        both_origin = _simpson_origin(lvef, method_id=simpson_method, phase="both")
        for view_key, view_label, metrics in (("a4c", "4C", lvef.a4c), ("a2c", "2C", lvef.a2c)):
            if metrics is None:
                continue
            length = metrics.length_ed_mm if metrics.length_ed_mm is not None else metrics.length_es_mm
            length_phase = "ed" if metrics.length_ed_mm is not None else "es"
            # The per-view values cite the contours of that view only.
            view_origin = _simpson_origin(lvef, method_id=simpson_method, views=(view_key,), phase=length_phase)
            item = _value(
                tr("domain.report.lv_length", view=view_label),
                scaled(length),
                length_unit,
                sex=sex,
                decimals=_ld(length_unit),
                group=GROUP_LEFT_VENTRICLE,
                origin=view_origin,
            )
            if item:
                values.append(item)
            ed_here = _simpson_origin(lvef, method_id=simpson_method, views=(view_key,), phase="ed")
            es_here = _simpson_origin(lvef, method_id=simpson_method, views=(view_key,), phase="es")
            for label_key, volume, origin in (
                ("domain.report.kdo_lv", metrics.edv_ml, ed_here),
                ("domain.report.kso_lv", metrics.esv_ml, es_here),
            ):
                item = _value(
                    tr(label_key, view=view_label),
                    volume,
                    volume_unit,
                    sex=sex,
                    group=GROUP_LEFT_VENTRICLE,
                    origin=origin,
                )
                if item:
                    values.append(item)
        for label_key, volume, origin in (
            ("domain.report.kdo_lv", lvef.edv_bi_ml, ed_origin),
            ("domain.report.kso_lv", lvef.esv_bi_ml, es_origin),
        ):
            item = _value(
                tr(label_key, view="BP"),
                volume,
                volume_unit,
                sex=sex,
                group=GROUP_LEFT_VENTRICLE,
                origin=origin,
            )
            if item:
                values.append(item)
        item = _value(
            tr("domain.report.lvef"),
            lvef.lvef_percent,
            "%",
            sex=sex,
            group=GROUP_LEFT_VENTRICLE,
            norm_label="LVEF",
            origin=both_origin,
        )
        if item:
            values.append(item)
        item = _value(
            tr("domain.report.sv"),
            lvef.sv_ml,
            volume_unit,
            sex=sex,
            group=GROUP_LEFT_VENTRICLE,
            norm_label="LVSV",
            # Stroke volume is EDV − ESV of the contours, not of the M-mode
            # calipers: the origin must name the Simpson contours.
            origin=both_origin,
        )
        if item:
            values.append(item)

    teichholz = snapshot.teichholz
    if teichholz is not None:
        # A Teichholz volume is a *derived* value: its inputs are the M-mode
        # calipers, and the card must say which clip and frame they came from.
        # Each volume names its own caliper — EDV comes from the end-diastolic
        # diameter, ESV from the end-systolic one; citing the first caliper of
        # the study for both would point the systolic volume at the diastolic
        # clip.
        teich_ed_origin = _linear_caliper_origin(snapshot, _LVEDD_ALIASES, METHOD_TEICHHOLZ)
        teich_es_origin = _linear_caliper_origin(snapshot, _LVESD_ALIASES, METHOD_TEICHHOLZ)
        teich_both_origin = _caliper_pair_origin(snapshot, METHOD_TEICHHOLZ)
        rows: tuple[tuple[str, float | None, str, str | None, ValueOrigin | None], ...] = (
            (_label_catalog("lv.edv_teich"), teichholz.edv_ml, "mL", None, teich_ed_origin),
            (_label_catalog("lv.esv_teich"), teichholz.esv_ml, "mL", None, teich_es_origin),
            (_label_catalog("lv.ef_teich"), teichholz.lvef_percent, "%", "LVEF", teich_both_origin),
            (tr("domain.report.sv"), teichholz.sv_ml, "mL", None, teich_both_origin),
        )
        for label, value, unit, norm_label, row_origin in rows:
            item = _value(
                label,
                value,
                unit,
                sex=sex,
                group=GROUP_LEFT_VENTRICLE,
                norm_label=norm_label,
                origin=row_origin,
            )
            if item:
                values.append(item)

    # LV mass and relative wall thickness are computed from the same M-mode
    # calipers as Teichholz (EDD/ESD, PWT, IVST), so they carry the caliper
    # origin instead of «происхождение не записано».
    linear_derived_origin = _linear_caliper_origin(snapshot, _LVEDD_ALIASES | _LVESD_ALIASES, METHOD_LINEAR_DERIVED)
    item = _value(
        _label("panel.lv_mass"),
        snapshot.lvm_g,
        "g",
        sex=sex,
        group=GROUP_LEFT_VENTRICLE,
        norm_label="LVM",
        origin=linear_derived_origin,
    )
    if item:
        values.append(item)
    item = _value(
        _label("result.rwt"),
        snapshot.rwt,
        "",
        sex=sex,
        decimals=2,
        group=GROUP_LEFT_VENTRICLE,
        norm_label="RWT",
        origin=linear_derived_origin,
    )
    if item:
        values.append(item)
    if snapshot.diastology_grade:
        values.append(_text_value(tr("domain.report.diastolic"), snapshot.diastology_grade, group=GROUP_LEFT_VENTRICLE))

    la = snapshot.la_simpson
    if la is not None:
        from echo_personal_tool.domain.calculations.chamber_simpson import (
            biplane_es_volume_ml,
            es_volume_from_view,
        )

        for label, volume in (
            (_label_catalog("la.lav_a4c"), es_volume_from_view(la.a4c)),
            (_label_catalog("la.lav_bp"), biplane_es_volume_ml(la.a4c, la.a2c)),
        ):
            item = _value(label, volume, volume_unit, sex=sex, group=GROUP_LEFT_ATRIUM, norm_label="LAV")
            if item:
                values.append(item)
        item = _value(_label_catalog("la.area"), la.area_cm2, area_unit, sex=sex, decimals=2, group=GROUP_LEFT_ATRIUM)
        if item:
            values.append(item)
    elif snapshot.la_volume is not None and snapshot.la_volume.volume_ml is not None:
        item = _value("LAV", snapshot.la_volume.volume_ml, volume_unit, sex=sex, group=GROUP_LEFT_ATRIUM)
        if item:
            values.append(item)

    ra = snapshot.ra_simpson
    if ra is not None:
        from echo_personal_tool.domain.calculations.chamber_simpson import es_volume_from_view

        item = _value(_label_catalog("ra.area"), ra.area_cm2, area_unit, sex=sex, decimals=2, group=GROUP_RIGHT_ATRIUM)
        if item:
            values.append(item)
        rav = es_volume_from_view(ra.a4c) or ra.max_volume_ml
        item = _value(_label("result.rav_4c"), rav, volume_unit, sex=sex, group=GROUP_RIGHT_ATRIUM, norm_label="RAV")
        if item:
            values.append(item)

    if snapshot.rv_fac_percent is not None:
        item = _value(
            _label("result.fac"), snapshot.rv_fac_percent, "%", sex=sex, group=GROUP_RIGHT_VENTRICLE, norm_label="FAC"
        )
        if item:
            values.append(item)
    rv = snapshot.rv_simpson
    if rv is not None and rv.max_volume_ml is not None:
        item = _value(
            tr("domain.report.rv_volume"),
            rv.max_volume_ml,
            "mL",
            sex=sex,
            group=GROUP_RIGHT_VENTRICLE,
        )
        if item:
            values.append(item)

    doppler = snapshot.doppler
    if doppler is not None:
        heart_rate = _value(
            _label("result.doppler_heart_rate"), doppler.heart_rate_bpm, tr("unit.bpm"), decimals=0, group=GROUP_OTHER
        )
        if heart_rate is not None:
            values.append(heart_rate)
        # Acquisition mode per flow-velocity row (Э2); velocities read in
        # m/s under CW and in cm/s under PW/TDI.
        flow_mode_by_label: dict[str, str] = {}
        flow_sample_count_by_label: dict[str, int] = {}
        doppler_values = [
            (_label("result.mv_e"), doppler.e_cm_s, "cm/s", GROUP_MITRAL_VALVE),
            (_label("result.mv_a"), doppler.a_cm_s, "cm/s", GROUP_MITRAL_VALVE),
            (_label("result.mv_ea_ratio"), doppler.e_a_ratio, "", GROUP_MITRAL_VALVE),
            (_label("result.mv_dt"), doppler.dt_ms, "ms", GROUP_MITRAL_VALVE),
            (_label("result.ivrt"), doppler.ivrt_ms, "ms", GROUP_MITRAL_VALVE),
            ("AT", doppler.at_ms, "ms", GROUP_AORTIC_VALVE),
            ("ET", doppler.et_ms, "ms", GROUP_AORTIC_VALVE),
            (_label("result.e_prime_sept"), doppler.e_prime_sept_cm_s, "cm/s", GROUP_MITRAL_VALVE),
            (_label("result.e_prime_lat"), doppler.e_prime_lat_cm_s, "cm/s", GROUP_MITRAL_VALVE),
            (_label("result.e_prime_avg"), doppler.e_prime_avg_cm_s, "cm/s", GROUP_MITRAL_VALVE),
            (_label("result.e_over_e_prime"), doppler.e_over_e_prime, "", GROUP_MITRAL_VALVE),
            ("E/e' sept", doppler.e_over_e_prime_sept, "", GROUP_MITRAL_VALVE),
            ("E/e' lat", doppler.e_over_e_prime_lat, "", GROUP_MITRAL_VALVE),
            ("e'/a'", doppler.e_prime_over_a_prime, "", GROUP_MITRAL_VALVE),
        ]
        flow_groups = {
            "MV": GROUP_MITRAL_VALVE,
            "MR": GROUP_MITRAL_VALVE,
            "AV": GROUP_AORTIC_VALVE,
            "LVOT": GROUP_AORTIC_VALVE,
            "AR": GROUP_AORTIC_VALVE,
            "TV": GROUP_TRICUSPID_VALVE,
            "TR": GROUP_TRICUSPID_VALVE,
            "PV": GROUP_RIGHT_VENTRICLE,
            "RVOT": GROUP_RIGHT_VENTRICLE,
            "PR": GROUP_RIGHT_VENTRICLE,
        }
        for flow in _flow_results_for_display(doppler):
            group = flow_groups.get(flow.site, GROUP_OTHER)
            doppler_values.extend(
                (
                    (_flow(flow.site, "Vmax"), flow.vmax_cm_s, "cm/s", group),
                    (_flow(flow.site, "PGmax"), flow.pgmax_mmhg, "mmHg", group),
                    (_flow(flow.site, "Vmean"), flow.vmean_cm_s, "cm/s", group),
                    (_flow(flow.site, "PGmean"), flow.pgmean_mmhg, "mmHg", group),
                    (_flow(flow.site, "VTI"), flow.vti_cm, "cm", group),
                )
            )
            flow_mode_by_label[_flow(flow.site, "Vmax")] = flow.mode
            flow_mode_by_label[_flow(flow.site, "Vmean")] = flow.mode
            vmax_repeat_count = flow.vmax_repeats or flow.vti_repeats
            flow_sample_count_by_label[_flow(flow.site, "Vmax")] = report_sample_count(vmax_repeat_count)
            flow_sample_count_by_label[_flow(flow.site, "VTI")] = report_sample_count(flow.vti_repeats)
        doppler_values.extend(
            (
                (_label_catalog("mv.pht"), doppler.mv_pht_ms, "ms", GROUP_MITRAL_VALVE),
                (_label_catalog("tv.pht"), doppler.tv_pht_ms, "ms", GROUP_TRICUSPID_VALVE),
                (_label_catalog("ar.pht"), doppler.ar_pht_ms, "ms", GROUP_AORTIC_VALVE),
                (_label_catalog("pr.pht"), doppler.pr_pht_ms, "ms", GROUP_RIGHT_VENTRICLE),
                (_label_catalog("av.at"), doppler.av_at_ms, "ms", GROUP_AORTIC_VALVE),
                (_label_catalog("av.et"), doppler.av_et_ms, "ms", GROUP_AORTIC_VALVE),
                (_label_catalog("rvot.at"), doppler.rvot_at_ms, "ms", GROUP_RIGHT_VENTRICLE),
            )
        )
        for label, doppler_val, unit, group in doppler_values:
            decimals = 2 if unit == "" else 1
            scale: float | None = None
            if label in flow_mode_by_label and doppler_val is not None:
                doppler_val, unit, decimals = scale_velocity_for_display(doppler_val, flow_mode_by_label[label])
                if unit == "m/s":
                    # Already in reference units (TR norm is stored in m/s).
                    scale = 1.0
            sample_count = flow_sample_count_by_label.get(label)
            if sample_count is not None and sample_count <= 1:
                sample_count = None
            item = _value(
                label,
                doppler_val,
                unit,
                sex=sex,
                decimals=decimals,
                group=group,
                scale=scale,
                sample_count=sample_count,
            )
            if item:
                values.append(item)

    indexed = snapshot.indexed
    provenance_notes_list: list[str] = []
    if indexed is not None:
        from echo_personal_tool.domain.services.bsa_provenance import bsa_source_label
        from echo_personal_tool.domain.services.provenance_notes import all_provenance_notes

        # Collect provenance warnings via unified helper (same wording as panel/text)
        # Filter to those that belong to indexed context + add others later
        # For PDF we collect all at once after snapshot is ready.
        provenance_notes_list = list(all_provenance_notes(snapshot))
        source_row = ReportValue(
            label=tr("domain.report.bsa_source"),
            value=bsa_source_label(indexed.bsa_basis),
            group=GROUP_OTHER,
        )
        indexed_values = (
            ("BSA", indexed.bsa_m2, "m²", 2, GROUP_OTHER, None),
            ("LVMI", indexed.lvmi_g_m2, "g/m²", 1, GROUP_LEFT_VENTRICLE, "LVMI"),
            (_label_catalog("lv.edvi"), indexed.simpson_edvi_ml_m2, "mL/m²", 1, GROUP_LEFT_VENTRICLE, "LVEDVi"),
            (_label_catalog("lv.esvi"), indexed.simpson_esvi_ml_m2, "mL/m²", 1, GROUP_LEFT_VENTRICLE, "LVESVi"),
            (
                _label_index("edvi", "4C"),
                indexed.simpson_a4c_edvi_ml_m2,
                "mL/m²",
                1,
                GROUP_LEFT_VENTRICLE,
                "LVEDVi",
            ),
            (
                _label_index("esvi", "4C"),
                indexed.simpson_a4c_esvi_ml_m2,
                "mL/m²",
                1,
                GROUP_LEFT_VENTRICLE,
                "LVESVi",
            ),
            (
                _label_index("edvi", "2C"),
                indexed.simpson_a2c_edvi_ml_m2,
                "mL/m²",
                1,
                GROUP_LEFT_VENTRICLE,
                "LVEDVi",
            ),
            (
                _label_index("esvi", "2C"),
                indexed.simpson_a2c_esvi_ml_m2,
                "mL/m²",
                1,
                GROUP_LEFT_VENTRICLE,
                "LVESVi",
            ),
            (_label_index("lavi", "4C"), indexed.lav_4c_index_ml_m2, "mL/m²", 1, GROUP_LEFT_ATRIUM, "LAVi"),
            (_label_index("lavi", "BP"), indexed.lav_bi_index_ml_m2, "mL/m²", 1, GROUP_LEFT_ATRIUM, "LAVi"),
            (
                _label_index("ravi"),
                indexed.rav_index_ml_m2,
                "mL/m²",
                1,
                GROUP_RIGHT_ATRIUM,
                "RAV",
            ),
        )
        for label, indexed_val, unit, decimals, group, norm_label in indexed_values:
            if indexed_val is None:
                continue
            item = _value(
                label,
                indexed_val,
                unit,
                sex=sex,
                decimals=decimals,
                group=group,
                norm_label=norm_label,
            )
            if item:
                values.append(item)
        # Which BSA normalised the numbers is part of the numbers (QH-1b.2).
        values.append(source_row)

    strain = snapshot.strain
    if strain is not None and strain.has_values:
        for view, value in strain.gls_by_view:
            item = _value(
                _strain(view),
                value,
                "%",
                sex=sex,
                group=GROUP_LEFT_VENTRICLE,
                norm_label="GLS",
            )
            if item:
                values.append(item)
        item = _value(
            _strain(None),
            strain.gls_average,
            "%",
            sex=sex,
            group=GROUP_LEFT_VENTRICLE,
            norm_label="GLS",
        )
        if item:
            values.append(item)

    for planimeter_item in snapshot.planimeter:
        decimals = 2 if planimeter_item.kind == "area" else 1
        entry = _value(
            planimeter_item.label,
            planimeter_item.value,
            planimeter_item.unit,
            sex=sex,
            decimals=decimals,
            default_group=GROUP_PLANIMETRY,
            # The contour that was traced is the primary source, and it
            # recorded its identity, clip and frame — pass them on.
            origin=_planimeter_origin(planimeter_item),
        )
        if entry:
            values.append(entry)

    for measurement in snapshot.linear_measurements:
        raw_label = measurement.label
        label = _cal(raw_label)
        origin = measurement_origin(
            METHOD_DOPPLER_CALIPER if measurement.doppler else METHOD_LINEAR_CALIPER,
            measurement_id=measurement.measurement_id,
            revision=measurement.revision,
            sop_instance_uid=measurement.sop_instance_uid,
            frame_index=measurement.frame_index,
        )
        if raw_label in PERCENT_LABELS:
            # Stenosis/comparison calipers keep a percentage in millimeter_length;
            # it is neither a length nor affected by the length unit or scaling.
            entry = _value(
                label,
                measurement.millimeter_length,
                "%",
                sex=sex,
                decimals=1,
                origin=origin,
            )
            if entry:
                values.append(entry)
            continue
        if measurement.doppler:
            # Doppler-zone caliper: report Δt (ms) and the velocity amplitude
            # in mode units (Э2) with its peak gradient, instead of a B-mode
            # length (which does not exist here).
            if measurement.time_ms is not None:
                entry = _value(
                    f"{label} Δt",
                    measurement.time_ms,
                    "ms",
                    sex=sex,
                    decimals=1,
                    group=GROUP_OTHER,
                    origin=origin,
                )
                if entry:
                    values.append(entry)
            if measurement.velocity_cm_s is not None:
                magnitude = abs(measurement.velocity_cm_s)
                scaled_vel, unit, decimals = scale_velocity_for_display(magnitude, measurement.doppler_mode)
                entry = _value(
                    f"{label} ΔV",
                    scaled_vel,
                    unit,
                    sex=sex,
                    decimals=decimals,
                    group=GROUP_OTHER,
                    origin=origin,
                )
                if entry:
                    values.append(entry)
                pg_entry = _value(
                    f"{label} PGmax",
                    pressure_gradient_mmhg(magnitude),
                    "mmHg",
                    sex=sex,
                    decimals=0,
                    group=GROUP_OTHER,
                    origin=origin,
                )
                if pg_entry:
                    values.append(pg_entry)
            continue
        if calibrated:
            caliper_val = measurement.millimeter_length
            unit = length_unit
            decimals = _ld(length_unit)
            if unit == "cm" and caliper_val is not None:
                caliper_val = caliper_val / 10.0
        else:
            caliper_val = measurement.pixel_length
            unit = "px"
            decimals = 0
        if caliper_val is None:
            continue
        entry = _value(label, caliper_val, unit, sex=sex, decimals=decimals, origin=origin)
        if entry:
            values.append(entry)

    for vessel in snapshot.vessel_measurements:
        vessel_values = (
            ("PSV", vessel.psv_cm_s, "cm/s"),
            ("EDV", vessel.edv_cm_s, "cm/s"),
            ("RI", vessel.ri, ""),
            ("S/D", vessel.sd, ""),
        )
        for label, vessel_val, unit in vessel_values:
            if vessel_val is None:
                continue
            values.append(
                ReportValue(
                    label=label,
                    value=f"{vessel_val:.2f}" if unit == "" else f"{vessel_val:.1f}",
                    unit=unit,
                    group=GROUP_VESSELS,
                    origin=measurement_origin(
                        METHOD_VESSEL,
                        measurement_id=vessel.measurement_id,
                        revision=vessel.revision,
                        sop_instance_uid=vessel.sop_instance_uid,
                        frame_index=vessel.frame_index,
                    ),
                )
            )

    # Ensure provenance notes are collected even if indexed is None (Simpson/Doppler/Derived)
    if not provenance_notes_list:
        from echo_personal_tool.domain.services.provenance_notes import all_provenance_notes

        provenance_notes_list = list(all_provenance_notes(snapshot))
    provenance_notes: tuple[str, ...] = tuple(provenance_notes_list)
    calculation_notes: tuple[str, ...] = ()
    calculations = snapshot.calculations
    if calculations is not None and not calculations.standalone and calculations.has_values:
        values.extend(_calculation_values(calculations))
        from echo_personal_tool.domain.calculators.text import report_notes

        calculation_notes = report_notes(calculations)

    grouped: list[ReportGroup] = []
    for key in GROUP_ORDER:
        group_values = tuple(value for value in values if value.group == key)
        if not group_values:
            continue
        notes = calculation_notes if key == GROUP_CALCULATIONS else ()
        if key == GROUP_OTHER and provenance_notes:
            notes = notes + provenance_notes
        grouped.append(ReportGroup(title=tr(f"report.group.{key}"), key=key, values=group_values, notes=notes))
    return tuple(grouped)


def _calculator_inputs(
    calculations: CalculationsSnapshot, calculator_id: str, output_id: str
) -> tuple[OriginInput, ...]:
    """Inputs one calculator output consumed, with their recorded sources.

    The calculator engine already carries per-input provenance (``measured``,
    ``dicom``, ``manual``…), so the report does not infer anything: the card
    lists exactly the inputs that entered the formula (Э11, QH-1b).
    """
    from echo_personal_tool.domain.calculators.registry import calculator_spec, input_spec

    spec = calculator_spec(calculator_id)
    if spec is None:
        return ()
    inputs: list[OriginInput] = []
    for input_id in spec.input_closure(output_id):
        value = calculations.input(input_id)
        if value is None or not value.available:
            continue
        label = input_spec(input_id)
        text = f"{value.value:g}" if value.value is not None else ""
        if label is not None and text:
            text = f"{text} {label.unit}".strip()
        inputs.append(
            OriginInput(
                id=label.label if label is not None else input_id,
                value=text,
                source=value.source,
            )
        )
    return tuple(inputs)


def _calculation_values(calculations: CalculationsSnapshot) -> list[ReportValue]:
    """Computed calculator outputs (Э11); shared outputs (LVOT area) appear once."""
    rows: list[ReportValue] = []
    seen: set[str] = set()
    for result in calculations.results:
        for output in result.outputs:
            if not output.computed or output.id in seen:
                continue
            seen.add(output.id)
            rows.append(
                ReportValue(
                    label=output.label,
                    value=output.formatted(),
                    unit=output.unit,
                    group=GROUP_CALCULATIONS,
                    origin=calculator_origin(
                        result.calculator_id,
                        inputs=_calculator_inputs(calculations, result.calculator_id, output.id),
                    ),
                )
            )
    return rows


def build_report_document(
    snapshot: MeasurementSnapshot | None,
    patient: PatientInfo | None = None,
    *,
    sex: str = "",
    length_display_unit: str = "mm",
) -> ReportDocument:
    """Assemble the full report: patient header plus grouped measurements."""
    info = patient or PatientInfo()
    if info.bsa_m2 is None and snapshot is not None and snapshot.indexed is not None:
        info = PatientInfo(**{**info.__dict__, "bsa_m2": snapshot.indexed.bsa_m2})
    return ReportDocument(
        patient=info, groups=build_report_groups(snapshot, sex=sex, length_display_unit=length_display_unit)
    )


def with_extra_values(document: ReportDocument, rows: tuple[ReportValue, ...]) -> ReportDocument:
    """Append rows that are not measurements of the snapshot (PR-5 marks).

    «не оценивалось» is a statement of the physician, not a study value, so it
    is appended to the printed document here instead of being invented inside
    the snapshot.  Existing groups keep their order and their notes; a group
    the document did not have yet is added in :data:`GROUP_ORDER` position.
    """
    if not rows:
        return document
    groups = list(document.groups)
    for row in rows:
        index = next((i for i, group in enumerate(groups) if group.key == row.group), None)
        if index is None:
            groups.append(ReportGroup(title=tr(f"report.group.{row.group}"), key=row.group, values=(row,)))
            order = {key: position for position, key in enumerate(GROUP_ORDER)}
            groups.sort(key=lambda group: order.get(group.key, len(order)))
        else:
            group = groups[index]
            groups[index] = replace(group, values=group.values + (row,))
    return ReportDocument(patient=document.patient, groups=tuple(groups))
