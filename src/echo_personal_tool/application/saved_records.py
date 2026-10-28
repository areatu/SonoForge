"""Read-only summaries of the stored study records (QH-1a, 2026-10-13).

The start page and the saved-measurements manager used to invent their own view
of the disk: the window asked the RAM session store for file entries it does not
own, and the failure was swallowed into "no saved studies".  Both surfaces now
read one projection produced here, on the persistence worker, from the existing
repository:

* a record that this build cannot read is reported as its own row instead of
  hiding the readable records next to it (S-06/S-07);
* "the listing itself failed" is a distinct outcome from "nothing is stored", so
  a broken/unavailable data directory is never displayed as an empty one;
* a row carries only an opaque study key, counts, sizes and allowlisted error
  codes — never a path, a payload, a source UID or a patient identifier (S-09).

Nothing in this module mutates the store, creates the root directory or repairs
files: it is a reader, and every repair stays an explicit user action.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from echo_personal_tool.infrastructure.measurement_codec import (
    MAX_DOCUMENT_BYTES,
    SEMANTICS_VERSION,
    VERSION,
    MeasurementStorageError,
    study_key,
    loads,
)
from echo_personal_tool.infrastructure.safe_diagnostics import (
    log_boundary_failure,
    safe_failure_code,
)

logger = logging.getLogger(__name__)


def study_key_for_uid(uid: str) -> str:
    """Application-facing wrapper over the measurement codec study key.

    Presentation must not reach into ``infrastructure.measurement_codec``
    directly; this facade is the single application entry point for computing
    the opaque study key used to match stored records to open studies.
    """
    return study_key(uid)

#: The record could be parsed and validated.
STATUS_READABLE = "readable"
#: The document exists but is damaged (bad JSON, failed validation, limits).
STATUS_CORRUPT = "corrupt"
#: A future/unsupported schema or semantics version: not damaged, not readable.
STATUS_UNSUPPORTED = "unsupported"
#: The file itself could not be read (permissions, removed device, I/O error).
STATUS_UNAVAILABLE = "unavailable"

#: Allowlist of statuses the UI may render; anything else is a programming error.
STATUSES = (STATUS_READABLE, STATUS_CORRUPT, STATUS_UNSUPPORTED, STATUS_UNAVAILABLE)

#: Codec code raised for a document whose declared schema/semantics version is
#: outside the supported range.  The code alone cannot tell "written by a newer
#: build" (unsupported) from "the version field is not even an integer"
#: (corrupt), so the declared value is read back on this error path only.
_VERSION_CODE = "version"

#: Measurement families shown as counts, in display order.
_KINDS = (
    ("contour", "contours"),
    ("linear", "linear_measurements"),
    ("vessel", "vessel_measurements"),
    ("strain", "strain"),
    # QH-1d: study-scoped primary calculator inputs are visible as a count,
    # never as values/labels, on the privacy-minimised manager projection.
    ("calculator_inputs", "manual_calculator_inputs"),
)


@dataclass(frozen=True)
class SavedRecordSummary:
    """One stored record as the UI needs it: identity, contents, status."""

    key: str
    status: str
    saved_at: str = ""
    revision: int = 0
    size_bytes: int = 0
    source_count: int = 0
    measurement_count: int = 0
    doppler_count: int = 0
    #: True when the record carries height/weight; they are not measurements.
    has_metrics: bool = False
    kinds: tuple[str, ...] = ()
    #: Allowlisted codec/OS code; never a path, a message or a payload fragment.
    error: str = ""

    @property
    def readable(self) -> bool:
        return self.status == STATUS_READABLE


@dataclass(frozen=True)
class SavedRecordsListing:
    """Outcome of one listing pass: rows plus an explicit failure flag."""

    records: tuple[SavedRecordSummary, ...] = ()
    #: True when the listing itself failed — an empty store is ``failed=False``.
    failed: bool = False
    error: str = ""

    @property
    def unreadable(self) -> int:
        return sum(1 for record in self.records if not record.readable)

    @property
    def size_bytes(self) -> int:
        return sum(record.size_bytes for record in self.records)


def _doppler_count(data) -> int:
    total = 0
    for field in ("doppler_by_instance", "doppler_by_instance_frame"):
        for entry in getattr(data, field):
            dto = entry[-1]
            total += len(dto.peaks) + len(dto.intervals) + len(dto.traces)
    return total


def _contents(data) -> tuple[int, int, tuple[str, ...]]:
    """Count stored measurements without interpreting their clinical value."""
    counts = {
        "contour": len(data.contours),
        "linear": len(data.linear_measurements),
        "vessel": len(data.vessel_measurements),
        "strain": 1 if data.strain is not None else 0,
        "calculator_inputs": len(data.manual_calculator_inputs),
    }
    doppler = _doppler_count(data)
    kinds = tuple(name for name, _ in _KINDS if counts[name])
    if doppler:
        kinds += ("doppler",)
    if data.height_cm is not None or data.weight_kg is not None:
        kinds += ("metrics",)
    return sum(counts.values()) + doppler, doppler, kinds


def _declared_future_version(payload: bytes) -> bool:
    """True when the payload declares a version newer than this build.

    Only used after the codec rejected the document: a malformed or absent
    version field is damage, a newer version is a compatibility question.
    """
    try:
        document = json.loads(payload)
    except (ValueError, TypeError, RecursionError):
        return False
    if not isinstance(document, dict):
        return False
    for field, supported in (("schema_version", VERSION), ("measurement_semantics_version", SEMANTICS_VERSION)):
        value = document.get(field)
        if type(value) is int and value > supported:
            return True
    return False


def summarize_record(key: str, payload: bytes, *, size_bytes: int | None = None) -> SavedRecordSummary:
    """Summarize one stored document; never raises and never guesses contents.

    ``payload`` is the raw document (bounded by the codec).  A document the codec
    rejects becomes a ``corrupt``/``unsupported`` row with an allowlisted code, so
    the caller can keep showing every other record.
    """
    size = len(payload) if size_bytes is None else size_bytes
    try:
        record = loads(payload)
    except MeasurementStorageError as exc:
        future = exc.code == _VERSION_CODE and _declared_future_version(payload)
        status = STATUS_UNSUPPORTED if future else STATUS_CORRUPT
        code = safe_failure_code(exc.code, fallback="io")
        return SavedRecordSummary(key=key, status=status, size_bytes=size, error=code)
    except Exception:  # noqa: BLE001 - an unexpected codec failure is still not silent
        return SavedRecordSummary(key=key, status=STATUS_CORRUPT, size_bytes=size, error="invalid")
    data = record["data"]
    measurements, doppler, kinds = _contents(data)
    return SavedRecordSummary(
        key=key,
        status=STATUS_READABLE,
        saved_at=str(record["saved_at"]),
        revision=int(record["revision"]),
        size_bytes=size,
        source_count=len(record["sources"]),
        measurement_count=measurements,
        doppler_count=doppler,
        has_metrics=data.height_cm is not None or data.weight_kg is not None,
        kinds=kinds,
    )


def read_saved_records(repository, *, limit: int | None = None) -> SavedRecordsListing:
    """Walk ``repository`` and summarize every record; newest first.

    Runs on the persistence worker.  Per-record failures stay per-record rows;
    only a failure of the listing itself (the directory cannot be enumerated)
    returns ``failed=True``, which the UI must not present as an empty store.
    """
    try:
        paths = repository.entries()
    except (MeasurementStorageError, OSError) as exc:
        code = safe_failure_code(exc.code, fallback="io") if isinstance(exc, MeasurementStorageError) else "scan"
        log_boundary_failure(logger, "measurement.list", exc, code=code)
        return SavedRecordsListing(failed=True, error=code)
    records: list[SavedRecordSummary] = []
    for path in paths:
        records.append(_read_one(path))
    # Newest first; unreadable rows (no timestamp) keep a stable place at the end.
    records.sort(key=lambda record: (record.saved_at, record.key), reverse=True)
    if limit is not None:
        records = records[: max(0, limit)]
    return SavedRecordsListing(records=tuple(records))


def _read_one(path: Path) -> SavedRecordSummary:
    key = path.stem  # opaque sha256 study key written by the repository
    try:
        with path.open("rb") as file:
            size = os.fstat(file.fileno()).st_size
            payload = file.read(MAX_DOCUMENT_BYTES + 1)
    except OSError:
        return SavedRecordSummary(key=key, status=STATUS_UNAVAILABLE, error="io")
    return summarize_record(key, payload, size_bytes=size)


def default_diagnostic_bundle_path() -> Path:
    """Application-facing default path for the presenter diagnostic ZIP bundle.

    Presentation must not reach into ``infrastructure.support_report`` directly;
    this facade is the single application entry point for the default bundle
    location.
    """
    from echo_personal_tool.infrastructure.support_report import default_bundle_path

    return default_bundle_path()


def default_logs_dir() -> str:
    """Application-facing default logs directory.

    Presentation must not reach into ``infrastructure.paths`` directly;
    this facade is the single application entry point for the logs root.
    """
    from echo_personal_tool.infrastructure.paths import logs_dir

    return logs_dir()


def migrate_legacy_scan_errors(study_directory: str | Path) -> bool:
    """Application-facing legacy scan-error migration.

    Presentation must not reach into ``infrastructure.diagnostics`` directly;
    this facade is the single application entry point for the migration.
    """
    from pathlib import Path

    from echo_personal_tool.infrastructure.diagnostics import (
        migrate_legacy_scan_errors as _migrate,
    )

    return _migrate(Path(study_directory))
