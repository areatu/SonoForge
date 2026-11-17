"""Tab isolation and per-tab clinical memory.

Tab switching hands the new study set to the controller
(``load_pre_scanned_studies``) and then activates the clip (``load_instance``).
The parked tab owns the values its clinician typed: manual calibration, manual
BSA, calculator overrides and contours survive a round trip through another tab,
while a fresh tab and a new source in the same tab start empty.  With local
measurement storage enabled the disk record stays the authority and no RAM copy
is parked.

These tests drive the real controller path with fake decode workers, as the
other controller tests do.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import numpy as np
import pytest

pytestmark = pytest.mark.gui

from echo_personal_tool.application.app_controller import AppController  # noqa: E402
from echo_personal_tool.application.tab_clinical_memory import TabClinicalMemory  # noqa: E402
from echo_personal_tool.domain.models.contour import Contour  # noqa: E402
from echo_personal_tool.domain.models.metadata import InstanceMetadata, SeriesMetadata, StudyMetadata
from echo_personal_tool.domain.models.ste_analysis import StrainAnalysis, StrainStudy  # noqa: E402

_MODULE = "echo_personal_tool.application.app_controller"
_BSA_INPUT = "bsa"


class _FakeSignal:
    def __init__(self) -> None:
        self._callbacks: list = []

    def connect(self, callback, *args, **kwargs) -> None:
        self._callbacks.append(callback)

    def emit(self, *args) -> None:
        for callback in list(self._callbacks):
            callback(*args)


class _FakeWorker:
    def __init__(self, *args, **kwargs) -> None:
        names = (
            "first_frame_ready",
            "progress",
            "finished",
            "failed",
            "error",
            "batch_finished",
            "batch_decoded",
            "timed_out",
        )
        self.signals = SimpleNamespace(**{name: _FakeSignal() for name in names})
        self.setAutoDelete = lambda _value: None


class _FakeAnalysisWorker:
    """Distinct type: an analysis worker is not a FrameLoaderWorker."""

    def __init__(self, *args, **kwargs) -> None:
        self.signals = _FakeWorker().signals
        self.setAutoDelete = lambda _value: None


class _RecordingThreadPool:
    def __init__(self) -> None:
        self.started: list = []

    def start(self, worker) -> None:
        self.started.append(worker)


@pytest.fixture
def controller(qapp, monkeypatch) -> AppController:  # qapp: the controller needs a live QApplication
    for name in ("DicomDecodeWorker", "VideoDecodeWorker", "FrameLoaderWorker", "ThumbnailLoaderWorker", "ScanWorker"):
        monkeypatch.setattr(f"{_MODULE}.{name}", _FakeWorker)
    monkeypatch.setattr(
        "echo_personal_tool.application.workers.speckle_worker.SpeckleTrackingWorker", _FakeAnalysisWorker
    )
    pool = _RecordingThreadPool()
    controller = AppController(thread_pool=pool)
    controller.test_thread_pool = pool
    return controller


def _studies(prefix: str, root) -> list[StudyMetadata]:
    def instance(index: int) -> InstanceMetadata:
        return InstanceMetadata(
            sop_instance_uid=f"{prefix}.{index}",
            series_uid=f"{prefix}.series",
            modality="US",
            number_of_frames=4,
            pixel_spacing=(0.5, 0.5),
            frame_time_ms=33.3,
            series_description="A4C",
            path=root / f"{prefix}{index}.dcm",
        )

    series = SeriesMetadata(
        series_uid=f"{prefix}.series",
        study_uid=f"{prefix}.study",
        modality="US",
        description="A4C",
        instances=(instance(0), instance(1)),
    )
    return [StudyMetadata(study_uid=f"{prefix}.study", study_datetime=datetime(2026, 10, 1, 9), series=(series,))]


def _switch_to(
    controller: AppController,
    studies: list[StudyMetadata],
    clinical_memory: TabClinicalMemory | None = None,
) -> None:
    """What the tab layer does on a switch: hand over the studies, then activate the clip."""
    controller.load_pre_scanned_studies(studies, clinical_memory=clinical_memory)
    controller.load_instance(studies[0].series[0].instances[0])


def _manual_bsa(controller: AppController) -> float | None:
    """The BSA the calculators actually use, through the public study snapshot."""
    snapshot = controller.compute_study_snapshot()
    calculations = snapshot.calculations if snapshot is not None else None
    entry = calculations.input(_BSA_INPUT) if calculations is not None else None
    return entry.value if entry is not None else None


def _contour() -> Contour:
    return Contour(phase="ED", view="A4C", chamber="LV", points=[(0.0, 0.0), (10.0, 0.0), (5.0, 10.0)])


def _finish_strain(controller: AppController, gls: float = -18.5) -> None:
    """Run the public speckle path and deliver the fake worker's result."""
    from echo_personal_tool.domain.models.speckle import StrainResult

    controller.run_speckle_tracking(_contour())
    worker = controller.test_thread_pool.started[-1]
    worker.signals.finished.emit(StrainResult(longitudinal=np.zeros(2), radial=np.zeros(2), gls=gls))


