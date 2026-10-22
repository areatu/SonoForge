"""Study-wide snapshot: the report sees every clip of the study."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.gui

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.domain.models import Contour, InstanceMetadata, LinearMeasurement


def _instance(path: Path, uid: str, *, series: str = "1.2.3.4.6") -> InstanceMetadata:
    return InstanceMetadata(
        sop_instance_uid=uid,
        series_uid=series,
        modality="US",
        number_of_frames=10,
        pixel_spacing=(0.5, 0.5),
        frame_time_ms=33.3,
        series_description="Test",
        path=path,
    )


def _open_clip(controller: AppController, instance: InstanceMetadata) -> None:
    """Mirror what load_instance does, without touching the decode pipeline."""
    controller._current_instance = instance
    controller.state_manager.set_instance(
        instance,
        total_frames=instance.number_of_frames,
        frame_time_ms=instance.frame_time_ms,
        emit=False,
    )
    controller._current_study_uid = controller._resolve_study_uid(instance)
    controller.state_manager.set_contours((), emit=False)
    controller._recompute_measurements()


def test_report_snapshot_contains_every_clip(synthetic_dicom_path: Path) -> None:
    controller = AppController()
    clip_a = _instance(synthetic_dicom_path, "clip-a")
    clip_b = _instance(synthetic_dicom_path, "clip-b")

    _open_clip(controller, clip_a)
    controller.on_linear_measurements_changed(
        [LinearMeasurement(label="LVEDD", pixel_length=100.0, millimeter_length=50.0)]
    )

    _open_clip(controller, clip_b)
    controller.on_linear_measurements_changed(
        [LinearMeasurement(label="E", pixel_length=160.0, millimeter_length=80.0)]
    )

    # The clip overlay stays scoped to the clip that is open …
    overlay_labels = {m.label for m in controller.state_manager.snapshot.measurement_snapshot.linear_measurements}
    assert overlay_labels == {"E"}

    # … while the report covers the whole study.
    study = controller.compute_study_snapshot()
    assert study is not None
    assert {m.label for m in study.linear_measurements} == {"LVEDD", "E"}


def test_deleted_caliper_disappears_from_the_report(synthetic_dicom_path: Path) -> None:
    controller = AppController()
    clip_a = _instance(synthetic_dicom_path, "clip-a")
    _open_clip(controller, clip_a)
    controller.on_linear_measurements_changed(
        [
            LinearMeasurement(label="LVEDD", pixel_length=100.0, millimeter_length=50.0),
            LinearMeasurement(label="IVSd", pixel_length=20.0, millimeter_length=10.0),
        ]
    )
    # The operator deletes LVEDD: the viewer re-reports what is left.
    controller.on_linear_measurements_changed(
        [LinearMeasurement(label="IVSd", pixel_length=20.0, millimeter_length=10.0)]
    )

    study = controller.compute_study_snapshot()
    assert {m.label for m in study.linear_measurements} == {"IVSd"}


def test_contours_survive_a_round_trip_between_clips(synthetic_dicom_path: Path) -> None:
    controller = AppController()
    clip_a = _instance(synthetic_dicom_path, "clip-a")
    clip_b = _instance(synthetic_dicom_path, "clip-b")

    def _area(label: str) -> Contour:
        return Contour(
            phase="GEN",
            view="A4C",
            chamber="AREA",
            points=[(0.0, 0.0), (20.0, 0.0), (20.0, 20.0)],
            measurement_label=label,
            frame_index=0,
        )

    _open_clip(controller, clip_a)
    controller.on_contours_changed([_area("Площадь1")])
    _open_clip(controller, clip_b)
    controller.on_contours_changed([_area("Площадь2")])
    _open_clip(controller, clip_a)

    study = controller.compute_study_snapshot()
    assert study is not None
    labels = {item.label for item in study.planimeter}
    assert labels == {"Площадь1", "Площадь2"}
