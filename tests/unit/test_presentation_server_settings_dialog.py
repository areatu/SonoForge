"""Unit tests for presentation/server_settings_dialog.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from echo_personal_tool.infrastructure.server_settings import ServerSettings

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def _setup_qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def _default_settings(**overrides) -> ServerSettings:
    return ServerSettings(**overrides)


class TestServerSettingsFormConstruction:
    @patch("echo_personal_tool.presentation.server_settings_dialog.load_server_settings")
    def test_creates_with_default_settings(self, mock_load):
        mock_load.return_value = _default_settings()
        from echo_personal_tool.presentation.server_settings_dialog import ServerSettingsForm

        form = ServerSettingsForm()
        assert form._description_edit is not None
        assert form._url_edit is not None
        assert form._dimse_enabled is not None


class TestServerSettingsFormSetSettings:
    @patch("echo_personal_tool.presentation.server_settings_dialog.load_server_settings")
    def test_set_settings_populates_fields(self, mock_load):
        mock_load.return_value = _default_settings()
        from echo_personal_tool.presentation.server_settings_dialog import ServerSettingsForm

        form = ServerSettingsForm()
        s = _default_settings(
            description="Test Server",
            url="http://192.168.1.5:8042/dicom-web",
            username="admin",
            password="secret",
            dimse_enabled=True,
            dimse_ae_title="MYAE",
            dimse_port=9999,
            dimse_host="10.0.0.1",
        )
        form.set_settings(s)

        assert form._description_edit.text() == "Test Server"
        assert form._url_edit.text() == "http://192.168.1.5:8042/dicom-web"
        assert form._username_edit.text() == "admin"
        assert form._password_edit.text() == "secret"
        assert form._dimse_enabled.isChecked()
        assert form._dimse_ae_edit.text() == "MYAE"
        assert form._dimse_port_edit.text() == "9999"
        assert form._dimse_host_edit.text() == "10.0.0.1"


class TestServerSettingsFormGetSettings:
    @patch("echo_personal_tool.presentation.server_settings_dialog.load_server_settings")
    def test_settings_round_trip(self, mock_load):
        mock_load.return_value = _default_settings()
        from echo_personal_tool.presentation.server_settings_dialog import ServerSettingsForm

        form = ServerSettingsForm()
        s = _default_settings(
            description="My PACS",
            url="http://pacs:8042/dicom-web",
            dimse_enabled=True,
            dimse_port=4242,
        )
        form.set_settings(s)
        result = form.settings()
        assert result.description == "My PACS"
        assert result.url == "http://pacs:8042/dicom-web"
        assert result.dimse_enabled is True
        assert result.dimse_port == 4242


class TestServerSettingsFormAuthMode:
    @patch("echo_personal_tool.presentation.server_settings_dialog.load_server_settings")
    def test_auth_none_disables_user_fields(self, mock_load):
        mock_load.return_value = _default_settings(auth_mode="none")
        from echo_personal_tool.presentation.server_settings_dialog import ServerSettingsForm

        form = ServerSettingsForm()
        assert not form._username_edit.isEnabled()
        assert not form._password_edit.isEnabled()

    @patch("echo_personal_tool.presentation.server_settings_dialog.load_server_settings")
    def test_auth_basic_enables_user_fields(self, mock_load):
        mock_load.return_value = _default_settings(auth_mode="basic")
        from echo_personal_tool.presentation.server_settings_dialog import ServerSettingsForm

        form = ServerSettingsForm()
        assert form._username_edit.isEnabled()
        assert form._password_edit.isEnabled()


class TestServerSettingsFormDimseFields:
    @patch("echo_personal_tool.presentation.server_settings_dialog.load_server_settings")
    def test_dimse_disabled_disables_fields(self, mock_load):
        mock_load.return_value = _default_settings(dimse_enabled=False)
        from echo_personal_tool.presentation.server_settings_dialog import ServerSettingsForm

        form = ServerSettingsForm()
        assert not form._dimse_ae_edit.isEnabled()
        assert not form._dimse_host_edit.isEnabled()
        assert not form._dimse_port_edit.isEnabled()
        assert not form._dimse_echo_btn.isEnabled()

    @patch("echo_personal_tool.presentation.server_settings_dialog.load_server_settings")
    def test_dimse_enabled_enables_fields(self, mock_load):
        mock_load.return_value = _default_settings(dimse_enabled=True)
        from echo_personal_tool.presentation.server_settings_dialog import ServerSettingsForm

        form = ServerSettingsForm()
        assert form._dimse_ae_edit.isEnabled()
        assert form._dimse_host_edit.isEnabled()
        assert form._dimse_port_edit.isEnabled()
        assert form._dimse_echo_btn.isEnabled()


class TestServerSettingsFormDimseEcho:
    @patch("echo_personal_tool.presentation.server_settings_dialog.QThreadPool")
    @patch("echo_personal_tool.presentation.ui_animations.set_button_loading")
    @patch("echo_personal_tool.infrastructure.dimse_client.PynetdimseClient")
    @patch("echo_personal_tool.presentation.server_settings_dialog.load_server_settings")
    def test_echo_calls_client(self, mock_load, mock_client_cls, mock_loading, mock_pool):
        mock_load.return_value = _default_settings()
        from echo_personal_tool.presentation.server_settings_dialog import ServerSettingsForm

        form = ServerSettingsForm()
        form._on_dimse_echo()
        mock_client_cls.from_settings.assert_called_once()


class TestServerSettingsFormDimseEchoResult:
    @patch("echo_personal_tool.presentation.ui_animations.set_button_loading")
    @patch("echo_personal_tool.presentation.server_settings_dialog.load_server_settings")
    def test_echo_ok_updates_label(self, mock_load, mock_loading):
        mock_load.return_value = _default_settings()
        from echo_personal_tool.presentation.server_settings_dialog import ServerSettingsForm

        form = ServerSettingsForm()
        form._on_dimse_echo_result(True, "")
        assert "ok" in form._dimse_echo_label.text().lower() or form._dimse_echo_label.text() != ""

    @patch("echo_personal_tool.presentation.ui_animations.set_button_loading")
    @patch("echo_personal_tool.presentation.server_settings_dialog.load_server_settings")
    def test_echo_fail_updates_label(self, mock_load, mock_loading):
        mock_load.return_value = _default_settings()
        from echo_personal_tool.presentation.server_settings_dialog import ServerSettingsForm

        form = ServerSettingsForm()
        form._on_dimse_echo_result(False, "timeout")
        assert "timeout" in form._dimse_echo_label.text()


class TestServerSettingsDialogConstruction:
    @patch("echo_personal_tool.presentation.server_settings_dialog.load_server_settings")
    def test_creates_dialog(self, mock_load):
        mock_load.return_value = _default_settings()
        from echo_personal_tool.presentation.server_settings_dialog import ServerSettingsDialog

        dlg = ServerSettingsDialog()
        assert dlg.windowTitle() != ""
        assert dlg._form is not None


class TestServerSettingsDialogAccept:
    @patch("echo_personal_tool.presentation.server_settings_dialog.save_server_settings")
    @patch("echo_personal_tool.presentation.server_settings_dialog.load_server_settings")
    def test_accept_saves_settings(self, mock_load, mock_save):
        mock_load.return_value = _default_settings()
        from echo_personal_tool.presentation.server_settings_dialog import ServerSettingsDialog

        dlg = ServerSettingsDialog()
        dlg._on_accept()
        mock_save.assert_called_once()


class TestDimseEchoTask:
    def test_run_success(self):
        from echo_personal_tool.presentation.server_settings_dialog import (
            _DimseEchoSignals,
            _DimseEchoTask,
        )

        mock_client = MagicMock()
        mock_client.c_echo.return_value = True
        signals = _DimseEchoSignals()

        received = []
        signals.result.connect(lambda ok, msg: received.append((ok, msg)))

        task = _DimseEchoTask(mock_client, signals)
        task.run()

        assert len(received) == 1
        assert received[0] == (True, "")

    def test_run_failure(self):
        from echo_personal_tool.presentation.server_settings_dialog import (
            _DimseEchoSignals,
            _DimseEchoTask,
        )

        mock_client = MagicMock()
        mock_client.c_echo.return_value = False
        signals = _DimseEchoSignals()

        received = []
        signals.result.connect(lambda ok, msg: received.append((ok, msg)))

        task = _DimseEchoTask(mock_client, signals)
        task.run()

        assert received == [(False, "no response")]

    def test_run_exception(self):
        from echo_personal_tool.presentation.server_settings_dialog import (
            _DimseEchoSignals,
            _DimseEchoTask,
        )

        mock_client = MagicMock()
        mock_client.c_echo.side_effect = RuntimeError("Connection refused")
        signals = _DimseEchoSignals()

        received = []
        signals.result.connect(lambda ok, msg: received.append((ok, msg)))

        task = _DimseEchoTask(mock_client, signals)
        task.run()

        assert received == [(False, "Connection refused")]
