"""GUI tests for the cardiac phase strip in both playback bars.

Skipped in environments without PySide6 widgets; the pure algorithm and
geometry are covered by ``test_cine_phase_timeline`` / ``test_cine_phase_geometry``.
"""

from __future__ import annotations

import numpy as np
import pytest

pytestmark = pytest.mark.gui
pytest.importorskip("pytestqt")
pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import QPoint, Qt  # noqa: E402

from echo_personal_tool.domain.services.cine_phase_timeline import (  # noqa: E402
    PHASE_DIASTOLE,
    PHASE_SYSTOLE,
    build_phase_timeline,
)
from echo_personal_tool.presentation.cine_phase_geometry import x_for_frame  # noqa: E402
from echo_personal_tool.presentation.cine_phase_strip import CinePhaseStrip  # noqa: E402


def _timeline():
    n = 72
    curve = np.cos(2 * np.pi * (np.arange(n) - 3) / 24)
    return build_phase_timeline(n_frames=n, frame_time_ms=33.3, area_curve=curve)


class TestStrip:
    def test_placeholder_without_a_detector(self, qtbot) -> None:
        strip = CinePhaseStrip()
        qtbot.addWidget(strip)
        strip.resize(400, 20)
        assert strip._placeholder
        assert strip._total == 0
        assert strip.phase_at(0) == "unknown"

    def test_timeline_paints_phases_and_markers(self, qtbot) -> None:
        strip = CinePhaseStrip()
        qtbot.addWidget(strip)
        strip.resize(400, 20)
        timeline = _timeline()
        strip.set_timeline(timeline)
        assert not strip._placeholder
        assert strip._total == 72
        assert strip.phase_at(4) == PHASE_SYSTOLE
        assert strip.phase_at(20) == PHASE_DIASTOLE
        hit = strip._marker_at(x_for_frame(3, 72, 0.0, 400.0), 5)
        assert hit is not None and hit[0].kind == "ed"
        assert strip.toolTip()  # source/confidence provenance is exposed

    def test_click_on_the_band_seeks_to_a_frame(self, qtbot) -> None:
        strip = CinePhaseStrip()
        qtbot.addWidget(strip)
        strip.resize(400, 20)
        strip.show()
        strip.set_timeline(_timeline())
        frames: list[int] = []
        strip.frame_selected.connect(frames.append)
        x = x_for_frame(40, 72, 0.0, 400.0)
        qtbot.mouseClick(strip, Qt.MouseButton.LeftButton, pos=QPoint(int(x), 15))
        assert frames and abs(frames[0] - 40) <= 1

    def test_dragging_an_es_chip_emits_manual_correction(self, qtbot) -> None:
        strip = CinePhaseStrip()
        qtbot.addWidget(strip)
        strip.resize(400, 20)
        strip.show()
        strip.set_timeline(_timeline())
        moved: list[tuple[int, str, int]] = []
        strip.marker_moved.connect(lambda *args: moved.append(args))
        start_x = x_for_frame(15, 72, 0.0, 400.0)
        end_x = x_for_frame(18, 72, 0.0, 400.0)
        qtbot.mousePress(strip, Qt.MouseButton.LeftButton, pos=QPoint(int(start_x), 5))
        qtbot.mouseMove(strip, pos=QPoint(int(end_x), 5))
        qtbot.wait(5)
        qtbot.mouseRelease(strip, Qt.MouseButton.LeftButton, pos=QPoint(int(end_x), 5))
        assert moved
        assert moved[0][1] == "es"
        assert moved[0][2] >= 17

    def test_low_confidence_result_stays_muted(self, qtbot) -> None:
        strip = CinePhaseStrip()
        qtbot.addWidget(strip)
        strip.resize(400, 20)
        from echo_personal_tool.domain.services.cine_phase_timeline import PhaseTimeline

        unavailable = PhaseTimeline(
            n_frames=30,
            frame_time_ms=33.3,
            labels=("unknown",) * 30,
            cycles=(),
            source="unavailable",
            confidence=0.0,
            warnings=("phase_unavailable",),
        )
        strip.set_timeline(unavailable)
        assert strip._placeholder
        assert strip.phase_at(10) == "unknown"


