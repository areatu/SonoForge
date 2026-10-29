"""Production code must not subscribe Python filters to QApplication.

PySide6 6.11.2 + QtWebEngine can segfault in Shiboken while wrapping an internal
no-RTTI RenderWidgetHostViewQtDelegateItem for an application-wide event filter.
The rejection has to happen before the filter is installed, not inside its body.
"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "echo_personal_tool"
_APP_FILTER = re.compile(r"(?:\bapp\b|\bapplication\b|QApplication\.instance\(\))\s*\.\s*installEventFilter\s*\(")


def test_no_application_wide_python_event_filters() -> None:
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if _APP_FILTER.search(line):
                offenders.append(f"{path.relative_to(SRC)}:{lineno}: {line.strip()}")
    assert offenders == []
