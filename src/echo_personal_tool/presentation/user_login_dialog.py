"""Local authentication dialogs: sign-in, session unlock and secret change.

Strict-typed presentation module; talks only to :class:`UserSessionService`
and domain user types, never to infrastructure modules directly.
"""

from __future__ import annotations

from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtGui import QCloseEvent, QRegularExpressionValidator
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.application.localization import tr
from echo_personal_tool.application.preferences_contract import UserPreferences
from echo_personal_tool.application.user_session import UserSessionService
from echo_personal_tool.domain.exceptions import UserAuthError
from echo_personal_tool.domain.models.user import (
    MAX_PASSWORD_LENGTH,
    MAX_PIN_LENGTH,
    SecretKind,
    UserProfile,
    UserRole,
    validate_secret,
)
from echo_personal_tool.presentation.dark_theme import get_theme_tokens

_PIN_REGEX = QRegularExpression(rf"^[0-9]{{0,{MAX_PIN_LENGTH}}}$")
_PASSWORD_REGEX = QRegularExpression(rf"^.{{0,{MAX_PASSWORD_LENGTH}}}$")


def role_label(role: UserRole) -> str:
    """Localized display name of a :class:`UserRole`."""
    return tr(f"auth.role.{role.value}")


def secret_kind_label(kind: SecretKind) -> str:
    """Localized display name of a :class:`SecretKind`."""
    return tr(f"auth.secret_kind.{kind.value}")


def format_auth_error(exc: UserAuthError) -> str:
    """Localized user-facing message for a :class:`UserAuthError`."""
    if exc.code == "account_locked":
        return tr("auth.error.account_locked", seconds=max(1, exc.retry_after_seconds))
    key = f"auth.error.{exc.code}"
    text = tr(key)
    return tr("auth.error.invalid_credentials") if text == key else text


def configure_secret_input(edit: QLineEdit, kind: SecretKind) -> None:
    """Apply password echo, length limits and optional digit validator to *edit*."""
    edit.setEchoMode(QLineEdit.EchoMode.Password)
    if kind is SecretKind.PIN:
        edit.setMaxLength(MAX_PIN_LENGTH)
        edit.setValidator(QRegularExpressionValidator(_PIN_REGEX, edit))
        edit.setPlaceholderText(tr("auth.login.pin_placeholder"))
    else:
        edit.setMaxLength(MAX_PASSWORD_LENGTH)
        edit.setValidator(QRegularExpressionValidator(_PASSWORD_REGEX, edit))
        edit.setPlaceholderText(tr("auth.login.password_placeholder"))


def _apply_error_style(label: QLabel) -> None:
    tokens = get_theme_tokens()
    danger = tokens.get("status.danger", tokens.get("text.1", ""))
    if danger:
        label.setStyleSheet(f"color: {danger};")


