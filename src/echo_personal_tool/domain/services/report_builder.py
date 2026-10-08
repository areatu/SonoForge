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
from dataclasses import dataclass, field
from functools import lru_cache

from echo_personal_tool.domain.calculations.bernoulli import pressure_gradient_mmhg
from echo_personal_tool.domain.doppler_catalog import scale_velocity_for_display
from echo_personal_tool.domain.models.linear_measurement import PERCENT_LABELS
from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
from echo_personal_tool.domain.services.ase_reference_norms import (
    NormRange,
    is_outside_norm,
    linear_norm_for_label,
)
from echo_personal_tool.domain.services.doppler_repeats import report_sample_count
from echo_personal_tool.domain.services.measurement_results_formatter import _flow_results_for_display
from echo_personal_tool.infrastructure.i18n import tr

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
    "mv": "ms_area",
    "mv area": "ms_area",
    "pht": "ms_pht",
}

#: Reference data unit → app unit conversion for a few parameters whose stored
#: norm is expressed in another unit than the app reports.
_UNIT_SCALE = {"tr_vmax": 0.01}  # app: cm/s, reference: m/s


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
def _reference_store():
    """Lazily loaded reference data (the YAML is parsed once per process)."""
    from echo_personal_tool.domain.services.reference_data_store import ReferenceDataStore

    try:
        return ReferenceDataStore().load()
    except Exception:  # noqa: BLE001 - a broken reference file must not kill the report
        logger.exception("reference data unavailable; report norms will be partial")
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

    mitral_tokens = {"mr", "mv", "mva", "mvd", "ms", "pht", "e", "a", "e/a", "dt", "ivrt"}
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
            "lvesd",
            "ivsd",
            "lvpwd",
            "lvm",
            "rwt",
            "gls",
            "кдо",
            "ксо",
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
    )


