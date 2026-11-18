"""Local workstation user identity, roles, permissions and session state.

Pure domain module (standard library only — no Qt, no cryptography, no I/O).
Password verifiers and encrypted private signing keys never cross into these
types: :class:`UserProfile` and :class:`UserSession` are safe to pass through
application facades and UI coordinators.

Multi-user mode is strictly opt-in: while ``multi_user_enabled`` is ``False``,
:meth:`UserSession.can` grants every permission so a single-user workstation
behaves identically to historical builds without a login prompt.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from types import MappingProxyType

from echo_personal_tool.domain.exceptions import UserAuthError

_UTC = timezone.utc  # noqa: UP017 - aligned with ruff target py310

#: Strict opaque user identifier: 32 lowercase hex chars (UUID4 hex).
USER_ID_RE = re.compile(r"^[0-9a-f]{32}$")
#: Strict short key fingerprint: 16 lowercase hex chars (first 64 bits of SHA-256).
KEY_ID_RE = re.compile(r"^[0-9a-f]{16}$")
#: Canonical login name: lowercase ASCII letters, digits and ``._-`` (2..32 chars).
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,31}$")
#: Numeric PIN length bounds (4..8 ASCII digits).
MIN_PIN_LENGTH = 4
MAX_PIN_LENGTH = 8
PIN_RE = re.compile(rf"^[0-9]{{{MIN_PIN_LENGTH},{MAX_PIN_LENGTH}}}$")
#: Password length bounds.
MIN_PASSWORD_LENGTH = 6
MAX_PASSWORD_LENGTH = 128
#: Display/profile field bounds.
MAX_DISPLAY_NAME_LENGTH = 120
MAX_TITLE_LENGTH = 120
MAX_EXTERNAL_ID_LENGTH = 64

#: Inactivity auto-lock bounds in minutes (0 disables automatic lock).
DEFAULT_AUTO_LOCK_MINUTES = 15
MIN_AUTO_LOCK_MINUTES = 0
MAX_AUTO_LOCK_MINUTES = 240

#: Brute-force lockout thresholds (especially important for 4-8 digit PINs).
LOCKOUT_FREE_ATTEMPTS = 5
LOCKOUT_BASE_SECONDS = 30
LOCKOUT_MAX_SECONDS = 300


class UserRole(str, Enum):
    """Role of a local workstation account."""

    #: Full workstation control: user accounts, audit log, server settings and clinical work.
    ADMIN = "admin"
    #: Attending physician: measure, edit/export reports, sign protocols and send to HIS/PACS.
    PHYSICIAN = "physician"
    #: Sonographer / resident: measure and prepare draft reports; cannot sign or manage users.
    OPERATOR = "operator"
    #: Read-only reviewer: open and inspect studies/reports; cannot modify, delete or export.
    VIEWER = "viewer"


class Permission(str, Enum):
    """Capabilities gated by :class:`UserRole` when multi-user mode is active."""

    VIEW_STUDY = "view_study"
    EDIT_MEASUREMENTS = "edit_measurements"
    DELETE_MEASUREMENTS = "delete_measurements"
    EDIT_REPORT = "edit_report"
    SIGN_REPORT = "sign_report"
    EXPORT_DATA = "export_data"
    CONFIGURE_SERVERS = "configure_servers"
    MANAGE_USERS = "manage_users"
    VIEW_AUDIT = "view_audit"


class SecretKind(str, Enum):
    """Authentication factor format chosen for an account."""

    PASSWORD = "password"
    PIN = "pin"


ROLE_PERMISSIONS: Mapping[UserRole, frozenset[Permission]] = MappingProxyType(
    {
        UserRole.ADMIN: frozenset(Permission),
        UserRole.PHYSICIAN: frozenset(
            {
                Permission.VIEW_STUDY,
                Permission.EDIT_MEASUREMENTS,
                Permission.DELETE_MEASUREMENTS,
                Permission.EDIT_REPORT,
                Permission.SIGN_REPORT,
                Permission.EXPORT_DATA,
            }
        ),
        UserRole.OPERATOR: frozenset(
            {
                Permission.VIEW_STUDY,
                Permission.EDIT_MEASUREMENTS,
                Permission.EDIT_REPORT,
                Permission.EXPORT_DATA,
            }
        ),
        UserRole.VIEWER: frozenset(
            {
                Permission.VIEW_STUDY,
            }
        ),
    }
)


def role_has_permission(role: UserRole, permission: Permission) -> bool:
    """Return True if *role* grants *permission*."""
    return permission in ROLE_PERMISSIONS[role]


def is_valid_user_id(user_id: str) -> bool:
    """Return True if *user_id* is a canonical 32-hex identifier."""
    return isinstance(user_id, str) and bool(USER_ID_RE.fullmatch(user_id))


def normalize_username(username: str) -> str:
    """Return trimmed, lowercase login identifier."""
    return username.strip().lower()


_RESERVED_USERNAMES: frozenset[str] = frozenset({"system", "anonymous"})


def validate_username(username: str) -> str:
    """Normalize and validate a login identifier; raise :class:`UserAuthError` if invalid."""
    normalized = normalize_username(username)
    if normalized in _RESERVED_USERNAMES or not USERNAME_RE.fullmatch(normalized):
        raise UserAuthError("invalid_username")
    return normalized


def _clean_single_line(text: str, *, max_length: int, error_code: str, allow_empty: bool) -> str:
    cleaned = text.strip()
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in cleaned):
        raise UserAuthError(error_code)
    if not cleaned and not allow_empty:
        raise UserAuthError(error_code)
    if len(cleaned) > max_length:
        raise UserAuthError(error_code)
    return cleaned


def validate_display_name(display_name: str) -> str:
    """Validate and trim a human-readable full name (e.g. physician name)."""
    return _clean_single_line(
        display_name,
        max_length=MAX_DISPLAY_NAME_LENGTH,
        error_code="invalid_display_name",
        allow_empty=False,
    )


def validate_title(title: str) -> str:
    """Validate optional role/specialty label printed on reports (e.g. 'Врач УЗД')."""
    return _clean_single_line(
        title,
        max_length=MAX_TITLE_LENGTH,
        error_code="invalid_title",
        allow_empty=True,
    )


def validate_external_id(external_id: str) -> str:
    """Validate optional staff/HIS identifier (used in HL7 XCN and FHIR Practitioner)."""
    return _clean_single_line(
        external_id,
        max_length=MAX_EXTERNAL_ID_LENGTH,
        error_code="invalid_external_id",
        allow_empty=True,
    )


def validate_secret(secret: str, kind: SecretKind) -> None:
    """Check secret format without returning or logging the secret itself."""
    if not isinstance(secret, str):
        raise UserAuthError("invalid_secret")
    if kind is SecretKind.PIN:
        if not PIN_RE.fullmatch(secret):
            raise UserAuthError("invalid_pin")
        return
    if (
        len(secret) < MIN_PASSWORD_LENGTH
        or len(secret) > MAX_PASSWORD_LENGTH
        or not secret.strip()
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in secret)
    ):
        raise UserAuthError("invalid_password")


def clamp_auto_lock_minutes(minutes: int) -> int:
    """Clamp inactivity lock timeout to the supported [0, 240] minute range."""
    return max(MIN_AUTO_LOCK_MINUTES, min(MAX_AUTO_LOCK_MINUTES, int(minutes)))


def format_key_fingerprint(key_id: str) -> str:
    """Format a 16-hex key id as grouped uppercase blocks (``A1B2-C3D4-E5F6-0708``)."""
    raw = key_id.strip().upper()
    if len(raw) != 16:
        return raw
    return f"{raw[0:4]}-{raw[4:8]}-{raw[8:12]}-{raw[12:16]}"


def lockout_duration_seconds(failed_attempts: int) -> int:
    """Return cooldown duration in seconds after *failed_attempts* consecutive failures."""
    if failed_attempts < LOCKOUT_FREE_ATTEMPTS:
        return 0
    exponent = min(failed_attempts - LOCKOUT_FREE_ATTEMPTS, 4)
    return min(LOCKOUT_MAX_SECONDS, LOCKOUT_BASE_SECONDS * (1 << exponent))


def compute_locked_until(failed_attempts: int, *, now: datetime | None = None) -> str:
    """Return UTC ISO-8601 lock expiry timestamp, or ``''`` if not locked."""
    seconds = lockout_duration_seconds(failed_attempts)
    if seconds <= 0:
        return ""
    current = now if now is not None else datetime.now(_UTC)
    return (current + timedelta(seconds=seconds)).isoformat()


def remaining_lockout_seconds(locked_until: str, *, now: datetime | None = None) -> int:
    """Return positive seconds remaining on an account lock, or ``0`` if expired/unset."""
    if not locked_until:
        return 0
    try:
        until = datetime.fromisoformat(locked_until)
    except ValueError:
        return 0
    if until.tzinfo is None:
        return 0
    current = now if now is not None else datetime.now(_UTC)
    delta = (until - current).total_seconds()
    if delta <= 0:
        return 0
    return max(1, int(delta + 0.999))


@dataclass(frozen=True)
class SigningKeyPublic:
    """Public half of a user's local Ed25519 signing key."""

    key_id: str
    algorithm: str = "ed25519"
    public_key_b64: str = ""
    created_at: str = ""

    @property
    def formatted_fingerprint(self) -> str:
        return format_key_fingerprint(self.key_id)


