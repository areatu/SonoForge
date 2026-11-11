"""Single definition point for non-measurement UI/technical display formats (issue 482).

Clinical echo/ultrasound measurement values must format exclusively through
:func:`echo_personal_tool.domain.measurement_catalog.format_measurement`.
Technical playback, calibration, patient-header, and storage figures share the
helpers in this module instead of scattering ad-hoc ``:.Nf`` literals across
presentation widgets.
"""

from __future__ import annotations


def format_fps(fps: float) -> str:
    """Playback or cine frame rate in frames per second (``60.0``)."""
    return f"{max(0.0, float(fps)):.1f}"


def format_frame_time_ms(frame_time_ms: float) -> str:
    """Inter-frame interval in milliseconds (``33.3``)."""
    return f"{float(frame_time_ms):.1f}"


def format_frequency_mhz(frequency_mhz: float) -> str:
    """Transducer frequency in MHz (``2.5``)."""
    return f"{float(frequency_mhz):.1f}"


def format_pixel_spacing_mm(spacing_mm: float) -> str:
    """Single-axis 2D DICOM pixel spacing in millimetres (``0.250``)."""
    return f"{float(spacing_mm):.3f}"


def format_mm_per_px(mm_per_px: float) -> str:
    """M-mode depth calibration in mm/px (``0.45``)."""
    return f"{float(mm_per_px):.2f}"


def format_ms_per_px(ms_per_px: float) -> str:
    """M-mode sweep calibration in ms/px (``4.00``)."""
    return f"{float(ms_per_px):.2f}"


def format_region_delta(delta: float) -> str:
    """Raw DICOM SequenceOfUltrasoundRegions PhysicalDeltaX/Y (``0.0254``)."""
    return f"{float(delta):.4f}"


def format_patient_height_cm(height_cm: float) -> str:
    """Patient height or integer body metric (``175``)."""
    return f"{float(height_cm):.0f}"


def format_patient_weight_kg(weight_kg: float) -> str:
    """Patient weight in kilograms (``72.5``)."""
    return f"{float(weight_kg):.1f}"


def format_bmi(bmi: float) -> str:
    """Body-mass index in kg/m² (``23.7``)."""
    return f"{float(bmi):.1f}"


def format_zoom_factor(zoom: float) -> str:
    """Magnifier zoom factor (``2.0``)."""
    return f"{float(zoom):.1f}"


def format_scale_factor(scale: float) -> str:
    """Viewport-to-frame scale factor (``1.25``)."""
    return f"{float(scale):.2f}"


def format_dpr(dpr: float) -> str:
    """Display device-pixel ratio (``2.0``)."""
    return f"{float(dpr):.1f}"


def format_playback_seconds(seconds: float, *, fine: bool = False) -> str:
    """Clip duration or multiview position in seconds."""
    return f"{float(seconds):.2f}" if fine else f"{float(seconds):.1f}"


def format_sync_ratio(ratio: float) -> str:
    """Multiview cardiac-cycle stretch factor (``1.05``)."""
    return f"{float(ratio):.2f}"


def format_confidence_score(confidence: float) -> str:
    """De-identification / classifier confidence in ``[0, 1]`` (``0.95``)."""
    return f"{float(confidence):.2f}"


def format_confidence_pct(confidence: float) -> str:
    """Confidence in ``[0, 1]`` formatted as whole percent with ``%`` (``95%``)."""
    return f"{float(confidence):.0%}"


def format_whole_pct(percent: float) -> str:
    """Integer diagnostic/QC percentage without unit (``92``)."""
    return f"{float(percent):.0f}"


def format_storage_unit_value(value: float) -> str:
    """Human-readable KB/MB storage size figure (``12.4``)."""
    return f"{float(value):.1f}"


def format_storage_bytes(size_bytes: int) -> str:
    """Human-readable byte count with binary IEC unit (``0 B``, ``12.4 MiB``)."""
    size = float(max(0, size_bytes))
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024.0 or unit == "TiB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024.0
    return "0 B"


def format_pixel_extent(pixels: float, *, whole: bool = False) -> str:
    """Uncalibrated pixel length or area figure."""
    return f"{float(pixels):.0f}" if whole else f"{float(pixels):.1f}"