def _text_value(label: str, text: str, *, group: str | None = None) -> ReportValue:
    return ReportValue(label=label, value=text, group=group or group_for_label(label))


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
        for view_label, metrics in (("4C", lvef.a4c), ("2C", lvef.a2c)):
            if metrics is None:
                continue
            length = metrics.length_ed_mm if metrics.length_ed_mm is not None else metrics.length_es_mm
            item = _value(
                tr("domain.report.lv_length", view=view_label),
                scaled(length),
                length_unit,
                sex=sex,
                group=GROUP_LEFT_VENTRICLE,
            )
            if item:
                values.append(item)
            for label_key, volume in (
                ("domain.report.kdo_lv", metrics.edv_ml),
                ("domain.report.kso_lv", metrics.esv_ml),
            ):
                item = _value(
                    tr(label_key, view=view_label),
                    volume,
                    volume_unit,
                    sex=sex,
                    group=GROUP_LEFT_VENTRICLE,
                )
                if item:
                    values.append(item)
        for label_key, volume in (
            ("domain.report.kdo_lv", lvef.edv_bi_ml),
            ("domain.report.kso_lv", lvef.esv_bi_ml),
        ):
            item = _value(
                tr(label_key, view="BP"),
                volume,
                volume_unit,
                sex=sex,
                group=GROUP_LEFT_VENTRICLE,
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
        )
        if item:
            values.append(item)

    teichholz = snapshot.teichholz
    if teichholz is not None:
        for label, value, unit, norm_label in (
            (f"{tr('domain.report.kdo')} (Teichholz)", teichholz.edv_ml, "mL", None),
            (f"{tr('domain.report.kso')} (Teichholz)", teichholz.esv_ml, "mL", None),
            (f"{tr('domain.report.fv')} (Teichholz)", teichholz.lvef_percent, "%", "LVEF"),
        ):
            item = _value(
                label,
                value,
                unit,
                sex=sex,
                group=GROUP_LEFT_VENTRICLE,
                norm_label=norm_label,
            )
            if item:
                values.append(item)

    item = _value(
        tr("domain.report.lvm"),
        snapshot.lvm_g,
        "g",
        sex=sex,
        group=GROUP_LEFT_VENTRICLE,
        norm_label="LVM",
    )
    if item:
        values.append(item)
    item = _value(
        tr("domain.report.rwt"),
        snapshot.rwt,
        "",
        sex=sex,
        decimals=2,
        group=GROUP_LEFT_VENTRICLE,
        norm_label="RWT",
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
            ("LAV 4C", es_volume_from_view(la.a4c)),
            ("LAV Bi", biplane_es_volume_ml(la.a4c, la.a2c)),
        ):
            item = _value(label, volume, volume_unit, sex=sex, group=GROUP_LEFT_ATRIUM, norm_label="LAV")
            if item:
                values.append(item)
        item = _value(tr("domain.report.s_la"), la.area_cm2, area_unit, sex=sex, decimals=2, group=GROUP_LEFT_ATRIUM)
        if item:
            values.append(item)
    elif snapshot.la_volume is not None and snapshot.la_volume.volume_ml is not None:
        item = _value("LAV", snapshot.la_volume.volume_ml, volume_unit, sex=sex, group=GROUP_LEFT_ATRIUM)
        if item:
            values.append(item)

    ra = snapshot.ra_simpson
    if ra is not None:
        from echo_personal_tool.domain.calculations.chamber_simpson import es_volume_from_view

        item = _value(tr("domain.report.s_ra"), ra.area_cm2, area_unit, sex=sex, decimals=2, group=GROUP_RIGHT_ATRIUM)
        if item:
            values.append(item)
        rav = es_volume_from_view(ra.a4c) or ra.max_volume_ml
        item = _value("RAV 4C", rav, volume_unit, sex=sex, group=GROUP_RIGHT_ATRIUM, norm_label="RAV")
        if item:
            values.append(item)

    if snapshot.rv_fac_percent is not None:
        item = _value("FAC", snapshot.rv_fac_percent, "%", sex=sex, group=GROUP_RIGHT_VENTRICLE, norm_label="FAC")
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
        # Acquisition mode per flow-velocity row (Э2); velocities read in
        # m/s under CW and in cm/s under PW/TDI.
        flow_mode_by_label: dict[str, str] = {}
        flow_sample_count_by_label: dict[str, int] = {}
        doppler_values = [
            ("E", doppler.e_cm_s, "cm/s", GROUP_MITRAL_VALVE),
            ("A", doppler.a_cm_s, "cm/s", GROUP_MITRAL_VALVE),
            ("E/A", doppler.e_a_ratio, "", GROUP_MITRAL_VALVE),
            ("DT", doppler.dt_ms, "ms", GROUP_MITRAL_VALVE),
            ("IVRT", doppler.ivrt_ms, "ms", GROUP_MITRAL_VALVE),
            ("AT", doppler.at_ms, "ms", GROUP_AORTIC_VALVE),
            ("ET", doppler.et_ms, "ms", GROUP_AORTIC_VALVE),
            ("e' sept", doppler.e_prime_sept_cm_s, "cm/s", GROUP_MITRAL_VALVE),
            ("e' lat", doppler.e_prime_lat_cm_s, "cm/s", GROUP_MITRAL_VALVE),
            ("e' mean", doppler.e_prime_avg_cm_s, "cm/s", GROUP_MITRAL_VALVE),
            ("E/e' mean", doppler.e_over_e_prime, "", GROUP_MITRAL_VALVE),
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
                    (f"{flow.site} Vmax", flow.vmax_cm_s, "cm/s", group),
                    (f"{flow.site} PGmax", flow.pgmax_mmhg, "mmHg", group),
                    (f"{flow.site} Vmean", flow.vmean_cm_s, "cm/s", group),
                    (f"{flow.site} PGmean", flow.pgmean_mmhg, "mmHg", group),
                    (f"{flow.site} VTI", flow.vti_cm, "cm", group),
                )
            )
            flow_mode_by_label[f"{flow.site} Vmax"] = flow.mode
            flow_mode_by_label[f"{flow.site} Vmean"] = flow.mode
            vmax_repeat_count = flow.vmax_repeats or flow.vti_repeats
            flow_sample_count_by_label[f"{flow.site} Vmax"] = report_sample_count(vmax_repeat_count)
            flow_sample_count_by_label[f"{flow.site} VTI"] = report_sample_count(flow.vti_repeats)
        doppler_values.extend(
            (
                ("MV PHT", doppler.mv_pht_ms, "ms", GROUP_MITRAL_VALVE),
                ("TV PHT", doppler.tv_pht_ms, "ms", GROUP_TRICUSPID_VALVE),
                ("AR PHT", doppler.ar_pht_ms, "ms", GROUP_AORTIC_VALVE),
                ("PR PHT", doppler.pr_pht_ms, "ms", GROUP_RIGHT_VENTRICLE),
                ("AV AT", doppler.av_at_ms, "ms", GROUP_AORTIC_VALVE),
                ("AV ET", doppler.av_et_ms, "ms", GROUP_AORTIC_VALVE),
                ("RVOT AT", doppler.rvot_at_ms, "ms", GROUP_RIGHT_VENTRICLE),
            )
        )
        for label, value, unit, group in doppler_values:
            decimals = 2 if unit == "" else 1
            scale: float | None = None
            if label in flow_mode_by_label and value is not None:
                value, unit, decimals = scale_velocity_for_display(value, flow_mode_by_label[label])
                if unit == "m/s":
                    # Already in reference units (TR norm is stored in m/s).
                    scale = 1.0
            sample_count = flow_sample_count_by_label.get(label)
            if sample_count is not None and sample_count <= 1:
                sample_count = None
            item = _value(
                label,
                value,
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
    if indexed is not None:
        indexed_values = (
            ("BSA", indexed.bsa_m2, "m²", 2, GROUP_OTHER, None),
            ("LVMI", indexed.lvmi_g_m2, "g/m²", 1, GROUP_LEFT_VENTRICLE, "LVMI"),
            (tr("domain.report.kdo_idx"), indexed.simpson_edvi_ml_m2, "mL/m²", 1, GROUP_LEFT_VENTRICLE, "LVEDVi"),
            (tr("domain.report.kso_idx"), indexed.simpson_esvi_ml_m2, "mL/m²", 1, GROUP_LEFT_VENTRICLE, "LVESVi"),
            ("EDVi 4C", indexed.simpson_a4c_edvi_ml_m2, "mL/m²", 1, GROUP_LEFT_VENTRICLE, "LVEDVi"),
            ("ESVi 4C", indexed.simpson_a4c_esvi_ml_m2, "mL/m²", 1, GROUP_LEFT_VENTRICLE, "LVESVi"),
            ("EDVi 2C", indexed.simpson_a2c_edvi_ml_m2, "mL/m²", 1, GROUP_LEFT_VENTRICLE, "LVEDVi"),
            ("ESVi 2C", indexed.simpson_a2c_esvi_ml_m2, "mL/m²", 1, GROUP_LEFT_VENTRICLE, "LVESVi"),
            ("LAVi 4C", indexed.lav_4c_index_ml_m2, "mL/m²", 1, GROUP_LEFT_ATRIUM, "LAVi"),
            ("LAVi Bi", indexed.lav_bi_index_ml_m2, "mL/m²", 1, GROUP_LEFT_ATRIUM, "LAVi"),
            ("RAVi", indexed.rav_index_ml_m2, "mL/m²", 1, GROUP_RIGHT_ATRIUM, "RAV"),
        )
        for label, value, unit, decimals, group, norm_label in indexed_values:
            if value is None:
                continue
            item = _value(
                label,
                value,
                unit,
                sex=sex,
                decimals=decimals,
                group=group,
                norm_label=norm_label,
            )
            if item:
                values.append(item)

    strain = snapshot.strain
    if strain is not None and strain.has_values:
        for view, value in strain.gls_by_view:
            item = _value(
                tr("domain.report.strain_gls_view", view=view),
                value,
                "%",
                sex=sex,
                group=GROUP_LEFT_VENTRICLE,
                norm_label="GLS",
            )
            if item:
                values.append(item)
        item = _value(
            tr("domain.report.strain_gls_av", n=str(len(strain.views_valid))),
            strain.gls_average,
            "%",
            sex=sex,
            group=GROUP_LEFT_VENTRICLE,
            norm_label="GLS",
        )
        if item:
            values.append(item)

    for item in snapshot.planimeter:
        decimals = 2 if item.kind == "area" else 1
        entry = _value(
            item.label,
            item.value,
            item.unit,
            sex=sex,
            decimals=decimals,
            default_group=GROUP_PLANIMETRY,
        )
        if entry:
            values.append(entry)

    for measurement in snapshot.linear_measurements:
        if measurement.label in PERCENT_LABELS:
            # Stenosis/comparison calipers keep a percentage in millimeter_length;
            # it is neither a length nor affected by the length unit or scaling.
            entry = _value(
                measurement.label,
                measurement.millimeter_length,
                "%",
                sex=sex,
                decimals=1,
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
                    f"{measurement.label} Δt",
                    measurement.time_ms,
                    "ms",
                    sex=sex,
                    decimals=1,
                    group=GROUP_OTHER,
                )
                if entry:
                    values.append(entry)
            if measurement.velocity_cm_s is not None:
                magnitude = abs(measurement.velocity_cm_s)
                scaled, unit, decimals = scale_velocity_for_display(magnitude, measurement.doppler_mode)
                entry = _value(
                    f"{measurement.label} ΔV",
                    scaled,
                    unit,
                    sex=sex,
                    decimals=decimals,
                    group=GROUP_OTHER,
                )
                if entry:
                    values.append(entry)
                pg_entry = _value(
                    f"{measurement.label} PGmax",
                    pressure_gradient_mmhg(magnitude),
                    "mmHg",
                    sex=sex,
                    decimals=0,
                    group=GROUP_OTHER,
                )
                if pg_entry:
                    values.append(pg_entry)
            continue
        if calibrated:
            value = measurement.millimeter_length
            unit = length_unit
            decimals = 1
            if unit == "cm" and value is not None:
                value = value / 10.0
        else:
            value = measurement.pixel_length
            unit = "px"
            decimals = 0
        if value is None:
            continue
        entry = _value(measurement.label, value, unit, sex=sex, decimals=decimals)
        if entry:
            values.append(entry)

    for vessel in snapshot.vessel_measurements:
        vessel_values = (
            ("PSV", vessel.psv_cm_s, "cm/s"),
            ("EDV", vessel.edv_cm_s, "cm/s"),
            ("RI", vessel.ri, ""),
            ("S/D", vessel.sd, ""),
        )
        for label, value, unit in vessel_values:
            if value is None:
                continue
            values.append(
                ReportValue(
                    label=label,
                    value=f"{value:.2f}" if unit == "" else f"{value:.1f}",
                    unit=unit,
                    group=GROUP_VESSELS,
                )
            )

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
        grouped.append(ReportGroup(title=tr(f"report.group.{key}"), key=key, values=group_values, notes=notes))
    return tuple(grouped)


def _calculation_values(calculations) -> list[ReportValue]:
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
