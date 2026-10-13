"""Record the test node id before setup and the test body run.

pytest-timeout's thread method calls ``os._exit(1)`` and leaves no FAILED
summary. Quiet mode also does not print node ids, so a hang is otherwise
anonymous. This file is flushed before the test so the workflow can name the
hung test after the process is killed.
"""

from __future__ import annotations

import os
from pathlib import Path

_BASE_PATH = Path(os.environ.get("PYTEST_CURRENT_NODE_FILE", "/tmp/pytest-last-node"))
_WORKER_ID = os.environ.get("PYTEST_XDIST_WORKER")
_PATH = _BASE_PATH if _WORKER_ID is None else _BASE_PATH.with_name(f"{_BASE_PATH.name}-{_WORKER_ID}")


def pytest_runtest_logstart(nodeid: str, location: tuple[str, int | None, str]) -> None:
    """Persist each worker's active test separately before its body starts."""
    del location
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    with _PATH.open("w", encoding="utf-8") as handle:
        handle.write(nodeid + "\n")
        handle.flush()
        os.fsync(handle.fileno())