def test_a_fresh_tab_does_not_receive_the_other_tab_values(controller, tmp_path) -> None:
    a = _studies("a", tmp_path)
    b = _studies("b", tmp_path)
    _switch_to(controller, a, TabClinicalMemory())
    assert controller.on_manual_calibration((0.3, 0.3))
    controller.set_calculator_input(_BSA_INPUT, 1.9)
    controller.on_contours_changed([_contour()])

    _switch_to(controller, b, TabClinicalMemory())

    snapshot = controller.state_manager.snapshot
    assert snapshot.manual_pixel_spacing is None
    assert snapshot.effective_pixel_spacing == (0.5, 0.5), "tab B measures with its own file spacing"
    assert snapshot.contours == ()
    assert _manual_bsa(controller) is None


def test_returning_to_a_tab_restores_calibration_bsa_and_contours(controller, tmp_path) -> None:
    a = _studies("a", tmp_path)
    b = _studies("b", tmp_path)
    _switch_to(controller, a, TabClinicalMemory())
    assert controller.on_manual_calibration((0.3, 0.3))
    controller.set_calculator_input(_BSA_INPUT, 1.9)
    controller.on_contours_changed([_contour()])
    parked_a = controller.snapshot_tab_clinical_memory()
    assert parked_a is not None

    _switch_to(controller, b, TabClinicalMemory())
    _switch_to(controller, a, parked_a)

    snapshot = controller.state_manager.snapshot
    assert snapshot.manual_pixel_spacing == (0.3, 0.3)
    assert snapshot.contours and snapshot.contours[0].points == [(0.0, 0.0), (10.0, 0.0), (5.0, 10.0)]
    assert _manual_bsa(controller) == 1.9


def test_each_tab_keeps_its_own_values_for_the_same_study(controller, tmp_path) -> None:
    studies = _studies("same", tmp_path)
    _switch_to(controller, studies, TabClinicalMemory())
    assert controller.on_manual_calibration((0.3, 0.3))
    controller.set_calculator_input(_BSA_INPUT, 1.9)
    parked_first = controller.snapshot_tab_clinical_memory()

    _switch_to(controller, studies, TabClinicalMemory())
    assert controller.state_manager.snapshot.manual_pixel_spacing is None, "a second tab starts empty"
    assert controller.on_manual_calibration((0.7, 0.7))
    controller.set_calculator_input(_BSA_INPUT, 1.5)
    parked_second = controller.snapshot_tab_clinical_memory()

    assert parked_first is not None and parked_second is not None
    _switch_to(controller, studies, parked_first)
    assert controller.state_manager.snapshot.manual_pixel_spacing == (0.3, 0.3)
    assert _manual_bsa(controller) == 1.9

    _switch_to(controller, studies, parked_second)
    assert controller.state_manager.snapshot.manual_pixel_spacing == (0.7, 0.7)
    assert _manual_bsa(controller) == 1.5


def test_a_new_source_in_the_same_tab_starts_without_memory(controller, tmp_path) -> None:
    a = _studies("a", tmp_path)
    c = _studies("c", tmp_path)
    _switch_to(controller, a, TabClinicalMemory())
    assert controller.on_manual_calibration((0.3, 0.3))
    controller.set_calculator_input(_BSA_INPUT, 1.9)
    assert controller.snapshot_tab_clinical_memory() is not None

    _switch_to(controller, c, None)

    assert controller.state_manager.snapshot.manual_pixel_spacing is None
    assert _manual_bsa(controller) is None


def test_cine_heart_rate_estimate_returns_with_its_tab(controller, tmp_path) -> None:
    a = _studies("a", tmp_path)
    b = _studies("b", tmp_path)
    _switch_to(controller, a, TabClinicalMemory())
    controller.record_heart_rate_estimate(72, "cine")
    parked_a = controller.snapshot_tab_clinical_memory()

    _switch_to(controller, b, TabClinicalMemory())
    assert parked_a is not None
    _switch_to(controller, a, parked_a)

    snapshot = controller.compute_study_snapshot()
    calculations = snapshot.calculations if snapshot is not None else None
    heart_rate = calculations.input("hr") if calculations is not None else None
    assert heart_rate is not None
    assert heart_rate.value == 72


