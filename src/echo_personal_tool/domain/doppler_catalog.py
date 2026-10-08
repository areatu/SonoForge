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
    # Δt between fixed velocities on the regurgitant CW jet (Э11 dP/dt):
    # MR 1 → 3 m/s (LV), TR 1 → 2 m/s (RV).
    "MR dP/dt",
    "TR dP/dt",
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
        "lv_dp_dt": "MR dP/dt",
        "rv_dp_dt": "TR dP/dt",
    }
    if key in aliases:
        return aliases[key]
    for canonical in INTERVAL_LABELS:
        if normalize_label(canonical) == key:
            return canonical
    return (label or "").strip()


#: Acquisition modes a spectral-Doppler marker can be measured in (Э2).
#: Resolved per marker from the DICOM ``RegionDataType`` (3 = PW, 4 = CW,
#: 0x10/0x11 = TDI) with an explicit manual override winning; empty means
#: the mode is unknown (legacy records, MP4/JPEG without an override).
DOPPLER_MODES: tuple[str, ...] = ("CW", "PW", "TDI")

#: Magnitude (cm/s) at which an unknown-mode velocity is shown in m/s,
#: mirroring the scanner convention used by the Doppler caliper.
UNKNOWN_MODE_MS_THRESHOLD_CM_S = 100.0


def normalize_doppler_mode(mode: str | None) -> str:
    """Canonicalize an acquisition mode; unknown spellings become ``""``.

    ``TDI_PW`` (pulsed tissue Doppler, ``RegionDataType`` 0x11) is tissue
    Doppler for display purposes and folds into ``TDI``.
    """

    text = (mode or "").strip().upper()
    if text in DOPPLER_MODES:
        return text
    if text in {"TDI_PW", "TDI-PW", "TDIPW"}:
        return "TDI"
    return ""


def velocity_display_unit(mode: str | None, velocity_cm_s: float | None = None) -> str:
    """Display unit for a Doppler velocity (Э2/D-17).

    CW is shown in m/s, PW and TDI in cm/s.  When the mode is unknown the
    unit follows the magnitude, like on a scanner: at least 1 m/s reads in
    m/s, slower flows in cm/s.
    """

    normalized = normalize_doppler_mode(mode)
    if normalized == "CW":
        return "m/s"
    if normalized in ("PW", "TDI"):
        return "cm/s"
    if velocity_cm_s is not None and abs(velocity_cm_s) >= UNKNOWN_MODE_MS_THRESHOLD_CM_S:
        return "m/s"
    return "cm/s"


def scale_velocity_for_display(velocity_cm_s: float, mode: str | None) -> tuple[float, str, int]:
    """Scale a stored cm/s velocity for display: ``(value, unit, decimals)``.

    m/s reads with two decimals (``3.12 m/s``), cm/s with one (``72.4 cm/s``),
    matching the scanner convention for CW jets and PW/TDI flows.
    """

    unit = velocity_display_unit(mode, velocity_cm_s)
    if unit == "m/s":
        return velocity_cm_s / 100.0, unit, 2
    return velocity_cm_s, unit, 1
