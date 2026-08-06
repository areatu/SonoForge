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

_current_language: str = "ru"
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
    for cb in _reload_callbacks:
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


def tr(key: str, **kwargs: str) -> str:
    """Translate a key to the current language.

    Supports simple variable substitution: tr("loading", name="file.dcm")
    Falls back to English, then to the key itself.
    """
    lang_dict = _translations.get(_current_language, {})
    text = lang_dict.get(key)
    if text is None:
        en_dict = _translations.get("en", {})
        text = en_dict.get(key)
    if text is None:
        return key
    if kwargs:
        try:
            return text.format(**kwargs)
        except KeyError:
            return text
    return text
