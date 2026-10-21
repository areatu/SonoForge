"""Domain port for translating user-facing domain text.

The domain owns the dependency; infrastructure supplies the locale-backed
implementation during application startup. Keeping the port independent of
locale files and UI state lets domain modules be exercised in isolation.
"""

from __future__ import annotations

from collections.abc import Callable

Translator = Callable[..., str]
LanguageGetter = Callable[[], str]


def _unconfigured_translator(key: str, **_kwargs: object) -> str:
    """Safe fallback for domain-only tools that have not installed an adapter."""
    return key


def _unconfigured_explicit_translator(key: str, _language: str, **_kwargs: object) -> str:
    return key


def _unconfigured_plural_translator(key: str, _count: int | float, **_kwargs: object) -> str:
    return key


_translator: Translator = _unconfigured_translator
_explicit_translator: Translator = _unconfigured_explicit_translator
_plural_translator: Translator = _unconfigured_plural_translator
_language_getter: LanguageGetter = lambda: "en"


def register_translator(
    translator: Translator,
    *,
    translate_for_language: Translator | None = None,
    translate_plural: Translator | None = None,
    get_language: LanguageGetter | None = None,
) -> None:
    """Install the infrastructure adapter for domain translations.

    The infrastructure i18n module calls this once it has loaded its locale
    catalogs. Tests and standalone domain clients may install their own adapter.
    Optional callbacks keep lightweight adapters focused on singular messages.
    """
    global _translator, _explicit_translator, _plural_translator, _language_getter
    _translator = translator
    _explicit_translator = translate_for_language or _unconfigured_explicit_translator
    _plural_translator = translate_plural or _unconfigured_plural_translator
    _language_getter = get_language or (lambda: "en")


def tr(key: str, **kwargs: object) -> str:
    """Translate *key* through the installed adapter."""
    return _translator(key, **kwargs)


def tr_for_language(key: str, language: str, **kwargs: object) -> str:
    """Translate *key* into an explicit locale through the installed adapter."""
    return _explicit_translator(key, language, **kwargs)


def tr_plural(key: str, count: int | float, **kwargs: object) -> str:
    """Translate a plural message through the installed adapter."""
    return _plural_translator(key, count, **kwargs)


def get_language() -> str:
    """Return the currently selected locale code (English before adapter setup)."""
    return _language_getter()
