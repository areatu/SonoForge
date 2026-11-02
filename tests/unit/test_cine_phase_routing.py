"""Main-window phase routing: organ gate, late workers and cache invalidation."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from echo_personal_tool.domain.models.metadata import InstanceMetadata
from echo_personal_tool.domain.models.viewer_state import ViewerState
from echo_personal_tool.domain.services.cine_phase_timeline import build_phase_timeline
from echo_personal_tool.presentation.main_window import MainWindow

pytestmark = pytest.mark.gui


def _state(**changes) -> ViewerState:
    instance = InstanceMetadata(
        sop_instance_uid="clip-1",
        series_uid="series-1",
        modality="US",
        number_of_frames=72,
        pixel_spacing=None,
        frame_time_ms=33.3,
        series_description="A4C",
        path=Path("/unused.dcm"),
    )
    return ViewerState(
        instance=replace(instance, **changes),
        current_frame_index=0,
        total_frames=72,
        frame_time_ms=33.3,
        is_playing=False,
    )


@pytest.fixture()
def routing(monkeypatch):
    from PySide6.QtCore import QThreadPool

    from echo_personal_tool.application.workers import cine_phase_worker

    jobs = []
    pool = SimpleNamespace(start=jobs.append)
    monkeypatch.setattr(QThreadPool, "globalInstance", lambda: pool)

    class Worker:
        def __init__(self, **kwargs):
            self.arguments = kwargs
            self.signals = SimpleNamespace(finished=MagicMock(), failed=MagicMock())

    monkeypatch.setattr(cine_phase_worker, "CinePhaseWorker", Worker)
    window = SimpleNamespace(
        _viewer=SimpleNamespace(set_phase_timeline=MagicMock()),
        _on_phase_timeline_ready=MagicMock(),
        _on_phase_timeline_failed=MagicMock(),
    )
    return window, jobs


def _sync(window, state):
    uid = state.instance.sop_instance_uid if state.instance else None
    MainWindow._sync_phase_timeline(window, state, uid)


def _timeline():
    return build_phase_timeline(
        n_frames=72,
        frame_time_ms=33.3,
        area_curve=np.cos(2 * np.pi * (np.arange(72) - 3) / 24),
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"body_part": "LIVER", "study_description": "Adult Echo"},
        {"body_part": "THYROID", "study_description": "Adult Echo"},
        {"series_description": "Щитовидная железа", "study_description": "ЭхоКГ"},
        {"series_description": "Cine (MP4)", "media_format": "mp4"},
        {"clip_mode": "doppler"},
        {"clip_mode": "m_mode"},
    ],
)
def test_other_organs_and_time_axes_never_start_detection(routing, changes):
    window, jobs = routing
    _sync(window, _state(**changes))
    assert jobs == []
    window._viewer.set_phase_timeline.assert_called_once_with(None)


def test_cardiac_clip_starts_once_after_decoded_frame_count_arrives(routing):
    window, jobs = routing
    state = _state()
    _sync(window, replace(state, total_frames=0))
    assert jobs == []
    _sync(window, state)
    assert len(jobs) == 1
    _sync(window, replace(state, current_frame_index=5))
    assert len(jobs) == 1


def test_late_heart_result_cannot_restore_markers_on_a_thyroid_clip(routing):
    window, jobs = routing
    _sync(window, _state())
    generation = jobs[0].arguments["generation"]
    # Even metadata corrected in place on the same UID invalidates the worker.
    _sync(window, _state(series_description="Thyroid"))
    MainWindow._on_phase_timeline_ready(window, _timeline(), "clip-1", generation)
    assert window._phase_timelines == {}
    assert window._phase_workers == {}
    assert window._viewer.set_phase_timeline.call_args.args == (None,)


def test_cached_heart_result_stays_behind_the_organ_gate(routing):
    window, jobs = routing
    _sync(window, _state())
    timeline = _timeline()
    MainWindow._on_phase_timeline_ready(window, timeline, "clip-1", window._phase_timeline_generation)
    _sync(window, _state(series_description="Liver"))
    assert window._viewer.set_phase_timeline.call_args.args == (None,)
    _sync(window, _state())
    assert window._viewer.set_phase_timeline.call_args.args == (timeline,)
    assert len(jobs) == 1


def test_frame_time_change_does_not_reuse_old_timing(routing):
    window, jobs = routing
    state = _state()
    _sync(window, state)
    MainWindow._on_phase_timeline_ready(window, _timeline(), "clip-1", window._phase_timeline_generation)
    _sync(window, replace(state, frame_time_ms=40.0))
    assert len(jobs) == 2
    assert jobs[-1].arguments["frame_time_ms"] == 40.0
    assert window._viewer.set_phase_timeline.call_args.args == (None,)
