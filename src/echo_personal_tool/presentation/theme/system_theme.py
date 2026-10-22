"""Detection of the operating system colour scheme (UI-0, PR-1).

The theme "system" used to be resolved in two places: ``_is_system_dark()``
(correct) and ``_resolve_theme("system")`` (inverted on Windows — the dark
system theme produced the *light* palette, spec §2.1). Two detectors, two
answers, an invisible logo on Linux and a light interface on a dark Windows.

There is one detector now. :func:`system_theme_id` returns the concrete theme
id for the current system scheme, and both the palette and the logo follow it.

Windows reads ``AppsUseLightTheme`` from the registry: ``0`` means the system
is *dark* (that inversion was the bug), ``1`` means light.
"""

from __future__ import annotations

import sys

from echo_personal_tool.presentation.theme.palettes import THEME_IDS

THEME_DARK = "dark"
THEME_LIGHT = "light"

#: Registry value that tells whether applications should use a light theme.
_WINDOWS_THEME_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
_WINDOWS_THEME_VALUE = "AppsUseLightTheme"


def _windows_apps_use_light_theme() -> bool | None:
    """Read ``AppsUseLightTheme`` from the Windows registry.

    Returns ``True`` for a light system theme, ``False`` for a dark one and
    ``None`` when the value cannot be read (no Windows, no registry, no
    permission).
    """
    try:
        import winreg
    except ImportError:
        return None
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WINDOWS_THEME_KEY)
        try:
            value, _ = winreg.QueryValueEx(key, _WINDOWS_THEME_VALUE)
        finally:
            winreg.CloseKey(key)
        return bool(value)
    except Exception:
        return None


def _macos_is_dark() -> bool | None:
    """Ask macOS for the interface style (``None`` when it cannot be read)."""
    import subprocess

    try:
        result = subprocess.run(
            ["defaults", "read", "-g", "AppleInterfaceStyle"],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return None
    return "Dark" in result.stdout


def system_theme_id() -> str:
    """Return the theme id that matches the current system colour scheme.

    ``"dark"`` or ``"light"``. The dark theme is the fallback whenever the
    system cannot be asked (no registry, no ``defaults``, unknown desktop).
    """
    if sys.platform == "win32":
        light = _windows_apps_use_light_theme()
        if light is None:
            return THEME_DARK
        return THEME_LIGHT if light else THEME_DARK
    if sys.platform == "darwin":
        dark = _macos_is_dark()
        if dark is None:
            return THEME_DARK
        return THEME_DARK if dark else THEME_LIGHT
    # Linux and the other desktops: the application keeps its dark theme, as
    # before. The GTK theme name is not a reliable indicator of the desktop
    # colour scheme, and a wrong guess would change the interface under the
    # user's feet.
    return THEME_DARK


def is_system_dark() -> bool:
    """Tell whether the system currently uses a dark colour scheme."""
    return system_theme_id() == THEME_DARK


def resolve_theme_id(mode: str) -> str:
    """Resolve a theme mode to a concrete theme id.

    "system" follows the current system colour scheme; an unknown mode falls
    back to the dark theme, as before.
    """
    if mode == "system":
        return system_theme_id()
    if mode in THEME_IDS:
        return mode
    return THEME_DARK
