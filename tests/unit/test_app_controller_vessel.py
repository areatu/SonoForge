"""Tests for AppController.accept_vessel_measurement."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from echo_personal_tool.domain.models.vessel_measurement import VesselMeasurement

pytestmark = pytest.mark.gui

from PySide6.QtWidgets import QApplication

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.domain.models import InstanceMetadata


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


def _m() -> VesselMeasurement:
    return VesselMeasurement(
        psv_cm_s=178.4,
        edv_cm_s=62.1,
        ri=0.65,
        sd=2.87,
        mv_approx=100.9,
        sop_instance_uid="UID",
        frame_index=0,
    )


def test_accept_vessel_measurement_returns_bool(qapp, monkeypatch):
    ctrl = _make_controller(qapp, monkeypatch)
    assert isinstance(ctrl.accept_vessel_measurement(_m()), bool)


def test_accept_vessel_measurement_rejects_non_vessel(qapp, monkeypatch):
    ctrl = _make_controller(qapp, monkeypatch)
    with pytest.raises(TypeError):
        ctrl.accept_vessel_measurement("not a vessel measurement")  # type: ignore[arg-type]


def test_accept_vessel_measurement_stores(qapp, monkeypatch):
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
    from datetime import UTC, datetime

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

    measurement = VesselMeasurement(
        psv_cm_s=178.4,
        edv_cm_s=62.1,
        ri=0.65,
        sd=2.87,
        mv_approx=100.9,
        sop_instance_uid="uid1",
        frame_index=0,
    )
    assert ctrl.accept_vessel_measurement(measurement) is True
    snapshot = ctrl._state_manager.snapshot.measurement_snapshot
    assert snapshot is not None
    assert snapshot.vessel_measurements == (measurement,)
