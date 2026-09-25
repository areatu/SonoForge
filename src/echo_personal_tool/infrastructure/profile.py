"""Build profiles and portable-mode helpers.

SonoForge has two runtime profiles:

- ``full`` (default) — the complete application: AI (ONNX) segmentation,
  ASE reference viewer (QtWebEngine), reference constructor, host-based
  settings (QSettings registry / OS keyring).
- ``presenter`` — the lightweight **SonoForge Presenter** build for demos
  from a USB stick on other people's machines: no ONNX runtime, no
  reference UI, no QtWebEngine/PyMuPDF/openpyxl, and *portable storage* —
  preferences, PACS server profiles, PACS passwords and the Orthanc cache
  live next to the executable instead of on the host.

The profile is selected via the ``SONOFORGE_PROFILE`` environment variable.
The Presenter entry point (:mod:`echo_personal_tool.__main_presenter__`)
sets it before any other application import, and the packaging spec for
Presenter additionally excludes the heavy optional dependencies, so the
same source tree produces both products.

All consumer modules must treat the presenter profile as an *additive*
restriction: optional features degrade gracefully (buttons hidden, guarded
imports return "unavailable"), while the full profile behaves exactly as
before.  Nothing in this module imports PySide6 at import time, so it is
safe to use from early startup code paths.

Environment variables
---------------------
``SONOFORGE_PROFILE``
    ``full`` (default) or ``presenter``.
``SONOFORGE_PORTABLE``
    ``1``/``0`` — force portable storage on/off.  Default: on for the
    presenter profile, off for full.
``SONOFORGE_PORTABLE_DIR``
    Explicit directory for portable data (overrides auto-detection).
    Primarily useful for tests and development.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROFILE_ENV = "SONOFORGE_PROFILE"
PORTABLE_ENV = "SONOFORGE_PORTABLE"
PORTABLE_DIR_ENV = "SONOFORGE_PORTABLE_DIR"

PROFILE_FULL = "full"
PROFILE_PRESENTER = "presenter"

#: Directory created next to the executable/AppImage in portable mode.
PORTABLE_DIR_NAME = "SonoForgePresenter-data"

_FALLBACK_ORTHANC_RELATIVE = Path(".sonoforge") / "orthanc"


def _env_flag(name: str) -> bool | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    return raw.strip().lower() not in {"", "0", "false", "no", "off"}


def profile() -> str:
    """Return the active profile name (``full`` or ``presenter``)."""
    raw = os.environ.get(PROFILE_ENV, "").strip().lower()
    return raw or PROFILE_FULL


def is_presenter() -> bool:
    return profile() == PROFILE_PRESENTER


# ── Optional-feature probes ─────────────────────────────────────────


def has_ai_segmentation() -> bool:
    """AI (ONNX) auto-segmentation is part of the full profile only."""
    return not is_presenter()


def has_reference_ui() -> bool:
    """ASE reference viewer / constructor UI is part of the full profile only."""
    return not is_presenter()


# ── Portable storage ────────────────────────────────────────────────


def portable_enabled() -> bool:
    """Whether settings/cache should be stored next to the executable."""
    flag = _env_flag(PORTABLE_ENV)
    if flag is not None:
        return flag
    return is_presenter()


def portable_root() -> Path | None:
    """Directory that holds portable data, or None when not portable.

    Resolution order:

    1. ``SONOFORGE_PORTABLE_DIR`` (explicit override — tests, dev);
    2. ``$APPIMAGE``'s directory (AppImage runtime sets ``APPIMAGE`` to the
       .AppImage file itself — data stays on the USB stick, not in the
       transient squashfs mount);
    3. frozen executable's directory (Windows onefile: ``sys.executable``
       is the .exe on the stick, *not* the temp unpack dir);
    4. current working directory when portable mode was explicitly
       requested via ``SONOFORGE_PORTABLE=1`` in a dev/source run.
    """
    if not portable_enabled():
        return None
    explicit = os.environ.get(PORTABLE_DIR_ENV)
    if explicit:
        return Path(explicit)
    appimage = os.environ.get("APPIMAGE")
    if appimage:
        return Path(appimage).resolve().parent / PORTABLE_DIR_NAME
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / PORTABLE_DIR_NAME
    return Path.cwd() / PORTABLE_DIR_NAME


def portable_path(*parts: str) -> Path | None:
    """Path inside the portable data dir, or None when not portable."""
    root = portable_root()
    if root is None:
        return None
    return root.joinpath(*parts)


def ensure_portable_root() -> Path | None:
    """Create the portable data dir (if portable) and return it."""
    root = portable_root()
    if root is not None:
        root.mkdir(parents=True, exist_ok=True)
    return root


def settings_ini_path() -> Path | None:
    return portable_path("preferences.ini")


def servers_ini_path() -> Path | None:
    return portable_path("server.ini")


def secrets_path() -> Path | None:
    """INI holding Fernet-encrypted PACS password tokens (managed via QSettings)."""
    return portable_path("secrets.ini")


def qsettings_for(org: str, app: str):
    """QSettings backed by an INI next to the exe in portable mode.

    Falls back to the native store (Windows registry / ~/.config) exactly
    like ``QSettings(org, app)`` when portable mode is off.  Import of
    PySide6 is deferred so this module stays import-cheap.
    """
    from PySide6.QtCore import QSettings

    ini = portable_path(f"{app}.ini")
    if ini is not None:
        try:
            ini.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            # Read-only media: QSettings stays usable in-memory and reports
            # AccessError on sync — the app runs, settings are not persisted.
            pass
        return QSettings(str(ini), QSettings.Format.IniFormat)
    return QSettings(org, app)


# ── Well-known data locations ───────────────────────────────────────


def diag_log_dir() -> Path:
    """Directory for diagnostic logs (host %LOCALAPPDATA% or portable)."""
    portable = portable_path("logs")
    if portable is not None:
        return portable
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "SonoForge" / "logs"


def orthanc_cache_root() -> Path:
    """Root of the Orthanc session cache (host ~/.sonoforge or portable)."""
    portable = portable_path("cache", "orthanc")
    if portable is not None:
        return portable
    return Path.home() / _FALLBACK_ORTHANC_RELATIVE


def display_name() -> str:
    """Human-visible application name for the active profile."""
    return "SonoForge Presenter" if is_presenter() else "SonoForge"
