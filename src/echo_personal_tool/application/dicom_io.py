"""Qt-free application API for reading DICOM data needed by presentation.

The UI can request metadata, tag rows, calibration and preview frames without
owning the pydicom/session adapters. Infrastructure imports stay lazy so an
application import does not initialize the DICOM decode stack.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from echo_personal_tool.domain.models.doppler_roi import DopplerCalibrationState, DopplerKind
from echo_personal_tool.domain.models.ecg import EcgWaveform
from echo_personal_tool.domain.models.frame_panels import FramePanelLayout
from echo_personal_tool.domain.models.metadata import PatientDemographics

if TYPE_CHECKING:
    import numpy as np

    from echo_personal_tool.domain.models.properties_snapshot import PropertiesSnapshot


class DicomTagRow(Protocol):
    """Application-facing projection of a DICOM tag for inspector widgets."""

    tag_hex: str
    keyword: str
    vr: str
    description: str
    value: str


class SamsungTickCalibration(Protocol):
    """Read-only calibration fields needed by Doppler presentation."""

    k_constant: float


def read_patient_demographics(path: Path) -> PatientDemographics:
    """Read patient demographics from a DICOM header, without loading pixels."""
    from echo_personal_tool.infrastructure.dicom_metadata_mapper import (
        read_patient_demographics as read_metadata,
    )

    return read_metadata(path)


def read_ecg_waveform(path: Path | str) -> EcgWaveform | None:
    """Read the ECG waveform embedded in one DICOM instance, if present."""
    from echo_personal_tool.infrastructure.dicom_session import read_ecg_waveform as read_waveform

    return cast(EcgWaveform | None, read_waveform(path))


def read_all_dicom_tag_rows(path: Path, *, filter_phi: bool = False) -> list[DicomTagRow]:
    """Return the display-safe tag projection used by the inspector widget."""
    from echo_personal_tool.infrastructure.dicom_tag_inspector import (
        read_all_dicom_tag_rows as read_rows,
    )

    return cast(list[DicomTagRow], read_rows(path, filter_phi=filter_phi))


def read_interesting_dicom_tag_rows(path: Path, tag_specs: tuple[str, ...]) -> list[DicomTagRow]:
    """Read the selected DICOM tags shown in the viewer overlay."""
    from echo_personal_tool.infrastructure.dicom_tag_inspector import (
        read_interesting_dicom_tag_rows as read_rows,
    )

    return cast(list[DicomTagRow], read_rows(path, tag_specs))


def try_parse_dicom_doppler_calibration(
    path: Path,
    *,
    kind: DopplerKind = DopplerKind.SPECTRAL,
    frame: object | None = None,
) -> DopplerCalibrationState | None:
    """Resolve Doppler axes from a DICOM header and optional decoded frame."""
    from echo_personal_tool.infrastructure.dicom_doppler_calibration import (
        try_parse_from_path,
    )

    return try_parse_from_path(path, kind=kind, frame=frame)


def try_parse_dicom_frame_panels(path: Path) -> FramePanelLayout | None:
    """Read panel geometry from a DICOM header."""
    from echo_personal_tool.infrastructure.dicom_frame_panels import (
        try_parse_from_path,
    )

    return try_parse_from_path(path)


def load_samsung_tick_calibration() -> SamsungTickCalibration | None:
    """Load the stored Samsung tick calibration for Doppler time-scale display."""
    from echo_personal_tool.infrastructure.samsung_calibration_builder import (
        load_calibration,
    )

    return cast(SamsungTickCalibration | None, load_calibration())


def load_dicom_preview_frame(path: Path) -> np.ndarray | None:
    """Decode a detached first-frame copy for the de-identification preview."""
    import numpy as np

    from echo_personal_tool.infrastructure.dicom_session import get_dicom_session

    try:
        session = get_dicom_session(path)
        session.open(path)
        return np.array(session.decode_first_frame(), copy=True)
    except Exception:  # noqa: BLE001 - a preview must never break the export
        return None


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
    """Application-facing extraction of a clinical summary from a DICOM header.

    Presentation must not reach into ``infrastructure.properties_extractor``
    directly; this facade is the single application entry point.
    """
    from echo_personal_tool.infrastructure.properties_extractor import (
        extract_properties_snapshot as _extract,
    )

    return _extract(
        path,
        depth_ok=depth_ok,
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
    )


def spectral_doppler_mode(snapshot: PropertiesSnapshot) -> str | None:
    """Application-facing Doppler mode resolution from a properties snapshot.

    Presentation must not reach into ``infrastructure.properties_extractor``
    directly; this facade is the single application entry point.
    """
    from echo_personal_tool.infrastructure.properties_extractor import (
        spectral_doppler_mode as _spectral_doppler_mode,
    )

    return _spectral_doppler_mode(snapshot)


__all__ = [
    "DicomTagRow",
    "SamsungTickCalibration",
    "extract_properties_snapshot",
    "load_dicom_preview_frame",
    "load_samsung_tick_calibration",
    "read_all_dicom_tag_rows",
    "read_ecg_waveform",
    "read_interesting_dicom_tag_rows",
    "read_patient_demographics",
    "spectral_doppler_mode",
    "try_parse_dicom_doppler_calibration",
    "try_parse_dicom_frame_panels",
]
