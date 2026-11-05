"""S-02 Isolation: a calibration and a manual override never move to another tab.

Tab switching hands the new study set to the controller (``load_pre_scanned_studies``)
and then activates the clip (``load_instance``).  The tab's own view state carries only
W/L, overlay and frame, so the isolation contract lives in the controller and the
per-study measurement store.  These tests drive that real path in both directions with
fake decode workers, as the other controller tests do.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.gui

from echo_personal_tool.application.app_controller import AppController  # noqa: E402
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


def _switch_to(controller: AppController, studies: list[StudyMetadata]) -> None:
    """What the tab layer does on a switch: hand over the studies, then activate the clip."""
    controller.load_pre_scanned_studies(studies)
    controller.load_instance(studies[0].series[0].instances[0])


def test_manual_calibration_and_bsa_do_not_move_to_the_other_tab(controller, tmp_path) -> None:
    a = _studies("a", tmp_path)
    b = _studies("b", tmp_path)
    _switch_to(controller, a)
    assert controller.on_manual_calibration((0.3, 0.3))
    controller.set_calculator_input(_BSA_INPUT, 1.9)
    assert controller._state_manager.snapshot.manual_pixel_spacing == (0.3, 0.3)

    _switch_to(controller, b)

    snapshot = controller._state_manager.snapshot
    assert snapshot.manual_pixel_spacing is None
    assert snapshot.effective_pixel_spacing == (0.5, 0.5), "tab B measures with its own file spacing"
    assert controller._measurement_session.get("b.study").manual_pixel_spacing is None
    assert controller._measurement_session.get("b.study").manual_bsa_m2 is None
    assert controller._calculator_inputs.manual("b.study") == {}


def test_calibration_and_bsa_of_the_other_tab_do_not_leak_back(controller, tmp_path) -> None:
    a = _studies("a", tmp_path)
    b = _studies("b", tmp_path)
    _switch_to(controller, a)
    controller.on_manual_calibration((0.3, 0.3))
    controller.set_calculator_input(_BSA_INPUT, 1.9)
    _switch_to(controller, b)
    assert controller.on_manual_calibration((0.7, 0.7))
    controller.set_calculator_input(_BSA_INPUT, 1.5)
    assert controller._state_manager.snapshot.manual_pixel_spacing == (0.7, 0.7)

    _switch_to(controller, a)

    snapshot = controller._state_manager.snapshot
    assert snapshot.manual_pixel_spacing is None, "B's calibration must not reach tab A"
    assert snapshot.effective_pixel_spacing == (0.5, 0.5)
    assert controller._measurement_session.get("a.study").manual_bsa_m2 is None
    assert controller._calculator_inputs.manual("a.study") == {}
