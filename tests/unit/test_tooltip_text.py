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


def test_theme_stylesheet_does_not_clip_tooltip_text() -> None:
    """QTipLabel measures before the QSS box model: padding/radius clip the glyphs.

    The spacing comes from ``qproperty-margin`` (part of Qt's sizeHint) and the
    ground is fully opaque, so moving between buttons cannot leave stale
    corners over the cine viewport (2026-11-04 UI polish).
    """
    from echo_personal_tool.presentation.theme import qss

    sheet = qss.build_clinical_stylesheet(13, "dark")
    block = sheet.split("QToolTip {", 1)[1].split("}", 1)[0]
    assert "padding" not in block
    assert "border-radius" not in block
    assert "qproperty-margin" in block
    assert "opacity: 255" in block
    assert "background-color:" in block


@pytest.mark.gui
def test_styled_tooltip_fits_the_whole_caption(qtbot) -> None:
    from echo_personal_tool.presentation.theme import qss

    app = QApplication.instance()
    previous = app.styleSheet()
    app.setStyleSheet(qss.build_clinical_stylesheet(13, "dark"))
    try:
        button = QPushButton()
        qtbot.addWidget(button)
        text = "Объём (сплайн, метод дисков)"
        button.setToolTip(text)
        button.resize(120, 40)
        button.show()
        qtbot.waitExposed(button)
        app.sendEvent(button, QHelpEvent(QEvent.Type.ToolTip, QPoint(5, 5), QPoint(400, 400)))
        app.processEvents()
        tips = [t for t in app.topLevelWidgets() if t.metaObject().className() == "QTipLabel"]
        assert tips, "no tooltip was shown"
        tip = tips[0]
        assert tip.text() == text
        metrics = tip.fontMetrics()
        assert tip.width() >= metrics.horizontalAdvance(text)
        assert tip.height() >= metrics.height()
        assert tip.windowOpacity() == 1.0
        tip.close()
    finally:
        app.setStyleSheet(previous)


def test_tool_button_reason_stays_one_phrase() -> None:
    """A folded hint must not split the short «button unavailable» reason."""
    from echo_personal_tool.presentation.tool_buttons.base import _join

    long_hint = (
        "Определить диастолу и систолу (D/S) на текущем эхо-клипе: "
        "явный запрос врача, если в заголовке нет кардиологической метки."
    )
    folded = _join(long_hint, "Нужен клип")
    assert "Нужен клип" in folded
    assert max(len(line) for line in folded.split("\n")) <= 56
    assert _join("Калипер", "") == "Калипер"


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
