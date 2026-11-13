"""Run the curated regression lane with no Qt plugins or imports (issue #556)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    modules = json.loads((root / "tests/pure_core_manifest.json").read_text())["modules"]
    env = os.environ.copy()
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env.pop("PYTEST_PLUGINS", None)
    env.pop("PYTEST_ADDOPTS", None)
    return subprocess.call(
        [
            sys.executable,
            "-m",
            "pytest",
            "--pure-core",
            "-p",
            "pytest_timeout",
            "-o",
            "addopts=",
            *modules,
            *sys.argv[1:],
        ],
        cwd=root,
        env=env,
    )


if __name__ == "__main__":
    raise SystemExit(main())
