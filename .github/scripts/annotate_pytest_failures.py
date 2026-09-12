#!/usr/bin/env python3
"""Stream pytest output and surface every failure as a GitHub annotation.

Why this exists: GitHub hides per-job logs behind blob storage that some
networks (and agent sandboxes) cannot reach, while check-run *annotations*
stay readable through the REST API. Piping the test step through this filter
keeps the full log in place and additionally publishes one ``::error``
annotation per failing test, so the failing test names are always reachable:

    gh api repos/<owner>/<repo>/check-runs/<job-check-run-id>/annotations

Usage (inside a workflow step):

    set -o pipefail
    pytest tests/unit/ -q --tb=line --no-header | python .github/scripts/annotate_pytest_failures.py

``pipefail`` keeps the step red when pytest fails; the filter itself always
exits 0 so a broken pipe cannot mask the real status.
"""

from __future__ import annotations

import re
import sys

# pytest's short summary lines look like:
#   FAILED tests/unit/test_x.py::test_y - AssertionError: ...
#   ERROR tests/unit/test_x.py - ImportError: ...
_SUMMARY = re.compile(r"^(FAILED|ERROR)\s+(\S+)(?:\s+-\s+(.*))?$")


def main() -> int:
    seen: set[tuple[str, str]] = set()
    for raw in sys.stdin:
        line = raw.rstrip("\n")
        print(line, flush=True)
        match = _SUMMARY.match(line.strip())
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
        print(f"::error title={kind} {node_id}::{message[:1800]}", flush=True)
    if seen:
        print(f"::notice::pytest failures: {len(seen)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
