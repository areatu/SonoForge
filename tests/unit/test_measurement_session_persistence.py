"""Tests that measurement results persist across instance switches."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.domain.models import InstanceMetadata, LinearMeasurement
from echo_personal_tool.domain.services.mbs_lite_service import fit_contour_from_landmarks


def _sample_instance(
    *,
    sop_instance_uid: str = "1.2.3.4.5",
    series_uid: str = "1.2.3.4.6",
) -> InstanceMetadata:
    return InstanceMetadata(
        sop_instance_uid=sop_instance_uid,
        series_uid=series_uid,
        modality="US",
        number_of_frames=10,
        pixel_spacing=(0.5, 0.5),
        frame_time_ms=33.3,
        series_description="Test",
        path=Path("/tmp/test.dcm"),
    )


def _load_instance(controller: AppController, instance: InstanceMetadata) -> None:
    controller._current_instance = instance
    controller.state_manager.set_instance(
        instance,
        total_frames=instance.number_of_frames,
        frame_time_ms=instance.frame_time_ms,
        emit=False,
    )
    controller._current_study_uid = controller._resolve_study_uid(instance)
    controller._recompute_measurements()


def test_linear_measurements_persist_after_instance_switch() -> None:
    controller = AppController()
    first = _sample_instance(sop_instance_uid="inst-a")
    second = _sample_instance(sop_instance_uid="inst-b")

    _load_instance(controller, first)
    controller.on_linear_measurements_changed(
        [LinearMeasurement(label="LVEDD", pixel_length=100.0, millimeter_length=50.0)]
    )

    snapshot_before = controller.state_manager.snapshot.measurement_snapshot
    assert snapshot_before is not None
    assert snapshot_before.linear_measurements[0].label == "LVEDD"

    _load_instance(controller, second)

    snapshot_after = controller.state_manager.snapshot.measurement_snapshot
    assert snapshot_after is not None
    assert snapshot_after.linear_measurements == snapshot_before.linear_measurements


def test_simpson_results_persist_after_instance_switch() -> None:
    controller = AppController()
    first = _sample_instance(sop_instance_uid="inst-a")
    second = _sample_instance(sop_instance_uid="inst-b")

    _load_instance(controller, first)
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

    snapshot_before = controller.state_manager.snapshot.measurement_snapshot
    assert snapshot_before is not None
    assert snapshot_before.lvef is not None
    assert snapshot_before.lvef.a4c is not None

    _load_instance(controller, second)

    snapshot_after = controller.state_manager.snapshot.measurement_snapshot
    assert snapshot_after is not None
    assert snapshot_after.lvef == snapshot_before.lvef


def test_open_folder_clears_session_store(monkeypatch, tmp_path: Path) -> None:
    controller = AppController()
    instance = _sample_instance()

    _load_instance(controller, instance)
    controller.on_linear_measurements_changed(
        [LinearMeasurement(label="LVEDD", pixel_length=100.0, millimeter_length=50.0)]
    )
    assert controller.state_manager.snapshot.measurement_snapshot is not None

    monkeypatch.setattr(controller._thread_pool, "start", lambda _worker: None)
    controller.open_folder(tmp_path)

    study_uid = controller._resolve_study_uid(instance)
    assert controller._measurement_session.get(study_uid).linear_measurements == ()


def test_patient_metrics_persist_after_instance_switch() -> None:
    controller = AppController()
    first = _sample_instance(sop_instance_uid="inst-a")
    second = _sample_instance(sop_instance_uid="inst-b")

    _load_instance(controller, first)
    controller.on_patient_metrics_changed(170.0, 70.0)

    snapshot_before = controller.state_manager.snapshot.measurement_snapshot
    assert snapshot_before is not None
    assert snapshot_before.height_cm == 170.0
    assert snapshot_before.weight_kg == 70.0
    assert snapshot_before.indexed is not None

    _load_instance(controller, second)

    snapshot_after = controller.state_manager.snapshot.measurement_snapshot
    assert snapshot_after is not None
    assert snapshot_after.height_cm == 170.0
    assert snapshot_after.weight_kg == 70.0
    assert snapshot_after.indexed is not None


@pytest.fixture(scope="session", autouse=True)
def _qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app
