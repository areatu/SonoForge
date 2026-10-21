"""Domain port for translating user-facing domain text.

The domain owns the dependency; infrastructure supplies the locale-backed
implementation during application startup. Keeping the port callable makes it
usable by pure domain modules without importing locale files or UI state.
"""

from __future__ import annotations

from typing import Protocol


class Translator(Protocol):
    """Translate a message key, applying optional named substitutions."""

    def __call__(self, key: str, **kwargs: object) -> str: ...


def _unconfigured_translator(key: str, **_kwargs: object) -> str:
    """Safe fallback for domain-only tools that have not installed an adapter."""
    return key


_translator: Translator = _unconfigured_translator


def register_translator(translator: Translator) -> None:
    """Install the infrastructure adapter for domain translations.

    The infrastructure i18n module calls this once it has loaded its locale
    catalogs. Tests and standalone domain clients may install their own adapter.
    """
    global _translator
    _translator = translator


def tr(key: str, **kwargs: object) -> str:
    """Translate *key* through the installed adapter."""
    return _translator(key, **kwargs)
