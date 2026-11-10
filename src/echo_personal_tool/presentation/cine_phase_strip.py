"""Re-export of :class:`CinePhaseStrip` owned by :mod:`echo_personal_tool.ui.cine_phase_strip`.

Importing this module ensures the presentation theme token provider is wired
for any strip mounted inside the desktop shell.
"""

from __future__ import annotations

from echo_personal_tool.presentation import dark_theme as _dark_theme  # noqa: F401
from echo_personal_tool.ui.cine_phase_strip import (
    CinePhaseStrip,
    ThemeTokensProvider,
    Translate,
    set_default_theme_tokens_provider,
    source_label,
    warning_label,
)

__all__ = [
    "CinePhaseStrip",
    "ThemeTokensProvider",
    "Translate",
    "set_default_theme_tokens_provider",
    "source_label",
    "warning_label",
]
