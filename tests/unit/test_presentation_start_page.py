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


def test_continue_label_shows_date_and_clip_count(qapp, tmp_path: Path) -> None:
    """Э5 §7.1: «Продолжить: <папка или сервер · дата · число клипов>»."""
    page = _page(qapp)
    page.set_continue_target("folder", str(tmp_path), date="2026-10-08", clip_count=4)
    text = page.continue_button.text()
    assert tmp_path.name in text
    assert "2026-10-08" in text
    assert "4" in text
    assert text.index(tmp_path.name) < text.index("2026-10-08") < text.index("4")
    # No full paths in the label (privacy N-01).
    assert str(tmp_path) not in text

    page.set_continue_target("server", "", date="2026-10-07", clip_count=2)
    from echo_personal_tool.infrastructure.i18n import tr

    text = page.continue_button.text()
    assert tr("start_page.session_server") in text
    assert "2026-10-07" in text
    assert "2" in text

    # Unknown date/count degrade gracefully to the bare target.
    page.set_continue_target("folder", str(tmp_path))
    text = page.continue_button.text()
    assert tmp_path.name in text
    assert "2026" not in text


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


def test_recent_study_rows_fill_the_browser_table(qapp) -> None:
    from echo_personal_tool.presentation.start_page import RecentStudySummary

    page = _page(qapp)
    summary = RecentStudySummary("study-1", "2026-10-08 · Echocardiography", "4 clips")
    page.set_recent_studies([summary])

    assert page._studies_table.rowCount() == 1
    # Without a structured date the title keeps its date — it is the only copy.
    assert page._studies_table.item(0, 0).text() == summary.title
    assert page._studies_empty.isHidden()


def test_browser_fills_the_area_and_title_follows_ui_font_size(qapp) -> None:
    page = _page(qapp)
    page.set_ui_font_size(18)
    page.refresh_theme()
    page.resize(1600, 920)
    page.show()
    qapp.processEvents()

    # The A2 browser is not a centred welcome column any more: sidebar +
    # table + detail panel span the whole viewer area.
    assert page._content.width() > 700
    assert page._studies_table.width() > 600
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


def _browser_rows():
    """Identifier-free rows dated relative to today, as the builders emit."""
    from datetime import date, timedelta

    from echo_personal_tool.presentation.start_page import RecentStudySummary

    today = date.today()
    week_ago = today - timedelta(days=5)
    old = today - timedelta(days=60)

    def iso(day) -> str:
        return day.strftime("%Y-%m-%d")

    return [
        RecentStudySummary(
            key="today-folder",
            title=f"{iso(today)} · Echocardiography",
            details="24 clips",
            origin="folder",
            folder="/data/Echo cases",
            study_date=iso(today),
            clip_count=24,
            measurement_count=14,
        ),
        RecentStudySummary(
            key="week-server",
            title=f"{iso(week_ago)} · Stress echo",
            details="46 clips",
            origin="server",
            study_uid="1.2.3",
            study_date=iso(week_ago),
            clip_count=46,
        ),
        RecentStudySummary(
            key="old-stored",
            title=f"{iso(old)} · saved",
            details="9 measurements",
            origin="stored",
            available=False,
            study_date=iso(old),
            measurement_count=9,
        ),
    ]


def test_browser_table_columns_status_and_detail(qapp) -> None:
    from echo_personal_tool.infrastructure.i18n import tr

    page = _page(qapp)
    page.set_recent_studies(_browser_rows())
    page.show()
    qapp.processEvents()

    table = page._studies_table
    assert table.rowCount() == 3
    # The date lives in its own column, so the study cell drops the prefix.
    assert table.item(0, 0).text() == "Echocardiography"
    assert table.item(0, 2).text() == "24"
    assert table.item(0, 3).text() == "14"
    assert tr("start_page.status_draft") in table.item(0, 4).text()
    assert table.item(0, 5).text() == "Echo cases"
    assert tr("start_page.status_new") in table.item(1, 4).text()

    # First row is selected and described on the right.
    assert page._detail_title.text() == "Echocardiography"
    assert page._detail_values["folder"].text() == "Echo cases"
    assert page._detail_values["measurements"].text() == "14"
    assert page.open_study_button.isEnabled()


