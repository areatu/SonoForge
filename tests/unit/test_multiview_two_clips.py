from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.gui

from echo_personal_tool.domain.models.metadata import SeriesMetadata, StudyMetadata
from echo_personal_tool.domain.models.multiview import PaneId, PlaybackMode

#: ``(viewer, pixels)`` pairs that really reached ``ViewerWidget.show_frame``.
_PAINT_LOG: list[tuple[object, np.ndarray]] = []

#: Wall clock the controller sees; driven by the tests instead of by Qt timers.
_CLOCK: dict[str, float] = {"now": 1_000_000.0}


@pytest.fixture()
def clips(tmp_path: Path):
    import pydicom

    from tests.fixtures.generate_synthetic_dicom import write_synthetic_multiframe_dicom

    study_uid = "1.2.3.4.5"
    left = write_synthetic_multiframe_dicom(
        tmp_path / "a4c.dcm",
        frame_count=30,
        study_uid=study_uid,
        series_uid="1.2.3.4.5.1",
        sop_uid="1.2.3.4.5.10",
        series_description="A4C",
    )
    right = write_synthetic_multiframe_dicom(
        tmp_path / "a2c.dcm",
        frame_count=40,
        study_uid=study_uid,
        series_uid="1.2.3.4.5.2",
        sop_uid="1.2.3.4.5.20",
        series_description="A2C",
    )
    # a time-based common window is only plannable when the clips carry a frame rate
    for path in (left, right):
        dataset = pydicom.dcmread(path)
        dataset.FrameTime = "33.0"
        dataset.save_as(path)
    return left, right


def _study() -> StudyMetadata:
    """Both fixtures belong to this single study (spec §10.2)."""
    from datetime import datetime

    return StudyMetadata(
        study_uid="1.2.3.4.5",
        study_datetime=datetime(2024, 6, 1, 12, 0, 0),
        series=(
            SeriesMetadata("1.2.3.4.5.1", "1.2.3.4.5", "US", "A4C", ()),
            SeriesMetadata("1.2.3.4.5.2", "1.2.3.4.5", "US", "A2C", ()),
        ),
    )


@pytest.fixture()
def multiview(qtbot, monkeypatch, clips, isolated_qsettings):
    from unittest.mock import patch

    from echo_personal_tool.application.app_controller import AppController
    from echo_personal_tool.infrastructure.dicom_metadata_mapper import read_header_metadata
    from echo_personal_tool.infrastructure.user_preferences import UserPreferences
    from echo_personal_tool.presentation.main_window import MainWindow
    from echo_personal_tool.presentation.viewer_widget import ViewerWidget

    _record_paints(monkeypatch, ViewerWidget)
    left_path, right_path = clips
    prefs = UserPreferences(layout_state_json="", auto_play=False)
    with (
        patch("echo_personal_tool.presentation.main_window.apply_clinical_theme"),
        patch("echo_personal_tool.presentation.main_window.save_user_preferences"),
    ):
        window = MainWindow(controller=AppController(), user_preferences=prefs)
    window._controller._studies = [_study()]
    # one shared monotonic clock for the whole session (spec §11.4)
    _CLOCK["now"] = 1_000_000.0
    monkeypatch.setattr(window._multiview, "_now_ms", lambda: _CLOCK["now"])
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    qtbot.waitExposed(window)
    # This fixture models the loaded-study state that enables pane creation;
    # an empty workspace intentionally remains on the welcome page.
    window._has_loaded_study = True
    window._set_start_page_visible(False)
    window._on_multiview_button()
    qtbot.wait(50)

    # left pane: the main viewer loads the clip through the controller
    window._controller.load_instance(read_header_metadata(left_path))
    window._sync_left_pane_from_controller()
    # right pane: Multiview owns the loader
    window._multiview.load_instance(PaneId.RIGHT, read_header_metadata(right_path), "1.2.3.4.5")
    window._multiview.refresh()
    _wait_for_frames(qtbot, window, PaneId.RIGHT)
    yield window
    window._multiview.shutdown()


