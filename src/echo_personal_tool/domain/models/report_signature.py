"""Local electronic signature of study reports (Ed25519, #624).

Pure domain module (standard library only — no Qt, no cryptography, no I/O).
Cryptographic signing and verification live behind
:class:`~echo_personal_tool.domain.ports.SignerPort`; this module owns the
canonical snapshot of a :class:`ReportDocument`, the detached receipt
(``.sig.json``) shape, the ``draft → signed → amended`` lifecycle and the
visual stamp data printed into the PDF.

Privacy invariant: a :class:`SignatureReceipt` carries only opaque ``user_id``
values, key fingerprints, SHA-256 digests and the signer display name — never
patient names, birth dates, raw StudyInstanceUIDs, secrets or paths. The
canonical snapshot itself is the printable report content; its hash binds the
signature to exactly what was shown.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from echo_personal_tool.domain.exceptions import ReportSignatureError
from echo_personal_tool.domain.models.user import KEY_ID_RE, is_valid_user_id

_UTC = timezone.utc  # noqa: UP017 - aligned with ruff target py310

#: Detached receipt format identifier written to ``.sig.json`` files.
SIGNATURE_FORMAT = "sonoforge.report-signature"
#: Receipt schema version written by this build.
SIGNATURE_SCHEMA_VERSION = 1
#: Only signing algorithm supported by the local adapter.
SIGNATURE_ALGORITHM = "ed25519"
#: Maximum receipt file size accepted on read (receipts are small JSON).
MAX_RECEIPT_BYTES = 64 * 1024
#: Maximum signature history kept on one study record.
MAX_SIGNATURES_PER_RECORD = 20
#: Maximum addendum history kept on one study record.
MAX_ADDENDA_PER_RECORD = 20
#: Maximum addendum reason length (free text, no control characters).
MAX_ADDENDUM_REASON_LENGTH = 500
#: Maximum signer display name / title length printed on the stamp.
MAX_SIGNER_NAME_LENGTH = 120

_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_ADDENDUM_ID_RE = re.compile(r"^[0-9a-f]{32}$")


class ReportLifecycle(str, Enum):
    """Lifecycle of one study protocol with respect to local signatures."""

    DRAFT = "draft"
    SIGNED = "signed"
    AMENDED = "amended"


#: Lifecycle values accepted on disk (legacy records without the field are draft).
VALID_LIFECYCLES: frozenset[str] = frozenset(item.value for item in ReportLifecycle)


def sha256_hex(data: bytes) -> str:
    """Return the lowercase hex SHA-256 digest of *data*."""
    return hashlib.sha256(data).hexdigest()


def is_valid_sha256(value: str) -> bool:
    """Return True if *value* is a canonical 64-hex SHA-256 digest."""
    return isinstance(value, str) and bool(_HEX64_RE.fullmatch(value))


def _clean_single_line(text: str, *, max_length: int, error_code: str, allow_empty: bool) -> str:
    cleaned = text.strip()
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in cleaned):
        raise ReportSignatureError(error_code)
    if not cleaned and not allow_empty:
        raise ReportSignatureError(error_code)
    if len(cleaned) > max_length:
        raise ReportSignatureError(error_code)
    return cleaned


def validate_signer_name(name: str) -> str:
    """Validate a signer display name printed on the stamp and stored in receipts."""
    return _clean_single_line(
        name, max_length=MAX_SIGNER_NAME_LENGTH, error_code="invalid_signer_name", allow_empty=False
    )


def validate_signer_title(title: str) -> str:
    """Validate an optional signer title printed on the stamp."""
    return _clean_single_line(
        title, max_length=MAX_SIGNER_NAME_LENGTH, error_code="invalid_signer_title", allow_empty=True
    )


def validate_addendum_reason(reason: str) -> str:
    """Validate an addendum reason (short free text, no control characters)."""
    return _clean_single_line(
        reason, max_length=MAX_ADDENDUM_REASON_LENGTH, error_code="invalid_addendum_reason", allow_empty=False
    )


def validate_addendum_id(value: str) -> str:
    """Ensure *value* is a canonical 32-hex addendum identifier."""
    if not isinstance(value, str) or not _ADDENDUM_ID_RE.fullmatch(value):
        raise ReportSignatureError("invalid_addendum_id")
    return value


def new_addendum_id() -> str:
    """Return a fresh opaque addendum identifier."""
    return uuid.uuid4().hex


def utc_now_iso(*, now: datetime | None = None) -> str:
    """Return the current UTC time as ISO-8601 (or *now* when injected)."""
    current = now if now is not None else datetime.now(_UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=_UTC)
    return current.astimezone(_UTC).isoformat()


def _parse_utc_timestamp(value: str) -> datetime:
    """Parse an ISO-8601 timestamp and require an explicit timezone."""
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ReportSignatureError("invalid_timestamp") from exc
    if parsed.tzinfo is None:
        raise ReportSignatureError("invalid_timestamp")
    return parsed.astimezone(_UTC)


def _b64_decode_strict(text: str, *, expected_len: int, error_code: str) -> bytes:
    if not isinstance(text, str) or not text:
        raise ReportSignatureError(error_code)
    try:
        raw = base64.b64decode(text.encode("ascii"), validate=True)
    except (ValueError, binascii.Error, UnicodeEncodeError) as exc:
        raise ReportSignatureError(error_code) from exc
    if len(raw) != expected_len:
        raise ReportSignatureError(error_code)
    return raw


def _b64_encode(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


@dataclass(frozen=True)
class SignatureReceipt:
    """Detached Ed25519 receipt binding one canonical report snapshot to a signer.

    The Ed25519 signature covers the ASCII hex of ``document_sha256`` — the
    SHA-256 of :func:`canonical_report_bytes` of the signed document — so a
    detached ``.sig.json`` alone is enough to verify the signature offline.
    ``pdf_sha256`` is the hash of the final exported PDF (which carries the
    visual stamp). Both digests are checked on verification so neither the
    document nor the exported file can be swapped silently.
    """

    user_id: str
    key_id: str
    algorithm: str
    public_key_b64: str
    signed_at: str
    document_sha256: str
    pdf_sha256: str
    signature_b64: str
    lifecycle: str = ReportLifecycle.SIGNED.value
    revision: int = 0
    signer_display_name: str = ""
    signer_title: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": SIGNATURE_FORMAT,
            "schema_version": SIGNATURE_SCHEMA_VERSION,
            "user_id": self.user_id,
            "key_id": self.key_id,
            "algorithm": self.algorithm,
            "public_key_b64": self.public_key_b64,
            "signed_at": self.signed_at,
            "document_sha256": self.document_sha256,
            "pdf_sha256": self.pdf_sha256,
            "signature_b64": self.signature_b64,
            "lifecycle": self.lifecycle,
            "revision": self.revision,
            "signer_display_name": self.signer_display_name,
            "signer_title": self.signer_title,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SignatureReceipt:
        """Validate and build a receipt from its detached ``.sig.json`` shape."""
        if not isinstance(data, dict):
            raise ReportSignatureError("invalid_receipt")
        if data.get("format") != SIGNATURE_FORMAT or data.get("schema_version") != SIGNATURE_SCHEMA_VERSION:
            raise ReportSignatureError("invalid_receipt")
        user_id = str(data.get("user_id", ""))
        if not is_valid_user_id(user_id):
            raise ReportSignatureError("invalid_receipt")
        key_id = str(data.get("key_id", ""))
        if not KEY_ID_RE.fullmatch(key_id):
            raise ReportSignatureError("invalid_receipt")
        if str(data.get("algorithm", "")) != SIGNATURE_ALGORITHM:
            raise ReportSignatureError("invalid_receipt")
        public_key_b64 = str(data.get("public_key_b64", ""))
        _b64_decode_strict(public_key_b64, expected_len=32, error_code="invalid_receipt")
        signed_at = str(data.get("signed_at", ""))
        _parse_utc_timestamp(signed_at)
        document_sha256 = str(data.get("document_sha256", ""))
        pdf_sha256 = str(data.get("pdf_sha256", ""))
        if not is_valid_sha256(document_sha256) or not is_valid_sha256(pdf_sha256):
            raise ReportSignatureError("invalid_receipt")
        signature_b64 = str(data.get("signature_b64", ""))
        _b64_decode_strict(signature_b64, expected_len=64, error_code="invalid_receipt")
        lifecycle = str(data.get("lifecycle", ReportLifecycle.SIGNED.value))
        if lifecycle not in VALID_LIFECYCLES:
            raise ReportSignatureError("invalid_receipt")
        revision = data.get("revision", 0)
        if type(revision) is not int or revision < 0:
            raise ReportSignatureError("invalid_receipt")
        signer_display_name = validate_signer_name(str(data.get("signer_display_name", "")))
        signer_title = validate_signer_title(str(data.get("signer_title", "")))
        return cls(
            user_id=user_id,
            key_id=key_id,
            algorithm=SIGNATURE_ALGORITHM,
            public_key_b64=public_key_b64,
            signed_at=signed_at,
            document_sha256=document_sha256,
            pdf_sha256=pdf_sha256,
            signature_b64=signature_b64,
            lifecycle=lifecycle,
            revision=revision,
            signer_display_name=signer_display_name,
            signer_title=signer_title,
        )

    def signature_bytes(self) -> bytes:
        """Return the raw 64-byte Ed25519 signature."""
        return _b64_decode_strict(self.signature_b64, expected_len=64, error_code="invalid_receipt")


@dataclass(frozen=True)
class ReportAddendum:
    """One explicit correction (addendum) applied to a signed protocol."""

    addendum_id: str
    created_at: str
    author_user_id: str
    reason: str
    previous_document_sha256: str
    new_document_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "addendum_id": self.addendum_id,
            "created_at": self.created_at,
            "author_user_id": self.author_user_id,
            "reason": self.reason,
            "previous_document_sha256": self.previous_document_sha256,
            "new_document_sha256": self.new_document_sha256,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReportAddendum:
        if not isinstance(data, dict):
            raise ReportSignatureError("invalid_addendum")
        addendum_id = validate_addendum_id(str(data.get("addendum_id", "")))
        created_at = str(data.get("created_at", ""))
        _parse_utc_timestamp(created_at)
        author_user_id = str(data.get("author_user_id", ""))
        if not is_valid_user_id(author_user_id):
            raise ReportSignatureError("invalid_addendum")
        reason = validate_addendum_reason(str(data.get("reason", "")))
        previous = str(data.get("previous_document_sha256", ""))
        new = str(data.get("new_document_sha256", ""))
        if not is_valid_sha256(previous) or not is_valid_sha256(new):
            raise ReportSignatureError("invalid_addendum")
        return cls(
            addendum_id=addendum_id,
            created_at=created_at,
            author_user_id=author_user_id,
            reason=reason,
            previous_document_sha256=previous,
            new_document_sha256=new,
        )


@dataclass(frozen=True)
class SignatureStamp:
    """Visual stamp printed into the signed PDF (honest local-EP label)."""

    signer_display_name: str
    signer_title: str
    signed_at: str
    key_id: str
    document_sha256: str

    @property
    def signer_label(self) -> str:
        """``'ФИО, должность'`` or ``'ФИО'`` as printed on the stamp."""
        if self.signer_title:
            return f"{self.signer_display_name}, {self.signer_title}"
        return self.signer_display_name


@dataclass(frozen=True)
class SignatureVerificationResult:
    """Outcome of an offline signature check (no patient data)."""

    valid: bool
    reason: str = ""
    receipt: SignatureReceipt | None = None
    key_archived: bool = False
    user_active: bool = True
    document_match: bool = False
    pdf_match: bool = False
    signature_match: bool = False


def canonical_report_dict(document: object) -> dict[str, Any]:
    """Project a :class:`ReportDocument` onto its printable, signable content.

    Only what the sheet prints is covered: patient header, title/profile,
    draft flag, notices and every group/value row. Lineage objects (``origin``,
    ``repeat``) are presentation aids and are deliberately excluded so the hash
    stays stable across UI-only changes.
    """
    patient = getattr(document, "patient", None)
    patient_dict: dict[str, Any] = {
        "name": getattr(patient, "name", ""),
        "patient_id": getattr(patient, "patient_id", ""),
        "birth_date": getattr(patient, "birth_date", ""),
        "age": getattr(patient, "age", ""),
        "sex": getattr(patient, "sex", ""),
        "study_date": getattr(patient, "study_date", ""),
        "height_cm": getattr(patient, "height_cm", None),
        "weight_kg": getattr(patient, "weight_kg", None),
        "bsa_m2": getattr(patient, "bsa_m2", None),
        "physician": getattr(patient, "physician", ""),
        "institution": getattr(patient, "institution", ""),
        "indication": getattr(patient, "indication", ""),
        "conclusion": getattr(patient, "conclusion", ""),
        "equipment": getattr(patient, "equipment", ""),
    }
    groups: list[dict[str, Any]] = []
    for group in getattr(document, "groups", ()) or ():
        values: list[dict[str, Any]] = []
        for value in getattr(group, "values", ()) or ():
            values.append(
                {
                    "label": getattr(value, "label", ""),
                    "value": getattr(value, "value", ""),
                    "unit": getattr(value, "unit", ""),
                    "norm": getattr(value, "norm", ""),
                    "pathological": bool(getattr(value, "pathological", False)),
                    "group": getattr(value, "group", ""),
                    "sample_count": getattr(value, "sample_count", None),
                    "key": getattr(value, "key", ""),
                    "parameter_id": getattr(value, "parameter_id", ""),
                    "repeat_sd": getattr(value, "repeat_sd", ""),
                    "repeat_cv": getattr(value, "repeat_cv", ""),
                }
            )
        groups.append(
            {
                "title": getattr(group, "title", ""),
                "key": getattr(group, "key", ""),
                "notes": list(getattr(group, "notes", ()) or ()),
                "values": values,
            }
        )
    return {
        "patient": patient_dict,
        "title": getattr(document, "title", ""),
        "profile_id": getattr(document, "profile_id", ""),
        "draft": bool(getattr(document, "draft", False)),
        "notices": list(getattr(document, "notices", ()) or ()),
        "groups": groups,
    }


def canonical_report_bytes(document: object) -> bytes:
    """Return deterministic UTF-8 bytes of the canonical report snapshot."""
    payload = canonical_report_dict(document)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode(
        "utf-8"
    )


def canonical_document_sha256(document: object) -> str:
    """Return the SHA-256 hex digest of the canonical report snapshot."""
    return sha256_hex(canonical_report_bytes(document))


def build_receipt(
    *,
    user_id: str,
    key_id: str,
    public_key_b64: str,
    signature: bytes,
    document: object,
    pdf_bytes: bytes,
    signed_at: str,
    lifecycle: str = ReportLifecycle.SIGNED.value,
    revision: int = 0,
    signer_display_name: str,
    signer_title: str = "",
) -> SignatureReceipt:
    """Build a validated receipt for *document* + *pdf_bytes* and a raw signature."""
    if not is_valid_user_id(user_id):
        raise ReportSignatureError("invalid_signer")
    if not KEY_ID_RE.fullmatch(key_id):
        raise ReportSignatureError("invalid_signer")
    if len(signature) != 64:
        raise ReportSignatureError("invalid_signature")
    if lifecycle not in VALID_LIFECYCLES:
        raise ReportSignatureError("invalid_lifecycle")
    if type(revision) is not int or revision < 0:
        raise ReportSignatureError("invalid_revision")
    _parse_utc_timestamp(signed_at)
    _b64_decode_strict(public_key_b64, expected_len=32, error_code="invalid_signer")
    return SignatureReceipt(
        user_id=user_id,
        key_id=key_id,
        algorithm=SIGNATURE_ALGORITHM,
        public_key_b64=public_key_b64,
        signed_at=signed_at,
        document_sha256=canonical_document_sha256(document),
        pdf_sha256=sha256_hex(pdf_bytes),
        signature_b64=_b64_encode(signature),
        lifecycle=lifecycle,
        revision=revision,
        signer_display_name=validate_signer_name(signer_display_name),
        signer_title=validate_signer_title(signer_title),
    )


def build_stamp(receipt: SignatureReceipt) -> SignatureStamp:
    """Return the visual stamp data for a receipt (printed into the signed PDF)."""
    return SignatureStamp(
        signer_display_name=receipt.signer_display_name,
        signer_title=receipt.signer_title,
        signed_at=receipt.signed_at,
        key_id=receipt.key_id,
        document_sha256=receipt.document_sha256,
    )


def validate_receipt_history(
    receipts: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> tuple[SignatureReceipt, ...]:
    """Validate an on-disk signature history list (bounded, ordered)."""
    if len(receipts) > MAX_SIGNATURES_PER_RECORD:
        raise ReportSignatureError("invalid_receipt")
    parsed: list[SignatureReceipt] = []
    for entry in receipts:
        if not isinstance(entry, dict):
            raise ReportSignatureError("invalid_receipt")
        parsed.append(SignatureReceipt.from_dict(entry))
    return tuple(parsed)


def validate_addendum_history(addenda: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> tuple[ReportAddendum, ...]:
    """Validate an on-disk addendum history list (bounded, ordered)."""
    if len(addenda) > MAX_ADDENDA_PER_RECORD:
        raise ReportSignatureError("invalid_addendum")
    parsed: list[ReportAddendum] = []
    for entry in addenda:
        if not isinstance(entry, dict):
            raise ReportSignatureError("invalid_addendum")
        parsed.append(ReportAddendum.from_dict(entry))
    return tuple(parsed)


def lifecycle_for_history(
    *,
    signatures: tuple[SignatureReceipt, ...],
    addenda: tuple[ReportAddendum, ...],
) -> ReportLifecycle:
    """Derive the lifecycle from stored histories (single source of truth)."""
    if addenda:
        return ReportLifecycle.AMENDED
    if signatures:
        return ReportLifecycle.SIGNED
    return ReportLifecycle.DRAFT


def next_lifecycle_after_sign(current: ReportLifecycle) -> ReportLifecycle:
    """Lifecycle after a successful signature (draft → signed, amended stays amended)."""
    if current is ReportLifecycle.DRAFT:
        return ReportLifecycle.SIGNED
    if current is ReportLifecycle.AMENDED:
        return ReportLifecycle.AMENDED
    raise ReportSignatureError("already_signed")
