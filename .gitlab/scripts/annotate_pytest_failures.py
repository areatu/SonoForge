#!/usr/bin/env python3
"""Stream pytest output and surface failures for GitLab CI.

GitLab doesn't have native annotations like GitHub, but this script:
1. Passes through full pytest output (job log)
2. Captures the last test node before exit (for native aborts)
3. Writes a summary file for debugging
4. Exits with pytest's exit code
"""

from __future__ import annotations

import re
import sys
from collections import deque
from pathlib import Path

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
    try:
        failure_status = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    except ValueError:
        failure_status = 0

    seen: set[tuple[str, str]] = set()
    abort_seen = False
    last_node: str | None = None
    last_lines: deque[str] = deque(maxlen=80)
    diagnostic_lines: deque[str] = deque(maxlen=60)
    diagnostic_context_remaining = 0

    for raw in sys.stdin:
        line = raw.rstrip("\n")
        last_lines.append(line)
        lowered = line.lower()

        timed_out = "timeout" in lowered and "+" in line
        if timed_out or any(marker in lowered for marker in _ABORT_MARKERS):
            abort_seen = True
            diagnostic_context_remaining = 40

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
        _emit(f"[GITLAB-FAILURE] {message}")

    if node_file is not None:
        if last_node is not None:
            with open(node_file, "w", encoding="utf-8") as f:
                f.write(last_node + "\n")
        tail_lines = diagnostic_lines or last_lines
        with open(node_file + ".tail", "w", encoding="utf-8") as f:
            f.write("\n".join(tail_lines) + "\n")

    if seen:
        _emit(f"[GITLAB-SUMMARY] pytest failures: {len(seen)}")
    elif failure_status != 0 or abort_seen:
        _emit("[GITLAB-SUMMARY] pytest crash/abort detected — see job log")

    return failure_status


if __name__ == "__main__":
    raise SystemExit(main())