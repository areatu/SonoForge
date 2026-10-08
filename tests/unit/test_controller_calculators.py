"""AppController wiring of the calculators (Э11): study-wide inputs, overrides, HR."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.gui

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.domain.calculators.models import SOURCE_DICOM, SOURCE_ESTIMATE, SOURCE_MANUAL
from echo_personal_tool.domain.models import InstanceMetadata, LinearMeasurement
from echo_personal_tool.domain.models.doppler import DopplerMeasurementDTO, DopplerTrace


def _instance(path: Path, uid: str, *, heart_rate: float | None = None) -> InstanceMetadata:
    return InstanceMetadata(
        sop_instance_uid=uid,
        series_uid="1.2.3.4.6",
        modality="US",
        number_of_frames=10,
        pixel_spacing=(0.5, 0.5),
        frame_time_ms=33.3,
        series_description="Test",
        path=path,
        heart_rate_bpm=heart_rate,
    )


def _open_clip(controller: AppController, instance: InstanceMetadata) -> None:
    controller._current_instance = instance
    controller.state_manager.set_instance(
        instance, total_frames=instance.number_of_frames, frame_time_ms=instance.frame_time_ms, emit=False
    )
    controller._current_study_uid = controller._resolve_study_uid(instance)
    controller.state_manager.set_contours((), emit=False)
    controller._recompute_measurements()


def _vti_trace(label: str, vti_cm: float, mid: str) -> DopplerTrace:
    peak = vti_cm / 0.15
    return DopplerTrace(label=label, points=((0.0, 0.0), (150.0, peak), (300.0, 0.0)), measurement_id=mid)


def _doppler(*traces: DopplerTrace) -> DopplerMeasurementDTO:
    return DopplerMeasurementDTO(peaks=(), intervals=(), traces=traces)


def _calculations(controller: AppController):
    return controller.state_manager.snapshot.measurement_snapshot.calculations


def _build_study(controller: AppController, path: Path, *, heart_rate: float | None = None) -> None:
    """LVOTd on a parasternal clip, LVOT/AV VTI on an apical Doppler clip."""
    plax = _instance(path, "plax")
    apical = _instance(path, "a5c", heart_rate=heart_rate)
    _open_clip(controller, plax)
    controller.on_linear_measurements_changed(
        [LinearMeasurement(label="LVOTd", pixel_length=40.0, millimeter_length=20.0)]
    )
    _open_clip(controller, apical)
    controller.save_current_instance_doppler(
        _doppler(_vti_trace("LVOT VTI", 20.0, "l1"), _vti_trace("AV VTI", 100.0, "a1"))
    )


def test_continuity_combines_clips_of_the_study(synthetic_dicom_path: Path) -> None:
    controller = AppController()
    _build_study(controller, synthetic_dicom_path)
    calculations = _calculations(controller)
    assert calculations is not None
    assert calculations.result("stroke_volume").output("sv").value == pytest.approx(62.8, abs=0.1)
    assert calculations.result("aortic_valve_area").output("ava_vti").value == pytest.approx(0.628, abs=0.005)
    # The report snapshot carries the same study-wide results.
    study = controller.compute_study_snapshot()
    assert study.calculations.result("stroke_volume").output("sv").computed


def test_dicom_heart_rate_of_the_lvot_clip_feeds_cardiac_output(synthetic_dicom_path: Path) -> None:
    controller = AppController()
    _build_study(controller, synthetic_dicom_path, heart_rate=70.0)
    calculations = _calculations(controller)
    assert calculations.input("hr").source == SOURCE_DICOM
    assert calculations.result("stroke_volume").output("co").value == pytest.approx(4.40, abs=0.01)


def test_cine_estimate_is_used_only_without_dicom_hr(synthetic_dicom_path: Path) -> None:
    controller = AppController()
    _build_study(controller, synthetic_dicom_path)
    controller.record_heart_rate_estimate(60.0, "optical_flow")
    assert _calculations(controller).input("hr").source == SOURCE_ESTIMATE

    with_dicom = AppController()
    _build_study(with_dicom, synthetic_dicom_path, heart_rate=72.0)
    with_dicom.record_heart_rate_estimate(60.0, "optical_flow")
    assert _calculations(with_dicom).input("hr").value == 72.0


def test_manual_override_and_reset(synthetic_dicom_path: Path) -> None:
    controller = AppController()
    _build_study(controller, synthetic_dicom_path)
    controller.set_calculator_input("lvot_d", 2.2)
    item = _calculations(controller).input("lvot_d")
    assert item.source == SOURCE_MANUAL and item.value == 2.2
    assert item.auto_value == pytest.approx(2.0)
    controller.set_calculator_input("lvot_d", None)
    assert _calculations(controller).input("lvot_d").value == pytest.approx(2.0)


def test_invalid_manual_value_is_ignored(synthetic_dicom_path: Path) -> None:
    controller = AppController()
    _build_study(controller, synthetic_dicom_path)
    before = _calculations(controller)
    controller.set_calculator_input("lvot_d", 500.0)
    controller.set_calculator_input("unknown", 1.0)
    assert _calculations(controller) == before


def test_no_inputs_no_calculations(synthetic_dicom_path: Path) -> None:
    controller = AppController()
    _open_clip(controller, _instance(synthetic_dicom_path, "empty"))
    assert _calculations(controller) is None


def test_pisa_mr_combines_color_caliper_cw_doppler_and_typed_va(synthetic_dicom_path: Path) -> None:
    controller = AppController()
    _build_study(controller, synthetic_dicom_path)
    color = _instance(synthetic_dicom_path, "a4c-color")
    _open_clip(controller, color)
    controller.on_linear_measurements_changed(
        [LinearMeasurement(label="PISA MR", pixel_length=20.0, millimeter_length=10.0)]
    )
    cw = _instance(synthetic_dicom_path, "a4c-cw")
    _open_clip(controller, cw)
    controller.save_current_instance_doppler(_doppler(_vti_trace("MR VTI", 150.0, "m1")))
    mr = _calculations(controller).result("pisa_mr")
    # Without Va nothing is computed — no typical aliasing velocity is assumed.
    assert not mr.has_values
    controller.set_calculator_input("va_mr", 40.0)
    mr = _calculations(controller).result("pisa_mr")
    # Vmax falls back to the trace peak (VTI 150 cm over 300 ms → 1000 cm/s).
    assert mr.output("pisa_flow_mr").value == pytest.approx(251.3, abs=0.2)
    assert mr.output("rvol_mr").computed
    assert mr.output("rf_mr").computed
