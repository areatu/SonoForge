"""Session-scoped measurement accumulation for an open study folder."""

from __future__ import annotations

import math
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, replace

from echo_personal_tool.domain.doppler_catalog import (
    canonical_interval_label,
    canonical_peak_label,
    canonical_trace_label,
)
from echo_personal_tool.domain.models import Contour, LinearMeasurement
from echo_personal_tool.domain.models.doppler import (
    DopplerIntervalMarker,
    DopplerMeasurementDTO,
    DopplerPeakMarker,
    DopplerTrace,
)
from echo_personal_tool.domain.models.doppler_roi import DopplerCalibrationState
from echo_personal_tool.domain.models.frame_panels import MmodeCalibrationState
from echo_personal_tool.domain.models.measurements import StrainReport
from echo_personal_tool.domain.models.vessel_measurement import VesselMeasurement
from echo_personal_tool.domain.services.contour_geometry import polygon_area_mm2
from echo_personal_tool.domain.services.doppler_repeats import merge_newest_wins


def merge_doppler_peaks(
    existing: tuple[DopplerPeakMarker, ...],
    incoming: tuple[DopplerPeakMarker, ...],
) -> tuple[DopplerPeakMarker, ...]:
    """Merge peak measurements, keeping repeated measurements of one parameter.

    A marker with an identity (``measurement_id``) is replaced in place when
    the same identity arrives again, and appended otherwise — this is how
    several beats of the same parameter coexist (D-23) while an edited marker
    stays one measurement.  Legacy markers without an identity keep the old
    replace-by-label behavior.
    """
    return merge_newest_wins(
        existing,
        incoming,
        identity_of=lambda marker: (canonical_peak_label(marker.label), marker.measurement_id),
        label_of=lambda marker: canonical_peak_label(marker.label),
    )


def merge_doppler_intervals(
    existing: tuple[DopplerIntervalMarker, ...],
    incoming: tuple[DopplerIntervalMarker, ...],
) -> tuple[DopplerIntervalMarker, ...]:
    return merge_newest_wins(
        existing,
        incoming,
        identity_of=lambda marker: (canonical_interval_label(marker.label), marker.measurement_id),
        label_of=lambda marker: canonical_interval_label(marker.label),
    )


def merge_doppler_traces(
    existing: tuple[DopplerTrace, ...],
    incoming: tuple[DopplerTrace, ...],
) -> tuple[DopplerTrace, ...]:
    return merge_newest_wins(
        existing,
        incoming,
        identity_of=lambda trace: (canonical_trace_label(trace.label), trace.measurement_id),
        label_of=lambda trace: canonical_trace_label(trace.label),
    )


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


def is_planimeter_contour(contour: Contour) -> bool:
    """True for the generic area/volume planimeter polygons (Площадь1, Объем1, …)."""
    return contour.chamber.upper() in {"AREA", "VOL"}


def merge_contours(
    existing: tuple[Contour, ...],
    incoming: tuple[Contour, ...],
    *,
    authoritative_instance_uid: str | None = None,
) -> tuple[Contour, ...]:
    """Replace contours by instance/chamber/view/phase; ignore empty incoming.

    ``authoritative_instance_uid`` marks a report that lists *all* planimeter
    contours of one clip (the viewer only ever holds the contours of the clip it
    shows). A planimeter polygon of that clip missing from such a report was
    deleted by the operator, so it is dropped here instead of resurfacing the
    next time the clip is opened. LV/LA/RV contours keep merge-only semantics:
    they are re-drawn and refined constantly, and an empty intermediate report
    must not throw an accepted ED/ES contour away.
    """
    if not incoming:
        if authoritative_instance_uid is not None:
            return tuple(
                c
                for c in existing
                if not (c.sop_instance_uid == authoritative_instance_uid and is_planimeter_contour(c))
            )
        return existing
    by_key = {contour_key(contour): contour for contour in existing}
    for contour in incoming:
        by_key[contour_key(contour)] = contour
    merged = tuple(by_key.values())
    if authoritative_instance_uid is None:
        return merged
    kept_planimeter_keys = {contour_key(contour) for contour in incoming if is_planimeter_contour(contour)}
    return tuple(
        contour
        for contour in merged
        if not (
            contour.sop_instance_uid == authoritative_instance_uid
            and is_planimeter_contour(contour)
            and contour_key(contour) not in kept_planimeter_keys
        )
    )


