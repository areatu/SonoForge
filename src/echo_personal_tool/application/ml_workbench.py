"""ML.6 local collection/inventory/transfer use cases; no clinical mutation.

This first workbench slice does not start training, freeze a corpus or activate
weights. A split preview is advisory and release readiness is always blocked.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import numpy as np

from echo_personal_tool.domain.services.ml_data_readiness import combine_sources, data_readiness
from echo_personal_tool.infrastructure.local_ml_storage import (
    atomic_json,
    external_path,
    load_settings,
    save_settings,
)
from echo_personal_tool.infrastructure.ml_archive_transfer import (
    archive_identity,
    export_identity,
    export_snapshot,
    import_snapshot,
    initialize_identity,
    latest_snapshots,
    verify_snapshot,
)
from echo_personal_tool.infrastructure.training_archive import SqliteMeasurementArchive


def collection_settings() -> dict[str, Any]:
    """Return a detached configuration snapshot; UI never owns a storage adapter."""
    settings = dict(load_settings())
    if "SONOFORGE_LOCAL_TRAINING_ARCHIVE" in os.environ:
        settings["enabled"] = os.environ["SONOFORGE_LOCAL_TRAINING_ARCHIVE"] == "1"
        settings["directory"] = os.environ.get("SONOFORGE_LOCAL_TRAINING_ARCHIVE_DIR", "")
    return settings


def configure_collection(*, enabled: bool, directory: Path, quota_bytes: int) -> None:
    """Persist explicit consent; collection binds this configuration at restart."""
    save_settings(enabled=enabled, directory=directory, quota_bytes=quota_bytes)


def workbench_available(profile: str) -> bool:
    import sys

    return profile == "full" and not getattr(sys, "frozen", False)


class LocalMLWorkbench:
    def __init__(self, directory: Path) -> None:
        self.directory = external_path(directory)
        self.archive = SqliteMeasurementArchive(self.directory / "measurement-training.sqlite3")

    def export_material(self, destination: Path) -> dict[str, Any]:
        return export_snapshot(self.archive, destination)

    def import_material(self, source: Path) -> Path:
        return import_snapshot(source, self.directory)

    def export_identity(self, destination: Path) -> None:
        export_identity(self.archive, destination)

    def import_identity(self, source: Path) -> None:
        initialize_identity(self.archive, source)

    def _sources(self) -> tuple[list[tuple[str, str, list[dict[str, Any]]]], dict[str, Path]]:
        sources, paths = [], {}
        if self.archive.path.exists():
            local = SqliteMeasurementArchive(self.archive.path, read_only=True)
            records = local.records(include_excluded=True)
            sources.append((archive_identity(local), "local", records))
            paths["local"] = local.path
        for package in latest_snapshots(self.directory):
            manifest = verify_snapshot(package)
            archive = SqliteMeasurementArchive(package / "archive.sqlite3", read_only=True)
            origin = manifest["origin"]
            # A returned snapshot of this archive is redundant, not a stale
            # second source. Compare durable origin IDs, never machine names.
            if self.archive.path.exists():
                with local._connection() as db:
                    local_origin = db.execute("SELECT value FROM settings WHERE key='origin'").fetchone()
                if local_origin == (origin,):
                    continue
            sources.append((manifest["namespace"], origin, archive.records(include_excluded=True)))
            paths[origin] = archive.path
        return sources, paths

    def decisions(self) -> dict[str, Any]:
        path = self.directory / "curation.json"
        if not path.exists():
            return {}
        if path.stat().st_size > 16 * 1024**2:
            raise ValueError("invalid_curation")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("invalid_curation")
        return data

    def inventory(self) -> dict[str, Any]:
        sources, _ = self._sources()
        inventory = combine_sources(sources)
        decisions = self.decisions()
        for record in inventory["records"]:
            record["curation"] = decisions.get(record["fingerprint"], {})
        # Fingerprints were calculated before UI-only curation was attached.
        inventory["report"] = data_readiness(inventory, decisions)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        inventory["disk"] = {
            "free_bytes": shutil.disk_usage(self.directory).free,
            "archive_bytes": self.archive.path.stat().st_size if self.archive.path.exists() else 0,
        }
        return inventory

    def decide(self, fingerprint: str, *, excluded: bool, reviewed: bool) -> None:
        from echo_personal_tool.infrastructure.ml_archive_transfer import HEX_ID

        if HEX_ID.fullmatch(fingerprint) is None:
            raise ValueError("invalid_fingerprint")
        decisions = self.decisions()
        decisions[fingerprint] = {"excluded": excluded, "reviewed": reviewed}
        atomic_json(self.directory / "curation.json", decisions)

    def preview(self, origin: str, frame_hash: str) -> np.ndarray:
        _, paths = self._sources()
        if origin not in paths:
            raise ValueError("unknown_origin")
        return SqliteMeasurementArchive(paths[origin], read_only=True).frame(frame_hash)

    def export_report(self, destination: Path) -> None:
        path = external_path(destination)
        if path.exists():
            raise ValueError("new_destination_required")
        # Aggregate only: no paths, source IDs, patient tokens or image pixels.
        atomic_json(path, self.inventory()["report"])
