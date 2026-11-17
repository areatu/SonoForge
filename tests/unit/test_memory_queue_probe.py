"""Synthetic tests for the opt-in diagnostic timeline, without patient files."""

from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import psutil
import pytest
from scripts.memory_queue_probe import Recorder, open_exclusive, process_memory

from echo_personal_tool.application.decode_gate import DecodeGate, DecodePriority
from echo_personal_tool.application.frame_cache import FrameCache
from echo_personal_tool.domain.services.study_comparison import ComparisonMemoryBudget


class Request:
    def __init__(self, path: Path, priority: DecodePriority) -> None:
        self.decode_path = path
        self.priority = priority
        self.requested_frames = 2
        self.estimated_frame_bytes = 10


class Process:
    def memory_info(self):
        return SimpleNamespace(rss=1234)

    def children(self, recursive):
        assert recursive
        return [SimpleNamespace(memory_info=lambda: SimpleNamespace(rss=222))]


def setup_recorder(tmp_path):
    cache = FrameCache()
    cache.load(tmp_path / "PRIVATE-PATIENT.dcm", np.zeros((2, 10, 10), dtype=np.uint8))
    cache.pin(0)
    gate = DecodeGate()
    assert gate.enter(Request(tmp_path / "PRIVATE-PATIENT.dcm", DecodePriority.INTERACTIVE))
    assert not gate.enter(Request(tmp_path / "PRIVATE-PATIENT.dcm", DecodePriority.PLAYBACK))
    budget = ComparisonMemoryBudget(500)
    assert budget.reserve("pane", 42)
    controller = SimpleNamespace(_frame_cache=cache, _decode_gate=gate)
    window = SimpleNamespace(_comparison=SimpleNamespace(_budget=budget))
    stream = io.StringIO()
    return Recorder(stream, controller, window, process=Process()), stream


def test_snapshot_samples_actual_cache_queue_and_comparison_without_identifiers(tmp_path):
    recorder, stream = setup_recorder(tmp_path)
    assert recorder.sample("scrub_start")
    row = json.loads(stream.getvalue())
    assert row["marker"] == "scrub_start"
    assert row["process"] == {
        "rss_bytes": 1234,
        "children_rss_bytes": 222,
        "children_count": 1,
        "children_complete": True,
    }
    assert row["queue"]["parked_requests"] == 1
    assert row["queue"]["estimated_pending_bytes"] == 20
    assert row["cache"]["logical_bytes"] == 200
    assert row["cache"]["owned_bytes"] == 200
    assert row["cache"]["pinned_bytes"] == 100
    assert row["comparison"] == {"reserved_bytes": 42, "cap_bytes": 500}
    assert "PRIVATE-PATIENT" not in stream.getvalue()
    with pytest.raises(ValueError, match="unknown marker"):
        recorder.sample("PRIVATE-PATIENT")


def test_child_exit_or_access_denied_is_reported_as_incomplete():
    class Gone:
        def memory_info(self):
            raise psutil.NoSuchProcess(10)

    class Parent(Process):
        def children(self, recursive):
            return [Gone(), SimpleNamespace(memory_info=lambda: SimpleNamespace(rss=222))]

    assert process_memory(Parent()) == {
        "rss_bytes": 1234,
        "children_rss_bytes": 222,
        "children_count": 2,
        "children_complete": False,
    }


def test_size_limit_and_write_error_stop_sampling(tmp_path):
    recorder, stream = setup_recorder(tmp_path)
    recorder.max_bytes = 1
    assert not recorder.sample()
    assert recorder.failed and recorder.stopped
    assert stream.getvalue() == ""
    assert not recorder.sample()

    class BadStream(io.StringIO):
        def write(self, value):
            raise OSError("private details")

    recorder, _ = setup_recorder(tmp_path)
    recorder.stream = BadStream()
    assert not recorder.sample()
    assert recorder.failed


def test_exclusive_file_creation_never_overwrites_or_follows_existing_link(tmp_path):
    path = tmp_path / "output.jsonl"
    with open_exclusive(path) as stream:
        stream.write("existing")
    with pytest.raises(FileExistsError):
        open_exclusive(path)
    assert path.read_text() == "existing"
    link = tmp_path / "link.jsonl"
    try:
        link.symlink_to(path)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    with pytest.raises(FileExistsError):
        open_exclusive(link)
    assert path.read_text() == "existing"


