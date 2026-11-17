"""Opt-in, PHI-free memory/queue timeline for a source-run SonoForge session.

Launches the normal application with a small manual marker panel.  It is a
measurement aid, not a budget enforcer or a latency/clinical acceptance test.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, TextIO

import psutil

# Explicit event names only: no paths, filenames, user text, IDs, or exception text.
MARKERS = {
    "play_start": "Playback: start",
    "play_end": "Playback: end",
    "scrub_start": "Scrub: start",
    "scrub_end": "Scrub: end",
    "tabs_start": "Tab switches: start",
    "tabs_end": "Tab switches: end",
    "comparison_start": "Comparison: start",
    "comparison_end": "Comparison: end",
    "analysis_start": "Analysis: start",
    "analysis_cancel": "Analysis: cancel",
    "idle": "Idle / waiting",
}
MAX_BYTES = 25 * 1024 * 1024


def open_exclusive(path: Path) -> TextIO:
    """Create a new private output file; never follow or overwrite an existing path."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        return os.fdopen(fd, "w", encoding="utf-8", newline="\n")
    except BaseException:
        os.close(fd)
        raise


def process_memory(process: Any) -> dict[str, Any]:
    """RSS in bytes, with explicit missing/partial child data, without PIDs."""
    try:
        parent_rss = int(process.memory_info().rss)
    except (psutil.Error, OSError):
        parent_rss = None
    try:
        children = process.children(recursive=True)
    except (psutil.Error, OSError):
        return {"rss_bytes": parent_rss, "children_rss_bytes": None, "children_count": None, "children_complete": False}
    total = 0
    complete = True
    for child in children:
        try:
            total += int(child.memory_info().rss)
        except (psutil.Error, OSError):
            complete = False
    return {
        "rss_bytes": parent_rss,
        "children_rss_bytes": total,
        "children_count": len(children),
        "children_complete": complete,
    }


class Recorder:
    """UI-thread-only snapshots; no frame buffers or application objects serialized."""

    def __init__(
        self, stream: TextIO, controller: Any, window: Any, *, process: Any = None, max_bytes: int = MAX_BYTES
    ):
        self.stream = stream
        self.controller = controller
        self.window = window
        self.process = process if process is not None else psutil.Process()
        self.started = time.monotonic()
        self.max_bytes = max_bytes
        self.written = 0
        self.stopped = False
        self.failed = False

    def write(self, record: dict[str, Any]) -> bool:
        if self.stopped:
            return False
        line = json.dumps(record, separators=(",", ":"), allow_nan=False) + "\n"
        size = len(line.encode("utf-8"))
        if self.written + size > self.max_bytes:
            self.stopped = self.failed = True
            return False
        try:
            self.stream.write(line)
            self.stream.flush()
        except OSError:
            self.stopped = self.failed = True
            return False
        self.written += size
        return True

    def sample(self, marker: str | None = None) -> bool:
        if marker is not None and marker not in MARKERS:
            raise ValueError("unknown marker")
        if self.stopped:
            return False
        cache = self.controller._frame_cache.memory_stats()  # diagnostic adapter, called on Qt thread
        queue = self.controller._decode_gate.stats()
        budget = self.window._comparison._budget
        record = {
            "type": "sample",
            "elapsed_s": round(time.monotonic() - self.started, 6),
            "marker": marker,
            "process": process_memory(self.process),
            "cache": {
                "frame_count": cache.frame_count,
                "logical_bytes": cache.logical_bytes,
                "owned_bytes": cache.owned_bytes,
                "pinned_bytes": cache.pinned_bytes,
                "peak_bytes": cache.peak_bytes,
                "budget_bytes": cache.budget_bytes,
                "mode": cache.mode,
            },
            "comparison": {"reserved_bytes": budget.total_bytes, "cap_bytes": budget.cap_bytes},
            "queue": {
                "parked_requests": queue.parked_requests,
                "parked_frames": queue.parked_frames,
                "estimated_pending_bytes": queue.pending_bytes,
                "dropped_requests": queue.dropped_requests,
                "files_with_parked": queue.files_with_parked,
            },
        }
        return self.write(record)

    def close(self) -> None:
        if not self.stopped:
            self.write({"type": "end", "elapsed_s": round(time.monotonic() - self.started, 6)})
        self.stopped = True
        try:
            self.stream.close()
        except OSError:
            self.failed = True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="new JSONL file (never overwritten)")
    parser.add_argument("--interval-ms", type=int, default=500, choices=range(250, 5001), metavar="250..5000")
    args = parser.parse_args()
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout

    import echo_personal_tool.main as app_main

    try:
        stream = open_exclusive(args.output)
    except OSError:
        print("Cannot create new diagnostic file; choose a new writable path.", file=sys.stderr)  # noqa: T201
        return 2
    # The launcher does not pass its arguments to Qt or the application.
    sys.argv = [sys.argv[0]]
    original_window = getattr(app_main, "MainWindow")
    recorders: list[Recorder] = []
    panels: list[QDialog] = []

    def window_factory(*args: Any, **kwargs: Any) -> Any:
        window = original_window(*args, **kwargs)
        recorder = Recorder(stream, kwargs["controller"], window)
        recorders.append(recorder)
        recorder.write({"type": "header", "format": "sonoforge-memory-queue-v1", "interval_ms": args_ns.interval_ms})
        panel = QDialog(window)
        panels.append(panel)  # retain the Python wrapper and timer for the whole session
        panel.setWindowTitle("Memory / queue markers")
        layout = QVBoxLayout(panel)
        status = QLabel("Recording. Buttons are manual event markers; no patient data is recorded.")
        layout.addWidget(status)
        timer = QTimer(panel)
        timer.setInterval(args_ns.interval_ms)

        def sample(marker: str | None = None) -> None:
            try:
                recorded = recorder.sample(marker)
            except Exception:  # noqa: BLE001 - diagnostics must not take down the application
                recorder.failed = recorder.stopped = True
                recorded = False
            if not recorded:
                timer.stop()
                status.setText("Recording stopped: diagnostic failure. File is incomplete.")

        for key, label in MARKERS.items():
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, name=key: sample(name))
            layout.addWidget(button)
        timer.timeout.connect(sample)
        timer.start()
        sample()
        panel.show()
        return window

    args_ns = args
    setattr(app_main, "MainWindow", window_factory)
    try:
        result = app_main.main()
    finally:
        setattr(app_main, "MainWindow", original_window)
        if recorders:
            recorders[0].close()
        else:
            stream.close()
    if recorders and recorders[0].failed:
        print("Diagnostic recording incomplete; see marker panel.", file=sys.stderr)  # noqa: T201
        return result or 1
    return result


if __name__ == "__main__":
    raise SystemExit(main())
