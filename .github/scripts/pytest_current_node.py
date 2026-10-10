"""Record the test node id before setup and the test body run.

pytest-timeout's thread method calls ``os._exit(1)`` and leaves no FAILED
summary. Quiet mode also does not print node ids, so a hang is otherwise
anonymous. This file is flushed before the test so the workflow can name the
hung test after the process is killed.
"""

from __future__ import annotations

import os

_PATH = os.environ.get("PYTEST_CURRENT_NODE_FILE", "/tmp/pytest-last-node")


def pytest_runtest_logstart(nodeid: str, location: tuple[str, int | None, str]) -> None:
    del location
    with open(_PATH, "w", encoding="utf-8") as handle:
        handle.write(nodeid + "\n")
        handle.flush()
        os.fsync(handle.fileno())
