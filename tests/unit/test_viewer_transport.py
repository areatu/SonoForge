"""A1: the frame/transport owner is isolated from ``ViewerWidget``.

These tests drive ``ViewerTransport`` directly, without a viewer, so a future
change to the surrounding widget cannot hide a broken projection.  They pin the
two ownership rules of the slice: the owner stores no ``ViewerState`` and the
debounce emits at most one pending frame.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pytestqt")

from PySide6.QtWidgets import QLabel

from echo_personal_tool.application.localization import tr
from echo_personal_tool.presentation.cine_phase_strip import CinePhaseStrip
from echo_personal_tool.presentation.viewer.transport import ViewerTransport

pytestmark = pytest.mark.gui


@pytest.fixture
def transport(qtbot):
    from PySide6.QtWidgets import QWidget

    parent = QWidget()
    qtbot.addWidget(parent)
    owner = ViewerTransport(
        parent=parent,
        loop=None,
        phase_strip=CinePhaseStrip(translate=tr),
        phase_label=QLabel("", parent),
    )
    yield owner
    owner.dispose()


def test_zero_frames_disables_playback_and_shows_no_counter(transport) -> None:
    transport.apply_state(frame_index=3, total_frames=0, fps=0.0, is_playing=True)

    assert transport.timeline_slider.maximum() == 0
    assert transport.timeline_slider.isEnabled() is False
    assert transport.play_button.isEnabled() is False
    assert transport.source_label.text() == tr("viewer.frame_none")
    transport.dispose()


def test_decode_in_progress_disables_play_but_keeps_the_pause_caption(transport) -> None:
    transport.apply_state(
        frame_index=7,
        total_frames=5,
        fps=30.0,
        is_playing=True,
        decode_in_progress=True,
    )

    # Negative scenario: a decode in progress must not leave a clickable play
    # button while the document still says «playing».
    assert transport.play_button.isEnabled() is False
    assert transport.play_button.accessibleName() == tr("viewer.pause")
    assert transport.timeline_slider.value() == 4
    assert transport.source_label.text() == tr("viewer.frame_counter", current="5", total="5")
    assert transport.fps_label.text().startswith("FPS: ")
    transport.dispose()


def test_on_timeline_changed_emits_and_select_frame_rejects_out_of_range(transport) -> None:
    transport.apply_state(frame_index=0, total_frames=5, fps=25.0, is_playing=False)
    received: list[int] = []
    transport.frame_selected.connect(received.append)

    transport.on_timeline_changed(2)
    assert received == [2]

    transport.select_frame(99)
    transport.select_frame(-1)
    assert received == [2]
    assert transport.timeline_slider.value() == 0
    transport.dispose()


def test_scroll_debounce_emits_one_pending_frame(transport) -> None:
    received: list[int] = []
    transport.scroll_frame_selected.connect(received.append)

    transport.scroll_debounce_ms = 50
    transport.queue_scroll(4)
    assert received == []
    assert transport.pending_scroll_index == 4

    transport.emit_pending_scroll()
    transport.emit_pending_scroll()
    assert received == [4]
    assert transport.pending_scroll_index is None
    transport.dispose()


def test_zero_debounce_emits_immediately(transport) -> None:
    received: list[int] = []
    transport.scroll_frame_selected.connect(received.append)

    transport.scroll_debounce_ms = 0
    transport.queue_scroll(3)

    assert received == [3]
    assert transport.pending_scroll_index is None
    transport.dispose()


def test_dispose_is_idempotent_and_stops_the_timer(transport) -> None:
    transport.scroll_debounce_ms = 1000
    transport.queue_scroll(1)
    assert transport.debounce_active is True

    transport.dispose()
    transport.dispose()

    assert transport.pending_scroll_index is None
    assert transport.debounce_active is False
