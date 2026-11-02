"""TP-6 slice A-17 / G-8: the palette filter and the panel update stay fast.

The budgets come from the spec: the Ctrl+K filter answers within 16 ms per
keystroke, and a panel refresh after a measurement stays within 50 ms (p95).
The samples are medians/p95 over repeated runs on a warmed process, so a
single scheduler hiccup in CI does not fail the build.
"""

from __future__ import annotations

import statistics
import time

import pytest

from echo_personal_tool.domain.protocol_definitions import LV_LINEAR
from echo_personal_tool.domain.protocols import progress
from echo_personal_tool.domain.services.study_projection import build_study_projection
from echo_personal_tool.presentation.command_catalog import (
    match_commands,
    protocol_commands,
    reference_commands,
)

#: Queries a user actually types: empty, RU/EN fragments of every group.
_QUERIES = ("", "лж", "lv", "симп", "откр", "калиб", "справ", "настрой")
_FILTER_BUDGET_MS = 16.0
_PANEL_BUDGET_MS = 50.0


def _filter_once(query: str) -> None:
    """The full path of ``CommandPalette._populate`` for one keystroke."""
    match_commands(query, profile="full")
    protocol_commands(query)
    reference_commands(query)


def test_palette_filter_stays_within_16ms_per_keystroke() -> None:
    for query in _QUERIES:
        _filter_once(query)  # warm the handbook, the translations and the catalogue
    samples: list[float] = []
    for query in _QUERIES:
        for _ in range(10):
            start = time.perf_counter()
            _filter_once(query)
            samples.append((time.perf_counter() - start) * 1000.0)
    assert statistics.median(samples) <= _FILTER_BUDGET_MS


@pytest.mark.gui
def test_panel_progress_update_stays_within_50ms_p95(qtbot) -> None:
    from PySide6.QtTest import QTest

    from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
    from echo_personal_tool.infrastructure.user_preferences import UserPreferences
    from echo_personal_tool.presentation.tool_panel import ToolPanel

    panel = ToolPanel(UserPreferences())
    qtbot.addWidget(panel)
    panel.resize(320, 640)
    panel.show()
    QTest.qWait(10)
    current = progress(LV_LINEAR, build_study_projection(MeasurementSnapshot()))
    samples: list[float] = []
    for _ in range(40):
        start = time.perf_counter()
        panel.set_protocol_progress(current)
        samples.append((time.perf_counter() - start) * 1000.0)
    p95 = sorted(samples)[int(0.95 * (len(samples) - 1))]
    assert p95 <= _PANEL_BUDGET_MS
