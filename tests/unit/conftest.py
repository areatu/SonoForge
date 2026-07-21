"""Unit test configuration — auto-mark GUI tests."""

from __future__ import annotations

import pytest


def pytest_collection_modifyitems(config, items):
    """Automatically add 'gui' marker to tests that import QApplication."""
    for item in items:
        if _uses_qapp(item):
            item.add_marker(pytest.mark.gui)


def _uses_qapp(item) -> bool:
    """Check if test module imports QApplication."""
    try:
        source = item.fspath.read_text()
        return "QApplication" in source
    except Exception:
        return False
