"""Tool buttons above and beside the snapshot (UI-2 PR-3, D-08).

One list of tools (:data:`buttons.TOOL_BUTTONS`), one signal out
(``action_requested(button_id)``), three views: the 42 px row over the image, the
70 px rail beside it, and — from a later PR — the tools block of the panel.

``buttons`` is Qt-free and holds the table, the captions, the keys and the
availability rules; the widgets live in :mod:`.row` and :mod:`.rail` and are
imported from there, so a test of the table never has to build a window::

    from echo_personal_tool.presentation.tool_buttons import buttons
    from echo_personal_tool.presentation.tool_buttons.row import ToolButtonRow
"""

from echo_personal_tool.presentation.tool_buttons.buttons import (
    TOOL_BUTTONS,
    TOOL_BUTTONS_RIGHT,
    ToolButtonSpec,
    ToolButtonState,
    caption,
    catalog_tool,
    key_hint,
    payload,
    tooltip,
    unavailable_reason,
)

__all__ = [
    "TOOL_BUTTONS",
    "TOOL_BUTTONS_RIGHT",
    "ToolButtonSpec",
    "ToolButtonState",
    "caption",
    "catalog_tool",
    "key_hint",
    "payload",
    "tooltip",
    "unavailable_reason",
]
