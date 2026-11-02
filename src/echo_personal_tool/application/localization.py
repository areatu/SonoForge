"""Application facade for UI localization.

Presentation translates through this Qt-free contract instead of importing
the infrastructure locale store directly (S2-03, #307).  The adapter stays in
``infrastructure.i18n`` — it reads the packaged JSON locale files — and this
module re-exports the public translation API.  Unlike the settings facades,
the import is module-level: the adapter pulls no Qt, and ``tr`` runs on hot
UI paths where a per-call lazy import would be pure overhead.
"""

from __future__ import annotations

from echo_personal_tool.infrastructure.i18n import (
    get_language,
    register_ui_reload,
    set_language,
    tr,
    tr_for_language,
    tr_plural,
    unregister_ui_reload,
)

__all__ = [
    "get_language",
    "register_ui_reload",
    "set_language",
    "tr",
    "tr_for_language",
    "tr_plural",
    "unregister_ui_reload",
]
