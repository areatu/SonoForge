"""Domain contour model."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Contour:
    phase: str
    view: str = "A4C"
    points: list[tuple[float, float]] = field(default_factory=list)
    source: str = "manual"