def _record_paints(monkeypatch, viewer_cls) -> None:
    """Wrap ``ViewerWidget.show_frame`` so the test can assert what reached the GPU."""
    _PAINT_LOG.clear()
    original = viewer_cls.show_frame

    def wrapper(self, pixels, *args, **kwargs):
        _PAINT_LOG.append((self, np.asarray(pixels)))
        return original(self, pixels, *args, **kwargs)

    monkeypatch.setattr(viewer_cls, "show_frame", wrapper)


def _painted(window, pane_id: PaneId) -> list[int]:
    """Frame indices this pane's viewer actually received (see ``_record_paints``)."""
    viewer = _pane_widget(window, pane_id).viewer
    return [int(pixels[0, 0]) for owner, pixels in _PAINT_LOG if owner is viewer]


def _pane_widget(window, pane_id: PaneId):
    return window._pane_left if pane_id is PaneId.LEFT else window._pane_right


def _wait_for_frames(qtbot, window, pane_id: PaneId, expected: int = 1, timeout_ms: int = 4000) -> None:
    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        qtbot.wait(20)
        if len(_painted(window, pane_id)) >= expected:
            return
    raise AssertionError(f"pane {pane_id} never painted {expected} frames")


def _drive(qtbot, window, seconds: float, step: float = 0.02) -> None:
    """Advance the shared clock by ``seconds`` in ``step`` increments.

    The panes load frames on the global thread pool, so the event loop runs
    between two ticks for the answers to arrive.
    """
    ticks = max(1, int(round(seconds / step)))
    for _ in range(ticks):
        _tick(window, step)
        qtbot.wait(1)
    # let the last frame request land before the assertions run
    qtbot.wait(30)


def _tick(window, seconds: float) -> None:
    """Advance the clock by exactly ``seconds`` and run one controller tick."""
    _CLOCK["now"] += seconds * 1000.0
    window._multiview._on_clock_tick()


