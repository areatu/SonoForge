"""ViewerContext — explicit per-frame/tab/pane identity for QH-3 composition.

Spec §7.1: ViewerContext carries study identity, source identity, frame,
pane/tab/session token and generation, plus the view transforms/calibration the
controllers need to interpret gestures.  It is *not* a second store — the
authoritative measurements remain in `StudyMeasurementSessionStore`; the context
only names *which* source is currently displayed so invalidation, barrier and
S-02 isolation checks have a single stable key.

Persistent identity (`study_uid` / `sop_instance_uid` / `series_uid`) survives
pane/tab reuse; ephemeral IDs (`pane_id`, `tab_id`, `session_generation`) allow
workers to discard late callbacks without touching disk (§6.1 «Generation»).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ViewerPaneIdentity:
    """Stable source identity (S-01) — never derived from file path or tab name."""

    study_uid: str = ""
    sop_instance_uid: str = ""
    series_uid: str = ""
    # For non-DICOM: content hash so a moved file can be rematched explicitly,
    # not by heuristic auto-restore (S-06, QH-1c hash-remap).
    fingerprint: str = ""


@dataclass(frozen=True, slots=True)
class ViewTransform:
    """Image ↔ view mapping needed by gesture controllers.

    `view_range` is (x0, x1, y0, y1) in view coordinates; `viewport_size` is
    (width, height) in logical pixels; `device_pixel_ratio` is for HiDPI
    hit-testing.  All values are optional — controllers handle None gracefully
    during early init before the first frame is shown.
    """

    view_range: tuple[float, float, float, float] | None = None
    viewport_size: tuple[float, float] | None = None
    device_pixel_ratio: float = 1.0
    image_size: tuple[int, int] | None = None  # (width, height) of current frame


@dataclass(frozen=True, slots=True)
class ViewerContext:
    """Explicit context passed to every controller/command.

    * `identity` — authoritative study/source (S-01, S-02)
    * `frame_index` + `total_frames` — which frame of the cine is shown
    * `generation` — incremented on every source replacement; late worker
      callbacks carry the generation they were spawned for (A-05, §5.2)
    * `pane_id` / `tab_id` — ephemeral container, never used for provenance
    * `pixel_spacing` — effective spacing (manual overrides real; None = uncalibrated)
    * `view_transform` — geometry for hit-testing without reaching into ViewBox
    * `extra` — escape hatch for per-slice state (kept bounded; not a second store)
    """

    identity: ViewerPaneIdentity = field(default_factory=ViewerPaneIdentity)
    frame_index: int = 0
    total_frames: int = 0
    generation: int = 0
    pane_id: str = "main"
    tab_id: str = ""
    pixel_spacing: tuple[float, float] | None = None
    calibration_version: str = ""
    view_transform: ViewTransform = field(default_factory=ViewTransform)
    extra: dict[str, Any] | None = None

    # -- queries -----------------------------------------------------------

    def matches_source(self, other: ViewerContext) -> bool:
        """True when two contexts refer to the same source (S-01)."""
        return (
            self.identity.study_uid == other.identity.study_uid
            and self.identity.sop_instance_uid == other.identity.sop_instance_uid
        )

    def is_same_generation(self, generation: int) -> bool:
        """Whether a worker result for `generation` is still current (stale → discard)."""
        return self.generation == generation

    def with_frame(self, frame_index: int) -> ViewerContext:
        return ViewerContext(
            identity=self.identity,
            frame_index=frame_index,
            total_frames=self.total_frames,
            generation=self.generation,
            pane_id=self.pane_id,
            tab_id=self.tab_id,
            pixel_spacing=self.pixel_spacing,
            calibration_version=self.calibration_version,
            view_transform=self.view_transform,
            extra=self.extra,
        )

    def with_generation(self, generation: int) -> ViewerContext:
        return ViewerContext(
            identity=self.identity,
            frame_index=self.frame_index,
            total_frames=self.total_frames,
            generation=generation,
            pane_id=self.pane_id,
            tab_id=self.tab_id,
            pixel_spacing=self.pixel_spacing,
            calibration_version=self.calibration_version,
            view_transform=self.view_transform,
            extra=self.extra,
        )

    # -- compat helper -----------------------------------------------------

    @classmethod
    def from_viewer_state(
        cls,
        instance: Any | None,
        frame_index: int,
        total_frames: int,
        *,
        generation: int = 0,
        pane_id: str = "main",
        tab_id: str = "",
        pixel_spacing: tuple[float, float] | None = None,
        view_transform: ViewTransform | None = None,
    ) -> ViewerContext:
        """Build context from the existing ViewerState/AppController state.

        Keeps the migration incremental: old code still produces ViewerState,
        new controllers read ViewerContext.  No behavioural change (QH-0 harness).
        """
        if instance is None:
            identity = ViewerPaneIdentity()
        else:
            identity = ViewerPaneIdentity(
                study_uid=getattr(instance, "study_uid", "") or "",
                sop_instance_uid=getattr(instance, "sop_instance_uid", "") or "",
                series_uid=getattr(instance, "series_uid", "") or "",
                fingerprint="",
            )
        return cls(
            identity=identity,
            frame_index=int(frame_index),
            total_frames=int(total_frames),
            generation=int(generation),
            pane_id=str(pane_id),
            tab_id=str(tab_id),
            pixel_spacing=pixel_spacing,
            view_transform=view_transform or ViewTransform(),
        )


__all__ = ["ViewerContext", "ViewerPaneIdentity", "ViewTransform"]
