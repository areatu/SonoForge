"""Focused tests for AppController critical uncovered methods.

Tests properties, helper methods, and callback paths that don't need full Qt infra.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

pytestmark = pytest.mark.gui
from datetime import UTC

from PySide6.QtWidgets import QApplication

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.domain.models import Contour, InstanceMetadata, LinearMeasurement
from echo_personal_tool.domain.models.doppler import (
    DopplerIntervalMarker,
    DopplerMeasurementDTO,
    DopplerPeakMarker,
    DopplerTrace,
)
from echo_personal_tool.domain.models.doppler_roi import DopplerCalibrationState, DopplerSpectrogramRoi
from echo_personal_tool.domain.models.frame_panels import MmodeCalibrationState


class _FakeSignal:
    def __init__(self):
        self._callbacks = []

    def connect(self, cb, *args, **kwargs):
        self._callbacks.append(cb)

    def emit(self, *args):
        for cb in list(self._callbacks):
            cb(*args)


class _FakeWorker:
    def __init__(self, *args, **kwargs):
        self.signals = SimpleNamespace(
            first_frame_ready=_FakeSignal(),
            progress=_FakeSignal(),
            finished=_FakeSignal(),
            failed=_FakeSignal(),
            batch_finished=_FakeSignal(),
            timed_out=_FakeSignal(),
        )
        self.setAutoDelete = lambda x: None


class _RecordingThreadPool:
    def __init__(self):
        self.started = []

    def start(self, worker):
        self.started.append(worker)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _make_controller(qapp, monkeypatch):
    monkeypatch.setattr("echo_personal_tool.application.app_controller.DicomDecodeWorker", _FakeWorker)
    monkeypatch.setattr("echo_personal_tool.application.app_controller.VideoDecodeWorker", _FakeWorker)
    monkeypatch.setattr("echo_personal_tool.application.app_controller.FrameLoaderWorker", _FakeWorker)
    monkeypatch.setattr("echo_personal_tool.application.app_controller.ThumbnailLoaderWorker", _FakeWorker)
    monkeypatch.setattr("echo_personal_tool.application.app_controller.ScanWorker", _FakeWorker)
    monkeypatch.setattr("echo_personal_tool.application.app_controller.OnnxWorker", _FakeWorker)
    monkeypatch.setattr(
        "echo_personal_tool.application.app_controller.VideoReader",
        type(
            "_VR",
            (),
            {
                "__enter__": lambda s: s,
                "__exit__": lambda *a: False,
                "open": lambda s, p: None,
                "frame_count": 10,
                "fps": 30,
            },
        ),
    )
    return AppController(thread_pool=_RecordingThreadPool())


# ── Properties ───────────────────────────────────────────────────────


def test_studies_property(qapp, monkeypatch):
    ctrl = _make_controller(qapp, monkeypatch)
    assert ctrl.studies == []


def test_state_manager_property(qapp, monkeypatch):
    ctrl = _make_controller(qapp, monkeypatch)
    assert ctrl.state_manager is not None


def test_playback_config_property(qapp, monkeypatch):
    ctrl = _make_controller(qapp, monkeypatch)
    assert ctrl.playback_config is not None


def test_fusion_result_property(qapp, monkeypatch):
    ctrl = _make_controller(qapp, monkeypatch)
    assert ctrl.fusion_result is None


def test_last_segment_roi_property(qapp, monkeypatch):
    ctrl = _make_controller(qapp, monkeypatch)
    assert ctrl.last_segment_roi_xyxy is None


def test_is_scroll_active(qapp, monkeypatch):
    ctrl = _make_controller(qapp, monkeypatch)
    assert ctrl.is_scroll_active() is False


# ── Simple setters / actions ─────────────────────────────────────────


def test_toggle_playback(qapp, monkeypatch):
    ctrl = _make_controller(qapp, monkeypatch)
    assert ctrl._state_manager.snapshot.is_playing is False
    ctrl.toggle_playback()
    assert ctrl._state_manager.snapshot.is_playing is True


def test_toggle_mmode(qapp, monkeypatch):
    ctrl = _make_controller(qapp, monkeypatch)
    assert ctrl._mmode_active is False
    ctrl.toggle_mmode()
    assert ctrl._mmode_active is True
    ctrl.toggle_mmode()
    assert ctrl._mmode_active is False


def test_step_frame(qapp, monkeypatch):
    ctrl = _make_controller(qapp, monkeypatch)
    inst = InstanceMetadata(
        sop_instance_uid="uid1",
        series_uid="s1",
        modality="US",
        number_of_frames=10,
        pixel_spacing=None,
        frame_time_ms=33.3,
        series_description="T",
        path=Path("/tmp/x.dcm"),
        media_format="dicom",
    )
    ctrl._state_manager.set_instance(inst, total_frames=10, frame_time_ms=33.3)
    assert ctrl._state_manager.snapshot.current_frame_index == 0
    ctrl.step_frame(1)
    assert ctrl._state_manager.snapshot.current_frame_index == 1
    ctrl.step_frame(-1)
    assert ctrl._state_manager.snapshot.current_frame_index == 0


def test_set_playback_speed_multiplier(qapp, monkeypatch):
    ctrl = _make_controller(qapp, monkeypatch)
    ctrl.set_playback_speed_multiplier(2.0)
    assert ctrl._playback_speed_multiplier == 2.0
    ctrl.set_playback_speed_multiplier(0.1)  # clamped
    assert ctrl._playback_speed_multiplier == 0.25
    ctrl.set_playback_speed_multiplier(10.0)  # clamped
    assert ctrl._playback_speed_multiplier == 4.0


def test_get_cached_frames_empty(qapp, monkeypatch):
    ctrl = _make_controller(qapp, monkeypatch)
    assert ctrl.get_cached_frames() == []


def test_get_cached_frames_with_data(qapp, monkeypatch):
    ctrl = _make_controller(qapp, monkeypatch)
    path = Path("/tmp/test.dcm")
    ctrl._frame_cache.set_total_frames(path, 3)
    for i in range(3):
        ctrl._frame_cache.put(i, np.zeros((4, 4), dtype=np.uint8) + i)
    frames = ctrl.get_cached_frames()
    assert len(frames) == 3


# ── Simpson workflow context ─────────────────────────────────────────


def test_set_simpson_workflow_context(qapp, monkeypatch):
    ctrl = _make_controller(qapp, monkeypatch)
    ctrl.set_simpson_workflow_context(phase="ED", view="A4C", chamber="LV")
    assert ctrl._auto_segment_phase == "ED"
    assert ctrl._auto_segment_view == "A4C"
    assert ctrl._auto_segment_chamber == "LV"


def test_is_lv_auto_session_active(qapp, monkeypatch):
    ctrl = _make_controller(qapp, monkeypatch)
    assert ctrl.is_lv_auto_session_active() is False
    ctrl.set_simpson_workflow_context(phase="ED", view="A4C")
    assert ctrl.is_lv_auto_session_active() is True
    ctrl.set_simpson_workflow_context(phase="ED", view="A2C")
    assert ctrl.is_lv_auto_session_active() is False


# ── Accept AI contour review ─────────────────────────────────────────


def test_accept_ai_contour_review(qapp, monkeypatch):
    ctrl = _make_controller(qapp, monkeypatch)
    inst = InstanceMetadata(
        sop_instance_uid="uid1",
        series_uid="s1",
        modality="US",
        number_of_frames=10,
        pixel_spacing=(0.5, 0.5),
        frame_time_ms=33.3,
        series_description="T",
        path=Path("/tmp/x.dcm"),
        media_format="dicom",
    )
    ctrl._state_manager.set_instance(inst, total_frames=10, frame_time_ms=33.3)
    contour = Contour(
        phase="ED",
        view="A4C",
        chamber="LV",
        points=[(0, 0)],
        source="ai",
        review_pending=True,
        sop_instance_uid="uid1",
    )
    ctrl._state_manager.set_contours((contour,))
    ctrl._state_manager.set_frame(0)

    # Set up studies so _resolve_study_uid works
    from datetime import datetime

    from echo_personal_tool.domain.models import SeriesMetadata, StudyMetadata

    study = StudyMetadata(
        study_uid="study1",
        study_datetime=datetime(2026, 1, 1, tzinfo=UTC),
        series=(
            SeriesMetadata(
                series_uid="s1",
                study_uid="study1",
                modality="US",
                description="T",
                instances=(inst,),
            ),
        ),
    )
    ctrl._studies = [study]

    result = ctrl.accept_ai_contour_review("A4C", "ED")
    assert result is True
    # Contour should have review_pending=False now
    updated = ctrl._state_manager.snapshot.contours
    assert len(updated) == 1
    assert updated[0].review_pending is False


def test_accept_ai_contour_review_not_found(qapp, monkeypatch):
    ctrl = _make_controller(qapp, monkeypatch)
    inst = InstanceMetadata(
        sop_instance_uid="uid1",
        series_uid="s1",
        modality="US",
        number_of_frames=10,
        pixel_spacing=None,
        frame_time_ms=33.3,
        series_description="T",
        path=Path("/tmp/x.dcm"),
        media_format="dicom",
    )
    ctrl._state_manager.set_instance(inst, total_frames=10, frame_time_ms=33.3)
    assert ctrl.accept_ai_contour_review("A4C", "ED") is False


# ── on_contours_changed ──────────────────────────────────────────────


def test_on_contours_changed(qapp, monkeypatch):
    ctrl = _make_controller(qapp, monkeypatch)
    inst = InstanceMetadata(
        sop_instance_uid="uid1",
        series_uid="s1",
        modality="US",
        number_of_frames=10,
        pixel_spacing=None,
        frame_time_ms=33.3,
        series_description="T",
        path=Path("/tmp/x.dcm"),
        media_format="dicom",
    )
    ctrl._state_manager.set_instance(inst, total_frames=10, frame_time_ms=33.3)
    from datetime import datetime

    from echo_personal_tool.domain.models import SeriesMetadata, StudyMetadata

    study = StudyMetadata(
        study_uid="study1",
        study_datetime=datetime(2026, 1, 1, tzinfo=UTC),
        series=(
            SeriesMetadata(
                series_uid="s1",
                study_uid="study1",
                modality="US",
                description="T",
                instances=(inst,),
            ),
        ),
    )
    ctrl._studies = [study]

    contour = Contour(phase="ED", view="A4C", chamber="LV", points=[(0, 0)])
    ctrl.on_contours_changed([contour])
    assert len(ctrl._state_manager.snapshot.contours) == 1


def test_on_contours_changed_tags_uid(qapp, monkeypatch):
    """Contour with different sop_instance_uid gets tagged with current instance."""
    ctrl = _make_controller(qapp, monkeypatch)
    inst = InstanceMetadata(
        sop_instance_uid="uid1",
        series_uid="s1",
        modality="US",
        number_of_frames=10,
        pixel_spacing=None,
        frame_time_ms=33.3,
        series_description="T",
        path=Path("/tmp/x.dcm"),
        media_format="dicom",
    )
    ctrl._state_manager.set_instance(inst, total_frames=10, frame_time_ms=33.3)
    from datetime import datetime

    from echo_personal_tool.domain.models import SeriesMetadata, StudyMetadata

    study = StudyMetadata(
        study_uid="study1",
        study_datetime=datetime(2026, 1, 1, tzinfo=UTC),
        series=(
            SeriesMetadata(
                series_uid="s1",
                study_uid="study1",
                modality="US",
                description="T",
                instances=(inst,),
            ),
        ),
    )
    ctrl._studies = [study]

    contour = Contour(phase="ED", view="A4C", chamber="LV", points=[], sop_instance_uid="other_uid")
    ctrl.on_contours_changed([contour])
    assert ctrl._state_manager.snapshot.contours[0].sop_instance_uid == "uid1"


def test_on_contours_changed_type_error(qapp, monkeypatch):
    ctrl = _make_controller(qapp, monkeypatch)
    with pytest.raises(TypeError):
        ctrl.on_contours_changed("not a list")


def test_on_contours_changed_no_instance(qapp, monkeypatch):
    ctrl = _make_controller(qapp, monkeypatch)
    # No instance loaded → should return silently
    ctrl.on_contours_changed([])


# ── on_linear_measurements_changed ───────────────────────────────────


def test_on_linear_measurements_changed(qapp, monkeypatch):
    ctrl = _make_controller(qapp, monkeypatch)
    inst = InstanceMetadata(
        sop_instance_uid="uid1",
        series_uid="s1",
        modality="US",
        number_of_frames=10,
        pixel_spacing=(0.5, 0.5),
        frame_time_ms=33.3,
        series_description="T",
        path=Path("/tmp/x.dcm"),
        media_format="dicom",
    )
    ctrl._state_manager.set_instance(inst, total_frames=10, frame_time_ms=33.3)
    from datetime import datetime

    from echo_personal_tool.domain.models import SeriesMetadata, StudyMetadata

    study = StudyMetadata(
        study_uid="study1",
        study_datetime=datetime(2026, 1, 1, tzinfo=UTC),
        series=(
            SeriesMetadata(
                series_uid="s1",
                study_uid="study1",
                modality="US",
                description="T",
                instances=(inst,),
            ),
        ),
    )
    ctrl._studies = [study]

    m = LinearMeasurement(label="LVEDD", pixel_length=100, millimeter_length=50, sop_instance_uid="uid1")
    ctrl.on_linear_measurements_changed([m])
    assert len(ctrl._state_manager.snapshot.linear_measurements) == 1


def test_on_linear_measurements_changed_type_error(qapp, monkeypatch):
    ctrl = _make_controller(qapp, monkeypatch)
    with pytest.raises(TypeError):
        ctrl.on_linear_measurements_changed("bad")


# ── on_manual_calibration ────────────────────────────────────────────


def test_on_manual_calibration(qapp, monkeypatch):
    ctrl = _make_controller(qapp, monkeypatch)
    ctrl.on_manual_calibration((0.5, 0.5))
    assert ctrl._state_manager.snapshot.manual_pixel_spacing == (0.5, 0.5)


def test_on_manual_calibration_type_error(qapp, monkeypatch):
    ctrl = _make_controller(qapp, monkeypatch)
    with pytest.raises(TypeError):
        ctrl.on_manual_calibration("bad")


def test_on_manual_calibration_negative_raises(qapp, monkeypatch):
    ctrl = _make_controller(qapp, monkeypatch)
    with pytest.raises(ValueError):
        ctrl.on_manual_calibration((-1.0, 0.5))


# ── needs_manual_calibration ─────────────────────────────────────────


def test_needs_manual_calibration_no_instance(qapp, monkeypatch):
    ctrl = _make_controller(qapp, monkeypatch)
    assert ctrl.needs_manual_calibration() is False


def test_needs_manual_calibration_dicom(qapp, monkeypatch):
    ctrl = _make_controller(qapp, monkeypatch)
    inst = InstanceMetadata(
        sop_instance_uid="uid1",
        series_uid="s1",
        modality="US",
        number_of_frames=10,
        pixel_spacing=None,
        frame_time_ms=33.3,
        series_description="T",
        path=Path("/tmp/x.dcm"),
        media_format="dicom",
    )
    ctrl._state_manager.set_instance(inst, total_frames=10, frame_time_ms=33.3)
    assert ctrl.needs_manual_calibration() is False


def test_needs_manual_calibration_mp4_no_spacing(qapp, monkeypatch):
    ctrl = _make_controller(qapp, monkeypatch)
    inst = InstanceMetadata(
        sop_instance_uid="uid1",
        series_uid="s1",
        modality="US",
        number_of_frames=10,
        pixel_spacing=None,
        frame_time_ms=33.3,
        series_description="T",
        path=Path("/tmp/x.mp4"),
        media_format="mp4",
    )
    ctrl._state_manager.set_instance(inst, total_frames=10, frame_time_ms=33.3)
    ctrl._current_instance = inst
    from datetime import datetime

    from echo_personal_tool.domain.models import SeriesMetadata, StudyMetadata

    study = StudyMetadata(
        study_uid="study1",
        study_datetime=datetime(2026, 1, 1, tzinfo=UTC),
        series=(
            SeriesMetadata(
                series_uid="s1",
                study_uid="study1",
                modality="US",
                description="T",
                instances=(inst,),
            ),
        ),
    )
    ctrl._studies = [study]
    assert ctrl.needs_manual_calibration() is True


# ── clear_manual_calibration ─────────────────────────────────────────


def test_clear_manual_calibration(qapp, monkeypatch):
    ctrl = _make_controller(qapp, monkeypatch)
    ctrl.on_manual_calibration((0.5, 0.5))
    ctrl.clear_manual_calibration()
    assert ctrl._state_manager.snapshot.manual_pixel_spacing is None


def test_clear_manual_calibration_noop_when_empty(qapp, monkeypatch):
    ctrl = _make_controller(qapp, monkeypatch)
    ctrl.clear_manual_calibration()  # should not raise


# ── reset_measurements_and_calibration ───────────────────────────────


def test_reset_measurements_and_calibration(qapp, monkeypatch):
    ctrl = _make_controller(qapp, monkeypatch)
    inst = InstanceMetadata(
        sop_instance_uid="uid1",
        series_uid="s1",
        modality="US",
        number_of_frames=10,
        pixel_spacing=(0.5, 0.5),
        frame_time_ms=33.3,
        series_description="T",
        path=Path("/tmp/x.dcm"),
        media_format="dicom",
    )
    ctrl._state_manager.set_instance(inst, total_frames=10, frame_time_ms=33.3)
    ctrl.on_manual_calibration((1.0, 1.0))
    ctrl.reset_measurements_and_calibration()
    assert ctrl._state_manager.snapshot.manual_pixel_spacing is None
    assert ctrl._state_manager.snapshot.linear_measurements == ()


# ── _format_doppler_summary ──────────────────────────────────────────


def test_format_doppler_summary(qapp, monkeypatch):
    ctrl = _make_controller(qapp, monkeypatch)
    dto = DopplerMeasurementDTO(
        peaks=(DopplerPeakMarker(label="E", time_ms=100, velocity_cm_s=120),),
        intervals=(DopplerIntervalMarker(label="IVRT", start_time_ms=0, end_time_ms=80),),
        traces=(DopplerTrace(label="flow", points=((1, 2),)),),
    )
    text = ctrl._format_doppler_summary(dto)
    assert "1 peak" in text
    assert "1 interval" in text
    assert "1 trace" in text

    dto2 = DopplerMeasurementDTO(peaks=(), intervals=(), traces=())
    text2 = ctrl._format_doppler_summary(dto2)
    assert "0 peaks" in text2


# ── _resolve_study_uid ──────────────────────────────────────────────


def test_resolve_study_uid_no_instance(qapp, monkeypatch):
    ctrl = _make_controller(qapp, monkeypatch)
    assert ctrl.resolve_study_uid() == "__default__"


def test_resolve_study_uid_with_study(qapp, monkeypatch):
    ctrl = _make_controller(qapp, monkeypatch)
    from datetime import datetime

    from echo_personal_tool.domain.models import SeriesMetadata, StudyMetadata

    inst = InstanceMetadata(
        sop_instance_uid="uid1",
        series_uid="s1",
        modality="US",
        number_of_frames=10,
        pixel_spacing=None,
        frame_time_ms=33.3,
        series_description="T",
        path=Path("/tmp/x.dcm"),
        media_format="dicom",
    )
    study = StudyMetadata(
        study_uid="study1",
        study_datetime=datetime(2026, 1, 1, tzinfo=UTC),
        series=(
            SeriesMetadata(
                series_uid="s1",
                study_uid="study1",
                modality="US",
                description="T",
                instances=(inst,),
            ),
        ),
    )
    ctrl._studies = [study]
    ctrl._current_instance = inst
    assert ctrl.resolve_study_uid(inst) == "study1"


# ── load_first_instance_of_series ───────────────────────────────────


def test_load_first_instance_of_series_not_found(qapp, monkeypatch):
    ctrl = _make_controller(qapp, monkeypatch)
    failed = []
    ctrl.frame_load_failed.connect(failed.append)
    from datetime import datetime

    from echo_personal_tool.domain.models import StudyMetadata

    study = StudyMetadata(
        study_uid="study1",
        study_datetime=datetime(2026, 1, 1, tzinfo=UTC),
        series=(),
    )
    ctrl.load_first_instance_of_series(study, "nonexistent")
    assert len(failed) == 1


def test_load_first_instance_of_series_empty_instances(qapp, monkeypatch):
    ctrl = _make_controller(qapp, monkeypatch)
    failed = []
    ctrl.frame_load_failed.connect(failed.append)
    from datetime import datetime

    from echo_personal_tool.domain.models import SeriesMetadata, StudyMetadata

    study = StudyMetadata(
        study_uid="study1",
        study_datetime=datetime(2026, 1, 1, tzinfo=UTC),
        series=(
            SeriesMetadata(
                series_uid="s1",
                study_uid="study1",
                modality="US",
                description="T",
                instances=(),
            ),
        ),
    )
    ctrl.load_first_instance_of_series(study, "s1")
    assert "no instances" in failed[0].lower() or "no" in failed[0].lower()


# ── _gold_contour_matches (static method) ────────────────────────────


def test_gold_contour_matches_basic():
    c = Contour(phase="ED", view="A4C", chamber="LV", points=[], frame_index=5)
    assert AppController._gold_contour_matches(c, chamber="LV", phase="ED", frame_index=5) is True


def test_gold_contour_matches_wrong_chamber():
    c = Contour(phase="ED", view="A4C", chamber="LV", points=[])
    assert AppController._gold_contour_matches(c, chamber="LA", phase="ED", frame_index=0) is False


def test_gold_contour_matches_review_pending():
    c = Contour(phase="ED", view="A4C", chamber="LV", points=[], review_pending=True)
    assert AppController._gold_contour_matches(c, chamber="LV", phase="ED", frame_index=0) is False


def test_gold_contour_matches_frame_index_mismatch():
    c = Contour(phase="ED", view="A4C", chamber="LV", points=[], frame_index=3)
    assert AppController._gold_contour_matches(c, chamber="LV", phase="ED", frame_index=5) is False


def test_gold_contour_matches_frame_index_none():
    c = Contour(phase="ED", view="A4C", chamber="LV", points=[], frame_index=None)
    assert AppController._gold_contour_matches(c, chamber="LV", phase="ED", frame_index=99) is True


# ── load_instance with no path ───────────────────────────────────────


def test_load_instance_no_path(qapp, monkeypatch):
    ctrl = _make_controller(qapp, monkeypatch)
    failed = []
    ctrl.frame_load_failed.connect(failed.append)
    inst = InstanceMetadata(
        sop_instance_uid="uid1",
        series_uid="s1",
        modality="US",
        number_of_frames=10,
        pixel_spacing=None,
        frame_time_ms=33.3,
        series_description="T",
        path=None,
        media_format="dicom",
    )
    ctrl.load_instance(inst)
    assert "no file path" in failed[0].lower()


# ── on_doppler_markers_changed ───────────────────────────────────────


def test_on_doppler_markers_changed_type_error(qapp, monkeypatch):
    ctrl = _make_controller(qapp, monkeypatch)
    with pytest.raises(TypeError):
        ctrl.on_doppler_markers_changed("bad")


def test_on_doppler_markers_changed_valid(qapp, monkeypatch):
    ctrl = _make_controller(qapp, monkeypatch)
    inst = InstanceMetadata(
        sop_instance_uid="uid1",
        series_uid="s1",
        modality="US",
        number_of_frames=10,
        pixel_spacing=(0.5, 0.5),
        frame_time_ms=33.3,
        series_description="T",
        path=Path("/tmp/x.dcm"),
        media_format="dicom",
    )
    ctrl._state_manager.set_instance(inst, total_frames=10, frame_time_ms=33.3)
    from datetime import datetime

    from echo_personal_tool.domain.models import SeriesMetadata, StudyMetadata

    study = StudyMetadata(
        study_uid="study1",
        study_datetime=datetime(2026, 1, 1, tzinfo=UTC),
        series=(
            SeriesMetadata(
                series_uid="s1",
                study_uid="study1",
                modality="US",
                description="T",
                instances=(inst,),
            ),
        ),
    )
    ctrl._studies = [study]
    dto = DopplerMeasurementDTO(
        peaks=(DopplerPeakMarker(label="E", time_ms=100, velocity_cm_s=120),),
        intervals=(),
        traces=(),
    )
    ctrl.on_doppler_markers_changed(dto)


# ── on_doppler_calibration_changed ───────────────────────────────────


def test_on_doppler_calibration_changed_type_error(qapp, monkeypatch):
    ctrl = _make_controller(qapp, monkeypatch)
    with pytest.raises(TypeError):
        ctrl.on_doppler_calibration_changed("bad")


def test_on_doppler_calibration_changed_no_instance(qapp, monkeypatch):
    ctrl = _make_controller(qapp, monkeypatch)
    roi = DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50)
    cal = DopplerCalibrationState(roi=roi, baseline_y_px=25)
    ctrl.on_doppler_calibration_changed(cal)  # no-op


# ── on_mmode_time_calibration ────────────────────────────────────────


def test_on_mmode_time_calibration_type_error(qapp, monkeypatch):
    ctrl = _make_controller(qapp, monkeypatch)
    with pytest.raises(TypeError):
        ctrl.on_mmode_time_calibration("bad")


# ── on_mmode_calibration_changed ─────────────────────────────────────


def test_on_mmode_calibration_changed_type_error(qapp, monkeypatch):
    ctrl = _make_controller(qapp, monkeypatch)
    with pytest.raises(TypeError):
        ctrl.on_mmode_calibration_changed("bad")


def test_on_mmode_calibration_changed_no_instance(qapp, monkeypatch):
    ctrl = _make_controller(qapp, monkeypatch)
    roi = DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50)
    mmode = MmodeCalibrationState(roi=roi, vertical_mm_per_pixel=0.5)
    ctrl.on_mmode_calibration_changed(mmode)  # no-op
