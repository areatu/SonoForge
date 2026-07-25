"""Unit tests for presentation/styled_dialogs.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def _setup_qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


_DARK_PALETTE = {
    "bg_panel": "#1a1a1a",
    "text": "#ffffff",
    "bg_control": "#2a2a2a",
    "accent_tab": "#2196f3",
    "border": "#3a3a3a",
    "bg_button_hover": "#3a3a3a",
    "bg_button_pressed": "#4a4a4a",
}


def _make_mockFileDialog(*, accepted=False):
    """Create a mock QFileDialog with DialogCode enum set correctly."""
    from PySide6.QtWidgets import QFileDialog

    mock_cls = MagicMock()
    mock_dialog = MagicMock()
    # Set the DialogCode.Accepted to be the same sentinel as exec() return
    sentinel = object()
    mock_cls.DialogCode.Accepted = sentinel
    mock_dialog.exec.return_value = sentinel if accepted else object()
    mock_cls.return_value = mock_dialog
    return mock_cls, mock_dialog


class TestStyleDialog:
    @patch("echo_personal_tool.presentation.styled_dialogs.get_theme_palette")
    def test_style_dialog_applies_palette(self, mock_palette):
        from PySide6.QtWidgets import QFileDialog

        from echo_personal_tool.presentation.styled_dialogs import _style_dialog

        mock_palette.return_value = _DARK_PALETTE
        dialog = QFileDialog()
        _style_dialog(dialog)
        assert dialog.palette() is not None
        dialog.close()


class TestStyledOpenFile:
    @patch("echo_personal_tool.presentation.styled_dialogs.get_theme_palette", return_value=_DARK_PALETTE)
    def test_returns_file_when_accepted(self, mock_palette):
        from echo_personal_tool.presentation.styled_dialogs import styled_open_file

        mock_cls, mock_dialog = _make_mockFileDialog(accepted=True)
        mock_dialog.selectedFiles.return_value = ["/tmp/test.dcm"]
        mock_dialog.selectedNameFilter.return_value = "DICOM (*.dcm)"

        with patch("echo_personal_tool.presentation.styled_dialogs.QFileDialog", mock_cls):
            result = styled_open_file(title="Open")
        assert result == ("/tmp/test.dcm", "DICOM (*.dcm)")

    @patch("echo_personal_tool.presentation.styled_dialogs.get_theme_palette", return_value=_DARK_PALETTE)
    def test_returns_empty_when_rejected(self, mock_palette):
        from echo_personal_tool.presentation.styled_dialogs import styled_open_file

        mock_cls, mock_dialog = _make_mockFileDialog(accepted=False)

        with patch("echo_personal_tool.presentation.styled_dialogs.QFileDialog", mock_cls):
            result = styled_open_file()
        assert result == ("", "")

    @patch("echo_personal_tool.presentation.styled_dialogs.get_theme_palette", return_value=_DARK_PALETTE)
    def test_returns_empty_when_no_files(self, mock_palette):
        from echo_personal_tool.presentation.styled_dialogs import styled_open_file

        mock_cls, mock_dialog = _make_mockFileDialog(accepted=True)
        mock_dialog.selectedFiles.return_value = []

        with patch("echo_personal_tool.presentation.styled_dialogs.QFileDialog", mock_cls):
            result = styled_open_file()
        assert result == ("", "")


class TestStyledOpenFiles:
    @patch("echo_personal_tool.presentation.styled_dialogs.get_theme_palette", return_value=_DARK_PALETTE)
    def test_returns_multiple_files(self, mock_palette):
        from echo_personal_tool.presentation.styled_dialogs import styled_open_files

        mock_cls, mock_dialog = _make_mockFileDialog(accepted=True)
        mock_dialog.selectedFiles.return_value = ["/tmp/a.dcm", "/tmp/b.dcm"]

        with patch("echo_personal_tool.presentation.styled_dialogs.QFileDialog", mock_cls):
            result = styled_open_files()
        assert result == ["/tmp/a.dcm", "/tmp/b.dcm"]

    @patch("echo_personal_tool.presentation.styled_dialogs.get_theme_palette", return_value=_DARK_PALETTE)
    def test_returns_empty_list_when_rejected(self, mock_palette):
        from echo_personal_tool.presentation.styled_dialogs import styled_open_files

        mock_cls, mock_dialog = _make_mockFileDialog(accepted=False)

        with patch("echo_personal_tool.presentation.styled_dialogs.QFileDialog", mock_cls):
            result = styled_open_files()
        assert result == []


class TestStyledSaveFile:
    @patch("echo_personal_tool.presentation.styled_dialogs.get_theme_palette", return_value=_DARK_PALETTE)
    def test_returns_saved_path(self, mock_palette):
        from echo_personal_tool.presentation.styled_dialogs import styled_save_file

        mock_cls, mock_dialog = _make_mockFileDialog(accepted=True)
        mock_dialog.selectedFiles.return_value = ["/tmp/report.pdf"]
        mock_dialog.selectedNameFilter.return_value = "PDF (*.pdf)"

        with patch("echo_personal_tool.presentation.styled_dialogs.QFileDialog", mock_cls):
            result = styled_save_file()
        assert result == ("/tmp/report.pdf", "PDF (*.pdf)")

    @patch("echo_personal_tool.presentation.styled_dialogs.get_theme_palette", return_value=_DARK_PALETTE)
    def test_returns_empty_when_rejected(self, mock_palette):
        from echo_personal_tool.presentation.styled_dialogs import styled_save_file

        mock_cls, mock_dialog = _make_mockFileDialog(accepted=False)

        with patch("echo_personal_tool.presentation.styled_dialogs.QFileDialog", mock_cls):
            result = styled_save_file()
        assert result == ("", "")


class TestStyledSelectDirectory:
    @patch("echo_personal_tool.presentation.styled_dialogs.get_theme_palette", return_value=_DARK_PALETTE)
    def test_returns_directory(self, mock_palette):
        from echo_personal_tool.presentation.styled_dialogs import styled_select_directory

        mock_cls, mock_dialog = _make_mockFileDialog(accepted=True)
        mock_dialog.selectedFiles.return_value = ["/data/dicoms"]

        with patch("echo_personal_tool.presentation.styled_dialogs.QFileDialog", mock_cls):
            result = styled_select_directory()
        assert result == "/data/dicoms"

    @patch("echo_personal_tool.presentation.styled_dialogs.get_theme_palette", return_value=_DARK_PALETTE)
    def test_returns_empty_when_rejected(self, mock_palette):
        from echo_personal_tool.presentation.styled_dialogs import styled_select_directory

        mock_cls, mock_dialog = _make_mockFileDialog(accepted=False)

        with patch("echo_personal_tool.presentation.styled_dialogs.QFileDialog", mock_cls):
            result = styled_select_directory()
        assert result == ""
