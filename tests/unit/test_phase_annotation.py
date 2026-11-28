"""The phase annotation controller (``viewer.phase_annotation``).

Viewer-level integration is pinned in ``tests/unit/test_cine_phase_strip.py``
(strip above the slider, caption following the playhead); these pin the
extracted controller itself: widget ownership, timeline transitions, the
caption matrix (systole/diastole/unknown/none) and the marker-edit re-derivation.
"""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtWidgets import QWidget

from echo_personal_tool.domain.services.cine_phase_timeline import build_phase_timeline
from echo_personal_tool.presentation.viewer.phase_annotation import PhaseAnnotationController

pytestmark = pytest.mark.gui


@pytest.fixture()
def controller(qtbot):
    owner = QWidget()
    qtbot.addWidget(owner)
    return PhaseAnnotationController(parent=owner, current_frame_provider=lambda: 4)


def _timeline():
    n = 72
    curve = np.cos(2 * np.pi * (np.arange(n) - 3) / 24)
    return build_phase_timeline(n_frames=n, frame_time_ms=33.3, area_curve=curve)


def test_the_controller_owns_the_strip_and_the_caption(controller) -> None:
    assert controller.strip is not None
    assert controller.label is not None
    # A fresh controller has no timeline: the strip is hidden, caption empty.
    assert controller.timeline() is None
    assert controller.strip.isHidden()
    assert controller.label.text() == ""


def test_set_timeline_shows_the_strip_only_when_markers_exist(controller) -> None:
    controller.set_timeline(_timeline())
    assert controller.timeline() is not None
    assert not controller.strip.isHidden()
    controller.set_timeline(None)
    assert controller.strip.isHidden()
    assert controller.timeline() is None


def test_caption_follows_the_phase_at_the_requested_frame(controller) -> None:
    controller.set_timeline(_timeline())
    texts = set()
    for frame in range(0, 30, 3):
        controller.update_caption(frame=frame)
        if controller.label.text():
            texts.add(controller.label.text())
    assert texts, "a usable cardiac result must produce a caption somewhere in the cine"


def test_caption_falls_back_to_the_provider_frame(controller) -> None:
    controller.set_timeline(_timeline())
    controller.update_caption()  # provider returns 4
    assert controller.label.styleSheet()  # a style is always applied


def test_marker_move_returns_a_timeline_with_the_manual_pair(controller) -> None:
    controller.set_timeline(_timeline())
    cycle = controller.timeline().cycles[0]
    moved = controller.on_marker_moved(0, "ed", cycle.ed_frame + 2)
    assert moved is not None
    assert moved.cycles[0].ed_frame == cycle.ed_frame + 2
    assert moved.cycles[0].es_frame == cycle.es_frame


def test_marker_move_is_ignored_without_a_timeline_or_out_of_range(controller) -> None:
    assert controller.on_marker_moved(0, "ed", 3) is None
    controller.set_timeline(_timeline())
    assert controller.on_marker_moved(99, "ed", 3) is None


def test_marker_reset_returns_the_base_timeline(controller) -> None:
    controller.set_timeline(_timeline())
    base = controller.on_marker_reset()
    assert base is not None
    moved = controller.on_marker_moved(0, "ed", 5)
    assert moved is not None
    controller.set_timeline(moved)
    assert controller.timeline() == moved
    # The strip remembers the machine result separately from the manual edit.
    assert controller.strip.base_timeline() == base
