"""Serial background persistence with explicit dirty, restore and flush boundaries.

Only detached dataclasses cross the worker boundary. UI callbacks execute on the
owning Qt thread. A failed save keeps the RAM snapshot available for retry/export.
"""

from __future__ import annotations

import hashlib
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import timezone
from pathlib import Path
from time import monotonic

from PySide6.QtCore import QEventLoop, QObject, QTimer, Signal

from echo_personal_tool.application.study_measurement_session import StudyMeasurementData, contour_key
from echo_personal_tool.domain.calculations.body_surface import resolve_bsa_basis
from echo_personal_tool.infrastructure.measurement_codec import (
    FORMAT,
    MAX_DOCUMENT_BYTES,
    SEMANTICS_VERSION,
    VERSION,
    MeasurementStorageError,
    dumps,
    loads,
)
from echo_personal_tool.infrastructure.measurement_remap import prepare_import
from echo_personal_tool.infrastructure.measurement_repository import MeasurementRepository
from echo_personal_tool.infrastructure.measurement_sources import describe_study
from echo_personal_tool.infrastructure.safe_diagnostics import log_boundary_failure, safe_failure_code

_UTC = timezone.utc  # noqa: UP017 - retain Python 3.10 compatibility

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SavedRecordSummary:
    """Lightweight, non-payload projection of one saved record for the StartPage.

    The page needs identity, ordering and a health status only; the full decoded
    measurement data stays in the application layer, never decoded in the GUI thread.
    """

    key: str  # opaque record identity (file hash stem), not the study uid
    study_uid: str
    saved_at: str  # ISO-8601 timestamp if present
    revision: int
    measurement_count: int
    measurement_types: tuple[str, ...]
    status: str  # "readable" | "corrupt" | "unsupported" | "unavailable"


@dataclass(frozen=True)
class SavedRecordsListing:
    """Result of a saved-record listing.

    ``list_error`` distinguishes a whole-list failure from a legitimately empty
    store so the UI never treats an error as "no saved studies" (QH-1a / §5.1).
    """

    summaries: list[SavedRecordSummary]
    list_error: str | None = None


@dataclass(frozen=True)
class ImportPreview:
    """Read-only result shown before an import can replace RAM or disk state.

    It intentionally exposes only allowlisted category/count information: no
    patient name, filesystem path, source UID, JSON payload, or measurement
    labels. ``digest`` binds the explicit Replace action to the exact checked
    bytes; a changed export is rejected rather than imported silently.
    """

    compatible: bool
    error: str = ""
    categories: tuple[str, ...] = ()
    category_counts: tuple[tuple[str, int], ...] = ()
    source_count: int = 0
    unavailable_sources: int = 0
    additional_live_sources: int = 0
    digest: str = ""
    target_digest: str = ""
    remapped_sources: int = 0


_IMPORT_CATEGORIES = (
    ("contours", "contours"),
    ("linear", "linear_measurements"),
    ("doppler", "doppler"),
    ("vessel", "vessel_measurements"),
    ("strain", "strain"),
    ("metrics", "metrics"),
    ("calculator_inputs", "manual_calculator_inputs"),
)


def _import_category_counts(data: StudyMeasurementData) -> tuple[tuple[str, int], ...]:
    """Return only small, non-clinical category counts for a replace preview."""
    counts = {
        "contours": len(data.contours),
        "linear": len(data.linear_measurements),
        "doppler": sum(
            1
            for name in ("doppler_by_instance", "doppler_by_instance_frame")
            for entry in getattr(data, name)
            if entry[-1].peaks or entry[-1].intervals or entry[-1].traces
        ),
        "vessel": len(data.vessel_measurements),
        "strain": int(data.strain is not None),
        "metrics": sum(value is not None for value in (data.height_cm, data.weight_kg)),
        "calculator_inputs": len(data.manual_calculator_inputs),
    }
    return tuple((category, counts[category]) for category, _field in _IMPORT_CATEGORIES if counts[category])


