"""Frame overlay model and styles (extracted from viewer_widget).

The frame overlay is the measurement transcript on top of the image
(«IVSd: 10.0 mm (20.0 px)», the LV-Auto protocol prompt, the calibration
banner).  This module owns its *state* — the ordered lines and which visual
variant applies — and the QSS style factories for all overlay variants
(default / calibration prompt / calibration success).  The QLabel that
renders the result stays in ``viewer_widget`` (it must be a child of the
viewer for the composite export), and its refresh is one binding block.

Extracted as the overlay-rendering seam of the 2026-11-27 audit
preparation; no behaviour changed.  The colours come from the palette tokens, the same
source the results overlay and the framed-panel styles use.
"""

from __future__ import annotations

from typing import Final

from echo_personal_tool.application.localization import tr
from echo_personal_tool.presentation.theme.palettes import (
    OVERLAY_CALIBRATION_PROMPT_BORDER,
    OVERLAY_CALIBRATION_PROMPT_TEXT,
    OVERLAY_CALIBRATION_SUCCESS,
    OVERLAY_DEFAULT_BORDER,
    OVERLAY_DEFAULT_TEXT,
)

#: Style variants of the overlay label.
DEFAULT_STYLE: Final = (
    "background-color: rgba(0, 0, 0, 180);"
    f" color: {OVERLAY_DEFAULT_TEXT};"
    " padding: 8px; font-size: 12px;"
    f" border: 1px solid {OVERLAY_DEFAULT_BORDER};"
)
CALIBRATION_PROMPT_STYLE: Final = (
    "background-color: rgba(0, 0, 0, 210);"
    f" color: {OVERLAY_CALIBRATION_PROMPT_TEXT};"
    " padding: 20px 36px;"
    " font-size: 22px; font-weight: bold;"
    f" border: 2px solid {OVERLAY_CALIBRATION_PROMPT_BORDER};"
    " border-radius: 8px;"
)
CALIBRATION_SUCCESS_STYLE: Final = (
    "background-color: rgba(0, 0, 0, 210);"
    f" color: {OVERLAY_CALIBRATION_SUCCESS};"
    " padding: 20px 36px;"
    " font-size: 22px; font-weight: bold;"
    f" border: 2px solid {OVERLAY_CALIBRATION_SUCCESS};"
    " border-radius: 8px;"
)

#: The banner width the calibration variants reserve (px).
CALIBRATION_MIN_WIDTH: Final = 360

#: Localization keys of the calibration overlay notices (single-line banners).
CALIBRATION_PROMPT_OVERLAY_KEY: Final = "viewer.calibration.calibration_prompt"
CALIBRATION_SUCCESS_OVERLAY_KEY: Final = "viewer.calibration.auto_ok"


class FrameOverlayModel:
    """The ordered overlay lines plus the visual variant that applies.

    The calibration banner and success notice are recognised by their exact
    single-line content (translated at comparison time), as before — the
    recognition is a display concern, not a data one, so the model keeps the
    raw lines untouched.
    """

    __slots__ = ("_lines",)

    def __init__(self) -> None:
        self._lines: list[str] = []

    def append(self, line: str) -> None:
        self._lines.append(line)

    def clear(self) -> None:
        self._lines.clear()

    def lines(self) -> tuple[str, ...]:
        """The lines of the frame overlay, in the order they were added."""
        return tuple(self._lines)

    def text(self) -> str:
        """The joined label text (empty when the overlay is hidden)."""
        return "\n".join(self._lines)

    def _is_calibration(self, key: str) -> bool:
        """The banner is recognised by its exact single translated line."""
        return self._lines == [tr(key)]

    def is_calibration_prompt(self) -> bool:
        return self._is_calibration(CALIBRATION_PROMPT_OVERLAY_KEY)

    def is_calibration_success(self) -> bool:
        return self._is_calibration(CALIBRATION_SUCCESS_OVERLAY_KEY)

    def style(self) -> tuple[str, int]:
        """The (stylesheet, minimum width) the overlay label must show."""
        if self.is_calibration_prompt():
            return CALIBRATION_PROMPT_STYLE, CALIBRATION_MIN_WIDTH
        if self.is_calibration_success():
            return CALIBRATION_SUCCESS_STYLE, CALIBRATION_MIN_WIDTH
        return DEFAULT_STYLE, 0
