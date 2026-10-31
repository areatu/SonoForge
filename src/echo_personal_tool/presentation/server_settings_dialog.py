"""Orthanc / DICOMweb server settings (embedded form + standalone dialog)."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
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
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.application.localization import tr
from echo_personal_tool.application.server_io import (
    ServerSettings,
    compute_insecure_exception_scope,
    describe_insecure_transport_modes,
    effective_exceptions_for_settings,
    evaluate_server_settings,
    grant_insecure_exception,
    load_server_settings,
    make_dimse_client,
    save_server_settings,
)
from echo_personal_tool.application.transport_policy import evaluate_dimse
from echo_personal_tool.presentation.dark_theme import get_theme_tokens
from echo_personal_tool.presentation.styled_dialogs import localize_dialog_button_box, theme_button_box_icons


def format_transport_status_text(settings: ServerSettings) -> tuple[str, bool]:
    """Return ``(status_text, is_insecure_or_blocked)`` for ``settings``."""
    if not isinstance(settings, ServerSettings) or settings.use_mock:
        return ("", False)
    modes = describe_insecure_transport_modes(settings)
    profile = evaluate_server_settings(settings)
    if settings.needs_confirmation or profile.blocked:
        modes_str = ", ".join(modes) if modes else "; ".join(f.message for d in profile.blocked for f in d.findings)
        return (tr("server_settings.insecure_status_unconfirmed", modes=modes_str), True)
    if profile.insecure or modes:
        return (tr("server_settings.insecure_status_active", modes=", ".join(modes)), True)
    return (tr("server_settings.insecure_status_secure"), False)


def prompt_transport_policy_confirmation(
    parent: QWidget | None,
    settings: ServerSettings,
    *,
    for_migration: bool = False,
) -> str:
    """Ask the user how to handle an insecure server profile before network use.

    Returns one of ``"configure_tls"``, ``"allow_exception"``, or ``"cancel"``.
    """
    modes = describe_insecure_transport_modes(settings)
    profile = evaluate_server_settings(settings)
    issues = ", ".join(modes) if modes else "; ".join(f.message for d in profile.blocked for f in d.findings)
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    if for_migration:
        box.setWindowTitle(tr("server_settings.insecure_migration_title"))
        box.setText(
            tr(
                "server_settings.insecure_migration_msg",
                profile=settings.description or settings.url,
                issues=issues,
            )
        )
    else:
        box.setWindowTitle(tr("server_settings.insecure_transport_title"))
        box.setText(tr("server_settings.insecure_transport_msg", issues=issues))

    configure_btn = box.addButton(
        tr("server_settings.insecure_action_configure_tls"),
        QMessageBox.ButtonRole.ActionRole,
    )
    allow_btn = box.addButton(
        tr("server_settings.insecure_action_allow_server"),
        QMessageBox.ButtonRole.DestructiveRole,
    )
    cancel_btn = box.addButton(
        tr("server_settings.insecure_action_cancel"),
        QMessageBox.ButtonRole.RejectRole,
    )
    box.setDefaultButton(configure_btn)
    box.setEscapeButton(cancel_btn)
    box.exec()
    clicked = box.clickedButton()
    if clicked is configure_btn:
        return "configure_tls"
    if clicked is allow_btn:
        return "allow_exception"
    return "cancel"


def ensure_transport_confirmed_before_network(
    parent: QWidget | None,
    settings: ServerSettings,
) -> ServerSettings | None:
    """Ensure ``settings`` is permitted by the transport policy before any network call.

    Returns the confirmed :class:`ServerSettings` or ``None`` if the user cancelled.
    """
    if not isinstance(settings, ServerSettings) or settings.use_mock:
        return settings
    profile = evaluate_server_settings(settings)
    if profile.allowed and not settings.needs_confirmation:
        return settings
    if any(not decision.requires_exception for decision in profile.blocked):
        details = "; ".join(f.message for d in profile.blocked for f in d.findings)
        QMessageBox.warning(parent, tr("server_settings.insecure_transport_title"), details)
        return None
    action = prompt_transport_policy_confirmation(
        parent,
        settings,
        for_migration=settings.needs_confirmation,
    )
    if action == "allow_exception":
        confirmed = grant_insecure_exception(settings)
        save_server_settings(confirmed)
        return confirmed
    if action == "configure_tls":
        if show_server_settings_dialog(parent):
            reloaded = load_server_settings()
            if evaluate_server_settings(reloaded).allowed and not reloaded.needs_confirmation:
                return reloaded
        return None
    return None


class ServerSettingsForm(QWidget):
    """Reusable DICOMweb connection fields (Weasis-style WEB node)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        tokens = get_theme_tokens()
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
        self._headers_edit.setPlaceholderText("Authorization: Basic cGFjczpwYcIBTU2NBRERS\nX-Custom-Header: value")
        self._headers_edit.setFixedHeight(72)
        self._mock_check = QCheckBox(tr("server_settings.mock"))
        self._tls_verify_check = QCheckBox(tr("server_settings.verify_certificate"))
        self._tls_verify_check.setChecked(True)
        self._tls_verify_warning = QLabel(tr("server_settings.tls_verify_warning"))
        self._tls_verify_warning.setStyleSheet(f"color: {tokens['state.warn']}; font-weight: bold;")
        self._tls_verify_warning.hide()
        self._tls_verify_check.toggled.connect(lambda checked: self._tls_verify_warning.setVisible(not checked))
        self._tls_ca_edit = QLineEdit()
        self._tls_ca_edit.setPlaceholderText("/path/to/ca.pem")
        hint = tr("server_settings.ca_bundle_hint")
        self._tls_ca_edit.setToolTip(hint)
        self._tls_ca_hint = QLabel(hint)
        self._tls_ca_hint.setWordWrap(True)
        self._tls_ca_hint.setStyleSheet(f"color: {tokens['text.2']};")

        form = QFormLayout(self)
        form.addRow(tr("server_settings.description"), self._description_edit)
        form.addRow("DICOMweb URL:", self._url_edit)
        form.addRow(tr("server_settings.auth"), self._auth_mode)
        form.addRow(tr("server_settings.username"), self._username_edit)
        form.addRow(tr("server_settings.password"), self._password_edit)
        form.addRow(tr("server_settings.http_headers"), self._headers_edit)
        form.addRow("", self._mock_check)
        form.addRow("", self._tls_verify_check)
        form.addRow("", self._tls_verify_warning)
        form.addRow(tr("server_settings.ca_bundle_label"), self._tls_ca_edit)
        form.addRow("", self._tls_ca_hint)

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
        dimse_form.addRow(tr("server_settings.retrieval_source"), self._retrieval_source_combo)

        # TLS settings
        self._dimse_use_tls = QCheckBox(tr("server_settings.use_tls"))
        self._dimse_use_tls.toggled.connect(self._sync_dimse_fields)
        dimse_form.addRow("", self._dimse_use_tls)
        self._dimse_tls_verify = QCheckBox(tr("server_settings.verify_certificate"))
        dimse_form.addRow("", self._dimse_tls_verify)
        self._dimse_tls_warning = QLabel(tr("server_settings.tls_verify_warning"))
        self._dimse_tls_warning.setStyleSheet(f"color: {tokens['state.warn']}; font-weight: bold;")
        self._dimse_tls_warning.hide()
        dimse_form.addRow("", self._dimse_tls_warning)
        self._dimse_tls_verify.toggled.connect(lambda checked: self._dimse_tls_warning.setVisible(not checked))
        self._dimse_tls_ca_path = QLineEdit()
        self._dimse_tls_ca_path.setPlaceholderText("/path/to/ca.pem")
        dimse_form.addRow(tr("server_settings.ca_certificate"), self._dimse_tls_ca_path)
        self._dimse_tls_cert_path = QLineEdit()
        self._dimse_tls_cert_path.setPlaceholderText("/path/to/client.pem")
        dimse_form.addRow(tr("server_settings.client_certificate"), self._dimse_tls_cert_path)
        self._dimse_tls_key_path = QLineEdit()
        self._dimse_tls_key_path.setPlaceholderText("/path/to/client.key")
        dimse_form.addRow(tr("server_settings.client_key"), self._dimse_tls_key_path)

        # Embedded Storage SCP for C-MOVE
        dimse_form.addRow("--- " + tr("server_settings.embedded_scp") + " ---", QLabel())
        self._dimse_scp_host = QLineEdit()
        self._dimse_scp_host.setPlaceholderText("127.0.0.1")
        dimse_form.addRow(tr("server_settings.scp_host"), self._dimse_scp_host)
        self._dimse_scp_port = QLineEdit()
        self._dimse_scp_port.setPlaceholderText("11112")
        dimse_form.addRow(tr("server_settings.scp_port"), self._dimse_scp_port)
        self._dimse_scp_ae_title = QLineEdit()
        self._dimse_scp_ae_title.setPlaceholderText(tr("server_settings.scp_ae_placeholder"))
        dimse_form.addRow(tr("server_settings.scp_ae_title"), self._dimse_scp_ae_title)

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

        # Visible transport security status banner
        self._transport_status_label = QLabel()
        self._transport_status_label.setWordWrap(True)
        form.addRow("", self._transport_status_label)

        # Profiles button
        profiles_row = QHBoxLayout()
        self._profiles_btn = QPushButton(tr("server_settings.profiles_button"))
        self._profiles_btn.clicked.connect(self._on_profiles)
        profiles_row.addWidget(self._profiles_btn)
        profiles_row.addStretch()
        form.addRow(tr("server_settings.profiles_label"), profiles_row)

        for signal in (
            self._url_edit.textChanged,
            self._tls_ca_edit.textChanged,
            self._stow_url_edit.textChanged,
            self._dimse_host_edit.textChanged,
            self._dimse_port_edit.textChanged,
            self._dimse_tls_ca_path.textChanged,
            self._tls_verify_check.toggled,
            self._mock_check.toggled,
            self._dimse_enabled.toggled,
            self._dimse_use_tls.toggled,
            self._dimse_tls_verify.toggled,
        ):
            signal.connect(self._update_transport_status_banner)

        self._settings_cache = load_server_settings()
        self.set_settings(self._settings_cache)

    def _update_transport_status_banner(self, *_args: object) -> None:
        if not hasattr(self, "_transport_status_label"):
            return
        text, is_insecure = format_transport_status_text(self.settings())
        self._transport_status_label.setText(text)
        if not text:
            self._transport_status_label.hide()
            return
        tokens = get_theme_tokens()
        if is_insecure:
            self._transport_status_label.setStyleSheet(f"color: {tokens['state.warn']}; font-weight: bold;")
        else:
            self._transport_status_label.setStyleSheet(f"color: {tokens['text.2']};")
        self._transport_status_label.show()

    def focus_tls_configuration(self) -> None:
        """Focus the relevant TLS / HTTPS / CA field so the user can secure the profile."""
        url_text = self._url_edit.text().strip().lower()
        if url_text.startswith("http://"):
            self._url_edit.setFocus()
            self._url_edit.selectAll()
            return
        if not self._tls_verify_check.isChecked():
            self._tls_ca_edit.setFocus()
            return
        if self._dimse_enabled.isChecked():
            if not self._dimse_use_tls.isChecked():
                self._dimse_use_tls.setFocus()
            else:
                self._dimse_tls_ca_path.setFocus()

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
        # TLS/SCP/retrieval fields
        self._retrieval_source_combo.setEnabled(enabled)
        self._dimse_use_tls.setEnabled(enabled)
        self._dimse_tls_verify.setEnabled(enabled and self._dimse_use_tls.isChecked())
        self._dimse_tls_ca_path.setEnabled(enabled and self._dimse_use_tls.isChecked())
        self._dimse_tls_cert_path.setEnabled(enabled and self._dimse_use_tls.isChecked())
        self._dimse_tls_key_path.setEnabled(enabled and self._dimse_use_tls.isChecked())
        self._dimse_scp_host.setEnabled(enabled)
        self._dimse_scp_port.setEnabled(enabled)
        self._dimse_scp_ae_title.setEnabled(enabled)

    def _on_profiles(self) -> None:
        from echo_personal_tool.presentation.server_profile_dialog import ServerProfileDialog
        from echo_personal_tool.presentation.ui_animations import exec_animated

        dlg = ServerProfileDialog(self.settings(), self)
        if exec_animated(dlg) == QDialog.DialogCode.Accepted:
            self.set_settings(dlg.selected_settings)

    def _on_dimse_echo(self) -> None:
        from echo_personal_tool.presentation.ui_animations import set_button_loading

        settings = self.settings()
        if not settings.use_mock:
            decision = evaluate_dimse(
                settings.dimse_host,
                settings.dimse_port,
                use_tls=settings.dimse_use_tls,
                tls_verify=settings.dimse_tls_verify,
                tls_ca_path=settings.dimse_tls_ca_path,
                exceptions=effective_exceptions_for_settings(settings),
            )
            if decision.blocked and not decision.requires_exception:
                details = "; ".join(f.message for f in decision.findings)
                QMessageBox.warning(self, tr("server_settings.insecure_transport_title"), details)
                return
            if settings.needs_confirmation or decision.blocked:
                action = prompt_transport_policy_confirmation(
                    self,
                    replace(settings, dimse_enabled=True),
                    for_migration=settings.needs_confirmation,
                )
                if action == "allow_exception":
                    settings = grant_insecure_exception(replace(settings, dimse_enabled=True))
                    self.set_settings(settings)
                elif action == "configure_tls":
                    self.focus_tls_configuration()
                    return
                else:
                    return
        client = make_dimse_client(settings)
        if client is None:
            return
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

    def _preserved_settings(self) -> ServerSettings:
        """Last loaded/saved settings used to carry fields without a widget."""
        return getattr(self, "_settings_cache", ServerSettings())

    def port_validation_error(self) -> str | None:
        """Return a localized error message for invalid port fields, if any."""
        checks = (
            (tr("server_settings.dimse_port"), self._dimse_port_edit, 1, 65535),
            (tr("server_settings.scp_port"), self._dimse_scp_port, 1, 65535),
        )
        for label, widget, low, high in checks:
            text = widget.text().strip()
            if not text:
                continue
            try:
                value = int(text)
            except ValueError:
                return tr("server_settings.port_invalid", field=label, value=text)
            if not (low <= value <= high):
                return tr("server_settings.port_out_of_range", field=label, value=text)
        return None

    @staticmethod
    def _parse_port(text: str, default: int) -> int:
        """Parse a port field, falling back to `default` when empty/invalid.

        Invalid text is reported by :meth:`port_validation_error` before
        saving; this tolerant parse keeps other callers (e.g. profile dialog)
        from crashing on intermediate user input.
        """
        stripped = text.strip()
        if not stripped:
            return default
        try:
            return int(stripped)
        except ValueError:
            return default

    def settings(self) -> ServerSettings:
        preserved = self._preserved_settings()
        candidate = ServerSettings(
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
            dimse_port=self._parse_port(self._dimse_port_edit.text(), 4242),
            stow_dicom_web_url=self._stow_url_edit.text().strip(),
            query_source=preserved.query_source,
            retrieval_source=str(self._retrieval_source_combo.currentData() or "auto"),
            dimse_retrieval_mode="cmove" if self._retrieval_source_combo.currentData() == "cmove" else "cget",
            dimse_use_tls=self._dimse_use_tls.isChecked(),
            dimse_tls_verify=self._dimse_tls_verify.isChecked(),
            dimse_tls_ca_path=self._dimse_tls_ca_path.text().strip(),
            dimse_tls_cert_path=self._dimse_tls_cert_path.text().strip(),
            dimse_tls_key_path=self._dimse_tls_key_path.text().strip(),
            dimse_scp_host=self._dimse_scp_host.text().strip() or "127.0.0.1",
            dimse_scp_port=self._parse_port(self._dimse_scp_port.text(), 11112),
            dimse_scp_ae_title=self._dimse_scp_ae_title.text().strip(),
            network_timeout=preserved.network_timeout,
            tls_verify=self._tls_verify_check.isChecked(),
            tls_ca_path=self._tls_ca_edit.text().strip(),
        )
        candidate_scope = compute_insecure_exception_scope(candidate)
        if (
            preserved.allow_insecure_transport
            and not preserved.needs_confirmation
            and preserved.insecure_exception_scope == candidate_scope
        ):
            return replace(
                candidate,
                allow_insecure_transport=True,
                insecure_exception_scope=preserved.insecure_exception_scope,
                needs_confirmation=False,
            )
        if preserved.needs_confirmation and compute_insecure_exception_scope(preserved) == candidate_scope:
            return replace(candidate, needs_confirmation=True)
        return candidate

    def set_settings(self, settings: ServerSettings) -> None:
        self._settings_cache = settings
        self._description_edit.setText(settings.description)
        self._url_edit.setText(settings.url)
        auth_index = self._auth_mode.findData(settings.auth_mode)
        self._auth_mode.setCurrentIndex(max(auth_index, 0))
        self._username_edit.setText(settings.username)
        self._password_edit.setText(settings.password)
        self._headers_edit.setPlainText(settings.http_headers)
        self._mock_check.setChecked(settings.use_mock)
        self._tls_verify_check.setChecked(settings.tls_verify)
        self._tls_ca_edit.setText(settings.tls_ca_path)
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
        self._update_transport_status_banner()


