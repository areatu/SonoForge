"""Tamper-evident local audit trail domain model (PHI-free by construction).

Pure domain module (standard library only). Every :class:`AuditEntry` links to
the SHA-256 digest of its predecessor, forming an append-only hash chain that
detects modification, deletion, insertion or reordering of events.

Privacy invariant: audit entries carry only opaque ``user_id`` values, opaque
64-hex ``study_key`` digests and an explicit allowlist of structured detail keys
— never patient names, birth dates, raw StudyInstanceUIDs, secrets or paths.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum

#: Previous-hash anchor of the first entry in a fresh audit log.
GENESIS_HASH = "0" * 64
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ACTOR_RE = re.compile(r"^(?:system|anonymous|[0-9a-f]{32})$")
_MAX_DETAIL_STR_LEN = 96

#: Explicit allowlist of detail keys accepted in audit entries (no PHI fields).
ALLOWED_DETAIL_KEYS: frozenset[str] = frozenset(
    {
        "auto_lock_minutes",
        "count",
        "key_id",
        "outcome",
        "previous_key_id",
        "protocol",
        "reason",
        "retry_after_seconds",
        "revision",
        "role",
        "secret_kind",
        "status",
        "target_username",
    }
)

DetailScalar = str | int | bool


class AuditAction(str, Enum):
    """Allowlisted event codes written to the local audit trail."""

    MULTI_USER_ENABLED = "auth.multi_user_enabled"
    MULTI_USER_DISABLED = "auth.multi_user_disabled"
    LOGIN_SUCCESS = "auth.login_success"
    LOGIN_FAILED = "auth.login_failed"
    LOGOUT = "auth.logout"
    SESSION_LOCKED = "auth.session_locked"
    SESSION_UNLOCKED = "auth.session_unlocked"
    SESSION_SWITCHED = "auth.session_switched"
    USER_CREATED = "user.created"
    USER_UPDATED = "user.updated"
    USER_DEACTIVATED = "user.deactivated"
    USER_REACTIVATED = "user.reactivated"
    SECRET_CHANGED = "user.secret_changed"
    SECRET_RESET = "user.secret_reset"
    SETTINGS_CHANGED = "auth.settings_changed"
    STUDY_SAVED = "study.saved"
    STUDY_DELETED = "study.deleted"
    STUDY_DELETE_ALL = "study.delete_all"
    REPORT_SIGNED = "report.signed"
    REPORT_AMENDED = "report.amended"
    INTEROP_EXPORTED = "interop.exported"


VALID_AUDIT_ACTIONS: frozenset[str] = frozenset(item.value for item in AuditAction)


def sanitize_audit_details(
    details: Mapping[str, DetailScalar] | None,
) -> tuple[tuple[str, DetailScalar], ...]:
    """Validate and canonically sort audit details; reject unknown or unsafe fields."""
    if not details:
        return ()
    items: list[tuple[str, DetailScalar]] = []
    for key in sorted(details):
        if key not in ALLOWED_DETAIL_KEYS:
            raise ValueError(f"disallowed audit detail key: {key!r}")
        value = details[key]
        if isinstance(value, bool):
            items.append((key, value))
        elif type(value) is int:
            items.append((key, value))
        elif isinstance(value, str):
            cleaned = value.strip()
            if len(cleaned) > _MAX_DETAIL_STR_LEN or any(ord(ch) < 32 or ord(ch) == 127 for ch in cleaned):
                raise ValueError(f"invalid audit detail value for {key!r}")
            items.append((key, cleaned))
        else:
            raise ValueError(f"unsupported audit detail type for {key!r}")
    return tuple(items)


def validate_actor_id(actor_id: str) -> str:
    """Ensure ``actor_id`` is ``'system'``, ``'anonymous'`` or a 32-hex ``user_id``."""
    if not isinstance(actor_id, str) or not _SAFE_ACTOR_RE.fullmatch(actor_id):
        raise ValueError("invalid actor_id")
    return actor_id


def validate_target_id(target_id: str) -> str:
    """Ensure ``target_id`` is empty or a 32-hex ``user_id``."""
    if target_id == "":
        return ""
    if not isinstance(target_id, str) or not re.fullmatch(r"^[0-9a-f]{32}$", target_id):
        raise ValueError("invalid target_id")
    return target_id


def validate_audit_study_key(study_key: str) -> str:
    """Ensure ``study_key`` is empty or an opaque 64-hex SHA-256 study key."""
    if study_key == "":
        return ""
    if not isinstance(study_key, str) or not _HEX64_RE.fullmatch(study_key):
        raise ValueError("invalid study_key")
    return study_key


def compute_entry_hash(
    *,
    seq: int,
    timestamp: str,
    action: str,
    actor_id: str,
    target_id: str,
    study_key: str,
    details: tuple[tuple[str, DetailScalar], ...],
    prev_hash: str,
) -> str:
    """Return canonical SHA-256 hex digest covering an entry and its predecessor hash."""
    canonical = {
        "seq": seq,
        "timestamp": timestamp,
        "action": action,
        "actor_id": actor_id,
        "target_id": target_id,
        "study_key": study_key,
        "details": [[k, v] for k, v in details],
        "prev_hash": prev_hash,
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class AuditEntry:
    """One immutable record of the hash-chained local audit trail."""

    seq: int
    timestamp: str
    action: str
    actor_id: str
    target_id: str = ""
    study_key: str = ""
    details: tuple[tuple[str, DetailScalar], ...] = ()
    prev_hash: str = GENESIS_HASH
    entry_hash: str = ""

    @property
    def details_dict(self) -> dict[str, DetailScalar]:
        return dict(self.details)

    def expected_hash(self) -> str:
        return compute_entry_hash(
            seq=self.seq,
            timestamp=self.timestamp,
            action=self.action,
            actor_id=self.actor_id,
            target_id=self.target_id,
            study_key=self.study_key,
            details=self.details,
            prev_hash=self.prev_hash,
        )


@dataclass(frozen=True)
class AuditVerificationResult:
    """Result of verifying an audit trail sequence from genesis."""

    valid: bool
    checked_count: int
    last_hash: str = GENESIS_HASH
    first_broken_seq: int | None = None
    reason: str = ""


def build_audit_entry(
    *,
    seq: int,
    timestamp: str,
    action: AuditAction | str,
    actor_id: str,
    prev_hash: str,
    target_id: str = "",
    study_key: str = "",
    details: Mapping[str, DetailScalar] | None = None,
) -> AuditEntry:
    """Construct a validated, hash-sealed :class:`AuditEntry`."""
    if type(seq) is not int or seq < 1:
        raise ValueError("seq must be a positive int")
    action_value = action.value if isinstance(action, AuditAction) else str(action)
    if action_value not in VALID_AUDIT_ACTIONS:
        raise ValueError(f"unknown audit action: {action_value!r}")
    if not isinstance(prev_hash, str) or not _HEX64_RE.fullmatch(prev_hash):
        raise ValueError("invalid prev_hash")
    checked_actor = validate_actor_id(actor_id)
    checked_target = validate_target_id(target_id)
    checked_study = validate_audit_study_key(study_key)
    checked_details = sanitize_audit_details(details)
    digest = compute_entry_hash(
        seq=seq,
        timestamp=timestamp,
        action=action_value,
        actor_id=checked_actor,
        target_id=checked_target,
        study_key=checked_study,
        details=checked_details,
        prev_hash=prev_hash,
    )
    return AuditEntry(
        seq=seq,
        timestamp=timestamp,
        action=action_value,
        actor_id=checked_actor,
        target_id=checked_target,
        study_key=checked_study,
        details=checked_details,
        prev_hash=prev_hash,
        entry_hash=digest,
    )


def verify_audit_chain(entries: Sequence[AuditEntry]) -> AuditVerificationResult:
    """Verify sequence continuity, prev-hash linkage and SHA-256 digests."""
    expected_prev = GENESIS_HASH
    for idx, entry in enumerate(entries, start=1):
        if entry.seq != idx:
            return AuditVerificationResult(
                valid=False,
                checked_count=idx - 1,
                last_hash=expected_prev,
                first_broken_seq=idx,
                reason="sequence_gap",
            )
        if entry.action not in VALID_AUDIT_ACTIONS:
            return AuditVerificationResult(
                valid=False,
                checked_count=idx - 1,
                last_hash=expected_prev,
                first_broken_seq=entry.seq,
                reason="invalid_action",
            )
        if entry.prev_hash != expected_prev:
            return AuditVerificationResult(
                valid=False,
                checked_count=idx - 1,
                last_hash=expected_prev,
                first_broken_seq=entry.seq,
                reason="prev_hash_mismatch",
            )
        if not _HEX64_RE.fullmatch(entry.entry_hash) or entry.entry_hash != entry.expected_hash():
            return AuditVerificationResult(
                valid=False,
                checked_count=idx - 1,
                last_hash=expected_prev,
                first_broken_seq=entry.seq,
                reason="hash_mismatch",
            )
        expected_prev = entry.entry_hash
    return AuditVerificationResult(
        valid=True,
        checked_count=len(entries),
        last_hash=expected_prev,
    )
