"""Extended tests for study_measurement_session (covering doppler, mmode, etc.)."""

from __future__ import annotations

import pytest

from echo_personal_tool.application.study_measurement_session import (
    StudyMeasurementData,
    StudyMeasurementSessionStore,
    aggregate_doppler_by_instance,
    contour_key,
    contours_for_instance,
    merge_contours,
    merge_doppler_dtos,
    merge_doppler_intervals,
    merge_doppler_peaks,
    merge_doppler_traces,
    merge_linear_measurements,
)
from echo_personal_tool.domain.models import Contour, LinearMeasurement
from echo_personal_tool.domain.models.doppler import (
    DopplerIntervalMarker,
    DopplerMeasurementDTO,
    DopplerPeakMarker,
    DopplerTrace,
)
from echo_personal_tool.domain.models.doppler_roi import DopplerCalibrationState, DopplerKind, DopplerSpectrogramRoi
from echo_personal_tool.domain.models.frame_panels import MmodeCalibrationState


# ── contour_key ──────────────────────────────────────────────────────


def test_contour_key_basic() -> None:
    c = Contour(phase="ED", view="A4C", chamber="LV", points=[], sop_instance_uid="uid1")
    assert contour_key(c) == ("uid1", "LV", "A4C", "ED")


def test_contour_key_area_chamber_uses_measurement_label() -> None:
    c = Contour(
        phase="ED",
        view="A4C",
        chamber="AREA",
        points=[],
        sop_instance_uid="uid1",
        measurement_label="ED_area",
    )
    assert contour_key(c) == ("uid1", "AREA", "A4C", "ED_area")


def test_contour_key_vol_chamber_uses_measurement_label() -> None:
    c = Contour(
        phase="ES",
        view="A4C",
        chamber="VOL",
        points=[],
        measurement_label="vol_label",
    )
    assert contour_key(c) == ("", "VOL", "A4C", "vol_label")


# ── contours_for_instance ───────────────────────────────────────────


def test_contours_for_instance_filters() -> None:
    c1 = Contour(phase="ED", view="A4C", chamber="LV", points=[], sop_instance_uid="a")
    c2 = Contour(phase="ED", view="A4C", chamber="LV", points=[], sop_instance_uid="b")
    result = contours_for_instance((c1, c2), "a")
    assert len(result) == 1
    assert result[0].sop_instance_uid == "a"


def test_contours_for_instance_empty() -> None:
    c1 = Contour(phase="ED", view="A4C", chamber="LV", points=[], sop_instance_uid="a")
    result = contours_for_instance((c1,), "z")
    assert result == ()


# ── merge_doppler_peaks ──────────────────────────────────────────────


def test_merge_doppler_peaks_new() -> None:
    existing = (DopplerPeakMarker(label="E", time_ms=100, velocity_cm_s=120),)
    incoming = (DopplerPeakMarker(label="A", time_ms=200, velocity_cm_s=80),)
    result = merge_doppler_peaks(existing, incoming)
    assert len(result) == 2


def test_merge_doppler_peaks_replaces_same_label() -> None:
    existing = (DopplerPeakMarker(label="E", time_ms=100, velocity_cm_s=120),)
    incoming = (DopplerPeakMarker(label="E", time_ms=150, velocity_cm_s=90),)
    result = merge_doppler_peaks(existing, incoming)
    assert len(result) == 1
    assert result[0].time_ms == 150


# ── merge_doppler_intervals ─────────────────────────────────────────


def test_merge_doppler_intervals() -> None:
    existing = (DopplerIntervalMarker(label="IVRT", start_time_ms=0, end_time_ms=80),)
    incoming = (DopplerIntervalMarker(label="IVRT", start_time_ms=10, end_time_ms=90),)
    result = merge_doppler_intervals(existing, incoming)
    assert len(result) == 1
    assert result[0].start_time_ms == 10


# ── merge_doppler_traces ────────────────────────────────────────────


def test_merge_doppler_traces() -> None:
    existing = (DopplerTrace(label="E", points=((1, 2),)),)
    incoming = (DopplerTrace(label="A", points=((3, 4),)),)
    result = merge_doppler_traces(existing, incoming)
    assert len(result) == 2


# ── merge_doppler_dtos ──────────────────────────────────────────────


def test_merge_doppler_dtos_none_existing() -> None:
    incoming = DopplerMeasurementDTO(peaks=(), intervals=(), traces=())
    assert merge_doppler_dtos(None, incoming) is incoming


def test_merge_doppler_dtos_merges() -> None:
    existing = DopplerMeasurementDTO(
        peaks=(DopplerPeakMarker(label="E", time_ms=100, velocity_cm_s=120),),
        intervals=(),
        traces=(),
    )
    incoming = DopplerMeasurementDTO(
        peaks=(DopplerPeakMarker(label="A", time_ms=200, velocity_cm_s=80),),
        intervals=(),
        traces=(),
    )
    result = merge_doppler_dtos(existing, incoming)
    assert len(result.peaks) == 2


