"""Integration tests for UserSessionService, profile isolation and study authors (#623)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from echo_personal_tool.application.measurement_persistence import MeasurementPersistence
from echo_personal_tool.application.saved_records import (
    filter_saved_records,
    read_saved_records,
)
from echo_personal_tool.application.study_measurement_session import (
    StudyMeasurementData,
    StudyMeasurementSessionStore,
)
from echo_personal_tool.application.user_session import UserSessionService
from echo_personal_tool.domain.exceptions import UserAuthError
from echo_personal_tool.domain.models import InstanceMetadata, SeriesMetadata, StudyMetadata
from echo_personal_tool.domain.models.audit import AuditAction
from echo_personal_tool.domain.models.user import Permission, SecretKind, UserRole
from echo_personal_tool.infrastructure import paths as infra_paths
from echo_personal_tool.infrastructure import user_preferences as infra_prefs
from echo_personal_tool.infrastructure.measurement_codec import study_key
from echo_personal_tool.infrastructure.measurement_repository import MeasurementRepository
from echo_personal_tool.infrastructure.recent_store import RecentStore
from echo_personal_tool.infrastructure.report_phrase_store import PhraseStore

FAST_N = 1 << 12


@pytest.fixture
def isolated_user_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Isolate config/data directories and global profile scoping to ``tmp_path``."""
    data_root = tmp_path / "data"
    config_root = tmp_path / "config"
    data_root.mkdir()
    config_root.mkdir()
    monkeypatch.setattr(infra_paths, "data_dir", lambda: data_root)
    single_ini = config_root / "single_preferences.ini"
    orig_store = infra_prefs._settings_store

    def _scoped_store():
        from PySide6.QtCore import QSettings

        if infra_paths.active_user_preferences_ini() is not None:
            return orig_store()
        return QSettings(str(single_ini), QSettings.Format.IniFormat)

    monkeypatch.setattr(infra_prefs, "_settings_store", _scoped_store)
    infra_paths.set_active_user_profile(None)
    yield tmp_path
    infra_paths.set_active_user_profile(None)


def _add_phrase(text: str) -> None:
    PhraseStore().add("summary", text, text)


def _phrase_texts() -> tuple[str, ...]:
    return tuple(p.ru for p in PhraseStore().phrases())


def _make_service(root: Path, *, scope_paths: bool = True) -> UserSessionService:
    users_dir = root / "data" / "users"
    return UserSessionService(users_dir, scrypt_n=FAST_N, scope_paths=scope_paths)


