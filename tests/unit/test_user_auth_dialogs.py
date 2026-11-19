"""GUI tests for local user login, session lock, management and storage filter (#623)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from PySide6.QtWidgets import QDialog, QMenu, QWidget

from echo_personal_tool.application.saved_records import SavedRecordsListing, SavedRecordSummary
from echo_personal_tool.application.user_session import UserSessionService
from echo_personal_tool.domain.models.user import SecretKind, UserRole
from echo_personal_tool.presentation.coordinators.user_session_coordinator import (
    UserSessionCoordinator,
)
from echo_personal_tool.presentation.measurement_storage_dialog import MeasurementStorageDialog
from echo_personal_tool.presentation.user_login_dialog import (
    ChangeSecretDialog,
    SessionLockDialog,
    UserLoginDialog,
)
from echo_personal_tool.presentation.user_management_dialog import (
    UserAccountEditorDialog,
    UserManagementDialog,
)
from echo_personal_tool.presentation.window_chrome.title_bar import WindowTitleBar

pytestmark = pytest.mark.gui

FAST_N = 1 << 12


def _service(tmp_path: Path) -> UserSessionService:
    users_dir = tmp_path / "users"
    return UserSessionService(users_dir, scrypt_n=FAST_N, scope_paths=False)


def test_login_dialog_switches_pin_and_password_and_authenticates(tmp_path: Path, qtbot) -> None:
    svc = _service(tmp_path)
    svc.bootstrap_first_admin(
        username="admin",
        display_name="Dr. Admin",
        secret="AdminPass#1",
        secret_kind=SecretKind.PASSWORD,
    )
    svc.create_user(
        username="petrov",
        display_name="Dr. Petrov",
        role=UserRole.PHYSICIAN,
        secret="4821",
        secret_kind=SecretKind.PIN,
        title="Cardiologist",
    )
    svc.logout()

    dialog = UserLoginDialog(svc)
    qtbot.addWidget(dialog)
    assert dialog.user_list.count() == 2

    dialog.username_edit.setText("petrov")
    dialog.secret_edit.setText("0000")
    dialog.submit()
    assert not dialog.error_label.isHidden()
    assert svc.current_user is None

    dialog.secret_edit.setText("4821")
    dialog.submit()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert svc.current_user is not None
    assert svc.current_user.username == "petrov"


def test_session_lock_dialog_blocks_escape_and_unlocks_with_secret(tmp_path: Path, qtbot) -> None:
    svc = _service(tmp_path)
    svc.bootstrap_first_admin(
        username="ivanov",
        display_name="Dr. Ivanov",
        secret="2468",
        secret_kind=SecretKind.PIN,
    )
    svc.lock_session(reason="manual")

    dialog = SessionLockDialog(svc)
    qtbot.addWidget(dialog)
    dialog.show()

    # Escape / window close cannot dismiss a locked workstation session.
    dialog.reject()
    assert svc.is_locked()
    dialog.close()
    assert svc.is_locked()

    dialog.secret_edit.setText("1111")
    dialog.unlock()
    assert svc.is_locked()
    assert not dialog.error_label.isHidden()

    dialog.secret_edit.setText("2468")
    dialog.unlock()
    assert not svc.is_locked()
    assert dialog.outcome == SessionLockDialog.OUTCOME_UNLOCKED


def test_change_secret_and_management_dialogs(tmp_path: Path, qtbot) -> None:
    svc = _service(tmp_path)
    single_dlg = UserManagementDialog(svc)
    qtbot.addWidget(single_dlg)
    assert single_dlg.users_table is None

    editor = UserAccountEditorDialog(svc, bootstrap_admin=True)
    qtbot.addWidget(editor)
    editor.username_edit.setText("chief")
    editor.display_name_edit.setText("Dr. Chief")
    editor.title_edit.setText("Head of Echo")
    assert editor.secret_edit is not None and editor.confirm_edit is not None
    editor.secret_edit.setText("ChiefPass#1")
    editor.confirm_edit.setText("ChiefPass#1")
    editor.submit()
    assert svc.is_multi_user_enabled()
    assert svc.current_user is not None
    fp_before = svc.current_user.signing_key.key_id if svc.current_user.signing_key else ""

    admin_dlg = UserManagementDialog(svc)
    qtbot.addWidget(admin_dlg)
    assert admin_dlg.users_table is not None
    assert admin_dlg.users_table.rowCount() == 1
    assert admin_dlg.audit_table is not None
    assert admin_dlg.audit_table.rowCount() >= 2

    change_dlg = ChangeSecretDialog(svc)
    qtbot.addWidget(change_dlg)
    change_dlg.current_edit.setText("ChiefPass#1")
    change_dlg.kind_combo.setCurrentIndex(1)  # PIN
    change_dlg.new_edit.setText("5599")
    change_dlg.confirm_edit.setText("5599")
    change_dlg.submit()
    assert change_dlg.result() == QDialog.DialogCode.Accepted
    assert svc.current_user.signing_key is not None
    assert svc.current_user.signing_key.key_id == fp_before


def test_title_bar_user_badge_and_storage_mine_filter(tmp_path: Path, qtbot) -> None:
    from echo_personal_tool.application.composition import AppServices, bind_controller_services
    from echo_personal_tool.application.preferences_contract import UserPreferences as UserPreferencesContract
    from echo_personal_tool.infrastructure.user_preferences import UserPreferences

    svc = _service(tmp_path)
    title_bar = WindowTitleBar()
    qtbot.addWidget(title_bar)
    assert title_bar.user_button.isHidden()

    host = QWidget()
    qtbot.addWidget(host)

    class _Port:
        def parent_widget(self) -> QWidget:
            return host

        def title_bar(self) -> WindowTitleBar:
            return title_bar

        def preferences(self) -> UserPreferencesContract:
            return UserPreferences()

        def apply_switched_user_preferences(self, preferences: UserPreferencesContract) -> None:
            pass

        def flush_before_user_change(self) -> None:
            pass

        def show_status(self, text: str) -> None:
            pass

        def close_application(self) -> None:
            pass

    coord = UserSessionCoordinator(svc, _Port(), parent=host)
    try:
        menu = QMenu()
        qtbot.addWidget(menu)
        coord.populate_app_menu(menu)
        assert len(menu.actions()) == 1

        admin = svc.bootstrap_first_admin(
            username="ivanov",
            display_name="Иванов И.И.",
            secret="AdminPass#1",
            secret_kind=SecretKind.PASSWORD,
        ).user
        assert admin is not None
        assert not title_bar.user_button.isHidden()
        assert "Иванов И.И." in title_bar.user_button.text()
        assert title_bar.user_button.menu() is not None

        # Locking session clears stale popup menu until unlocked.
        svc.lock_session(reason="manual")
        assert title_bar.user_button.menu() is None
        svc.unlock_session("AdminPass#1")
        assert title_bar.user_button.menu() is not None

        op = svc.create_user(
            username="sidorova",
            display_name="Сидорова С.С.",
            role=UserRole.OPERATOR,
            secret="1234",
            secret_kind=SecretKind.PIN,
        )
        svc.login("sidorova", "1234")

        listing = SavedRecordsListing(
            records=(
                SavedRecordSummary(
                    key="a" * 64,
                    status="readable",
                    saved_at="2026-11-18T10:00:00Z",
                    revision=1,
                    size_bytes=2048,
                    source_count=1,
                    measurement_count=4,
                    created_by=admin.user_id,
                    updated_by=admin.user_id,
                ),
                SavedRecordSummary(
                    key="b" * 64,
                    status="readable",
                    saved_at="2026-11-18T11:00:00Z",
                    revision=1,
                    size_bytes=2048,
                    source_count=1,
                    measurement_count=2,
                    created_by=op.user_id,
                    updated_by=op.user_id,
                ),
            ),
        )

        class _Controller:
            def __init__(self, persistence: Any) -> None:
                self.measurement_persistence = persistence

        controller = _Controller(
            SimpleNamespace(
                repository=SimpleNamespace(root=tmp_path / "measurements"),
                list_saved_records=lambda cb: cb(listing),
                enabled=True,
            )
        )
        fake_services = cast(AppServices, SimpleNamespace(user_session=svc))
        bind_controller_services(controller, fake_services)

        storage_dlg = MeasurementStorageDialog(controller)
        qtbot.addWidget(storage_dlg)
        assert storage_dlg.records.count() == 2
        assert "Иванов И.И." in storage_dlg.records.item(0).text()
        assert "Сидорова С.С." in storage_dlg.records.item(1).text()
        # Operator cannot delete records.
        assert not storage_dlg._action_buttons["delete_all"].isEnabled()
        assert not storage_dlg._action_buttons["delete_selected"].isEnabled()

        storage_dlg.set_filter_scope("mine")
        assert storage_dlg.records.count() == 1
        assert "Сидорова С.С." in storage_dlg.records.item(0).text()
    finally:
        coord.shutdown()
