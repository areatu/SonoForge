"""Security tests for local user crypto, repository and hash-chained audit (#623)."""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from echo_personal_tool.domain.exceptions import UserAuthError
from echo_personal_tool.domain.models.audit import AuditAction
from echo_personal_tool.domain.models.user import SecretKind, UserRole
from echo_personal_tool.infrastructure.audit_log import AuditLogError, LocalAuditLog
from echo_personal_tool.infrastructure.user_crypto import (
    generate_user_signing_key,
    hash_secret,
    reencrypt_signing_key,
    sign_with_user_key,
    verify_ed25519_signature,
    verify_secret,
)
from echo_personal_tool.infrastructure.user_repository import LocalUserRepository

# Lowest permitted power-of-two parameter for fast unit/security execution.
pytestmark = pytest.mark.security

FAST_N = 1 << 12


class TestUserCryptoSecurity:
    def test_password_and_pin_hash_verify_and_reject_wrong_secret(self) -> None:
        pwd_hash = hash_secret("Doctor-Secret-2026!", n=FAST_N)
        assert verify_secret("Doctor-Secret-2026!", pwd_hash)
        assert not verify_secret("Doctor-Secret-2026?", pwd_hash)
        assert not verify_secret("", pwd_hash)

        pin_hash = hash_secret("4821", n=FAST_N)
        assert verify_secret("4821", pin_hash)
        assert not verify_secret("4822", pin_hash)

    def test_rejects_excessive_scrypt_cost_parameters(self) -> None:
        record = hash_secret("safe-pass", n=FAST_N)
        forged = type(record)(
            kdf=record.kdf,
            n=1 << 22,
            r=record.r,
            p=record.p,
            salt_b64=record.salt_b64,
            digest_b64=record.digest_b64,
        )
        with pytest.raises(UserAuthError) as exc_info:
            verify_secret("safe-pass", forged)
        assert exc_info.value.code == "corrupt_store"

    def test_ed25519_wrap_aad_binding_sign_verify_and_reencrypt(self) -> None:
        uid = "0123456789abcdef0123456789abcdef"
        other_uid = "fedcba9876543210fedcba9876543210"
        pub, envelope = generate_user_signing_key(
            user_id=uid,
            secret="InitPass#1",
            created_at="2026-11-18T10:00:00+00:00",
            n=FAST_N,
        )

        payload = b'{"study_hash":"abc123","conclusion":"Normal LV systolic function"}'
        sig = sign_with_user_key(envelope, user_id=uid, secret="InitPass#1", payload=payload)
        assert verify_ed25519_signature(pub.public_key_b64, payload, sig)
        assert not verify_ed25519_signature(pub.public_key_b64, payload + b" ", sig)

        # Wrong password rejected.
        with pytest.raises(UserAuthError) as wrong_secret:
            sign_with_user_key(envelope, user_id=uid, secret="WrongPass#1", payload=payload)
        assert wrong_secret.value.code == "invalid_credentials"

        # AAD transplant attack (moving wrapped key blob onto another user_id) rejected!
        with pytest.raises(UserAuthError):
            sign_with_user_key(envelope, user_id=other_uid, secret="InitPass#1", payload=payload)

        # Self re-encryption preserves exact Ed25519 key_id + public key while invalidating old secret.
        reencrypted = reencrypt_signing_key(
            envelope,
            user_id=uid,
            old_secret="InitPass#1",
            new_secret="7391",
            n=FAST_N,
        )
        assert reencrypted.key_id == pub.key_id
        assert reencrypted.public_key_b64 == pub.public_key_b64
        with pytest.raises(UserAuthError):
            sign_with_user_key(reencrypted, user_id=uid, secret="InitPass#1", payload=payload)
        sig_after = sign_with_user_key(reencrypted, user_id=uid, secret="7391", payload=payload)
        assert verify_ed25519_signature(pub.public_key_b64, payload, sig_after)


