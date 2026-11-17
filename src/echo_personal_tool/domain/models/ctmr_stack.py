"""Pixel-free classic CT/MR stack references, not a volume or cine (#557)."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt
from pathlib import Path
from typing import cast

from echo_personal_tool.domain.models.dicom_display import DicomDisplay

Vector3 = tuple[float, float, float]
Orientation = tuple[float, float, float, float, float, float]


@dataclass(frozen=True)
class SliceGeometry:
    """DICOM LPS coordinates; spacing is (row, column), in millimetres."""

    position: Vector3
    orientation: Orientation
    pixel_spacing: tuple[float, float]

    def __post_init__(self) -> None:
        if len(self.position) != 3 or len(self.orientation) != 6 or len(self.pixel_spacing) != 2:
            raise ValueError("invalid_spatial_geometry")
        if not all(isfinite(v) for v in (*self.position, *self.orientation, *self.pixel_spacing)):
            raise ValueError("invalid_spatial_geometry")
        if any(abs(v) > 1e9 for v in self.position) or any(not 1e-9 <= v <= 1e6 for v in self.pixel_spacing):
            raise ValueError("unstable_spatial_scale")
        a, b = self.orientation[:3], self.orientation[3:]
        if any(abs(sqrt(sum(v * v for v in axis)) - 1) > 1e-4 for axis in (a, b)):
            raise ValueError("invalid_direction_cosines")
        if abs(sum(x * y for x, y in zip(a, b, strict=True))) > 1e-4 or min(self.pixel_spacing) <= 0:
            raise ValueError("invalid_spatial_geometry")

    def patient_point(self, row: float, column: float) -> Vector3:
        if not isfinite(row) or not isfinite(column):
            raise ValueError("invalid_image_coordinate")
        # The first IOP vector follows increasing COLUMN, the second ROW.
        return cast(
            Vector3,
            tuple(
                self.position[i]
                + column * self.pixel_spacing[1] * self.orientation[i]
                + row * self.pixel_spacing[0] * self.orientation[i + 3]
                for i in range(3)
            ),
        )


@dataclass(frozen=True)
class StackFrameRef:
    """One exact SOP/local frame, with no resident pixels or patient demographics.

    The stat stamp detects ordinary replacement; it is NOT a content hash.
    The future loader must re-check it before decoding/publishing.
    """

    path: Path
    study_uid: str
    series_uid: str
    sop_uid: str
    frame_of_reference_uid: str
    sop_class_uid: str
    modality: str
    rows: int
    columns: int
    bits_allocated: int
    bits_stored: int
    pixel_representation: int
    photometric: str
    geometry: SliceGeometry | None
    dimension_key: tuple[tuple[str, str], ...]
    image_type: tuple[str, ...]
    display: DicomDisplay | None = None
    local_frame: int = 0
    file_stamp: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if not all((self.study_uid, self.series_uid, self.sop_uid, self.sop_class_uid)):
            raise ValueError("invalid_frame_identity")
        if self.local_frame != 0 or self.modality not in ("CT", "MR"):
            raise ValueError("classic_frame_required")
        if any(type(v) is not int or v <= 0 for v in (self.rows, self.columns, self.bits_stored, self.bits_allocated)):
            raise ValueError("invalid_pixel_geometry")
        if self.bits_allocated not in (8, 16, 32) or self.bits_stored > self.bits_allocated:
            raise ValueError("invalid_pixel_encoding")
        if self.pixel_representation not in (0, 1) or self.photometric not in ("MONOCHROME1", "MONOCHROME2"):
            raise ValueError("unsupported_pixel_encoding")

    @property
    def identity(self) -> tuple[str, int]:
        return self.sop_uid, self.local_frame


@dataclass(frozen=True)
class CtMrStack:
    frames: tuple[StackFrameRef, ...]
    spatial_order_verified: bool
    positions_mm: tuple[float, ...]
    adjacent_spacing_mm: tuple[float, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class StackIndexDiagnostic:
    """Paths are local UI evidence, never interpolated into log messages."""

    path: Path | None
    code: str


@dataclass(frozen=True)
class CtMrIndex:
    stacks: tuple[CtMrStack, ...]
    diagnostics: tuple[StackIndexDiagnostic, ...]
    complete: bool = True
