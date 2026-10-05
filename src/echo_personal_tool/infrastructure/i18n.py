"""i18n translation module with Russian/English support.

Loads translations from JSON locale files. Supports variable substitution
and UI reload callbacks for live language switching.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)

_current_language: str = "en"
_translations: dict[str, dict[str, str]] = {}
_reload_callbacks: list[Callable[[], None]] = []

_LOCALES_DIR = Path(__file__).parent / "locales"


def _load_locales() -> None:
    global _translations
    _translations = {}
    for lang in ("ru", "en"):
        path = _LOCALES_DIR / f"{lang}.json"
        if path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                _translations[lang] = {k: v for k, v in data.items() if not k.startswith("_")}
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load locale %s: %s", lang, e)
                _translations[lang] = {}


_load_locales()


def set_language(lang: str) -> None:
    """Set the current language ('ru' or 'en')."""
    global _current_language
    if lang not in _translations:
        logger.warning("Unknown language '%s', falling back to 'en'", lang)
        lang = "en"
    _current_language = lang
    for cb in tuple(_reload_callbacks):
        try:
            cb()
        except Exception:
            logger.exception("UI reload callback failed")


def get_language() -> str:
    """Get the current language code."""
    return _current_language


def register_ui_reload(callback: Callable[[], None]) -> None:
    """Register a callback to be called when language changes."""
    _reload_callbacks.append(callback)


def unregister_ui_reload(callback: Callable[[], None]) -> None:
    """Unregister a UI reload callback."""
    try:
        _reload_callbacks.remove(callback)
    except ValueError:
        pass


def tr(key: str, **kwargs: object) -> str:
    """Translate a key to the current language.

    Supports simple variable substitution and falls back to English, then to
    the key itself. Use :func:`tr_plural` for count-sensitive text.
    """
    text = _lookup(key)
    if text is None:
        return key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, ValueError):
            logger.warning("Could not format translation key %s", key, exc_info=True)
            return text
    return text


def tr_plural(key: str, count: int | float, **kwargs: object) -> str:
    """Translate *key* using the current locale's plural form.

    Locale catalogs use ``<key>.one``, ``.few``, ``.many``, and ``.other``.
    English selects ``one`` only for 1; Russian follows the traditional
    one/few/many integer rules and uses ``other`` for fractional values.
    Missing forms fall back to ``.other``, then to the unsuffixed key.
    """
    category = plural_category(count, _current_language)
    template = _lookup(f"{key}.{category}") or _lookup(f"{key}.other") or _lookup(key)
    if template is None:
        return key
    values = {**kwargs, "count": count}
    try:
        return template.format(**values)
    except (KeyError, ValueError):
        logger.warning("Could not format plural translation key %s", key, exc_info=True)
        return template


def plural_category(count: int | float, language: str | None = None) -> str:
    """Return the CLDR-style plural category used by SonoForge's locales."""
    try:
        number = float(count)
    except (TypeError, ValueError):
        return "other"
    if not number.is_integer():
        return "other"
    value = abs(int(number))
    lang = language or _current_language
    if lang == "ru":
        mod10 = value % 10
        mod100 = value % 100
        if mod10 == 1 and mod100 != 11:
            return "one"
        if 2 <= mod10 <= 4 and not 12 <= mod100 <= 14:
            return "few"
        return "many"
    return "one" if value == 1 else "other"


def _lookup(key: str) -> str | None:
    text = _translations.get(_current_language, {}).get(key)
    if text is None:
        text = _translations.get("en", {}).get(key)
    return text