@pytest.mark.gui
def test_launcher_writes_timed_samples_and_button_marker(tmp_path, monkeypatch, qapp, qtbot):
    import sys

    from PySide6.QtWidgets import QDialog, QMainWindow, QPushButton
    from scripts import memory_queue_probe

    import echo_personal_tool.main as app_main

    cache = FrameCache()
    gate = DecodeGate()
    budget = ComparisonMemoryBudget(500)
    controller = SimpleNamespace(_frame_cache=cache, _decode_gate=gate)

    class FakeWindow(QMainWindow):
        def __init__(self, *, controller):
            super().__init__()
            self._comparison = SimpleNamespace(_budget=budget)

    def fake_main():
        window = app_main.MainWindow(controller=controller)
        qtbot.addWidget(window)
        panel = window.findChild(QDialog)
        assert panel is not None
        button = next(b for b in panel.findChildren(QPushButton) if b.text() == "Scrub: start")
        button.click()
        qtbot.wait(350)
        return 0

    path = tmp_path / "timeline.jsonl"
    monkeypatch.setattr(app_main, "MainWindow", FakeWindow)
    monkeypatch.setattr(app_main, "main", fake_main)
    monkeypatch.setattr(sys, "argv", ["probe", "--output", str(path), "--interval-ms", "250"])
    assert memory_queue_probe.main() == 0
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert rows[0] == {"type": "header", "format": "sonoforge-memory-queue-v1", "interval_ms": 250}
    assert rows[-1]["type"] == "end"
    assert any(row.get("marker") == "scrub_start" for row in rows)
    assert sum(row["type"] == "sample" for row in rows) >= 3
    assert app_main.MainWindow is FakeWindow


def test_missing_child_enumeration_and_parent_rss_are_not_reported_as_zero():
    class Denied:
        def memory_info(self):
            raise psutil.AccessDenied(10)

        def children(self, recursive):
            raise psutil.AccessDenied(10)

    assert process_memory(Denied()) == {
        "rss_bytes": None,
        "children_rss_bytes": None,
        "children_count": None,
        "children_complete": False,
    }


@pytest.mark.gui
def test_diagnostic_sampling_failure_does_not_crash_app_and_is_incomplete(tmp_path, monkeypatch, qapp, qtbot, capsys):
    import sys

    from PySide6.QtWidgets import QMainWindow
    from scripts import memory_queue_probe

    import echo_personal_tool.main as app_main

    class FakeWindow(QMainWindow):
        def __init__(self, *, controller):
            super().__init__()

    def fake_main():
        qtbot.addWidget(app_main.MainWindow(controller=object()))
        return 0

    def broken_sample(*args, **kwargs):
        raise RuntimeError("PRIVATE-PATIENT")

    path = tmp_path / "failed.jsonl"
    monkeypatch.setattr(app_main, "MainWindow", FakeWindow)
    monkeypatch.setattr(app_main, "main", fake_main)
    monkeypatch.setattr(memory_queue_probe.Recorder, "sample", broken_sample)
    monkeypatch.setattr(sys, "argv", ["probe", "--output", str(path)])
    assert memory_queue_probe.main() == 1
    assert [json.loads(line)["type"] for line in path.read_text().splitlines()] == ["header"]
    assert "PRIVATE-PATIENT" not in capsys.readouterr().err


def test_timeline_observes_queue_draining_and_cache_clearing(tmp_path):
    cache = FrameCache()
    gate = DecodeGate()
    controller = SimpleNamespace(_frame_cache=cache, _decode_gate=gate)
    window = SimpleNamespace(_comparison=SimpleNamespace(_budget=ComparisonMemoryBudget(500)))
    stream = io.StringIO()
    recorder = Recorder(stream, controller, window, process=Process())
    path = tmp_path / "fixture.dcm"
    cache.load(path, np.zeros((2, 10, 10), dtype=np.uint8))
    owner = Request(path, DecodePriority.INTERACTIVE)
    assert gate.enter(owner)
    assert not gate.enter(Request(path, DecodePriority.PLAYBACK))
    assert recorder.sample("tabs_start")
    parked = gate.next_parked(owner)
    assert parked is not None
    assert gate.next_parked(parked) is None
    cache.clear()
    assert recorder.sample("tabs_end")
    rows = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert rows[0]["queue"]["parked_requests"] == 1
    assert rows[0]["cache"]["owned_bytes"] == 200
    assert rows[1]["queue"]["parked_requests"] == 0
    assert rows[1]["cache"]["owned_bytes"] == 0
    assert rows[1]["elapsed_s"] >= rows[0]["elapsed_s"]
