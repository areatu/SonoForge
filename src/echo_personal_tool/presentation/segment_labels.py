"""Localised segment names for the STE overlays.

Two name forms are used side by side and they answer different questions:

* :func:`short_segment_label` — the vendor-style abbreviation drawn *next to the
  wall on the cine* ("БазПерг", "СрБок", GE's "Inf. septum base"). The vendors
  label the place they measure; a reader must be able to match a number on the
  image to a segment without a legend.
* :func:`full_segment_label` — the standard AHA name ("базальный
  нижнеперегородочный", "basal inferoseptal") used where there is room for prose
  (quality list, tables, exports).

Both are keyed by the standard 18-segment AHA ids. Missing translations degrade
to the id, never to a wrong segment: a label may be ugly, it must not lie.
"""

from __future__ import annotations

from echo_personal_tool.domain.services.segment_map import SEGMENT_NAMES
from echo_personal_tool.infrastructure.i18n import tr


def _translated(key: str) -> str | None:
    """Value of ``key``, or ``None`` when the locale has no such entry."""
    value = tr(key)
    return None if value == key else value


def short_segment_label(segment_id: int) -> str:
    """Vendor-style short label of a segment ("БазПерг" / "BasSept")."""
    seg = int(segment_id)
    return _translated(f"strain.segment_name.{seg}") or full_segment_label(seg)


def full_segment_label(segment_id: int) -> str:
    """Standard AHA name of a segment, localised when the locale knows it."""
    seg = int(segment_id)
    translated = _translated(f"strain.seg_{seg}")
    if translated is not None:
        return translated
    if seg in SEGMENT_NAMES:
        return SEGMENT_NAMES[seg]
    return tr("strain.segment_fallback", id=str(seg))
