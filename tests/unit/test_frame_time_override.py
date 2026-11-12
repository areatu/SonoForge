"""Session FPS override from the transport's «FPS» label (double-click).

The value is per SOP Instance UID and is parked with its tab, and it is a
*viewing* retiming («скорость прокрутки»): it moves the playback interval and
the transport's FPS label through the state, while the instance keeps the
file's own timebase — Auto-HR, the D/S phase timeline and MP4 export must
never depend on how fast the clip is played back.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.gui
from PySide6.QtWidgets import QApplication

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.domain.models.metadata import InstanceMetadata


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _instance(uid: str = "1.2.3.fps", frame_time_ms: float | None = 33.3) -> InstanceMetadata:
    return InstanceMetadata(
        sop_instance_uid=uid,
        series_uid="1.2.3.series",
        modality="US",
        number_of_frames=30,
        pixel_spacing=None,
        frame_time_ms=frame_time_ms,
        series_description="A4C",
        path=Path("/nonexistent/clip.dcm"),
        media_format="dicom",
    )


def _controller(qapp) -> AppController:
    controller = AppController()
    # The controller retimes through state emission; its own playback listener
    # would start a decode of the nonexistent test path on that emission.
    controller.state_manager.state_changed.disconnect(controller._on_state_changed)
    instance = _instance()
    controller.state_manager.set_instance(instance, total_frames=30, frame_time_ms=33.3, emit=False)
    controller.state_manager._current_frame_index = 7
    return controller


def test_override_retimes_playback_but_never_the_measurements_timebase(qapp):
    """The regression pin: HR/phase read instance.frame_time_ms, which must stay file-timed."""
    controller = _controller(qapp)

    controller.set_frame_time_override(1000.0 / 60.0)  # user typed 60 fps

    snapshot = controller.state_manager.snapshot
    # Playback + the FPS label see the new rate…
    assert snapshot.frame_time_ms == pytest.approx(16.667, rel=1e-3)
    # …while the file timebase every measurement reads is untouched.
    assert snapshot.instance is not None
    assert snapshot.instance.frame_time_ms == pytest.approx(33.3)
    assert controller._playback_frame_time_ms(snapshot.instance) == pytest.approx(16.667, rel=1e-3)
    assert snapshot.current_frame_index == 7  # the playhead stays put
    assert snapshot.total_frames == 30


def test_the_override_is_reapplied_when_the_clip_is_loaded_again(qapp):
    controller = _controller(qapp)
    controller.set_frame_time_override(20.0)  # frame time in ms (50 fps)

    # The next load of that clip plays at the override; another clip does not.
    assert controller._playback_frame_time_ms(_instance()) == pytest.approx(20.0)
    other = _instance(uid="9.9.9")
    assert controller._playback_frame_time_ms(other) == pytest.approx(33.3)


def test_clearing_the_override_restores_the_file_timing(qapp):
    controller = _controller(qapp)
    controller.set_frame_time_override(50.0)
    assert controller._frame_time_overrides

    controller.set_frame_time_override(None)

    assert controller._frame_time_overrides == {}
    snapshot = controller.state_manager.snapshot
    assert snapshot.frame_time_ms == pytest.approx(33.3)
    assert controller._playback_frame_time_ms(snapshot.instance) == pytest.approx(33.3)


def test_override_without_a_clip_is_a_noop(qapp):
    controller = AppController()
    controller.state_manager.state_changed.disconnect(controller._on_state_changed)
    controller.set_frame_time_override(60.0)
    assert controller._frame_time_overrides == {}
