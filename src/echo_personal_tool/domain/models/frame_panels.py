"""Ultrasound frame panel layout (B-mode, M-mode, Doppler) for composite images."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi
from echo_personal_tool.domain.services.ultrasound_region_physics import (
    PHYSICAL_UNIT_CM,
    PHYSICAL_UNIT_MM,
    horizontal_ms_per_pixel,
    vertical_mm_per_pixel,
)


class PanelKind(str, Enum):
    B_MODE = "b_mode"
    M_MODE = "m_mode"
    DOPPLER = "doppler"


@dataclass(frozen=True)
class UltrasoundPanel:
    """One rectangular panel inside a composite ultrasound frame."""

    kind: PanelKind
    bounds: DopplerSpectrogramRoi
    physical_delta_x: float | None = None
    physical_delta_y: float | None = None
    physical_units_x: int | None = None
    physical_units_y: int | None = None

    @property
    def horizontal_ms_per_pixel(self) -> float | None:
        if self.physical_delta_x is None or self.physical_units_x is None:
            return None
        return horizontal_ms_per_pixel(abs(self.physical_delta_x), self.physical_units_x)

    @property
    def horizontal_mm_per_pixel(self) -> float | None:
        """B-mode horizontal scale (mm/px); None on time/velocity axes."""
        if self.physical_delta_x is None or self.physical_units_x is None:
            return None
        if self.physical_units_x not in (PHYSICAL_UNIT_CM, PHYSICAL_UNIT_MM):
            return None
        return vertical_mm_per_pixel(abs(self.physical_delta_x), self.physical_units_x)

    @property
    def vertical_mm_per_pixel(self) -> float | None:
        if self.physical_delta_y is None or self.physical_units_y is None:
            return None
        return vertical_mm_per_pixel(abs(self.physical_delta_y), self.physical_units_y)

    def contains(self, x: float, y: float) -> bool:
        return self.bounds.contains(x, y)


@dataclass(frozen=True)
class FramePanelLayout:
    panels: tuple[UltrasoundPanel, ...]

    def panel_at(self, x: float, y: float) -> UltrasoundPanel | None:
        for panel in self.panels:
            if panel.contains(x, y):
                return panel
        return None

    def first_of_kind(self, kind: PanelKind) -> UltrasoundPanel | None:
        for panel in self.panels:
            if panel.kind is kind:
                return panel
        return None

    @property
    def b_mode(self) -> UltrasoundPanel | None:
        return self.first_of_kind(PanelKind.B_MODE)

    @property
    def m_mode(self) -> UltrasoundPanel | None:
        return self.first_of_kind(PanelKind.M_MODE)

    @property
    def doppler(self) -> UltrasoundPanel | None:
        return self.first_of_kind(PanelKind.DOPPLER)


@dataclass(frozen=True)
class MmodeCalibrationState:
    """Per-instance M-mode strip calibration (vertical depth scale)."""

    roi: DopplerSpectrogramRoi
    vertical_mm_per_pixel: float
    horizontal_ms_per_pixel: float | None = None

    def is_complete(self) -> bool:
        return self.roi.width > 0 and self.roi.height > 0 and self.vertical_mm_per_pixel > 0.0
