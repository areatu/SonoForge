"""At-rest encryption for the saved-measurements store (Z2-M).

Every measurement record is sealed with AES-256-GCM *before* it reaches the
disk; the 256-bit key never lives next to the ciphertexts in non-portable
mode.  The envelope is a small, versioned JSON document that keeps the
``*.json`` record naming, the write-admission quota and the listing logic of
:class:`MeasurementRepository` unchanged.

Key sources by profile (threat model matches ``SECURITY.md``):

* **Non-portable (full build):** a random 32-byte key is generated once and
  stored in the OS keychain via ``keyring``, scoped to the OS user.  Other
  local accounts, backup copies of just the data directory, and every process
  that cannot read the keychain cannot read the measurements.
* **Portable (Presenter / forced portable):** the key is wrapped with the
  portable device secret (the same secret that protects stored PACS
  passwords) and kept as ``.vault.key`` beside the records.  Possessing the
  whole stick still means possessing the key — the documented device-key
  trade-off — but with master-password mode (#621) enabled the wrapped key
  is unreadable until the vault is unlocked, so the stick alone is not
  enough.

Fail-closed everywhere: a missing, unreadable or malformed key source, a
wrong key, a tampered ciphertext or a swapped envelope raises
:class:`MeasurementStorageError` with a stable code and never falls back to
plaintext.  Record payloads never enter log lines; only stable codes do.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from echo_personal_tool.infrastructure.measurement_codec import MeasurementStorageError

ENVELOPE_FORMAT = "sonoforge-measurements-encrypted"
ENVELOPE_VERSION = 1
VAULT_KEY_FORMAT = "sonoforge-measurements-vault-key"
VAULT_KEY_VERSION = 1
#: keyring service/username pair for the non-portable master record key.
KEY_SERVICE = "SonoForge"
KEY_USERNAME = "measurements.vault-key-v1"
#: Wrapped key file next to the records in portable mode; ``entries()`` only
#: matches ``<64 hex>.json``, the quota scan never sees it.
VAULT_KEY_NAME = ".vault.key"
VAULT_KEY_AAD = "sonoforge-measurements-vault-wrap-v1"

_KEY_BYTES = 32
_NONCE_BYTES = 12

_b64encode = base64.urlsafe_b64encode
_b64decode = base64.urlsafe_b64decode


def _b64e(raw: bytes) -> str:
    return _b64encode(raw).decode("ascii")


def _b64d(text: object) -> bytes:
    if not isinstance(text, str):
        raise MeasurementStorageError("decryption_failed")
    try:
        return base64.b64decode(text.encode("ascii"), altchars=b"-_", validate=True)
    except (ValueError, UnicodeEncodeError) as exc:
        raise MeasurementStorageError("decryption_failed") from exc


def key_id_for(key: bytes) -> str:
    """Stable short identifier of a record key (for rotation diagnostics only)."""
    return hashlib.sha256(b"sonoforge-key-id-v1" + key).hexdigest()[:16]


def is_encrypted_envelope(payload: bytes) -> bool:
    """Return ``True`` when *payload* is an encrypted record envelope.

    Parses the whole document (callers have already read it) and requires the
    exact format marker — a truncated or foreign JSON document is never
    mistaken for an envelope.
    """
    try:
        document = json.loads(payload)
    except (ValueError, UnicodeDecodeError):
        return False
    return isinstance(document, dict) and document.get("format") == ENVELOPE_FORMAT


def _load_aesgcm() -> Callable[..., Any]:
    """Import AESGCM lazily; ``cryptography`` is a hard runtime dependency."""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:  # pragma: no cover - hard dependency in package builds
        raise MeasurementStorageError("key_unavailable") from exc
    return cast(Callable[..., Any], AESGCM)


def _aead_errors() -> tuple[type[BaseException], ...]:
    """The exceptions an AEAD box may raise, without a broad ``except``.

    ``InvalidTag`` (wrong key, tampered ciphertext, swapped AAD) plus the
    value/type errors a malformed nonce or payload raises.  ``cryptography``
    ships no stubs in this project's mypy setup, so the import is defensive:
    without it the tag check still fails closed through the value/TypeError
    branches.
    """
    try:
        from cryptography.exceptions import InvalidTag
    except ImportError:  # pragma: no cover - cryptography is a hard dependency
        return (ValueError, TypeError)
    return (ValueError, TypeError, InvalidTag)


class MeasurementsCipher:
    """Seal/verify one measurement record per call with AES-256-GCM.

    The additional authenticated data binds the ciphertext to the record
    file key (the SHA-256 hex stem of ``<key>.json``) and to the envelope
    format/version, so envelopes cannot be swapped between records or fed to
    a different envelope reader without failing the GCM tag check.
    """

    __slots__ = ("_aesgcm", "_key_id")

    def __init__(self, key: bytes) -> None:
        if not isinstance(key, bytes) or len(key) != _KEY_BYTES:
            raise MeasurementStorageError("key_unavailable")
        self._aesgcm = _load_aesgcm()(key)
        self._key_id = key_id_for(key)

    @property
    def key_id(self) -> str:
        return self._key_id

    def encrypt(self, plaintext: bytes, *, aad: str) -> bytes:
        nonce = os.urandom(_NONCE_BYTES)
        associated = _aad_bytes(aad)
        try:
            ciphertext = self._aesgcm.encrypt(nonce, plaintext, associated)
        except (ValueError, TypeError) as exc:
            raise MeasurementStorageError("encryption_failed") from exc
        envelope = {
            "format": ENVELOPE_FORMAT,
            "version": ENVELOPE_VERSION,
            "key_id": self._key_id,
            "nonce": _b64e(nonce),
            "ciphertext": _b64e(ciphertext),
        }
        return json.dumps(envelope, ensure_ascii=True, separators=(",", ":")).encode("ascii")

    def decrypt(self, envelope: bytes, *, aad: str) -> bytes:
        try:
            document = json.loads(envelope)
        except (ValueError, UnicodeDecodeError) as exc:
            raise MeasurementStorageError("decryption_failed") from exc
        if not isinstance(document, dict):
            raise MeasurementStorageError("decryption_failed")
        if document.get("format") != ENVELOPE_FORMAT:
            raise MeasurementStorageError("decryption_failed")
        version = document.get("version")
        if version != ENVELOPE_VERSION:
            raise MeasurementStorageError("unsupported_envelope")
        if document.get("key_id") != self._key_id:
            raise MeasurementStorageError("key_mismatch")
        nonce = _b64d(document.get("nonce"))
        ciphertext = _b64d(document.get("ciphertext"))
        if len(nonce) != _NONCE_BYTES:
            raise MeasurementStorageError("decryption_failed")
        try:
            return bytes(self._aesgcm.decrypt(nonce, ciphertext, _aad_bytes(aad)))
        except _aead_errors() as exc:
            raise MeasurementStorageError("decryption_failed") from exc


def _aad_bytes(aad: str) -> bytes:
    return f"{ENVELOPE_FORMAT}:{ENVELOPE_VERSION}:{aad}".encode("ascii")


def _wrap_key_from_device_secret(secret: bytes) -> bytes:
    """Derive the vault-key wrapping key from the portable device secret."""
    if len(secret) < 16:
        raise MeasurementStorageError("key_unavailable")
    return hashlib.sha256(b"sonoforge-measurements-vault-wrap-v1" + secret).digest()


def _write_vault_key_file(path: Path, document: dict[str, Any]) -> None:
    payload = json.dumps(document, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(payload)
            file.flush()
            os.fsync(file.fileno())
    finally:
        if os.name != "nt":  # best effort; an unreadable key fails closed on next use
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass


def _read_vault_key_file(path: Path) -> dict[str, Any]:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise MeasurementStorageError("key_unavailable") from exc
    try:
        document = json.loads(payload)
    except (ValueError, UnicodeDecodeError) as exc:
        raise MeasurementStorageError("key_unavailable") from exc
    if not isinstance(document, dict) or document.get("format") != VAULT_KEY_FORMAT:
        raise MeasurementStorageError("key_unavailable")
    if document.get("version") != VAULT_KEY_VERSION:
        raise MeasurementStorageError("key_unavailable")
    return document


def _portable_cipher(root: Path) -> MeasurementsCipher:
    """Unwrap (or create) the record key wrapped under the device secret."""
    from echo_personal_tool.infrastructure.server_settings import portable_device_secret_for_wrapping

    secret = portable_device_secret_for_wrapping()
    if secret is None:
        raise MeasurementStorageError("vault_locked")
    wrap = _load_aesgcm()(_wrap_key_from_device_secret(secret))
    path = root / VAULT_KEY_NAME
    if path.exists() or path.is_symlink():
        document = _read_vault_key_file(path)
        try:
            raw = bytes(
                wrap.decrypt(
                    _b64d(document.get("nonce")),
                    _b64d(document.get("ciphertext")),
                    VAULT_KEY_AAD.encode("ascii"),
                )
            )
        except _aead_errors() as exc:
            raise MeasurementStorageError("key_unavailable") from exc
        if document.get("key_id") != key_id_for(raw):
            raise MeasurementStorageError("key_unavailable")
        return MeasurementsCipher(raw)
    key = os.urandom(_KEY_BYTES)
    cipher = MeasurementsCipher(key)
    nonce = os.urandom(_NONCE_BYTES)
    wrapped = _aesgcm_encrypt(wrap, nonce, key)
    _write_vault_key_file(
        path,
        {
            "format": VAULT_KEY_FORMAT,
            "version": VAULT_KEY_VERSION,
            "key_id": cipher.key_id,
            "nonce": _b64e(nonce),
            "ciphertext": _b64e(wrapped),
        },
    )
    return cipher


def _aesgcm_encrypt(aesgcm: Any, nonce: bytes, plaintext: bytes) -> bytes:
    associated = VAULT_KEY_AAD.encode("ascii")
    return bytes(aesgcm.encrypt(nonce, plaintext, associated))


def _keyring_errors() -> tuple[type[BaseException], ...]:
    """Backend failures the keychain may raise, without a broad ``except``.

    Backends are plugins: the standard ``KeyringError`` family plus the
    runtime/OSError shapes a broken backend actually surfaces.  Anything
    outside this tuple propagates — and is still fail-closed, because an
    unexpected exception aborts the start path before any record is written.
    """
    try:
        from keyring.errors import KeyringError
    except ImportError:  # pragma: no cover - keyring is a hard dependency
        return (RuntimeError, OSError, ValueError, TypeError, AttributeError)
    return (KeyringError, RuntimeError, OSError, ValueError, TypeError, AttributeError)


def _keyring_cipher() -> MeasurementsCipher:
    """Load (or generate) the record key from the OS keychain."""
    try:
        import keyring
    except ImportError as exc:  # pragma: no cover - keyring is a hard dependency
        raise MeasurementStorageError("key_unavailable") from exc
    try:
        stored = keyring.get_password(KEY_SERVICE, KEY_USERNAME)
    except _keyring_errors() as exc:
        raise MeasurementStorageError("key_unavailable") from exc
    if stored:
        try:
            key = bytes.fromhex(stored)
        except ValueError as exc:
            raise MeasurementStorageError("key_unavailable") from exc
        return MeasurementsCipher(key)
    key = os.urandom(_KEY_BYTES)
    try:
        keyring.set_password(KEY_SERVICE, KEY_USERNAME, key.hex())
    except _keyring_errors() as exc:
        raise MeasurementStorageError("key_unavailable") from exc
    return MeasurementsCipher(key)


def load_or_create_cipher(root: Path, *, portable: bool | None = None) -> MeasurementsCipher:
    """Resolve the at-rest cipher for *root* according to the active profile.

    ``portable`` overrides profile detection (tests); ``None`` follows
    ``profile.portable_enabled()``.  Never falls back to plaintext: any key
    problem raises ``MeasurementStorageError`` with a stable code.
    """
    if portable is None:
        from echo_personal_tool.infrastructure.profile import portable_enabled

        portable = portable_enabled()
    if portable:
        return _portable_cipher(root)
    return _keyring_cipher()
