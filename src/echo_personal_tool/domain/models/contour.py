"""Domain contour model."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Contour:
    phase: str
    view: str = "A4C"
    chamber: str = "LV"
    points: list[tuple[float, float]] = field(default_factory=list)
    source: str = "manual"
    mitral_annulus: tuple[tuple[float, float], tuple[float, float]] | None = None
    apex_landmark: tuple[float, float] | None = None
    num_nodes: int = 32
    frame_index: int | None = None

    @property
    def is_open_arc(self) -> bool:
        return self.mitral_annulus is not None

    def closed_polygon_points(self) -> list[tuple[float, float]]:
        """Arc points; for open arc the MA chord closes the cavity base."""
        if not self.is_open_arc:
            return list(self.points)
        septal, lateral = self.mitral_annulus  # type: ignore[misc]
        return list(self.points) + [lateral, septal]
