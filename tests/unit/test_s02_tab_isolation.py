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

import pytest

pytestmark = pytest.mark.gui

from echo_personal_tool.application.app_controller import AppController  # noqa: E402
from echo_personal_tool.application.tab_clinical_memory import TabClinicalMemory  # noqa: E402
from echo_personal_tool.domain.models.contour import Contour  # noqa: E402
from echo_personal_tool.domain.models.metadata import InstanceMetadata, SeriesMetadata, StudyMetadata  # noqa: E402

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
        names = ("first_frame_ready", "progress", "finished", "failed", "batch_finished", "batch_decoded", "timed_out")
        self.signals = SimpleNamespace(**{name: _FakeSignal() for name in names})
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
    return AppController(thread_pool=_RecordingThreadPool())


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


def test_persistence_on_keeps_the_disk_record_as_the_authority(controller, tmp_path) -> None:
    _switch_to(controller, _studies("a", tmp_path), TabClinicalMemory())
    assert controller.on_manual_calibration((0.3, 0.3))

    controller.measurement_persistence.enabled = True
    try:
        assert controller.snapshot_tab_clinical_memory() is None
    finally:
        controller.measurement_persistence.enabled = False
