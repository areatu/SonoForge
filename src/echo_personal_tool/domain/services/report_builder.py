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
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from echo_personal_tool.domain.calculators.models import CalculationsSnapshot
    from echo_personal_tool.domain.services.reference_data_store import ReferenceDataStore

from echo_personal_tool.domain.calculations.bernoulli import pressure_gradient_mmhg
from echo_personal_tool.domain.doppler_catalog import scale_velocity_for_display
from echo_personal_tool.domain.measurement_catalog import (
    format_measurement,
    measurement_for_caliper,
)
from echo_personal_tool.domain.measurement_units import area_for_display, volume_for_display
from echo_personal_tool.domain.models.linear_measurement import PERCENT_LABELS
from echo_personal_tool.domain.models.measurements import MeasurementSnapshot, StrainReport
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
from echo_personal_tool.domain.services.nomenclature import (
    flow_measurement_id,
    strain_measurement_id,
    view_measurement_id,
)
from echo_personal_tool.domain.services.nomenclature import indexed_label as _label_index
from echo_personal_tool.domain.services.nomenclature import overlay_label as _label
from echo_personal_tool.domain.services.nomenclature import strain_label as _strain
from echo_personal_tool.domain.services.organ_volumes import (
    bladder_volume_ml,
    organ_volume_ml,
    thyroid_lobe_volume_ml,
)
from echo_personal_tool.domain.services.reference_data_store import register_cache_invalidator
from echo_personal_tool.domain.translation import tr, tr_plural

logger = logging.getLogger(__name__)

# The group ids and their printed order live in the leaf module
# ``report_groups``: the report formats need them too, and a format that
# imported them from here while the builder resolved ``profile_id`` from the
# formats would be a circle (the import-graph guard of issue 328).  The
# ``as`` re-export keeps them readable from this module, which is where every
# consumer has always taken them.
from echo_personal_tool.domain.services.report_groups import GROUP_ABDOMEN as GROUP_ABDOMEN
from echo_personal_tool.domain.services.report_groups import GROUP_AORTIC_VALVE as GROUP_AORTIC_VALVE
from echo_personal_tool.domain.services.report_groups import GROUP_CALCULATIONS as GROUP_CALCULATIONS
from echo_personal_tool.domain.services.report_groups import GROUP_KIDNEY as GROUP_KIDNEY
from echo_personal_tool.domain.services.report_groups import GROUP_LEFT_ATRIUM as GROUP_LEFT_ATRIUM
from echo_personal_tool.domain.services.report_groups import GROUP_LEFT_VENTRICLE as GROUP_LEFT_VENTRICLE
from echo_personal_tool.domain.services.report_groups import GROUP_MITRAL_VALVE as GROUP_MITRAL_VALVE
from echo_personal_tool.domain.services.report_groups import GROUP_ORDER as GROUP_ORDER
from echo_personal_tool.domain.services.report_groups import GROUP_OTHER as GROUP_OTHER
from echo_personal_tool.domain.services.report_groups import GROUP_PLANIMETRY as GROUP_PLANIMETRY
from echo_personal_tool.domain.services.report_groups import GROUP_PRECEREBRAL as GROUP_PRECEREBRAL
from echo_personal_tool.domain.services.report_groups import GROUP_RIGHT_ATRIUM as GROUP_RIGHT_ATRIUM
from echo_personal_tool.domain.services.report_groups import GROUP_RIGHT_VENTRICLE as GROUP_RIGHT_VENTRICLE
from echo_personal_tool.domain.services.report_groups import GROUP_THYROID as GROUP_THYROID
from echo_personal_tool.domain.services.report_groups import GROUP_TRICUSPID_VALVE as GROUP_TRICUSPID_VALVE
from echo_personal_tool.domain.services.report_groups import GROUP_VESSELS as GROUP_VESSELS

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
    # Organ measurements (item 2) — the same catalog labels in both display languages.
    "квр печени": "liver_size",
    "liver kvr": "liver_size",
    "толщина лд печени": "liver_left_lobe_thickness",
    "liver ll": "liver_left_lobe_thickness",
    "толщина пд печени": "liver_right_lobe_thickness",
    "liver rl": "liver_right_lobe_thickness",
    "ожп": "common_bile_duct_diameter",
    "cbd": "common_bile_duct_diameter",
    "длина жп": "gallbladder_length",
    "gb length": "gallbladder_length",
    "ширина жп": "gallbladder_width",
    "gb width": "gallbladder_width",
    "стенка жп": "gallbladder_wall_thickness",
    "gb wall": "gallbladder_wall_thickness",
    "воротная вена": "portal_vein_diameter",
    "portal vein": "portal_vein_diameter",
    "головка пж": "pancreas_head_diameter",
    "pancreas head": "pancreas_head_diameter",
    "тело пж": "pancreas_body_diameter",
    "pancreas body": "pancreas_body_diameter",
    "хвост пж": "pancreas_tail_diameter",
    "pancreas tail": "pancreas_tail_diameter",
    "проток пж": "pancreatic_duct_width",
    "pancreatic duct": "pancreatic_duct_width",
    "брюшная аорта": "aorta_diameter_ant",
    "abdominal aorta": "aorta_diameter_ant",
    "почка п длина": "kidney_length",
    "почка л длина": "kidney_length",
    "r kidney length": "kidney_length",
    "l kidney length": "kidney_length",
    "почка п ширина": "kidney_width",
    "почка л ширина": "kidney_width",
    "r kidney width": "kidney_width",
    "l kidney width": "kidney_width",
    "почка п паренхима": "kidney_cortex_thickness",
    "почка л паренхима": "kidney_cortex_thickness",
    "r kidney parenchyma": "kidney_cortex_thickness",
    "l kidney parenchyma": "kidney_cortex_thickness",
    # Third and fifth linear sizes of the kidney profile: the thickness of the
    # whole organ and the echogenic sinus — neither of them is the parenchyma.
    "почка п толщина": "kidney_thickness",
    "почка л толщина": "kidney_thickness",
    "r kidney thickness": "kidney_thickness",
    "l kidney thickness": "kidney_thickness",
    "почка п синус": "kidney_sinus",
    "почка л синус": "kidney_sinus",
    "r kidney sinus": "kidney_sinus",
    "l kidney sinus": "kidney_sinus",
    # Urinary bladder dimensions and the volume derived from them.
    "мп длина": "bladder_length",
    "bladder length": "bladder_length",
    "мп ширина": "bladder_width",
    "bladder width": "bladder_width",
    "мп глубина": "bladder_depth",
    "мп высота": "bladder_depth",  # the former name of the third dimension
    "bladder depth": "bladder_depth",
    "bladder height": "bladder_depth",
    "мп стенка": "bladder_wall_thickness",
    "bladder wall": "bladder_wall_thickness",
    "объём мп": "bladder_volume",
    "bladder volume": "bladder_volume",
    # Thyroid lobe and isthmus sizes (item 3) — the same catalog labels in both display languages.
    "щж п ширина": "thyroid_lobe_width",
    "щж л ширина": "thyroid_lobe_width",
    "r lobe width": "thyroid_lobe_width",
    "l lobe width": "thyroid_lobe_width",
    "щж п высота": "thyroid_lobe_length",
    "щж л высота": "thyroid_lobe_length",
    "r lobe height": "thyroid_lobe_length",
    "l lobe height": "thyroid_lobe_length",
    "щж п толщина": "thyroid_lobe_thickness",
    "щж л толщина": "thyroid_lobe_thickness",
    "r lobe thickness": "thyroid_lobe_thickness",
    "l lobe thickness": "thyroid_lobe_thickness",
    "перешеек": "thyroid_isthmus_thickness",
    "isthmus": "thyroid_isthmus_thickness",
    # Total thyroid volume from both lobes (Brunn coefficient, see organ_volumes).
    "объём щж": "thyroid_volume",
    "thyroid volume": "thyroid_volume",
    # Carotid intima-media thickness (item 4): one reference parameter for both sides.
    "ким оса правая": "cca_imt",
    "ким оса левая": "cca_imt",
    "r cca imt": "cca_imt",
    "l cca imt": "cca_imt",
}