class TestLocalUserRepositorySecurity:
    def test_no_plaintext_secret_stored_and_strict_file_mode(self, tmp_path: Path) -> None:
        repo = LocalUserRepository(tmp_path / "users", scrypt_n=FAST_N)
        secret = "UltraUniqueClinicianSecret!9472"
        admin = repo.create_user(
            username="ChiefDoc",
            display_name="Dr. Chief",
            role=UserRole.ADMIN,
            secret=secret,
            secret_kind=SecretKind.PASSWORD,
            title="Head of Echo Lab",
            enable_multi_user=True,
        )
        assert admin.username == "chiefdoc"
        raw = repo.path.read_text(encoding="utf-8")
        assert secret not in raw
        if sys.platform != "win32":
            assert (os.stat(repo.path).st_mode & 0o777) == 0o600

    def test_first_user_must_be_admin_and_usernames_are_unique(self, tmp_path: Path) -> None:
        repo = LocalUserRepository(tmp_path / "users", scrypt_n=FAST_N)
        with pytest.raises(UserAuthError) as non_admin:
            repo.create_user(
                username="doc1",
                display_name="Doc One",
                role=UserRole.PHYSICIAN,
                secret="DoctorPass1",
                secret_kind=SecretKind.PASSWORD,
            )
        assert non_admin.value.code == "first_user_must_be_admin"

        repo.create_user(
            username="admin1",
            display_name="Admin One",
            role=UserRole.ADMIN,
            secret="AdminPass1",
            secret_kind=SecretKind.PASSWORD,
        )
        with pytest.raises(UserAuthError) as dup:
            repo.create_user(
                username="ADMIN1",
                display_name="Admin Dup",
                role=UserRole.ADMIN,
                secret="AdminPass2",
                secret_kind=SecretKind.PASSWORD,
            )
        assert dup.value.code == "username_taken"

    def test_brute_force_lockout_and_recovery_with_controlled_clock(self, tmp_path: Path) -> None:
        repo = LocalUserRepository(tmp_path / "users", scrypt_n=FAST_N)
        repo.create_user(
            username="doc",
            display_name="Dr. Test",
            role=UserRole.ADMIN,
            secret="2580",
            secret_kind=SecretKind.PIN,
            enable_multi_user=True,
        )
        t0 = datetime(2026, 11, 18, 10, 0, 0, tzinfo=UTC)

        from echo_personal_tool.domain.models.user import LOCKOUT_BASE_SECONDS, LOCKOUT_FREE_ATTEMPTS

        # First LOCKOUT_FREE_ATTEMPTS - 1 wrong attempts stay below lockout threshold; next triggers lockout.
        for _ in range(LOCKOUT_FREE_ATTEMPTS - 1):
            with pytest.raises(UserAuthError) as err:
                repo.authenticate("doc", "0000", now=t0)
            assert err.value.code == "invalid_credentials"

        with pytest.raises(UserAuthError) as locked_err:
            repo.authenticate("doc", "0000", now=t0)
        assert locked_err.value.code == "account_locked"
        assert locked_err.value.retry_after_seconds == LOCKOUT_BASE_SECONDS

        # Even the correct PIN is rejected while the lockout window is active.
        with pytest.raises(UserAuthError) as still_locked:
            repo.authenticate("doc", "2580", now=t0 + timedelta(seconds=5))
        assert still_locked.value.code == "account_locked"
        assert still_locked.value.retry_after_seconds == LOCKOUT_BASE_SECONDS - 5

        # Once the cooldown expires, valid PIN succeeds and resets lockout.
        profile = repo.authenticate("doc", "2580", now=t0 + timedelta(seconds=LOCKOUT_BASE_SECONDS + 1))
        assert profile.username == "doc"

    def test_last_admin_guard_and_key_rotation_on_admin_reset(self, tmp_path: Path) -> None:
        repo = LocalUserRepository(tmp_path / "users", scrypt_n=FAST_N)
        admin = repo.create_user(
            username="admin",
            display_name="Admin",
            role=UserRole.ADMIN,
            secret="AdminPass1",
            secret_kind=SecretKind.PASSWORD,
            enable_multi_user=True,
        )
        with pytest.raises(UserAuthError) as last_deact:
            repo.set_user_active(admin.user_id, active=False)
        assert last_deact.value.code == "last_admin"

        with pytest.raises(UserAuthError) as last_demote:
            repo.update_user(
                admin.user_id,
                display_name="Admin",
                title="",
                external_id="",
                role=UserRole.PHYSICIAN,
            )
        assert last_demote.value.code == "last_admin"

        doc = repo.create_user(
            username="petrov",
            display_name="Dr. Petrov",
            role=UserRole.PHYSICIAN,
            secret="1357",
            secret_kind=SecretKind.PIN,
        )
        assert doc.signing_key is not None
        original_key_id = doc.signing_key.key_id
        report_digest = b"sha256:signed-echo-report-v1"
        env_v1 = repo.get_signing_envelope(doc.user_id)
        sig_v1 = sign_with_user_key(env_v1, user_id=doc.user_id, secret="1357", payload=report_digest)

        # Admin resets forgotten PIN -> rotates Ed25519 key and archives previous public key.
        rotated, retired_key_id = repo.admin_reset_secret(
            doc.user_id, new_secret="NewPassword#9", new_kind=SecretKind.PASSWORD
        )
        assert retired_key_id == original_key_id
        assert rotated.signing_key is not None
        assert rotated.signing_key.key_id != original_key_id
        archived = rotated.find_public_key(original_key_id)
        assert archived is not None

        # Historical signature STILL verifies against archived public key!
        assert verify_ed25519_signature(archived.public_key_b64, report_digest, sig_v1)

        # New signature uses the rotated active key.
        env_v2 = repo.get_signing_envelope(doc.user_id)
        sig_v2 = sign_with_user_key(env_v2, user_id=doc.user_id, secret="NewPassword#9", payload=report_digest)
        assert verify_ed25519_signature(rotated.signing_key.public_key_b64, report_digest, sig_v2)

    def test_corrupt_store_fails_closed(self, tmp_path: Path) -> None:
        repo = LocalUserRepository(tmp_path / "users", scrypt_n=FAST_N)
        repo.path.parent.mkdir(parents=True, exist_ok=True)
        repo.path.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(UserAuthError) as err:
            repo.load_state()
        assert err.value.code == "corrupt_store"