def test_strain_results_are_parked_with_the_tab(controller, tmp_path) -> None:
    studies = _studies("a", tmp_path)
    _switch_to(controller, studies, TabClinicalMemory())
    _finish_strain(controller)
    assert controller.strain_study("a.study") is not None
    parked = controller.snapshot_tab_clinical_memory()
    assert parked is not None
    assert set(parked.strain_studies) == {"a.study"}

    _switch_to(controller, _studies("b", tmp_path), TabClinicalMemory())
    assert controller.strain_study("a.study") is None, "another tab does not inherit the analyses"

    _switch_to(controller, studies, parked)
    restored = controller.strain_study("a.study")
    assert restored is not None
    assert restored.view_gls("A4C") == pytest.approx(-18.5)


def test_the_playback_fps_returns_with_its_tab_and_does_not_leak(controller, tmp_path) -> None:
    studies = _studies("a", tmp_path)
    _switch_to(controller, studies, TabClinicalMemory())
    controller.set_frame_time_override(40.0)
    parked = controller.snapshot_tab_clinical_memory()
    assert parked is not None
    assert parked.frame_time_overrides == {"a.0": 40.0}

    _switch_to(controller, studies, TabClinicalMemory())
    assert controller.state_manager.snapshot.frame_time_ms != 40.0, "another tab keeps the file timing"

    _switch_to(controller, studies, parked)
    assert controller.state_manager.snapshot.frame_time_ms == 40.0
    assert controller.state_manager.snapshot.instance.frame_time_ms == 33.3, "the file timebase is untouched"

    _switch_to(controller, _studies("c", tmp_path), None)
    assert controller.state_manager.snapshot.frame_time_ms != 40.0, "a new source in the tab starts clean"


def test_strain_analyses_return_with_their_tab(controller, tmp_path) -> None:
    studies = _studies("a", tmp_path)
    analysis = StrainAnalysis(view="A4C", gls=-18.5)
    memory = TabClinicalMemory(strain_studies={"a.study": StrainStudy(analyses={"A4C": analysis})})

    _switch_to(controller, studies, memory)
    restored = controller.strain_study("a.study")

    assert restored is not None
    assert restored.view_gls("A4C") == pytest.approx(-18.5)


def test_a_refused_flush_reports_that_the_load_never_started(controller, monkeypatch, tmp_path) -> None:
    studies = _studies("a", tmp_path)
    _switch_to(controller, studies, TabClinicalMemory())
    assert controller.on_manual_calibration((0.3, 0.3))
    blocked: list[bool] = []
    controller.persistence_blocked.connect(lambda: blocked.append(True))
    monkeypatch.setattr(controller.measurement_persistence, "flush", lambda *args, **kwargs: False)

    assert controller.load_pre_scanned_studies(studies) is False
    assert blocked, "the refusal is still reported loudly"
    assert controller.state_manager.snapshot.manual_pixel_spacing == (0.3, 0.3), "state was never touched"


def test_a_started_load_reports_true(controller, tmp_path) -> None:
    assert controller.load_pre_scanned_studies(_studies("a", tmp_path)) is True


def test_persistence_on_keeps_the_disk_record_as_the_authority(controller, tmp_path) -> None:
    _switch_to(controller, _studies("a", tmp_path), TabClinicalMemory())
    assert controller.on_manual_calibration((0.3, 0.3))

    controller.measurement_persistence.enabled = True
    try:
        assert controller.snapshot_tab_clinical_memory() is None
    finally:
        controller.measurement_persistence.enabled = False


def test_persistence_on_ignores_a_snapshot_parked_before_it_was_enabled(controller, monkeypatch, tmp_path) -> None:
    studies = _studies("a", tmp_path)
    _switch_to(controller, studies, TabClinicalMemory())
    assert controller.on_manual_calibration((0.3, 0.3))
    parked = controller.snapshot_tab_clinical_memory()
    assert parked is not None

    # Enabling persistence makes the disk record the authority: the RAM copy
    # taken while it was off must not be restored over it.
    monkeypatch.setattr(controller.measurement_persistence, "load", lambda *args, **kwargs: args[1]())
    controller.measurement_persistence.enabled = True
    try:
        _switch_to(controller, studies, parked)
        assert controller.state_manager.snapshot.manual_pixel_spacing is None
        assert _manual_bsa(controller) is None
    finally:
        controller.measurement_persistence.enabled = False


def _strain_payload(gls=-18.5):
    from echo_personal_tool.domain.models.speckle import StrainResult

    return StrainResult(longitudinal=np.zeros(2), radial=np.zeros(2), gls=gls)