class TestUserSessionLifecycleAndIsolation:
    def test_single_user_default_has_zero_friction(self, isolated_user_env: Path) -> None:
        svc = _make_service(isolated_user_env)
        assert not svc.is_multi_user_enabled()
        assert not svc.has_users()
        assert not svc.is_locked()
        assert svc.active_user_id == ""
        assert svc.default_report_physician() == ""
        for perm in Permission:
            assert svc.can(perm)

    def test_per_user_preferences_phrases_and_recents_are_isolated(self, isolated_user_env: Path) -> None:
        shared = infra_prefs.load_user_preferences()
        shared.report_institution = "City Cardiology Center"
        shared.theme_mode = "dark"
        infra_prefs.save_user_preferences(shared)
        _add_phrase("Single-user baseline phrase")

        svc = _make_service(isolated_user_env)
        admin_session = svc.bootstrap_first_admin(
            username="ivanov",
            display_name="Иванов И.И.",
            secret="AdminPass#1",
            secret_kind=SecretKind.PASSWORD,
            title="Зав. отделением УЗД",
            base_preferences=shared,
        )
        assert svc.is_multi_user_enabled()
        assert admin_session.user is not None
        assert svc.default_report_physician() == "Иванов И.И., Зав. отделением УЗД"

        ivanov_prefs = infra_prefs.load_user_preferences()
        assert ivanov_prefs.report_institution == "City Cardiology Center"
        ivanov_prefs.theme_mode = "light"
        ivanov_prefs.ui_font_size = 15
        ivanov_prefs.report_physician = "д.м.н. Иванов И.И."
        infra_prefs.save_user_preferences(ivanov_prefs)
        _add_phrase("ФВ ЛЖ сохранена (шаблон Иванова)")

        folder_a = isolated_user_env / "study_ivanov"
        folder_a.mkdir()
        RecentStore().record(folder_a)

        # Also verify a single long-lived PhraseStore and RecentStore track live switches.
        live_phrases = PhraseStore()
        live_recents = RecentStore()
        assert tuple(p.ru for p in live_phrases.phrases()) == ("ФВ ЛЖ сохранена (шаблон Иванова)",)
        assert live_recents.paths() == [str(folder_a)]

        # Set a custom report template for Ivanov and confirm Petrov does not inherit it.
        ivanov_prefs.report_template_json = '{"schema_version":1,"profile_id":"adult_tte","title":"Ivanov"}'
        infra_prefs.save_user_preferences(ivanov_prefs)

        # Create Dr. Petrov (PIN login) and switch into his session.
        petrov = svc.create_user(
            username="petrov",
            display_name="Петров П.П.",
            role=UserRole.PHYSICIAN,
            secret="4821",
            secret_kind=SecretKind.PIN,
            title="Врач УЗД",
            base_preferences=shared,
        )
        svc.login("petrov", "4821")
        assert svc.active_user_id == petrov.user_id
        assert svc.default_report_physician() == "Петров П.П., Врач УЗД"

        petrov_prefs = infra_prefs.load_user_preferences()
        assert petrov_prefs.report_institution == "City Cardiology Center"
        assert petrov_prefs.theme_mode == "dark"  # NOT Ivanov's "light"
        assert petrov_prefs.report_physician == "Петров П.П., Врач УЗД"  # NOT Ivanov's physician line
        assert petrov_prefs.report_template_json == ""  # NOT Ivanov's report template
        assert tuple(p.ru for p in live_phrases.phrases()) == ()
        assert live_recents.paths() == []

        petrov_prefs.theme_mode = "graphite"
        petrov_prefs.ui_font_size = 13
        petrov_prefs.report_template_json = '{"schema_version":1,"profile_id":"vascular","title":"Petrov"}'
        infra_prefs.save_user_preferences(petrov_prefs)
        live_phrases.add("summary", "Камеры сердца не расширены (шаблон Петрова)", "Normal chambers")
        folder_b = isolated_user_env / "study_petrov"
        folder_b.mkdir()
        live_recents.record(folder_b)

        # Non-admin cannot disable multi-user.
        with pytest.raises(UserAuthError) as non_admin_dis:
            svc.disable_multi_user("4821")
        assert non_admin_dis.value.code == "permission_denied"

        # Switch back to Ivanov: his exact settings, template, phrases and recents return!
        svc.login("ivanov", "AdminPass#1")
        reloaded_ivanov = infra_prefs.load_user_preferences()
        assert reloaded_ivanov.theme_mode == "light"
        assert reloaded_ivanov.ui_font_size == 15
        assert reloaded_ivanov.report_physician == "д.м.н. Иванов И.И."
        assert "Ivanov" in reloaded_ivanov.report_template_json
        assert tuple(p.ru for p in live_phrases.phrases()) == ("ФВ ЛЖ сохранена (шаблон Иванова)",)
        assert live_recents.paths() == [str(folder_a)]

        # Wrong admin password cannot disable multi-user.
        with pytest.raises(UserAuthError) as bad_dis:
            svc.disable_multi_user("WrongPass#9")
        assert bad_dis.value.code == "invalid_credentials"
        assert svc.is_multi_user_enabled()

        # Disable multi-user -> returns to original single-user profile while preserving accounts.
        svc.disable_multi_user("AdminPass#1")
        assert not svc.is_multi_user_enabled()
        assert svc.has_users()
        assert infra_prefs.load_user_preferences().theme_mode == "dark"
        assert tuple(p.ru for p in live_phrases.phrases()) == ("Single-user baseline phrase",)

        # Re-enable multi-user: non-admin rejected, existing admin succeeds and restores scope!
        with pytest.raises(UserAuthError):
            svc.enable_multi_user("petrov", "4821")
        assert not svc.is_multi_user_enabled()
        svc.enable_multi_user("ivanov", "AdminPass#1")
        assert svc.is_multi_user_enabled()
        assert svc.active_user_id == admin_session.user.user_id
        assert infra_prefs.load_user_preferences().theme_mode == "light"

        # Logout leaves workstation locked and resets path scope to unauthenticated state.
        svc.logout()
        assert svc.is_locked()
        assert svc.current_user is None
        assert not svc.can(Permission.VIEW_STUDY)

        # Re-enable with existing admin account -> Ivanov's personal profile still intact!
        svc.enable_multi_user("ivanov", "AdminPass#1")
        assert svc.is_multi_user_enabled()
        assert infra_prefs.load_user_preferences().theme_mode == "light"

    def test_lock_unlock_rbac_signing_and_audit_chain(self, isolated_user_env: Path) -> None:
        svc = _make_service(isolated_user_env)
        svc.bootstrap_first_admin(
            username="admin",
            display_name="Admin Doc",
            secret="AdminPass#1",
            secret_kind=SecretKind.PASSWORD,
        )
        svc.set_auto_lock_minutes(10)
        assert svc.auto_lock_minutes() == 10

        operator = svc.create_user(
            username="nurse",
            display_name="Operator Sidorova",
            role=UserRole.OPERATOR,
            secret="1955",
            secret_kind=SecretKind.PIN,
        )
        viewer = svc.create_user(
            username="intern",
            display_name="Intern",
            role=UserRole.VIEWER,
            secret="InternPass1",
            secret_kind=SecretKind.PASSWORD,
        )
        assert operator.role is UserRole.OPERATOR
        assert viewer.role is UserRole.VIEWER

        # Admin locks workstation -> zero permissions until unlocked.
        svc.lock_session(reason="inactivity")
        assert svc.is_locked()
        assert not svc.can(Permission.VIEW_STUDY)
        with pytest.raises(UserAuthError):
            svc.unlock_session("wrong")
        assert svc.is_locked()
        svc.unlock_session("AdminPass#1")
        assert not svc.is_locked()
        assert svc.can(Permission.MANAGE_USERS)

        # Admin changes own password -> PIN; Ed25519 signing still works seamlessly.
        svc.change_own_secret(old_secret="AdminPass#1", new_secret="9042", new_kind=SecretKind.PIN)
        key_meta, sig = svc.sign_payload(secret="9042", payload=b"canonical-report-bytes")
        assert svc.verify_user_signature(
            user_id=svc.active_user_id,
            key_id=key_meta.key_id,
            payload=b"canonical-report-bytes",
            signature=sig,
        )

        # Operator cannot sign reports, manage users, deactivate accounts, or read audit trail.
        svc.login("nurse", "1955")
        assert svc.can(Permission.EDIT_MEASUREMENTS)
        assert not svc.can(Permission.DELETE_MEASUREMENTS)
        assert not svc.can(Permission.SIGN_REPORT)
        with pytest.raises(UserAuthError) as sign_denied:
            svc.sign_payload(secret="1955", payload=b"canonical-report-bytes")
        assert sign_denied.value.code == "permission_denied"
        with pytest.raises(UserAuthError) as audit_denied:
            svc.recent_audit_entries()
        assert audit_denied.value.code == "permission_denied"

        # Switch back to admin, test user update + deactivation/reactivation + admin reset, verify audit.
        svc.login("admin", "9042")
        updated = svc.update_user(
            viewer.user_id,
            display_name="Dr. Intern",
            title="Resident",
            external_id="EXT-42",
            role=UserRole.VIEWER,
        )
        assert updated.display_name == "Dr. Intern"
        deactivated = svc.set_user_active(viewer.user_id, active=False)
        assert not deactivated.active
        # Deactivated user cannot log in even with valid password!
        with pytest.raises(UserAuthError) as disabled_err:
            svc.login("intern", "InternPass1")
        assert disabled_err.value.code == "account_disabled"
        # Unknown user fails cleanly through dummy scrypt verification.
        with pytest.raises(UserAuthError) as unknown_err:
            svc.login("ghost.user", "SomePassword1")
        assert unknown_err.value.code == "invalid_credentials"
        # Signed-in admin cannot deactivate themselves even when a second admin exists!
        second_admin = svc.create_user(
            username="admin2",
            display_name="Second Admin",
            role=UserRole.ADMIN,
            secret="SecondAdm#1",
            secret_kind=SecretKind.PASSWORD,
        )
        assert second_admin.role is UserRole.ADMIN
        with pytest.raises(UserAuthError) as self_deact:
            svc.set_user_active(svc.active_user_id, active=False)
        assert self_deact.value.code == "cannot_deactivate_self"
        reactivated = svc.set_user_active(viewer.user_id, active=True)
        assert reactivated.active
        reset_op = svc.admin_reset_secret(operator.user_id, new_secret="7788", new_kind=SecretKind.PIN)
        assert len(reset_op.archived_keys) == 1

        verification = svc.verify_audit_log()
        assert verification.valid
        assert verification.checked_count >= 12
        actions = [e.action for e in svc.recent_audit_entries(limit=50)]
        assert AuditAction.SESSION_LOCKED.value in actions
        assert AuditAction.SESSION_UNLOCKED.value in actions
        assert AuditAction.LOGIN_FAILED.value in actions
        assert AuditAction.SECRET_CHANGED.value in actions
        assert AuditAction.SECRET_RESET.value in actions
        assert AuditAction.SESSION_SWITCHED.value in actions

    def test_corrupt_store_on_startup_fails_closed(self, isolated_user_env: Path) -> None:
        users_dir = isolated_user_env / "data" / "users"
        users_dir.mkdir(parents=True)
        (users_dir / "users.json").write_text("{corrupt", encoding="utf-8")
        svc = UserSessionService(users_dir, scope_paths=False)
        assert svc.is_multi_user_enabled()
        assert svc.is_locked()
        assert not svc.can(Permission.EDIT_MEASUREMENTS)
        assert not svc.can(Permission.DELETE_MEASUREMENTS)


