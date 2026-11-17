"""Boundary acceptance: an incoming prefetch is not exempt from its own cap."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from echo_personal_tool.application.decode_gate import DecodeGate, DecodePriority


@pytest.mark.parametrize(
    "limits,frames,frame_bytes",
    [
        ({"max_parked_frames_per_file": 4}, 5, 1),
        ({"max_pending_bytes": 1024}, 1, 1025),
        ({"max_pending_bytes": 0}, 1, 1),
    ],
)
def test_oversized_incoming_speculative_is_cancelled(tmp_path: Path, limits, frames, frame_bytes):
    gate = DecodeGate(**limits)
    path = tmp_path / "cine.dcm"
    owner = SimpleNamespace(decode_path=path, priority=DecodePriority.INTERACTIVE)
    cancelled = []
    request = SimpleNamespace(
        decode_path=path,
        priority=DecodePriority.PLAYBACK,
        requested_frames=frames,
        estimated_frame_bytes=frame_bytes,
        cancel_parked=lambda: cancelled.append(True),
    )
    assert gate.enter(owner)
    assert not gate.enter(request)
    assert cancelled == [True]
    assert gate.stats().parked_requests == 0
    assert gate.stats().pending_bytes == 0
    assert gate.next_parked(owner) is None
