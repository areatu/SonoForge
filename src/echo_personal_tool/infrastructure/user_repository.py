"""Atomic local workstation user store (``users.json``).

Persists local user profiles, scrypt password/PIN verifiers, password-wrapped
Ed25519 signing keys, archived public keys and lockout counters under
``<users_dir>/users.json`` with ``0o700``/``0o600`` permissions, symlink checks,
advisory file locking and ``O_EXCL`` + ``fsync`` + ``os.replace`` writes.
"""

from __future__ import annotations

import contextlib
import errno
import json
import os
import sys
import threading
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from echo_personal_tool.domain.exceptions import UserAuthError
from echo_personal_tool.domain.models.user import (
    DEFAULT_AUTO_LOCK_MINUTES,
    KEY_ID_RE,
    ArchivedSigningKey,
    SecretKind,
    UserProfile,
    UserRole,
    clamp_auto_lock_minutes,
    compute_locked_until,
    is_valid_user_id,
    normalize_username,
    remaining_lockout_seconds,
    validate_display_name,
    validate_external_id,
    validate_secret,
    validate_title,
    validate_username,
)
from echo_personal_tool.infrastructure.user_crypto import (
    DEFAULT_SCRYPT_N,
    EncryptedSigningKey,
    PasswordVerifier,
    dummy_verify_secret,
    generate_user_signing_key,
    hash_secret,
    reencrypt_signing_key,
    verify_secret,
)

_UTC = timezone.utc  # noqa: UP017 - aligned with ruff target py310
FORMAT = "sonoforge.local-users"
SCHEMA_VERSION = 1
USERS_FILENAME = "users.json"
MAX_USERS_FILE_BYTES = 4 * 1024 * 1024
MAX_USERS = 200


