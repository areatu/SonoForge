"""Catalog-backed nomenclature for the overlay and the report (TP-1 PR-1).

Rule D-11: every label is fully RU or fully EN.  The single source of truth
is the measurement catalog (``domain.measurement_catalog``) whose label
discipline (unique ids, RU/EN pair per id, Latin in RU only from the ASE
whitelist) is enforced by ``tests/unit/test_ase_table6.py`` (rule A-12).

Overlay/report call sites keep their locale keys; :func:`overlay_label`
resolves a key through :data:`OVERLAY_TO_CATALOG` to a catalog label and
falls back to ``tr(key)`` where the catalog has no entry yet (AT of the
mitral inflow, E/e′ per septal/lateral leaflets, areas).  Those gaps move to
the catalog in a later TP-1 slice.
"""

from __future__ import annotations

import re
from types import MappingProxyType

from echo_personal_tool.domain.measurement_catalog import (
    CALIPER_TO_MEASUREMENT,
    LINEAR_UNIT_CM,
    LINEAR_UNIT_MM,
    MEASUREMENTS,
)
from echo_personal_tool.domain.models.linear_measurement import (
    _LABEL_I18N_KEY,
    ANATOMICAL_CALIPER_LABELS,
    AREA_LABELS,
    PERCENT_LABELS,
    is_unnamed_caliper_label,
)
from echo_personal_tool.domain.translation import get_language, tr

#: Overlay locale key (``result.*`` / ``panel.*``) → catalog measurement id.
OVERLAY_TO_CATALOG = MappingProxyType(
    {
        "result.mv_e": "mv.e",
        "result.mv_a": "mv.a",
        "result.mv_ea_ratio": "mv.ea",
        "result.doppler_heart_rate": "hr",
        "result.mv_dt": "mv.dt",
        "result.ivrt": "lv.ivrt",
        "result.e_prime_sept": "tdi.e_sept",
        "result.e_prime_lat": "tdi.e_lat",
        "result.e_prime_avg": "tdi.e_avg",
        "result.e_over_e_prime": "mv.e_e_avg",
        "result.e_over_e_prime_sept": "tdi.e_e_sept",
        "result.e_over_e_prime_lat": "tdi.e_e_lat",
        "result.e_prime_over_a_prime": "tdi.e_a_prime",
        "result.s_prime_sept": "tdi.s_prime_sept",
        "result.s_prime_lat": "tdi.s_prime_lat",
        "result.s_prime_rv": "rv.s_prime",
        "result.rwt": "lv.rwt",
        "result.fac": "rv.fac",
        "result.rav_4c": "ra.vol",
        "result.lvedv_teich": "lv.edv_teich",
        "result.lvesv_teich": "lv.esv_teich",
        "result.lvef_teich": "lv.ef_teich",
        "panel.kdo_lv_bp": "lv.edv_bp",
        "panel.kso_lv_bp": "lv.esv_bp",
        "panel.lv_mass": "lv.mass",
        "panel.lav_4c_short": "la.lav_a4c",
        "panel.lav_bi_short": "la.lav_bp",
        "panel.s_la": "la.area",
        "panel.s_ra": "ra.area",
    }
)

_VIEW_BY_KEY = MappingProxyType({"kdo": "edv", "kso": "esv"})
#: ``4C``/``2C`` — apical views; ``BP`` — biplane (report rows use it).
_VIEW_SUFFIX = MappingProxyType({"4C": "a4c", "2C": "a2c", "BP": "bp"})

#: Spectral-Doppler row labels ``"<site> <kind>"`` → catalog id.
_FLOW_TO_CATALOG = MappingProxyType(
    {
        "MV Vmax": "mv.vmax",
        "MR Vmax": "mr.vmax",
        "AV Vmax": "av.vmax",
        "LVOT Vmax": "lvot.vmax",
        "AR Vmax": "ar.vmax",
        "TV Vmax": "tv.vmax",
        "TR Vmax": "tr.vmax",
        "PV Vmax": "pv.vmax",
        "RVOT Vmax": "rvot.vmax",
        "PR Vmax": "pr.vmax",
        "MV VTI": "mv.vti",
        "MR VTI": "mr.vti",
        "AV VTI": "av.vti",
        "LVOT VTI": "lvot.vti",
        "AR VTI": "ar.vti",
        "TV VTI": "tv.vti",
        "TR VTI": "tr.vti",
        "PV VTI": "pv.vti",
        "RVOT VTI": "rvot.vti",
        "PR VTI": "pr.vti",
        "AV PGmax": "av.pg_peak",
        "TR PGmax": "tr.pg",
        "AV PGmean": "av.pg_mean",
    }
)

_FLOW_MEASUREMENT_FALLBACK = MappingProxyType(
    {
        "Vmax": "doppler.vmax",
        "Vmean": "doppler.vmean",
        "PGmax": "doppler.pg_peak",
        "PGmean": "doppler.pg_mean",
        "VTI": "doppler.vti",
        "PHT": "doppler.pht",
        "AT": "doppler.at",
        "ET": "doppler.et",
    }
)

