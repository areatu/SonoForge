#!/usr/bin/env python3
"""Stream pytest output and surface every failure as a GitHub annotation.

Why this exists: GitHub hides per-job logs behind blob storage that some
networks (and agent sandboxes) cannot reach, while check-run *annotations*
stay readable through the REST API. Piping the test step through this filter
keeps the full log in place and additionally publishes one ``::error``
annotation per failing test, so the failing test names are always reachable:

    gh api repos/<owner>/<repo>/check-runs/<job-check-run-id>/annotations

This script is called from the Linux CI workflow after pytest output. Its
optional file argument receives the most recently reported node, or the active
node recorded by the worker that crashed, so the workflow can annotate native
aborts and timeouts that have no pytest failure summary.
"""

from __future__ import annotations

import os
import re
import sys
from collections import deque
from pathlib import Path

# pytest's short summary lines look like:
#   FAILED tests/unit/test_x.py::test_y - AssertionError: ...
#   ERROR tests/unit/test_x.py - ImportError: ...
_SUMMARY = re.compile(r"^(FAILED|ERROR)\s+(\S+)(?:\s+-\s+(.*))?$")
_TEST_NODE = re.compile(r"(tests/\S+::\S+)")
_WORKER_CRASH = re.compile(r"\b(?:worker\s+)?['\"]?(gw\d+)['\"]?\s+crashed\b", re.IGNORECASE)
_WORKER_CRASH_NODE = re.compile(
    r"\b(?:worker\s+)?['\"]?(gw\d+)['\"]?\s+crashed\s+while\s+running\s+['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)
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
    crashed_workers: list[str] = []
    crashed_worker_nodes: list[str] = []
    last_lines: deque[str] = deque(maxlen=80)
    diagnostic_lines: deque[str] = deque(maxlen=60)
    diagnostic_context_remaining = 0
    for raw in sys.stdin:
        line = raw.rstrip("\n")
        last_lines.append(line)
        lowered = line.lower()
        worker_node_match = _WORKER_CRASH_NODE.search(line)
        if worker_node_match is not None:
            crashed_workers.append(worker_node_match.group(1))
            crashed_worker_nodes.append(worker_node_match.group(2))
        else:
            worker_match = _WORKER_CRASH.search(line)
            if worker_match is not None:
                crashed_workers.append(worker_match.group(1))

        # pytest-timeout's thread method prints "+++ Timeout +++" and then
        # os._exit(1). There is no FAILED summary and no traceback header.
        timed_out = "timeout" in lowered and "+" in line
        if timed_out or any(marker in lowered for marker in _ABORT_MARKERS):
            abort_seen = True
            diagnostic_context_remaining = 40
        if diagnostic_context_remaining:
            diagnostic_lines.append(line)
            diagnostic_context_remaining -= 1
        _emit(line)
        stripped = line.strip()
        node_match = _TEST_NODE.search(stripped)
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
        node_path = Path(node_file)
        abort_node = None
        if failure_status != 0 and (crashed_workers or crashed_worker_nodes or not seen):
            abort_node = next(iter(crashed_worker_nodes), None) or _last_worker_node(node_path, crashed_workers)
        node_to_write = abort_node or last_node
        if node_to_write is not None:
            node_path.parent.mkdir(parents=True, exist_ok=True)
            node_path.write_text(node_to_write + "\n", encoding="utf-8")
        tail_lines = diagnostic_lines or last_lines
        node_path.with_name(node_path.name + ".tail").write_text("\n".join(tail_lines) + "\n", encoding="utf-8")
    if seen:
        _emit(f"::notice::pytest failures: {len(seen)}")
    elif failure_status != 0 or abort_seen:
        # No FAILED summary. A native abort or pytest-timeout's os._exit(1)
        # both look like this. Publish the banner window and the log tail so
        # the hung test is visible without downloading the job log.
        # GitHub keeps about 10 error annotations per step. The crash stack
        # follows "Fatal Python error" / the timeout banner; the log tail is
        # only the pytest entry point and must not crowd that window out.
        _emit_named_lines("pytest crash", _crash_window(list(last_lines)))
    return 0


def _last_worker_node(base: Path, crashed_workers: list[str]) -> str | None:
    """Read the active node recorded by the worker that died, if available."""
    for worker_id in dict.fromkeys(crashed_workers):
        worker_path = base.with_name(f"{base.name}-{worker_id}")
        if worker_path.is_file():
            node_id = worker_path.read_text(encoding="utf-8", errors="replace").strip()
            if node_id:
                return node_id

    worker_paths = list(base.parent.glob(f"{base.name}-gw*"))
    if not worker_paths:
        return None
    latest = max(worker_paths, key=lambda path: path.stat().st_mtime_ns)
    node_id = latest.read_text(encoding="utf-8", errors="replace").strip()
    return node_id or None


def _emit_named_lines(title: str, lines: list[str]) -> None:
    for index, line in enumerate(lines):
        safe = line.replace("%", "%25").replace("\r", "")[:700]
        if safe.strip():
            _emit(f"::error title={title} {index}::{safe}")


def _crash_window(tail: list[str]) -> list[str]:
    log_path = Path(os.environ.get("PYTEST_LOG_FILE", "/tmp/pytest.log"))
    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines() if log_path.is_file() else tail
    marker_at = next(
        (
            index
            for index, line in enumerate(lines)
            if "Fatal Python error" in line
            or "Segmentation fault" in line
            or ("timeout" in line.lower() and "+" in line)
        ),
        None,
    )
    if marker_at is None:
        return lines[-8:]
    window = lines[marker_at : marker_at + 40]
    useful = [
        line
        for line in window
        if any(token in line for token in ("echo_personal_tool", "tests/", "Fatal", "Segmentation", "Timeout", "File "))
    ]
    return (useful or window)[:8]


if __name__ == "__main__":
    raise SystemExit(main())
