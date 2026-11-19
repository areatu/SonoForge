"""Pure-stdlib unit tests for local user, RBAC, lockout and audit models (#623)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from echo_personal_tool.domain.exceptions import UserAuthError
from echo_personal_tool.domain.models.audit import (
    GENESIS_HASH,
    AuditAction,
    AuditEntry,
    AuditVerificationResult,
    build_audit_entry,
    verify_audit_chain,
)
from echo_personal_tool.domain.models.user import (
    DEFAULT_AUTO_LOCK_MINUTES,
    LOCKOUT_MAX_SECONDS,
    MAX_AUTO_LOCK_MINUTES,
    ROLE_PERMISSIONS,
    ArchivedSigningKey,
    Permission,
    SecretKind,
    SigningKeyPublic,
    UserProfile,
    UserRole,
    UserSession,
    clamp_auto_lock_minutes,
    compute_locked_until,
    format_key_fingerprint,
    is_valid_user_id,
    lockout_duration_seconds,
    normalize_username,
    remaining_lockout_seconds,
    role_has_permission,
    validate_display_name,
    validate_external_id,
    validate_secret,
    validate_title,
    validate_username,
)


def _sample_key(char: str = "a") -> SigningKeyPublic:
    return SigningKeyPublic(
        key_id=char * 16,
        algorithm="Ed25519",
        public_key_b64="MCowBQYDK2VwAyEA" + "A" * 28,
        created_at="2026-11-18T10:00:00+00:00",
    )


def _sample_user(
    *,
    role: UserRole = UserRole.PHYSICIAN,
    active: bool = True,
    title: str = "Cardiologist",
    archived: tuple[ArchivedSigningKey, ...] = (),
) -> UserProfile:
    return UserProfile(
        user_id="0123456789abcdef0123456789abcdef",
        username="ivanov",
        display_name="Dr. Ivanov",
        role=role,
        secret_kind=SecretKind.PIN,
        title=title,
        external_id="DOC-42",
        active=active,
        created_at="2026-11-18T10:00:00+00:00",
        updated_at="2026-11-18T10:00:00+00:00",
        signing_key=_sample_key(),
        archived_keys=archived,
    )


class TestRolePermissions:
    def test_admin_holds_every_permission(self) -> None:
        assert ROLE_PERMISSIONS[UserRole.ADMIN] == frozenset(Permission)
        for perm in Permission:
            assert role_has_permission(UserRole.ADMIN, perm)

    def test_physician_clinical_permissions(self) -> None:
        perms = ROLE_PERMISSIONS[UserRole.PHYSICIAN]
        assert Permission.VIEW_STUDY in perms
        assert Permission.EDIT_MEASUREMENTS in perms
        assert Permission.DELETE_MEASUREMENTS in perms
        assert Permission.EDIT_REPORT in perms
        assert Permission.SIGN_REPORT in perms
        assert Permission.EXPORT_DATA in perms
        assert Permission.MANAGE_USERS not in perms
        assert Permission.VIEW_AUDIT not in perms
        assert Permission.CONFIGURE_SERVERS not in perms

    def test_operator_cannot_sign_or_delete(self) -> None:
        perms = ROLE_PERMISSIONS[UserRole.OPERATOR]
        assert Permission.VIEW_STUDY in perms
        assert Permission.EDIT_MEASUREMENTS in perms
        assert Permission.EDIT_REPORT in perms
        assert Permission.EXPORT_DATA in perms
        assert Permission.SIGN_REPORT not in perms
        assert Permission.DELETE_MEASUREMENTS not in perms
        assert Permission.MANAGE_USERS not in perms

    def test_viewer_is_strictly_read_only(self) -> None:
        assert ROLE_PERMISSIONS[UserRole.VIEWER] == frozenset({Permission.VIEW_STUDY})

    def test_inactive_profile_has_zero_permissions(self) -> None:
        inactive_admin = _sample_user(role=UserRole.ADMIN, active=False)
        for perm in Permission:
            assert not inactive_admin.can(perm)


class TestSessions:
    def test_single_user_session_grants_all_without_active_user_id(self) -> None:
        session = UserSession()
        assert not session.multi_user_enabled
        assert not session.authenticated
        assert session.active_user_id == ""
        for perm in Permission:
            assert session.can(perm)

    def test_locked_multi_user_session_blocks_everything(self) -> None:
        admin = _sample_user(role=UserRole.ADMIN)
        locked = UserSession(multi_user_enabled=True, user=admin, locked=True)
        assert not locked.authenticated
        assert locked.active_user_id == ""
        for perm in Permission:
            assert not locked.can(perm)

    def test_active_multi_user_session_delegates_to_user_role(self) -> None:
        doc = _sample_user(role=UserRole.PHYSICIAN)
        session = UserSession(multi_user_enabled=True, user=doc, locked=False)
        assert session.authenticated
        assert session.active_user_id == doc.user_id
        assert session.can(Permission.SIGN_REPORT)
        assert not session.can(Permission.MANAGE_USERS)


class TestValidationAndLockout:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Ivanov", "ivanov"),
            ("  dr.petrov_01 ", "dr.petrov_01"),
            ("a-b", "a-b"),
            ("admin", "admin"),
        ],
    )
    def test_valid_usernames(self, raw: str, expected: str) -> None:
        assert normalize_username(raw) == expected
        assert validate_username(raw) == expected

    @pytest.mark.parametrize(
        "bad",
        ["", "a", ".dot", "-dash", "user name", "../etc", "иванов", "system", "anonymous", "x" * 33],
    )
    def test_invalid_usernames_rejected(self, bad: str) -> None:
        with pytest.raises(UserAuthError) as exc_info:
            validate_username(bad)
        assert exc_info.value.code == "invalid_username"

    @pytest.mark.parametrize("pin", ["0000", "4821", "12345678"])
    def test_valid_pins(self, pin: str) -> None:
        validate_secret(pin, SecretKind.PIN)
        assert pin.isascii() and pin.isdigit()

    @pytest.mark.parametrize("bad_pin", ["", "123", "123456789", "12a4", "12 34", "١٢٣٤"])
    def test_invalid_pins(self, bad_pin: str) -> None:
        with pytest.raises(UserAuthError) as exc_info:
            validate_secret(bad_pin, SecretKind.PIN)
        assert exc_info.value.code == "invalid_pin"

    @pytest.mark.parametrize("pwd", ["secret", "Correct-Horse-99!", "парольВрача2026"])
    def test_valid_passwords(self, pwd: str) -> None:
        validate_secret(pwd, SecretKind.PASSWORD)
        assert len(pwd) >= 6

    @pytest.mark.parametrize("bad_pwd", ["", "12345", "a" * 129, "bad\x00pwd", "line\nbreak"])
    def test_invalid_passwords(self, bad_pwd: str) -> None:
        with pytest.raises(UserAuthError) as exc_info:
            validate_secret(bad_pwd, SecretKind.PASSWORD)
        assert exc_info.value.code == "invalid_password"

    def test_profile_field_validators_and_key_lookup(self) -> None:
        assert validate_display_name("  Иванов И.И. ") == "Иванов И.И."
        assert validate_title("  Врач УЗД ") == "Врач УЗД"
        assert validate_external_id("  PRAC-001 ") == "PRAC-001"
        assert is_valid_user_id("ab" * 16)
        assert not is_valid_user_id("not-hex")
        assert clamp_auto_lock_minutes(DEFAULT_AUTO_LOCK_MINUTES) == DEFAULT_AUTO_LOCK_MINUTES
        assert clamp_auto_lock_minutes(-5) == 0
        assert clamp_auto_lock_minutes(9999) == MAX_AUTO_LOCK_MINUTES
        with pytest.raises(UserAuthError):
            validate_display_name("   ")

        arch = ArchivedSigningKey(
            key_id="b" * 16,
            algorithm="Ed25519",
            public_key_b64="MCowBQYDK2VwAyEA" + "B" * 28,
            created_at="2026-10-01T00:00:00+00:00",
            retired_at="2026-11-01T00:00:00+00:00",
            reason="admin_reset",
        )
        doc = _sample_user(archived=(arch,))
        assert doc.report_physician_label == "Dr. Ivanov, Cardiologist"
        assert doc.find_public_key("a" * 16) is doc.signing_key
        assert doc.find_public_key("b" * 16) is arch
        assert doc.find_public_key("c" * 16) is None
        assert format_key_fingerprint("f" * 16) == "FFFF-FFFF-FFFF-FFFF"
        assert _sample_key("f").formatted_fingerprint == "FFFF-FFFF-FFFF-FFFF"
        assert arch.formatted_fingerprint == "BBBB-BBBB-BBBB-BBBB"

    def test_exponential_lockout_backoff_and_remaining(self) -> None:
        from echo_personal_tool.domain.models.user import LOCKOUT_BASE_SECONDS, LOCKOUT_FREE_ATTEMPTS

        for free in range(LOCKOUT_FREE_ATTEMPTS):
            assert lockout_duration_seconds(free) == 0
        assert lockout_duration_seconds(LOCKOUT_FREE_ATTEMPTS) == LOCKOUT_BASE_SECONDS
        assert lockout_duration_seconds(LOCKOUT_FREE_ATTEMPTS + 1) == LOCKOUT_BASE_SECONDS * 2
        assert lockout_duration_seconds(LOCKOUT_FREE_ATTEMPTS + 2) == LOCKOUT_BASE_SECONDS * 4
        assert lockout_duration_seconds(50) == LOCKOUT_MAX_SECONDS

        t0 = datetime(2026, 11, 18, 12, 0, 0, tzinfo=UTC)
        until = compute_locked_until(LOCKOUT_FREE_ATTEMPTS, now=t0)
        assert remaining_lockout_seconds(until, now=t0 + timedelta(seconds=5)) == LOCKOUT_BASE_SECONDS - 5
        assert remaining_lockout_seconds(until, now=t0 + timedelta(seconds=LOCKOUT_BASE_SECONDS + 1)) == 0
        assert remaining_lockout_seconds("", now=t0) == 0


class TestAuditChainModel:
    def test_chained_entries_verify_and_detect_mutation(self) -> None:
        with pytest.raises(ValueError, match="disallowed audit detail key"):
            build_audit_entry(
                seq=1,
                timestamp="2026-11-18T10:00:00+00:00",
                action=AuditAction.MULTI_USER_ENABLED,
                actor_id="0123456789abcdef0123456789abcdef",
                prev_hash=GENESIS_HASH,
                details={"patient_name": "MUST_BE_REJECTED"},
            )

        with pytest.raises(ValueError, match="invalid audit detail value"):
            build_audit_entry(
                seq=1,
                timestamp="2026-11-18T10:00:00+00:00",
                action=AuditAction.MULTI_USER_ENABLED,
                actor_id="0123456789abcdef0123456789abcdef",
                prev_hash=GENESIS_HASH,
                details={"reason": "line1\nline2"},
            )

        first = build_audit_entry(
            seq=1,
            timestamp="2026-11-18T10:00:00+00:00",
            action=AuditAction.MULTI_USER_ENABLED,
            actor_id="0123456789abcdef0123456789abcdef",
            prev_hash=GENESIS_HASH,
            details={"role": "admin", "reason": "  bootstrap  "},
        )
        assert first.entry_hash == first.expected_hash()
        assert dict(first.details)["reason"] == "bootstrap"

        second = build_audit_entry(
            seq=2,
            timestamp="2026-11-18T10:05:00+00:00",
            action=AuditAction.STUDY_SAVED,
            actor_id="0123456789abcdef0123456789abcdef",
            study_key="a" * 64,
            prev_hash=first.entry_hash,
            details={"revision": 1},
        )
        chain_ok = verify_audit_chain((first, second))
        assert isinstance(chain_ok, AuditVerificationResult)
        assert chain_ok.valid and chain_ok.checked_count == 2

        forged = AuditEntry(
            seq=second.seq,
            timestamp=second.timestamp,
            action=second.action,
            actor_id=second.actor_id,
            target_id=second.target_id,
            study_key=second.study_key,
            details=(("revision", 99),),
            prev_hash=second.prev_hash,
            entry_hash=second.entry_hash,
        )
        broken = verify_audit_chain((first, forged))
        assert not broken.valid
        assert broken.first_broken_seq == 2
        assert broken.reason == "hash_mismatch"
