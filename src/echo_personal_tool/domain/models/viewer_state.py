"""Pure domain snapshot of viewer playback state."""

from __future__ import annotations

from dataclasses import dataclass

from echo_personal_tool.domain.models.calibration import (
    CalibrationConfidence,
    CalibrationContext,
    CalibrationScope,
    CalibrationSelection,
    select_calibration,
)
from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.models.doppler import DopplerMeasurementDTO
from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
from echo_personal_tool.domain.models.metadata import InstanceMetadata


@dataclass(frozen=True)
class ViewerState:
    instance: InstanceMetadata | None
    current_frame_index: int
    total_frames: int
    frame_time_ms: float | None
    is_playing: bool
    doppler_measurement: DopplerMeasurementDTO | None = None
    contours: tuple[Contour, ...] = ()
    linear_measurements: tuple[LinearMeasurement, ...] = ()
    measurement_snapshot: MeasurementSnapshot | None = None
    decode_in_progress: bool = False
    manual_pixel_spacing: tuple[float, float] | None = None
    manual_calibration: CalibrationContext | None = None
    scroll_navigation: bool = False

    @property
    def effective_calibration(self) -> CalibrationContext | None:
        """The calibration the current frame can use without picking a region."""
        if self.manual_calibration is not None:
            return self.manual_calibration
        if self.manual_pixel_spacing is not None:
            try:
                return CalibrationContext(
                    spacing=self.manual_pixel_spacing,
                    source="manual",
                    scope=CalibrationScope.INSTANCE,
                    confidence=CalibrationConfidence.ASSUMED,
                    assumed_isotropic=True,
                )
            except ValueError:
                return None
        if self.instance is None:
            return None
        if self.instance.calibration is not None:
            return self.instance.calibration
        if self.instance.calibrations:
            selection = select_calibration(self.instance.calibrations, frame_index=self.current_frame_index)
            if selection.context is not None:
                return selection.context
            return None
        if self.instance.pixel_spacing is None:
            return None
        try:
            return CalibrationContext(
                spacing=self.instance.pixel_spacing,
                source=self.instance.pixel_spacing_source or "unknown",
                scope=CalibrationScope.INSTANCE,
                confidence=CalibrationConfidence.UNKNOWN,
            )
        except ValueError:
            return None

    @property
    def effective_pixel_spacing(self) -> tuple[float, float] | None:
        if self.manual_pixel_spacing is not None and self.manual_calibration is None:
            return self.manual_pixel_spacing
        calibration = self.effective_calibration
        return calibration.spacing if calibration is not None else None

    def calibration_for_geometry(
        self,
        bbox: tuple[float, float, float, float],
    ) -> CalibrationSelection:
        """Select by frame + measurement bbox; refuses a region-crossing line."""
        contexts = self.instance.calibrations if self.instance is not None else ()
        if self.manual_calibration is not None:
            return CalibrationSelection(context=self.manual_calibration)
        if not contexts and self.effective_calibration is not None:
            return CalibrationSelection(context=self.effective_calibration)
        return select_calibration(contexts, frame_index=self.current_frame_index, bbox=bbox)

    @property
    def calibration_reason(self) -> str:
        """Why no calibration applies without geometry (empty when available)."""
        if self.effective_calibration is not None:
            return ""
        contexts = self.instance.calibrations if self.instance is not None else ()
        return select_calibration(contexts, frame_index=self.current_frame_index).reason

    @property
    def calibration_revision(self) -> int:
        calibration = self.effective_calibration
        return calibration.revision if calibration is not None else 0

    @property
    def calibration_source_label(self) -> str | None:
        calibration = self.effective_calibration
        return calibration.source if calibration is not None else None

    @property
    def calibration_confidence(self) -> CalibrationConfidence:
        calibration = self.effective_calibration
        return calibration.confidence if calibration is not None else CalibrationConfidence.UNKNOWN

    @property
    def calibration_scope(self) -> CalibrationScope | None:
        calibration = self.effective_calibration
        return calibration.scope if calibration is not None else None

    @property
    def pixel_spacing_source_label(self) -> str | None:
        if self.manual_pixel_spacing is not None and self.manual_calibration is None:
            return "manual"
        return self.calibration_source_label or (self.instance.pixel_spacing_source if self.instance else None)

    @property
    def fps(self) -> float:
        if self.frame_time_ms is None or self.frame_time_ms <= 0:
            return 0.0
        return 1000.0 / self.frame_time_ms
