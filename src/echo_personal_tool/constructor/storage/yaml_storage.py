"""YAML load/save for references_structured.yaml with backup."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import yaml


class YamlStorage:
    """Read/write the structured references YAML file."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> dict[str, Any]:
        """Load YAML and return raw dict."""
        with open(self._path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data is None:
            return {"topics": []}
        return data

    def save(self, data: dict[str, Any]) -> None:
        """Write YAML with backup (.bak)."""
        self._backup()
        with open(self._path, "w", encoding="utf-8") as f:
            yaml.dump(
                data,
                f,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
                width=120,
            )

    def _backup(self) -> None:
        """Create .bak copy before overwrite."""
        if self._path.exists():
            bak = self._path.with_suffix(self._path.suffix + ".bak")
            shutil.copy2(self._path, bak)
