"""Word-wrapped tooltips (item 2 of the 2026-10-23 acceptance list).

``QToolTip`` measures its label from the text as it stands, and ``QTipLabel``
wraps only what has spaces *and* is long enough for Qt's own heuristic.  A hint
that carries one long unbreakable word therefore came out as a single strip —
measured here at 1747 × 44 px for 200 characters — which reads as a flattened
tooltip and is cut off on one side wherever the screen edge is nearer than the
strip is wide.

The filter below answers the ``QEvent::ToolTip`` request itself, with the text
wrapped at word boundaries, so a tooltip is a compact block that always shows
all of it.  Short hints are left to Qt untouched.
"""

from __future__ import annotations

import textwrap
from typing import Any

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QToolTip, QWidget

#: Characters a tooltip line keeps before it folds.  At the UI font this is a
#: little over 400 px — wide enough for a whole sentence, narrow enough that the
#: tip never reaches the screen edge.
TOOLTIP_LINE_LIMIT = 56

#: Below this length Qt's own layout is already a single compact line.
TOOLTIP_WRAP_THRESHOLD = TOOLTIP_LINE_LIMIT


def wrap_tooltip_text(text: str, limit: int = TOOLTIP_LINE_LIMIT) -> str:
    """Fold *text* into lines of at most *limit* characters.

    Explicit line breaks of the source are kept, so a tooltip that was laid out
    by hand stays as it was written; only the lines that are too long are
    folded.  A word longer than the limit is broken, because an unbreakable
    word is exactly what Qt cannot fold on its own.
    """
    if not text:
        return text
    folded: list[str] = []
    for paragraph in text.split("\n"):
        if len(paragraph) <= limit:
            folded.append(paragraph)
            continue
        folded.extend(
            textwrap.wrap(
                paragraph,
                width=limit,
                break_long_words=True,
                break_on_hyphens=False,
                replace_whitespace=True,
            )
            or [""]
        )
    return "\n".join(folded)


def needs_wrapping(text: str, limit: int = TOOLTIP_LINE_LIMIT) -> bool:
    """Whether Qt would paint *text* wider than one folded line allows."""
    if len(text) <= TOOLTIP_WRAP_THRESHOLD:
        # A short text can still hold one unbreakable token — a path, a DICOM
        # tag — and that one Qt leaves alone, however long it is.
        return any(len(word) > limit for word in text.split())
    return True


def wrapped_tooltip(text: str) -> str:
    """Fold a long hint at the source, without an application event filter."""
    return wrap_tooltip_text(text) if needs_wrapping(text) else text


class TooltipWrapFilter(QObject):
    """Widget-local filter that shows a folded tooltip instead of a wide strip."""

    def eventFilter(self, watched: Any, event: Any) -> bool:  # noqa: ANN401 - Qt event
        if event is None or event.type() != QEvent.Type.ToolTip:
            return False
        widget = watched if isinstance(watched, QWidget) else None
        if widget is None:
            return False
        text = widget.toolTip()
        if not text or not needs_wrapping(text):
            return False
        wrapped = wrap_tooltip_text(text)
        if wrapped == text:
            return False
        global_pos = event.globalPos()
        QToolTip.showText(global_pos, wrapped, widget)
        return True


def install_tooltip_wrapping(widget: QObject) -> TooltipWrapFilter:
    """Install the wrapper on one explicitly owned widget, never on QApplication.

    Application-wide Python filters can crash beside QtWebEngine's internal
    no-RTTI objects (Shiboken wraps the receiver before the filter runs).  Long
    tool hints are folded at the source instead; this helper remains available
    for a single widget that needs the legacy behaviour.
    """
    existing = getattr(widget, "_tooltip_wrap_filter", None)
    if isinstance(existing, TooltipWrapFilter):
        return existing
    wrapped = TooltipWrapFilter(widget)
    widget.installEventFilter(wrapped)
    widget._tooltip_wrap_filter = wrapped
    return wrapped
