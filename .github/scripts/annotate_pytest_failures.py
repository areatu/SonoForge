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

# pytest's short summary lines look like:
#   FAILED tests/unit/test_x.py::test_y - AssertionError: ...
#   ERROR tests/unit/test_x.py - ImportError: ...
_SUMMARY = re.compile(r"^(FAILED|ERROR)\s+(\S+)(?:\s+-\s+(.*))?$")
_TEST_NODE = re.compile(r"^(tests/\S+::\S+)")


def _emit(line: str) -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def main() -> int:
    node_file = sys.argv[1] if len(sys.argv) > 1 else None
    seen: set[tuple[str, str]] = set()
    last_node: str | None = None
    last_lines: deque[str] = deque(maxlen=12)
    for raw in sys.stdin:
        line = raw.rstrip("\n")
        last_lines.append(line)
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
        with open(node_file + ".tail", "w", encoding="utf-8") as tail_stream:
            tail_stream.write("\n".join(last_lines) + "\n")
    if seen:
        _emit(f"::notice::pytest failures: {len(seen)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
