"""ASE reference norm ranges from ``References ASE+.md`` (sex-agnostic union)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NormRange:
    low: float | None = None
    high: float | None = None


# Section 1 — LV (References ASE+.md)
LV_IVSD_MM = NormRange(6.0, 11.0)
LV_LVPWD_MM = NormRange(6.0, 11.0)
LV_LVEDD_MM = NormRange(39.0, 59.0)
LVEDVI_MLM2 = NormRange(32.0, 97.0)
LVESVI_MLM2 = NormRange(9.0, 38.0)
LVMI_GM2 = NormRange(43.0, 134.0)

# Section 3 — LA / RA
LAVI_MLM2 = NormRange(None, 34.0)
RAV_ML = NormRange(None, 39.0)

# Aorta root (approximate adult absolute mm; indexed when exceeded)
AO_ANNULUS_MM = NormRange(20.0, 36.0)
AO_SINUS_MM = NormRange(29.0, 42.0)
AO_JUNCTION_MM = NormRange(25.0, 38.0)
AO_PROX_MM = NormRange(25.0, 40.0)
AO_AV_MM = NormRange(25.0, 42.0)

#: Indexed aorta diameters (mm/m²) — the second look at a dilated segment
#: (2026-11-18, item 8): an absolute diameter above its range is re-read as
#: diameter/BSA against the indexed upper limits of the adult references
#: (annulus ≤14, sinuses of Valsalva ≤20, sinotubular junction and ascending
#: aorta ≤17 mm/m²).
AO_ANNULUS_INDEX_MM_M2 = NormRange(None, 14.0)
AO_SINUS_INDEX_MM_M2 = NormRange(None, 20.0)
AO_JUNCTION_INDEX_MM_M2 = NormRange(None, 17.0)
AO_PROX_INDEX_MM_M2 = NormRange(None, 17.0)


def is_outside_norm(value: float, norm: NormRange) -> bool:
    if norm.low is not None and value < norm.low:
        return True
    return norm.high is not None and value > norm.high


def linear_norm_for_label(label: str) -> NormRange | None:
    key = label.casefold().strip()
    mapping = {
        "ivsd": LV_IVSD_MM,
        "lvpwd": LV_LVPWD_MM,
        "lvedd": LV_LVEDD_MM,
        "av": AO_AV_MM,
        "annulus": AO_ANNULUS_MM,
        "ao sinus": AO_SINUS_MM,
        "ao junction": AO_JUNCTION_MM,
        "prox ao": AO_PROX_MM,
        # Indexed aorta diameters (mm/m²), item 8 of the 2026-11-18 list.
        "av index": AO_ANNULUS_INDEX_MM_M2,
        "annulus index": AO_ANNULUS_INDEX_MM_M2,
        "ao sinus index": AO_SINUS_INDEX_MM_M2,
        "ao junction index": AO_JUNCTION_INDEX_MM_M2,
        "prox ao index": AO_PROX_INDEX_MM_M2,
    }
    return mapping.get(key)


def should_show_indexed_linear(label: str, absolute_mm: float) -> bool:
    norm = linear_norm_for_label(label)
    if norm is None:
        return False
    return is_outside_norm(absolute_mm, norm)