class TestTwoClipPlayback:
    def test_both_panes_hold_a_clip_of_the_same_study(self, multiview, qtbot) -> None:
        left = multiview._multiview.session.pane(PaneId.LEFT)
        right = multiview._multiview.session.pane(PaneId.RIGHT)
        assert left.instance_uid == "1.2.3.4.5.10"
        assert right.instance_uid == "1.2.3.4.5.20"
        assert left.study_uid == right.study_uid == "1.2.3.4.5"
        assert multiview._multiview.session.clips_are_comparable()

    def test_headers_show_both_clips(self, multiview, qtbot) -> None:
        for pane, expected_name in (
            (multiview._pane_left, "a4c.dcm"),
            (multiview._pane_right, "a2c.dcm"),
        ):
            assert pane._file_label.toolTip() == expected_name
            assert pane._file_label.text() == expected_name or pane._file_label.text().endswith("…")
        assert "30" in multiview._pane_left._frame_label.text()
        assert "40" in multiview._pane_right._frame_label.text()

    def test_second_pane_never_mirrors_the_main_clip(self, multiview, qtbot) -> None:
        assert multiview._multiview.session.pane(PaneId.RIGHT).instance_uid != "1.2.3.4.5.10"

    def test_common_window_runs_both_clips_together(self, multiview, qtbot) -> None:
        mv = multiview._multiview
        mv.set_mode(PlaybackMode.COMMON_WINDOW)
        mv.play()
        try:
            assert mv.session.is_playing is True
            _drive(qtbot, multiview, 0.4)
            left_frame = mv.session.pane(PaneId.LEFT).current_frame
            right_frame = mv.session.pane(PaneId.RIGHT).current_frame
            # both clips advanced from their own start, at the same wall-clock offset
            assert left_frame == 12
            assert right_frame == 12
            assert _painted(multiview, PaneId.RIGHT)[-1] == right_frame
        finally:
            mv.pause()

    def test_common_window_loops_after_the_hold(self, multiview, qtbot) -> None:
        mv = multiview._multiview
        mv.set_mode(PlaybackMode.COMMON_WINDOW)
        mv.play()
        try:
            # 29 frames * 33 ms is the shorter remainder of the two clips
            _drive(qtbot, multiview, 1.0)
            assert mv.session.pane(PaneId.LEFT).current_frame == 29
            assert mv.session.pane(PaneId.RIGHT).current_frame == 29
            # the endpoint hold keeps both clips on their last frame
            _drive(qtbot, multiview, 0.10)
            assert mv.session.pane(PaneId.LEFT).current_frame == 29
            assert mv.session.pane(PaneId.RIGHT).current_frame == 29
            # once it expires the cycle starts over
            _tick(multiview, 0.15)
            assert mv.session.pane(PaneId.LEFT).current_frame == 0
            assert mv.session.pane(PaneId.RIGHT).current_frame == 0
        finally:
            mv.pause()

    def test_event_cycle_aligns_the_markers(self, multiview, qtbot) -> None:
        mv = multiview._multiview
        # left: MK0=0, MK1=10; right: MK0=0, MK1=20
        for ordinal, frame in ((0, 0), (1, 10)):
            mv.set_frame(PaneId.LEFT, frame)
            mv.place_marker(PaneId.LEFT, ordinal)
        for ordinal, frame in ((0, 0), (1, 20)):
            mv.set_frame(PaneId.RIGHT, frame)
            mv.place_marker(PaneId.RIGHT, ordinal)
        mv.set_mode(PlaybackMode.EVENT_CYCLE)
        mv.play()
        try:
            schedule = mv._schedule
            assert schedule is not None
            assert schedule.total_s == pytest.approx((10 * 33.0 + 20 * 33.0) / 2.0 / 1000.0, abs=0.01)
            assert schedule.entries[0].timing.k_left < 1.0
            assert schedule.entries[0].timing.k_right > 1.0
            # half of the display cycle: the left clip is on its frame 5,
            # the right one on its frame 10 - both at 50 % of their own cycle.
            _drive(qtbot, multiview, schedule.total_s / 2.0)
            left_frame = mv.session.pane(PaneId.LEFT).current_frame
            right_frame = mv.session.pane(PaneId.RIGHT).current_frame
            assert left_frame == pytest.approx(5, abs=1)
            assert right_frame == pytest.approx(10, abs=1)
            assert _painted(multiview, PaneId.LEFT)[-1] == left_frame
        finally:
            mv.pause()

    def test_two_cycles_keep_the_alignment_on_the_middle_marker(self, multiview, qtbot) -> None:
        mv = multiview._multiview
        for ordinal, frame in ((0, 0), (1, 10), (2, 20)):
            mv.set_frame(PaneId.LEFT, frame)
            mv.place_marker(PaneId.LEFT, ordinal)
        for ordinal, frame in ((0, 0), (1, 20), (2, 38)):
            mv.set_frame(PaneId.RIGHT, frame)
            mv.place_marker(PaneId.RIGHT, ordinal)
        mv.set_cycle_count(2)
        mv.set_mode(PlaybackMode.EVENT_CYCLE)
        mv.play()
        try:
            schedule = mv._schedule
            assert schedule is not None
            assert len(schedule.entries) == 2
            assert schedule.entries[1].timing.k_left != schedule.entries[0].timing.k_left
            # at the boundary between the cycles both clips sit on their MK1
            _drive(qtbot, multiview, schedule.entries[0].duration_s)
            assert mv.session.pane(PaneId.LEFT).current_frame == 10
            assert mv.session.pane(PaneId.RIGHT).current_frame == 20
        finally:
            mv.pause()

    def test_stop_returns_both_clips_to_the_start_of_the_mode(self, multiview, qtbot) -> None:
        mv = multiview._multiview
        mv.set_frame(PaneId.LEFT, 2)
        mv.set_frame(PaneId.RIGHT, 3)
        mv.set_mode(PlaybackMode.COMMON_WINDOW)
        mv.play()
        _drive(qtbot, multiview, 0.3)
        mv.stop()
        assert mv.session.is_playing is False
        assert mv.session.pane(PaneId.LEFT).current_frame == 2
        assert mv.session.pane(PaneId.RIGHT).current_frame == 3

    def test_painted_frames_are_always_original_frames(self, multiview, qtbot) -> None:
        mv = multiview._multiview
        mv.set_mode(PlaybackMode.COMMON_WINDOW)
        mv.play()
        try:
            _drive(qtbot, multiview, 0.5)
            for frame in _painted(multiview, PaneId.RIGHT):
                assert 0 <= frame < 40
        finally:
            mv.pause()