# ── aggregate_doppler_by_instance ────────────────────────────────────


def test_aggregate_doppler_empty() -> None:
    assert aggregate_doppler_by_instance({}) is None


def test_aggregate_doppler_single() -> None:
    dto = DopplerMeasurementDTO(
        peaks=(DopplerPeakMarker(label="E", time_ms=100, velocity_cm_s=120),),
        intervals=(),
        traces=(),
    )
    result = aggregate_doppler_by_instance({"uid1": dto})
    assert result is dto


# ── StudyMeasurementSessionStore ─────────────────────────────────────


def test_contains_returns_false_for_unknown() -> None:
    store = StudyMeasurementSessionStore()
    assert "unknown" not in store


def test_contains_returns_true_after_get() -> None:
    store = StudyMeasurementSessionStore()
    store.get("study1")
    assert "study1" in store


def test_merge_linear_measurements_empty_incoming_clears() -> None:
    store = StudyMeasurementSessionStore()
    store.merge_linear_measurements(
        "s1",
        (LinearMeasurement(label="LVEDD", pixel_length=100, millimeter_length=50),),
    )
    store.merge_linear_measurements("s1", ())
    data = store.get("s1")
    assert data.linear_measurements == ()


def test_doppler_measurement_property() -> None:
    dto = DopplerMeasurementDTO(
        peaks=(DopplerPeakMarker(label="E", time_ms=100, velocity_cm_s=120),),
        intervals=(),
        traces=(),
    )
    data = StudyMeasurementData(doppler_by_instance=(("uid", dto),))
    assert data.doppler_measurement is dto


def test_doppler_measurement_property_empty() -> None:
    data = StudyMeasurementData()
    assert data.doppler_measurement is None


def test_merge_doppler_for_instance() -> None:
    store = StudyMeasurementSessionStore()
    dto = DopplerMeasurementDTO(
        peaks=(DopplerPeakMarker(label="E", time_ms=100, velocity_cm_s=120),),
        intervals=(),
        traces=(),
    )
    store.merge_doppler_for_instance("s1", "uid1", dto)
    result = store.get_doppler_for_instance("s1", "uid1")
    assert result is not None
    assert len(result.peaks) == 1


def test_get_doppler_for_instance_not_found() -> None:
    store = StudyMeasurementSessionStore()
    assert store.get_doppler_for_instance("s1", "uid1") is None


def test_set_doppler_calibration_and_get() -> None:
    store = StudyMeasurementSessionStore()
    roi = DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50)
    cal = DopplerCalibrationState(roi=roi, baseline_y_px=25)
    store.set_doppler_calibration("s1", "uid1", cal)
    assert store.get_doppler_calibration("s1", "uid1") is cal


def test_set_doppler_calibration_none_removes() -> None:
    store = StudyMeasurementSessionStore()
    roi = DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50)
    cal = DopplerCalibrationState(roi=roi, baseline_y_px=25)
    store.set_doppler_calibration("s1", "uid1", cal)
    store.set_doppler_calibration("s1", "uid1", None)
    assert store.get_doppler_calibration("s1", "uid1") is None


def test_set_doppler_calibration_for_frame() -> None:
    store = StudyMeasurementSessionStore()
    roi = DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50)
    cal = DopplerCalibrationState(roi=roi, baseline_y_px=25)
    store.set_doppler_calibration_for_frame("s1", "uid1", 5, cal)
    assert store.get_doppler_calibration_for_frame("s1", "uid1", 5) is cal
    assert store.get_doppler_calibration_for_frame("s1", "uid1", 6) is None


def test_set_doppler_calibration_for_frame_none_removes() -> None:
    store = StudyMeasurementSessionStore()
    roi = DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50)
    cal = DopplerCalibrationState(roi=roi, baseline_y_px=25)
    store.set_doppler_calibration_for_frame("s1", "uid1", 5, cal)
    store.set_doppler_calibration_for_frame("s1", "uid1", 5, None)
    assert store.get_doppler_calibration_for_frame("s1", "uid1", 5) is None


def test_merge_doppler_for_instance_frame() -> None:
    store = StudyMeasurementSessionStore()
    dto = DopplerMeasurementDTO(
        peaks=(DopplerPeakMarker(label="E", time_ms=100, velocity_cm_s=120),),
        intervals=(),
        traces=(),
    )
    store.merge_doppler_for_instance_frame("s1", "uid1", 3, dto)
    result = store.get_doppler_for_instance_frame("s1", "uid1", 3)
    assert result is not None
    assert len(result.peaks) == 1


def test_merge_doppler_for_instance_frame_accumulates() -> None:
    store = StudyMeasurementSessionStore()
    dto1 = DopplerMeasurementDTO(
        peaks=(DopplerPeakMarker(label="E", time_ms=100, velocity_cm_s=120),),
        intervals=(),
        traces=(),
    )
    dto2 = DopplerMeasurementDTO(
        peaks=(DopplerPeakMarker(label="A", time_ms=200, velocity_cm_s=80),),
        intervals=(),
        traces=(),
    )
    store.merge_doppler_for_instance_frame("s1", "uid1", 3, dto1)
    store.merge_doppler_for_instance_frame("s1", "uid1", 3, dto2)
    result = store.get_doppler_for_instance_frame("s1", "uid1", 3)
    assert len(result.peaks) == 2