def _is_unsafe_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        stat = path.lstat()
    except FileNotFoundError:
        return False
    return bool(getattr(stat, "st_file_attributes", 0) & 0x400)


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    if _is_unsafe_link(path):
        raise UserAuthError("storage_error")
    temp: Path | None = None
    fd = -1
    for _ in range(3):
        candidate = path.parent / f".pending-{uuid.uuid4().hex}.tmp"
        try:
            fd = os.open(candidate, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
            temp = candidate
            break
        except FileExistsError:
            continue
    if temp is None:
        raise OSError(errno.EEXIST, "no usable temporary file")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        if os.name != "nt":
            with contextlib.suppress(OSError):
                os.chmod(path, 0o600)
            dir_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
    finally:
        temp.unlink(missing_ok=True)


@dataclass(frozen=True)
class _StoredUser:
    profile: UserProfile
    verifier: PasswordVerifier
    signing_envelope: EncryptedSigningKey
    failed_attempts: int = 0
    locked_until: str = ""

    def to_dict(self) -> dict[str, Any]:
        p = self.profile
        return {
            "user_id": p.user_id,
            "username": p.username,
            "display_name": p.display_name,
            "role": p.role.value,
            "title": p.title,
            "external_id": p.external_id,
            "secret_kind": p.secret_kind.value,
            "active": p.active,
            "created_at": p.created_at,
            "updated_at": p.updated_at,
            "last_login_at": p.last_login_at,
            "verifier": self.verifier.to_dict(),
            "signing_key": self.signing_envelope.to_dict(),
            "archived_keys": [
                {
                    "key_id": item.key_id,
                    "algorithm": item.algorithm,
                    "public_key_b64": item.public_key_b64,
                    "created_at": item.created_at,
                    "retired_at": item.retired_at,
                    "reason": item.reason,
                }
                for item in p.archived_keys
            ],
            "failed_attempts": self.failed_attempts,
            "locked_until": self.locked_until,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> _StoredUser:
        user_id = str(data.get("user_id", ""))
        if not is_valid_user_id(user_id):
            raise UserAuthError("corrupt_store")
        username = validate_username(str(data.get("username", "")))
        display_name = validate_display_name(str(data.get("display_name", "")))
        title = validate_title(str(data.get("title", "")))
        external_id = validate_external_id(str(data.get("external_id", "")))
        try:
            role = UserRole(str(data.get("role", "")))
            secret_kind = SecretKind(str(data.get("secret_kind", "")))
        except ValueError as exc:
            raise UserAuthError("corrupt_store") from exc
        active = data.get("active")
        if not isinstance(active, bool):
            raise UserAuthError("corrupt_store")
        raw_verifier = data.get("verifier")
        raw_signing = data.get("signing_key")
        raw_archived = data.get("archived_keys", [])
        if (
            not isinstance(raw_verifier, dict)
            or not isinstance(raw_signing, dict)
            or not isinstance(raw_archived, list)
        ):
            raise UserAuthError("corrupt_store")
        verifier = PasswordVerifier.from_dict(raw_verifier)
        envelope = EncryptedSigningKey.from_dict(raw_signing)
        archived_items: list[ArchivedSigningKey] = []
        for entry in raw_archived:
            if not isinstance(entry, dict):
                raise UserAuthError("corrupt_store")
            arch_id = str(entry.get("key_id", ""))
            if not KEY_ID_RE.fullmatch(arch_id):
                raise UserAuthError("corrupt_store")
            archived_items.append(
                ArchivedSigningKey(
                    key_id=arch_id,
                    algorithm=str(entry.get("algorithm", "ed25519")),
                    public_key_b64=str(entry.get("public_key_b64", "")),
                    created_at=str(entry.get("created_at", "")),
                    retired_at=str(entry.get("retired_at", "")),
                    reason=str(entry.get("reason", "password_reset")),
                )
            )
        failed_attempts = data.get("failed_attempts", 0)
        if type(failed_attempts) is not int or failed_attempts < 0:
            raise UserAuthError("corrupt_store")
        locked_until = str(data.get("locked_until", ""))
        profile = UserProfile(
            user_id=user_id,
            username=username,
            display_name=display_name,
            role=role,
            title=title,
            external_id=external_id,
            secret_kind=secret_kind,
            active=active,
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
            last_login_at=str(data.get("last_login_at", "")),
            signing_key=envelope.public_key(),
            archived_keys=tuple(archived_items),
        )
        return cls(
            profile=profile,
            verifier=verifier,
            signing_envelope=envelope,
            failed_attempts=failed_attempts,
            locked_until=locked_until,
        )


@dataclass(frozen=True)
class UserStoreState:
    """Public metadata snapshot of the local user repository."""

    multi_user_enabled: bool = False
    auto_lock_minutes: int = DEFAULT_AUTO_LOCK_MINUTES
    last_username: str = ""
    users: tuple[UserProfile, ...] = ()


@dataclass
class _StoreDocument:
    multi_user_enabled: bool = False
    auto_lock_minutes: int = DEFAULT_AUTO_LOCK_MINUTES
    last_username: str = ""
    users: list[_StoredUser] | None = None

    def entries(self) -> list[_StoredUser]:
        if self.users is None:
            self.users = []
        return self.users

    def active_admin_count(self) -> int:
        return sum(1 for item in self.entries() if item.profile.active and item.profile.role is UserRole.ADMIN)

    def to_bytes(self) -> bytes:
        payload = {
            "format": FORMAT,
            "schema_version": SCHEMA_VERSION,
            "multi_user_enabled": self.multi_user_enabled,
            "auto_lock_minutes": clamp_auto_lock_minutes(self.auto_lock_minutes),
            "last_username": self.last_username,
            "users": [item.to_dict() for item in self.entries()],
        }
        return (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")

    @classmethod
    def from_bytes(cls, payload: bytes) -> _StoreDocument:
        if len(payload) > MAX_USERS_FILE_BYTES:
            raise UserAuthError("corrupt_store")
        try:
            raw = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise UserAuthError("corrupt_store") from exc
        if not isinstance(raw, dict) or raw.get("format") != FORMAT or raw.get("schema_version") != SCHEMA_VERSION:
            raise UserAuthError("corrupt_store")
        enabled = raw.get("multi_user_enabled")
        auto_lock = raw.get("auto_lock_minutes", DEFAULT_AUTO_LOCK_MINUTES)
        last_username = raw.get("last_username", "")
        raw_users = raw.get("users")
        if (
            not isinstance(enabled, bool)
            or type(auto_lock) is not int
            or not isinstance(last_username, str)
            or not isinstance(raw_users, list)
            or len(raw_users) > MAX_USERS
        ):
            raise UserAuthError("corrupt_store")
        seen_ids: set[str] = set()
        seen_names: set[str] = set()
        users: list[_StoredUser] = []
        for entry in raw_users:
            if not isinstance(entry, dict):
                raise UserAuthError("corrupt_store")
            stored = _StoredUser.from_dict(entry)
            if stored.profile.user_id in seen_ids or stored.profile.username in seen_names:
                raise UserAuthError("corrupt_store")
            seen_ids.add(stored.profile.user_id)
            seen_names.add(stored.profile.username)
            users.append(stored)
        doc = cls(
            multi_user_enabled=enabled,
            auto_lock_minutes=clamp_auto_lock_minutes(auto_lock),
            last_username=last_username,
            users=users,
        )
        if doc.multi_user_enabled and doc.active_admin_count() == 0:
            raise UserAuthError("corrupt_store")
        return doc


class LocalUserRepository:
    """Persistent repository of local workstation accounts."""

    def __init__(self, root: Path, *, scrypt_n: int = DEFAULT_SCRYPT_N) -> None:
        self._root = Path(root)
        self._path = self._root / USERS_FILENAME
        self._lock_path = self._root / ".users.lock"
        self._scrypt_n = scrypt_n
        self._thread_lock = threading.Lock()

    @property
    def root(self) -> Path:
        return self._root

    @property
    def path(self) -> Path:
        return self._path

    def _check_links(self, *, create_root: bool) -> None:
        if _is_unsafe_link(self._root):
            raise UserAuthError("storage_error")
        if create_root:
            try:
                self._root.mkdir(mode=0o700, parents=True, exist_ok=True)
            except OSError as exc:
                raise UserAuthError("storage_error") from exc
        if _is_unsafe_link(self._path) or _is_unsafe_link(self._lock_path):
            raise UserAuthError("storage_error")

    @contextlib.contextmanager
    def _locked(self) -> Iterator[None]:
        with self._thread_lock:
            self._check_links(create_root=True)
            try:
                lock_fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
                lock_file = os.fdopen(lock_fd, "a+b")
            except OSError as exc:
                raise UserAuthError("storage_error") from exc
            try:
                if sys.platform == "win32":
                    import msvcrt

                    lock_file.seek(0, 2)
                    if lock_file.tell() == 0:
                        lock_file.write(b"0")
                        lock_file.flush()
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
                else:
                    import fcntl

                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                yield
            except UserAuthError:
                raise
            except OSError as exc:
                raise UserAuthError("storage_error") from exc
            finally:
                lock_file.close()

    def _load_unlocked(self) -> _StoreDocument:
        self._check_links(create_root=False)
        try:
            payload = self._path.read_bytes()
        except FileNotFoundError:
            return _StoreDocument()
        except OSError as exc:
            raise UserAuthError("storage_error") from exc
        return _StoreDocument.from_bytes(payload)

    def _save_unlocked(self, doc: _StoreDocument) -> None:
        try:
            _atomic_write_bytes(self._path, doc.to_bytes())
        except UserAuthError:
            raise
        except OSError as exc:
            raise UserAuthError("storage_error") from exc

    def load_state(self) -> UserStoreState:
        """Read current store state without creating directories when unconfigured."""
        with self._thread_lock:
            doc = self._load_unlocked()
        return UserStoreState(
            multi_user_enabled=doc.multi_user_enabled,
            auto_lock_minutes=doc.auto_lock_minutes,
            last_username=doc.last_username,
            users=tuple(item.profile for item in doc.entries()),
        )

    def create_user(
        self,
        *,
        username: str,
        display_name: str,
        role: UserRole,
        secret: str,
        secret_kind: SecretKind = SecretKind.PASSWORD,
        title: str = "",
        external_id: str = "",
        enable_multi_user: bool = False,
        now: datetime | None = None,
    ) -> UserProfile:
        """Create a new local account with an scrypt verifier and wrapped Ed25519 key."""
        clean_username = validate_username(username)
        clean_name = validate_display_name(display_name)
        clean_title = validate_title(title)
        clean_ext = validate_external_id(external_id)
        validate_secret(secret, secret_kind)
        now_iso = (now if now is not None else datetime.now(_UTC)).isoformat()

        with self._locked():
            doc = self._load_unlocked()
            entries = doc.entries()
            if len(entries) >= MAX_USERS:
                raise UserAuthError("user_limit_reached")
            if any(item.profile.username == clean_username for item in entries):
                raise UserAuthError("username_taken")
            if not entries and role is not UserRole.ADMIN:
                raise UserAuthError("first_user_must_be_admin")
            user_id = uuid.uuid4().hex
            verifier = hash_secret(secret, n=self._scrypt_n)
            pub_key, envelope = generate_user_signing_key(
                user_id=user_id,
                secret=secret,
                created_at=now_iso,
                n=self._scrypt_n,
            )
            profile = UserProfile(
                user_id=user_id,
                username=clean_username,
                display_name=clean_name,
                role=role,
                title=clean_title,
                external_id=clean_ext,
                secret_kind=secret_kind,
                active=True,
                created_at=now_iso,
                updated_at=now_iso,
                last_login_at=now_iso if enable_multi_user else "",
                signing_key=pub_key,
                archived_keys=(),
            )
            entries.append(_StoredUser(profile=profile, verifier=verifier, signing_envelope=envelope))
            if enable_multi_user:
                doc.multi_user_enabled = True
                doc.last_username = clean_username
            self._save_unlocked(doc)
            return profile

    def authenticate(
        self,
        username: str,
        secret: str,
        *,
        enable_multi_user: bool = False,
        require_role: UserRole | None = None,
        record_login: bool = True,
        now: datetime | None = None,
    ) -> UserProfile:
        """Verify credentials, enforce brute-force cooldown and update lockout state."""
        current = now if now is not None else datetime.now(_UTC)
        clean_username = normalize_username(username)
        with self._locked():
            doc = self._load_unlocked()
            entries = doc.entries()
            idx = next((i for i, item in enumerate(entries) if item.profile.username == clean_username), -1)
            if idx < 0:
                dummy_verify_secret(secret, n=self._scrypt_n)
                raise UserAuthError("invalid_credentials")
            stored = entries[idx]
            if not stored.profile.active:
                dummy_verify_secret(secret, n=self._scrypt_n)
                raise UserAuthError("account_disabled")
            retry = remaining_lockout_seconds(stored.locked_until, now=current)
            if retry > 0:
                raise UserAuthError("account_locked", retry_after_seconds=retry)
            if not verify_secret(secret, stored.verifier):
                attempts = stored.failed_attempts + 1
                locked_until = compute_locked_until(attempts, now=current)
                entries[idx] = replace(stored, failed_attempts=attempts, locked_until=locked_until)
                self._save_unlocked(doc)
                new_retry = remaining_lockout_seconds(locked_until, now=current)
                if new_retry > 0:
                    raise UserAuthError("account_locked", retry_after_seconds=new_retry)
                raise UserAuthError("invalid_credentials")
            if require_role is not None and stored.profile.role is not require_role:
                raise UserAuthError("permission_denied")
            updated_profile = (
                replace(stored.profile, last_login_at=current.isoformat()) if record_login else stored.profile
            )
            dirty = stored.failed_attempts != 0 or bool(stored.locked_until) or record_login
            entries[idx] = replace(stored, profile=updated_profile, failed_attempts=0, locked_until="")
            if record_login and doc.last_username != updated_profile.username:
                doc.last_username = updated_profile.username
                dirty = True
            if enable_multi_user and not doc.multi_user_enabled:
                doc.multi_user_enabled = True
                dirty = True
            if dirty:
                self._save_unlocked(doc)
            return updated_profile

    def update_user(
        self,
        user_id: str,
        *,
        display_name: str,
        title: str,
        external_id: str,
        role: UserRole,
        now: datetime | None = None,
    ) -> UserProfile:
        """Update editable profile metadata and role while keeping at least one active admin."""
        clean_name = validate_display_name(display_name)
        clean_title = validate_title(title)
        clean_ext = validate_external_id(external_id)
        now_iso = (now if now is not None else datetime.now(_UTC)).isoformat()
        with self._locked():
            doc = self._load_unlocked()
            idx = self._index_of(doc, user_id)
            stored = doc.entries()[idx]
            if (
                stored.profile.active
                and stored.profile.role is UserRole.ADMIN
                and role is not UserRole.ADMIN
                and doc.active_admin_count() <= 1
            ):
                raise UserAuthError("last_admin")
            updated = replace(
                stored.profile,
                display_name=clean_name,
                title=clean_title,
                external_id=clean_ext,
                role=role,
                updated_at=now_iso,
            )
            doc.entries()[idx] = replace(stored, profile=updated)
            self._save_unlocked(doc)
            return updated

    def set_user_active(
        self,
        user_id: str,
        *,
        active: bool,
        now: datetime | None = None,
    ) -> UserProfile:
        """Soft-activate or soft-deactivate an account (records are never deleted)."""
        now_iso = (now if now is not None else datetime.now(_UTC)).isoformat()
        with self._locked():
            doc = self._load_unlocked()
            idx = self._index_of(doc, user_id)
            stored = doc.entries()[idx]
            if not active and stored.profile.active and stored.profile.role is UserRole.ADMIN:
                if doc.active_admin_count() <= 1:
                    raise UserAuthError("last_admin")
            updated = replace(stored.profile, active=active, updated_at=now_iso)
            doc.entries()[idx] = replace(stored, profile=updated, failed_attempts=0, locked_until="")
            self._save_unlocked(doc)
            return updated

    def change_own_secret(
        self,
        user_id: str,
        *,
        old_secret: str,
        new_secret: str,
        new_kind: SecretKind,
        now: datetime | None = None,
    ) -> UserProfile:
        """Change a user's own secret and re-wrap their existing Ed25519 private key."""
        validate_secret(new_secret, new_kind)
        current = now if now is not None else datetime.now(_UTC)
        with self._locked():
            doc = self._load_unlocked()
            idx = self._index_of(doc, user_id)
            stored = doc.entries()[idx]
            retry = remaining_lockout_seconds(stored.locked_until, now=current)
            if retry > 0:
                raise UserAuthError("account_locked", retry_after_seconds=retry)
            if not verify_secret(old_secret, stored.verifier):
                attempts = stored.failed_attempts + 1
                locked_until = compute_locked_until(attempts, now=current)
                doc.entries()[idx] = replace(stored, failed_attempts=attempts, locked_until=locked_until)
                self._save_unlocked(doc)
                raise UserAuthError("invalid_credentials")
            new_envelope = reencrypt_signing_key(
                stored.signing_envelope,
                user_id=user_id,
                old_secret=old_secret,
                new_secret=new_secret,
                n=self._scrypt_n,
            )
            new_verifier = hash_secret(new_secret, n=self._scrypt_n)
            updated = replace(stored.profile, secret_kind=new_kind, updated_at=current.isoformat())
            doc.entries()[idx] = replace(
                stored,
                profile=updated,
                verifier=new_verifier,
                signing_envelope=new_envelope,
                failed_attempts=0,
                locked_until="",
            )
            self._save_unlocked(doc)
            return updated

    def admin_reset_secret(
        self,
        user_id: str,
        *,
        new_secret: str,
        new_kind: SecretKind,
        now: datetime | None = None,
    ) -> tuple[UserProfile, str]:
        """Reset an account's secret, rotate its Ed25519 key and archive the old public key.

        Returns ``(updated_profile, previous_key_id)``.
        """
        validate_secret(new_secret, new_kind)
        now_iso = (now if now is not None else datetime.now(_UTC)).isoformat()
        with self._locked():
            doc = self._load_unlocked()
            idx = self._index_of(doc, user_id)
            stored = doc.entries()[idx]
            old_pub = stored.signing_envelope.public_key()
            archived = ArchivedSigningKey(
                key_id=old_pub.key_id,
                algorithm=old_pub.algorithm,
                public_key_b64=old_pub.public_key_b64,
                created_at=old_pub.created_at,
                retired_at=now_iso,
                reason="password_reset",
            )
            new_pub, new_envelope = generate_user_signing_key(
                user_id=user_id,
                secret=new_secret,
                created_at=now_iso,
                n=self._scrypt_n,
            )
            new_verifier = hash_secret(new_secret, n=self._scrypt_n)
            updated = replace(
                stored.profile,
                secret_kind=new_kind,
                updated_at=now_iso,
                signing_key=new_pub,
                archived_keys=stored.profile.archived_keys + (archived,),
            )
            doc.entries()[idx] = replace(
                stored,
                profile=updated,
                verifier=new_verifier,
                signing_envelope=new_envelope,
                failed_attempts=0,
                locked_until="",
            )
            self._save_unlocked(doc)
            return updated, old_pub.key_id

    def set_auto_lock_minutes(self, minutes: int) -> int:
        """Persist workstation inactivity auto-lock timeout in minutes."""
        clamped = clamp_auto_lock_minutes(minutes)
        with self._locked():
            doc = self._load_unlocked()
            doc.auto_lock_minutes = clamped
            self._save_unlocked(doc)
        return clamped

    def set_multi_user_enabled(self, enabled: bool) -> None:
        """Toggle multi-user mode while keeping all accounts and signing keys on disk."""
        with self._locked():
            doc = self._load_unlocked()
            if enabled and doc.active_admin_count() == 0:
                raise UserAuthError("last_admin")
            doc.multi_user_enabled = enabled
            self._save_unlocked(doc)

    def get_signing_envelope(self, user_id: str) -> EncryptedSigningKey:
        """Return the encrypted Ed25519 envelope for an active user (used at signing time)."""
        with self._thread_lock:
            doc = self._load_unlocked()
            idx = self._index_of(doc, user_id)
            stored = doc.entries()[idx]
            if not stored.profile.active:
                raise UserAuthError("account_disabled")
            return stored.signing_envelope

    @staticmethod
    def _index_of(doc: _StoreDocument, user_id: str) -> int:
        for idx, item in enumerate(doc.entries()):
            if item.profile.user_id == user_id:
                return idx
        raise UserAuthError("user_not_found")