def test_search_period_and_source_filters_narrow_the_table(qapp) -> None:
    page = _page(qapp)
    page.set_recent_studies(_browser_rows())

    page._search_edit.setText("stress")
    assert [row.key for row in page._visible_studies] == ["week-server"]

    page._search_edit.clear()
    page._period_buttons[1].click()  # «Сегодня»
    assert [row.key for row in page._visible_studies] == ["today-folder"]
    page._period_buttons[0].click()  # «Все»

    page._source_nav.setCurrentRow(3)  # хранилище измерений
    assert [row.key for row in page._visible_studies] == ["old-stored"]
    page._source_nav.setCurrentRow(0)

    drafts = page._filter_list.item(0)
    drafts.setCheckState(Qt.CheckState.Checked)
    assert {row.key for row in page._visible_studies} == {"today-folder", "old-stored"}


def test_no_results_offers_a_filter_reset(qapp) -> None:
    page = _page(qapp)
    page.set_recent_studies(_browser_rows())
    page.show()
    qapp.processEvents()

    page._search_edit.setText("zzzz-no-match")
    qapp.processEvents()
    assert page._studies_table.rowCount() == 0
    assert page._no_results.isVisible()
    assert page._studies_empty.isHidden()

    page._reset_filters_button.click()
    qapp.processEvents()
    assert page._search_edit.text() == ""
    assert page._studies_table.rowCount() == 3
    assert page._no_results.isHidden()


def test_selection_does_not_open_but_activation_and_button_do(qapp) -> None:
    page = _page(qapp)
    opened = MagicMock()
    page.recent_study_requested.connect(opened)
    rows = _browser_rows()
    page.set_recent_studies(rows)
    page.show()
    qapp.processEvents()

    page._studies_table.setCurrentCell(1, 0)
    qapp.processEvents()
    opened.assert_not_called()
    assert page._detail_title.text() == "Stress echo"

    page.open_study_button.click()
    opened.assert_called_once_with(rows[1])

    opened.reset_mock()
    page._studies_table.itemActivated.emit(page._studies_table.item(0, 0))
    opened.assert_called_once_with(rows[0])


def test_unavailable_row_selects_but_never_opens(qapp) -> None:
    page = _page(qapp)
    opened = MagicMock()
    page.recent_study_requested.connect(opened)
    page.set_recent_studies(_browser_rows())
    page.show()
    qapp.processEvents()

    page._studies_table.setCurrentCell(2, 0)
    qapp.processEvents()
    assert not page.open_study_button.isEnabled()
    assert page._detail_note.text()  # explains why the row cannot be reopened

    page._studies_table.itemActivated.emit(page._studies_table.item(2, 0))
    opened.assert_not_called()


def test_drop_folder_and_file_emit_recent_folder_requested(qapp, tmp_path: Path) -> None:
    from PySide6.QtCore import QMimeData, QPointF, QUrl
    from PySide6.QtGui import QDropEvent

    folder = tmp_path / "cases"
    folder.mkdir()
    clip = folder / "clip.dcm"
    clip.write_bytes(b"")
    page = _page(qapp)
    requested = MagicMock()
    page.recent_folder_requested.connect(requested)

    def drop(path: Path) -> None:
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(path))])
        event = QDropEvent(
            QPointF(10, 10),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        page.dropEvent(event)

    drop(folder)
    drop(clip)  # a single file opens through its parent folder
    assert requested.call_count == 2
    requested.assert_called_with(str(folder))


def test_focus_search_puts_focus_into_the_search_edit(qapp) -> None:
    page = _page(qapp)
    page.show()
    qapp.processEvents()

    page.focus_search()
    qapp.processEvents()
    assert page._search_edit.hasFocus()