def test_set_mmode_calibration() -> None:
    store = StudyMeasurementSessionStore()
    roi = DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50)
    mmode = MmodeCalibrationState(roi=roi, vertical_mm_per_pixel=0.5)
    store.set_mmode_calibration("s1", "uid1", mmode)
    assert store.get_mmode_calibration("s1", "uid1") is mmode


def test_set_mmode_calibration_none_removes() -> None:
    store = StudyMeasurementSessionStore()
    roi = DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50)
    mmode = MmodeCalibrationState(roi=roi, vertical_mm_per_pixel=0.5)
    store.set_mmode_calibration("s1", "uid1", mmode)
    store.set_mmode_calibration("s1", "uid1", None)
    assert store.get_mmode_calibration("s1", "uid1") is None


def test_set_mmode_time_per_pixel_ms() -> None:
    store = StudyMeasurementSessionStore()
    store.set_mmode_time_per_pixel_ms("s1", 2.5)
    assert store.get("s1").mmode_time_per_pixel_ms == 2.5


def test_set_cine_segment_roi() -> None:
    store = StudyMeasurementSessionStore()
    store.set_cine_segment_roi("s1", "uid1", (10.0, 20.0, 30.0, 40.0))
    assert store.get_cine_segment_roi("s1", "uid1") == (10.0, 20.0, 30.0, 40.0)


def test_set_cine_segment_roi_none_removes() -> None:
    store = StudyMeasurementSessionStore()
    store.set_cine_segment_roi("s1", "uid1", (10.0, 20.0, 30.0, 40.0))
    store.set_cine_segment_roi("s1", "uid1", None)
    assert store.get_cine_segment_roi("s1", "uid1") is None


def test_get_cine_segment_roi_not_found() -> None:
    store = StudyMeasurementSessionStore()
    assert store.get_cine_segment_roi("s1", "uid1") is None


def test_set_doppler_measurement_legacy() -> None:
    store = StudyMeasurementSessionStore()
    dto = DopplerMeasurementDTO(
        peaks=(DopplerPeakMarker(label="E", time_ms=100, velocity_cm_s=120),),
        intervals=(),
        traces=(),
    )
    store.set_doppler_measurement("s1", dto)
    data = store.get("s1")
    assert len(data.doppler_by_instance) == 1
    assert data.doppler_by_instance[0][0] == "__legacy__"


def test_set_doppler_measurement_none_clears() -> None:
    store = StudyMeasurementSessionStore()
    store.set_doppler_measurement("s1", None)
    assert store.get("s1").doppler_by_instance == ()


def test_set_manual_pixel_spacing() -> None:
    store = StudyMeasurementSessionStore()
    store.set_manual_pixel_spacing("s1", (0.5, 0.5))
    assert store.get("s1").manual_pixel_spacing == (0.5, 0.5)


def test_set_patient_metrics() -> None:
    store = StudyMeasurementSessionStore()
    store.set_patient_metrics("s1", 170.0, 70.0)
    data = store.get("s1")
    assert data.height_cm == 170.0
    assert data.weight_kg == 70.0


def test_reset_measurements_preserves_patient_metrics() -> None:
    store = StudyMeasurementSessionStore()
    store.set_patient_metrics("s1", 170.0, 70.0)
    store.merge_contours(
        "s1",
        (Contour(phase="ED", view="A4C", chamber="LV", points=[], sop_instance_uid="u"),),
    )
    store.reset_measurements("s1")
    data = store.get("s1")
    assert data.contours == ()
    assert data.height_cm == 170.0
    assert data.weight_kg == 70.0


def test_merge_linear_measurements_by_key() -> None:
    existing = (
        LinearMeasurement(label="LVEDD", pixel_length=100, millimeter_length=50, frame_index=0),
        LinearMeasurement(label="LVESD", pixel_length=80, millimeter_length=40, frame_index=0),
    )
    incoming = (
        LinearMeasurement(label="LVEDD", pixel_length=110, millimeter_length=55, frame_index=1),
    )
    result = merge_linear_measurements(existing, incoming)
    # LVEDD at frame 0 and frame 1 are different keys, so both kept; LVESD at frame 0 kept
    assert len(result) == 3


def test_merge_linear_measurements_none_frame_index() -> None:
    existing = (
        LinearMeasurement(label="LVEDD", pixel_length=100, millimeter_length=50, frame_index=None),
    )
    incoming = (
        LinearMeasurement(label="LVEDD", pixel_length=110, millimeter_length=55, frame_index=None),
    )
    result = merge_linear_measurements(existing, incoming)
    assert len(result) == 1
    assert result[0].pixel_length == 110
