"""The one widget style the stylesheet is written for (UI-0 §5.3).

The interface is painted by :mod:`theme.qss`; the widget style decides only what
the sheet does not: menu indicators, spin-box arrows, tab close buttons and the
default metrics of a control.  Left to the platform, that part differs —
``Fusion`` on Linux, the Windows style on Windows — so the *same* stylesheet
came out with visibly different buttons, paddings and glyph alignment on the two
systems, and a screenshot comparison of the platforms was meaningless.

``Fusion`` is therefore pinned once, before the first widget exists, on every
platform: macOS and Windows inherit the look Linux already had.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from PySide6.QtWidgets import QApplication, QStyle

#: Name of the pinned style. A constant so a test can assert it is what is applied.
WIDGET_STYLE = "Fusion"


def apply_widget_style(app: QApplication, *, create: Callable[[str], QStyle | None] | None = None) -> QStyle | None:
    """Apply :data:`WIDGET_STYLE` to *app*; ``None`` when the platform lacks it.

    A missing style is not an error: the application keeps the platform default,
    which is worse for parity but never breaks the start. *create* is the
    ``QStyleFactory.create`` seam — the only reason it is injectable is that a
    test has to run without a GUI stack.
    """
    if create is None:
        from PySide6.QtWidgets import QStyleFactory

        create = QStyleFactory.create
    style = create(WIDGET_STYLE)
    if style is None:
        return None
    app.setStyle(style)
    return style
