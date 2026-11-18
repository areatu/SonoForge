"""Local multi-user account management and hash-chained audit trail dialog.

Provides single-user -> multi-user onboarding, admin CRUD over local cabinet
accounts (password/PIN, roles, Ed25519 key fingerprints, soft deactivation,
inactivity lock timeout), self-service actions for non-admins, and live
verification/export of ``audit.jsonl``.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.application.localization import tr
from echo_personal_tool.application.preferences_contract import UserPreferences
from echo_personal_tool.application.user_session import UserSessionService
from echo_personal_tool.domain.exceptions import UserAuthError
from echo_personal_tool.domain.models.audit import AuditEntry
from echo_personal_tool.domain.models.user import (
    MAX_AUTO_LOCK_MINUTES,
    MAX_DISPLAY_NAME_LENGTH,
    MAX_EXTERNAL_ID_LENGTH,
    MAX_TITLE_LENGTH,
    MIN_AUTO_LOCK_MINUTES,
    Permission,
    SecretKind,
    UserProfile,
    UserRole,
    validate_secret,
)
from echo_personal_tool.presentation.dark_theme import get_theme_tokens
from echo_personal_tool.presentation.user_login_dialog import (
    ChangeSecretDialog,
    UserLoginDialog,
    configure_secret_input,
    format_auth_error,
    role_label,
    secret_kind_label,
)


def _apply_danger_color(label: QLabel) -> None:
    tokens = get_theme_tokens()
    color = tokens.get("status.danger", tokens.get("text.1", ""))
    if color:
        label.setStyleSheet(f"color: {color};")


class UserAccountEditorDialog(QDialog):
    """Create a local account (or first admin), or edit an existing profile."""

    def __init__(
        self,
        service: UserSessionService,
        parent: QWidget | None = None,
        *,
        bootstrap_admin: bool = False,
        existing: UserProfile | None = None,
        base_preferences: UserPreferences | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._bootstrap_admin = bootstrap_admin
        self._existing = existing
        self._base_preferences = base_preferences
        self.saved_profile: UserProfile | None = None

        if bootstrap_admin:
            title_key = "auth.editor.create_admin_title"
        elif existing is not None:
            title_key = "auth.editor.edit_title"
        else:
            title_key = "auth.editor.create_title"
        self.setWindowTitle(tr(title_key))
        self.setModal(True)
        self.resize(460, 360)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.username_edit = QLineEdit(existing.username if existing else "", self)
        self.username_edit.setPlaceholderText(tr("auth.editor.username_placeholder"))
        self.username_edit.setMaxLength(32)
        if existing is not None:
            self.username_edit.setReadOnly(True)
            self.username_edit.setEnabled(False)
        form.addRow(tr("auth.editor.username"), self.username_edit)

        self.display_name_edit = QLineEdit(existing.display_name if existing else "", self)
        self.display_name_edit.setPlaceholderText(tr("auth.editor.display_name_placeholder"))
        self.display_name_edit.setMaxLength(MAX_DISPLAY_NAME_LENGTH)
        form.addRow(tr("auth.editor.display_name"), self.display_name_edit)

        self.title_edit = QLineEdit(existing.title if existing else "", self)
        self.title_edit.setPlaceholderText(tr("auth.editor.title_placeholder"))
        self.title_edit.setMaxLength(MAX_TITLE_LENGTH)
        form.addRow(tr("auth.editor.title_field"), self.title_edit)

        self.external_id_edit = QLineEdit(existing.external_id if existing else "", self)
        self.external_id_edit.setPlaceholderText(tr("auth.editor.external_id_placeholder"))
        self.external_id_edit.setMaxLength(MAX_EXTERNAL_ID_LENGTH)
        form.addRow(tr("auth.editor.external_id"), self.external_id_edit)

        self.role_combo = QComboBox(self)
        for role in (UserRole.ADMIN, UserRole.PHYSICIAN, UserRole.OPERATOR, UserRole.VIEWER):
            self.role_combo.addItem(role_label(role), role.value)
        initial_role = UserRole.ADMIN if bootstrap_admin else (existing.role if existing else UserRole.PHYSICIAN)
        role_idx = self.role_combo.findData(initial_role.value)
        if role_idx >= 0:
            self.role_combo.setCurrentIndex(role_idx)
        if bootstrap_admin:
            self.role_combo.setEnabled(False)
        form.addRow(tr("auth.editor.role"), self.role_combo)

        self.kind_combo: QComboBox | None = None
        self.secret_edit: QLineEdit | None = None
        self.confirm_edit: QLineEdit | None = None
        if existing is None:
            self.kind_combo = QComboBox(self)
            self.kind_combo.addItem(secret_kind_label(SecretKind.PASSWORD), SecretKind.PASSWORD.value)
            self.kind_combo.addItem(secret_kind_label(SecretKind.PIN), SecretKind.PIN.value)
            self.kind_combo.currentIndexChanged.connect(self._sync_secret_kind)
            form.addRow(tr("auth.editor.secret_kind"), self.kind_combo)

            self.secret_edit = QLineEdit(self)
            form.addRow(tr("auth.editor.secret"), self.secret_edit)

            self.confirm_edit = QLineEdit(self)
            self.confirm_edit.returnPressed.connect(self.submit)
            form.addRow(tr("auth.editor.secret_confirm"), self.confirm_edit)
            self._sync_secret_kind()

        layout.addLayout(form)

        self.error_label = QLabel(self)
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        _apply_danger_color(self.error_label)
        layout.addWidget(self.error_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel_btn = QPushButton(tr("auth.login.cancel"), self)
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton(tr("auth.editor.save"), self)
        save_btn.setDefault(True)
        save_btn.clicked.connect(self.submit)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(save_btn)
        layout.addLayout(buttons)

    def _selected_kind(self) -> SecretKind:
        if self.kind_combo is None:
            return SecretKind.PASSWORD
        return SecretKind(str(self.kind_combo.currentData()))

    def _sync_secret_kind(self) -> None:
        if self.secret_edit is None or self.confirm_edit is None:
            return
        kind = self._selected_kind()
        self.secret_edit.clear()
        self.confirm_edit.clear()
        configure_secret_input(self.secret_edit, kind)
        configure_secret_input(self.confirm_edit, kind)

    def submit(self) -> None:
        role = UserRole(str(self.role_combo.currentData()))
        display_name = self.display_name_edit.text()
        title = self.title_edit.text()
        external_id = self.external_id_edit.text()
        try:
            if self._existing is not None:
                self.saved_profile = self._service.update_user(
                    self._existing.user_id,
                    display_name=display_name,
                    title=title,
                    external_id=external_id,
                    role=role,
                )
            else:
                assert self.secret_edit is not None and self.confirm_edit is not None
                secret = self.secret_edit.text()
                confirm = self.confirm_edit.text()
                kind = self._selected_kind()
                validate_secret(secret, kind)
                if secret != confirm:
                    raise UserAuthError("secret_mismatch")
                username = self.username_edit.text()
                if self._bootstrap_admin:
                    session = self._service.bootstrap_first_admin(
                        username=username,
                        display_name=display_name,
                        secret=secret,
                        secret_kind=kind,
                        title=title,
                        external_id=external_id,
                        base_preferences=self._base_preferences,
                    )
                    self.saved_profile = session.user
                else:
                    self.saved_profile = self._service.create_user(
                        username=username,
                        display_name=display_name,
                        role=role,
                        secret=secret,
                        secret_kind=kind,
                        title=title,
                        external_id=external_id,
                        base_preferences=self._base_preferences,
                    )
        except UserAuthError as exc:
            self.error_label.setText(format_auth_error(exc))
            self.error_label.show()
            return
        if self.secret_edit is not None:
            self.secret_edit.clear()
        if self.confirm_edit is not None:
            self.confirm_edit.clear()
        self.accept()


class AdminResetSecretDialog(QDialog):
    """Admin dialog to reset a user's forgotten password/PIN (rotates Ed25519 key)."""

    def __init__(
        self,
        service: UserSessionService,
        target: UserProfile,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._target = target
        self.setWindowTitle(tr("auth.editor.reset_title", name=target.display_name))
        self.setModal(True)
        self.resize(450, 280)

        layout = QVBoxLayout(self)
        warning = QLabel(tr("auth.editor.reset_warning"), self)
        warning.setWordWrap(True)
        layout.addWidget(warning)

        form = QFormLayout()
        self.kind_combo = QComboBox(self)
        self.kind_combo.addItem(secret_kind_label(SecretKind.PASSWORD), SecretKind.PASSWORD.value)
        self.kind_combo.addItem(secret_kind_label(SecretKind.PIN), SecretKind.PIN.value)
        self.kind_combo.setCurrentIndex(1 if target.secret_kind is SecretKind.PIN else 0)
        self.kind_combo.currentIndexChanged.connect(self._sync_kind)
        form.addRow(tr("auth.editor.secret_kind"), self.kind_combo)

        self.secret_edit = QLineEdit(self)
        form.addRow(tr("auth.editor.secret"), self.secret_edit)

        self.confirm_edit = QLineEdit(self)
        self.confirm_edit.returnPressed.connect(self.submit)
        form.addRow(tr("auth.editor.secret_confirm"), self.confirm_edit)
        layout.addLayout(form)

        self.error_label = QLabel(self)
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        _apply_danger_color(self.error_label)
        layout.addWidget(self.error_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel_btn = QPushButton(tr("auth.login.cancel"), self)
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton(tr("auth.editor.save"), self)
        save_btn.setDefault(True)
        save_btn.clicked.connect(self.submit)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(save_btn)
        layout.addLayout(buttons)

        self._sync_kind()

    def _sync_kind(self) -> None:
        kind = SecretKind(str(self.kind_combo.currentData()))
        self.secret_edit.clear()
        self.confirm_edit.clear()
        configure_secret_input(self.secret_edit, kind)
        configure_secret_input(self.confirm_edit, kind)

    def submit(self) -> None:
        kind = SecretKind(str(self.kind_combo.currentData()))
        secret = self.secret_edit.text()
        confirm = self.confirm_edit.text()
        try:
            validate_secret(secret, kind)
            if secret != confirm:
                raise UserAuthError("secret_mismatch")
            self._service.admin_reset_secret(self._target.user_id, new_secret=secret, new_kind=kind)
        except UserAuthError as exc:
            self.error_label.setText(format_auth_error(exc))
            self.error_label.show()
            return
        self.secret_edit.clear()
        self.confirm_edit.clear()
        self.accept()


class UserManagementDialog(QDialog):
    """Main local users, session mode and audit-trail dialog."""

    def __init__(
        self,
        service: UserSessionService,
        parent: QWidget | None = None,
        *,
        base_preferences: UserPreferences | None = None,
        on_switch_user: Callable[[], None] | None = None,
        on_lock_session: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._base_preferences = base_preferences
        self._on_switch_user = on_switch_user
        self._on_lock_session = on_lock_session
        self.mode_changed = False
        self._users: tuple[UserProfile, ...] = ()

        self.setWindowTitle(tr("auth.manage.title"))
        self.setModal(True)
        self.resize(820, 520)

        self._root = QVBoxLayout(self)
        self._content: QWidget | None = None
        self.users_table: QTableWidget | None = None
        self.audit_table: QTableWidget | None = None
        self.audit_status_label: QLabel | None = None
        self.auto_lock_spin: QSpinBox | None = None
        self.toggle_active_button: QPushButton | None = None
        self._rebuild()

    def _rebuild(self) -> None:
        if self._content is not None:
            self._root.removeWidget(self._content)
            self._content.deleteLater()
            self._content = None
        self.users_table = None
        self.audit_table = None
        self.audit_status_label = None
        self.auto_lock_spin = None
        self.toggle_active_button = None

        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        if not self._service.is_multi_user_enabled():
            self._build_single_user_view(layout)
        elif self._service.can(Permission.MANAGE_USERS):
            self._build_admin_view(layout)
        else:
            self._build_self_service_view(layout)

        footer = QHBoxLayout()
        footer.addStretch(1)
        close_btn = QPushButton(tr("auth.manage.close"), container)
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)
        layout.addLayout(footer)

        self._content = container
        self._root.addWidget(container)

    def _build_single_user_view(self, layout: QVBoxLayout) -> None:
        info = QLabel(tr("auth.manage.single_user_info"))
        info.setWordWrap(True)
        layout.addWidget(info)

        actions = QHBoxLayout()
        if self._service.has_users():
            enable_btn = QPushButton(tr("auth.manage.enable_existing"))
            enable_btn.setObjectName("authEnableExistingButton")
            enable_btn.clicked.connect(self._enable_existing)
            actions.addWidget(enable_btn)
        else:
            create_btn = QPushButton(tr("auth.manage.enable_new"))
            create_btn.setObjectName("authBootstrapAdminButton")
            create_btn.clicked.connect(self._bootstrap_admin)
            actions.addWidget(create_btn)
        actions.addStretch(1)
        layout.addLayout(actions)
        layout.addStretch(1)

    def _build_self_service_view(self, layout: QVBoxLayout) -> None:
        user = self._service.current_user
        if user is not None:
            banner = QLabel(tr("auth.manage.active_banner", name=user.display_name, role=role_label(user.role)))
            banner.setWordWrap(True)
            layout.addWidget(banner)
        info = QLabel(tr("auth.manage.non_admin_info"))
        info.setWordWrap(True)
        layout.addWidget(info)

        row = QHBoxLayout()
        change_btn = QPushButton(tr("app_menu.change_secret"))
        change_btn.clicked.connect(self._change_own_secret)
        row.addWidget(change_btn)
        if self._on_switch_user is not None:
            switch_btn = QPushButton(tr("app_menu.switch_user"))
            switch_btn.clicked.connect(self._trigger_switch)
            row.addWidget(switch_btn)
        if self._on_lock_session is not None:
            lock_btn = QPushButton(tr("app_menu.lock_session"))
            lock_btn.clicked.connect(self._trigger_lock)
            row.addWidget(lock_btn)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addStretch(1)

    def _build_admin_view(self, layout: QVBoxLayout) -> None:
        user = self._service.current_user
        if user is not None:
            banner = QLabel(tr("auth.manage.active_banner", name=user.display_name, role=role_label(user.role)))
            banner.setWordWrap(True)
            layout.addWidget(banner)

        tabs = QTabWidget()
        tabs.addTab(self._build_users_tab(), tr("auth.manage.tab_users"))
        tabs.addTab(self._build_audit_tab(), tr("auth.manage.tab_audit"))
        layout.addWidget(tabs, stretch=1)
        self.refresh_users()
        self.refresh_audit()

    def _build_users_tab(self) -> QWidget:
        page = QWidget()
        vbox = QVBoxLayout(page)

        table = QTableWidget(0, 7, page)
        table.setObjectName("authUsersTable")
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        headers = [
            tr("auth.manage.col_name"),
            tr("auth.manage.col_username"),
            tr("auth.manage.col_role"),
            tr("auth.manage.col_title"),
            tr("auth.manage.col_auth"),
            tr("auth.manage.col_key"),
            tr("auth.manage.col_status"),
        ]
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.itemSelectionChanged.connect(self._sync_toggle_label)
        self.users_table = table
        vbox.addWidget(table, stretch=1)

        buttons = QHBoxLayout()
        add_btn = QPushButton(tr("auth.manage.add_user"), page)
        add_btn.clicked.connect(self._add_user)
        edit_btn = QPushButton(tr("auth.manage.edit_user"), page)
        edit_btn.clicked.connect(self._edit_user)
        reset_btn = QPushButton(tr("auth.manage.reset_secret"), page)
        reset_btn.clicked.connect(self._reset_user_secret)
        toggle_btn = QPushButton(tr("auth.manage.deactivate_user"), page)
        toggle_btn.clicked.connect(self._toggle_user_active)
        self.toggle_active_button = toggle_btn
        change_own_btn = QPushButton(tr("app_menu.change_secret"), page)
        change_own_btn.clicked.connect(self._change_own_secret)
        for btn in (add_btn, edit_btn, reset_btn, toggle_btn, change_own_btn):
            buttons.addWidget(btn)
        buttons.addStretch(1)
        vbox.addLayout(buttons)

        settings_row = QHBoxLayout()
        settings_row.addWidget(QLabel(tr("auth.manage.auto_lock_label"), page))
        spin = QSpinBox(page)
        spin.setRange(MIN_AUTO_LOCK_MINUTES, MAX_AUTO_LOCK_MINUTES)
        spin.setSpecialValueText(tr("auth.manage.auto_lock_off"))
        spin.setSuffix(tr("auth.manage.auto_lock_suffix"))
        spin.setValue(self._service.auto_lock_minutes())
        spin.valueChanged.connect(self._on_auto_lock_changed)
        self.auto_lock_spin = spin
        settings_row.addWidget(spin)
        settings_row.addStretch(1)
        disable_btn = QPushButton(tr("auth.manage.disable_mode"), page)
        disable_btn.clicked.connect(self._disable_mode)
        settings_row.addWidget(disable_btn)
        vbox.addLayout(settings_row)
        return page

    def _build_audit_tab(self) -> QWidget:
        page = QWidget()
        vbox = QVBoxLayout(page)

        top = QHBoxLayout()
        status = QLabel(page)
        status.setObjectName("authAuditStatusLabel")
        status.setWordWrap(True)
        self.audit_status_label = status
        top.addWidget(status, stretch=1)

        verify_btn = QPushButton(tr("auth.audit.verify"), page)
        verify_btn.clicked.connect(self.refresh_audit)
        refresh_btn = QPushButton(tr("auth.audit.refresh"), page)
        refresh_btn.clicked.connect(self.refresh_audit)
        export_btn = QPushButton(tr("auth.audit.export"), page)
        export_btn.clicked.connect(self._export_audit)
        top.addWidget(verify_btn)
        top.addWidget(refresh_btn)
        top.addWidget(export_btn)
        vbox.addLayout(top)

        table = QTableWidget(0, 6, page)
        table.setObjectName("authAuditTable")
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setHorizontalHeaderLabels(
            [
                tr("auth.audit.col_seq"),
                tr("auth.audit.col_time"),
                tr("auth.audit.col_action"),
                tr("auth.audit.col_actor"),
                tr("auth.audit.col_target"),
                tr("auth.audit.col_details"),
            ]
        )
        table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.audit_table = table
        vbox.addWidget(table, stretch=1)
        return page

    def _selected_user(self) -> UserProfile | None:
        if self.users_table is None:
            return None
        row = self.users_table.currentRow()
        if 0 <= row < len(self._users):
            return self._users[row]
        return None

    def _sync_toggle_label(self) -> None:
        if self.toggle_active_button is None:
            return
        selected = self._selected_user()
        key = (
            "auth.manage.activate_user"
            if (selected is not None and not selected.active)
            else "auth.manage.deactivate_user"
        )
        self.toggle_active_button.setText(tr(key))

    def refresh_users(self) -> None:
        if self.users_table is None:
            return
        self._users = self._service.list_users(include_inactive=True)
        self.users_table.setRowCount(len(self._users))
        for row, profile in enumerate(self._users):
            fingerprint = profile.signing_key.formatted_fingerprint if profile.signing_key else ""
            status_text = tr("auth.manage.status_active" if profile.active else "auth.manage.status_inactive")
            cells = (
                profile.display_name,
                profile.username,
                role_label(profile.role),
                profile.title,
                secret_kind_label(profile.secret_kind),
                fingerprint,
                status_text,
            )
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, profile.user_id)
                self.users_table.setItem(row, col, item)
        if self._users:
            self.users_table.selectRow(0)
        self._sync_toggle_label()

    def refresh_audit(self) -> None:
        if self.audit_table is None or self.audit_status_label is None:
            return
        verification = self._service.verify_audit_log()
        if verification.valid:
            self.audit_status_label.setStyleSheet("")
            self.audit_status_label.setText(tr("auth.audit.chain_ok", count=verification.checked_count))
        else:
            _apply_danger_color(self.audit_status_label)
            self.audit_status_label.setText(
                tr(
                    "auth.audit.chain_broken",
                    seq=verification.first_broken_seq or 0,
                    reason=verification.reason,
                )
            )
        names = self._service.user_display_map()
        entries = self._service.recent_audit_entries(limit=200)
        self.audit_table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            cells = self._format_audit_row(entry, names)
            for col, text in enumerate(cells):
                self.audit_table.setItem(row, col, QTableWidgetItem(text))

    @staticmethod
    def _format_audit_row(entry: AuditEntry, names: dict[str, str]) -> tuple[str, ...]:
        action_key = f"auth.audit.action.{entry.action}"
        action_text = tr(action_key)
        if action_text == action_key:
            action_text = entry.action
        if entry.actor_id == "system":
            actor_text = tr("auth.audit.actor_system")
        elif entry.actor_id == "anonymous":
            actor_text = tr("auth.audit.actor_anonymous")
        else:
            actor_text = names.get(entry.actor_id, entry.actor_id[:8])
        target_parts: list[str] = []
        if entry.target_id:
            target_parts.append(names.get(entry.target_id, entry.target_id[:8]))
        if entry.study_key:
            target_parts.append(entry.study_key[:12])
        details_text = ", ".join(f"{k}={v}" for k, v in entry.details)
        stamp = entry.timestamp[:19].replace("T", " ")
        return (str(entry.seq), stamp, action_text, actor_text, " · ".join(target_parts), details_text)

    def _bootstrap_admin(self) -> None:
        editor = UserAccountEditorDialog(
            self._service,
            self,
            bootstrap_admin=True,
            base_preferences=self._base_preferences,
        )
        if editor.exec() == QDialog.DialogCode.Accepted:
            self.mode_changed = True
            self._rebuild()

    def _enable_existing(self) -> None:
        dialog = UserLoginDialog(
            self._service,
            self,
            enable_mode=True,
            base_preferences=self._base_preferences,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.mode_changed = True
            self._rebuild()

    def _add_user(self) -> None:
        editor = UserAccountEditorDialog(
            self._service,
            self,
            base_preferences=self._base_preferences,
        )
        if editor.exec() == QDialog.DialogCode.Accepted:
            self.refresh_users()
            self.refresh_audit()

    def _edit_user(self) -> None:
        selected = self._selected_user()
        if selected is None:
            return
        editor = UserAccountEditorDialog(self._service, self, existing=selected)
        if editor.exec() == QDialog.DialogCode.Accepted:
            self.refresh_users()
            self.refresh_audit()

    def _reset_user_secret(self) -> None:
        selected = self._selected_user()
        if selected is None:
            return
        dialog = AdminResetSecretDialog(self._service, selected, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh_users()
            self.refresh_audit()

    def _toggle_user_active(self) -> None:
        selected = self._selected_user()
        if selected is None:
            return
        try:
            self._service.set_user_active(selected.user_id, active=not selected.active)
        except UserAuthError as exc:
            QMessageBox.warning(self, self.windowTitle(), format_auth_error(exc))
            return
        self.refresh_users()
        self.refresh_audit()

    def _change_own_secret(self) -> None:
        dialog = ChangeSecretDialog(self._service, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh_users()
            self.refresh_audit()

    def _on_auto_lock_changed(self, value: int) -> None:
        try:
            self._service.set_auto_lock_minutes(value)
        except UserAuthError as exc:
            QMessageBox.warning(self, self.windowTitle(), format_auth_error(exc))
            return
        self.refresh_audit()

    def _disable_mode(self) -> None:
        secret, ok = QInputDialog.getText(
            self,
            tr("auth.manage.disable_title"),
            tr("auth.manage.disable_prompt"),
            QLineEdit.EchoMode.Password,
        )
        if not ok or not secret:
            return
        try:
            self._service.disable_multi_user(secret)
        except UserAuthError as exc:
            QMessageBox.warning(self, self.windowTitle(), format_auth_error(exc))
            return
        self.mode_changed = True
        self._rebuild()

    def _export_audit(self) -> None:
        target, _ = QFileDialog.getSaveFileName(
            self,
            tr("auth.audit.export_title"),
            str(Path.home() / "sonoforge-audit.jsonl"),
            "JSON Lines (*.jsonl)",
        )
        if not target:
            return
        count = self._service.export_audit_log(Path(target))
        QMessageBox.information(self, self.windowTitle(), tr("auth.audit.export_done", count=count))

    def _trigger_switch(self) -> None:
        self.accept()
        if self._on_switch_user is not None:
            self._on_switch_user()

    def _trigger_lock(self) -> None:
        self.accept()
        if self._on_lock_session is not None:
            self._on_lock_session()