class TestAuditLogTamperDetection:
    def test_hash_chain_detects_edit_deletion_and_truncation(self, tmp_path: Path) -> None:
        log = LocalAuditLog(tmp_path / "users")
        assert log.verify().valid

        e1 = log.append(action=AuditAction.MULTI_USER_ENABLED, actor_id="a" * 32, details={"role": "admin"})
        e2 = log.append(action=AuditAction.LOGIN_SUCCESS, actor_id="a" * 32, details={"secret_kind": "pin"})
        e3 = log.append(
            action=AuditAction.STUDY_SAVED,
            actor_id="a" * 32,
            study_key="b" * 64,
            details={"revision": 1},
        )
        assert e1 is not None and e2 is not None and e3 is not None
        assert (e1.seq, e2.seq, e3.seq) == (1, 2, 3)
        ver = log.verify()
        assert ver.valid and ver.checked_count == 3

        export_dir = tmp_path / "export-dir"
        export_dir.mkdir()
        exported = export_dir / "audit.jsonl"
        assert log.export_copy(exported) == 3
        assert LocalAuditLog(export_dir).verify().valid

        if sys.platform != "win32":
            assert (os.stat(log.path).st_mode & 0o777) == 0o600

        # Tamper 1: modify a field inside entry #2 without updating hashes.
        lines = log.path.read_text(encoding="utf-8").splitlines()
        mutated = json.loads(lines[1])
        mutated["details"]["secret_kind"] = "password"
        edit_dir = tmp_path / "tampered-edit"
        edit_dir.mkdir()
        (edit_dir / "audit.jsonl").write_text(
            "\n".join([lines[0], json.dumps(mutated), lines[2]]) + "\n",
            encoding="utf-8",
        )
        res_edit = LocalAuditLog(edit_dir).verify()
        assert not res_edit.valid
        assert res_edit.first_broken_seq == 2
        assert res_edit.reason == "hash_mismatch"

        # Tamper 2: delete middle line #2.
        gap_dir = tmp_path / "tampered-gap"
        gap_dir.mkdir()
        (gap_dir / "audit.jsonl").write_text("\n".join([lines[0], lines[2]]) + "\n", encoding="utf-8")
        res_gap = LocalAuditLog(gap_dir).verify()
        assert not res_gap.valid
        assert res_gap.first_broken_seq == 2
        assert res_gap.reason == "sequence_gap"

        # Tamper 3: append refuses to extend a corrupted tail.
        tail_dir = tmp_path / "tampered-tail"
        tail_dir.mkdir()
        (tail_dir / "audit.jsonl").write_text(lines[0] + "\n{truncated", encoding="utf-8")
        assert not LocalAuditLog(tail_dir).verify().valid
        with pytest.raises(AuditLogError):
            LocalAuditLog(tail_dir).append(action=AuditAction.LOGOUT, actor_id="a" * 32)

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlink refusal test")
    def test_symlinked_user_store_and_audit_log_are_refused(self, tmp_path: Path) -> None:
        outside_json = tmp_path / "outside-users.json"
        outside_json.write_text("{}", encoding="utf-8")
        users_dir = tmp_path / "users"
        users_dir.mkdir()
        (users_dir / "users.json").symlink_to(outside_json)

        repo = LocalUserRepository(users_dir, scrypt_n=FAST_N)
        with pytest.raises(UserAuthError):
            repo.load_state()
        with pytest.raises(UserAuthError):
            repo.create_user(
                username="admin",
                display_name="Admin",
                role=UserRole.ADMIN,
                secret="AdminPass1",
                secret_kind=SecretKind.PASSWORD,
            )

        audit_dir = tmp_path / "audit-root"
        audit_dir.mkdir()
        outside_log = tmp_path / "outside-audit.jsonl"
        outside_log.write_text("", encoding="utf-8")
        (audit_dir / "audit.jsonl").symlink_to(outside_log)
        audit = LocalAuditLog(audit_dir)
        with pytest.raises(AuditLogError) as app_err:
            audit.append(action=AuditAction.LOGOUT, actor_id="a" * 32)
        assert app_err.value.code == "unsafe_path"
        with pytest.raises(AuditLogError) as ver_err:
            audit.verify()
        assert ver_err.value.code == "unsafe_path"
