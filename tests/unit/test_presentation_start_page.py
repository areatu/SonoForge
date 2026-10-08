"""GUI tests for the native welcome page (Э5 / PR-D)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

pytestmark = pytest.mark.gui


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _page(qapp, *, entries=(), profile_name="full"):
    del qapp
    from echo_personal_tool.infrastructure.recent_store import RecentStore
    from echo_personal_tool.presentation.start_page import StartPage

    return StartPage(
        recent_store=RecentStore(entries=list(entries)),
        version="0.3.1",
        profile_name=profile_name,
        measurement_persistence_enabled=True,
    )


def test_primary_actions_and_help_emit_native_signals(qapp) -> None:
    page = _page(qapp)
    opened_folder = MagicMock()
    loaded_server = MagicMock()
    continued = MagicMock()
    requested_help = MagicMock()
    page.open_folder_requested.connect(opened_folder)
    page.load_from_server_requested.connect(loaded_server)
    page.continue_requested.connect(continued)
    page.help_requested.connect(requested_help)

    page.open_folder_button.click()
    page.load_server_button.click()
    page.continue_button.click()  # disabled until a previous session is known
    page.help_button.click()

    opened_folder.assert_called_once_with()
    loaded_server.assert_called_once_with()
    continued.assert_not_called()
    requested_help.assert_called_once_with()


def test_recent_places_are_limited_and_missing_places_are_disabled(qapp, tmp_path: Path) -> None:
    from echo_personal_tool.infrastructure.recent_store import RecentFolder

    existing = tmp_path / "scan"
    existing.mkdir()
    entries = [RecentFolder(str(existing), pinned=True)] + [
        RecentFolder(str(tmp_path / f"missing-{index}")) for index in range(9)
    ]
    page = _page(qapp, entries=entries)
    assert page._places_list.count() == 8
    assert page._places_list.item(0).text().startswith("★")
    assert page._places_list.item(0).flags() & Qt.ItemFlag.ItemIsEnabled
    missing = page._places_list.item(1)
    assert not missing.flags() & Qt.ItemFlag.ItemIsEnabled
    assert missing.toolTip() == ""
    assert str(tmp_path) not in missing.text()


def test_recent_place_click_emits_path_but_missing_place_does_not(qapp, tmp_path: Path) -> None:
    from echo_personal_tool.infrastructure.recent_store import RecentFolder

    existing = tmp_path / "folder"
    existing.mkdir()
    page = _page(
        qapp,
        entries=[RecentFolder(str(existing)), RecentFolder(str(tmp_path / "gone"))],
    )
    selected = MagicMock()
    page.recent_folder_requested.connect(selected)

    page._places_list.itemClicked.emit(page._places_list.item(0))
    page._places_list.itemClicked.emit(page._places_list.item(1))

    selected.assert_called_once_with(str(existing))


def test_continue_target_tracks_local_and_server_sessions(qapp, tmp_path: Path) -> None:
    page = _page(qapp)
    page.set_continue_target("folder", str(tmp_path))
    assert page.continue_button.isEnabled()
    assert tmp_path.name in page.continue_button.text()
    assert str(tmp_path) not in page.continue_button.toolTip()

    page.set_continue_target("server", str(tmp_path))
    assert page.continue_button.isEnabled()
    from echo_personal_tool.infrastructure.i18n import tr

    assert tr("start_page.session_server") in page.continue_button.text()

    page.set_continue_target("folder", str(tmp_path / "missing"))
    assert not page.continue_button.isEnabled()


def test_presenter_page_hides_private_recent_and_settings_sections(qapp) -> None:
    page = _page(qapp, profile_name="presenter")

    assert page._places_card.isHidden()
    assert page._studies_card.isHidden()
    assert page.continue_button.isHidden()
    assert page.references_button.isHidden()
    assert page.documents_button.isHidden()
    assert page.feedback_button.isHidden()
    assert page.settings_button.isHidden()
    assert not page.open_folder_button.isHidden()
    assert not page.load_server_button.isHidden()
    assert not page.help_button.isHidden()


def test_recent_study_rows_accept_safe_summary_and_use_placeholder_delegate(qapp) -> None:
    from echo_personal_tool.presentation.start_page import RecentStudySummary

    page = _page(qapp)
    summary = RecentStudySummary("study-1", "2026-10-08 · Echocardiography", "4 clips")
    page.set_recent_studies([summary])

    assert page._studies_list.count() == 1
    assert page._studies_list.item(0).text() == summary.title
    assert page._studies_list.itemDelegate() is not None
    assert page._studies_empty.isHidden()


def test_content_width_and_title_follow_ui_font_size(qapp) -> None:
    page = _page(qapp)
    page.set_ui_font_size(18)
    page.refresh_theme()
    page.resize(1280, 920)
    page.show()
    qapp.processEvents()

    assert page._content.width() == 1040
    assert page._title.font().pixelSize() == 32


def test_start_page_is_language_refreshable(qapp) -> None:
    from echo_personal_tool.infrastructure.i18n import get_language, set_language

    page = _page(qapp)
    original = get_language()
    try:
        set_language("ru")
        page.reload_text()
        assert page.open_folder_button.text() == "Открыть папку…"
        set_language("en")
        page.reload_text()
        assert page.open_folder_button.text() == "Open folder…"
    finally:
        set_language(original)


def test_help_dialog_loads_the_localized_markdown_guide(qapp) -> None:
    from echo_personal_tool.presentation.help_dialog import HelpDialog, help_document_path

    russian_path = help_document_path("ru")
    english_path = help_document_path("en")
    assert russian_path.name == "HELP_RU.md"
    assert english_path.name == "HELP_EN.md"
    assert russian_path.is_file()
    assert english_path.is_file()

    dialog = HelpDialog(language="ru")
    assert "SonoForge" in dialog._browser.toPlainText()
    dialog.close()
