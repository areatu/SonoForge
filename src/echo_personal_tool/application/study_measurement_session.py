"""Session-scoped measurement accumulation for an open study folder."""

from __future__ import annotations

from dataclasses import dataclass, replace

from echo_personal_tool.domain.models import Contour, LinearMeasurement
from echo_personal_tool.domain.models.doppler import (
    DopplerIntervalMarker,
    DopplerMeasurementDTO,
    DopplerPeakMarker,
    DopplerTrace,
)
from echo_personal_tool.domain.models.doppler_roi import DopplerCalibrationState
from echo_personal_tool.domain.models.frame_panels import MmodeCalibrationState
from echo_personal_tool.domain.models.vessel_measurement import VesselMeasurement


def merge_doppler_peaks(
    existing: tuple[DopplerPeakMarker, ...],
    incoming: tuple[DopplerPeakMarker, ...],
) -> tuple[DopplerPeakMarker, ...]:
    by_label = {marker.label: marker for marker in existing}
    for marker in incoming:
        by_label[marker.label] = marker
    return tuple(by_label.values())


def merge_doppler_intervals(
    existing: tuple[DopplerIntervalMarker, ...],
    incoming: tuple[DopplerIntervalMarker, ...],
) -> tuple[DopplerIntervalMarker, ...]:
    by_label = {marker.label: marker for marker in existing}
    for marker in incoming:
        by_label[marker.label] = marker
    return tuple(by_label.values())


def merge_doppler_traces(
    existing: tuple[DopplerTrace, ...],
    incoming: tuple[DopplerTrace, ...],
) -> tuple[DopplerTrace, ...]:
    by_label = {trace.label: trace for trace in existing}
    for trace in incoming:
        by_label[trace.label] = trace
    return tuple(by_label.values())


def merge_doppler_dtos(
    existing: DopplerMeasurementDTO | None,
    incoming: DopplerMeasurementDTO,
) -> DopplerMeasurementDTO:
    if existing is None:
        return incoming
    return DopplerMeasurementDTO(
        peaks=merge_doppler_peaks(existing.peaks, incoming.peaks),
        intervals=merge_doppler_intervals(existing.intervals, incoming.intervals),
        traces=merge_doppler_traces(existing.traces, incoming.traces),
    )


def aggregate_doppler_by_instance(
    by_instance: dict[str, DopplerMeasurementDTO],
) -> DopplerMeasurementDTO | None:
    aggregated: DopplerMeasurementDTO | None = None
    for dto in by_instance.values():
        aggregated = merge_doppler_dtos(aggregated, dto)
    return aggregated


def contour_key(contour: Contour) -> tuple[str, str, str, str]:
    """Stable identity for LV/LA contours within a study session."""
    phase_key = contour.phase
    if contour.chamber.upper() in {"AREA", "VOL"} and contour.measurement_label:
        phase_key = contour.measurement_label
    return (
        contour.sop_instance_uid or "",
        contour.chamber,
        contour.view,
        phase_key,
    )


def contours_for_instance(
    contours: tuple[Contour, ...],
    instance_uid: str,
) -> tuple[Contour, ...]:
    """Return contours scoped to a single DICOM/clip instance."""
    return tuple(contour for contour in contours if contour.sop_instance_uid == instance_uid)


def merge_contours(
    existing: tuple[Contour, ...],
    incoming: tuple[Contour, ...],
) -> tuple[Contour, ...]:
    """Replace contours by instance/chamber/view/phase; ignore empty incoming."""
    if not incoming:
        return existing
    by_key = {contour_key(contour): contour for contour in existing}
    for contour in incoming:
        by_key[contour_key(contour)] = contour
    return tuple(by_key.values())


def merge_linear_measurements(
    existing: tuple[LinearMeasurement, ...],
    incoming: tuple[LinearMeasurement, ...],
) -> tuple[LinearMeasurement, ...]:
    """Replace linear measurements by label, frame, and instance; clear when incoming is empty."""
    if not incoming:
        return ()
    by_key: dict[tuple[str, int, str], LinearMeasurement] = {}
    for measurement in existing:
        frame_key = measurement.frame_index if measurement.frame_index is not None else -1
        by_key[(measurement.label, frame_key, measurement.sop_instance_uid)] = measurement
    for measurement in incoming:
        frame_key = measurement.frame_index if measurement.frame_index is not None else -1
        by_key[(measurement.label, frame_key, measurement.sop_instance_uid)] = measurement
    return tuple(by_key.values())


def linear_measurements_for_instance(
    measurements: tuple[LinearMeasurement, ...],
    sop_instance_uid: str,
) -> tuple[LinearMeasurement, ...]:
    """Return only measurements belonging to the given instance."""
    return tuple(m for m in measurements if m.sop_instance_uid == sop_instance_uid)


def merge_vessel_measurements(
    existing: tuple[VesselMeasurement, ...],
    incoming: tuple[VesselMeasurement, ...],
) -> tuple[VesselMeasurement, ...]:
    """Replace vessel measurements by instance and frame; clear when incoming is empty."""
    if not incoming:
        return ()
    by_key: dict[tuple[str, int], VesselMeasurement] = {}
    for measurement in existing:
        by_key[(measurement.sop_instance_uid, measurement.frame_index)] = measurement
    for measurement in incoming:
        by_key[(measurement.sop_instance_uid, measurement.frame_index)] = measurement
    return tuple(by_key.values())


