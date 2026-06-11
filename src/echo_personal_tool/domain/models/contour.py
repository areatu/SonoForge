"""Domain contour model."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Contour:
    phase: str
    view: str = "A4C"
    points: list[tuple[float, float]] = field(default_factory=list)
    source: str = "manual"
    mitral_annulus: tuple[tuple[float, float], tuple[float, float]] | None = None

    @property
    def is_open_arc(self) -> bool:
        return self.mitral_annulus is not None
