"""Orthanc / DICOMweb server settings (embedded form + standalone dialog)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.infrastructure.server_settings import (
    ServerSettings,
    load_server_settings,
    save_server_settings,
)


class ServerSettingsForm(QWidget):
    """Reusable DICOMweb connection fields (Weasis-style WEB node)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._description_edit = QLineEdit()
        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText("http://192.168.1.111:8042/dicom-web")
        self._auth_mode = QComboBox()
        self._auth_mode.addItem("Без аутентификации", "none")
        self._auth_mode.addItem("Basic (логин / пароль)", "basic")
        self._auth_mode.currentIndexChanged.connect(self._sync_auth_fields)
        self._username_edit = QLineEdit()
        self._password_edit = QLineEdit()
        self._password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._headers_edit = QPlainTextEdit()
        self._headers_edit.setPlaceholderText(
            "Authorization: Basic cGFjczpwYcIBTU2NBRERS\nX-Custom-Header: value"
        )
        self._headers_edit.setFixedHeight(72)
        self._mock_check = QCheckBox("Mock (без сервера)")

        form = QFormLayout(self)
        form.addRow("Описание:", self._description_edit)
        form.addRow("DICOMweb URL:", self._url_edit)
        form.addRow("Аутентификация:", self._auth_mode)
        form.addRow("Имя пользователя:", self._username_edit)
        form.addRow("Пароль:", self._password_edit)
        form.addRow("HTTP-заголовки:", self._headers_edit)
        form.addRow("", self._mock_check)

        self.set_settings(load_server_settings())

    def _sync_auth_fields(self) -> None:
        basic = self._auth_mode.currentData() == "basic"
        self._username_edit.setEnabled(basic)
        self._password_edit.setEnabled(basic)

    def settings(self) -> ServerSettings:
        return ServerSettings(
            description=self._description_edit.text().strip(),
            url=self._url_edit.text().strip(),
            username=self._username_edit.text(),
            password=self._password_edit.text(),
            auth_mode=str(self._auth_mode.currentData()),
            http_headers=self._headers_edit.toPlainText().strip(),
            use_mock=self._mock_check.isChecked(),
        )

    def set_settings(self, settings: ServerSettings) -> None:
        self._description_edit.setText(settings.description)
        self._url_edit.setText(settings.url)
        auth_index = self._auth_mode.findData(settings.auth_mode)
        self._auth_mode.setCurrentIndex(max(auth_index, 0))
        self._username_edit.setText(settings.username)
        self._password_edit.setText(settings.password)
        self._headers_edit.setPlainText(settings.http_headers)
        self._mock_check.setChecked(settings.use_mock)
        self._sync_auth_fields()


def show_server_settings_dialog(parent: QWidget | None = None) -> bool:
    dialog = ServerSettingsDialog(parent)
    return dialog.exec() == QDialog.DialogCode.Accepted


class ServerSettingsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Настройки сервера")

        self._form = ServerSettingsForm(self)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self._form)
        layout.addWidget(buttons)

    def _on_accept(self) -> None:
        save_server_settings(self._form.settings())
        self.accept()