_FLOW_SITE_KIND_SUFFIX = MappingProxyType(
    {
        "Vmax": "vmax",
        "Vmean": "vmean",
        "PGmax": "pg_peak",
        "PGmean": "pg_mean",
        "VTI": "vti",
        "PHT": "pht",
        "AT": "at",
        "ET": "et",
    }
)

#: Strain view codes (``A4C``/``A2C``) → catalog id; unknown views fall back.
_STRAIN_TO_CATALOG = MappingProxyType({"A4C": "lv.gls_a4c", "A2C": "lv.gls_a2c"})

#: Indexed values measured per position → catalog ids.
_VIEW_QUANTITY_TO_CATALOG = MappingProxyType(
    {
        ("edvi", "4C"): "lv.edvi_a4c",
        ("edvi", "2C"): "lv.edvi_a2c",
        ("edvi", "BP"): "lv.edvi_bp",
        ("esvi", "4C"): "lv.esvi_a4c",
        ("esvi", "2C"): "lv.esvi_a2c",
        ("esvi", "BP"): "lv.esvi_bp",
        ("lavi", "4C"): "la.lavi_a4c",
        ("lavi", "BP"): "la.lavi_bp",
        ("ravi", ""): "ra.ravi",
    }
)


def catalog_label(measurement_id: str, language: str | None = None) -> str:
    """Short catalog label for *measurement_id* in the active (or given) locale."""
    spec = MEASUREMENTS[measurement_id]
    return spec.label(language or get_language()).short


def length_decimals(unit: str) -> int:
    """Decimals of linear sizes (D-12): ``mm`` — 0, ``cm`` (ASE) — 1.

    Delegates to ``MEASUREMENTS["caliper.length"].decimals_for(unit)``.
    """
    target = LINEAR_UNIT_CM if unit == "cm" else LINEAR_UNIT_MM
    return MEASUREMENTS["caliper.length"].decimals_for(target)


def view_measurement_id(kind: str, view: str) -> str:
    """Catalog measurement id for LV Simpson EDV/ESV per view (``4C``/``2C``/``BP``)."""
    quantity = _VIEW_BY_KEY.get(kind, "edv")
    suffix = _VIEW_SUFFIX.get(view, "bp")
    candidate = f"lv.{quantity}_{suffix}"
    return candidate if candidate in MEASUREMENTS else "lv.edv_bp"


def flow_measurement_id(site: str, kind: str) -> str:
    """Catalog measurement id for spectral Doppler row ``"<site> <kind>"``."""
    mapped = _FLOW_TO_CATALOG.get(f"{site} {kind}")
    if mapped is not None:
        return mapped
    site_key = site.strip().lower()
    suffix = _FLOW_SITE_KIND_SUFFIX.get(kind)
    if site_key and suffix:
        candidate = f"{site_key}.{suffix}"
        if candidate in MEASUREMENTS:
            return candidate
    return _FLOW_MEASUREMENT_FALLBACK.get(kind, "doppler.vmax")


def strain_measurement_id(view: str | None) -> str:
    """Catalog measurement id for GLS of *view* (or global ``lv.gls``)."""
    if view is not None:
        upper = view.upper()
        if upper in {"A3C", "ALAX"}:
            return "lv.gls_a3c"
        mapped = _STRAIN_TO_CATALOG.get(upper)
        if mapped is not None:
            return mapped
    return "lv.gls"


def indexed_measurement_id(quantity: str, view: str = "") -> str:
    """Catalog measurement id for an indexed chamber volume."""
    mapped = _VIEW_QUANTITY_TO_CATALOG.get((quantity, view))
    if mapped is not None:
        return mapped
    return "lv.edvi_bp"


def overlay_label(key: str) -> str:
    """Label for an overlay key, catalog-first, locale-key fallback."""
    measurement_id = OVERLAY_TO_CATALOG.get(key)
    if measurement_id is not None:
        return catalog_label(measurement_id)
    return tr(key)


#: Spectral-Doppler marker labels → catalog ids.  The markers keep short
#: storage labels (``s_prime_rv``, ``e_sept``… — they are part of saved data),
#: but a marker printed on the frame must read as a clinical name, not as the
#: storage key (2026-11-17 list, item 4).  The tissue entries mirror
#: ``TISSUE_PEAK_LABELS``; the flow entries are resolved by site below.
_MARKER_TO_CATALOG = MappingProxyType(
    {
        # E/A are the mitral inflow peaks; the catalog adds the valve to the
        # name («MV E»), which is more than the marker needs on the frame, so
        # these two keep their short clinical reading on both locales.
        "e": "",
        "a": "",
        "e_sept": "tdi.e_sept",
        "e_lat": "tdi.e_lat",
        "a_sept": "mv.a",
        "a_lat": "mv.a",
        "s_sept": "tdi.s_prime_sept",
        "s_lat": "tdi.s_prime_lat",
        # The RV systolic peak has no separate septal entry: it is the peak
        # the catalog names ``rv.s_prime``.  The septal/lateral keys the old
        # metrics lookups accepted are the mitral-annulus ones below.
        "s_prime_rv": "rv.s_prime",
        # Legacy spellings of the same markers.
        "e_prime_sept": "tdi.e_sept",
        "e_prime_lat": "tdi.e_lat",
        "s_prime_sept": "tdi.s_prime_sept",
        "s_prime_lat": "tdi.s_prime_lat",
        "rv_s_prime": "rv.s_prime",
    }
)


