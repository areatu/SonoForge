"""Paired cardiac tools: the second half continues on the next click (ТЗ п. 2).

«МЖП · КДР ЛЖ · ЗСЛЖ» and «КДО · 4-кам.» are half-pairs: they are only worth a
place in Quick/Favorites if the operator does not have to hunt for the second
button after scrolling the cine to the systolic frame.  The chain therefore

* survives scrolling — a tool that is already *running* is cancelled by a frame
  change, so the second half is armed and started by the click, not by the
  completion of the first;
* is dropped by anything that means «not now»: Esc, another tool, another clip;
* never steals a click that grabs a node of the previous contour (correcting a
  measurement must not spawn the next one).
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import QPointF, Qt

from echo_personal_tool.domain.models import InstanceMetadata
from echo_personal_tool.domain.models.viewer_state import ViewerState
from echo_personal_tool.presentation.viewer_widget import ViewerWidget

pytestmark = pytest.mark.gui

_FRAME = 200


def _state(frame_index: int = 0) -> ViewerState:
    instance = InstanceMetadata(
        sop_instance_uid="1.2.3.4.5.6",
        series_uid="1.2.3.4.5",
        modality="US",
        number_of_frames=30,
        pixel_spacing=(0.5, 0.5),
        frame_time_ms=33.3,
        series_description="Adult Echo",
        path=None,
        media_format="dicom",
    )
    return ViewerState(
        instance=instance,
        current_frame_index=frame_index,
        total_frames=30,
        frame_time_ms=33.3,
        is_playing=False,
    )


def _make_viewer(qtbot) -> ViewerWidget:
    w = ViewerWidget()
    qtbot.addWidget(w)
    w.resize(640, 480)
    w.show_frame(np.zeros((_FRAME, _FRAME), dtype=np.uint8))
    w.set_state(_state())
    return w


def _click(viewer: ViewerWidget, x: float, y: float) -> None:
    ev = SimpleNamespace(
        button=lambda: Qt.MouseButton.LeftButton,
        pos=lambda: QPointF(x, y),
    )
    viewer._map_view_event = lambda _e: (x, y)  # type: ignore[method-assign]
    viewer._handle_linear_caliper_mouse_press(ev)


class TestArmedNextTool:
    def test_nothing_is_armed_by_default(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w.armed_next() is None
        assert w.start_armed_next() is False

    def test_the_caliper_chain_starts_on_the_next_click(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.arm_next_caliper("LVESD")
        assert w.armed_next() == ("caliper", "LVESD")

        assert w.start_armed_next() is True
        assert w.is_linear_caliper_active is True
        assert w._current_caliper_label() == "LVESD"
        # Consumed: the following click is the second point, not a new tool.
        assert w.armed_next() is None

    def test_the_contour_chain_starts_on_the_next_click(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.arm_next_contour(chamber="LV", view="A4C", phase="ES")
        assert w.start_armed_next() is True
        assert w.is_contour_mode_active is True
        assert w._active_contour_phase == "ES"
        assert w._active_contour_view == "A4C"

    def test_scrolling_the_cine_keeps_the_chain(self, qtbot) -> None:
        """The operator scrolls to the systolic frame — that must not disarm."""
        w = _make_viewer(qtbot)
        w.arm_next_contour(chamber="LV", view="A4C", phase="ES")
        w.set_state(_state(frame_index=7))
        assert w.armed_next() == ("contour", "LV", "A4C", "ES", False)

    def test_escape_drops_the_chain(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.arm_next_caliper("LVESD")
        w.cancel_active_tool()
        assert w.armed_next() is None

    def test_another_clip_drops_the_chain(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.arm_next_caliper("LVESD")
        other = replace(
            _state(),
            instance=InstanceMetadata(
                sop_instance_uid="9.9.9",
                series_uid="9.9",
                modality="US",
                number_of_frames=30,
                pixel_spacing=(0.5, 0.5),
                frame_time_ms=33.3,
                series_description="Adult Echo",
                path=None,
                media_format="dicom",
            ),
        )
        w.set_state(other)
        assert w.armed_next() is None

    def test_an_armed_caliper_takes_the_first_point_of_the_next_click(self, qtbot) -> None:
        """The click that starts the chained tool is also its first point.

        This is the order the graphics view uses: resolve the armed step, then
        hand the same press to the caliper handler.
        """
        w = _make_viewer(qtbot)
        w.arm_next_caliper("LVESD")
        assert w.start_armed_next() is True
        _click(w, 20.0, 20.0)
        assert w._linear_caliper_start == (20.0, 20.0)
        assert w.is_linear_caliper_active is True
