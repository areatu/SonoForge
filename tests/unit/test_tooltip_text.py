"""Word-wrapped tooltips (item 2 of the 2026-10-23 acceptance list).

``QToolTip`` measures its label from the text as it stands and folds only part
of it, so a hint with a long unbreakable word arrived as one flattened strip —
measured at 1747 × 44 px for 200 characters, cut off on one side wherever the
screen edge was nearer than the strip was wide.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QPoint
from PySide6.QtGui import QHelpEvent
from PySide6.QtWidgets import QApplication, QPushButton

from echo_personal_tool.presentation.tooltip_text import (
    TOOLTIP_LINE_LIMIT,
    install_tooltip_wrapping,
    needs_wrapping,
    wrap_tooltip_text,
)


def test_a_short_text_is_left_alone() -> None:
    assert wrap_tooltip_text("Калипер") == "Калипер"
    assert needs_wrapping("Калипер") is False


def test_a_text_of_one_line_is_kept() -> None:
    text = "A" * TOOLTIP_LINE_LIMIT
    assert wrap_tooltip_text(text) == text


def test_a_long_text_folds_at_word_boundaries() -> None:
    words = ("измерение " * 12).strip()
    folded = wrap_tooltip_text(words)
    assert folded.count("\n") >= 2
    assert all(len(line) <= TOOLTIP_LINE_LIMIT for line in folded.split("\n"))
    assert folded.replace("\n", " ") == words


def test_an_unbreakable_word_is_broken() -> None:
    """The one case Qt cannot fold on its own — a path, a tag, a long token."""
    token = "X" * (TOOLTIP_LINE_LIMIT * 3)
    folded = wrap_tooltip_text(token)
    assert max(len(line) for line in folded.split("\n")) <= TOOLTIP_LINE_LIMIT
    assert folded.replace("\n", "") == token
    assert needs_wrapping(token) is True


def test_written_line_breaks_survive() -> None:
    assert wrap_tooltip_text("Строка один\nСтрока два") == "Строка один\nСтрока два"


def test_an_empty_text_stays_empty() -> None:
    assert wrap_tooltip_text("") == ""


@pytest.mark.gui
def test_a_long_tooltip_is_shown_folded(qtbot) -> None:
    """The filter answers the hover request itself, with the folded text."""
    app = QApplication.instance()
    button = QPushButton()
    qtbot.addWidget(button)
    # The wrapper is widget-local: an application-wide Python filter is unsafe
    # next to QtWebEngine's internal no-RTTI compositor objects.
    install_tooltip_wrapping(button)
    button.resize(200, 40)
    button.show()
    qtbot.waitExposed(button)
    button.setToolTip("Y" * 200)
    app.sendEvent(button, QHelpEvent(QEvent.Type.ToolTip, QPoint(5, 5), QPoint(400, 400)))
    app.processEvents()
    tips = [t for t in app.topLevelWidgets() if t.metaObject().className() == "QTipLabel"]
    assert tips, "no tooltip was shown"
    tip = tips[0]
    # One strip would be ~1700 px wide; the folded tip stays a block.
    assert tip.width() < 700
    assert tip.height() > 44
