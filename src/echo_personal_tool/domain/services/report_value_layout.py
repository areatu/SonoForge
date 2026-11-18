"""User-level report layout. Keys describe parameters, never a study or frame."""

from __future__ import annotations

from collections.abc import Iterable

# The routine sheet omits these rows. They remain available in the row editor,
# even if this leaves their entire group empty on the printed sheet.
DEFAULT_REPORT_VALUE_EXCLUDED = (
    "lv:lv.length_a4c:0",
    "lv:lv.length_a2c:0",
    "lv:lv.sv_teich:0",
    "calculations:calc.sv_teich:0",
    "av:lvot.vmax:0",
)


def merge_report_order(saved: Iterable[str], reordered: tuple[str, ...]) -> tuple[str, ...]:
    """Replace only the edited rows' slots; retain preferences for absent rows."""
    edited = set(reordered)
    remaining = iter(reordered)
    result = [next(remaining) if key in edited else key for key in dict.fromkeys(saved)]
    return (*result, *remaining)
