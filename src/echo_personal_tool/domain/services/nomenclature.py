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

from types import MappingProxyType

from echo_personal_tool.domain.measurement_catalog import MEASUREMENTS
from echo_personal_tool.domain.models.linear_measurement import _LABEL_I18N_KEY
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

#: Spectral-Doppler row labels ``"<site> <kind>"`` → catalog id.  Sites the
#: catalog measures not (PHT of regurgitant jets, PG of every jet) fall back.
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

    Areas, volumes, ratios and pixel readings are not linear sizes and keep
    their own numbers of decimals.
    """
    return 1 if unit == "cm" else 0


def overlay_label(key: str) -> str:
    """Label for an overlay key, catalog-first, locale-key fallback."""
    measurement_id = OVERLAY_TO_CATALOG.get(key)
    if measurement_id is not None:
        return catalog_label(measurement_id)
    return tr(key)


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
