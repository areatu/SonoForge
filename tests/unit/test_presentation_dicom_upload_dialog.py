"""Unit tests for presentation/dicom_upload_dialog.py."""

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


class TestRunDicomUploadDialogNoFiles:
    @patch("echo_personal_tool.presentation.dicom_upload_dialog.collect_dicom_bytes", return_value=[])
    @patch("echo_personal_tool.presentation.dicom_upload_dialog.QMessageBox.information")
    def test_shows_no_files_message(self, mock_info, mock_collect):
        from echo_personal_tool.presentation.dicom_upload_dialog import run_dicom_upload_dialog

        run_dicom_upload_dialog(None, [], ServerSettings())
        mock_info.assert_called_once()
        mock_collect.assert_called_once()


class TestRunDicomUploadDialogNoProtocol:
    @patch("echo_personal_tool.presentation.dicom_upload_dialog.collect_dicom_bytes", return_value=[b"data"])
    @patch("echo_personal_tool.presentation.dicom_upload_dialog.stow_upload_available", return_value=False)
    @patch("echo_personal_tool.presentation.dicom_upload_dialog.dimse_upload_available", return_value=False)
    @patch("echo_personal_tool.presentation.dicom_upload_dialog.QMessageBox.warning")
    def test_shows_no_protocol_warning(self, mock_warn, mock_dimse, mock_stow, mock_collect):
        from echo_personal_tool.presentation.dicom_upload_dialog import run_dicom_upload_dialog

        run_dicom_upload_dialog(None, [MagicMock()], ServerSettings())
        mock_warn.assert_called_once()


class TestRunDicomUploadDialogUserCancels:
    @patch("echo_personal_tool.presentation.dicom_upload_dialog.collect_dicom_bytes", return_value=[b"data"])
    @patch("echo_personal_tool.presentation.dicom_upload_dialog.stow_upload_available", return_value=True)
    @patch("echo_personal_tool.presentation.ui_animations.exec_animated", return_value=0)  # Rejected
    def test_returns_when_user_cancels(self, mock_exec, mock_stow, mock_collect):
        from echo_personal_tool.presentation.dicom_upload_dialog import run_dicom_upload_dialog

        # Should return without error
        run_dicom_upload_dialog(None, [MagicMock()], ServerSettings())
        mock_exec.assert_called_once()


class TestRunDicomUploadDialogMakeUploadTargetsFails:
    @patch("echo_personal_tool.presentation.dicom_upload_dialog.collect_dicom_bytes", return_value=[b"data"])
    @patch("echo_personal_tool.presentation.dicom_upload_dialog.stow_upload_available", return_value=True)
    @patch("echo_personal_tool.presentation.ui_animations.exec_animated", return_value=1)  # Accepted
    @patch(
        "echo_personal_tool.presentation.dicom_upload_dialog.make_upload_targets",
        side_effect=ValueError("bad config"),
    )
    @patch("echo_personal_tool.presentation.dicom_upload_dialog.QMessageBox.warning")
    def test_shows_warning_on_upload_target_error(self, mock_warn, mock_targets, mock_exec, mock_stow, mock_collect):
        from echo_personal_tool.presentation.dicom_upload_dialog import run_dicom_upload_dialog

        run_dicom_upload_dialog(None, [MagicMock()], ServerSettings())
        mock_warn.assert_called_once()
