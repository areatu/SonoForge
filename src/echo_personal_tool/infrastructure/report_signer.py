"""Local Ed25519 report signer adapter and detached receipt store (#624).

Implements :class:`~echo_personal_tool.domain.ports.SignerPort` on top of the
password-wrapped Ed25519 envelopes from :mod:`user_crypto`. The private seed is
unwrapped with the signer's password/PIN only inside :meth:`sign` and wiped
from memory immediately afterwards; it is never written to disk in plaintext.

The receipt store persists detached ``.sig.json`` files next to exported PDFs
with atomic writes, symlink checks and size limits, mirroring the user store
and audit log conventions.
"""

from __future__ import annotations

import contextlib
import json
import os
import uuid
from pathlib import Path

from echo_personal_tool.domain.exceptions import ReportSignatureError, UserAuthError
from echo_personal_tool.domain.models.report_signature import (
    MAX_RECEIPT_BYTES,
    SIGNATURE_ALGORITHM,
    SignatureReceipt,
)
from echo_personal_tool.domain.models.user import ArchivedSigningKey, SigningKeyPublic, is_valid_user_id
from echo_personal_tool.domain.ports import ReportSignature
from echo_personal_tool.infrastructure.user_crypto import sign_with_user_key, verify_ed25519_signature
from echo_personal_tool.infrastructure.user_repository import LocalUserRepository


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
        raise ReportSignatureError("unsafe_path")
    if _is_unsafe_link(path.parent) and path.parent.exists():
        raise ReportSignatureError("unsafe_path")
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
        raise ReportSignatureError("io_error")
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
    except OSError as exc:
        raise ReportSignatureError("io_error") from exc
    finally:
        temp.unlink(missing_ok=True)


class Ed25519SignerAdapter:
    """Bind one local user to the :class:`SignerPort` contract.

    Constructed per signing user; :meth:`sign` re-authenticates through the
    repository so brute-force lockout also protects signing prompts.
    """

    def __init__(self, repository: LocalUserRepository, user_id: str) -> None:
        if not is_valid_user_id(user_id):
            raise ReportSignatureError("invalid_signer")
        self._repository = repository
        self._user_id = user_id

    @property
    def user_id(self) -> str:
        return self._user_id

    def sign(self, payload: bytes, *, secret: str) -> ReportSignature:
        """Unwrap the bound user's Ed25519 key with *secret* and sign *payload*."""
        if not isinstance(payload, (bytes, bytearray)) or not payload:
            raise ReportSignatureError("invalid_payload")
        if not isinstance(secret, str) or not secret:
            raise ReportSignatureError("invalid_secret")
        # Re-authenticate so lockout counters protect signing prompts too.
        try:
            self._repository.authenticate(self._username(), secret, record_login=False)
        except UserAuthError as exc:
            raise ReportSignatureError(exc.code) from exc
        envelope = self._repository.get_signing_envelope(self._user_id)
        try:
            raw_signature = sign_with_user_key(envelope, user_id=self._user_id, secret=secret, payload=bytes(payload))
        except UserAuthError as exc:
            raise ReportSignatureError(exc.code) from exc
        public = envelope.public_key()
        return ReportSignature(
            key_id=public.key_id,
            algorithm=public.algorithm,
            public_key_b64=public.public_key_b64,
            signature=raw_signature,
        )

    def verify(self, payload: bytes, signature: ReportSignature) -> bool:
        """Verify *signature* over *payload* against its embedded public key."""
        if signature.algorithm != SIGNATURE_ALGORITHM:
            return False
        if len(signature.signature) != 64:
            return False
        return verify_ed25519_signature(signature.public_key_b64, bytes(payload), signature.signature)

    def find_public_key(self, user_id: str, key_id: str) -> SigningKeyPublic | ArchivedSigningKey | None:
        """Look up active or archived public key (including deactivated users)."""
        if not is_valid_user_id(user_id):
            return None
        users = self._repository.load_state().users
        profile = next((item for item in users if item.user_id == user_id), None)
        if profile is None:
            return None
        return profile.find_public_key(key_id)

    def _username(self) -> str:
        users = self._repository.load_state().users
        profile = next((item for item in users if item.user_id == self._user_id), None)
        if profile is None:
            raise ReportSignatureError("invalid_signer")
        return profile.username


def receipt_to_bytes(receipt: SignatureReceipt) -> bytes:
    """Serialize a receipt to deterministic UTF-8 JSON bytes."""
    payload = json.dumps(receipt.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(payload) > MAX_RECEIPT_BYTES:
        raise ReportSignatureError("invalid_receipt")
    return payload


def receipt_from_bytes(payload: bytes) -> SignatureReceipt:
    """Parse and validate detached receipt bytes (bounded, strict)."""
    if not isinstance(payload, (bytes, bytearray)) or not payload or len(payload) > MAX_RECEIPT_BYTES:
        raise ReportSignatureError("invalid_receipt")
    try:
        raw = json.loads(bytes(payload).decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ReportSignatureError("invalid_receipt") from exc
    if not isinstance(raw, dict):
        raise ReportSignatureError("invalid_receipt")
    return SignatureReceipt.from_dict(raw)


def write_receipt_file(path: Path, receipt: SignatureReceipt) -> Path:
    """Atomically write *receipt* to *path* (``.sig.json``) and return it."""
    target = Path(path)
    if target.suffix != ".json":
        raise ReportSignatureError("invalid_receipt_path")
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _atomic_write_bytes(target, receipt_to_bytes(receipt))
    return target


def read_receipt_file(path: Path) -> SignatureReceipt:
    """Read and validate a detached receipt file (never follows symlinks)."""
    target = Path(path)
    if _is_unsafe_link(target):
        raise ReportSignatureError("unsafe_path")
    try:
        payload = target.read_bytes()
    except FileNotFoundError as exc:
        raise ReportSignatureError("receipt_not_found") from exc
    except OSError as exc:
        raise ReportSignatureError("io_error") from exc
    return receipt_from_bytes(payload)


def receipt_path_for_pdf(pdf_path: Path) -> Path:
    """Return the detached receipt path for an exported PDF (``name.sig.json``)."""
    target = Path(pdf_path)
    if target.suffix.lower() != ".pdf":
        raise ReportSignatureError("invalid_receipt_path")
    return target.with_suffix(".sig.json")