class TestSharedCabinetStudyAuthorsAndRbac:
    def test_repository_preserves_created_by_and_filters_mine_vs_all(self, tmp_path: Path) -> None:
        meas_dir = tmp_path / "measurements"
        repo = MeasurementRepository(meas_dir)
        sources = {"1.2.3.1": {"fingerprint": "a" * 64, "frames": 1, "spacing": None}}

        ivanov_id = "11" * 16
        petrov_id = "22" * 16
        sidorov_id = "33" * 16

        # Legacy single-user study: created_by and updated_by omitted completely on disk.
        uid_legacy = "1.2.840.10008.1"
        repo.save(uid_legacy, StudyMeasurementData(height_cm=170.0, height_source="manual"), sources, 0)
        legacy_json = json.loads((meas_dir / f"{study_key(uid_legacy)}.json").read_text("utf-8"))
        assert "created_by" not in legacy_json
        assert "updated_by" not in legacy_json

        # Study A: created by Dr. Ivanov, then revised by Dr. Petrov.
        uid_shared = "1.2.840.10008.2"
        r1 = repo.save(
            uid_shared,
            StudyMeasurementData(height_cm=175.0, height_source="manual"),
            sources,
            0,
            author_id=ivanov_id,
        )
        assert r1["created_by"] == ivanov_id
        assert r1["updated_by"] == ivanov_id
        r2 = repo.save(
            uid_shared,
            StudyMeasurementData(height_cm=175.0, height_source="manual", weight_kg=80.0, weight_source="manual"),
            sources,
            1,
            author_id=petrov_id,
        )
        assert r2["created_by"] == ivanov_id  # original author preserved!
        assert r2["updated_by"] == petrov_id

        # Study B: created solely by Dr. Petrov.
        uid_petrov = "1.2.840.10008.3"
        repo.save(
            uid_petrov,
            StudyMeasurementData(height_cm=162.0, height_source="manual"),
            sources,
            0,
            author_id=petrov_id,
        )

        listing = read_saved_records(repo)
        assert not listing.failed
        assert len(listing.records) == 3

        assert len(filter_saved_records(listing.records, scope="all", user_id=ivanov_id)) == 3
        mine_ivanov = filter_saved_records(listing.records, scope="mine", user_id=ivanov_id)
        assert [rec.key for rec in mine_ivanov] == [study_key(uid_shared)]

        mine_petrov = filter_saved_records(listing.records, scope="mine", user_id=petrov_id)
        assert {rec.key for rec in mine_petrov} == {study_key(uid_shared), study_key(uid_petrov)}

        mine_sidorov = filter_saved_records(listing.records, scope="mine", user_id=sidorov_id)
        assert mine_sidorov == ()

    def test_measurement_persistence_stamps_author_enforces_rbac_and_audits(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qapp
    ) -> None:
        # Use the shared QApplication fixture: creating a bare QCoreApplication
        # here would poison QApplication.instance() for every later test in
        # this xdist worker (no styleSheet(), breaking GUI hygiene fixtures).
        app = qapp

        dcm = tmp_path / "clip.dcm"
        dcm.write_bytes(b"synthetic-dicom-bytes")
        uid = "1.2.840.99999.42"
        sop = "1.2.840.99999.42.1"
        monkeypatch.setattr(
            "echo_personal_tool.application.measurement_persistence.describe_study",
            lambda _study: {sop: {"fingerprint": "a" * 64, "frames": 1, "spacing": [0.5, 0.5]}},
        )
        inst = InstanceMetadata(
            sop_instance_uid="1.2.840.99999.42.1",
            series_uid="1.2.840.99999.42.2",
            modality="US",
            number_of_frames=1,
            pixel_spacing=None,
            frame_time_ms=None,
            series_description="Echo",
            path=dcm,
            media_format="dicom",
            patient_surname="SECRET_PATIENT_PHI",
            patient_id="PHI_MRN_999",
        )
        series = SeriesMetadata(
            series_uid="1.2.840.99999.42.2",
            study_uid=uid,
            modality="US",
            description="Echo",
            instances=[inst],
        )
        study = StudyMetadata(
            study_uid=uid,
            study_datetime=None,
            series=[series],
        )

        users_dir = tmp_path / "users"
        svc = UserSessionService(users_dir, scrypt_n=FAST_N, scope_paths=False)
        admin = svc.bootstrap_first_admin(
            username="admin",
            display_name="Dr. Admin",
            secret="AdminPass#1",
            secret_kind=SecretKind.PASSWORD,
        ).user
        assert admin is not None
        svc.create_user(
            username="operator",
            display_name="Operator",
            role=UserRole.OPERATOR,
            secret="1111",
            secret_kind=SecretKind.PIN,
        )
        svc.create_user(
            username="viewer",
            display_name="Viewer",
            role=UserRole.VIEWER,
            secret="2222",
            secret_kind=SecretKind.PIN,
        )

        store = StudyMeasurementSessionStore()
        meas_dir = tmp_path / "measurements"
        persistence = MeasurementPersistence(
            meas_dir,
            store,
            enabled=True,
            author_provider=lambda: svc.active_user_id,
            can_write=lambda: svc.can(Permission.EDIT_MEASUREMENTS),
            can_delete=lambda: svc.can(Permission.DELETE_MEASUREMENTS),
            audit_callback=lambda kind, key, rev: svc.record_study_audit(
                AuditAction.STUDY_SAVED if kind == "saved" else AuditAction.STUDY_DELETED,
                study_key=key,
                details={"revision": rev} if rev else None,
            ),
        )
        statuses: list[str] = []
        persistence.status.connect(statuses.append)
        try:
            loaded_done: list[bool] = []
            persistence.load([study], lambda: loaded_done.append(True))
            assert persistence.flush()
            app.processEvents()
            assert loaded_done == [True]

            # Admin saves revision 1.
            store.set_patient_metrics(uid, 180.0, 75.0)
            persistence.save_pending()
            assert persistence.flush()
            app.processEvents()

            # Operator edits -> revision 2 stamped with operator updated_by, admin created_by preserved.
            op_session = svc.login("operator", "1111")
            assert op_session.user is not None
            store.set_patient_metrics(uid, 180.0, 77.0)
            persistence.save_pending()
            assert persistence.flush()
            app.processEvents()

            rec = persistence.repository.load(uid)
            assert rec is not None
            assert rec["created_by"] == admin.user_id
            assert rec["updated_by"] == op_session.user.user_id

            # Operator cannot delete records!
            del_errors: list[str | None] = []
            persistence.delete_record(study_key(uid), del_errors.append)
            app.processEvents()
            assert del_errors == ["permission"]
            assert persistence.repository.load(uid) is not None

            # Viewer cannot save modifications!
            svc.login("viewer", "2222")
            statuses.clear()
            store.set_patient_metrics(uid, 150.0, 50.0)
            persistence.save_pending()
            assert persistence.flush()
            app.processEvents()
            assert "permission" in statuses
            rec_after = persistence.repository.load(uid)
            assert rec_after is not None
            assert rec_after["data"].weight_kg == 77.0

            # Admin deletes record -> succeeds and logs PHI-free audit entry.
            svc.login("admin", "AdminPass#1")
            admin_del: list[str | None] = []
            persistence.delete_record(study_key(uid), admin_del.append)
            assert persistence.flush()
            app.processEvents()
            assert admin_del == [None]
            assert persistence.repository.load(uid) is None
        finally:
            persistence.close()

        # Verify audit log integrity AND guarantee zero raw PHI leaked into audit.jsonl!
        assert svc.verify_audit_log().valid
        exported = tmp_path / "audit-export.jsonl"
        assert svc.export_audit_log(exported) > 0
        raw_audit = exported.read_text(encoding="utf-8")
        assert "SECRET_PATIENT_PHI" not in raw_audit
        assert "PHI_MRN_999" not in raw_audit
        assert uid not in raw_audit
        assert study_key(uid) in raw_audit