def merge_linear_measurements(
    existing: tuple[LinearMeasurement, ...],
    incoming: tuple[LinearMeasurement, ...],
) -> tuple[LinearMeasurement, ...]:
    """Replace linear measurements by label, frame, and instance.

    An empty ``incoming`` means "this clip has nothing (yet)" — it must never
    wipe the measurements already taken on the other clips of the study, which
    is what the report is built from. Clearing is explicit
    (:meth:`StudyMeasurementSessionStore.reset_measurements`).
    """
    if not incoming:
        return existing
    by_key: dict[tuple[str, int, str], LinearMeasurement] = {}
    for measurement in existing:
        frame_key = measurement.frame_index if measurement.frame_index is not None else -1
        by_key[(measurement.label, frame_key, measurement.sop_instance_uid)] = measurement
    for measurement in incoming:
        frame_key = measurement.frame_index if measurement.frame_index is not None else -1
        by_key[(measurement.label, frame_key, measurement.sop_instance_uid)] = measurement
    return tuple(by_key.values())


def replace_linear_measurements_for_instance(
    existing: tuple[LinearMeasurement, ...],
    instance_uid: str,
    incoming: tuple[LinearMeasurement, ...],
) -> tuple[LinearMeasurement, ...]:
    """Authoritative update of one clip's calipers.

    The viewer holds exactly the calipers of the clip it shows, so its report is
    the truth for that clip: calipers it no longer lists were deleted and must
    disappear from the study too (otherwise they come back after a clip switch
    and stay in the report). Other clips are untouched.
    """
    kept = tuple(m for m in existing if m.sop_instance_uid != instance_uid)
    if not incoming:
        return kept
    by_key: dict[tuple[str, int, str], LinearMeasurement] = {
        (m.label, m.frame_index if m.frame_index is not None else -1, m.sop_instance_uid): m for m in kept
    }
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
    """Replace vessel measurements by instance and frame; keep existing on empty."""
    if not incoming:
        return existing
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
    manual_spacing_by_instance: tuple[tuple[str, tuple[float, float]], ...] = ()
    mmode_time_by_instance: tuple[tuple[str, float], ...] = ()
    height_source: str = "unset"
    weight_source: str = "unset"
    height_cm: float | None = None
    weight_kg: float | None = None
    mmode_time_per_pixel_ms: float | None = None
    vessel_measurements: tuple[VesselMeasurement, ...] = ()
    simpson_area_by_frame: tuple[tuple[str, str, int, float], ...] = ()
    #: Speckle-tracking result of the study (plan §5.3 п.6). Kept per study,
    #: not per instance: GLS_AV is an average over apical views that normally
    #: live in different clips of the same study.
    strain: StrainReport | None = None

    @property
    def has_measurements(self) -> bool:
        """User measurements, excluding automatic patient metadata/calibrations."""
        return bool(
            self.contours
            or self.linear_measurements
            or self.vessel_measurements
            or self.simpson_area_by_frame
            or self.strain is not None
            or any(dto.peaks or dto.intervals or dto.traces for _, dto in self.doppler_by_instance)
            or any(dto.peaks or dto.intervals or dto.traces for _, _, dto in self.doppler_by_instance_frame)
        )

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

    def __init__(self, on_change: Callable[[str, StudyMeasurementData], None] | None = None) -> None:
        self.on_change = on_change
        self._studies: dict[str, StudyMeasurementData] = {}

    def snapshot(self, study_uid: str) -> StudyMeasurementData:
        return deepcopy(self.get(study_uid))

    def restore(self, study_uid: str, data: StudyMeasurementData) -> None:
        """Hydrate without generating an autosave or mutating the supplied record."""
        self._studies[study_uid] = deepcopy(data)

    def activate_instance(self, study_uid: str, instance_uid: str) -> None:
        """Select per-clip calibration without copying or dirtying the whole study."""
        data = self.get(study_uid)
        self._studies[study_uid] = replace(
            data,
            manual_pixel_spacing=dict(data.manual_spacing_by_instance).get(instance_uid),
            mmode_time_per_pixel_ms=dict(data.mmode_time_by_instance).get(instance_uid),
        )

    def _set(self, study_uid: str, data: StudyMeasurementData) -> None:
        if self._studies.get(study_uid) == data:
            return
        self._studies[study_uid] = data
        if self.on_change is not None:
            self.on_change(study_uid, data)

    def set_instance_spacing(self, study_uid: str, instance_uid: str, spacing) -> None:
        data = self.get(study_uid)
        values = dict(data.manual_spacing_by_instance)
        if spacing is None:
            values.pop(instance_uid, None)
        else:
            values[instance_uid] = spacing
        self._set(
            study_uid, replace(data, manual_spacing_by_instance=tuple(values.items()), manual_pixel_spacing=spacing)
        )

    def set_instance_mmode_time(self, study_uid: str, instance_uid: str, value: float) -> None:
        data = self.get(study_uid)
        values = dict(data.mmode_time_by_instance)
        values[instance_uid] = value
        self._set(study_uid, replace(data, mmode_time_by_instance=tuple(values.items()), mmode_time_per_pixel_ms=value))

    def fill_dicom_metrics(self, study_uid: str, height_cm, weight_kg) -> None:
        data = self.get(study_uid)
        updates = {}
        for name, value in (("height", height_cm), ("weight", weight_kg)):
            field = "height_cm" if name == "height" else "weight_kg"
            if getattr(data, name + "_source") == "unset" and value is not None:
                limit = 300 if name == "height" else 700
                if math.isfinite(value) and 0 < value <= limit:
                    updates[field] = float(value)
                    updates[name + "_source"] = "dicom"
        if updates:
            self._set(study_uid, replace(data, **updates))

    def clear(self) -> None:
        self._studies.clear()

    def __contains__(self, study_uid: str) -> bool:
        return study_uid in self._studies

    def get(self, study_uid: str) -> StudyMeasurementData:
        return self._studies.setdefault(study_uid, StudyMeasurementData())

    def merge_contours(
        self,
        study_uid: str,
        incoming: tuple[Contour, ...],
        *,
        authoritative_instance_uid: str | None = None,
    ) -> None:
        data = self.get(study_uid)
        self._set(
            study_uid,
            replace(
                data,
                contours=merge_contours(
                    data.contours,
                    incoming,
                    authoritative_instance_uid=authoritative_instance_uid,
                ),
            ),
        )

    def merge_simpson_areas(
        self,
        study_uid: str,
        incoming: tuple[Contour, ...],
        pixel_spacing: tuple[float, float],
    ) -> None:
        """Store LV cavity area by instance/view/frame for phase fallback."""
        data = self.get(study_uid)
        current = {(uid, view, frame): area for uid, view, frame, area in data.simpson_area_by_frame}
        for contour in incoming:
            if contour.chamber.upper() != "LV" or contour.frame_index is None or len(contour.points) < 3:
                continue
            area = polygon_area_mm2(contour.closed_polygon_points(), pixel_spacing)
            if area > 0.0:
                key = (contour.sop_instance_uid or "", contour.view.upper(), contour.frame_index)
                current[key] = area
        values = tuple((*key, area) for key, area in sorted(current.items()))
        self._set(study_uid, replace(data, simpson_area_by_frame=values))

    def get_simpson_area_curve(
        self,
        study_uid: str,
        instance_uid: str,
        view: str,
    ) -> tuple[tuple[int, float], ...]:
        """Return frame-sorted Simpson cavity areas for one CINE/view."""
        target_view = view.upper()
        return tuple(
            (frame, area)
            for uid, stored_view, frame, area in self.get(study_uid).simpson_area_by_frame
            if uid == instance_uid and stored_view == target_view
        )

    def merge_linear_measurements(
        self,
        study_uid: str,
        incoming: tuple[LinearMeasurement, ...],
    ) -> None:
        data = self.get(study_uid)
        self._set(
            study_uid,
            replace(
                data,
                linear_measurements=merge_linear_measurements(data.linear_measurements, incoming),
            ),
        )

    def set_linear_measurements_for_instance(
        self,
        study_uid: str,
        instance_uid: str,
        incoming: tuple[LinearMeasurement, ...],
    ) -> None:
        """Store the authoritative caliper set of one clip (deletions included)."""
        data = self.get(study_uid)
        self._set(
            study_uid,
            replace(
                data,
                linear_measurements=replace_linear_measurements_for_instance(
                    data.linear_measurements,
                    instance_uid,
                    incoming,
                ),
            ),
        )

    def clear_instance_measurements(self, study_uid: str, instance_uid: str) -> None:
        """Drop every caliper of one clip (used by the on-image 'clear' action)."""
        self.set_linear_measurements_for_instance(study_uid, instance_uid, ())

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
        self._set(
            study_uid,
            replace(
                data,
                doppler_by_instance=tuple(current.items()),
            ),
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
        self._set(
            study_uid,
            replace(
                data,
                doppler_calibration_by_instance=tuple(current.items()),
            ),
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
        self._set(
            study_uid,
            replace(
                data,
                doppler_calibration_by_instance_frame=tuple(
                    (uid, frame, stored) for (uid, frame), stored in current.items()
                ),
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

    def set_doppler_for_instance_frame(self, study_uid, instance_uid, frame_index, dto) -> None:
        """Authoritative editor update, including deletion of the last marker.

        The legacy per-instance entry for this instance is dropped on purpose: the
        frame records below are aggregated together with ``doppler_by_instance`` in
        ``all_doppler_dto``, so keeping it would count the same markers twice (and
        deleting the last marker would not clear this instance from the aggregate).
        Entries of every other instance stay untouched, so their contribution to the
        study-wide aggregate survives this update.
        """
        data = self.get(study_uid)
        entries = tuple(
            item for item in data.doppler_by_instance_frame if (item[0], item[1]) != (instance_uid, frame_index)
        )
        self._set(
            study_uid,
            replace(
                data,
                doppler_by_instance=tuple(item for item in data.doppler_by_instance if item[0] != instance_uid),
                doppler_by_instance_frame=entries + ((instance_uid, frame_index, dto),),
            ),
        )

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
        self._set(
            study_uid,
            replace(
                data,
                doppler_by_instance_frame=tuple((uid, frame, stored) for (uid, frame), stored in current.items()),
            ),
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
        self._set(study_uid, replace(data, mmode_time_per_pixel_ms=value))

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
        self._set(
            study_uid,
            replace(
                data,
                mmode_calibration_by_instance=tuple(current.items()),
            ),
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
        self._set(
            study_uid,
            replace(
                data,
                cine_segment_roi_by_instance=tuple(current.items()),
            ),
        )

    def set_doppler_measurement(
        self,
        study_uid: str,
        dto: DopplerMeasurementDTO | None,
    ) -> None:
        """Replace all Doppler data (legacy); prefer merge_doppler_for_instance."""
        data = self.get(study_uid)
        if dto is None:
            self._set(study_uid, replace(data, doppler_by_instance=()))
            return
        self._set(
            study_uid,
            replace(
                data,
                doppler_by_instance=(("__legacy__", dto),),
            ),
        )

    def set_manual_pixel_spacing(
        self,
        study_uid: str,
        spacing: tuple[float, float] | None,
    ) -> None:
        data = self.get(study_uid)
        self._set(study_uid, replace(data, manual_pixel_spacing=spacing))

    def set_patient_metrics(
        self,
        study_uid: str,
        height_cm: float | None,
        weight_kg: float | None,
    ) -> None:
        for value, limit in ((height_cm, 300), (weight_kg, 700)):
            if value is not None and (not math.isfinite(value) or not 0 < value <= limit):
                raise ValueError("Patient metric out of range")
        data = self.get(study_uid)
        self._set(
            study_uid,
            replace(
                data,
                height_cm=height_cm,
                weight_kg=weight_kg,
                height_source="manual" if height_cm is not None else "cleared",
                weight_source="manual" if weight_kg is not None else "cleared",
            ),
        )

    def set_strain(self, study_uid: str, report: StrainReport | None) -> None:
        """Store the study's speckle-tracking result for the protocol (§5.3 п.6).

        The newest analysis of the study wins as a whole: the report record is
        already the merge of every analysed view, so replacing it keeps the
        protocol identical to what the strain window shows.
        """
        data = self.get(study_uid)
        self._set(study_uid, replace(data, strain=report))

    def merge_vessel_measurements(
        self,
        study_uid: str,
        incoming: tuple[VesselMeasurement, ...],
    ) -> None:
        data = self.get(study_uid)
        self._set(
            study_uid,
            replace(
                data,
                vessel_measurements=merge_vessel_measurements(data.vessel_measurements, incoming),
            ),
        )

    def reset_measurements(self, study_uid: str) -> None:
        """Clear contours, linear calipers, Doppler, and manual calibration for a study."""
        data = self.get(study_uid)
        self._set(
            study_uid,
            StudyMeasurementData(
                height_cm=data.height_cm,
                weight_kg=data.weight_kg,
                height_source=data.height_source,
                weight_source=data.weight_source,
            ),
        )
