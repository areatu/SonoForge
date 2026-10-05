"""Canonical spectral-Doppler measurement labels and legacy aliases.

Physical marker labels are part of saved measurement data, so this module keeps
old spellings readable while all newly created measurements use unambiguous,
flow-specific names.  Velocity and instantaneous pressure-gradient terminology
follows current echocardiography convention: ``Vmax`` and ``PGmax``.
"""

from __future__ import annotations

import re

# Anatomical order used in overlays, worksheets and reports.
FLOW_SITES: tuple[str, ...] = (
    "MV",
    "MR",
    "AV",
    "LVOT",
    "AR",
    "TV",
    "TR",
    "PV",
    "RVOT",
    "PR",
)

TISSUE_PEAK_LABELS: tuple[str, ...] = (
    "E",
    "A",
    "e_sept",
    "e_lat",
    "a_sept",
    "a_lat",
    "s_sept",
    "s_lat",
    "s_prime_rv",
)

FLOW_PEAK_LABELS: tuple[str, ...] = tuple(f"{site} Vmax" for site in FLOW_SITES)
PEAK_LABELS: tuple[str, ...] = (*TISSUE_PEAK_LABELS, *FLOW_PEAK_LABELS)
TRACE_LABELS: tuple[str, ...] = tuple(f"{site} VTI" for site in FLOW_SITES)
INTERVAL_LABELS: tuple[str, ...] = (
    "DT",
    "IVRT",
    "AT",
    "ET",
    "MV PHT",
    "TV PHT",
    "AR PHT",
    "PR PHT",
    "AV AT",
    "AV ET",
    "RVOT AT",
)


def normalize_label(label: str) -> str:
    """Return a comparison key tolerant of punctuation and prime glyphs."""

    text = (label or "").strip().lower().replace("′", "'")
    text = text.replace("peak", "max")
    text = re.sub(r"[^a-z0-9']+", "_", text)
    return text.strip("_").replace("'", "_prime")


# Historical marker spellings that must continue to load. Generic Vmax/Vpeak
# represented the aortic/CW workflow in the old UI and is therefore mapped to
# AV for specific reporting rather than being displayed as an unlabeled value.
_PEAK_ALIASES: dict[str, str] = {
    "vmax": "AV Vmax",
    "v_max": "AV Vmax",
    "avmax": "AV Vmax",
    "av_max": "AV Vmax",
    "trmax": "TR Vmax",
    "tr_max": "TR Vmax",
}
for _site in FLOW_SITES:
    _canonical = f"{_site} Vmax"
    _site_key = _site.lower()
    _PEAK_ALIASES[normalize_label(_canonical)] = _canonical
    _PEAK_ALIASES[f"{_site_key}max"] = _canonical
    _PEAK_ALIASES[f"{_site_key}_max"] = _canonical


def canonical_peak_label(label: str) -> str:
    """Canonicalize known flow peaks while leaving tissue labels intact."""

    key = normalize_label(label)
    canonical = _PEAK_ALIASES.get(key)
    if canonical is not None:
        return canonical
    for tissue in TISSUE_PEAK_LABELS:
        if normalize_label(tissue) == key:
            return tissue
    return (label or "").strip()


def flow_site_from_peak_label(label: str) -> str | None:
    canonical = canonical_peak_label(label)
    if canonical.endswith(" Vmax"):
        site = canonical[: -len(" Vmax")]
        if site in FLOW_SITES:
            return site
    return None


def flow_site_from_trace_label(label: str) -> str | None:
    """Resolve both ``AV VTI`` and legacy ``VTI AV`` trace labels."""

    key = normalize_label(label)
    if key in {"vti", "vti_trace"}:
        return "AV"
    tokens = [token for token in key.split("_") if token]
    if "vti" not in tokens:
        return None
    for site in FLOW_SITES:
        if site.lower() in tokens:
            return site
    return None


def canonical_trace_label(label: str) -> str:
    site = flow_site_from_trace_label(label)
    return f"{site} VTI" if site is not None else (label or "").strip()


def canonical_interval_label(label: str) -> str:
    """Canonicalize site-specific timing labels and common legacy aliases."""

    key = normalize_label(label)
    aliases = {
        "paat": "RVOT AT",
        "rvot_acct": "RVOT AT",
        "rvot_acc_t": "RVOT AT",
        "rvot_acceleration_time": "RVOT AT",
        "pht": "MV PHT",
    }
    if key in aliases:
        return aliases[key]
    for canonical in INTERVAL_LABELS:
        if normalize_label(canonical) == key:
            return canonical
    return (label or "").strip()
