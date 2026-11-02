"""Persistable, study-scoped manual calculator input (QH-1d).

The input identifier selects both the allowlisted quantity and its canonical unit
from :mod:`echo_personal_tool.domain.calculators.registry`.  This DTO therefore
stores the numeric primary input rather than a widget's locale-formatted text or
any display cache.  It deliberately has no SOP/frame fields: a value typed by a
user is study-scoped and must not be presented as a measurement reference.
"""

from __future__ import annotations

from dataclasses import dataclass

MANUAL_CALCULATOR_ORIGIN = "manual"


@dataclass(frozen=True)
class ManualCalculatorInput:
    """One active user-entered calculator value in canonical input units.

    ``revision`` changes each time this particular active override is replaced
    during a study session.  Clearing an override removes this DTO entirely;
    the resolver then falls back to the measured/derived candidate rather than
    inventing a value or source reference.
    """

    input_id: str
    value: float
    origin: str = MANUAL_CALCULATOR_ORIGIN
    revision: int = 1