def marker_label(label: str, language: str | None = None) -> str:
    """Clinical name of a Doppler marker label, for the caption on the frame.

    The marker keeps its storage label (``s_prime_rv``) in the document — old
    studies and the calculation read that spelling — while the caption reads
    «s′ ПЖ».  Flow peaks (``TR Vmax``…) already carry their clinical name and
    fall through unchanged; an unknown label is printed as stored rather than
    guessed.
    """
    text = (label or "").strip()
    if not text:
        return text
    key = "_".join(re.findall(r"[a-z0-9]+", text.casefold().replace("′", "'")))
    if key not in _MARKER_TO_CATALOG:
        return text
    measurement_id = _MARKER_TO_CATALOG[key]
    if not measurement_id:
        return text
    return catalog_label(measurement_id, language)


def view_label(kind: str, view: str) -> str:
    """View-parameterised label: «КДО/КСО · 4-кам.» via catalog ids.

    *kind* is ``"kdo"`` (EDV) or ``"kso"`` (ESV); *view* is ``"4C"``/``"2C"``
    (overlay/panel), ``"BP"`` (report biplane rows).  Unknown combinations
    fall back to the locale key.
    """
    quantity = _VIEW_BY_KEY.get(kind)
    suffix = _VIEW_SUFFIX.get(view)
    fallback = tr(f"panel.{kind}_lv", view=view)
    if quantity is None or suffix is None:
        return fallback
    measurement_id = f"lv.{quantity}_{suffix}"
    if measurement_id in MEASUREMENTS:
        return catalog_label(measurement_id)
    return fallback


def flow_label(site: str, kind: str) -> str:
    """Spectral-Doppler row label ``"<site> <kind>"``, catalog-first."""
    measurement_id = _FLOW_TO_CATALOG.get(f"{site} {kind}")
    if measurement_id is not None:
        return catalog_label(measurement_id)
    return f"{site} {kind}"


def strain_label(view: str | None) -> str:
    """GLS row label for a strain view (``A4C``/``A2C``), catalog-first.

    ``None`` (or an unknown view) reads as the average: the plain GLS label.
    """
    if view is not None:
        measurement_id = _STRAIN_TO_CATALOG.get(view.upper())
        if measurement_id is not None:
            return catalog_label(measurement_id)
        return tr("domain.report.strain_gls_view", view=view)
    return catalog_label("lv.gls")


def indexed_label(quantity: str, view: str = "") -> str:
    """Per-position indexed label («иКДО · 4-кам.»), catalog-first.

    ``quantity`` is ``"edvi"``/``"esvi"``/``"lavi"``/``"ravi"``; ``view`` is
    ``"4C"``/``"2C"``/``"BP"`` (empty for RAVi).  Unknown combinations fall
    back to the historical composed label.
    """
    measurement_id = _VIEW_QUANTITY_TO_CATALOG.get((quantity, view))
    if measurement_id is not None:
        return catalog_label(measurement_id)
    return f"{quantity.upper()}i {view}".rstrip()


def caliper_label(raw: str) -> str:
    """Caliper label in the active locale (RU xor EN), or the raw label.

    The calipers store fixed internal labels (``LVEDD``, ``%D стеноз``…);
    the catalog id comes from the tool that drew the caliper, so the legacy
    i18n map stays the bridge until the caliper stores measurement ids.
    """
    key = _LABEL_I18N_KEY.get(raw)
    return tr(key) if key else raw


def is_renamable_caliper_label(raw: str) -> bool:
    """True when a caliper label may be renamed by the point menu (item 1).

    The generic «Dist» placeholder and a name the physician already invented
    are renameable; every fixed label of the two registries («LVEDD»,
    «%D стеноз»…) and every anatomical tool label («TAPSE», «Ao Sinus»…) keeps
    its meaning and its report row.
    """
    label = (raw or "").strip()
    if not label:
        return False
    if is_unnamed_caliper_label(label):
        return True
    if label in ANATOMICAL_CALIPER_LABELS or label in PERCENT_LABELS or label in AREA_LABELS:
        return False
    return label not in _LABEL_I18N_KEY and label not in CALIPER_TO_MEASUREMENT