def vessel_measurements_for_instance(
    measurements: tuple[VesselMeasurement, ...],
    sop_instance_uid: str,
) -> tuple[VesselMeasurement, ...]:
    """Return only vessel measurements belonging to the given instance."""
    return tuple(m for m in measurements if m.sop_instance_uid == sop_instance_uid)


@dataclass(frozen=True)
class StudyMeasurementData:
    contours: tuple[Contour, ...] = ()
    linear_measurements: tuple[LinearMeasurement, ...] = ()
    doppler_by_instance: tuple[tuple[str, DopplerMeasurementDTO], ...] = ()
    doppler_by_instance_frame: tuple[tuple[str, int, DopplerMeasurementDTO], ...] = ()
    doppler_calibration_by_instance: tuple[tuple[str, DopplerCalibrationState], ...] = ()
    doppler_calibration_by_instance_frame: tuple[tuple[str, int, DopplerCalibrationState], ...] = ()
    mmode_calibration_by_instance: tuple[tuple[str, MmodeCalibrationState], ...] = ()
    cine_segment_roi_by_instance: tuple[tuple[str, tuple[float, float, float, float]], ...] = ()
    manual_pixel_spacing: tuple[float, float] | None = None
    height_cm: float | None = None
    weight_kg: float | None = None
    mmode_time_per_pixel_ms: float | None = None
    vessel_measurements: tuple[VesselMeasurement, ...] = ()

    @property
    def doppler_measurement(self) -> DopplerMeasurementDTO | None:
        return aggregate_doppler_by_instance(dict(self.doppler_by_instance))

    @property
    def all_doppler_dto(self) -> DopplerMeasurementDTO | None:
        """Aggregate doppler data across all instances and frames in the study."""
        aggregated = aggregate_doppler_by_instance(dict(self.doppler_by_instance))
        for _uid, _frame, dto in self.doppler_by_instance_frame:
            aggregated = merge_doppler_dtos(aggregated, dto)
        return aggregated


