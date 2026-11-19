"""Optional master-password protection for the portable secret store (#621).

Portable mode keeps PACS password tokens (Fernet-encrypted in ``secrets.ini``)
next to a per-device ``device.key`` on the same stick. That protects against
casual inspection, but anyone who takes the whole stick takes the key too.

Master-password mode removes the plaintext ``device.key`` from the medium:

* a random 32-byte device secret is generated (or the existing one migrated);
* the *wrap key* is derived from the user's master password with memory-hard
  ``hashlib.scrypt`` (RFC 7914) and a per-install random salt;
* the device secret is stored only as a Fernet token (``device.key.enc``)
  encrypted under that wrap key;
* ``master.lock`` holds the KDF parameters, salt and a *verifier* digest
  (separate scrypt domain) so a wrong password is detected cheaply and
  fails closed — there is no fallback, no plaintext, no host keychain.

The unlocked device secret lives only in process memory for the session.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

KDF_ID = "scrypt-v1"
#: Master-password scrypt parameters: 2^15 * 8 * 1 ≈ 32 MiB RAM, ~100 ms desktop.
DEFAULT_SCRYPT_N = 1 << 15
DEFAULT_SCRYPT_R = 8
DEFAULT_SCRYPT_P = 1
_SCRYPT_MAXMEM = 256 * 1024 * 1024
_SALT_BYTES = 16
_DKLEN = 32
_DEVICE_SECRET_BYTES = 32

_VERIFIER_DOMAIN = b"sonoforge-master-verifier-v1"
_WRAP_DOMAIN = b"sonoforge-master-wrap-v1"

MASTER_LOCK_FILE = "master.lock"
MASTER_KEY_FILE = "device.key.enc"

_LOCK_VERSION = 1

#: Device secret unlocked for this process only; never written anywhere.
_SESSION_DEVICE_SECRET: bytearray | None = None


class MasterPasswordError(RuntimeError):
    """Master-password store cannot be used safely; ``code`` is a stable token."""

    def __init__(self, code: str) -> None:
        super().__init__(f"master password store unavailable ({code})")
        self.code = code


def _paths() -> tuple[Path, Path, Path]:
    from echo_personal_tool.infrastructure.profile import portable_path

    lock = portable_path(MASTER_LOCK_FILE)
    enc = portable_path(MASTER_KEY_FILE)
    device = portable_path("device.key")
    if lock is None or enc is None or device is None:
        raise MasterPasswordError("not_portable")
    return lock, enc, device


def _derive(password: str, salt: bytes, *, domain: bytes, n: int, r: int, p: int) -> bytes:
    material = domain + b"\x00" + password.encode("utf-8")
    return hashlib.scrypt(material, salt=salt, n=n, r=r, p=p, maxmem=_SCRYPT_MAXMEM, dklen=_DKLEN)


def _wrap_fernet(password: str, salt: bytes, *, n: int, r: int, p: int) -> Any:
    # ``cryptography`` is a follow_imports=skip dependency (#325): the Fernet
    # type reaches mypy as Any by contract.
    """Fernet key derived from the master password (wrap domain)."""
    from cryptography.fernet import Fernet

    key = _derive(password, salt, domain=_WRAP_DOMAIN, n=n, r=r, p=p)
    return Fernet(base64.urlsafe_b64encode(key))


def master_password_enabled() -> bool:
    """Whether the portable root is in master-password mode."""
    try:
        lock, _, _ = _paths()
    except MasterPasswordError:
        return False
    return lock.is_file() and not lock.is_symlink()


@dataclass(frozen=True)
class _LockParams:
    n: int
    r: int
    p: int
    salt: bytes
    verifier: bytes


def _read_lock(lock: Path) -> _LockParams:
    try:
        if lock.is_symlink() or not lock.is_file():
            raise MasterPasswordError("lock_missing")
        data = json.loads(lock.read_text(encoding="utf-8"))
    except MasterPasswordError:
        raise
    except (OSError, ValueError) as exc:
        raise MasterPasswordError("lock_invalid") from exc
    if not isinstance(data, dict) or data.get("version") != _LOCK_VERSION or data.get("kdf") != KDF_ID:
        raise MasterPasswordError("lock_invalid")
    n, r, p = data.get("n"), data.get("r"), data.get("p")
    if type(n) is not int or type(r) is not int or type(p) is not int:
        raise MasterPasswordError("lock_invalid")
    try:
        salt = bytes.fromhex(str(data.get("salt_hex", "")))
        verifier = bytes.fromhex(str(data.get("verifier_hex", "")))
    except ValueError as exc:
        raise MasterPasswordError("lock_invalid") from exc
    if len(salt) != _SALT_BYTES or len(verifier) != _DKLEN:
        raise MasterPasswordError("lock_invalid")
    return _LockParams(n=n, r=r, p=p, salt=salt, verifier=verifier)


def _write_private(path: Path, payload: bytes) -> None:
    """Write ``payload`` to ``path`` with 0600, fsync, atomic rename."""
    tmp = path.parent / f".{path.name}.{os.getpid()}.tmp"
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            written = os.write(fd, payload)
            if written != len(payload):
                raise OSError("short write")
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, path)
    except OSError as exc:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise MasterPasswordError("write_failed") from exc
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _make_lock(password: str) -> tuple[bytes, bytes, bytes]:
    """Return (salt, verifier, lock_payload) for a fresh master password."""
    salt = os.urandom(_SALT_BYTES)
    verifier = _derive(
        password, salt, domain=_VERIFIER_DOMAIN, n=DEFAULT_SCRYPT_N, r=DEFAULT_SCRYPT_R, p=DEFAULT_SCRYPT_P
    )
    payload = json.dumps(
        {
            "version": _LOCK_VERSION,
            "kdf": KDF_ID,
            "n": DEFAULT_SCRYPT_N,
            "r": DEFAULT_SCRYPT_R,
            "p": DEFAULT_SCRYPT_P,
            "salt_hex": salt.hex(),
            "verifier_hex": verifier.hex(),
        },
        sort_keys=True,
    ).encode("utf-8")
    return salt, verifier, payload


def _read_device_secret(path: Path) -> bytes:
    """Read and validate a plaintext device key (same format as server_settings)."""
    try:
        if path.is_symlink() or not path.is_file():
            raise MasterPasswordError("key_invalid")
        text = path.read_text(encoding="ascii")
    except MasterPasswordError:
        raise
    except OSError as exc:
        raise MasterPasswordError("key_unreadable") from exc
    except (UnicodeError, ValueError) as exc:
        raise MasterPasswordError("key_invalid") from exc
    stripped = text.strip()
    if len(stripped) != _DEVICE_SECRET_BYTES * 2:
        raise MasterPasswordError("key_invalid")
    try:
        raw = bytes.fromhex(stripped)
    except ValueError as exc:
        raise MasterPasswordError("key_invalid") from exc
    if len(raw) != _DEVICE_SECRET_BYTES:
        raise MasterPasswordError("key_invalid")
    return raw


def _has_stored_portable_secrets() -> bool:
    """Whether secrets.ini already holds encrypted tokens (via the portable INI)."""
    from echo_personal_tool.infrastructure.profile import qsettings_for, secrets_path

    if secrets_path() is None:
        raise MasterPasswordError("not_portable")
    try:
        return any(str(key).strip() for key in qsettings_for("SonoForge", "secrets").allKeys())
    except (OSError, RuntimeError, ValueError) as exc:
        # An unreadable store must not be mistaken for an empty one, because a
        # new key would orphan the existing tokens.
        raise MasterPasswordError("secrets_store_unreadable") from exc


def _device_secret_now(device_key: Path) -> bytes:
    """Existing plaintext device secret, a fresh one, or fail closed."""
    if device_key.exists() or device_key.is_symlink():
        return _read_device_secret(device_key)
    if _has_stored_portable_secrets():
        # A new random secret would orphan every stored token.
        raise MasterPasswordError("key_missing_with_secrets")
    return os.urandom(_DEVICE_SECRET_BYTES)


def set_master_password(password: str) -> None:
    """Enable master-password mode, migrating an existing ``device.key``.

    The plaintext ``device.key`` is removed from the medium once its secret
    is wrapped; secrets already in ``secrets.ini`` stay decryptable because
    the *device secret* is preserved, only its storage form changes.
    """
    if not password:
        raise MasterPasswordError("empty_password")
    lock, enc, device_key = _paths()
    if master_password_enabled():
        raise MasterPasswordError("already_enabled")
    secret = _device_secret_now(device_key)
    salt, _verifier, lock_payload = _make_lock(password)
    fernet = _wrap_fernet(password, salt, n=DEFAULT_SCRYPT_N, r=DEFAULT_SCRYPT_R, p=DEFAULT_SCRYPT_P)
    token = fernet.encrypt(secret).decode("ascii").encode("ascii")
    try:
        enc.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise MasterPasswordError("write_failed") from exc
    _write_private(enc, token)
    _write_private(lock, lock_payload)
    # Remove the plaintext key only after both wrapped files are durable.
    if device_key.exists() or device_key.is_symlink():
        try:
            device_key.unlink()
        except OSError as exc:
            raise MasterPasswordError("write_failed") from exc
    lock_master_password()


def unlock_master_password(password: str) -> bool:
    """Verify the master password and hold the device secret in memory.

    Returns False on a wrong password — the store stays fail-closed and no
    fallback key is derived.
    """
    global _SESSION_DEVICE_SECRET
    lock, enc, _device_key = _paths()
    params = _read_lock(lock)
    candidate = _derive(password, params.salt, domain=_VERIFIER_DOMAIN, n=params.n, r=params.r, p=params.p)
    if not hmac.compare_digest(candidate, params.verifier):
        return False
    try:
        if enc.is_symlink() or not enc.is_file():
            raise MasterPasswordError("key_invalid")
        token = enc.read_text(encoding="ascii").strip().encode("ascii")
    except MasterPasswordError:
        raise
    except (OSError, ValueError) as exc:
        raise MasterPasswordError("key_invalid") from exc
    fernet = _wrap_fernet(password, params.salt, n=params.n, r=params.r, p=params.p)
    from cryptography.fernet import InvalidToken

    try:
        secret = fernet.decrypt(token)
    except InvalidToken as exc:
        # Wrong password or tampered token: fail closed, never derive a fallback.
        raise MasterPasswordError("key_invalid") from exc
    if len(secret) != _DEVICE_SECRET_BYTES:
        raise MasterPasswordError("key_invalid")
    _SESSION_DEVICE_SECRET = bytearray(secret)
    return True


def lock_master_password() -> None:
    """Drop the in-memory device secret (session lock)."""
    global _SESSION_DEVICE_SECRET
    if _SESSION_DEVICE_SECRET is not None:
        for idx in range(len(_SESSION_DEVICE_SECRET)):
            _SESSION_DEVICE_SECRET[idx] = 0
    _SESSION_DEVICE_SECRET = None


def session_device_secret() -> bytes | None:
    """The unlocked device secret for this process, or None when locked."""
    if _SESSION_DEVICE_SECRET is None:
        return None
    return bytes(_SESSION_DEVICE_SECRET)


def change_master_password(old_password: str, new_password: str) -> bool:
    """Re-wrap the device secret under a new master password.

    Returns False when the old password does not verify; the stored files
    are left untouched in that case.
    """
    if not new_password:
        raise MasterPasswordError("empty_password")
    if not unlock_master_password(old_password):
        return False
    secret = session_device_secret()
    if secret is None:
        raise MasterPasswordError("key_invalid")
    lock, enc, _device_key = _paths()
    salt, _verifier, lock_payload = _make_lock(new_password)
    fernet = _wrap_fernet(new_password, salt, n=DEFAULT_SCRYPT_N, r=DEFAULT_SCRYPT_R, p=DEFAULT_SCRYPT_P)
    token = fernet.encrypt(secret).decode("ascii").encode("ascii")
    _write_private(enc, token)
    _write_private(lock, lock_payload)
    lock_master_password()
    return True


__all__ = [
    "MasterPasswordError",
    "change_master_password",
    "lock_master_password",
    "master_password_enabled",
    "session_device_secret",
    "set_master_password",
    "unlock_master_password",
]
