"""Unit tests for study-scoped measurement session accumulation."""

from __future__ import annotations

from echo_personal_tool.application.study_measurement_session import (
    StudyMeasurementSessionStore,
    merge_contours,
    merge_linear_measurements,
    merge_vessel_measurements,
    vessel_measurements_for_instance,
)
from echo_personal_tool.domain.models import Contour, LinearMeasurement
from echo_personal_tool.domain.models.vessel_measurement import VesselMeasurement


def test_merge_contours_replaces_same_chamber_view_phase() -> None:
    uid = "1.2.3.instance.a"
    existing = (
        Contour(
            phase="ED",
            view="A4C",
            chamber="LV",
            points=[(0.0, 0.0)],
            sop_instance_uid=uid,
        ),
        Contour(
            phase="ES",
            view="A4C",
            chamber="LV",
            points=[(1.0, 1.0)],
            sop_instance_uid=uid,
        ),
    )
    incoming = (
        Contour(
            phase="ED",
            view="A4C",
            chamber="LV",
            points=[(2.0, 2.0)],
            sop_instance_uid=uid,
        ),
    )

    merged = merge_contours(existing, incoming)

    assert len(merged) == 2
    ed = next(contour for contour in merged if contour.phase == "ED")
    es = next(contour for contour in merged if contour.phase == "ES")
    assert ed.points == [(2.0, 2.0)]
    assert es.points == [(1.0, 1.0)]


def test_merge_contours_keeps_different_instances_separate() -> None:
    existing = (
        Contour(
            phase="ED",
            view="A4C",
            chamber="LV",
            points=[(0.0, 0.0)],
            sop_instance_uid="clip-a",
        ),
    )
    incoming = (
        Contour(
            phase="ED",
            view="A4C",
            chamber="LV",
            points=[(2.0, 2.0)],
            sop_instance_uid="clip-b",
        ),
    )

    merged = merge_contours(existing, incoming)

    assert len(merged) == 2


def test_merge_contours_ignores_empty_incoming() -> None:
    existing = (
        Contour(
            phase="ED",
            view="A4C",
            chamber="LV",
            points=[(0.0, 0.0)],
            sop_instance_uid="clip-a",
        ),
    )

    assert merge_contours(existing, ()) is existing


def test_merge_linear_measurements_replaces_by_label() -> None:
    existing = (
        LinearMeasurement(label="LVEDD", pixel_length=100.0, millimeter_length=50.0),
        LinearMeasurement(label="LVESD", pixel_length=80.0, millimeter_length=40.0),
    )
    incoming = (LinearMeasurement(label="LVEDD", pixel_length=90.0, millimeter_length=45.0),)

    merged = merge_linear_measurements(existing, incoming)

    assert len(merged) == 2
    lvedd = next(item for item in merged if item.label == "LVEDD")
    assert lvedd.millimeter_length == 45.0


def test_session_store_accumulates_across_merge_calls() -> None:
    store = StudyMeasurementSessionStore()
    study_uid = "1.2.3"

    store.merge_contours(
        study_uid,
        (
            Contour(
                phase="ED",
                view="A4C",
                chamber="LV",
                points=[(0.0, 0.0)],
                sop_instance_uid="clip-a",
            ),
        ),
    )
    store.merge_linear_measurements(
        study_uid,
        (LinearMeasurement(label="LVEDD", pixel_length=100.0, millimeter_length=50.0),),
    )
    store.merge_contours(
        study_uid,
        (
            Contour(
                phase="ES",
                view="A4C",
                chamber="LV",
                points=[(1.0, 1.0)],
                sop_instance_uid="clip-a",
            ),
        ),
    )

    data = store.get(study_uid)
    assert len(data.contours) == 2
    assert len(data.linear_measurements) == 1
    assert data.linear_measurements[0].label == "LVEDD"


def test_session_store_clear() -> None:
    store = StudyMeasurementSessionStore()
    store.merge_contours(
        "study",
        (
            Contour(
                phase="ED",
                view="A4C",
                chamber="LV",
                points=[(0.0, 0.0)],
                sop_instance_uid="clip-a",
            ),
        ),
    )

    store.clear()

    assert store.get("study").contours == ()


def _vessel_m(psv: float, uid: str, frame: int) -> VesselMeasurement:
    return VesselMeasurement(
        psv_cm_s=psv,
        edv_cm_s=psv / 2.0,
        ri=0.5,
        sd=2.0,
        mv_approx=psv * 2.0 / 3.0,
        sop_instance_uid=uid,
        frame_index=frame,
    )


def test_merge_vessel_measurements_replaces_by_instance_and_frame() -> None:
    existing = (_vessel_m(100.0, "A", 1), _vessel_m(200.0, "A", 2))
    incoming = (_vessel_m(150.0, "A", 1),)  # заменяет frame 1, сохраняет frame 2
    result = merge_vessel_measurements(existing, incoming)
    assert len(result) == 2
    by_frame = {m.frame_index: m for m in result}
    assert by_frame[1].psv_cm_s == 150.0
    assert by_frame[2].psv_cm_s == 200.0


def test_merge_vessel_measurements_empty_clears() -> None:
    existing = (_vessel_m(100.0, "A", 1),)
    assert merge_vessel_measurements(existing, ()) == ()


def test_vessel_measurements_filter_by_instance() -> None:
    measurements = (_vessel_m(100.0, "A", 1), _vessel_m(120.0, "B", 1))
    assert vessel_measurements_for_instance(measurements, "B") == (measurements[1],)


def test_session_store_merge_vessel_and_reset() -> None:
    store = StudyMeasurementSessionStore()
    store.merge_vessel_measurements("study1", (_vessel_m(100.0, "A", 1),))
    data = store.get("study1")
    assert len(data.vessel_measurements) == 1
    store.reset_measurements("study1")
    assert store.get("study1").vessel_measurements == ()