class TestCinePanelIntegration:
    def test_panel_accepts_a_timeline_and_applies_manual_edits(self, qtbot) -> None:
        from echo_personal_tool.ui.cine_panel import CinePanel

        panel = CinePanel("A4C")
        qtbot.addWidget(panel)
        panel.resize(400, 300)
        panel.set_frames(np.zeros((72, 32, 32), dtype=np.uint8))
        timeline = _timeline()
        panel.set_phase_timeline(timeline)
        assert panel._phase_timeline is timeline
        assert not panel._phase_bar._placeholder
        panel._on_phase_marker_moved(0, "es", 17)
        assert panel._phase_timeline.cycles[0].source == "manual"
        assert panel._phase_timeline.cycles[0].es_frame == 17
        panel._on_phase_marker_reset(0, "es")
        assert panel._phase_timeline.cycles[0].es_frame == 15

    def test_clicking_the_strip_moves_the_scrubber(self, qtbot) -> None:
        from echo_personal_tool.ui.cine_panel import CinePanel

        panel = CinePanel("A4C")
        qtbot.addWidget(panel)
        panel.resize(400, 300)
        panel.show()
        panel.set_frames(np.zeros((72, 32, 32), dtype=np.uint8))
        panel.set_phase_timeline(_timeline())
        x = x_for_frame(30, 72, 0.0, float(panel._phase_bar.width()))
        qtbot.mouseClick(panel._phase_bar, Qt.MouseButton.LeftButton, pos=QPoint(int(x), 15))
        assert abs(panel._frame_slider.value() - 30) <= 1


class TestViewerIntegration:
    def test_viewer_has_a_phase_strip_above_the_slider(self, qtbot) -> None:
        from echo_personal_tool.presentation.viewer_widget import ViewerWidget

        viewer = ViewerWidget()
        qtbot.addWidget(viewer)
        viewer.resize(640, 480)
        viewer.set_phase_timeline(_timeline())
        viewer.show()
        qtbot.waitExposed(viewer)
        assert viewer._phase_strip is not None
        assert viewer._phase_strip.width() == viewer._timeline_slider.width()
        bar_y = viewer._phase_strip.mapTo(viewer, viewer._phase_strip.rect().topLeft()).y()
        slider_y = viewer._timeline_slider.mapTo(viewer, viewer._timeline_slider.rect().topLeft()).y()
        assert bar_y < slider_y

    def test_viewer_phase_label_follows_the_playhead(self, qtbot) -> None:
        from echo_personal_tool.presentation.viewer_widget import ViewerWidget

        viewer = ViewerWidget()
        qtbot.addWidget(viewer)
        viewer.resize(640, 480)
        viewer.set_phase_timeline(_timeline())
        viewer._update_phase_label(frame=4)
        assert viewer._phase_label.text()
        viewer._update_phase_label(frame=20)
        assert viewer._phase_label.text()
        viewer.set_phase_timeline(None)
        assert viewer._phase_label.text() == ""

    def test_viewer_hides_markers_until_a_usable_cardiac_result_exists(self, qtbot) -> None:
        from echo_personal_tool.presentation.viewer_widget import ViewerWidget

        viewer = ViewerWidget()
        qtbot.addWidget(viewer)
        assert viewer._phase_strip.isHidden()
        viewer.set_phase_timeline(_timeline())
        assert not viewer._phase_strip.isHidden()
        viewer.set_phase_timeline(None)
        assert viewer._phase_strip.isHidden()
        assert viewer._phase_strip.base_timeline() is None
        assert viewer._phase_label.text() == ""
        viewer._on_phase_marker_reset(0, "ed")
        assert viewer._phase_timeline is None

    def test_unknown_result_has_no_visible_chips(self, qtbot) -> None:
        from echo_personal_tool.presentation.viewer_widget import ViewerWidget

        viewer = ViewerWidget()
        qtbot.addWidget(viewer)
        timeline = build_phase_timeline(n_frames=30, frame_time_ms=33.3)
        viewer.set_phase_timeline(timeline)
        assert viewer._phase_strip.isHidden()
        assert viewer._phase_strip._marker_at(100, 5) is None
