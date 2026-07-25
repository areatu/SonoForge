"""Unit tests for presentation/server_profile_dialog.py."""

from __future__ import annotations

from unittest.mock import patch

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


class TestServerProfileDialogConstruction:
    @patch("echo_personal_tool.presentation.server_profile_dialog.list_profiles", return_value={})
    def test_creates_with_empty_profiles(self, mock_list):
        from echo_personal_tool.presentation.server_profile_dialog import ServerProfileDialog

        dlg = ServerProfileDialog(_default_settings())
        assert dlg.windowTitle() != ""
        assert dlg._list.count() == 0
        assert not dlg._btn_load.isEnabled()
        assert not dlg._btn_delete.isEnabled()

    @patch(
        "echo_personal_tool.presentation.server_profile_dialog.list_profiles",
        return_value={"Alpha": _default_settings(), "Beta": _default_settings()},
    )
    def test_populates_sorted_profiles(self, mock_list):
        from echo_personal_tool.presentation.server_profile_dialog import ServerProfileDialog

        dlg = ServerProfileDialog(_default_settings())
        assert dlg._list.count() == 2
        # Check sorted order
        names = [dlg._list.item(i).text() for i in range(dlg._list.count())]
        assert names == ["Alpha", "Beta"]


class TestSelectionChanges:
    @patch(
        "echo_personal_tool.presentation.server_profile_dialog.list_profiles",
        return_value={"Test": _default_settings()},
    )
    def test_selecting_item_enables_buttons(self, mock_list):
        from echo_personal_tool.presentation.server_profile_dialog import ServerProfileDialog

        dlg = ServerProfileDialog(_default_settings())
        dlg._list.setCurrentRow(0)
        assert dlg._btn_load.isEnabled()
        assert dlg._btn_delete.isEnabled()
        assert dlg._selected_name == "Test"

    @patch("echo_personal_tool.presentation.server_profile_dialog.list_profiles", return_value={})
    def test_no_selection_disables_buttons(self, mock_list):
        from echo_personal_tool.presentation.server_profile_dialog import ServerProfileDialog

        dlg = ServerProfileDialog(_default_settings())
        assert not dlg._btn_load.isEnabled()
        assert not dlg._btn_delete.isEnabled()
        assert dlg._selected_name is None


class TestLoadProfile:
    @patch(
        "echo_personal_tool.presentation.server_profile_dialog.list_profiles",
        return_value={"Existing": _default_settings(url="http://test:8042")},
    )
    @patch("echo_personal_tool.presentation.server_profile_dialog.load_profile")
    def test_load_existing_profile(self, mock_load, mock_list):
        from echo_personal_tool.presentation.server_profile_dialog import ServerProfileDialog

        loaded_settings = _default_settings(url="http://loaded:8042")
        mock_load.return_value = loaded_settings
        dlg = ServerProfileDialog(_default_settings())
        dlg._list.setCurrentRow(0)

        with patch.object(dlg, "accept") as mock_accept:
            dlg._on_load()
            mock_accept.assert_called_once()
            assert dlg.selected_settings.url == "http://loaded:8042"

    @patch(
        "echo_personal_tool.presentation.server_profile_dialog.list_profiles",
        return_value={"Missing": _default_settings()},
    )
    @patch("echo_personal_tool.presentation.server_profile_dialog.load_profile", return_value=None)
    @patch("echo_personal_tool.presentation.server_profile_dialog.QMessageBox.warning")
    def test_load_missing_profile_shows_warning(self, mock_warn, mock_load, mock_list):
        from echo_personal_tool.presentation.server_profile_dialog import ServerProfileDialog

        dlg = ServerProfileDialog(_default_settings())
        dlg._list.setCurrentRow(0)
        with patch.object(dlg, "accept") as mock_accept:
            dlg._on_load()
            mock_accept.assert_not_called()
            mock_warn.assert_called_once()

    def test_load_no_selection_does_nothing(self):
        from echo_personal_tool.presentation.server_profile_dialog import ServerProfileDialog

        dlg = ServerProfileDialog(_default_settings())
        with patch.object(dlg, "accept") as mock_accept:
            dlg._on_load()
            mock_accept.assert_not_called()


