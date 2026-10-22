"""Tests for dialogs.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.gui


class TestStyledOpenFile:
    @patch("echo_personal_tool.constructor.dialogs._style_dialog")
    @patch("echo_personal_tool.constructor.dialogs.QFileDialog")
    def test_accepted(self, mock_dialog_cls, mock_style) -> None:
        from echo_personal_tool.constructor.dialogs import styled_open_file

        accepted = object()  # sentinel
        mock_dialog_cls.DialogCode.Accepted = accepted

        mock_dialog = MagicMock()
        mock_dialog_cls.return_value = mock_dialog
        mock_dialog.exec.return_value = accepted
        mock_dialog.selectedFiles.return_value = ["/tmp/test.txt"]
        mock_dialog.selectedNameFilter.return_value = "Text (*.txt)"

        result = styled_open_file(None, "Open", "/tmp", "Text (*.txt)")
        assert result == ("/tmp/test.txt", "Text (*.txt)")

    @patch("echo_personal_tool.constructor.dialogs._style_dialog")
    @patch("echo_personal_tool.constructor.dialogs.QFileDialog")
    def test_rejected(self, mock_dialog_cls, mock_style) -> None:
        from echo_personal_tool.constructor.dialogs import styled_open_file

        accepted = object()
        rejected = object()
        mock_dialog_cls.DialogCode.Accepted = accepted
        mock_dialog_cls.DialogCode.Rejected = rejected

        mock_dialog = MagicMock()
        mock_dialog_cls.return_value = mock_dialog
        mock_dialog.exec.return_value = rejected

        result = styled_open_file()
        assert result == ("", "")

    @patch("echo_personal_tool.constructor.dialogs._style_dialog")
    @patch("echo_personal_tool.constructor.dialogs.QFileDialog")
    def test_empty_files(self, mock_dialog_cls, mock_style) -> None:
        from echo_personal_tool.constructor.dialogs import styled_open_file

        accepted = object()
        mock_dialog_cls.DialogCode.Accepted = accepted

        mock_dialog = MagicMock()
        mock_dialog_cls.return_value = mock_dialog
        mock_dialog.exec.return_value = accepted
        mock_dialog.selectedFiles.return_value = []

        result = styled_open_file()
        assert result == ("", "")


class TestStyledOpenFiles:
    @patch("echo_personal_tool.constructor.dialogs._style_dialog")
    @patch("echo_personal_tool.constructor.dialogs.QFileDialog")
    def test_accepted_multiple(self, mock_dialog_cls, mock_style) -> None:
        from echo_personal_tool.constructor.dialogs import styled_open_files

        accepted = object()
        mock_dialog_cls.DialogCode.Accepted = accepted

        mock_dialog = MagicMock()
        mock_dialog_cls.return_value = mock_dialog
        mock_dialog.exec.return_value = accepted
        mock_dialog.selectedFiles.return_value = ["/tmp/a.txt", "/tmp/b.txt"]

        result = styled_open_files()
        assert result == ["/tmp/a.txt", "/tmp/b.txt"]

    @patch("echo_personal_tool.constructor.dialogs._style_dialog")
    @patch("echo_personal_tool.constructor.dialogs.QFileDialog")
    def test_rejected(self, mock_dialog_cls, mock_style) -> None:
        from echo_personal_tool.constructor.dialogs import styled_open_files

        accepted = object()
        rejected = object()
        mock_dialog_cls.DialogCode.Accepted = accepted
        mock_dialog_cls.DialogCode.Rejected = rejected

        mock_dialog = MagicMock()
        mock_dialog_cls.return_value = mock_dialog
        mock_dialog.exec.return_value = rejected

        result = styled_open_files()
        assert result == []


class TestStyledSaveFile:
    @patch("echo_personal_tool.constructor.dialogs._style_dialog")
    @patch("echo_personal_tool.constructor.dialogs.QFileDialog")
    def test_accepted(self, mock_dialog_cls, mock_style) -> None:
        from echo_personal_tool.constructor.dialogs import styled_save_file

        accepted = object()
        mock_dialog_cls.DialogCode.Accepted = accepted

        mock_dialog = MagicMock()
        mock_dialog_cls.return_value = mock_dialog
        mock_dialog.exec.return_value = accepted
        mock_dialog.selectedFiles.return_value = ["/tmp/out.yaml"]
        mock_dialog.selectedNameFilter.return_value = "YAML (*.yaml)"

        result = styled_save_file(None, "Save", "/tmp", "YAML (*.yaml)")
        assert result == ("/tmp/out.yaml", "YAML (*.yaml)")

    @patch("echo_personal_tool.constructor.dialogs._style_dialog")
    @patch("echo_personal_tool.constructor.dialogs.QFileDialog")
    def test_rejected(self, mock_dialog_cls, mock_style) -> None:
        from echo_personal_tool.constructor.dialogs import styled_save_file

        accepted = object()
        rejected = object()
        mock_dialog_cls.DialogCode.Accepted = accepted
        mock_dialog_cls.DialogCode.Rejected = rejected

        mock_dialog = MagicMock()
        mock_dialog_cls.return_value = mock_dialog
        mock_dialog.exec.return_value = rejected

        result = styled_save_file()
        assert result == ("", "")


class TestStyledSelectDirectory:
    @patch("echo_personal_tool.constructor.dialogs._style_dialog")
    @patch("echo_personal_tool.constructor.dialogs.QFileDialog")
    def test_accepted(self, mock_dialog_cls, mock_style) -> None:
        from echo_personal_tool.constructor.dialogs import styled_select_directory

        accepted = object()
        mock_dialog_cls.DialogCode.Accepted = accepted

        mock_dialog = MagicMock()
        mock_dialog_cls.return_value = mock_dialog
        mock_dialog.exec.return_value = accepted
        mock_dialog.selectedFiles.return_value = ["/tmp/dir"]

        result = styled_select_directory()
        assert result == "/tmp/dir"

    @patch("echo_personal_tool.constructor.dialogs._style_dialog")
    @patch("echo_personal_tool.constructor.dialogs.QFileDialog")
    def test_rejected(self, mock_dialog_cls, mock_style) -> None:
        from echo_personal_tool.constructor.dialogs import styled_select_directory

        accepted = object()
        rejected = object()
        mock_dialog_cls.DialogCode.Accepted = accepted
        mock_dialog_cls.DialogCode.Rejected = rejected

        mock_dialog = MagicMock()
        mock_dialog_cls.return_value = mock_dialog
        mock_dialog.exec.return_value = rejected

        result = styled_select_directory()
        assert result == ""

    @patch("echo_personal_tool.constructor.dialogs._style_dialog")
    @patch("echo_personal_tool.constructor.dialogs.QFileDialog")
    def test_empty_files(self, mock_dialog_cls, mock_style) -> None:
        from echo_personal_tool.constructor.dialogs import styled_select_directory

        accepted = object()
        mock_dialog_cls.DialogCode.Accepted = accepted

        mock_dialog = MagicMock()
        mock_dialog_cls.return_value = mock_dialog
        mock_dialog.exec.return_value = accepted
        mock_dialog.selectedFiles.return_value = []

        result = styled_select_directory()
        assert result == ""