#: Reference data unit → app unit conversion for a few parameters whose stored
#: norm is expressed in another unit than the app reports.
_UNIT_SCALE = {"tr_vmax": 0.01, "liver_size": 0.1}  # tr_vmax: cm/s→m/s; liver_size: mm→cm


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
    #: Stable identifier of this row inside the document (item 9 of the
    #: 2026-11-06 list): ``group:label:ordinal``.  Hiding a row is addressed by
    #: this key, not by its position, so the choice survives other rows being
    #: hidden or restored.  Empty for rows the builder does not own (the
    #: «не оценивалось» marks appended by the window).
    key: str = ""

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
    #: Printed title of the sheet (item 7 of the 2026-11-06 list).  Empty means
    #: the default «Протокол ЭхоКГ», so a document built before the report
    #: formats existed still prints exactly what it printed then.
    title: str = ""
    #: Format id the document was built for (``echo`` / ``ultrasound_generic``).
    #: Kept in the document so CSV/JSON exports and the header of the sheet name
    #: the same thing as the PDF.
    profile_id: str = ""

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


# A saved edit of the handbook must reach the report norms (the store calls this on save).
register_cache_invalidator(_reference_store.cache_clear)


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

    # Organ blocks of the non-cardiac profiles (item 2/3) come first: their
    # labels share words with the cardiac rules («Головка ПЖ», «Брюшная аорта»,
    # «Синус правой почки» vs the aortic sinuses).
    if any(keyword in text for keyword in ("мочев", "bladder")) or tokens & {"мп"}:
        return GROUP_KIDNEY
    if any(keyword in text for keyword in ("почк", "почеч", "kidney", "renal", "паренхим", "parenchyma")):
        return GROUP_KIDNEY
    if any(keyword in text for keyword in ("щитовид", "щж", "перешеек", "thyroid", "isthmus", "тирео", "lobe")):
        return GROUP_THYROID
    if any(
        keyword in text
        for keyword in (
            "ким",
            "имт",
            "imt",
            "сонн",
            "carot",
            "позвоноч",
            "vertebr",
            "подключич",
            "subclav",
            "прецеребр",
            "precerebr",
            "brachio",
        )
    ) or tokens & {"оса", "вса", "нса", "бца", "бцс", "cca", "ica", "eca", "bct"}:
        return GROUP_PRECEREBRAL
    if any(
        keyword in text
        for keyword in (
            "печени",
            "liver",
            "квр",
            "желч",
            "gallblad",
            "воротн",
            "portal",
            "проток",
            "duct",
            "поджелуд",
            "панкре",
            "pancrea",
            "брюшн",
            "abdominal",
            "головк",
            "тело",
            "хвост",
        )
    ) or tokens & {"жп", "gb", "пв", "ожп", "хвк", "cbd"}:
        return GROUP_ABDOMEN

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
    measurement_id: str,
    value: float | None,
    unit: str,
    *,
    sex: str = "",
    group: str | None = None,
    default_group: str | None = None,
    norm_label: str | None = None,
    scale: float | None = None,
    sample_count: int | None = None,
    origin: ValueOrigin | None = None,
) -> ReportValue | None:
    """One report row formatted via :func:`format_measurement` (issue 482).

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
        value=format_measurement(measurement_id, value, unit),
        unit=unit,
        norm=norm_text,
        pathological=pathological,
        group=resolved,
        sample_count=sample_count,
        origin=origin,
    )


def _text_value(label: str, text: str, *, group: str | None = None) -> ReportValue:
    return ReportValue(label=label, value=text, group=group or group_for_label(label))


_STRAIN_QC_MARKS = {"valid": "●", "review": "⚠", "invalid": "■"}


def _strain_report_notes(strain: StrainReport) -> tuple[str, ...]:
    """Report the QC and method context that makes each GLS value interpretable."""
    notes: list[str] = []
    qc_by_view = dict(strain.qc_by_view)
    for view, _value in strain.gls_by_view:
        status = qc_by_view.get(view, "")
        if not status:
            continue
        mark = _STRAIN_QC_MARKS.get(status, "")
        status_text = tr(f"strain.qc_status_{status}")
        notes.append(f"{_strain(view)}: {mark} {status_text}".strip())

    if strain.gls_average is None:
        notes.append(tr("domain.report.strain_no_average").strip())
    if strain.segmentation:
        method = tr("domain.report.strain_method", segmentation=strain.segmentation)
        notes.append(tr("domain.report.method", method=method).strip())
    avc_by_view = dict(strain.avc_source_by_view)
    avc_text = ", ".join(f"{view}: {tr(f'strain.avc_{source}')}" for view, source in avc_by_view.items() if source)
    if avc_text:
        notes.append(tr("domain.report.strain_avc_source", source=avc_text).strip())
    if strain.contour_source != "manual":
        notes.append(tr("domain.report.strain_contour_draft").strip())
    if strain.segments_missing:
        notes.append(tr_plural("domain.report.strain_segments_missing", strain.segments_missing).strip())
    return tuple(notes)


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


def _append_left_ventricle_report_values(
    values: list[ReportValue],
    snapshot: MeasurementSnapshot,
    *,
    sex: str,
    volume_unit: str,
    calibrated: bool,
    length_unit: str,
    length_scale: float,
) -> None:
    """Append Simpson, Teichholz, and linear-derived LV measurements."""

    def scaled(value: float | None) -> float | None:
        return None if value is None else value * length_scale

    def display_volume(value: float | None) -> float | None:
        return volume_for_display(value, calibrated=calibrated)

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
                f"lv.length_{view_key}",
                scaled(length),
                length_unit,
                sex=sex,
                group=GROUP_LEFT_VENTRICLE,
                origin=view_origin,
            )
            if item:
                values.append(item)
            ed_here = _simpson_origin(lvef, method_id=simpson_method, views=(view_key,), phase="ed")
            es_here = _simpson_origin(lvef, method_id=simpson_method, views=(view_key,), phase="es")
            for label_key, kind, volume, origin in (
                ("domain.report.kdo_lv", "kdo", display_volume(metrics.edv_ml), ed_here),
                ("domain.report.kso_lv", "kso", display_volume(metrics.esv_ml), es_here),
            ):
                item = _value(
                    tr(label_key, view=view_label),
                    view_measurement_id(kind, view_label),
                    volume,
                    volume_unit,
                    sex=sex,
                    group=GROUP_LEFT_VENTRICLE,
                    origin=origin,
                )
                if item:
                    values.append(item)
        for label_key, measurement_id, volume, origin in (
            ("domain.report.kdo_lv", "lv.edv_bp", display_volume(lvef.edv_bi_ml), ed_origin),
            ("domain.report.kso_lv", "lv.esv_bp", display_volume(lvef.esv_bi_ml), es_origin),
        ):
            item = _value(
                tr(label_key, view="BP"),
                measurement_id,
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
            "lv.ef_bp",
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
            "lv.sv",
            display_volume(lvef.sv_ml),
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
        teich_ed_origin = _linear_caliper_origin(snapshot, _LVEDD_ALIASES, METHOD_TEICHHOLZ)
        teich_es_origin = _linear_caliper_origin(snapshot, _LVESD_ALIASES, METHOD_TEICHHOLZ)
        teich_both_origin = _caliper_pair_origin(snapshot, METHOD_TEICHHOLZ)
        rows: tuple[tuple[str, str, float | None, str, str | None, ValueOrigin | None], ...] = (
            (_label_catalog("lv.edv_teich"), "lv.edv_teich", teichholz.edv_ml, "mL", None, teich_ed_origin),
            (_label_catalog("lv.esv_teich"), "lv.esv_teich", teichholz.esv_ml, "mL", None, teich_es_origin),
            (_label_catalog("lv.ef_teich"), "lv.ef_teich", teichholz.lvef_percent, "%", "LVEF", teich_both_origin),
            (tr("domain.report.sv"), "lv.sv", teichholz.sv_ml, "mL", None, teich_both_origin),
        )
        for label, measurement_id, value, unit, norm_label, row_origin in rows:
            item = _value(
                label,
                measurement_id,
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
        "lv.mass",
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
        "lv.rwt",
        snapshot.rwt,
        "",
        sex=sex,
        group=GROUP_LEFT_VENTRICLE,
        norm_label="RWT",
        origin=linear_derived_origin,
    )
    if item:
        values.append(item)
    if snapshot.diastology_grade:
        values.append(_text_value(tr("domain.report.diastolic"), snapshot.diastology_grade, group=GROUP_LEFT_VENTRICLE))


def _append_chamber_report_values(
    values: list[ReportValue],
    snapshot: MeasurementSnapshot,
    *,
    sex: str,
    volume_unit: str,
    area_unit: str,
    calibrated: bool,
) -> None:
    """Append atrial and right-ventricular measurements."""
    la = snapshot.la_simpson

    def display_volume(value: float | None) -> float | None:
        return volume_for_display(value, calibrated=calibrated)

    def display_area(value: float | None) -> float | None:
        return area_for_display(value, calibrated=calibrated)

    if la is not None:
        from echo_personal_tool.domain.calculations.chamber_simpson import (
            confirmed_biplane_es_volume_ml,
            es_volume_from_view,
        )

        volumes = [("la.lav_a4c", es_volume_from_view(la.a4c))]
        # No true biplane method yet: the averaged monoplane value is not
        # promoted to the «LAV (biplane)» row (F08 / issue 548).
        biplane_volume = confirmed_biplane_es_volume_ml(la)
        if biplane_volume is not None:
            volumes.append(("la.lav_bp", biplane_volume))
        for measurement_id, volume in volumes:
            item = _value(
                _label_catalog(measurement_id),
                measurement_id,
                display_volume(volume),
                volume_unit,
                sex=sex,
                group=GROUP_LEFT_ATRIUM,
                norm_label="LAV",
            )
            if item:
                values.append(item)
        item = _value(
            _label_catalog("la.area"), "la.area", display_area(la.area_cm2), area_unit, sex=sex, group=GROUP_LEFT_ATRIUM
        )
        if item:
            values.append(item)
    elif snapshot.la_volume is not None and snapshot.la_volume.volume_ml is not None:
        item = _value("LAV", "la.lav_al", snapshot.la_volume.volume_ml, "mL", sex=sex, group=GROUP_LEFT_ATRIUM)
        if item:
            values.append(item)

    ra = snapshot.ra_simpson
    if ra is not None:
        from echo_personal_tool.domain.calculations.chamber_simpson import es_volume_from_view

        item = _value(
            _label_catalog("ra.area"),
            "ra.area",
            display_area(ra.area_cm2),
            area_unit,
            sex=sex,
            group=GROUP_RIGHT_ATRIUM,
        )
        if item:
            values.append(item)
        rav = es_volume_from_view(ra.a4c) or ra.max_volume_ml
        item = _value(
            _label("result.rav_4c"),
            "ra.vol",
            display_volume(rav),
            volume_unit,
            sex=sex,
            group=GROUP_RIGHT_ATRIUM,
            norm_label="RAV",
        )
        if item:
            values.append(item)

    if snapshot.rv_fac_percent is not None:
        item = _value(
            _label("result.fac"),
            "rv.fac",
            snapshot.rv_fac_percent,
            "%",
            sex=sex,
            group=GROUP_RIGHT_VENTRICLE,
            norm_label="FAC",
        )
        if item:
            values.append(item)
    rv = snapshot.rv_simpson
    if rv is not None and rv.max_volume_ml is not None:
        item = _value(
            tr("domain.report.rv_volume"),
            "rv.edv_a4c",
            rv.max_volume_ml,
            "mL",
            sex=sex,
            group=GROUP_RIGHT_VENTRICLE,
        )
        if item:
            values.append(item)


def _append_doppler_report_values(values: list[ReportValue], snapshot: MeasurementSnapshot, *, sex: str) -> None:
    """Append Doppler measurements with mode-specific units and sample counts."""
    doppler = snapshot.doppler
    if doppler is not None:
        heart_rate = _value(
            _label("result.doppler_heart_rate"),
            "hr",
            doppler.heart_rate_bpm,
            tr("unit.bpm"),
            group=GROUP_OTHER,
        )
        if heart_rate is not None:
            values.append(heart_rate)
        flow_mode_by_label: dict[str, str] = {}
        flow_sample_count_by_label: dict[str, int] = {}
        doppler_values: list[tuple[str, str, float | None, str, str]] = [
            (_label("result.mv_e"), "mv.e", doppler.e_cm_s, "cm/s", GROUP_MITRAL_VALVE),
            (_label("result.mv_a"), "mv.a", doppler.a_cm_s, "cm/s", GROUP_MITRAL_VALVE),
            (_label("result.mv_ea_ratio"), "mv.ea", doppler.e_a_ratio, "", GROUP_MITRAL_VALVE),
            (_label("result.mv_dt"), "mv.dt", doppler.dt_ms, "ms", GROUP_MITRAL_VALVE),
            (_label("result.ivrt"), "lv.ivrt", doppler.ivrt_ms, "ms", GROUP_MITRAL_VALVE),
            ("AT", "mv.at", doppler.at_ms, "ms", GROUP_AORTIC_VALVE),
            ("ET", "doppler.et", doppler.et_ms, "ms", GROUP_AORTIC_VALVE),
            (_label("result.e_prime_sept"), "tdi.e_sept", doppler.e_prime_sept_cm_s, "cm/s", GROUP_MITRAL_VALVE),
            (_label("result.e_prime_lat"), "tdi.e_lat", doppler.e_prime_lat_cm_s, "cm/s", GROUP_MITRAL_VALVE),
            (_label("result.e_prime_avg"), "tdi.e_avg", doppler.e_prime_avg_cm_s, "cm/s", GROUP_MITRAL_VALVE),
            (_label("result.e_over_e_prime"), "mv.e_e_avg", doppler.e_over_e_prime, "", GROUP_MITRAL_VALVE),
            ("E/e' sept", "tdi.e_e_sept", doppler.e_over_e_prime_sept, "", GROUP_MITRAL_VALVE),
            ("E/e' lat", "tdi.e_e_lat", doppler.e_over_e_prime_lat, "", GROUP_MITRAL_VALVE),
            ("e'/a'", "tdi.e_a_prime", doppler.e_prime_over_a_prime, "", GROUP_MITRAL_VALVE),
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
                    (_flow(flow.site, "Vmax"), flow_measurement_id(flow.site, "Vmax"), flow.vmax_cm_s, "cm/s", group),
                    (
                        _flow(flow.site, "PGmax"),
                        flow_measurement_id(flow.site, "PGmax"),
                        flow.pgmax_mmhg,
                        "mmHg",
                        group,
                    ),
                    (
                        _flow(flow.site, "Vmean"),
                        flow_measurement_id(flow.site, "Vmean"),
                        flow.vmean_cm_s,
                        "cm/s",
                        group,
                    ),
                    (
                        _flow(flow.site, "PGmean"),
                        flow_measurement_id(flow.site, "PGmean"),
                        flow.pgmean_mmhg,
                        "mmHg",
                        group,
                    ),
                    (_flow(flow.site, "VTI"), flow_measurement_id(flow.site, "VTI"), flow.vti_cm, "cm", group),
                )
            )
            flow_mode_by_label[_flow(flow.site, "Vmax")] = flow.mode
            flow_mode_by_label[_flow(flow.site, "Vmean")] = flow.mode
            vmax_repeat_count = flow.vmax_repeats or flow.vti_repeats
            flow_sample_count_by_label[_flow(flow.site, "Vmax")] = report_sample_count(vmax_repeat_count)
            flow_sample_count_by_label[_flow(flow.site, "VTI")] = report_sample_count(flow.vti_repeats)
        doppler_values.extend(
            (
                (_label_catalog("mv.pht"), "mv.pht", doppler.mv_pht_ms, "ms", GROUP_MITRAL_VALVE),
                (_label_catalog("tv.pht"), "tv.pht", doppler.tv_pht_ms, "ms", GROUP_TRICUSPID_VALVE),
                (_label_catalog("ar.pht"), "ar.pht", doppler.ar_pht_ms, "ms", GROUP_AORTIC_VALVE),
                (_label_catalog("pr.pht"), "pr.pht", doppler.pr_pht_ms, "ms", GROUP_RIGHT_VENTRICLE),
                (_label_catalog("av.at"), "av.at", doppler.av_at_ms, "ms", GROUP_AORTIC_VALVE),
                (_label_catalog("av.et"), "av.et", doppler.av_et_ms, "ms", GROUP_AORTIC_VALVE),
                (_label_catalog("rvot.at"), "rvot.at", doppler.rvot_at_ms, "ms", GROUP_RIGHT_VENTRICLE),
            )
        )
        for label, measurement_id, doppler_val, unit, group in doppler_values:
            scale: float | None = None
            if label in flow_mode_by_label and doppler_val is not None:
                doppler_val, unit, _ = scale_velocity_for_display(
                    doppler_val,
                    flow_mode_by_label[label],
                    measurement_id=measurement_id,
                )
                if unit == "m/s":
                    scale = 1.0
            sample_count = flow_sample_count_by_label.get(label)
            if sample_count is not None and sample_count <= 1:
                sample_count = None
            item = _value(
                label,
                measurement_id,
                doppler_val,
                unit,
                sex=sex,
                group=group,
                scale=scale,
                sample_count=sample_count,
            )
            if item:
                values.append(item)


def _append_indexed_report_values(values: list[ReportValue], snapshot: MeasurementSnapshot, *, sex: str) -> list[str]:
    """Append indexed values and return their provenance notes."""
    indexed = snapshot.indexed
    provenance_notes_list: list[str] = []
    if indexed is not None:
        from echo_personal_tool.domain.calculations.chamber_simpson import confirmed_biplane_es_volume_ml
        from echo_personal_tool.domain.services.bsa_provenance import bsa_source_label
        from echo_personal_tool.domain.services.provenance_notes import all_provenance_notes

        provenance_notes_list = list(all_provenance_notes(snapshot))
        lav_bi_index = (
            indexed.lav_bi_index_ml_m2 if confirmed_biplane_es_volume_ml(snapshot.la_simpson) is not None else None
        )
        source_row = ReportValue(
            label=tr("domain.report.bsa_source"),
            value=bsa_source_label(indexed.bsa_basis),
            group=GROUP_OTHER,
        )
        indexed_values = (
            ("BSA", "patient.bsa", indexed.bsa_m2, "m²", GROUP_OTHER, None),
            ("LVMI", "lv.mass_i", indexed.lvmi_g_m2, "g/m²", GROUP_LEFT_VENTRICLE, "LVMI"),
            (_label_catalog("lv.edvi"), "lv.edvi", indexed.simpson_edvi_ml_m2, "mL/m²", GROUP_LEFT_VENTRICLE, "LVEDVi"),
            (_label_catalog("lv.esvi"), "lv.esvi", indexed.simpson_esvi_ml_m2, "mL/m²", GROUP_LEFT_VENTRICLE, "LVESVi"),
            (
                _label_index("edvi", "4C"),
                "lv.edvi_a4c",
                indexed.simpson_a4c_edvi_ml_m2,
                "mL/m²",
                GROUP_LEFT_VENTRICLE,
                "LVEDVi",
            ),
            (
                _label_index("esvi", "4C"),
                "lv.esvi_a4c",
                indexed.simpson_a4c_esvi_ml_m2,
                "mL/m²",
                GROUP_LEFT_VENTRICLE,
                "LVESVi",
            ),
            (
                _label_index("edvi", "2C"),
                "lv.edvi_a2c",
                indexed.simpson_a2c_edvi_ml_m2,
                "mL/m²",
                GROUP_LEFT_VENTRICLE,
                "LVEDVi",
            ),
            (
                _label_index("esvi", "2C"),
                "lv.esvi_a2c",
                indexed.simpson_a2c_esvi_ml_m2,
                "mL/m²",
                GROUP_LEFT_VENTRICLE,
                "LVESVi",
            ),
            (_label_index("lavi", "4C"), "la.lavi_a4c", indexed.lav_4c_index_ml_m2, "mL/m²", GROUP_LEFT_ATRIUM, "LAVi"),
            (_label_index("lavi", "BP"), "la.lavi_bp", lav_bi_index, "mL/m²", GROUP_LEFT_ATRIUM, "LAVi"),
            (_label_index("ravi"), "ra.ravi", indexed.rav_index_ml_m2, "mL/m²", GROUP_RIGHT_ATRIUM, "RAV"),
        )
        for label, measurement_id, indexed_val, unit, group, norm_label in indexed_values:
            if indexed_val is None:
                continue
            item = _value(
                label,
                measurement_id,
                indexed_val,
                unit,
                sex=sex,
                group=group,
                norm_label=norm_label,
            )
            if item:
                values.append(item)
        values.append(source_row)
    return provenance_notes_list


def _append_strain_report_values(values: list[ReportValue], snapshot: MeasurementSnapshot, *, sex: str) -> None:
    """Append GLS report values."""
    strain = snapshot.strain
    if strain is not None and strain.has_values:
        for view, value in strain.gls_by_view:
            item = _value(
                _strain(view),
                strain_measurement_id(view),
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
            "lv.gls",
            strain.gls_average,
            "%",
            sex=sex,
            group=GROUP_LEFT_VENTRICLE,
            norm_label="GLS",
        )
        if item:
            values.append(item)


def _append_planimeter_report_values(values: list[ReportValue], snapshot: MeasurementSnapshot, *, sex: str) -> None:
    """Append traced planimetry values with their measurement lineage."""
    for planimeter_item in snapshot.planimeter:
        measurement_id = {
            "area": "planimeter.area",
            "volume": "planimeter.volume",
        }.get(planimeter_item.kind, "planimeter.length")
        entry = _value(
            planimeter_item.label,
            measurement_id,
            planimeter_item.value,
            planimeter_item.unit,
            sex=sex,
            default_group=GROUP_PLANIMETRY,
            origin=_planimeter_origin(planimeter_item),
        )
        if entry:
            values.append(entry)


def _append_linear_report_values(
    values: list[ReportValue],
    snapshot: MeasurementSnapshot,
    *,
    sex: str,
    calibrated: bool,
    length_unit: str,
) -> None:
    """Append linear calipers in calibrated or pixel units."""
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
            entry = _value(
                label,
                "caliper.stenosis_pct",
                measurement.millimeter_length,
                "%",
                sex=sex,
                origin=origin,
            )
            if entry:
                values.append(entry)
            continue
        if raw_label in ("S1", "S2") and measurement.millimeter_length is not None:
            entry = _value(
                label,
                "caliper.area",
                measurement.millimeter_length,
                "cm²",
                sex=sex,
                origin=origin,
            )
            if entry:
                values.append(entry)
            continue
        if measurement.doppler:
            if measurement.time_ms is not None:
                entry = _value(
                    f"{label} Δt",
                    "doppler.time",
                    measurement.time_ms,
                    "ms",
                    sex=sex,
                    group=GROUP_OTHER,
                    origin=origin,
                )
                if entry:
                    values.append(entry)
            if measurement.velocity_cm_s is not None:
                magnitude = abs(measurement.velocity_cm_s)
                scaled_vel, unit, _ = scale_velocity_for_display(
                    magnitude,
                    measurement.doppler_mode,
                    measurement_id="doppler.vmax",
                )
                entry = _value(
                    f"{label} ΔV",
                    "doppler.vmax",
                    scaled_vel,
                    unit,
                    sex=sex,
                    group=GROUP_OTHER,
                    origin=origin,
                )
                if entry:
                    values.append(entry)
                pg_entry = _value(
                    f"{label} PGmax",
                    "doppler.pg_peak",
                    pressure_gradient_mmhg(magnitude),
                    "mmHg",
                    sex=sex,
                    group=GROUP_OTHER,
                    origin=origin,
                )
                if pg_entry:
                    values.append(pg_entry)
            continue
        if calibrated:
            caliper_val = measurement.millimeter_length
            unit = length_unit
            caliper_id = (
                "caliper.length_submm"
                if measurement.submillimeter
                else (measurement_for_caliper(raw_label) or "caliper.length")
            )
            if unit == "cm" and caliper_val is not None:
                caliper_val = caliper_val / 10.0
        else:
            caliper_val = measurement.pixel_length
            unit = "px"
            caliper_id = measurement_for_caliper(raw_label) or "caliper.length"
        if caliper_val is None:
            continue
        entry = _value(label, caliper_id, caliper_val, unit, sex=sex, origin=origin)
        if entry:
            values.append(entry)


def _volume_origin(measurements: Iterable[object]) -> ValueOrigin:
    """Origin of a volume derived from the three calipers it was computed from."""
    sources: list[ClipSource] = []
    ids: list[str] = []
    for measurement in measurements:
        uid = str(getattr(measurement, "sop_instance_uid", "") or "")
        if uid:
            source = ClipSource(uid, getattr(measurement, "frame_index", None))
            if source not in sources:
                sources.append(source)
        identifier = str(getattr(measurement, "measurement_id", "") or "")
        if identifier and identifier not in ids:
            ids.append(identifier)
    return derived_origin(METHOD_LINEAR_DERIVED, sources=tuple(sources), measurement_ids=tuple(ids))


def _volume_row(
    values: list[ReportValue],
    measurement_id: str,
    volume_ml: float | None,
    *,
    group: str,
    measurements: Iterable[object],
) -> None:
    """Append one derived volume row in millilitres (item 11)."""
    if volume_ml is None:
        return
    entry = _value(
        _label_catalog(measurement_id),
        measurement_id,
        volume_ml,
        "mL",
        group=group,
        origin=_volume_origin(measurements),
    )
    if entry:
        values.append(entry)


def _append_derived_volume_report_values(values: list[ReportValue], snapshot: MeasurementSnapshot) -> None:
    """Organ volumes from three dimensions (item 11 of the 2026-11-06 list).

    Two kinds of rows:

    * automatic ones — the bladder (length × width × depth, ellipsoid) and each
      thyroid lobe (Brunn), plus the total thyroid volume when both lobes are
      complete.  A physician who measured the three sizes should not have to
      ask for the arithmetic;
    * the generic «объём по трём измерениям» triplets of the general tool, each
      three consecutive ``ORGAN-VOL-1/2/3`` calipers, with the ellipsoid
      coefficient.

    Only calibrated calipers can produce a volume: pixel lengths are not
    millimetres and a guessed scale must not become a printed millilitre.
    """
    by_label: dict[str, object] = {}
    for measurement in snapshot.linear_measurements:
        if measurement.millimeter_length is None:
            continue
        by_label.setdefault(measurement.label, measurement)

    def length(label: str) -> float | None:
        measurement = by_label.get(label)
        if measurement is None:
            return None
        value = getattr(measurement, "millimeter_length", None)
        return float(value) if value is not None else None

    def row_for(
        measurement_id: str,
        volume: float | None,
        group: str,
        *labels: str,
    ) -> None:
        parts = tuple(by_label[label] for label in labels if label in by_label)
        _volume_row(values, measurement_id, volume, group=group, measurements=parts)

    bladder_length = length("BL-L")
    bladder_width = length("BL-W")
    # «Высота» is the old name of the third bladder dimension; documents that
    # measured it still get their volume instead of a silent gap.
    bladder_depth = length("BL-D") if "BL-D" in by_label else length("BL-H")
    if bladder_length is not None and bladder_width is not None and bladder_depth is not None:
        depth_label = "BL-D" if "BL-D" in by_label else "BL-H"
        row_for(
            "bladder.volume",
            bladder_volume_ml(bladder_length, bladder_width, bladder_depth),
            GROUP_KIDNEY,
            "BL-L",
            "BL-W",
            depth_label,
        )

    lobe_volumes: list[float] = []
    for side, labels in (
        ("r", ("TH-R-H", "TH-R-W", "TH-R-TH")),
        ("l", ("TH-L-H", "TH-L-W", "TH-L-TH")),
    ):
        height, width, thickness = (length(label) for label in labels)
        if height is None or width is None or thickness is None:
            continue
        volume = thyroid_lobe_volume_ml(height, width, thickness)
        _volume_row(
            values,
            f"thyroid.{side}_volume",
            volume,
            group=GROUP_THYROID,
            measurements=tuple(by_label[label] for label in labels),
        )
        if volume is not None:
            lobe_volumes.append(volume)
    if len(lobe_volumes) == 2:
        _volume_row(
            values,
            "thyroid.volume",
            sum(lobe_volumes),
            group=GROUP_THYROID,
            measurements=tuple(
                by_label[label] for label in ("TH-R-H", "TH-R-W", "TH-R-TH", "TH-L-H", "TH-L-W", "TH-L-TH")
            ),
        )

    triplet: list[object] = []
    for measurement in snapshot.linear_measurements:
        if measurement.label == "ORGAN-VOL-1":
            triplet = [measurement]
            continue
        if measurement.label == "ORGAN-VOL-2" and len(triplet) == 1:
            triplet.append(measurement)
            continue
        if measurement.label == "ORGAN-VOL-3" and len(triplet) == 2:
            triplet.append(measurement)
            sides = [float(getattr(item, "millimeter_length", 0.0) or 0.0) for item in triplet]
            if all(side > 0.0 for side in sides):
                _volume_row(
                    values,
                    "organ.volume",
                    organ_volume_ml(sides[0], sides[1], sides[2]),
                    group=GROUP_PLANIMETRY,
                    measurements=tuple(triplet),
                )
            triplet = []
            continue
        if measurement.label.startswith("ORGAN-VOL-"):
            triplet = []


def _append_vessel_report_values(values: list[ReportValue], snapshot: MeasurementSnapshot) -> None:
    """Append vessel Doppler measurements with recorded source lineage.

    A named site («ОСА правая», «R renal artery»…) prefixes every row so the
    arteries measured on one frame stay distinguishable (item 2/4); the rows of
    the unnamed legacy tool keep the generic PSV/EDV labels and the vessels
    group.  The site travels in the raw internal label and is localized here.
    """
    for vessel in snapshot.vessel_measurements:
        site = _cal(vessel.label) if vessel.label else ""
        vessel_values = (
            ("PSV", "vessel.psv", vessel.psv_cm_s, "cm/s"),
            ("EDV", "vessel.edv", vessel.edv_cm_s, "cm/s"),
            ("RI", "vessel.ri", vessel.ri, ""),
            ("S/D", "vessel.sd", vessel.sd, ""),
        )
        for label, measurement_id, vessel_val, unit in vessel_values:
            if vessel_val is None:
                continue
            row_label = f"{site} {label}" if site else label
            values.append(
                ReportValue(
                    label=row_label,
                    value=format_measurement(measurement_id, vessel_val, unit),
                    unit=unit,
                    group=group_for_label(row_label) if site else GROUP_VESSELS,
                    origin=measurement_origin(
                        METHOD_VESSEL,
                        measurement_id=vessel.measurement_id,
                        revision=vessel.revision,
                        sop_instance_uid=vessel.sop_instance_uid,
                        frame_index=vessel.frame_index,
                    ),
                )
            )


def build_report_groups(
    snapshot: MeasurementSnapshot | None,
    *,
    sex: str = "",
    length_display_unit: str = "mm",
    include_inputs: bool = True,
) -> tuple[ReportGroup, ...]:
    """Group every measurement of the study snapshot by anatomical structure.

    ``include_inputs`` gates every machine-generated footnote under the
    parameter tables: the calculations notes, the provenance notes of the
    «Прочие» group and the strain-method notes under the LV group.  With it
    off, the routine report prints the tables and nothing else — values are
    unchanged either way.
    """
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

    _append_left_ventricle_report_values(
        values,
        snapshot,
        sex=sex,
        volume_unit=volume_unit,
        calibrated=calibrated,
        length_unit=length_unit,
        length_scale=length_scale,
    )
    _append_chamber_report_values(
        values, snapshot, sex=sex, volume_unit=volume_unit, area_unit=area_unit, calibrated=calibrated
    )
    _append_doppler_report_values(values, snapshot, sex=sex)
    provenance_notes_list = _append_indexed_report_values(values, snapshot, sex=sex)
    _append_strain_report_values(values, snapshot, sex=sex)
    _append_planimeter_report_values(values, snapshot, sex=sex)
    _append_linear_report_values(values, snapshot, sex=sex, calibrated=calibrated, length_unit=length_unit)
    _append_derived_volume_report_values(values, snapshot)
    _append_vessel_report_values(values, snapshot)

    # Ensure provenance notes are collected even if indexed is None (Simpson/Doppler/Derived)
    if not provenance_notes_list:
        from echo_personal_tool.domain.services.provenance_notes import all_provenance_notes

        provenance_notes_list = list(all_provenance_notes(snapshot))
    provenance_notes: tuple[str, ...] = tuple(provenance_notes_list) if include_inputs else ()
    strain_notes = (
        _strain_report_notes(snapshot.strain)
        if include_inputs and snapshot.strain is not None and snapshot.strain.has_values
        else ()
    )
    calculation_notes: tuple[str, ...] = ()
    calculations = snapshot.calculations
    if calculations is not None and not calculations.standalone and calculations.has_values:
        values.extend(_calculation_values(calculations))
        from echo_personal_tool.domain.calculators.text import report_notes

        calculation_notes = report_notes(calculations, include_inputs=include_inputs)

    grouped: list[ReportGroup] = []
    for key in GROUP_ORDER:
        group_values = tuple(value for value in values if value.group == key)
        if not group_values:
            continue
        notes = calculation_notes if key == GROUP_CALCULATIONS else ()
        if key == GROUP_LEFT_VENTRICLE and strain_notes:
            notes = notes + strain_notes
        if key == GROUP_OTHER and provenance_notes:
            notes = notes + provenance_notes
        grouped.append(
            ReportGroup(
                title=tr(f"report.group.{key}"),
                key=key,
                values=_keyed_values(key, group_values),
                notes=notes,
            )
        )
    return tuple(grouped)


def _keyed_values(group_key: str, values: tuple[ReportValue, ...]) -> tuple[ReportValue, ...]:
    """Give every row its stable ``group:label:ordinal`` key (item 9).

    The ordinal counts same-labelled rows inside the group — two planimeter
    contours of one frame stay apart — and it is computed over the *whole*
    group, before any hiding, so restoring a row never renumbers the others.
    """
    counters: dict[str, int] = {}
    keyed: list[ReportValue] = []
    for value in values:
        ordinal = counters.get(value.label, 0)
        counters[value.label] = ordinal + 1
        keyed.append(value if value.key else replace(value, key=f"{group_key}:{value.label}:{ordinal}"))
    return tuple(keyed)


def without_values(document: ReportDocument, hidden_keys: Iterable[str]) -> ReportDocument:
    """Drop the rows the physician hid from the sheet (item 9).

    The filter works on the built document, once, so the preview, the PDF, the
    CSV and the JSON all lose the same rows; a group that becomes empty
    disappears with its notes.  Unknown keys are ignored, which keeps a study
    reload from resurrecting a row that no longer exists.
    """
    hidden = frozenset(key for key in hidden_keys if key)
    if not hidden:
        return document
    groups: list[ReportGroup] = []
    dropped = False
    for group in document.groups:
        values = tuple(value for value in group.values if value.key not in hidden)
        if not values:
            dropped = True
            continue
        if len(values) != len(group.values):
            dropped = True
            groups.append(replace(group, values=values))
        else:
            groups.append(group)
    return replace(document, groups=tuple(groups)) if dropped else document


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
    profile_id: str = "",
    include_inputs: bool = True,
    hidden_keys: Iterable[str] = (),
    study_profile_id: str = "",
) -> ReportDocument:
    """Assemble the full report: patient header plus grouped measurements.

    ``profile_id`` selects the report format (item 7 of the 2026-11-06 list):
    the groups the format does not print are dropped here, once, so every
    consumer — the preview, the PDF, the CSV and the JSON — sees the same
    document.  An empty id is the echocardiography format of the older builds.

    ``study_profile_id`` selects the examination the report is about (item 11
    of the 2026-11-06 list).  One study can hold the measurements of several
    examinations, and the sheet must print the one on screen: the measures of
    the other studies are dropped here, before the groups are built, so no
    derived row (a Teichholz EF, a Simpson volume) of another examination
    reaches the protocol either.  An empty id keeps the whole study, which is
    what the callers that know nothing about profiles expect.

    ``hidden_keys`` drops rows the physician hid in the sheet (item 9 of the
    2026-11-06 list) after the group is built and keyed, so hiding and
    restoring are the same operation in both directions.
    """
    from echo_personal_tool.domain.services.report_profiles import profile, profile_title
    from echo_personal_tool.domain.services.report_scope import restrict_snapshot_to_profile
    from echo_personal_tool.domain.study_profiles import is_explicit, study_profile

    info = patient or PatientInfo()
    if snapshot is not None and is_explicit(study_profile_id):
        snapshot = restrict_snapshot_to_profile(snapshot, study_profile(study_profile_id))
    if info.bsa_m2 is None and snapshot is not None and snapshot.indexed is not None:
        info = PatientInfo(**{**info.__dict__, "bsa_m2": snapshot.indexed.bsa_m2})
    if not profile_id:
        # No format asked for: keep the pre-item-7 document byte for byte, so
        # the dialog and every older caller print what they printed before.
        return without_values(
            ReportDocument(
                patient=info,
                groups=build_report_groups(
                    snapshot,
                    sex=sex,
                    length_display_unit=length_display_unit,
                    include_inputs=include_inputs,
                ),
            ),
            hidden_keys,
        )
    chosen = profile(profile_id)
    groups = chosen.groups(
        build_report_groups(
            snapshot,
            sex=sex,
            length_display_unit=length_display_unit,
            include_inputs=include_inputs,
        )
    )
    return without_values(
        ReportDocument(
            patient=info,
            groups=groups,
            title=profile_title(chosen.id, tr),
            profile_id=chosen.id,
        ),
        hidden_keys,
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
    return replace(document, groups=tuple(groups))
