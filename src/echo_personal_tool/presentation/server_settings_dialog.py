"""Orthanc / DICOMweb server settings (embedded form + standalone dialog)."""

from __future__ import annotations

from PySide6.QtCore import QRunnable, QThreadPool, Signal, QObject
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.infrastructure.i18n import tr
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
        self._auth_mode.addItem(tr("server_settings.auth_mode_none"), "none")
        self._auth_mode.addItem(tr("server_settings.auth_mode_basic"), "basic")
        self._auth_mode.currentIndexChanged.connect(self._sync_auth_fields)
        self._username_edit = QLineEdit()
        self._password_edit = QLineEdit()
        self._password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._headers_edit = QPlainTextEdit()
        self._headers_edit.setPlaceholderText(
            "Authorization: Basic cGFjczpwYcIBTU2NBRERS\nX-Custom-Header: value"
        )
        self._headers_edit.setFixedHeight(72)
        self._mock_check = QCheckBox(tr("server_settings.mock"))

        form = QFormLayout(self)
        form.addRow(tr("server_settings.description"), self._description_edit)
        form.addRow("DICOMweb URL:", self._url_edit)
        form.addRow(tr("server_settings.auth"), self._auth_mode)
        form.addRow(tr("server_settings.username"), self._username_edit)
        form.addRow(tr("server_settings.password"), self._password_edit)
        form.addRow(tr("server_settings.http_headers"), self._headers_edit)
        form.addRow("", self._mock_check)

        # DIMSE section
        dimse_group = QGroupBox("DIMSE (Native DICOM)")
        dimse_form = QFormLayout(dimse_group)
        self._dimse_enabled = QCheckBox(tr("server_settings.dimse_enabled"))
        self._dimse_enabled.toggled.connect(self._sync_dimse_fields)
        dimse_form.addRow("", self._dimse_enabled)
        self._dimse_ae_edit = QLineEdit()
        self._dimse_ae_edit.setPlaceholderText("ECHO2026")
        dimse_form.addRow(tr("server_settings.dimse_ae_title"), self._dimse_ae_edit)
        self._dimse_called_ae_edit = QLineEdit()
        self._dimse_called_ae_edit.setPlaceholderText("ORTHANC")
        dimse_form.addRow(tr("server_settings.dimse_called_ae"), self._dimse_called_ae_edit)
        self._dimse_host_edit = QLineEdit()
        self._dimse_host_edit.setPlaceholderText("127.0.0.1")
        dimse_form.addRow(tr("server_settings.dimse_host"), self._dimse_host_edit)
        self._dimse_port_edit = QLineEdit()
        self._dimse_port_edit.setPlaceholderText("4242")
        dimse_form.addRow(tr("server_settings.dimse_port"), self._dimse_port_edit)

        # Retrieval source
        self._retrieval_source_combo = QComboBox()
        self._retrieval_source_combo.addItem("WADO-RS", "wado")
        self._retrieval_source_combo.addItem("DIMSE (C-GET)", "dimse")
        self._retrieval_source_combo.addItem("DIMSE (C-MOVE)", "cmove")
        self._retrieval_source_combo.addItem("Auto", "auto")
        dimse_form.addRow("Retrieval source:", self._retrieval_source_combo)

        # TLS settings
        self._dimse_use_tls = QCheckBox("Use TLS")
        dimse_form.addRow("", self._dimse_use_tls)
        self._dimse_tls_verify = QCheckBox("Verify server certificate")
        dimse_form.addRow("", self._dimse_tls_verify)
        self._dimse_tls_ca_path = QLineEdit()
        self._dimse_tls_ca_path.setPlaceholderText("/path/to/ca.pem")
        dimse_form.addRow("CA certificate:", self._dimse_tls_ca_path)
        self._dimse_tls_cert_path = QLineEdit()
        self._dimse_tls_cert_path.setPlaceholderText("/path/to/client.pem")
        dimse_form.addRow("Client certificate:", self._dimse_tls_cert_path)
        self._dimse_tls_key_path = QLineEdit()
        self._dimse_tls_key_path.setPlaceholderText("/path/to/client.key")
        dimse_form.addRow("Client key:", self._dimse_tls_key_path)

        # Embedded Storage SCP for C-MOVE
        dimse_form.addRow("--- Embedded Storage SCP ---", QLabel())
        self._dimse_scp_host = QLineEdit()
        self._dimse_scp_host.setPlaceholderText("127.0.0.1")
        dimse_form.addRow("SCP bind host:", self._dimse_scp_host)
        self._dimse_scp_port = QLineEdit()
        self._dimse_scp_port.setPlaceholderText("11112")
        dimse_form.addRow("SCP port:", self._dimse_scp_port)
        self._dimse_scp_ae_title = QLineEdit()
        self._dimse_scp_ae_title.setPlaceholderText("(default: same as AE title)")
        dimse_form.addRow("SCP AE title:", self._dimse_scp_ae_title)

        self._dimse_echo_btn = QPushButton(tr("server_settings.dimse_test_echo"))
        self._dimse_echo_btn.clicked.connect(self._on_dimse_echo)
        dimse_form.addRow("", self._dimse_echo_btn)
        self._dimse_echo_label = QLabel()
        dimse_form.addRow("", self._dimse_echo_label)
        form.addRow(dimse_group)

        # STOW-RS URL
        self._stow_url_edit = QLineEdit()
        self._stow_url_edit.setPlaceholderText(tr("server_settings.stow_url"))
        form.addRow(tr("server_settings.stow_url"), self._stow_url_edit)

        # Profiles button
        profiles_row = QHBoxLayout()
        self._profiles_btn = QPushButton(tr("server_settings.profiles_button"))
        self._profiles_btn.clicked.connect(self._on_profiles)
        profiles_row.addWidget(self._profiles_btn)
        profiles_row.addStretch()
        form.addRow(tr("server_settings.profiles_label"), profiles_row)

        self.set_settings(load_server_settings())

    def _sync_auth_fields(self) -> None:
        basic = self._auth_mode.currentData() == "basic"
        self._username_edit.setEnabled(basic)
        self._password_edit.setEnabled(basic)

    def _sync_dimse_fields(self) -> None:
        enabled = self._dimse_enabled.isChecked()
        self._dimse_ae_edit.setEnabled(enabled)
        self._dimse_called_ae_edit.setEnabled(enabled)
        self._dimse_host_edit.setEnabled(enabled)
        self._dimse_port_edit.setEnabled(enabled)
        self._dimse_echo_btn.setEnabled(enabled)

    def _on_profiles(self) -> None:
        from echo_personal_tool.presentation.server_profile_dialog import ServerProfileDialog
        from echo_personal_tool.presentation.ui_animations import exec_animated

        dlg = ServerProfileDialog(self.settings(), self)
        if exec_animated(dlg) == QDialog.DialogCode.Accepted:
            self.set_settings(dlg.selected_settings)

    def _on_dimse_echo(self) -> None:
        from echo_personal_tool.infrastructure.dimse_client import PynetdimseClient
        from echo_personal_tool.presentation.ui_animations import set_button_loading

        settings = self.settings()
        client = PynetdimseClient.from_settings(settings)
        self._dimse_echo_label.setText("...")
        set_button_loading(self._dimse_echo_btn, True, "…")
        signals = _DimseEchoSignals()
        signals.result.connect(self._on_dimse_echo_result)
        task = _DimseEchoTask(client, signals)
        QThreadPool.globalInstance().start(task)

    def _on_dimse_echo_result(self, ok: bool, message: str) -> None:
        from echo_personal_tool.presentation.ui_animations import set_button_loading
        set_button_loading(self._dimse_echo_btn, False)
        if ok:
            self._dimse_echo_label.setText(tr("server_settings.dimse_echo_ok"))
        else:
            self._dimse_echo_label.setText(tr("server_settings.dimse_echo_fail", message=message))

    def settings(self) -> ServerSettings:
        return ServerSettings(
            description=self._description_edit.text().strip(),
            url=self._url_edit.text().strip(),
            username=self._username_edit.text(),
            password=self._password_edit.text(),
            auth_mode=str(self._auth_mode.currentData()),
            http_headers=self._headers_edit.toPlainText().strip(),
            use_mock=self._mock_check.isChecked(),
            dimse_enabled=self._dimse_enabled.isChecked(),
            dimse_ae_title=self._dimse_ae_edit.text().strip() or "ECHO2026",
            dimse_called_ae=self._dimse_called_ae_edit.text().strip() or "ORTHANC",
            dimse_host=self._dimse_host_edit.text().strip() or "127.0.0.1",
            dimse_port=int(self._dimse_port_edit.text().strip() or "4242"),
            stow_dicom_web_url=self._stow_url_edit.text().strip(),
            retrieval_source=str(self._retrieval_source_combo.currentData() or "auto"),
            dimse_retrieval_mode="cget",  # derived from retrieval_source
            dimse_use_tls=self._dimse_use_tls.isChecked(),
            dimse_tls_verify=self._dimse_tls_verify.isChecked(),
            dimse_tls_ca_path=self._dimse_tls_ca_path.text().strip(),
            dimse_tls_cert_path=self._dimse_tls_cert_path.text().strip(),
            dimse_tls_key_path=self._dimse_tls_key_path.text().strip(),
            dimse_scp_host=self._dimse_scp_host.text().strip() or "127.0.0.1",
            dimse_scp_port=int(self._dimse_scp_port.text().strip() or "11112"),
            dimse_scp_ae_title=self._dimse_scp_ae_title.text().strip(),
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
        self._dimse_enabled.setChecked(settings.dimse_enabled)
        self._dimse_ae_edit.setText(settings.dimse_ae_title)
        self._dimse_called_ae_edit.setText(settings.dimse_called_ae)
        self._dimse_host_edit.setText(settings.dimse_host)
        self._dimse_port_edit.setText(str(settings.dimse_port))
        self._stow_url_edit.setText(settings.stow_dicom_web_url)
        # New retrieval settings
        retrieval_idx = self._retrieval_source_combo.findData(settings.retrieval_source)
        self._retrieval_source_combo.setCurrentIndex(max(retrieval_idx, 0))
        self._dimse_use_tls.setChecked(settings.dimse_use_tls)
        self._dimse_tls_verify.setChecked(settings.dimse_tls_verify)
        self._dimse_tls_ca_path.setText(settings.dimse_tls_ca_path)
        self._dimse_tls_cert_path.setText(settings.dimse_tls_cert_path)
        self._dimse_tls_key_path.setText(settings.dimse_tls_key_path)
        self._dimse_scp_host.setText(settings.dimse_scp_host)
        self._dimse_scp_port.setText(str(settings.dimse_scp_port))
        self._dimse_scp_ae_title.setText(settings.dimse_scp_ae_title)
        self._sync_auth_fields()
        self._sync_dimse_fields()


def show_server_settings_dialog(parent: QWidget | None = None) -> bool:
    from echo_personal_tool.presentation.ui_animations import exec_animated
    dialog = ServerSettingsDialog(parent)
    return exec_animated(dialog) == QDialog.DialogCode.Accepted


class ServerSettingsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("server_settings.title"))

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


class _DimseEchoSignals(QObject):
    result = Signal(bool, str)


class _DimseEchoTask(QRunnable):
    """Run C-ECHO on a worker thread."""

    def __init__(self, client, signals: _DimseEchoSignals) -> None:  # noqa: ANN001
        super().__init__()
        self._client = client
        self._signals = signals
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            ok = self._client.c_echo()
            if ok:
                self._signals.result.emit(True, "")
            else:
                self._signals.result.emit(False, "no response")
        except Exception as exc:  # noqa: BLE001
            self._signals.result.emit(False, str(exc))