class UserLoginDialog(QDialog):
    """Cabinet user picker and password/PIN sign-in dialog."""

    def __init__(
        self,
        service: UserSessionService,
        parent: QWidget | None = None,
        *,
        switch_mode: bool = False,
        enable_mode: bool = False,
        base_preferences: UserPreferences | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._enable_mode = enable_mode
        self._base_preferences = base_preferences
        self._profiles_by_username: dict[str, UserProfile] = {}

        title_key = "auth.login.switch_title" if switch_mode else "auth.login.title"
        self.setWindowTitle(tr(title_key))
        self.setModal(True)
        self.resize(440, 390)

        layout = QVBoxLayout(self)
        heading = QLabel(tr("auth.login.heading"))
        heading.setWordWrap(True)
        layout.addWidget(heading)

        list_label = QLabel(tr("auth.login.users_label"))
        layout.addWidget(list_label)

        self.user_list = QListWidget(self)
        self.user_list.setObjectName("authUserList")
        self.user_list.setAccessibleName(tr("auth.login.users_label"))
        self.user_list.currentItemChanged.connect(self._on_user_selected)
        layout.addWidget(self.user_list, stretch=1)

        form = QFormLayout()
        self.username_edit = QLineEdit(self)
        self.username_edit.setObjectName("authUsernameEdit")
        self.username_edit.setAccessibleName(tr("auth.login.username_label"))
        self.username_edit.textChanged.connect(self._on_username_typed)
        form.addRow(tr("auth.login.username_label"), self.username_edit)

        self._secret_label = QLabel(tr("auth.login.secret_password_label"))
        self.secret_edit = QLineEdit(self)
        self.secret_edit.setObjectName("authSecretEdit")
        self.secret_edit.setAccessibleName(tr("auth.login.secret_password_label"))
        configure_secret_input(self.secret_edit, SecretKind.PASSWORD)
        self.secret_edit.returnPressed.connect(self.submit)
        form.addRow(self._secret_label, self.secret_edit)
        layout.addLayout(form)

        self.error_label = QLabel(self)
        self.error_label.setObjectName("authErrorLabel")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        _apply_error_style(self.error_label)
        layout.addWidget(self.error_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancel_button = QPushButton(tr("auth.login.cancel"), self)
        self.cancel_button.clicked.connect(self.reject)
        self.submit_button = QPushButton(tr("auth.login.submit"), self)
        self.submit_button.setDefault(True)
        self.submit_button.clicked.connect(self.submit)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.submit_button)
        layout.addLayout(buttons)

        self._populate_users()

    def _populate_users(self) -> None:
        self.user_list.clear()
        self._profiles_by_username.clear()
        users = self._service.list_users(include_inactive=False)
        if self._enable_mode:
            users = tuple(user for user in users if user.role is UserRole.ADMIN)
        preferred = self._service.last_username()
        selected_row = 0 if users else -1
        for idx, profile in enumerate(users):
            self._profiles_by_username[profile.username] = profile
            role_text = role_label(profile.role)
            text = (
                tr("auth.login.user_row_titled", name=profile.display_name, title=profile.title, role=role_text)
                if profile.title
                else tr("auth.login.user_row", name=profile.display_name, role=role_text)
            )
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, profile.username)
            self.user_list.addItem(item)
            if profile.username == preferred:
                selected_row = idx
        if selected_row >= 0:
            self.user_list.setCurrentRow(selected_row)
            self.secret_edit.setFocus()
        else:
            self.username_edit.setFocus()

    def _on_user_selected(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is None:
            return
        username = str(current.data(Qt.ItemDataRole.UserRole) or "")
        if self.username_edit.text().strip().lower() != username:
            self.username_edit.setText(username)
        self._sync_secret_mode(username)
        self.secret_edit.clear()
        self.error_label.hide()

    def _on_username_typed(self, text: str) -> None:
        self._sync_secret_mode(text.strip().lower())

    def _sync_secret_mode(self, username: str) -> None:
        profile = self._profiles_by_username.get(username)
        kind = profile.secret_kind if profile is not None else SecretKind.PASSWORD
        label_key = "auth.login.secret_pin_label" if kind is SecretKind.PIN else "auth.login.secret_password_label"
        self._secret_label.setText(tr(label_key))
        self.secret_edit.setAccessibleName(tr(label_key))
        configure_secret_input(self.secret_edit, kind)

    def submit(self) -> None:
        username = self.username_edit.text().strip()
        secret = self.secret_edit.text()
        try:
            if self._enable_mode:
                self._service.enable_multi_user(username, secret, base_preferences=self._base_preferences)
            else:
                self._service.login(username, secret, base_preferences=self._base_preferences)
        except UserAuthError as exc:
            self.secret_edit.clear()
            self.error_label.setText(format_auth_error(exc))
            self.error_label.show()
            self.secret_edit.setFocus()
            return
        self.secret_edit.clear()
        self.accept()


class SessionLockDialog(QDialog):
    """Non-bypassable modal lock dialog for an active workstation session."""

    OUTCOME_UNLOCKED = "unlocked"
    OUTCOME_SWITCHED = "switched"
    OUTCOME_QUIT = "quit"

    def __init__(
        self,
        service: UserSessionService,
        parent: QWidget | None = None,
        *,
        base_preferences: UserPreferences | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._base_preferences = base_preferences
        self._allow_close = False
        self.outcome = ""

        self.setWindowTitle(tr("auth.login.unlock_title"))
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        self.resize(430, 250)

        user = service.current_user
        layout = QVBoxLayout(self)
        heading_text = (
            tr("auth.login.unlock_heading", name=user.display_name, role=role_label(user.role))
            if user is not None
            else tr("auth.login.unlock_title")
        )
        self.heading_label = QLabel(heading_text, self)
        self.heading_label.setWordWrap(True)
        layout.addWidget(self.heading_label)

        hint = QLabel(tr("auth.login.unlock_hint"), self)
        hint.setWordWrap(True)
        layout.addWidget(hint)

        form = QFormLayout()
        kind = user.secret_kind if user is not None else SecretKind.PASSWORD
        secret_key = "auth.login.secret_pin_label" if kind is SecretKind.PIN else "auth.login.secret_password_label"
        self.secret_edit = QLineEdit(self)
        self.secret_edit.setObjectName("authUnlockSecretEdit")
        self.secret_edit.setAccessibleName(tr(secret_key))
        configure_secret_input(self.secret_edit, kind)
        self.secret_edit.returnPressed.connect(self.unlock)
        form.addRow(tr(secret_key), self.secret_edit)
        layout.addLayout(form)

        self.error_label = QLabel(self)
        self.error_label.setObjectName("authUnlockErrorLabel")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        _apply_error_style(self.error_label)
        layout.addWidget(self.error_label)

        buttons = QHBoxLayout()
        self.quit_button = QPushButton(tr("auth.login.quit_button"), self)
        self.quit_button.clicked.connect(self.request_quit)
        self.switch_button = QPushButton(tr("auth.login.switch_button"), self)
        self.switch_button.clicked.connect(self.switch_user)
        self.unlock_button = QPushButton(tr("auth.login.unlock_submit"), self)
        self.unlock_button.setDefault(True)
        self.unlock_button.clicked.connect(self.unlock)
        buttons.addWidget(self.quit_button)
        buttons.addStretch(1)
        buttons.addWidget(self.switch_button)
        buttons.addWidget(self.unlock_button)
        if user is None:
            self.secret_edit.setEnabled(False)
            self.unlock_button.setEnabled(False)
        layout.addLayout(buttons)

    def reject(self) -> None:
        """Ignore Escape so a locked workstation cannot be dismissed without credentials."""
        if self._allow_close:
            super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._allow_close:
            super().closeEvent(event)
        else:
            event.ignore()

    def unlock(self) -> None:
        secret = self.secret_edit.text()
        try:
            self._service.unlock_session(secret)
        except UserAuthError as exc:
            self.secret_edit.clear()
            self.error_label.setText(format_auth_error(exc))
            self.error_label.show()
            self.secret_edit.setFocus()
            return
        self.secret_edit.clear()
        self.outcome = self.OUTCOME_UNLOCKED
        self._allow_close = True
        self.accept()

    def switch_user(self) -> None:
        dialog = UserLoginDialog(
            self._service,
            self,
            switch_mode=True,
            base_preferences=self._base_preferences,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.secret_edit.clear()
            self.outcome = self.OUTCOME_SWITCHED
            self._allow_close = True
            self.accept()

    def request_quit(self) -> None:
        self.secret_edit.clear()
        self.outcome = self.OUTCOME_QUIT
        self._allow_close = True
        super().reject()


class ChangeSecretDialog(QDialog):
    """Self-service dialog for updating the active user's password or PIN."""

    def __init__(self, service: UserSessionService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self.setWindowTitle(tr("auth.change_secret.title"))
        self.setModal(True)
        self.resize(430, 290)

        user = service.current_user
        current_kind = user.secret_kind if user is not None else SecretKind.PASSWORD

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.current_edit = QLineEdit(self)
        self.current_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.current_edit.setMaxLength(MAX_PASSWORD_LENGTH)
        self.current_edit.setAccessibleName(tr("auth.change_secret.current"))
        form.addRow(tr("auth.change_secret.current"), self.current_edit)

        self.kind_combo = QComboBox(self)
        self.kind_combo.addItem(secret_kind_label(SecretKind.PASSWORD), SecretKind.PASSWORD.value)
        self.kind_combo.addItem(secret_kind_label(SecretKind.PIN), SecretKind.PIN.value)
        self.kind_combo.setCurrentIndex(1 if current_kind is SecretKind.PIN else 0)
        self.kind_combo.currentIndexChanged.connect(self._on_kind_changed)
        form.addRow(tr("auth.change_secret.kind"), self.kind_combo)

        self.new_edit = QLineEdit(self)
        self.new_edit.setAccessibleName(tr("auth.change_secret.new"))
        form.addRow(tr("auth.change_secret.new"), self.new_edit)

        self.confirm_edit = QLineEdit(self)
        self.confirm_edit.setAccessibleName(tr("auth.change_secret.confirm"))
        self.confirm_edit.returnPressed.connect(self.submit)
        form.addRow(tr("auth.change_secret.confirm"), self.confirm_edit)
        layout.addLayout(form)

        note = QLabel(tr("auth.change_secret.key_note"), self)
        note.setWordWrap(True)
        layout.addWidget(note)

        self.error_label = QLabel(self)
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        _apply_error_style(self.error_label)
        layout.addWidget(self.error_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel_btn = QPushButton(tr("auth.login.cancel"), self)
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton(tr("auth.change_secret.save"), self)
        save_btn.setDefault(True)
        save_btn.clicked.connect(self.submit)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(save_btn)
        layout.addLayout(buttons)

        self._on_kind_changed()

    def selected_kind(self) -> SecretKind:
        return SecretKind(str(self.kind_combo.currentData()))

    def _on_kind_changed(self) -> None:
        kind = self.selected_kind()
        self.new_edit.clear()
        self.confirm_edit.clear()
        configure_secret_input(self.new_edit, kind)
        configure_secret_input(self.confirm_edit, kind)

    def submit(self) -> None:
        old_secret = self.current_edit.text()
        new_secret = self.new_edit.text()
        confirm = self.confirm_edit.text()
        kind = self.selected_kind()
        try:
            validate_secret(new_secret, kind)
            if new_secret != confirm:
                raise UserAuthError("secret_mismatch")
            self._service.change_own_secret(old_secret=old_secret, new_secret=new_secret, new_kind=kind)
        except UserAuthError as exc:
            self.error_label.setText(format_auth_error(exc))
            self.error_label.show()
            return
        self.current_edit.clear()
        self.new_edit.clear()
        self.confirm_edit.clear()
        self.accept()