def scoped(data: StudyMeasurementData, uids: set[str]) -> StudyMeasurementData:
    """Project a full record without destroying measurements of missing sources."""
    values = {}
    for field in ("contours", "linear_measurements", "vessel_measurements"):
        values[field] = tuple(x for x in getattr(data, field) if x.sop_instance_uid in uids)
    for field in data.__dataclass_fields__:
        if "by_instance" in field or field == "simpson_area_by_frame":
            values[field] = tuple(x for x in getattr(data, field) if x[0] in uids)
    return replace(data, **values)


def combine(full, incoming, active):
    missing = scoped(full, {uid for uid in _source_uids(full) if uid not in active})
    values = {}
    for field in ("contours", "linear_measurements", "vessel_measurements"):
        values[field] = getattr(missing, field) + getattr(incoming, field)
    for field in incoming.__dataclass_fields__:
        if "by_instance" in field or field == "simpson_area_by_frame":
            values[field] = getattr(missing, field) + getattr(incoming, field)
    return replace(incoming, **values)


def _source_uids(data):
    uids = {
        x.sop_instance_uid
        for name in ("contours", "linear_measurements", "vessel_measurements")
        for x in getattr(data, name)
    }
    for name in data.__dataclass_fields__:
        if "by_instance" in name or name == "simpson_area_by_frame":
            uids.update(x[0] for x in getattr(data, name))
    return uids


def record_bsa_basis(data: StudyMeasurementData) -> StudyMeasurementData:
    """Freeze the BSA behind the derived results into the record being written.

    The stored numbers are recomputed from the record's own inputs, so the basis
    that describes them is the basis those inputs produce *now* (QH-1b.2, slice
    2). Writing it at this single point means a record on disk always agrees
    with its own inputs, and any later difference the panel/report/PDF report is
    a real difference between the record and the open study.

    A study without a BSA keeps ``None``: "no body metrics" is not the same
    claim as "normalised by some BSA", and only the second one is worth a
    warning.
    """
    basis = resolve_bsa_basis(
        height_cm=data.height_cm,
        weight_kg=data.weight_kg,
        manual_bsa_m2=data.manual_bsa_m2,
    )
    return replace(data, bsa_basis=basis if basis.value is not None else None)


def committed_data(data, previous=None):
    """AI proposals are transient; keep the last accepted contour until acceptance."""
    previous_by_key = {contour_key(c): c for c in previous.contours} if previous else {}
    contours = []
    for contour in data.contours:
        if not contour.review_pending:
            contours.append(contour)
        elif contour_key(contour) in previous_by_key:
            contours.append(previous_by_key[contour_key(contour)])
    return replace(data, contours=tuple(contours))


