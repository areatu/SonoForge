"""Integration tests for measurement recomputation wiring."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.domain.calculations.doppler_metrics import compute
from echo_personal_tool.domain.calculations.lvef_simpson import calculate
from echo_personal_tool.domain.calculations.teichholz import from_linear_measurements
from echo_personal_tool.domain.models import (
    Contour,
    DopplerIntervalMarker,
    DopplerMeasurementDTO,
    DopplerPeakMarker,
    DopplerTrace,
    InstanceMetadata,
    LinearMeasurement,
)
from echo_personal_tool.domain.services.mbs_lite_service import fit_contour_from_landmarks


def _sample_instance() -> InstanceMetadata:
    return InstanceMetadata(
        sop_instance_uid="1.2.3.4.5",
        series_uid="1.2.3.4.6",
        modality="US",
        number_of_frames=4,
        pixel_spacing=(0.5, 0.5),
        frame_time_ms=40.0,
        series_description="Test",
        path=Path("/tmp/test.dcm"),
    )


def _sample_doppler() -> DopplerMeasurementDTO:
    return DopplerMeasurementDTO(
        peaks=(
            DopplerPeakMarker(label="E", time_ms=120.0, velocity_cm_s=85.0),
            DopplerPeakMarker(label="A", time_ms=220.0, velocity_cm_s=60.0),
            DopplerPeakMarker(label="e_sept", time_ms=130.0, velocity_cm_s=8.0),
            DopplerPeakMarker(label="e_lat", time_ms=130.0, velocity_cm_s=10.0),
            DopplerPeakMarker(label="Vmax", time_ms=150.0, velocity_cm_s=250.0),
        ),
        intervals=(
            DopplerIntervalMarker(label="DT", start_time_ms=80.0, end_time_ms=260.0),
            DopplerIntervalMarker(label="IVRT", start_time_ms=60.0, end_time_ms=140.0),
            DopplerIntervalMarker(label="AT", start_time_ms=150.0, end_time_ms=270.0),
        ),
        traces=(DopplerTrace(label="VTI", points=((0.0, 0.0), (10.0, 2.0), (20.0, 1.0))),),
    )


def _sample_contours() -> tuple[Contour, ...]:
    return (
        Contour(
            phase="ED",
            view="A4C",
            points=[(0.0, 0.0), (20.0, 0.0), (20.0, 40.0), (0.0, 40.0)],
        ),
        Contour(
            phase="ES",
            view="A4C",
            points=[(0.0, 0.0), (16.0, 0.0), (16.0, 40.0), (0.0, 40.0)],
        ),
    )


def _sample_linear_measurements() -> tuple[LinearMeasurement, ...]:
    return (
        LinearMeasurement(label="LVEDD", pixel_length=100.0, millimeter_length=50.0),
        LinearMeasurement(label="LVESD", pixel_length=80.0, millimeter_length=40.0),
    )


def test_app_controller_recomputes_lvef_from_model_contours() -> None:
    controller = AppController()
    controller.state_manager.set_instance(_sample_instance(), total_frames=4, frame_time_ms=40.0)

    ed = fit_contour_from_landmarks(
        septal=(10.0, 40.0),
        lateral=(50.0, 40.0),
        apex=(30.0, 10.0),
        phase="ED",
        view="A4C",
    )
    es = fit_contour_from_landmarks(
        septal=(12.0, 40.0),
        lateral=(48.0, 40.0),
        apex=(30.0, 15.0),
        phase="ES",
        view="A4C",
    )
    controller.on_contours_changed([ed, es])

    snapshot = controller.state_manager.snapshot.measurement_snapshot
    assert snapshot is not None
    assert snapshot.lvef is not None
    assert snapshot.lvef.a4c is not None
    assert snapshot.lvef.a4c.edv_ml > 0.0
    assert snapshot.lvef.a4c.esv_ml > 0.0


def test_app_controller_recomputes_measurements_from_current_state() -> None:
    controller = AppController()
    controller.state_manager.set_instance(_sample_instance(), total_frames=4, frame_time_ms=40.0)

    doppler = _sample_doppler()
    contours = _sample_contours()
    linear_measurements = _sample_linear_measurements()

    controller.on_doppler_markers_changed(doppler)
    controller.on_contours_changed(list(contours))
    controller.on_linear_measurements_changed(list(linear_measurements))

    snapshot = controller.state_manager.snapshot.measurement_snapshot
    assert snapshot is not None
    assert snapshot.doppler == compute(doppler)
    assert snapshot.lvef == calculate(contours, _sample_instance().pixel_spacing)
    assert snapshot.teichholz == from_linear_measurements(linear_measurements)
    assert snapshot.linear_measurements == linear_measurements


@pytest.fixture(scope="session", autouse=True)
def _qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app
