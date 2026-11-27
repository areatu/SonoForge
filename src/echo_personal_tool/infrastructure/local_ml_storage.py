"""Local ML workspace primitives. Never a network, repository or telemetry store."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def external_path(value: Path) -> Path:
    """Require an explicit absolute path outside every enclosing Git checkout."""
    path = value.resolve()
    if not value.is_absolute() or any((p / ".git").exists() for p in (path, *path.parents)):
        raise ValueError("external_absolute_path_required")
    return path


def atomic_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=".ml-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def settings_path() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return base / "SonoForge" / "local-ml.json"


def load_settings() -> dict[str, Any]:
    path = external_path(settings_path())
    if not path.is_file():
        return {
            "enabled": True,
            "directory": str(external_path(settings_path().parent / "measurement-training")),
            "quota_bytes": 4096 * 1024**2,
        }
    if path.stat().st_size > 8192:
        raise ValueError("invalid_ml_settings")
    data = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(data, dict)
        or type(data.get("enabled")) is not bool
        or not isinstance(data.get("directory"), str)
        or type(data.get("quota_bytes")) is not int
        or not 16 * 1024**2 <= data["quota_bytes"] <= 1024**4
    ):
        raise ValueError("invalid_ml_settings")
    return data


def save_settings(*, enabled: bool, directory: Path, quota_bytes: int) -> None:
    path = external_path(directory)
    if type(quota_bytes) is not int or not 16 * 1024**2 <= quota_bytes <= 1024**4:
        raise ValueError("invalid_quota")
    atomic_json(
        external_path(settings_path()), {"enabled": enabled, "directory": str(path), "quota_bytes": quota_bytes}
    )
