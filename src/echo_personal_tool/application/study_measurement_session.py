"""Session-scoped measurement accumulation for an open study folder."""

from __future__ import annotations

from dataclasses import dataclass, replace

from echo_personal_tool.domain.models import Contour, LinearMeasurement
from echo_personal_tool.domain.models.doppler import DopplerMeasurementDTO


def contour_key(contour: Contour) -> tuple[str, str, str]:
    """Stable identity for LV/LA contours within a study session."""
    return (contour.chamber, contour.view, contour.phase)


def merge_contours(
    existing: tuple[Contour, ...],
    incoming: tuple[Contour, ...],
) -> tuple[Contour, ...]:
    """Replace contours by chamber/view/phase; ignore empty incoming (instance switch)."""
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
    """Replace linear measurements by label and frame; ignore empty incoming."""
    if not incoming:
        return existing
    by_key: dict[tuple[str, int], LinearMeasurement] = {}
    for measurement in existing:
        frame_key = measurement.frame_index if measurement.frame_index is not None else -1
        by_key[(measurement.label, frame_key)] = measurement
    for measurement in incoming:
        frame_key = measurement.frame_index if measurement.frame_index is not None else -1
        by_key[(measurement.label, frame_key)] = measurement
    return tuple(by_key.values())


@dataclass(frozen=True)
class StudyMeasurementData:
    contours: tuple[Contour, ...] = ()
    linear_measurements: tuple[LinearMeasurement, ...] = ()
    doppler_measurement: DopplerMeasurementDTO | None = None
    manual_pixel_spacing: tuple[float, float] | None = None
    height_cm: float | None = None
    weight_kg: float | None = None


class StudyMeasurementSessionStore:
    """Accumulates raw measurement inputs per study until the app session ends."""

    def __init__(self) -> None:
        self._studies: dict[str, StudyMeasurementData] = {}

    def clear(self) -> None:
        self._studies.clear()

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

    def set_doppler_measurement(
        self,
        study_uid: str,
        dto: DopplerMeasurementDTO | None,
    ) -> None:
        data = self.get(study_uid)
        self._studies[study_uid] = replace(data, doppler_measurement=dto)

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

    def reset_measurements(self, study_uid: str) -> None:
        """Clear contours, linear calipers, Doppler, and manual calibration for a study."""
        data = self.get(study_uid)
        self._studies[study_uid] = StudyMeasurementData(
            height_cm=data.height_cm,
            weight_kg=data.weight_kg,
        )
