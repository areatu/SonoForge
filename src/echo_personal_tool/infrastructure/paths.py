"""Canonical application data paths and safe legacy-path migration.

The full profile stores mutable application data in the platform's per-user
application-data directory. Portable mode is resolved first and keeps all of
its existing next-to-the-executable overrides.

The legacy-path candidates in this module are a one-release compatibility
bridge. Remove them after the migration release has shipped to users.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from echo_personal_tool.infrastructure.profile import portable_enabled, portable_root

_MIGRATION_MARKER = ".path-migration-v1"


def data_dir() -> Path:
    """Return the canonical per-user data directory for the active profile."""
    portable = portable_root()
    if portable is not None:
        return portable

    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        base = Path(local_app_data) if local_app_data else None
        if base is not None and base.is_absolute():
            return base / "SonoForge"
        return Path.home() / "AppData" / "Local" / "SonoForge"

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "SonoForge"

    xdg_data_home = os.environ.get("XDG_DATA_HOME", "").strip()
    xdg_base = Path(xdg_data_home) if xdg_data_home else None
    if xdg_base is not None and xdg_base.is_absolute():
        return xdg_base / "sonoforge"
    return Path.home() / ".local" / "share" / "sonoforge"


def measurements_dir() -> Path:
    """Durable medical results; intentionally outside the disposable cache."""
    return data_dir() / "measurements"


def models_dir() -> Path:
    """Return the canonical directory for downloaded ONNX models."""
    return data_dir() / "models"


def cache_dir() -> Path:
    """Return the canonical root for application-managed caches."""
    return data_dir() / "cache"


def logs_dir() -> Path:
    """Return the canonical directory for application log files."""
    return data_dir() / "logs"


def venv_dir() -> Path:
    """Return the per-user virtual-environment directory used by launchers."""
    return data_dir() / "venv"


def fonts_cache_dir() -> Path:
    """Return the application cache directory for copied bundled fonts."""
    return cache_dir() / "fonts"


def orthanc_cache_dir() -> Path:
    """Return the Orthanc cache path, with a one-release legacy read fallback.

    The application migrates the legacy cache before creating its UI. If a
    legacy installation cannot be moved before a canonical cache root exists
    (for example, because it is read-only), continue using that existing cache
    until the compatibility bridge is removed in a later release.
    """
    canonical = cache_dir() / "orthanc"
    if portable_enabled():
        return canonical
    legacy = _legacy_orthanc_cache_dir()
    if not canonical.is_dir() and legacy.is_dir():
        return legacy
    return canonical


def models_dirs_for_read() -> tuple[Path, ...]:
    """Return model directories in priority order for the compatibility release."""
    canonical = models_dir()
    if portable_enabled():
        return (canonical,)

    legacy = _legacy_models_dir()
    if _same_path(canonical, legacy):
        return (canonical,)
    return (canonical, legacy)


def migrate_legacy_paths() -> tuple[str, ...]:
    """Move legacy models, cache, fonts, and logs into the canonical layout.

    Migration runs once per non-portable user profile. It never overwrites a
    destination entry: non-conflicting files are moved, while conflicting
    legacy entries are retained at their old path. I/O failures are reported
    and leave the migration marker unset so another launch can retry. Portable
    mode never reads or moves host-profile data.

    Returns human-readable warnings for startup logging; migration problems do
    not prevent SonoForge from starting.
    """
    if portable_enabled():
        return ()

    root = data_dir()
    marker = root / _MIGRATION_MARKER
    if marker.is_file():
        return ()

    home = Path.home()
    mappings = (
        (_legacy_models_dir(), models_dir()),
        (_legacy_orthanc_cache_dir(), cache_dir() / "orthanc"),
        (home / ".sonoforge" / "fonts", fonts_cache_dir()),
        (home / "SonoForge" / "logs", logs_dir()),
        (_legacy_local_app_data_logs(), logs_dir()),
    )

    warnings: list[str] = []
    retry_required = False
    seen: set[tuple[str, str]] = set()
    for source, destination in mappings:
        try:
            if _same_path(source, destination):
                continue
            key = (_normalized_path(source), _normalized_path(destination))
            if key in seen or not _path_exists(source):
                continue
            seen.add(key)
            warnings.extend(_move_without_overwrite(source, destination))
        except OSError as exc:
            retry_required = True
            warnings.append(
                f"Could not migrate legacy application data ({type(exc).__name__}); the old data was left in place."
            )

    for legacy_root in (home / ".sonoforge", home / "SonoForge", home / ".local" / "share" / "sonoforge"):
        try:
            if legacy_root.is_dir() and not legacy_root.is_symlink() and not any(legacy_root.iterdir()):
                legacy_root.rmdir()
        except OSError:
            # Removing an empty parent is cosmetic; the actual move result is
            # already reported above and the next launch can retry it.
            pass

    if retry_required:
        return tuple(warnings)

    try:
        root.mkdir(parents=True, exist_ok=True)
        marker.write_text("1\n", encoding="ascii")
    except OSError as exc:
        warnings.append(
            f"Could not record completion of the application-data migration "
            f"({type(exc).__name__}); it will be retried next launch."
        )
    return tuple(warnings)


def _legacy_models_dir() -> Path:
    """Models location used by older runtime_setup/ONNX builds."""
    return Path.home() / ".local" / "share" / "sonoforge" / "models"


def _legacy_orthanc_cache_dir() -> Path:
    """Orthanc cache location used before platform paths were centralized."""
    return Path.home() / ".sonoforge" / "orthanc"


def _legacy_local_app_data_logs() -> Path:
    """Log directory used by the old duplicated logging setup."""
    local_app_data = os.environ.get("LOCALAPPDATA", str(Path.home()))
    return Path(local_app_data) / "SonoForge" / "logs"


def _move_without_overwrite(source: Path, destination: Path) -> list[str]:
    """Move a file/tree without replacing any existing destination entry."""
    if not _path_exists(source) or _same_path(source, destination):
        return []

    if not _path_exists(destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        return []

    if source.is_dir() and not source.is_symlink() and destination.is_dir() and not destination.is_symlink():
        warnings: list[str] = []
        for child in sorted(source.iterdir(), key=lambda item: item.name):
            child_destination = destination / child.name
            if not _path_exists(child_destination):
                shutil.move(str(child), str(child_destination))
            elif (
                child.is_dir()
                and not child.is_symlink()
                and child_destination.is_dir()
                and not child_destination.is_symlink()
            ):
                warnings.extend(_move_without_overwrite(child, child_destination))
            else:
                warnings.append("A legacy application-data item was retained because its destination already exists.")
        if source.exists() and not any(source.iterdir()):
            source.rmdir()
        return warnings

    return ["A legacy application-data item was retained because its destination already exists."]


def _path_exists(path: Path) -> bool:
    """Include broken symlinks when deciding whether legacy data exists."""
    return path.exists() or path.is_symlink()


def _normalized_path(path: Path) -> str:
    try:
        resolved = path.resolve(strict=False)
    except OSError:
        resolved = path.absolute()
    return os.path.normcase(str(resolved))


def _same_path(first: Path, second: Path) -> bool:
    return _normalized_path(first) == _normalized_path(second)


def _main() -> int:
    """Small CLI used by the legacy launch scripts before model checks."""
    parser = argparse.ArgumentParser(description=__doc__)
    output = parser.add_mutually_exclusive_group(required=True)
    output.add_argument("--print-data-dir", action="store_true")
    output.add_argument("--print-models-dir", action="store_true")
    output.add_argument("--print-models-read-dir", action="store_true")
    output.add_argument("--migrate", action="store_true")
    args = parser.parse_args()

    if args.print_data_dir:
        print(data_dir())  # noqa: T201 - this module is the path CLI
    elif args.print_models_dir:
        print(models_dir())  # noqa: T201 - this module is the path CLI
    elif args.print_models_read_dir:
        readable = next(
            (candidate for candidate in models_dirs_for_read() if (candidate / "model_manifest.json").is_file()),
            models_dir(),
        )
        print(readable)  # noqa: T201 - this module is the path CLI
    else:
        for warning in migrate_legacy_paths():
            print(f"SonoForge path migration: {warning}", file=sys.stderr)  # noqa: T201 - this module is the path CLI
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
