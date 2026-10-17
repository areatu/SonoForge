"""Catalog-backed nomenclature for the measurement overlay (TP-1 PR-1).

Rule D-11: every label is fully RU or fully EN.  The single source of truth
is the measurement catalog (``domain.measurement_catalog``) whose label
discipline (unique ids, RU/EN pair per id, Latin in RU only from the ASE
whitelist) is enforced by ``tests/unit/test_ase_table6.py`` (rule A-12).

Overlay call sites keep their locale keys; :func:`overlay_label` resolves a
key through :data:`OVERLAY_TO_CATALOG` to a catalog label and falls back to
``tr(key)`` where the catalog has no entry yet (AT of the mitral inflow,
E/e′ per septal/lateral leaflets, areas).  Those gaps move to the catalog in
a later TP-1 slice.
"""

from __future__ import annotations

from types import MappingProxyType

from echo_personal_tool.domain.measurement_catalog import MEASUREMENTS
from echo_personal_tool.infrastructure.i18n import get_language, tr

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
        "result.s_prime_rv": "rv.s_prime",
        "result.rwt": "lv.rwt",
        "result.fac": "rv.fac",
        "result.rav_4c": "ra.vol",
        "panel.kdo_lv_bp": "lv.edv_bp",
        "panel.kso_lv_bp": "lv.esv_bp",
        "panel.lv_mass": "lv.mass",
        "panel.lav_4c_short": "la.lav_a4c",
        "panel.lav_bi_short": "la.lav_bp",
    }
)

_VIEW_BY_KEY = MappingProxyType({"kdo": "edv", "kso": "esv"})
_VIEW_SUFFIX = MappingProxyType({"4C": "a4c", "2C": "a2c"})


def catalog_label(measurement_id: str, language: str | None = None) -> str:
    """Short catalog label for *measurement_id* in the active (or given) locale."""
    spec = MEASUREMENTS[measurement_id]
    return spec.label(language or get_language()).short


def overlay_label(key: str) -> str:
    """Label for an overlay key, catalog-first, locale-key fallback."""
    measurement_id = OVERLAY_TO_CATALOG.get(key)
    if measurement_id is not None:
        return catalog_label(measurement_id)
    return tr(key)


def view_label(kind: str, view: str) -> str:
    """View-parameterised label: «КДО/КСО · 4-кам.» via catalog ids.

    *kind* is ``"kdo"`` (EDV) or ``"kso"`` (ESV); *view* is ``"4C"``/``"2C"``.
    Unknown combinations fall back to the locale key.
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
