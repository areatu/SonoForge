"""Design tokens, palettes and the stylesheet builder (UI-0, PR-1).

The presentation layer has three layers of appearance (UI redesign spec §5.1):

* :mod:`.tokens` — the semantic vocabulary (the role of a colour),
* :mod:`.palettes` — the raw colours of every theme,
* :mod:`.qss` — the stylesheet, assembled from the tokens.

:mod:`.system_theme` resolves the "system" theme to a concrete one.

``presentation.dark_theme`` stays the public facade of the package: it hands
out the legacy 28-key palette until every call site is moved to tokens.
"""

from echo_personal_tool.presentation.theme.palettes import (
    LEGACY_PALETTES,
    PALETTES,
    THEME_DARK,
    THEME_GRAPHITE,
    THEME_IDS,
    THEME_LIGHT,
    THEME_VS_CODE_DARK,
    THEME_VS_CODE_LIGHT,
    get_legacy_palette,
    get_palette_tokens,
    is_dark_theme,
)
from echo_personal_tool.presentation.theme.qss import (
    build_clinical_stylesheet,
    clear_stylesheet_cache,
)
from echo_personal_tool.presentation.theme.system_theme import (
    is_system_dark,
    system_theme_id,
)
from echo_personal_tool.presentation.theme.tokens import (
    LEGACY_KEY_TO_TOKEN,
    LEGACY_KEYS,
    REQUIRED_TOKEN_NAMES,
    TOKEN_NAMES,
    TOKENS,
    legacy_to_tokens,
    tokens_to_legacy,
)

__all__ = [
    "LEGACY_KEYS",
    "LEGACY_KEY_TO_TOKEN",
    "LEGACY_PALETTES",
    "PALETTES",
    "REQUIRED_TOKEN_NAMES",
    "THEME_DARK",
    "THEME_GRAPHITE",
    "THEME_IDS",
    "THEME_LIGHT",
    "THEME_VS_CODE_DARK",
    "THEME_VS_CODE_LIGHT",
    "TOKENS",
    "TOKEN_NAMES",
    "build_clinical_stylesheet",
    "clear_stylesheet_cache",
    "get_legacy_palette",
    "get_palette_tokens",
    "is_dark_theme",
    "is_system_dark",
    "legacy_to_tokens",
    "system_theme_id",
    "tokens_to_legacy",
]