@pytest.mark.parametrize(
    "change", ["calibration", "calibration_undo", "contour", "reload", "tab_roundtrip", "reset", "timebase", "close"]
)
def test_pending_ste_cannot_publish_after_context_changes(controller, tmp_path, change):
    from dataclasses import replace

    studies = _studies("a", tmp_path)
    _switch_to(controller, studies, TabClinicalMemory())
    contour = _contour()
    controller.on_contours_changed([contour])
    delivered = []
    controller.speckle_result_ready.connect(delivered.append)
    controller.run_speckle_tracking(contour)
    worker = controller.test_thread_pool.started[-1]

    if change.startswith("calibration"):
        assert controller.on_manual_calibration((0.3, 0.3))
        if change == "calibration_undo":
            controller.clear_manual_calibration()
    elif change == "contour":
        controller.on_contours_changed([replace(contour, revision=1)])
    elif change == "reload":
        controller.load_instance(studies[0].series[0].instances[0])
    elif change == "tab_roundtrip":
        _switch_to(controller, _studies("b", tmp_path), TabClinicalMemory())
        _switch_to(controller, studies, TabClinicalMemory())
    elif change == "reset":
        controller.reset_measurements_and_calibration()
    elif change == "close":
        controller.load_pre_scanned_studies([])
    else:
        controller.state_manager.set_frame_time(40.0)

    statuses = []
    controller.status_message.connect(statuses.append)
    worker.signals.error.emit("old error")
    worker.signals.finished.emit(_strain_payload())
    assert not delivered
    assert not statuses, "neither stale error nor success may change the new UI"
    assert controller.strain_study("a.study") is None


def test_ste_new_request_supersedes_old_success_and_error(controller, tmp_path):
    _switch_to(controller, _studies("a", tmp_path), TabClinicalMemory())
    controller.run_speckle_tracking(_contour())
    first = controller.test_thread_pool.started[-1]
    controller.run_speckle_tracking(_contour())
    second = controller.test_thread_pool.started[-1]
    delivered = []
    controller.speckle_result_ready.connect(delivered.append)
    first.signals.finished.emit(_strain_payload(-10))
    first.signals.error.emit("obsolete")
    assert not delivered
    second.signals.finished.emit(_strain_payload(-20))
    second.signals.finished.emit(_strain_payload(-30))
    assert len(delivered) == 1
    assert controller.strain_study("a.study").view_gls("A4C") == pytest.approx(-20)


def test_ste_remains_publishable_during_frame_navigation(controller, tmp_path):
    _switch_to(controller, _studies("a", tmp_path), TabClinicalMemory())
    controller.run_speckle_tracking(_contour())
    worker = controller.test_thread_pool.started[-1]
    controller.state_manager.set_frame(2)
    worker.signals.finished.emit(_strain_payload())
    assert controller.strain_study("a.study") is not None


def test_queued_ste_result_is_rechecked_when_gui_consumes_it(controller, tmp_path, monkeypatch, qtbot):
    from PySide6.QtCore import QObject, Qt, Signal

    class Signals(QObject):
        finished = Signal(object)
        error = Signal(str)

    class Worker:
        def __init__(self, **kwargs):
            self.signals = Signals()

        def setAutoDelete(self, enabled):  # noqa: N802 - Qt API
            pass

    monkeypatch.setattr("echo_personal_tool.application.workers.speckle_worker.SpeckleTrackingWorker", Worker)
    _switch_to(controller, _studies("a", tmp_path), TabClinicalMemory())
    delivered = []
    controller.speckle_result_ready.connect(delivered.append)
    controller.run_speckle_tracking(_contour())
    worker = controller.test_thread_pool.started[-1]
    consumed = []
    worker.signals.finished.connect(lambda _: consumed.append(True), Qt.ConnectionType.QueuedConnection)
    worker.signals.finished.emit(_strain_payload())
    assert not consumed  # terminal callback is still queued
    assert controller.on_manual_calibration((0.3, 0.3))
    qtbot.waitUntil(lambda: bool(consumed))
    assert not delivered
    assert controller.strain_study("a.study") is None


def test_current_ste_error_is_reported_once_without_publishing_a_result(controller, tmp_path):
    from echo_personal_tool.application.localization import tr

    _switch_to(controller, _studies("a", tmp_path), TabClinicalMemory())
    controller.run_speckle_tracking(_contour())
    worker = controller.test_thread_pool.started[-1]
    statuses = []
    controller.status_message.connect(statuses.append)
    worker.signals.error.emit("private backend details")
    worker.signals.error.emit("duplicate")
    worker.signals.finished.emit(_strain_payload())
    assert statuses == [tr("app.speckle_error")]
    assert controller.strain_study("a.study") is None
