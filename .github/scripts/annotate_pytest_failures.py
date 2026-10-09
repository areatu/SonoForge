#!/usr/bin/env python3
"""Stream pytest output and surface every failure as a GitHub annotation.

Why this exists: GitHub hides per-job logs behind blob storage that some
networks (and agent sandboxes) cannot reach, while check-run *annotations*
stay readable through the REST API. Piping the test step through this filter
keeps the full log in place and additionally publishes one ``::error``
annotation per failing test, so the failing test names are always reachable:

    gh api repos/<owner>/<repo>/check-runs/<job-check-run-id>/annotations

This script is called from the Linux CI workflow after verbose pytest output.
Its optional file argument receives the most recently reported test node after
stdout closes, so the workflow can annotate native aborts that have no pytest
failure summary.
"""

from __future__ import annotations

import re
import sys
from collections import deque
from pathlib import Path

# pytest's short summary lines look like:
#   FAILED tests/unit/test_x.py::test_y - AssertionError: ...
#   ERROR tests/unit/test_x.py - ImportError: ...
_SUMMARY = re.compile(r"^(FAILED|ERROR)\s+(\S+)(?:\s+-\s+(.*))?$")
_TEST_NODE = re.compile(r"^(tests/\S+::\S+)")
_ABORT_MARKERS = (
    "fatal python error",
    "qthread:",
    "qt fatal",
    "segmentation fault",
    "core dumped",
    "aborted",
    "assertion failure",
    "terminate called",
    "fatal signal",
    "traceback (most recent call last)",
)


def _emit(line: str) -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def main() -> int:
    node_file = sys.argv[1] if len(sys.argv) > 1 else None
    seen: set[tuple[str, str]] = set()
    abort_seen = False
    last_node: str | None = None
    last_lines: deque[str] = deque(maxlen=12)
    diagnostic_lines: deque[str] = deque(maxlen=24)
    diagnostic_context_remaining = 0
    for raw in sys.stdin:
        line = raw.rstrip("\n")
        last_lines.append(line)
        lowered = line.lower()
        if any(marker in lowered for marker in _ABORT_MARKERS):
            abort_seen = True
            diagnostic_context_remaining = 12
        if diagnostic_context_remaining:
            diagnostic_lines.append(line)
            diagnostic_context_remaining -= 1
        _emit(line)
        stripped = line.strip()
        node_match = _TEST_NODE.match(stripped)
        if node_match is not None:
            last_node = node_match.group(1)
        match = _SUMMARY.match(stripped)
        if match is None:
            continue
        kind, node_id, detail = match.group(1), match.group(2), match.group(3) or ""
        if (kind, node_id) in seen:
            continue
        seen.add((kind, node_id))
        message = f"pytest {kind.lower()}: {node_id}"
        if detail:
            message = f"{message} — {detail}"
        # GitHub trims long annotation messages; the node id survives the cut.
        _emit(f"::error title={kind} {node_id}::{message[:1800]}")
    if node_file is not None:
        if last_node is not None:
            with open(node_file, "w", encoding="utf-8") as last_node_stream:
                last_node_stream.write(last_node + "\n")
        tail_lines = diagnostic_lines or last_lines
        with open(node_file + ".tail", "w", encoding="utf-8") as tail_stream:
            tail_stream.write("\n".join(tail_lines) + "\n")
    if seen:
        _emit(f"::notice::pytest failures: {len(seen)}")
    elif abort_seen:
        # No FAILED summary: a native abort. faulthandler prints the crashing
        # frame first; the log tail is only the pytest entry point.
        _emit_abort_frames(list(last_lines))
    return 0


def _emit_abort_frames(tail: list[str]) -> None:
    log_path = Path("/tmp/pytest.log")
    lines = log_path.read_text(errors="replace").splitlines() if log_path.is_file() else tail
    start = next(
        (index for index, line in enumerate(lines) if "Fatal Python error" in line or "Current thread" in line),
        0,
    )
    window = lines[start : start + 35] or lines[:35]
    for index, line in enumerate(window):
        safe = line.replace("%", "%25").replace("\r", "")[:700]
        _emit(f"::error title=pytest frame {index}::{safe}")
    for index, line in enumerate(lines[:12]):
        safe = line.replace("%", "%25").replace("\r", "")[:700]
        _emit(f"::notice title=pytest log {index}::{safe}")


if __name__ == "__main__":
    raise SystemExit(main())
