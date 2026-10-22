"""i18n translation module with Russian/English support.

Loads translations from JSON locale files. Supports variable substitution
and UI reload callbacks for live language switching.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path

from echo_personal_tool.domain.translation import register_translator
from echo_personal_tool.infrastructure.safe_diagnostics import log_boundary_failure

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
            except (json.JSONDecodeError, OSError) as exc:
                log_boundary_failure(logger, "i18n.load", exc, code="invalid", level=logging.WARNING)
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
        except Exception as exc:  # noqa: BLE001
            log_boundary_failure(logger, "i18n.reload", exc, code="unexpected", level=logging.WARNING)


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
    return tr_for_language(key, _current_language, **kwargs)


def tr_for_language(key: str, language: str, **kwargs: object) -> str:
    """Translate *key* into an explicit locale without changing global UI state.

    This is useful for generated documents (notably the shortcut reference in
    HELP) that may be exported in a language other than the active interface.
    Missing translations fall back to English, matching :func:`tr`.
    """
    text = _lookup(key, language=language)
    if text is None:
        return key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, ValueError) as exc:
            log_boundary_failure(logger, "i18n.format", exc, code="invalid", level=logging.WARNING)
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
    except (KeyError, ValueError) as exc:
        log_boundary_failure(logger, "i18n.format", exc, code="invalid", level=logging.WARNING)
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


def _lookup(key: str, *, language: str | None = None) -> str | None:
    active_language = language or _current_language
    text = _translations.get(active_language, {}).get(key)
    if text is None:
        text = _translations.get("en", {}).get(key)
    return text


# Infrastructure adapts the domain-owned port to the locale catalog. Keeping
# registration here means importing the adapter is the only composition step.
register_translator(
    tr,
    translate_for_language=tr_for_language,
    translate_plural=tr_plural,
    get_language=get_language,
)