class MeasurementPersistence(QObject):
    status = Signal(str)
    #: Emitted on the owner thread after a full record replaces the RAM session.
    #: Consumers such as calculator input resolution must hydrate before the
    #: next calculation, not after a widget already rendered stale provenance.
    restored = Signal(str)
    completed = Signal(object, object, object)
    #: One successfully written record: (study_uid, recorded BsaBasis | None).
    #: The RAM copy adopts the basis the write froze, so the record and the open
    #: study agree on it without a reload (QH-1b.2, slice 2).
    saved = Signal(str, object)

    def __init__(self, root, store, *, enabled=False, parent=None):
        super().__init__(parent)
        self.store = store
        self.enabled = enabled
        self.repository = MeasurementRepository(root)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="measurement-io")
        self._pending = 0
        self._dirty = {}
        self._versions = {}
        # Per-study operation generations fence late save callbacks after an
        # explicit reset/delete/import replacement.  A callback belongs to the
        # snapshot/revision it captured, never whichever tab is active later.
        self._epochs = {}
        self._saving = False
        self._contexts = {}  # worker-owned {uid: (full record, active source descriptors)}
        self._load_errors = {}  # worker-owned {uid: error code observed while restoring}
        self.loaded = set()
        self._studies = {}
        self._suppressed = set()
        self.sources = {}  # GUI-owned checked descriptors, for per-instance calculations
        self.restore_conflicts = set()  # studies with records left out by load(restore=…)
        self._errors = set()
        self._first_dirty = None
        self._closed = False
        self.completed.connect(self._complete)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.save_pending)
        # The disabled path must remain cheap: the store detaches observers
        # rather than making a full detached snapshot just to throw it away.
        store.on_change = self.changed if enabled else None

    def enable(self):
        """Runtime enable (Settings OK, no restart): track committed changes now.

        Records of studies opened while disabled are read separately by the
        controller via load(restore=set()) — enable() itself never touches RAM.
        """
        if self._closed:
            return
        self.enabled = True
        self.store.on_change = self.changed
        self.status.emit("ready")

    def disable(self):
        """Runtime disable (Settings OK, no restart): stop tracking changes.

        The caller owns unsaved edits first — flush() them or discard_pending();
        disable() itself never drops or resurrects dirty data.
        """
        self.enabled = False
        self.store.on_change = None
        self._timer.stop()
        self._first_dirty = None
        self.status.emit("disabled")

    @property
    def has_pending_edits(self) -> bool:
        """True while unsaved edits or an in-flight write exist (disable asks the user)."""
        return self._saving or bool(self._dirty)

    def submit(self, operation, callback):
        """Public entry point; presentation code must not depend on `_submit`."""
        return self._submit(operation, callback)

    def list_record_summaries(self) -> SavedRecordsListing:
        """Saved-record summaries for the StartPage, served from the file repository.

        Queries the disk repository (never the RAM store) and never raises. Each
        entry is classified ``readable``/``corrupt``/``unsupported``/``unavailable``
        so one bad neighbour never hides the rest, and a whole-list failure is
        reported through ``list_error`` rather than as an empty store (QH-1a / §5.1).
        """
        if not self.enabled:
            return SavedRecordsListing(summaries=[])
        try:
            paths = self.repository.entries()
        except (MeasurementStorageError, OSError) as exc:
            code = safe_failure_code(getattr(exc, "code", "io"), fallback="io")
            log_boundary_failure(logger, "measurement.list", exc, code=code)
            return SavedRecordsListing(summaries=[], list_error=code)
        summaries = [summary for path in paths if (summary := self._summarize_entry(path)) is not None]
        summaries.sort(key=lambda summary: summary.saved_at, reverse=True)
        return SavedRecordsListing(summaries=summaries)

    def _summarize_entry(self, path: Path) -> SavedRecordSummary | None:
        key = path.stem
        try:
            with path.open("rb") as file:
                record = loads(file.read(MAX_DOCUMENT_BYTES + 1))
        except MeasurementStorageError as exc:
            status = "unsupported" if exc.code == "version" else "corrupt"
            return SavedRecordSummary(
                key=key,
                study_uid="",
                saved_at="",
                revision=0,
                measurement_count=0,
                measurement_types=(),
                status=status,
            )
        except OSError:
            return SavedRecordSummary(
                key=key,
                study_uid="",
                saved_at="",
                revision=0,
                measurement_count=0,
                measurement_types=(),
                status="unavailable",
            )
        sources = record.get("sources") or {}
        return SavedRecordSummary(
            key=key,
            study_uid=str(record.get("study_uid", "")),
            saved_at=str(record.get("saved_at", "")),
            revision=int(record.get("revision", 0)),
            measurement_count=len(sources),
            measurement_types=tuple(sorted(sources.keys())),
            status="readable",
        )

    def _submit(self, operation, callback, *, context="measurement.task"):
        self._pending += 1
        future = self._executor.submit(operation)

        def done(task):
            try:
                value, error = task.result(), None
            except MeasurementStorageError as exc:
                code = safe_failure_code(exc.code, fallback="io")
                log_boundary_failure(logger, context, exc, code=code)
                value, error = None, code
            except Exception as exc:
                log_boundary_failure(logger, context, exc, code="io")
                value, error = None, "io"
            self.completed.emit(callback, value, error)

        future.add_done_callback(done)

    def _complete(self, callback, value, error):
        self._pending -= 1
        callback(value, error)

    def barrier(self, *uids: str, discard_pending: bool = False) -> None:
        """Fence callbacks created before a destructive/replacement operation.

        The caller performs the synchronous RAM mutation immediately after this
        method.  Any earlier asynchronous save may still finish on the serial
        worker, but its acknowledgement cannot requeue stale bytes or alter the
        context/status of the newer operation.
        """
        for uid in uids:
            self._epochs[uid] = self._epochs.get(uid, 0) + 1
            if discard_pending:
                self._dirty.pop(uid, None)
        self._timer.stop()

    def changed(self, uid, data):
        if not self.enabled or self._closed or uid in self._suppressed:
            return
        self._versions[uid] = self._versions.get(uid, 0) + 1
        self._dirty[uid] = deepcopy(data)
        self._first_dirty = self._first_dirty or monotonic()
        self.status.emit("dirty")
        if monotonic() - self._first_dirty >= 5:
            self.save_pending()
        else:
            self._timer.start(1000)

    def list_saved_records(self, callback, *, limit=None):
        """Summaries of the stored records, read on the serial worker (QH-1a).

        Public read-only entry point: presentation code must ask for the disk
        contents here instead of probing ``repository``/``store`` itself.  The
        worker keeps the single-writer ordering, the repository stays the only
        file-system authority, and ``callback(listing)`` runs on the owning
        thread with a :class:`SavedRecordsListing`.  An empty listing means "no
        records"; a failed listing means "could not read" — the caller must not
        show both as «нет сохранённых исследований» (S-07).
        """
        from echo_personal_tool.application.saved_records import SavedRecordsListing, read_saved_records

        if self._closed:
            callback(SavedRecordsListing(failed=True, error="io"))
            return

        def read():
            return read_saved_records(self.repository, limit=limit)

        def done(listing, error):
            callback(SavedRecordsListing(failed=True, error=error) if error else listing)

        self.submit(read, done)

    def load(self, studies, callback, restore=None):
        """Called before exposing the new study set to editable UI.

        ``restore=None`` (open path) applies every study that has a record to the
        RAM store. An explicit set restores only those uids — used when autosave
        is enabled at runtime while studies are already open: their saved records
        are read into the persistence contexts (required for saves) without
        touching the live session; uids with records left out land in
        ``restore_conflicts`` for the caller's RAM-vs-disk resolution.
        """
        # One detached copy serves both the RAM view and the worker read: both only read it.
        snapshot = deepcopy(studies)
        self._studies = {study.study_uid: study for study in snapshot}
        self._suppressed.clear()
        if not self.enabled:
            callback()
            return
        self.status.emit("loading")

        def read():
            self._contexts.clear()
            self._load_errors.clear()
            results = {}
            for study in snapshot:
                uid = study.study_uid
                try:
                    sources = describe_study(study)
                    record = self.repository.load(uid)
                    if record and any(
                        key in record["sources"] and record["sources"][key] != value for key, value in sources.items()
                    ):
                        raise MeasurementStorageError("source")
                    self._contexts[uid] = (record, sources)
                    if record:
                        active = set(sources) & set(record["sources"])
                        data = scoped(record["data"], active)
                        partial = bool(set(record["sources"]) - set(sources))
                        if partial:
                            data = replace(data, strain=None)
                        results[uid] = (data, sources, "partial" if partial else "restored")
                    else:
                        results[uid] = (None, sources, "ready")
                except (MeasurementStorageError, OSError, ValueError) as exc:
                    # I/O/unavailable source access is distinct from a checked
                    # descriptor mismatch; neither is silently restored.
                    raw_code = (
                        exc.code
                        if isinstance(exc, MeasurementStorageError)
                        else ("io" if isinstance(exc, OSError) else "source")
                    )
                    code = safe_failure_code(raw_code, fallback="io")
                    log_boundary_failure(logger, "measurement.load", exc, code=code)
                    # Remember why the study has no context so a later save reports the real reason.
                    self._load_errors[uid] = code
                    results[uid] = (None, {}, code)
            return results

        def apply(results, error):
            self.loaded.clear()
            self.sources.clear()
            self._errors.clear()
            self.restore_conflicts = set()
            if error:
                self._errors.add("load")
                self.status.emit(error)
            else:
                for uid, (data, sources, state) in results.items():
                    self.sources[uid] = sources
                    if data is not None:
                        if restore is None or uid in restore:
                            self.store.restore(uid, data)
                            self.restored.emit(uid)
                            self.loaded.add(uid)
                        else:
                            # A saved record exists but the live session owns the
                            # study for now; the caller decides disk vs RAM.
                            self.restore_conflicts.add(uid)
                            continue
                    if state not in ("ready", "restored", "partial"):
                        self._errors.add(uid)
                    self.status.emit(state)
                if self._errors:
                    self.status.emit("blocked")
                elif not results:
                    self.status.emit("ready")
            callback()

        self._submit(read, apply, context="measurement.load")

    def adopt_conflicts(self):
        """Resolution «keep the live session»: RAM is authoritative, the saved
        record is rewritten by the next save. Marks the studies as loaded so
        embedded DICOM annotations are not re-imported next to the record."""
        self.loaded.update(self.restore_conflicts)
        self.restore_conflicts.clear()
        self.status.emit("dirty" if self._dirty else ("saving" if self._saving else "ready"))

    def save_pending(self):
        self._timer.stop()
        self._first_dirty = None
        if not self.enabled or not self._dirty or self._saving:
            return
        self._saving = True
        batch, self._dirty = self._dirty, {}
        batch_versions = {uid: self._versions[uid] for uid in batch}
        batch_epochs = {uid: self._epochs.get(uid, 0) for uid in batch}
        self.status.emit("saving")

        def save():
            failures = {}
            written = {}
            for uid, data in batch.items():
                try:
                    if uid not in self._contexts:
                        raise MeasurementStorageError(self._load_errors.get(uid, "identity"))
                    record, sources = self._contexts[uid]
                    data = committed_data(data, record["data"] if record else None)
                    full = combine(record["data"], data, set(sources)) if record else data
                    full = record_bsa_basis(full)
                    # A summary without editable inputs may only be restored against the whole source set.
                    if record and set(record["sources"]) - set(sources):
                        full = replace(full, strain=record["data"].strain)
                    all_sources = {**(record["sources"] if record else {}), **sources}
                    result = self.repository.save(uid, full, all_sources, record["revision"] if record else 0)
                    self._contexts[uid] = (result, sources)
                    written[uid] = full.bsa_basis
                except (MeasurementStorageError, OSError) as exc:
                    raw_code = exc.code if isinstance(exc, MeasurementStorageError) else "io"
                    failures[uid] = safe_failure_code(raw_code, fallback="io")
                    log_boundary_failure(logger, "measurement.save", exc, code=failures[uid])
                    if isinstance(exc, OSError) and uid in self._contexts:
                        old_record, active_sources = self._contexts[uid]
                        self._reconcile_write(uid, old_record, full, all_sources, active_sources)
            return failures, written

        def applied(result, error):
            self._saving = False
            if error is None:
                failures, written = result
            else:
                failures, written = dict.fromkeys(batch, error), {}
            for uid, data in batch.items():
                # A reset/delete/import barrier owns the newer state.  Do not
                # requeue this old snapshot after a late worker callback.
                if self._epochs.get(uid, 0) != batch_epochs[uid]:
                    continue
                if uid in failures:
                    if self._versions.get(uid) == batch_versions[uid] and uid not in self._suppressed:
                        self._dirty.setdefault(uid, data)
                    self._errors.add(uid)
                else:
                    self._errors.discard(uid)
                    self.loaded.add(uid)
                    if uid in written:
                        self.saved.emit(uid, written[uid])
                    self._load_errors.pop(uid, None)
            newer = any(self._versions.get(uid, 0) > batch_versions.get(uid, -1) for uid in self._dirty)
            if newer and self.enabled:
                self.save_pending()  # coalesce edits that arrived during the single in-flight write
            self.status.emit(
                next(iter(failures.values()))
                if failures
                else (
                    "blocked"
                    if self._errors
                    else "saving"
                    if self._saving
                    else "dirty"
                    if self._dirty
                    else "saved_drafts"
                    if any(c.review_pending for d in batch.values() for c in d.contours)
                    else "saved"
                )
            )

        self._submit(save, applied, context="measurement.save")

    def _reconcile_write(self, uid, previous, data, all_sources, active_sources):
        """Worker-only: visible replace is not durable success; only advance retry CAS.

        Never absorb an unrelated revision or acknowledge the failed operation.
        RAM/dirty/error ownership remains with the caller.
        """
        try:
            observed = self.repository.load(uid)
            old_revision = previous["revision"] if previous else 0
            if (
                observed
                and observed["revision"] == old_revision + 1
                and observed["data"] == data
                and observed["sources"] == all_sources
            ):
                self._contexts[uid] = (observed, active_sources)
        except (MeasurementStorageError, OSError) as exc:
            log_boundary_failure(logger, "measurement.reconcile", exc, code="io", level=logging.DEBUG)

    def _reconcile_deleted(self, uids):
        """A failed directory sync may follow a successful unlink (or partial delete).

        Keep RAM for retry; only records now absent may reset their expected
        revision. Existing/conflicting/corrupt records are never overwritten.
        """
        for uid in uids:
            if uid not in self._contexts:
                continue
            try:
                if self.repository.load(uid) is None:
                    self._contexts[uid] = (None, self._contexts[uid][1])
            except (MeasurementStorageError, OSError) as exc:
                log_boundary_failure(logger, "measurement.reconcile", exc, code="io", level=logging.DEBUG)

    def flush(self, timeout_ms=2000):
        """Keep Qt processing completion events; failed/timed-out writes block navigation."""
        if self._closed:
            return True
        if not self.enabled and not self._pending:
            return True  # disabled and idle is the default path: never stall the GUI
        for _ in range(2):
            self.save_pending()
            if self._pending:
                loop = QEventLoop()
                timer = QTimer()
                timer.setInterval(10)
                timer.timeout.connect(lambda: loop.quit() if not self._pending else None)
                deadline = QTimer()
                deadline.setSingleShot(True)
                deadline.timeout.connect(loop.quit)
                timer.start()
                deadline.start(timeout_ms)
                loop.exec(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
                timer.stop()
                deadline.stop()
            if not self._dirty or not self.enabled:
                break
            # A destructive op that failed while draining (delete_all restores
            # the dirty snapshots on error) re-dirties the store after the
            # first save_pending() no-oped on disabled state: retry once so the
            # restored data is written instead of reported unsaved.
        return not self._pending and not self._dirty

    def delete_all(self, callback):
        # UI prevents edits during this operation; discard queued RAM, then delete after in-flight saves.
        affected = set(self._studies) | set(self._contexts) | set(self._dirty) | set(self._versions)
        snapshots = {uid: self.store.snapshot(uid) for uid in affected}
        was_enabled = self.enabled
        self.barrier(*affected, discard_pending=True)
        self.enabled = False
        self.store.on_change = None
        self._dirty.clear()

        def remove():
            try:
                self.repository.delete_all()
            except OSError:
                self._reconcile_deleted(tuple(self._contexts))
                raise
            self._contexts.clear()
            self._load_errors.clear()

        def applied(_, error):
            if error:
                # The records were not confirmed deleted. Restore the previous
                # autosave policy and dirty RAM snapshots so retry/export remain
                # possible; do not claim the destructive operation succeeded.
                self.enabled = was_enabled
                self.store.on_change = self.changed if was_enabled else None
                if was_enabled:
                    for uid, snapshot in snapshots.items():
                        self.changed(uid, snapshot)
            else:
                self.loaded.clear()
                self.sources.clear()
                self._dirty.clear()  # an earlier failing save may have requeued data
            self.status.emit(error or "disabled")
            callback(error)

        self._submit(remove, applied, context="measurement.delete_all")

    def discard_pending(self):
        """Explicit user decision only, and never while a write is in flight."""
        if self._pending:
            return False
        self.enabled = False
        self.store.on_change = None
        self._timer.stop()
        self._dirty.clear()
        self.status.emit("disabled")
        return True

    def delete_record(self, key, callback):
        from echo_personal_tool.infrastructure.measurement_codec import study_key

        uids = set()
        for uid in self.sources:
            try:
                if study_key(uid) == key:
                    uids.add(uid)
            except MeasurementStorageError:
                continue
        self.barrier(*uids, discard_pending=True)
        self._suppressed.update(uids)
        for uid in uids:
            self._dirty.pop(uid, None)

        def remove():
            try:
                self.repository.delete_key(key)
            except OSError:
                self._reconcile_deleted(uids)
                raise
            for uid in list(self._contexts):
                if study_key(uid) == key:
                    self._contexts.pop(uid)
            for uid in list(self._load_errors):
                try:
                    if study_key(uid) == key:
                        self._load_errors.pop(uid)
                except MeasurementStorageError:
                    continue

        def applied(_, error):
            if error:
                # A failed delete must not leave a permanent autosave mute or
                # drop editable RAM.  Requeue the current snapshot for retry;
                # the explicit error still reaches the UI (never false success).
                self._suppressed.difference_update(uids)
                for uid in uids:
                    self.changed(uid, self.store.snapshot(uid))
            else:
                for uid in uids:
                    self._dirty.pop(uid, None)
                    self.loaded.discard(uid)
            self.status.emit(error or "disabled")
            callback(error)

        self._submit(remove, applied, context="measurement.delete")

    def export_study(self, uid, path, callback):
        snapshot = self.store.snapshot(uid)

        def write():
            from datetime import datetime

            if path.resolve().is_relative_to(self.repository.root.resolve()):
                raise MeasurementStorageError("unsafe_path")
            if uid not in self._contexts:
                if uid not in self._studies:
                    raise MeasurementStorageError("source")
                self._contexts[uid] = (None, describe_study(self._studies[uid]))
            record, sources = self._contexts[uid]
            snapshot_data = committed_data(snapshot, record["data"] if record else None)
            data = combine(record["data"], snapshot_data, set(sources)) if record else snapshot_data
            output = dict(
                format=FORMAT,
                schema_version=VERSION,
                measurement_semantics_version=SEMANTICS_VERSION,
                study_uid=uid,
                revision=1,
                saved_at=datetime.now(_UTC).isoformat(),
                sources={**(record["sources"] if record else {}), **sources},
                data=data,
            )
            self.repository.atomic_write(path, dumps(output))

        self._submit(write, lambda _, error: callback(error), context="measurement.export")

    @staticmethod
    def _import_target_digest(uid: str, sources: dict) -> str:
        return hashlib.sha256(json.dumps([uid, sources], sort_keys=True).encode()).hexdigest()

    def _checked_import_sources(self, uid: str) -> dict:
        # Rehash at preview AND confirmation, not the cached load-time descriptors.
        if uid not in self._studies:
            raise MeasurementStorageError("identity")
        return describe_study(self._studies[uid])

    def _preview_import_record(self, uid: str, path: Path, sources: dict) -> ImportPreview:
        with path.open("rb") as file:
            payload = file.read(MAX_DOCUMENT_BYTES + 1)
        record = loads(payload)
        category_counts = _import_category_counts(record["data"])
        categories = tuple(category for category, _count in category_counts)
        try:
            prepared, remapped = prepare_import(record, self._studies[uid], sources)
            error = ""
            unavailable = 0
        except MeasurementStorageError as exc:
            prepared, remapped = record, 0
            error = exc.code
            unavailable = sum(sources.get(k) != v for k, v in record["sources"].items())
        return ImportPreview(
            compatible=not error,
            error=error,
            categories=categories or ("empty",),
            category_counts=category_counts or (("empty", 0),),
            source_count=len(record["sources"]),
            unavailable_sources=unavailable,
            additional_live_sources=len(set(sources) - set(prepared["sources"])),
            digest=hashlib.sha256(payload).hexdigest(),
            target_digest=self._import_target_digest(uid, sources),
            remapped_sources=remapped,
        )

    def preview_import(self, uid: str, path: Path, callback) -> None:
        """Produce an import preview before Replace can affect RAM or disk.

        A malformed, foreign or incompatible export is a failed preview, not a
        confirmation dialog that happens to fail after the user selected
        Replace.  The callback receives one typed projection on the GUI thread.
        """

        def read() -> ImportPreview:
            sources = self._checked_import_sources(uid)
            return self._preview_import_record(uid, Path(path), sources)

        def applied(preview, error):
            if error:
                callback(ImportPreview(compatible=False, error=safe_failure_code(error, fallback="io")))
            else:
                callback(preview)

        self._submit(read, applied, context="measurement.import_preview")

    def import_study(self, uid, path, callback, *, preview: ImportPreview | None):
        """Replace one study from a previously previewed export; never merge.

        A preview is mandatory: it is the explicit user-review boundary before
        RAM/disk mutation. Its digest is checked again inside the worker so
        replacing the export between preview and confirmation cannot import
        unchecked bytes.
        """
        if preview is None:
            callback("invalid")
            return
        if not preview.compatible:
            callback(safe_failure_code(preview.error, fallback="invalid"))
            return
        if not self.flush():
            callback("blocked")
            return
        self.barrier(uid)
        import_epoch = self._epochs.get(uid, 0)

        def read():
            sources = self._checked_import_sources(uid)
            if self._import_target_digest(uid, sources) != preview.target_digest:
                raise MeasurementStorageError("source")
            current = self._contexts[uid][0] if uid in self._contexts else None
            with Path(path).open("rb") as file:
                payload = file.read(MAX_DOCUMENT_BYTES + 1)
            if hashlib.sha256(payload).hexdigest() != preview.digest:
                raise MeasurementStorageError("conflict")
            record, remapped = prepare_import(loads(payload), self._studies[uid], sources)
            if remapped != preview.remapped_sources:
                raise MeasurementStorageError("conflict")
            # Replacement is deliberately a full imported record.  In
            # particular, an empty category is an explicit deletion, not a
            # merge with RAM or the old repository record.
            if self.enabled:
                try:
                    record = self.repository.save(
                        uid, record["data"], record["sources"], current["revision"] if current else 0
                    )
                except OSError:
                    self._reconcile_write(uid, current, record["data"], record["sources"], sources)
                    raise
            self._contexts[uid] = (record, sources)
            return record["data"], sources

        def applied(result, error):
            if not error and self._epochs.get(uid, 0) == import_epoch:
                data, sources = result
                self.sources[uid] = sources
                self.store.restore(uid, data)
                self.restored.emit(uid)
                self.loaded.add(uid)
                self._suppressed.discard(uid)
                self._errors.discard(uid)
                self.status.emit("restored")
            elif not error:
                # A later reset/delete/import owns RAM.  Do not tell the caller
                # the older import succeeded against the active study state.
                error = "conflict"
            callback(safe_failure_code(error, fallback="io") if error else None)

        self._submit(read, applied, context="measurement.import")

    def close(self):
        if self._closed:
            return True
        if not self.flush():
            return False
        # Mark closed before the bounded shutdown so a timeout can never leak the worker.
        self._closed = True
        closed = True
        try:
            future = self._executor.submit(self.repository.close)
            future.result(timeout=5)
        except Exception as exc:
            # Close failure is a distinct shutdown outcome, not a successful
            # flush acknowledgement.  The executor still stops in finally.
            closed = False
            log_boundary_failure(logger, "measurement.close", exc, code="io")
        finally:
            self._executor.shutdown(wait=False, cancel_futures=True)
        return closed