class TestSaveProfile:
    @patch(
        "echo_personal_tool.presentation.server_profile_dialog.list_profiles",
        return_value={},
    )
    @patch("echo_personal_tool.presentation.server_profile_dialog.save_profile")
    @patch("echo_personal_tool.presentation.server_profile_dialog.QInputDialog.getText", return_value=("NewProfile", True))
    def test_save_new_profile(self, mock_input, mock_save, mock_list):
        from echo_personal_tool.presentation.server_profile_dialog import ServerProfileDialog

        dlg = ServerProfileDialog(_default_settings())
        dlg._on_save_as()
        mock_save.assert_called_once_with("NewProfile", dlg._current_settings)

    @patch(
        "echo_personal_tool.presentation.server_profile_dialog.list_profiles",
        return_value={},
    )
    @patch("echo_personal_tool.presentation.server_profile_dialog.QInputDialog.getText", return_value=("", True))
    def test_save_empty_name_does_nothing(self, mock_input, mock_list):
        from echo_personal_tool.presentation.server_profile_dialog import ServerProfileDialog

        dlg = ServerProfileDialog(_default_settings())
        with patch("echo_personal_tool.presentation.server_profile_dialog.save_profile") as mock_save:
            dlg._on_save_as()
            mock_save.assert_not_called()

    @patch(
        "echo_personal_tool.presentation.server_profile_dialog.list_profiles",
        return_value={},
    )
    @patch("echo_personal_tool.presentation.server_profile_dialog.QInputDialog.getText", return_value=("Name", False))
    def test_save_cancelled_does_nothing(self, mock_input, mock_list):
        from echo_personal_tool.presentation.server_profile_dialog import ServerProfileDialog

        dlg = ServerProfileDialog(_default_settings())
        with patch("echo_personal_tool.presentation.server_profile_dialog.save_profile") as mock_save:
            dlg._on_save_as()
            mock_save.assert_not_called()


class TestDeleteProfile:
    @patch(
        "echo_personal_tool.presentation.server_profile_dialog.list_profiles",
        return_value={"ToDelete": _default_settings()},
    )
    @patch("echo_personal_tool.presentation.server_profile_dialog.delete_profile", return_value=True)
    @patch(
        "echo_personal_tool.presentation.server_profile_dialog.QMessageBox.question",
        return_value=0x00004000,  # QMessageBox.StandardButton.Yes
    )
    def test_confirm_deletes_profile(self, mock_question, mock_delete, mock_list):
        from echo_personal_tool.presentation.server_profile_dialog import ServerProfileDialog

        dlg = ServerProfileDialog(_default_settings())
        dlg._list.setCurrentRow(0)
        dlg._on_delete()
        mock_delete.assert_called_once_with("ToDelete")

    @patch(
        "echo_personal_tool.presentation.server_profile_dialog.list_profiles",
        return_value={"ToDelete": _default_settings()},
    )
    @patch("echo_personal_tool.presentation.server_profile_dialog.delete_profile")
    @patch(
        "echo_personal_tool.presentation.server_profile_dialog.QMessageBox.question",
        return_value=0x00000400,  # QMessageBox.StandardButton.No
    )
    def test_reject_does_not_delete(self, mock_question, mock_delete, mock_list):
        from echo_personal_tool.presentation.server_profile_dialog import ServerProfileDialog

        dlg = ServerProfileDialog(_default_settings())
        dlg._list.setCurrentRow(0)
        dlg._on_delete()
        mock_delete.assert_not_called()

    def test_delete_no_selection_does_nothing(self):
        from echo_personal_tool.presentation.server_profile_dialog import ServerProfileDialog

        dlg = ServerProfileDialog(_default_settings())
        with patch("echo_personal_tool.presentation.server_profile_dialog.delete_profile") as mock_delete:
            dlg._on_delete()
            mock_delete.assert_not_called()


class TestSelectedSettings:
    def test_returns_current_settings(self):
        from echo_personal_tool.presentation.server_profile_dialog import ServerProfileDialog

        s = _default_settings(url="http://test:8042")
        dlg = ServerProfileDialog(s)
        assert dlg.selected_settings.url == "http://test:8042"