@dataclass(frozen=True)
class ArchivedSigningKey:
    """Retired public signing key preserved so historical report signatures still verify."""

    key_id: str
    algorithm: str
    public_key_b64: str
    created_at: str
    retired_at: str
    reason: str = "password_reset"

    @property
    def formatted_fingerprint(self) -> str:
        return format_key_fingerprint(self.key_id)


@dataclass(frozen=True)
class UserProfile:
    """Public profile of one local workstation account (no secret material)."""

    user_id: str
    username: str
    display_name: str
    role: UserRole = UserRole.PHYSICIAN
    title: str = ""
    external_id: str = ""
    secret_kind: SecretKind = SecretKind.PASSWORD
    active: bool = True
    created_at: str = ""
    updated_at: str = ""
    last_login_at: str = ""
    signing_key: SigningKeyPublic | None = None
    archived_keys: tuple[ArchivedSigningKey, ...] = ()

    def can(self, permission: Permission) -> bool:
        """True when the account is active and its role grants *permission*."""
        if not self.active:
            return False
        return role_has_permission(self.role, permission)

    @property
    def report_physician_label(self) -> str:
        """Default physician string for report headers ('ФИО, должность' or 'ФИО')."""
        if self.title:
            return f"{self.display_name}, {self.title}"
        return self.display_name

    def find_public_key(self, key_id: str) -> SigningKeyPublic | ArchivedSigningKey | None:
        """Look up active or archived public signing key by ``key_id``."""
        if self.signing_key is not None and self.signing_key.key_id == key_id:
            return self.signing_key
        for archived in self.archived_keys:
            if archived.key_id == key_id:
                return archived
        return None


@dataclass(frozen=True)
class UserSession:
    """Current workstation authentication state."""

    user: UserProfile | None = None
    multi_user_enabled: bool = False
    locked: bool = False
    started_at: str = ""
    auto_lock_minutes: int = DEFAULT_AUTO_LOCK_MINUTES

    @property
    def authenticated(self) -> bool:
        """True when a specific local user is signed in and unlocked."""
        return self.multi_user_enabled and not self.locked and self.user is not None and self.user.active

    @property
    def active_user_id(self) -> str:
        """Opaque ID of the active unlocked user, or ``''`` in single-user/locked states."""
        if self.authenticated and self.user is not None:
            return self.user.user_id
        return ""

    def can(self, permission: Permission) -> bool:
        """Check whether the active workstation session may perform *permission*."""
        if not self.multi_user_enabled:
            return True
        if self.locked or self.user is None:
            return False
        return self.user.can(permission)
