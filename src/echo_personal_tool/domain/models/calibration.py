"""Spatial calibration provenance for a DICOM image (#547, #555).

The same pixel grid can carry more than one physical scale: enhanced DICOM has
per-frame pixel measures, and ultrasound clips may contain several spatial
regions (2D panel, colour box, zoom) with different scales.  A single
``pixel_spacing`` tuple is therefore not enough to describe a calibration.  A
:class:`CalibrationContext` records *what* scale was used, *where* (frame and/or
region), *how strong* the evidence is, and which revision produced it.

The module is pure: no pydicom, Qt or infrastructure imports.  The DICOM
resolver in ``domain.services.pixel_spacing_resolver`` builds contexts; viewers
and calculators select one for the geometry they actually measure.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite


class CalibrationScope(str, Enum):
    """Where a calibration is valid."""

    INSTANCE = "instance"
    FRAME = "frame"
    REGION = "region"


class CalibrationConfidence(str, Enum):
    """How strongly the source supports a physical calibration.

    ``MEASURED`` is an explicit spatial DICOM calibration, ``DERIVED`` is a
    deterministic conversion from another physical DICOM unit, ``ASSUMED`` is a
    fallback (for example ImagerPixelSpacing or an isotropic manual line when
    anisotropy is unknown) and ``UNKNOWN`` must not be presented as calibrated.
    """

    MEASURED = "measured"
    DERIVED = "derived"
    ASSUMED = "assumed"
    UNKNOWN = "unknown"


#: Stable reason codes for a refused/ambiguous selection.  They are not
#: localized here; the UI turns them into text in #555.
CALIBRATION_NONE = "calibration_missing"
CALIBRATION_REGION_REQUIRED = "region_required"
CALIBRATION_CROSSES_REGION = "crosses_region"
CALIBRATION_AMBIGUOUS = "ambiguous_region"
CALIBRATION_FRAME_MISMATCH = "frame_mismatch"

#: The only physical unit produced by the current spatial resolver.
MM_PER_PIXEL = "mm_per_pixel"


@dataclass(frozen=True)
class CalibrationRegion:
    """Half-open image-space rectangle ``[x0, x1) × [y0, y1)``.

    DICOM ultrasound-region bounds are inclusive on the max side; callers pass
    the converted half-open bounds so containment checks cannot accidentally
    include the neighbouring panel's first column/row.
    """

    x0: int
    x1: int
    y0: int
    y1: int

    def __post_init__(self) -> None:
        if self.x0 < 0 or self.y0 < 0 or self.x1 <= self.x0 or self.y1 <= self.y0:
            raise ValueError("calibration region must have positive half-open bounds")

    @property
    def width(self) -> int:
        return self.x1 - self.x0

    @property
    def height(self) -> int:
        return self.y1 - self.y0

    def contains(self, x: float, y: float) -> bool:
        return self.x0 <= x < self.x1 and self.y0 <= y < self.y1

    def contains_bbox(self, bbox: tuple[float, float, float, float]) -> bool:
        """True when ``(x0, y0, x1, y1)`` lies completely inside the region."""
        x0, y0, x1, y1 = bbox
        return self.x0 <= min(x0, x1) and max(x0, x1) <= self.x1 and self.y0 <= min(y0, y1) and max(y0, y1) <= self.y1

    def intersects_bbox(self, bbox: tuple[float, float, float, float]) -> bool:
        x0, y0, x1, y1 = bbox
        return self.x0 < max(x0, x1) and min(x0, x1) < self.x1 and self.y0 < max(y0, y1) and min(y0, y1) < self.y1

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.x0, self.x1, self.y0, self.y1)


@dataclass(frozen=True)
class CalibrationContext:
    """One physical scale and its scope/provenance.

    ``frame_index`` is required for ``scope=FRAME`` and ``region`` for
    ``scope=REGION``.  A context with no frame/region is instance-wide.  Manual
    isotropic calibration is deliberately ``ASSUMED``: a single known distance
    gives equal row/column spacing, but cannot prove that pixel anisotropy is
    absent.
    """

    spacing: tuple[float, float]
    source: str
    scope: CalibrationScope = CalibrationScope.INSTANCE
    confidence: CalibrationConfidence = CalibrationConfidence.MEASURED
    frame_index: int | None = None
    region: CalibrationRegion | None = None
    units: str = MM_PER_PIXEL
    revision: int = 0
    assumed_isotropic: bool = False

    def __post_init__(self) -> None:
        if self.units != MM_PER_PIXEL:
            raise ValueError(f"unsupported calibration units: {self.units!r}")
        if not self.source:
            raise ValueError("calibration source must not be empty")
        try:
            row, col = (float(self.spacing[0]), float(self.spacing[1]))
        except (IndexError, TypeError, ValueError) as exc:
            raise ValueError("calibration spacing must be a pair") from exc
        if not isfinite(row) or not isfinite(col) or row <= 0.0 or col <= 0.0:
            raise ValueError("calibration spacing must be finite and positive")
        if self.revision < 0:
            raise ValueError("calibration revision must not be negative")
        if self.scope is CalibrationScope.FRAME:
            if self.frame_index is None or self.frame_index < 0:
                raise ValueError("frame-scoped calibration needs a frame index")
        elif self.scope is CalibrationScope.REGION:
            if self.region is None:
                raise ValueError("region-scoped calibration needs a region")
        elif self.frame_index is not None or self.region is not None:
            raise ValueError("instance-scoped calibration cannot carry a frame or region")

    @property
    def row_spacing(self) -> float:
        return float(self.spacing[0])

    @property
    def column_spacing(self) -> float:
        return float(self.spacing[1])

    @property
    def is_isotropic(self) -> bool:
        return abs(self.row_spacing - self.column_spacing) <= 1e-12 * max(self.row_spacing, self.column_spacing)

    @property
    def is_calibrated(self) -> bool:
        return self.confidence is not CalibrationConfidence.UNKNOWN

    def applies_to_frame(self, frame_index: int | None) -> bool:
        if self.scope is not CalibrationScope.FRAME:
            return True
        return frame_index is not None and frame_index == self.frame_index

    def contains_bbox(self, bbox: tuple[float, float, float, float]) -> bool:
        if self.scope is not CalibrationScope.REGION:
            return True
        assert self.region is not None
        return self.region.contains_bbox(bbox)

    def intersects_bbox(self, bbox: tuple[float, float, float, float]) -> bool:
        if self.scope is not CalibrationScope.REGION:
            return True
        assert self.region is not None
        return self.region.intersects_bbox(bbox)

    def signature(self) -> tuple[object, ...]:
        """Stable basis for freshness comparisons (no timestamps)."""
        region = self.region.as_tuple() if self.region is not None else None
        return (
            tuple(self.spacing),
            self.source,
            self.scope.value,
            self.confidence.value,
            self.frame_index,
            region,
            self.units,
            self.revision,
            self.assumed_isotropic,
        )


@dataclass(frozen=True)
class CalibrationSelection:
    """Result of selecting a context for a frame/geometry."""

    context: CalibrationContext | None = None
    reason: str = ""

    @property
    def available(self) -> bool:
        return self.context is not None


def _dedupe_by_spacing(contexts: list[CalibrationContext]) -> list[CalibrationContext]:
    seen: set[tuple[float, float]] = set()
    unique: list[CalibrationContext] = []
    for context in contexts:
        key = (context.row_spacing, context.column_spacing)
        if key not in seen:
            seen.add(key)
            unique.append(context)
    return unique


def select_calibration(
    contexts: tuple[CalibrationContext, ...],
    *,
    frame_index: int | None = None,
    bbox: tuple[float, float, float, float] | None = None,
) -> CalibrationSelection:
    """Pick one calibration for a frame and optional measurement geometry.

    Rules:

    - instance contexts apply everywhere; frame contexts only to their frame;
    - with a bbox, only a region that *fully contains* the geometry is usable;
      an overlap with two different scales is refused rather than guessed;
    - without a bbox, multiple different region scales require the caller to
      pass geometry (``region_required``);
    - a measurement that touches a region but is not contained by it is refused
      as ``crosses_region``.
    """
    frame_candidates = [
        context
        for context in contexts
        if context.applies_to_frame(frame_index)
        and (context.scope is not CalibrationScope.FRAME or context.frame_index == frame_index)
    ]
    if not frame_candidates:
        return CalibrationSelection(reason=CALIBRATION_FRAME_MISMATCH if contexts else CALIBRATION_NONE)

    if bbox is None:
        if len(frame_candidates) == 1:
            return CalibrationSelection(context=frame_candidates[0])
        distinct = _dedupe_by_spacing(frame_candidates)
        if len(distinct) == 1:
            # Every applicable frame/panel agrees on the scale; only the scope
            # differs.  Prefer the most specific context for display.
            return CalibrationSelection(
                context=max(frame_candidates, key=lambda item: item.scope is CalibrationScope.REGION)
            )
        if any(context.scope is CalibrationScope.REGION for context in frame_candidates):
            if any(context.scope is CalibrationScope.INSTANCE for context in frame_candidates):
                return CalibrationSelection(reason=CALIBRATION_AMBIGUOUS)
            return CalibrationSelection(reason=CALIBRATION_REGION_REQUIRED)
        return CalibrationSelection(reason=CALIBRATION_AMBIGUOUS)

    regions = [context for context in frame_candidates if context.scope is CalibrationScope.REGION]
    containing_regions = [context for context in regions if context.contains_bbox(bbox)]
    if regions and not containing_regions:
        # The geometry is outside every panel, so an instance fallback is fine;
        # if it touches a panel it crosses that panel's scale boundary.
        if any(context.intersects_bbox(bbox) for context in regions):
            return CalibrationSelection(reason=CALIBRATION_CROSSES_REGION)
        containing = [context for context in frame_candidates if context.scope is not CalibrationScope.REGION]
    else:
        containing = [context for context in frame_candidates if context.contains_bbox(bbox)]
    if not containing:
        return CalibrationSelection(reason=CALIBRATION_NONE)
    distinct = _dedupe_by_spacing(containing)
    if len(distinct) == 1:
        # Prefer the most specific region over an instance-level fallback.
        return CalibrationSelection(context=max(containing, key=lambda item: item.scope is CalibrationScope.REGION))
    return CalibrationSelection(reason=CALIBRATION_AMBIGUOUS)


def invalidate_dependents(context: CalibrationContext, *, reason: str = "recalibrated") -> CalibrationContext:
    """Return the next revision of a calibration after an explicit change.

    A recalibration keeps the source/scope but bumps ``revision``; freshness
    consumers compare revisions/signatures and mark earlier derived results
    stale (``calibration_changed``).  ``reason`` is accepted for call-site
    documentation and intentionally does not become part of the signature.
    """
    del reason
    return CalibrationContext(
        spacing=context.spacing,
        source=context.source,
        scope=context.scope,
        confidence=context.confidence,
        frame_index=context.frame_index,
        region=context.region,
        units=context.units,
        revision=context.revision + 1,
        assumed_isotropic=context.assumed_isotropic,
    )
