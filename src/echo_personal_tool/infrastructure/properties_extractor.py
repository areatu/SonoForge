"""Extract PropertiesSnapshot from DICOM header."""

from __future__ import annotations

from pathlib import Path

import pydicom

from echo_personal_tool.domain.models.properties_snapshot import (
    PropertiesSnapshot,
    RegionSummary,
)
from echo_personal_tool.domain.services.pixel_spacing_resolver import resolve_pixel_spacing
from echo_personal_tool.domain.services.ultrasound_region_physics import (
    is_mmode_region,
    is_spectral_doppler_region,
    region_physical_deltas,
)

_SPATIAL_FORMAT_MAP = {
    1: "B-mode",
    2: "M-mode",
    3: "Spectral",
}

_DOPPLER_DATA_TYPE_MAP = {
    3: "PW",
    4: "CW",
    0x10: "TDI",
    0x11: "TDI_PW",
}


def _safe_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_str(value) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def _frame_time_ms(dataset) -> float | None:
    frame_time = dataset.get("FrameTime")
    if frame_time is not None:
        return float(frame_time)
    cine_rate = dataset.get("CineRate")
    if cine_rate:
        rate = float(cine_rate)
        if rate > 0:
            return 1000.0 / rate
    return None


def _cine_rate_fps(dataset) -> float | None:
    cine_rate = dataset.get("CineRate")
    if cine_rate is not None:
        rate = float(cine_rate)
        if rate > 0:
            return rate
    frame_time = dataset.get("FrameTime")
    if frame_time is not None:
        ft = float(frame_time)
        if ft > 0:
            return 1000.0 / ft
    return None


def _build_region_summary(index: int, region) -> RegionSummary:
    spatial_format_code = int(region.get("RegionSpatialFormat", 0) or 0)
    data_type_code = int(region.get("RegionDataType", 0) or 0)

    spatial_format = _SPATIAL_FORMAT_MAP.get(spatial_format_code, "Unknown")
    if is_spectral_doppler_region(region):
        spatial_format = "Spectral"
    elif is_mmode_region(region):
        spatial_format = "M-mode"

    data_type = _DOPPLER_DATA_TYPE_MAP.get(data_type_code)

    x_min = int(region.get("RegionLocationMinX0", 0) or 0)
    x_max = int(region.get("RegionLocationMaxX1", 0) or 0)
    y_min = int(region.get("RegionLocationMinY0", 0) or 0)
    y_max = int(region.get("RegionLocationMaxY1", 0) or 0)

    delta_x, delta_y, units_x, units_y = region_physical_deltas(region)

    ref_y0 = region.get("ReferencePixelY0")
    ref_y0_int = int(ref_y0) if ref_y0 is not None else None

    return RegionSummary(
        index=index,
        spatial_format=spatial_format,
        data_type=data_type,
        bounds=(x_min, x_max, y_min, y_max),
        delta_x=delta_x,
        delta_y=delta_y,
        units_x=units_x,
        units_y=units_y,
        ref_y0=ref_y0_int,
    )


def _bsa_du_bois(height_m: float | None, weight_kg: float | None) -> float | None:
    """DuBois & DuBois BSA formula: 0.007184 * H^0.725 * W^0.425."""
    if height_m is None or weight_kg is None:
        return None
    if height_m <= 0 or weight_kg <= 0:
        return None
    return 0.007184 * (height_m * 100) ** 0.725 * weight_kg**0.425


def extract_properties_snapshot(
    path: Path,
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
    """Extract clinical summary from DICOM header."""
    dataset = pydicom.dcmread(path, stop_before_pixels=True, force=True)

    # Identity
    modality = str(dataset.get("Modality", "OT") or "OT")
    series_description = str(dataset.get("SeriesDescription", "") or "").strip()
    manufacturer = _safe_str(dataset.get("Manufacturer"))
    manufacturer_model = _safe_str(dataset.get("ManufacturerModelName"))
    software_versions = _safe_str(dataset.get("SoftwareVersions"))

    image_type_raw = dataset.get("ImageType")
    image_type = None
    if image_type_raw is not None:
        try:
            image_type = tuple(str(v) for v in image_type_raw)
        except TypeError:
            pass

    number_of_frames = int(dataset.get("NumberOfFrames", 1) or 1)

    # Timing
    frame_time_ms = _frame_time_ms(dataset)
    cine_rate_fps = _cine_rate_fps(dataset)
    frame_time_vector = dataset.get("FrameTimeVector")
    frame_time_vector_present = frame_time_vector is not None and len(frame_time_vector) > 0
    heart_rate_bpm = _safe_float(dataset.get("HeartRate"))

    # Spatial
    resolution = resolve_pixel_spacing(dataset)
    pixel_spacing_mm = resolution.spacing if resolution else None
    pixel_spacing_source = resolution.source if resolution else None
    transducer_frequency_mhz = _safe_float(dataset.get("TransducerFrequency"))

    # Regions
    regions_raw = dataset.get("SequenceOfUltrasoundRegions")
    regions: list[RegionSummary] = []
    if regions_raw:
        for i, region in enumerate(regions_raw):
            regions.append(_build_region_summary(i, region))

    # Patient
    patient_height_m = _safe_float(dataset.get("PatientSize"))
    patient_weight_kg = _safe_float(dataset.get("PatientWeight"))
    bsa_m2 = _bsa_du_bois(patient_height_m, patient_weight_kg)

    return PropertiesSnapshot(
        modality=modality,
        series_description=series_description,
        manufacturer=manufacturer,
        manufacturer_model=manufacturer_model,
        software_versions=software_versions,
        image_type=image_type,
        number_of_frames=number_of_frames,
        media_format="dicom",
        frame_time_ms=frame_time_ms,
        cine_rate_fps=cine_rate_fps,
        frame_time_vector_present=frame_time_vector_present,
        heart_rate_bpm=heart_rate_bpm,
        pixel_spacing_mm=pixel_spacing_mm,
        pixel_spacing_source=pixel_spacing_source,
        transducer_frequency_mhz=transducer_frequency_mhz,
        regions=tuple(regions),
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
        patient_height_m=patient_height_m,
        patient_weight_kg=patient_weight_kg,
        bsa_m2=bsa_m2,
    )
