"""Presentation glue between the viewer and the PHI mask.

The filter knows nothing about vendors or DICOM: it asks the profile table for a
context, turns it into rectangles with the pure domain code, and fills them.
It exists mainly to keep the viewer free of that plumbing and to give one place
to switch the whole thing off at runtime.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np

from echo_personal_tool.domain.services.phi_mask import (
    MaskPlan,
    MaskRect,
    apply_mask,
    fill_values,
    resolve_mask_plan,
)
from echo_personal_tool.infrastructure.phi_mask_profiles import (
    PhiMaskContext,
    masks_disabled_by_header,
    phi_mask_context,
    resolve_mask_spec,
)

# The background of a scanner header does not change from frame to frame, so the
# fill colour is measured once and then reused.  It is refreshed periodically
# anyway: a clip can fade in, switch layout, or start on a black frame.
BACKGROUND_REFRESH_EVERY = 60


class AnonymizationFilter:
    """Masks burned-in patient data on frames before they are rendered.

    Every frame passes through :meth:`apply`, which returns either the original
    array (nothing to mask, filter off, or the file declares no burned-in text)
    or a new masked array.  The input is never modified: frames come from the
    frame cache and are shared with playback, M-mode extraction and export, so
    mutating them would make the choice irreversible.

    The masked result is a fresh array rather than a reused buffer on purpose —
    it escapes into ``_current_frame`` and is read by other widgets, and a
    recycled buffer would silently rewrite data somebody still holds.
    """

    def __init__(self, enabled: bool = True) -> None:
        self._enabled = bool(enabled)
        self._last_plan: MaskPlan = MaskPlan(reason="disabled")
        self._fills: tuple[np.ndarray | int, ...] = ()
        self._fills_key: tuple[str, tuple[MaskRect, ...], tuple[int, ...]] | None = None
        self._fills_age = 0

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def last_plan(self) -> MaskPlan:
        """Plan produced by the last :meth:`apply` call (diagnostics/tests)."""
        return self._last_plan

    def set_enabled(self, value: bool) -> None:
        self._enabled = bool(value)
        if not self._enabled:
            self._last_plan = MaskPlan(reason="disabled")

    def plan_for(self, height: int, width: int, source_path: Path | str | None = None) -> MaskPlan:
        """Return the plan that :meth:`apply` would use for this frame size."""
        if not self._enabled:
            return MaskPlan(reason="disabled")
        context = phi_mask_context(source_path)
        if masks_disabled_by_header(context):
            return MaskPlan(reason="burned-in-annotation-no")
        spec = resolve_mask_spec(context.vendor, height, width)
        return resolve_mask_plan(spec, height, width, panel_top=context.panel_top)

    def apply(
        self,
        pixels: np.ndarray,
        source_path: Path | str | None = None,
    ) -> np.ndarray:
        """Mask ``pixels`` in place of nothing; returns the frame to render."""
        if not self._enabled:
            self._last_plan = MaskPlan(reason="disabled")
            return pixels

        frame = np.asarray(pixels)
        if frame.ndim < 2 or frame.size == 0:
            self._last_plan = MaskPlan(reason="empty-frame")
            return pixels

        height, width = frame.shape[:2]
        context = phi_mask_context(source_path)
        if masks_disabled_by_header(context):
            self._last_plan = MaskPlan(reason="burned-in-annotation-no")
            return pixels

        spec = resolve_mask_spec(context.vendor, height, width)
        plan = resolve_mask_plan(spec, height, width, panel_top=context.panel_top)
        self._last_plan = plan
        if plan.is_empty:
            return pixels
        return apply_mask(frame, plan, fills=self._fills_for(frame, plan, source_path))

    def _fills_for(
        self,
        frame: np.ndarray,
        plan: MaskPlan,
        source_path: Path | str | None,
    ) -> tuple[np.ndarray | int, ...]:
        """Cached fill colours for this file and geometry."""
        key = (str(source_path) if source_path is not None else "", plan.rects, frame.shape[:2])
        if self._fills_key == key and self._fills and self._fills_age < BACKGROUND_REFRESH_EVERY:
            self._fills_age += 1
            return self._fills
        self._fills = fill_values(frame, plan)
        self._fills_key = key
        self._fills_age = 0
        return self._fills

    def context_for(self, source_path: Path | str | None) -> PhiMaskContext:
        return phi_mask_context(source_path)


#: A callable that hides burned-in PHI on one frame and returns it to render.
FrameMasker = Callable[[np.ndarray], np.ndarray]


def frame_masker(
    source_path: Path | str | None,
    *,
    enabled: bool = True,
) -> FrameMasker | None:
    """Build a masker bound to one file, for code that consumes frames off-screen.

    The MP4 export worker runs on a pool thread and never renders anything: it
    cannot ask a widget which file it is exporting or whether masking is on.  It
    gets its own filter — with the geometry resolved from *the exported file's
    own header*, exactly like the preview does for the displayed one, so the
    exported video and what the user saw agree on the band, panel clamp
    included.

    A private filter per export also keeps the cached fill colour of this clip
    out of the viewer's filter, which lives on the GUI thread.

    Returns ``None`` when masking is switched off, so a caller can keep the path
    that skips re-encoding the file altogether.
    """
    if not enabled:
        return None
    filter_ = AnonymizationFilter(enabled=True)

    def mask(frame: np.ndarray) -> np.ndarray:
        return filter_.apply(frame, source_path)

    return mask
