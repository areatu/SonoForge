"""Domain DTO for Properties panel clinical summary."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RegionSummary:
    """Compact representation of one ultrasound region item."""

    index: int
    spatial_format: str  # "B-mode" | "M-mode" | "Spectral"
    data_type: str | None  # "PW" | "CW" | "TDI" | None
    bounds: tuple[int, int, int, int]  # x_min, x_max, y_min, y_max
    delta_x: float | None
    delta_y: float | None
    units_x: int | None
    units_y: int | None
    ref_y0: int | None


@dataclass(frozen=True)
class PropertiesSnapshot:
    """Clinical summary for calibration and measurements."""

    # Identity / study
    modality: str
    series_description: str
    manufacturer: str | None
    manufacturer_model: str | None
    software_versions: str | None
    image_type: tuple[str, ...] | None
    number_of_frames: int
    media_format: str

    # Timing
    frame_time_ms: float | None
    cine_rate_fps: float | None
    frame_time_vector_present: bool
    heart_rate_bpm: float | None

    # Spatial (B-mode)
    pixel_spacing_mm: tuple[float, float] | None
    pixel_spacing_source: str | None
    transducer_frequency_mhz: float | None

    # Ultrasound regions summary
    regions: tuple[RegionSummary, ...]

    # Calibration status (runtime)
    depth_calibrated: bool
    mmode_calibrated: bool
    mmode_has_time_scale: bool
    doppler_calibrated: bool
    doppler_has_time_from_dicom: bool
    doppler_has_velocity_from_dicom: bool
    doppler_partial: bool

    # Patient metrics
    patient_height_m: float | None
    patient_weight_kg: float | None
    bsa_m2: float | None

    # M-mode calibration values (with defaults for backward compat)
    mmode_vertical_mm_per_pixel: float | None = None
    mmode_horizontal_ms_per_pixel: float | None = None
    mmode_has_depth_from_dicom: bool = False
    mmode_has_time_from_dicom: bool = False

    @classmethod
    def default(
        cls,
        *,
        depth_ok: bool = False,
        mmode_calibrated: bool = False,
        mmode_has_time_scale: bool = False,
        mmode_vertical_mm_per_pixel: float | None = None,
        mmode_horizontal_ms_per_pixel: float | None = None,
        mmode_has_depth_from_dicom: bool = False,
        mmode_has_time_from_dicom: bool = False,
        doppler_calibrated: bool = False,
        doppler_has_time_from_dicom: bool = False,
        doppler_has_velocity_from_dicom: bool = False,
        doppler_partial: bool = False,
    ) -> PropertiesSnapshot:
        return cls(
            modality="OT",
            series_description="",
            manufacturer=None,
            manufacturer_model=None,
            software_versions=None,
            image_type=None,
            number_of_frames=1,
            media_format="dicom",
            frame_time_ms=None,
            cine_rate_fps=None,
            frame_time_vector_present=False,
            heart_rate_bpm=None,
            pixel_spacing_mm=None,
            pixel_spacing_source=None,
            transducer_frequency_mhz=None,
            regions=(),
            depth_calibrated=depth_ok,
            mmode_calibrated=mmode_calibrated,
            mmode_has_time_scale=mmode_has_time_scale,
            mmode_vertical_mm_per_pixel=mmode_vertical_mm_per_pixel,
            mmode_horizontal_ms_per_pixel=mmode_horizontal_ms_per_pixel,
            mmode_has_depth_from_dicom=mmode_has_depth_from_dicom,
            mmode_has_time_from_dicom=mmode_has_time_from_dicom,
            doppler_calibrated=doppler_calibrated,
            doppler_has_time_from_dicom=doppler_has_time_from_dicom,
            doppler_has_velocity_from_dicom=doppler_has_velocity_from_dicom,
            doppler_partial=doppler_partial,
            patient_height_m=None,
            patient_weight_kg=None,
            bsa_m2=None,
        )
