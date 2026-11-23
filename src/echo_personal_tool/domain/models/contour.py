"""Domain contour model."""

from __future__ import annotations

from dataclasses import dataclass, field

#: Chamber id of an RV free-wall *trace* (plan А.7): the drawn material line
#: the RV strain tracks, not a cavity boundary. A separate id keeps the
#: free-wall trace out of every cavity calculation — the FAC/volume grouping
#: selects chamber ``"RV"`` exactly, and a wall is not an area.
RV_FREE_WALL_CHAMBER = "RV_FW"


@dataclass(frozen=True)
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
    sop_instance_uid: str | None = None
    review_pending: bool = False
    refine_step: int = 0
    refine_locked_indices: tuple[int, ...] = ()
    measurement_label: str | None = None
    #: Freehand trace (LV/atrial stroke or freehand area). Assistants must not move it.
    unassisted: bool = False
    #: Stable measurement ID for provenance (QH-1b.1). Empty for legacy docs.
    measurement_id: str = ""
    #: Content revision, incremented on each edit (QH-1b.1).
    revision: int = 0

    @property
    def is_open_arc(self) -> bool:
        return self.mitral_annulus is not None

    def closed_polygon_points(self) -> list[tuple[float, float]]:
        """Arc points; for open arc the MA chord closes the cavity base."""
        annulus = self.mitral_annulus
        if annulus is None:
            return list(self.points)
        septal, lateral = annulus
        return list(self.points) + [lateral, septal]