def show_server_settings_dialog(parent: QWidget | None = None) -> bool:
    from echo_personal_tool.presentation.ui_animations import exec_animated

    dialog = ServerSettingsDialog(parent)
    return exec_animated(dialog) == QDialog.DialogCode.Accepted


class ServerSettingsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("server_settings.title"))

        self._form = ServerSettingsForm(self)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        localize_dialog_button_box(buttons)
        theme_button_box_icons(buttons)

        layout = QVBoxLayout(self)
        layout.addWidget(self._form)
        layout.addWidget(buttons)

    def _on_accept(self) -> None:
        port_error = self._form.port_validation_error()
        if port_error:
            QMessageBox.warning(self, tr("server_settings.title"), port_error)
            return
        settings = self._form.settings()
        if not settings.use_mock:
            profile = evaluate_server_settings(settings)
            if any(not decision.requires_exception for decision in profile.blocked):
                details = "; ".join(f.message for d in profile.blocked for f in d.findings)
                QMessageBox.warning(self, tr("server_settings.insecure_transport_title"), details)
                return
            if settings.needs_confirmation or profile.blocked:
                action = prompt_transport_policy_confirmation(
                    self,
                    settings,
                    for_migration=settings.needs_confirmation,
                )
                if action == "allow_exception":
                    settings = grant_insecure_exception(settings)
                    self._form.set_settings(settings)
                elif action == "configure_tls":
                    self._form.focus_tls_configuration()
                    return
                else:
                    return
        save_server_settings(settings)
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
