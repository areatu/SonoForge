"""Tests for the "Report a problem" dialog (Q-13)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.parse import unquote

import pytest

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def _setup_qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture()
def bundle_path(tmp_path: Path) -> Path:
    return tmp_path / "SonoForge-diagnostics-test.zip"


@pytest.fixture()
def dialog(qtbot, bundle_path: Path):
    from echo_personal_tool.presentation.feedback_dialog import SupportFeedbackDialog

    widget = SupportFeedbackDialog(bundle_path=bundle_path)
    qtbot.addWidget(widget)
    return widget


@pytest.fixture()
def opened_urls() -> list[str]:
    """Capture every QDesktopServices.openUrl target and report success."""
    urls: list[str] = []

    def _open(url):
        urls.append(url.toString())
        return True

    with patch("echo_personal_tool.presentation.feedback_dialog.QDesktopServices.openUrl", side_effect=_open):
        yield urls


@pytest.fixture()
def silent_boxes():
    """Keep QMessageBox non-modal so the tests can assert on it instead."""
    with (
        patch("echo_personal_tool.presentation.feedback_dialog.QMessageBox.information") as info,
        patch("echo_personal_tool.presentation.feedback_dialog.QMessageBox.warning") as warning,
    ):
        yield info, warning


class TestContents:
    def test_preview_shows_what_the_link_carries(self, dialog) -> None:
        from echo_personal_tool import __version__

        text = dialog._preview.toPlainText()
        assert f"SonoForge version: {__version__}" in text
        assert dialog._bundle_path.name in text

    def test_bundle_is_opt_out_only_by_default(self, dialog) -> None:
        assert dialog._bundle_checkbox.isChecked()
        assert dialog._destination_label.isVisibleTo(dialog)
        assert dialog._browse_button.isVisibleTo(dialog)

    def test_unchecking_the_bundle_hides_the_destination_and_the_link_mention(self, dialog) -> None:
        dialog._bundle_checkbox.setChecked(False)  # toggled() drives the preview
        assert not dialog._bundle_checkbox.isChecked()
        assert not dialog._destination_label.isVisibleTo(dialog)
        assert "not created" in dialog._preview.toPlainText()
        assert dialog._bundle_path.name not in dialog.issue_url()

    def test_issue_url_mentions_the_bundle_file_name_only(self, dialog, bundle_path: Path) -> None:
        url = dialog.issue_url()
        assert bundle_path.name in url
        assert str(bundle_path.parent) not in url


class TestOpenForm:
    def test_creates_the_bundle_then_opens_the_form(self, dialog, opened_urls, silent_boxes, bundle_path: Path) -> None:
        from echo_personal_tool.infrastructure import diagnostics

        def _create(destination, **kwargs):
            Path(destination).write_bytes(b"PK\x03\x04")
            return Path(destination)

        with patch.object(diagnostics, "create_diagnostic_bundle", side_effect=_create) as create:
            dialog._open_form()

        assert create.call_count == 1
        assert bundle_path.exists()
        # Folder first (so the archive can be dragged into the browser), then the form.
        assert opened_urls[0].startswith("file:")
        assert opened_urls[1].startswith("https://github.com/areatu/SonoForge/issues/new?")
        assert bundle_path.name in opened_urls[1]
        assert dialog.result() == dialog.DialogCode.Accepted

    def test_without_the_bundle_only_the_form_is_opened(self, dialog, opened_urls, silent_boxes) -> None:
        from echo_personal_tool.infrastructure import diagnostics

        dialog._bundle_checkbox.setChecked(False)
        with patch.object(diagnostics, "create_diagnostic_bundle") as create:
            dialog._open_form()

        create.assert_not_called()
        assert len(opened_urls) == 1
        assert "Diagnostic bundle: not created" in unquote(opened_urls[0])

    def test_a_bundle_failure_still_opens_the_form(self, dialog, opened_urls, silent_boxes) -> None:
        from echo_personal_tool.infrastructure import diagnostics

        info, warning = silent_boxes
        with patch.object(diagnostics, "create_diagnostic_bundle", side_effect=OSError("read-only media")):
            dialog._open_form()

        assert warning.call_count == 1
        assert len(opened_urls) == 1
        assert "Diagnostic bundle: not created" in unquote(opened_urls[0])
        assert not Path(dialog._bundle_path).exists()

    def test_a_browser_failure_copies_the_link(self, dialog, silent_boxes) -> None:
        from PySide6.QtWidgets import QApplication

        from echo_personal_tool.infrastructure import diagnostics

        info, _ = silent_boxes
        dialog._bundle_checkbox.setChecked(False)
        with (
            patch.object(diagnostics, "create_diagnostic_bundle"),
            patch(
                "echo_personal_tool.presentation.feedback_dialog.QDesktopServices.openUrl",
                return_value=False,
            ),
        ):
            dialog._open_form()

        assert info.call_count == 1
        assert QApplication.clipboard().text().startswith("https://github.com/areatu/SonoForge/issues/new?")
        assert dialog.result() != dialog.DialogCode.Accepted


class TestCopyLink:
    def test_link_lands_on_the_clipboard(self, dialog, silent_boxes) -> None:
        from PySide6.QtWidgets import QApplication

        dialog._copy_link()
        text = QApplication.clipboard().text()
        assert text.startswith("https://github.com/areatu/SonoForge/issues/new?")
        assert "template=bug_report.yml" in text


class TestDestination:
    def test_choosing_a_path_without_a_suffix_gets_one(self, dialog, tmp_path: Path) -> None:
        chosen = tmp_path / "report-archive"
        with patch(
            "echo_personal_tool.presentation.styled_dialogs.styled_save_file",
            return_value=(str(chosen), "ZIP (*.zip)"),
        ):
            dialog._choose_destination()

        assert dialog._bundle_path == tmp_path / "report-archive.zip"
        assert "report-archive.zip" in dialog._destination_label.text()

    def test_cancelling_the_save_dialog_changes_nothing(self, dialog, bundle_path: Path) -> None:
        with patch("echo_personal_tool.presentation.styled_dialogs.styled_save_file", return_value=("", "")):
            dialog._choose_destination()

        assert dialog._bundle_path == bundle_path


class TestSettingsEntry:
    def test_the_settings_dialog_has_the_button(self) -> None:
        from echo_personal_tool.infrastructure.user_preferences import default_user_preferences
        from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

        with patch(
            "echo_personal_tool.presentation.user_preferences_dialog.load_user_preferences",
            return_value=default_user_preferences(),
        ):
            dialog = UserPreferencesDialog()
        button = dialog.findChild(object, "feedbackButton")
        assert button is not None
        assert button.text()

    def test_the_button_opens_the_report_dialog(self) -> None:
        from echo_personal_tool.infrastructure.user_preferences import default_user_preferences
        from echo_personal_tool.presentation import feedback_dialog as feedback_module
        from echo_personal_tool.presentation.user_preferences_dialog import UserPreferencesDialog

        with patch(
            "echo_personal_tool.presentation.user_preferences_dialog.load_user_preferences",
            return_value=default_user_preferences(),
        ):
            dialog = UserPreferencesDialog()

        opener = MagicMock()
        with patch.object(feedback_module, "show_support_feedback_dialog", opener):
            dialog._report_problem()

        opener.assert_called_once_with(dialog)
