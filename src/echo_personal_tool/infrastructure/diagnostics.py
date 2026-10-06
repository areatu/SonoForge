"""Privacy-filtered support bundle creation.

Bundles contain only application logs and an allowlisted runtime summary.
Patient media, measurements, preferences, server settings, and caches are
never read or added to the archive.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from echo_personal_tool.infrastructure.log_sanitizer import sanitize_log_text
from echo_personal_tool.infrastructure.logging_setup import system_info_text
from echo_personal_tool.infrastructure.paths import logs_dir

_LOG = logging.getLogger(__name__)
_MAX_LOG_BYTES = 2 * 1024 * 1024
_MAX_TOTAL_LOG_BYTES = 20 * 1024 * 1024


def create_diagnostic_bundle(
    destination: Path,
    *,
    log_directory: Path | None = None,
    app=None,
) -> Path:
    """Create a ZIP containing sanitized logs and non-PHI system information.

    Only regular ``.log`` files directly inside the application log directory
    are eligible. Symlinks, arbitrary files, paths outside that directory, and
    the destination itself are excluded. Oversized logs are clipped to their
    newest portion before sanitization.
    """
    destination = Path(destination)
    source_dir = Path(log_directory) if log_directory is not None else logs_dir()
    source_root = source_dir.resolve(strict=False)
    destination.parent.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        handler.flush()

    included: list[dict[str, object]] = []
    total_bytes = 0
    with ZipFile(destination, mode="w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr("system-info.txt", system_info_text(app) + "\n")
        for path in sorted(source_dir.glob("*.log*"), key=lambda item: item.name.casefold()):
            if path.is_symlink() or not path.is_file():
                continue
            if path.resolve(strict=False).parent != source_root:
                continue
            if destination.resolve(strict=False) == path.resolve(strict=False):
                continue
            try:
                source_size = path.stat().st_size
                if source_size <= 0 or total_bytes >= _MAX_TOTAL_LOG_BYTES:
                    continue
                safe_text = sanitize_log_text(_read_log_tail(path, _MAX_LOG_BYTES))
            except OSError as exc:
                _LOG.warning("Skipping unreadable diagnostic log (%s)", type(exc).__name__)
                continue
            if not safe_text.strip():
                continue
            safe_bytes = safe_text.encode("utf-8")
            if total_bytes + len(safe_bytes) > _MAX_TOTAL_LOG_BYTES:
                safe_bytes = safe_bytes[: _MAX_TOTAL_LOG_BYTES - total_bytes]
            if not safe_bytes:
                continue
            # Do not copy source filenames: a caller or older app version may
            # have written patient identifiers into a log's filename.
            archive_name = f"logs/log-{len(included) + 1:03d}.log"
            archive.writestr(archive_name, safe_bytes)
            total_bytes += len(safe_bytes)
            included.append(
                {
                    "name": archive_name,
                    "source_bytes": source_size,
                    "included_bytes": len(safe_bytes),
                    "truncated": source_size > _MAX_LOG_BYTES or len(safe_bytes) < len(safe_text.encode("utf-8")),
                }
            )

        manifest = {
            "format": "SonoForge diagnostics",
            "schema_version": 1,
            "created_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "privacy": "No patient media, measurements, preferences, or server settings included. Log text is filtered.",
            "logs": included,
        }
        archive.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    return destination


def migrate_legacy_scan_errors(study_directory: Path, *, log_directory: Path | None = None) -> bool:
    """Move a legacy patient-folder ``scan_errors.log`` into the app log folder.

    Historical lines are filtered before they leave the selected folder. The
    source is removed only after the sanitized copy has been appended
    successfully. Returns ``True`` when a legacy file was migrated.
    """
    study_directory = Path(study_directory)
    source = study_directory / "scan_errors.log"
    destination = (Path(log_directory) if log_directory is not None else logs_dir()) / "scan_errors.log"
    if source.resolve(strict=False) == destination.resolve(strict=False):
        return False
    if source.is_symlink() or not source.is_file():
        return False

    destination.parent.mkdir(parents=True, exist_ok=True)
    raw_text = _read_log_tail(source, _MAX_LOG_BYTES)
    filtered = sanitize_log_text(raw_text)
    if source.stat().st_size > _MAX_LOG_BYTES:
        filtered = "[Earlier legacy scan diagnostics were truncated. Not all records were copied.]\n" + filtered
    with destination.open("a", encoding="utf-8") as target:
        if filtered:
            target.write(filtered.rstrip() + "\n")
    source.unlink()
    _LOG.info("Relocated a legacy scan diagnostic log into the application log folder")
    return True


def _read_log_tail(path: Path, max_bytes: int) -> str:
    """Read at most *max_bytes* from the tail, avoiding huge/PHI-heavy files."""
    with path.open("rb") as stream:
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        start = max(0, size - max_bytes)
        stream.seek(start)
        data = stream.read(max_bytes)
    if start:
        first_line_end = data.find(b"\n")
        if first_line_end >= 0:
            data = data[first_line_end + 1 :]
    return data.decode("utf-8", errors="replace")
