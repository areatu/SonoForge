"""Label → handbook lookup and the norm gradation of a report value (issue 277).

The report rows carry their gradation as data (``ReportValue.norm_grade``) so
the PDF sheet can paint the norm dot next to the value and the preview card
can repeat it — the same handbook scale the panel rows and the S2 card show.

This is a leaf module: it imports only the reference data store, never the
report builder, so the import graph stays acyclic (the builder imports the
lookup from here; the architecture-boundaries test pins that).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from echo_personal_tool.domain.services.reference_data_store import ReferenceDataStore

logger = logging.getLogger(__name__)

#: App measurement label → parameter id in the structured reference data.
LABEL_TO_PARAM_ID: Mapping[str, str] = {
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
    # Lang 2015 volumes: absolute (mL) and indexed (mL/m²), sex-specific. The
    # rows look these up by their norm label ("LVEDV" / "LVEDVi"…).
    "lvedv": "lvedv",
    "lvesv": "lvesv",
    "lvedvi": "lvedvi",
    "lvesvi": "lvesvi",
    "lav": "lav",
    "lavi": "lavi",
    "la area": "la_area",
    "площадь лп": "la_area",
    "s лп": "la_area",
    "ra area": "ra_area",
    "площадь пп": "ra_area",
    "rav": "ra_volume",
    "ravi": "ra_vol_index",
    "иопп": "ra_vol_index",
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
    # IVC diameter («НПВ» / "IVC"): the reference norm is ≤21 mm. Both keys —
    # rows look up norms by their localized display label.
    "нпв": "ivc_diameter",
    "ivc": "ivc_diameter",
    # Aorta segments (item 6 of the 2026-11-18 list): the sex-specific
    # 2022 ACC/AHA ranges of the handbook instead of the sex-agnostic
    # fallback constants.
    "ao sinus": "asc_aorta",
    "ao junction": "sinotubular",
    "prox ao": "ascending_aorta",
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

#: Reference unit → app unit conversion for the few parameters whose stored
#: norm is expressed in another unit than the app reports (tr_vmax: cm/s→m/s).
UNIT_SCALE: Mapping[str, float] = {"tr_vmax": 0.01, "liver_size": 0.1}


def unit_scale_for_label(label: str) -> float:
    """App → reference unit conversion of one measurement label."""
    param_id = LABEL_TO_PARAM_ID.get(label.casefold().strip())
    return UNIT_SCALE.get(param_id or "", 1.0)


@lru_cache(maxsize=1)
def _store() -> ReferenceDataStore | None:
    """Lazily loaded reference data (the YAML is parsed once per process)."""
    from yaml import YAMLError

    from echo_personal_tool.domain.services.reference_data_store import ReferenceDataStore

    try:
        return ReferenceDataStore().load()
    except (OSError, ValueError, YAMLError) as exc:
        # A missing, unreadable or malformed handbook must not kill the report.
        logger.warning("reference data unavailable; norm gradations will be partial (%s)", type(exc).__name__)
        return None


def _is_female(sex: str) -> bool:
    return (sex or "").casefold().startswith(("f", "ж", "w"))


def norm_grade_for(
    label: str,
    value: float | None,
    sex: str = "",
    *,
    norm_label: str | None = None,
    scale: float | None = None,
) -> str:
    """Gradation name of a value («Норма», «Лёгкое» …); ``""`` when unbound.

    The same handbook lookup the report's norm column uses (the label table
    above + the gradation cuts of the parameter), so a norm dot always agrees
    with the norm text next to it.  Empty when the label has no handbook
    binding, the value is missing, or the value falls outside every cut — the
    dot then stays off, exactly as on the panel rows (spec §4.7).
    """
    if value is None:
        return ""
    key = norm_label or label
    param_id = LABEL_TO_PARAM_ID.get(key.casefold().strip())
    if param_id is None:
        return ""
    store = _store()
    if store is None:
        return ""
    resolved_scale = unit_scale_for_label(key) if scale is None else scale
    ref_value = value * resolved_scale
    female = _is_female(sex)
    for _topic, _pathology, _gradation, param in store.search(param_id):
        if param.id != param_id:
            continue
        for gradation in param.gradations:
            rng = (gradation.range_female if female else gradation.range_male) or gradation.range_male
            if rng is None:
                continue
            low_ok = rng.low is None or ref_value >= rng.low
            high_ok = rng.high is None or ref_value <= rng.high
            if low_ok and high_ok:
                return str(gradation.name)
        return ""
    return ""