class StudyMeasurementSessionStore:
    """Accumulates raw measurement inputs per study until the app session ends."""

    def __init__(self) -> None:
        self._studies: dict[str, StudyMeasurementData] = {}

    def clear(self) -> None:
        self._studies.clear()

    def __contains__(self, study_uid: str) -> bool:
        return study_uid in self._studies

    def get(self, study_uid: str) -> StudyMeasurementData:
        return self._studies.setdefault(study_uid, StudyMeasurementData())

    def merge_contours(self, study_uid: str, incoming: tuple[Contour, ...]) -> None:
        data = self.get(study_uid)
        self._studies[study_uid] = replace(
            data,
            contours=merge_contours(data.contours, incoming),
        )

    def merge_linear_measurements(
        self,
        study_uid: str,
        incoming: tuple[LinearMeasurement, ...],
    ) -> None:
        data = self.get(study_uid)
        self._studies[study_uid] = replace(
            data,
            linear_measurements=merge_linear_measurements(data.linear_measurements, incoming),
        )

    def merge_doppler_for_instance(
        self,
        study_uid: str,
        instance_uid: str,
        dto: DopplerMeasurementDTO,
    ) -> None:
        data = self.get(study_uid)
        current = dict(data.doppler_by_instance)
        existing = current.get(instance_uid)
        current[instance_uid] = merge_doppler_dtos(existing, dto)
        self._studies[study_uid] = replace(
            data,
            doppler_by_instance=tuple(current.items()),
        )

    def set_doppler_calibration(
        self,
        study_uid: str,
        instance_uid: str,
        calibration: DopplerCalibrationState | None,
    ) -> None:
        data = self.get(study_uid)
        current = dict(data.doppler_calibration_by_instance)
        if calibration is None:
            current.pop(instance_uid, None)
        else:
            current[instance_uid] = calibration
        self._studies[study_uid] = replace(
            data,
            doppler_calibration_by_instance=tuple(current.items()),
        )

    def get_doppler_calibration(
        self,
        study_uid: str,
        instance_uid: str,
    ) -> DopplerCalibrationState | None:
        data = self.get(study_uid)
        for uid, calibration in data.doppler_calibration_by_instance:
            if uid == instance_uid:
                return calibration
        return None

    def set_doppler_calibration_for_frame(
        self,
        study_uid: str,
        instance_uid: str,
        frame_index: int,
        calibration: DopplerCalibrationState | None,
    ) -> None:
        data = self.get(study_uid)
        current = {(uid, frame): stored for uid, frame, stored in data.doppler_calibration_by_instance_frame}
        key = (instance_uid, frame_index)
        if calibration is None:
            current.pop(key, None)
        else:
            current[key] = calibration
        self._studies[study_uid] = replace(
            data,
            doppler_calibration_by_instance_frame=tuple(
                (uid, frame, stored) for (uid, frame), stored in current.items()
            ),
        )

    def get_doppler_calibration_for_frame(
        self,
        study_uid: str,
        instance_uid: str,
        frame_index: int,
    ) -> DopplerCalibrationState | None:
        data = self.get(study_uid)
        for uid, frame, calibration in data.doppler_calibration_by_instance_frame:
            if uid == instance_uid and frame == frame_index:
                return calibration
        return None

    def get_doppler_for_instance(
        self,
        study_uid: str,
        instance_uid: str,
    ) -> DopplerMeasurementDTO | None:
        data = self.get(study_uid)
        for uid, dto in data.doppler_by_instance:
            if uid == instance_uid:
                return dto
        return None

    def merge_doppler_for_instance_frame(
        self,
        study_uid: str,
        instance_uid: str,
        frame_index: int,
        dto: DopplerMeasurementDTO,
    ) -> None:
        data = self.get(study_uid)
        current = {(uid, frame): stored for uid, frame, stored in data.doppler_by_instance_frame}
        key = (instance_uid, frame_index)
        current[key] = merge_doppler_dtos(current.get(key), dto)
        self._studies[study_uid] = replace(
            data,
            doppler_by_instance_frame=tuple((uid, frame, stored) for (uid, frame), stored in current.items()),
        )

    def get_doppler_for_instance_frame(
        self,
        study_uid: str,
        instance_uid: str,
        frame_index: int,
    ) -> DopplerMeasurementDTO | None:
        data = self.get(study_uid)
        for uid, frame, dto in data.doppler_by_instance_frame:
            if uid == instance_uid and frame == frame_index:
                return dto
        return None

    def set_mmode_time_per_pixel_ms(
        self,
        study_uid: str,
        value: float | None,
    ) -> None:
        data = self.get(study_uid)
        self._studies[study_uid] = replace(data, mmode_time_per_pixel_ms=value)

    def set_mmode_calibration(
        self,
        study_uid: str,
        instance_uid: str,
        calibration: MmodeCalibrationState | None,
    ) -> None:
        data = self.get(study_uid)
        current = dict(data.mmode_calibration_by_instance)
        if calibration is None:
            current.pop(instance_uid, None)
        else:
            current[instance_uid] = calibration
        self._studies[study_uid] = replace(
            data,
            mmode_calibration_by_instance=tuple(current.items()),
        )

    def get_mmode_calibration(
        self,
        study_uid: str,
        instance_uid: str,
    ) -> MmodeCalibrationState | None:
        data = self.get(study_uid)
        for uid, calibration in data.mmode_calibration_by_instance:
            if uid == instance_uid:
                return calibration
        return None

    def get_cine_segment_roi(
        self,
        study_uid: str,
        instance_uid: str,
    ) -> tuple[float, float, float, float] | None:
        data = self.get(study_uid)
        for uid, roi in data.cine_segment_roi_by_instance:
            if uid == instance_uid:
                return roi
        return None

    def set_cine_segment_roi(
        self,
        study_uid: str,
        instance_uid: str,
        roi_xyxy: tuple[float, float, float, float] | None,
    ) -> None:
        data = self.get(study_uid)
        current = dict(data.cine_segment_roi_by_instance)
        if roi_xyxy is None:
            current.pop(instance_uid, None)
        else:
            current[instance_uid] = roi_xyxy
        self._studies[study_uid] = replace(
            data,
            cine_segment_roi_by_instance=tuple(current.items()),
        )

    def set_doppler_measurement(
        self,
        study_uid: str,
        dto: DopplerMeasurementDTO | None,
    ) -> None:
        """Replace all Doppler data (legacy); prefer merge_doppler_for_instance."""
        data = self.get(study_uid)
        if dto is None:
            self._studies[study_uid] = replace(data, doppler_by_instance=())
            return
        self._studies[study_uid] = replace(
            data,
            doppler_by_instance=(("__legacy__", dto),),
        )

    def set_manual_pixel_spacing(
        self,
        study_uid: str,
        spacing: tuple[float, float] | None,
    ) -> None:
        data = self.get(study_uid)
        self._studies[study_uid] = replace(data, manual_pixel_spacing=spacing)

    def set_patient_metrics(
        self,
        study_uid: str,
        height_cm: float | None,
        weight_kg: float | None,
    ) -> None:
        data = self.get(study_uid)
        self._studies[study_uid] = replace(
            data,
            height_cm=height_cm,
            weight_kg=weight_kg,
        )

    def merge_vessel_measurements(
        self,
        study_uid: str,
        incoming: tuple[VesselMeasurement, ...],
    ) -> None:
        data = self.get(study_uid)
        self._studies[study_uid] = replace(
            data,
            vessel_measurements=merge_vessel_measurements(data.vessel_measurements, incoming),
        )

    def reset_measurements(self, study_uid: str) -> None:
        """Clear contours, linear calipers, Doppler, and manual calibration for a study."""
        data = self.get(study_uid)
        self._studies[study_uid] = StudyMeasurementData(
            height_cm=data.height_cm,
            weight_kg=data.weight_kg,
        )
