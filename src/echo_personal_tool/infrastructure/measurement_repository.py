"""Atomic per-study storage, independent of Qt and the disposable DICOM cache."""

from __future__ import annotations

import errno
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Any

from echo_personal_tool.infrastructure.measurement_codec import (
    FORMAT,
    MAX_DOCUMENT_BYTES,
    SEMANTICS_VERSION,
    VERSION,
    MeasurementStorageError,
    dumps,
    loads,
    study_key,
)
from echo_personal_tool.infrastructure.measurements_encryption import (
    MeasurementsCipher,
    is_encrypted_envelope,
)

_UTC = timezone.utc  # noqa: UP017 - datetime.UTC migration deferred (ruff target py310)


class MeasurementRepository:
    def __init__(
        self,
        root: Path,
        max_bytes: int = 1024**3,
        *,
        cipher: MeasurementsCipher | None = None,
    ):
        self.root = Path(root)
        self.max_bytes = max_bytes
        self._cipher = cipher
        self._lock_file: IO[bytes] | None = None

    def _safe(self, path: Path) -> Path:
        # Never follow record/root links, including Windows junctions/reparse points.
        for item in (self.root, path):
            if item.is_symlink() or (item.exists() and getattr(item.lstat(), "st_file_attributes", 0) & 0x400):
                raise MeasurementStorageError("unsafe_path")
        return path

    def _path(self, uid: str) -> Path:
        return self._safe(self.root / (study_key(uid) + ".json"))

    def acquire(self) -> None:
        if self._lock_file is not None:
            return
        self._safe(self.root)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = self._safe(self.root / ".writer.lock")
        file = open(path, "a+b")
        try:
            if sys.platform == "win32":
                # `sys.platform` rather than `os.name`: mypy narrows platform
                # blocks, so the Windows-only msvcrt surface is checked against
                # Windows stubs instead of being invisible (issue 325).
                import msvcrt

                file.seek(0, 2)
                if file.tell() == 0:
                    file.write(b"0")
                    file.flush()
                file.seek(0)
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            file.close()
            raise MeasurementStorageError("busy") from exc
        self._lock_file = file
        # Incomplete atomic writes are never used as recovery records.
        for temp in self.root.glob(".pending-*.tmp"):
            self._safe(temp).unlink(missing_ok=True)

    def close(self) -> None:
        if self._lock_file is not None:
            self._lock_file.close()  # OS releases advisory lock on close/process death.
            self._lock_file = None

    def load(self, uid: str) -> dict | None:
        path = self._path(uid)
        try:
            with path.open("rb") as file:
                raw = file.read(MAX_DOCUMENT_BYTES + 1)
        except FileNotFoundError:
            return None
        if is_encrypted_envelope(raw):
            if self._cipher is None:
                raise MeasurementStorageError("encrypted_unavailable")
            raw = self._cipher.decrypt(raw, aad=study_key(uid))
        record = loads(raw)
        if record["study_uid"] != uid:
            raise MeasurementStorageError("identity")
        return record

    def save(
        self,
        uid: str,
        data: object,
        sources: dict[str, Any],
        expected_revision: int,
        *,
        author_id: str = "",
        signatures: list[dict[str, Any]] | None = None,
        addenda: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        self.acquire()
        path = self._path(uid)
        previous = self.load(uid)  # corrupt/future records block writes, never auto-replaced
        revision = previous["revision"] if previous else 0
        if revision != expected_revision:
            raise MeasurementStorageError("conflict")
        previous_signatures = list(previous.get("signatures", [])) if previous else []
        previous_addenda = list(previous.get("addenda", [])) if previous else []
        previous_lifecycle = str(previous.get("lifecycle", "")) if previous else ""
        lifecycle, signatures, addenda = self._apply_signature_guard(
            previous_lifecycle,
            previous_signatures,
            previous_addenda,
            signatures,
            addenda,
        )
        stored: dict[str, Any] = dict(
            format=FORMAT,
            schema_version=VERSION,
            measurement_semantics_version=SEMANTICS_VERSION,
            study_uid=uid,
            revision=revision + 1,
            saved_at=datetime.now(_UTC).isoformat(),
            sources=sources,
            data=data,
        )
        previous_creator = str(previous.get("created_by", "")) if previous else ""
        previous_updater = str(previous.get("updated_by", "")) if previous else ""
        creator = previous_creator or author_id
        updater = author_id or previous_updater
        if creator:
            stored["created_by"] = creator
        if updater:
            stored["updated_by"] = updater
        if signatures:
            stored["signatures"] = [dict(item) for item in signatures]
        if addenda:
            stored["addenda"] = [dict(item) for item in addenda]
        if signatures or addenda:
            stored["lifecycle"] = lifecycle
        payload = dumps(stored)
        if self._cipher is not None:
            payload = self._cipher.encrypt(payload, aad=study_key(uid))
        old_size = path.stat().st_size if path.exists() else 0
        if self.size_bytes() - old_size + len(payload) > self.max_bytes:
            raise MeasurementStorageError("quota")
        self.atomic_write(path, payload)
        return stored

    def migrate_encryption(
        self,
        target: MeasurementsCipher | None,
        *,
        read_cipher: MeasurementsCipher | None = None,
    ) -> tuple[int, int]:
        """Rewrite every record to (or from) the at-rest envelope in place.

        Phase one verifies every record is readable — a corrupt or
        key-mismatched record aborts the migration before anything is
        written, so a partially converted store cannot hide a failure.
        Phase two rewrites each record with :meth:`atomic_write`; record
        content, revision and signature history are preserved byte-for-byte,
        only the envelope changes.  Returns ``(converted, already_current)``.

        ``target=None`` decrypts back to plaintext (the disable path) and
        needs *read_cipher* whenever this repository itself holds no cipher.
        """
        reader = read_cipher if read_cipher is not None else self._cipher
        self.acquire()
        records: dict[Path, tuple[bytes, bytes]] = {}
        for path in self.entries():
            with path.open("rb") as file:
                raw = file.read(MAX_DOCUMENT_BYTES + 1)
            if is_encrypted_envelope(raw):
                if reader is None:
                    raise MeasurementStorageError("encrypted_unavailable")
                # Validate before writing anything: a record that cannot be
                # opened must abort the migration, not be re-sealed blindly.
                records[path] = (raw, reader.decrypt(raw, aad=path.stem))
            else:
                loads(raw)  # an unparsable plaintext record aborts the migration
                records[path] = (raw, raw)
        converted = 0
        already = 0
        for path, (raw, plaintext) in records.items():
            if target is None:
                if not is_encrypted_envelope(raw):
                    already += 1
                    continue
                payload = plaintext
            else:
                if is_encrypted_envelope(raw) and reader is not None and reader.key_id == target.key_id:
                    already += 1
                    continue
                payload = target.encrypt(plaintext, aad=path.stem)
            self.atomic_write(path, payload)
            converted += 1
        return converted, already

    @staticmethod
    def _apply_signature_guard(
        previous_lifecycle: str,
        previous_signatures: list[dict[str, Any]],
        previous_addenda: list[dict[str, Any]],
        signatures: list[dict[str, Any]] | None,
        addenda: list[dict[str, Any]] | None,
    ) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
        """Enforce the ``draft → signed → amended`` lifecycle (#624).

        A signed or amended revision is immutable: a plain save (neither
        *signatures* nor *addenda* given) is rejected with ``signed_locked``
        instead of silently overwriting it.  Explicit signature/addendum
        updates must be append-only — the previous history has to be a
        verbatim prefix of the new one, so no signed revision can be dropped
        or rewritten.  Returns ``(lifecycle, signatures, addenda)`` for the
        new record.
        """
        from echo_personal_tool.domain.exceptions import ReportSignatureError
        from echo_personal_tool.domain.models.report_signature import (
            lifecycle_for_history,
            validate_addendum_history,
            validate_receipt_history,
        )

        try:
            if previous_lifecycle in ("signed", "amended"):
                if signatures is None and addenda is None:
                    raise MeasurementStorageError("signed_locked")
                if signatures is not None and [dict(i) for i in signatures][: len(previous_signatures)] != [
                    dict(i) for i in previous_signatures
                ]:
                    raise MeasurementStorageError("signed_locked")
                if addenda is not None and [dict(i) for i in addenda][: len(previous_addenda)] != [
                    dict(i) for i in previous_addenda
                ]:
                    raise MeasurementStorageError("signed_locked")
            new_signatures = list(signatures) if signatures is not None else list(previous_signatures)
            new_addenda = list(addenda) if addenda is not None else list(previous_addenda)
            receipts = validate_receipt_history(new_signatures)
            parsed_addenda = validate_addendum_history(new_addenda)
            lifecycle = lifecycle_for_history(signatures=receipts, addenda=parsed_addenda).value
        except ReportSignatureError as exc:
            raise MeasurementStorageError("invalid") from exc
        return lifecycle, new_signatures, new_addenda

    def append_signature(
        self,
        uid: str,
        receipt: dict[str, Any],
        *,
        author_id: str = "",
    ) -> dict[str, Any]:
        """Attach one validated receipt to the study's signature history (#624)."""
        from echo_personal_tool.domain.exceptions import ReportSignatureError
        from echo_personal_tool.domain.models.report_signature import SignatureReceipt

        try:
            parsed = SignatureReceipt.from_dict(receipt).to_dict()
        except ReportSignatureError as exc:
            raise MeasurementStorageError("invalid") from exc
        self.acquire()
        previous = self.load(uid)
        if previous is None:
            raise MeasurementStorageError("not_found")
        signatures = list(previous.get("signatures", []))
        if any(str(item.get("document_sha256", "")) == parsed["document_sha256"] for item in signatures):
            raise MeasurementStorageError("signed_locked")
        signatures.append(parsed)
        return self.save(
            uid,
            previous["data"],
            previous["sources"],
            previous["revision"],
            author_id=author_id,
            signatures=signatures,
            addenda=list(previous.get("addenda", [])),
        )

    def append_addendum(
        self,
        uid: str,
        addendum: dict[str, Any],
        *,
        author_id: str = "",
    ) -> dict[str, Any]:
        """Append an explicit addendum to a signed study, preserving signatures (#624)."""
        from echo_personal_tool.domain.exceptions import ReportSignatureError
        from echo_personal_tool.domain.models.report_signature import ReportAddendum

        try:
            parsed = ReportAddendum.from_dict(addendum).to_dict()
        except ReportSignatureError as exc:
            raise MeasurementStorageError("invalid") from exc
        self.acquire()
        previous = self.load(uid)
        if previous is None:
            raise MeasurementStorageError("not_found")
        addenda = list(previous.get("addenda", []))
        if any(str(item.get("addendum_id", "")) == parsed["addendum_id"] for item in addenda):
            raise MeasurementStorageError("signed_locked")
        addenda.append(parsed)
        return self.save(
            uid,
            previous["data"],
            previous["sources"],
            previous["revision"],
            author_id=author_id,
            signatures=list(previous.get("signatures", [])),
            addenda=addenda,
        )

    @staticmethod
    def atomic_write(path: Path, payload: bytes) -> None:
        if path.is_symlink():
            raise MeasurementStorageError("unsafe_path")
        # One attempt with a uuid name, never tempfile.mkstemp(): on Windows a
        # directory denied by ACL makes mkstemp spin through TMP_MAX retries —
        # its PermissionError fallback trusts os.access(W_OK), which cannot see
        # deny ACEs — stalling the writer for minutes instead of failing fast.
        temp: Path | None = None
        fd = -1
        for _ in range(3):
            candidate = path.parent / f".pending-{uuid.uuid4().hex}.tmp"
            try:
                fd = os.open(candidate, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                continue
            temp = candidate
            break
        if temp is None:
            raise FileExistsError(errno.EEXIST, "No usable temporary file name found")
        try:
            with os.fdopen(fd, "wb") as file:
                file.write(payload)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp, path)
            if os.name != "nt":
                directory = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        finally:
            temp.unlink(missing_ok=True)

    def entries(self) -> list[Path]:
        self._safe(self.root)
        return [self._safe(p) for p in sorted(self.root.glob("*.json")) if re.fullmatch(r"[a-f0-9]{64}\.json", p.name)]

    def size_bytes(self) -> int:
        return sum(p.stat().st_size for p in self.entries())

    def _sync_directory(self) -> None:
        if os.name != "nt":
            fd = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)

    def delete(self, uid: str) -> None:
        self.acquire()
        self._path(uid).unlink(missing_ok=True)
        self._sync_directory()

    def delete_key(self, key: str) -> None:
        if not re.fullmatch(r"[a-f0-9]{64}", key):
            raise MeasurementStorageError("identity")
        self.acquire()
        self._safe(self.root / (key + ".json")).unlink(missing_ok=True)
        self._sync_directory()

    def delete_all(self) -> None:
        self.acquire()
        for path in self.entries():
            path.unlink()  # report failure; never claim a partially failed delete succeeded
        self._sync_directory()
