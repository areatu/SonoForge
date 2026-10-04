"""Serial background persistence with explicit dirty, restore and flush boundaries.

Only detached dataclasses cross the worker boundary. UI callbacks execute on the
owning Qt thread. A failed save keeps the RAM snapshot available for retry/export.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from datetime import timezone
from time import monotonic

from PySide6.QtCore import QEventLoop, QObject, QTimer, Signal

from echo_personal_tool.application.study_measurement_session import StudyMeasurementData, contour_key
from echo_personal_tool.infrastructure.measurement_codec import (
    FORMAT,
    MAX_DOCUMENT_BYTES,
    VERSION,
    MeasurementStorageError,
    dumps,
    loads,
)
from echo_personal_tool.infrastructure.measurement_repository import MeasurementRepository
from echo_personal_tool.infrastructure.measurement_sources import describe_study

_UTC = timezone.utc  # noqa: UP017 - retain Python 3.10 compatibility

logger = logging.getLogger(__name__)


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
    completed = Signal(object, object, object)

    def __init__(self, root, store, *, enabled=False, parent=None):
        super().__init__(parent)
        self.store = store
        self.enabled = enabled
        self.repository = MeasurementRepository(root)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="measurement-io")
        self._pending = 0
        self._dirty = {}
        self._versions = {}
        self._saving = False
        self._contexts = {}  # worker-owned {uid: (full record, active source descriptors)}
        self._load_errors = {}  # worker-owned {uid: error code observed while restoring}
        self.loaded = set()
        self._studies = {}
        self._suppressed = set()
        self.sources = {}  # GUI-owned checked descriptors, for per-instance calculations
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

    def submit(self, operation, callback):
        """Public entry point; presentation code must not depend on `_submit`."""
        return self._submit(operation, callback)

    def _submit(self, operation, callback):
        self._pending += 1
        future = self._executor.submit(operation)

        def done(task):
            try:
                value, error = task.result(), None
            except MeasurementStorageError as exc:
                value, error = None, exc.code
            except Exception as exc:
                # do not log a traceback containing patient paths
                logger.warning("measurement persistence op failed: %s", type(exc).__name__)
                value, error = None, "io"
            self.completed.emit(callback, value, error)

        future.add_done_callback(done)

    def _complete(self, callback, value, error):
        self._pending -= 1
        callback(value, error)

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

    def load(self, studies, callback):
        """Called before exposing the new study set to editable UI."""
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
                    code = exc.code if isinstance(exc, MeasurementStorageError) else "source"
                    # Remember why the study has no context so a later save reports the real reason.
                    self._load_errors[uid] = code
                    results[uid] = (None, {}, code)
            return results

        def apply(results, error):
            self.loaded.clear()
            self.sources.clear()
            self._errors.clear()
            if error:
                self._errors.add("load")
                self.status.emit(error)
            else:
                for uid, (data, sources, state) in results.items():
                    self.sources[uid] = sources
                    if data is not None:
                        self.store.restore(uid, data)
                        self.loaded.add(uid)
                    if state not in ("ready", "restored", "partial"):
                        self._errors.add(uid)
                    self.status.emit(state)
                if self._errors:
                    self.status.emit("blocked")
                elif not results:
                    self.status.emit("ready")
            callback()

        self._submit(read, apply)

    def save_pending(self):
        self._timer.stop()
        self._first_dirty = None
        if not self.enabled or not self._dirty or self._saving:
            return
        self._saving = True
        batch, self._dirty = self._dirty, {}
        batch_versions = {uid: self._versions[uid] for uid in batch}
        self.status.emit("saving")

        def save():
            failures = {}
            for uid, data in batch.items():
                try:
                    if uid not in self._contexts:
                        raise MeasurementStorageError(self._load_errors.get(uid, "identity"))
                    record, sources = self._contexts[uid]
                    data = committed_data(data, record["data"] if record else None)
                    full = combine(record["data"], data, set(sources)) if record else data
                    # A summary without editable inputs may only be restored against the whole source set.
                    if record and set(record["sources"]) - set(sources):
                        full = replace(full, strain=record["data"].strain)
                    all_sources = {**(record["sources"] if record else {}), **sources}
                    result = self.repository.save(uid, full, all_sources, record["revision"] if record else 0)
                    self._contexts[uid] = (result, sources)
                except (MeasurementStorageError, OSError) as exc:
                    failures[uid] = exc.code if isinstance(exc, MeasurementStorageError) else "io"
                    if isinstance(exc, OSError) and uid in self._contexts:
                        old_record, active_sources = self._contexts[uid]
                        try:
                            observed = self.repository.load(uid)
                            old_revision = old_record["revision"] if old_record else 0
                            if (
                                observed
                                and observed["revision"] == old_revision + 1
                                and observed["data"] == full
                                and observed["sources"] == all_sources
                            ):
                                self._contexts[uid] = (observed, active_sources)
                        except (MeasurementStorageError, OSError):
                            pass
            return failures

        def applied(failures, error):
            self._saving = False
            failures = failures if error is None else dict.fromkeys(batch, error)
            for uid, data in batch.items():
                if uid in failures:
                    if self._versions.get(uid) == batch_versions[uid] and uid not in self._suppressed:
                        self._dirty.setdefault(uid, data)
                    self._errors.add(uid)
                else:
                    self._errors.discard(uid)
                    self.loaded.add(uid)
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

        self._submit(save, applied)

    def flush(self, timeout_ms=2000):
        """Keep Qt processing completion events; failed/timed-out writes block navigation."""
        if self._closed:
            return True
        if not self.enabled and not self._pending:
            return True  # disabled and idle is the default path: never stall the GUI
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
        return not self._pending and not self._dirty

    def delete_all(self, callback):
        # UI prevents edits during this operation; discard queued RAM, then delete after in-flight saves.
        self._timer.stop()
        self.enabled = False
        self.store.on_change = None
        self._dirty.clear()

        def remove():
            self.repository.delete_all()
            self._contexts.clear()
            self._load_errors.clear()

        def applied(_, error):
            self.loaded.clear()
            self.sources.clear()
            self._dirty.clear()  # an earlier failing save may have requeued data
            self.status.emit(error or "disabled")
            callback(error)

        self._submit(remove, applied)

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
        self._suppressed.update(uids)
        for uid in uids:
            self._dirty.pop(uid, None)

        def remove():
            self.repository.delete_key(key)
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
            for uid in uids:
                self._dirty.pop(uid, None)
                self.loaded.discard(uid)
            self.status.emit(error or "disabled")
            callback(error)

        self._submit(remove, applied)

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
                study_uid=uid,
                revision=1,
                saved_at=datetime.now(_UTC).isoformat(),
                sources={**(record["sources"] if record else {}), **sources},
                data=data,
            )
            self.repository.atomic_write(path, dumps(output))

        self._submit(write, lambda _, error: callback(error))

    def import_study(self, uid, path, callback):
        if not self.flush():
            callback("io")
            return

        def read():
            with path.open("rb") as file:
                record = loads(file.read(MAX_DOCUMENT_BYTES + 1))
            if record["study_uid"] != uid:
                raise MeasurementStorageError("identity")
            if uid not in self._contexts:
                if uid not in self._studies:
                    raise MeasurementStorageError("identity")
                self._contexts[uid] = (None, describe_study(self._studies[uid]))
            current, sources = self._contexts[uid]
            if any(key not in sources or sources[key] != value for key, value in record["sources"].items()):
                raise MeasurementStorageError("source")
            if self.enabled:
                record = self.repository.save(
                    uid, record["data"], record["sources"], current["revision"] if current else 0
                )
                self._contexts[uid] = (record, sources)
            return record["data"]

        def applied(data, error):
            if not error:
                self.store.restore(uid, data)
                self.loaded.add(uid)
                self.status.emit("restored")
            callback(error)

        self._submit(read, applied)

    def close(self):
        if self._closed:
            return True
        if not self.flush():
            return False
        # Mark closed before the bounded shutdown so a timeout can never leak the worker.
        self._closed = True
        try:
            future = self._executor.submit(self.repository.close)
            future.result(timeout=5)
        except Exception as exc:
            logger.warning("measurement persistence op failed: %s", type(exc).__name__)
        finally:
            self._executor.shutdown(wait=False, cancel_futures=True)
        return True
