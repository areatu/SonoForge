"""Unit tests for study-scoped measurement session accumulation."""

from __future__ import annotations

from echo_personal_tool.application.study_measurement_session import (
    StudyMeasurementSessionStore,
    merge_contours,
    merge_linear_measurements,
)
from echo_personal_tool.domain.models import Contour, LinearMeasurement


def test_merge_contours_replaces_same_chamber_view_phase() -> None:
    existing = (
        Contour(phase="ED", view="A4C", chamber="LV", points=[(0.0, 0.0)]),
        Contour(phase="ES", view="A4C", chamber="LV", points=[(1.0, 1.0)]),
    )
    incoming = (Contour(phase="ED", view="A4C", chamber="LV", points=[(2.0, 2.0)]),)

    merged = merge_contours(existing, incoming)

    assert len(merged) == 2
    ed = next(contour for contour in merged if contour.phase == "ED")
    es = next(contour for contour in merged if contour.phase == "ES")
    assert ed.points == [(2.0, 2.0)]
    assert es.points == [(1.0, 1.0)]


def test_merge_contours_ignores_empty_incoming() -> None:
    existing = (Contour(phase="ED", view="A4C", chamber="LV", points=[(0.0, 0.0)]),)

    assert merge_contours(existing, ()) is existing


def test_merge_linear_measurements_replaces_by_label() -> None:
    existing = (
        LinearMeasurement(label="LVEDD", pixel_length=100.0, millimeter_length=50.0),
        LinearMeasurement(label="LVESD", pixel_length=80.0, millimeter_length=40.0),
    )
    incoming = (
        LinearMeasurement(label="LVEDD", pixel_length=90.0, millimeter_length=45.0),
    )

    merged = merge_linear_measurements(existing, incoming)

    assert len(merged) == 2
    lvedd = next(item for item in merged if item.label == "LVEDD")
    assert lvedd.millimeter_length == 45.0


def test_session_store_accumulates_across_merge_calls() -> None:
    store = StudyMeasurementSessionStore()
    study_uid = "1.2.3"

    store.merge_contours(
        study_uid,
        (Contour(phase="ED", view="A4C", chamber="LV", points=[(0.0, 0.0)]),),
    )
    store.merge_linear_measurements(
        study_uid,
        (LinearMeasurement(label="LVEDD", pixel_length=100.0, millimeter_length=50.0),),
    )
    store.merge_contours(
        study_uid,
        (Contour(phase="ES", view="A4C", chamber="LV", points=[(1.0, 1.0)]),),
    )

    data = store.get(study_uid)
    assert len(data.contours) == 2
    assert len(data.linear_measurements) == 1
    assert data.linear_measurements[0].label == "LVEDD"


def test_session_store_clear() -> None:
    store = StudyMeasurementSessionStore()
    store.merge_contours(
        "study",
        (Contour(phase="ED", view="A4C", chamber="LV", points=[(0.0, 0.0)]),),
    )

    store.clear()

    assert store.get("study").contours == ()
