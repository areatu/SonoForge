"""Unit test configuration — skip GUI tests in CI."""

from __future__ import annotations

import os
from pathlib import Path

# In CI, skip test files that import QApplication (crashes headless)
if os.environ.get("CI"):
    _unit_dir = Path(__file__).parent
    collect_ignore_glob = [
        str(f) for f in _unit_dir.glob("test_*.py")
        if "QApplication" in f.read_text(errors="ignore")
    ]
