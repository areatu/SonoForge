"""Э3: recent folders store and the "Open folder" dialog chrome."""

from __future__ import annotations

from pathlib import Path

import pytest

from echo_personal_tool.infrastructure.recent_store import (
    MAX_RECENT_FOLDERS,
    RecentFolder,
    RecentStore,
    normalize_folder,
)


def _store(tmp_path: Path, *, limit: int = MAX_RECENT_FOLDERS) -> RecentStore:
    from PySide6.QtCore import QSettings

    settings = QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)
    return RecentStore(settings, limit=limit)


# ── the store ───────────────────────────────────────────────────────


def test_record_dedupes_and_moves_to_front(tmp_path: Path) -> None:
    store = _store(tmp_path)
    a, b = tmp_path / "a", tmp_path / "b"
    store.record(a)
    store.record(b)
    store.record(a)

    assert store.paths() == [str(a), str(b)]


def test_record_is_survived_by_a_new_store_instance(tmp_path: Path) -> None:
    first = _store(tmp_path)
    first.record(tmp_path / "clips")

    second = _store(tmp_path)
    assert second.paths() == [str(tmp_path / "clips")]


def test_entries_are_trimmed_but_pins_are_kept(tmp_path: Path) -> None:
    store = _store(tmp_path, limit=3)
    pinned = tmp_path / "pinned"
    store.record(pinned)
    store.set_pinned(pinned)
    for index in range(6):
        store.record(tmp_path / f"folder-{index}")

    paths = store.paths()
    assert paths[0] == str(pinned)  # pinned entries stay on top
    assert len(paths) == 3
    assert str(tmp_path / "folder-5") in paths  # newest unpinned entries survive


def test_toggle_pin_and_remove(tmp_path: Path) -> None:
    store = _store(tmp_path)
    path = tmp_path / "clips"
    store.record(path)

    assert store.toggle_pinned(path) is True
    assert store.is_pinned(path) is True
    assert store.toggle_pinned(path) is False
    assert store.is_pinned(path) is False

    store.remove(path)
    assert store.paths() == []


def test_clear_can_keep_pinned_entries(tmp_path: Path) -> None:
    store = _store(tmp_path)
    keep, drop = tmp_path / "keep", tmp_path / "drop"
    store.record(keep)
    store.record(drop)
    store.set_pinned(keep)

    store.clear(keep_pinned=True)
    assert store.paths() == [str(keep)]

    store.clear()
    assert store.paths() == []


def test_last_folder_skips_missing_entries(tmp_path: Path) -> None:
    existing = tmp_path / "exists"
    existing.mkdir()
    store = _store(tmp_path)
    store.record(tmp_path / "gone")
    store.record(existing)

    assert store.last_folder() == str(existing)


def test_missing_folder_is_reported_but_stays_in_the_list(tmp_path: Path) -> None:
    store = _store(tmp_path)
    missing = tmp_path / "usb-stick-that-is-not-plugged-in"
    store.record(missing)

    entries = store.entries()
    assert entries == [RecentFolder(path=str(missing))]
    assert entries[0].exists is False


def test_corrupt_settings_value_is_ignored(tmp_path: Path) -> None:
    from PySide6.QtCore import QSettings

    settings = QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)
    settings.setValue("recent_folders", "{not json")
    settings.sync()

    assert RecentStore(settings).paths() == []


def test_legacy_plain_string_list_is_accepted(tmp_path: Path) -> None:
    from PySide6.QtCore import QSettings

    settings = QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)
    settings.setValue("recent_folders", '["/tmp/one", {"path": "/tmp/two", "pinned": true}]')
    settings.sync()

    entries = RecentStore(settings).entries()
    assert [entry.path for entry in entries] == ["/tmp/two", "/tmp/one"]
    assert entries[0].pinned is True


def test_normalization_removes_trailing_separators_and_expands_home() -> None:
    assert normalize_folder("/data/clips/") == normalize_folder("/data/clips")
    assert normalize_folder("") == ""
    expanded = normalize_folder("~/sonoforge")
    assert "~" not in expanded
    assert expanded.startswith("/") or ":\\" in expanded


# ── dialog chrome ───────────────────────────────────────────────────


@pytest.fixture()
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.mark.gui
def test_recents_strip_lists_pins_and_handles_missing_folders(qapp, tmp_path: Path) -> None:
    from PySide6.QtWidgets import QComboBox, QFileDialog

    from echo_personal_tool.presentation.styled_dialogs import _recents_bar

    store = _store(tmp_path)
    existing = tmp_path / "exists"
    existing.mkdir()
    store.record(tmp_path / "gone")
    store.record(existing)  # most recent

    dialog = QFileDialog()
    bar = _recents_bar(dialog, store)

    combo = bar.findChild(QComboBox, "recentFoldersCombo")
    assert combo is not None
    items = [combo.itemText(index) for index in range(combo.count())]
    assert str(existing) in items[0]  # most recent first
    # The unavailable folder is still listed, but cannot be selected.
    assert not combo.model().item(1).isEnabled()


@pytest.mark.gui
def test_recents_strip_pin_button_toggles_the_flag(qapp, tmp_path: Path) -> None:
    from PySide6.QtWidgets import QFileDialog, QPushButton

    from echo_personal_tool.presentation.styled_dialogs import _recents_bar

    store = _store(tmp_path)
    folder = tmp_path / "clips"
    folder.mkdir()
    store.record(folder)

    dialog = QFileDialog()
    bar = _recents_bar(dialog, store)
    buttons = {button.objectName(): button for button in bar.findChildren(QPushButton)}

    buttons["recentPinButton"].click()
    assert store.is_pinned(folder) is True
    buttons["recentPinButton"].click()
    assert store.is_pinned(folder) is False

    buttons["recentRemoveButton"].click()
    assert store.paths() == []


@pytest.mark.gui
def test_sidebar_contains_known_places_and_existing_recents(qapp, tmp_path: Path, monkeypatch) -> None:
    from PySide6.QtWidgets import QFileDialog

    from echo_personal_tool.presentation.styled_dialogs import _add_sidebar_urls

    store = _store(tmp_path)
    existing = tmp_path / "clips"
    existing.mkdir()
    store.record(existing)
    store.record(tmp_path / "gone")

    desktop = qapp.primaryScreen()  # keep the reference alive for the fixture
    assert desktop is not None

    dialog = QFileDialog()
    _add_sidebar_urls(dialog, store)
    urls = [url.toLocalFile() for url in dialog.sidebarUrls()]

    assert str(existing) in urls
    assert str(tmp_path / "gone") not in urls  # unavailable folders are not offered
    # Known folders are resolved through the OS, not from ~/Desktop.
    from echo_personal_tool.presentation.styled_dialogs import _standard_places

    labels = [label for label, _path in _standard_places()]
    assert any("Desktop" in label or "Рабочий стол" in label for label in labels)


@pytest.mark.gui
def test_dialog_starts_from_the_recent_folder_and_records_the_choice(qapp, tmp_path: Path, monkeypatch) -> None:
    """The dialog itself: start directory and the write-back of the choice."""
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QFileDialog

    from echo_personal_tool.presentation import styled_dialogs as module

    settings = QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)
    remembered = tmp_path / "remembered"
    remembered.mkdir()
    RecentStore(settings).record(remembered)

    seen: dict = {}

    class _Dialog(QFileDialog):
        """A real QFileDialog that is never shown, so the chrome is exercised."""

        def __init__(self, parent=None, title="", directory="", *_args, **_kwargs):
            super().__init__(parent, title, directory)
            seen["start"] = directory
            seen["dialog"] = self

        def exec(self) -> QFileDialog.DialogCode:
            return QFileDialog.DialogCode.Accepted

        def selectedFiles(self) -> list[str]:
            return [str(tmp_path / "chosen")]

    monkeypatch.setattr(module, "QFileDialog", _Dialog)
    monkeypatch.setattr(
        "echo_personal_tool.infrastructure.recent_store.RecentStore",
        lambda *a, **k: RecentStore(settings),
    )
    monkeypatch.setattr(module, "_style_dialog", lambda _dialog: None)

    result = module.styled_select_directory()

    assert result == str(tmp_path / "chosen")
    assert seen["start"] == str(remembered)  # started where the user was last time
    # ...and remembered it, in front of the folder it started from
    assert RecentStore(settings).paths() == [str(tmp_path / "chosen"), str(remembered)]

    # The dialog carries the recents strip and the folders offered as places.
    from PySide6.QtWidgets import QComboBox

    combo = seen["dialog"].findChild(QComboBox, "recentFoldersCombo")
    assert combo is not None
    # Built before the choice: it lists the folder the dialog started from...
    assert [combo.itemText(index) for index in range(combo.count())] == [str(remembered)]
    # ...and the sidebar offers places to jump to, not only the current folder.
    assert len([url for url in seen["dialog"].sidebarUrls() if url.toLocalFile()]) >= 2

    # The preference panels pass remember=False: a dataset folder is not a
    # patient folder and must not enter the "recent" list.
    seen.clear()
    module.styled_select_directory(remember=False)
    assert RecentStore(settings).paths() == [str(tmp_path / "chosen"), str(remembered)]


@pytest.mark.gui
def test_dialog_without_history_starts_in_documents_or_home(qapp, tmp_path: Path, monkeypatch) -> None:
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QFileDialog

    from echo_personal_tool.presentation import styled_dialogs as module

    settings = QSettings(str(tmp_path / "empty-prefs.ini"), QSettings.Format.IniFormat)
    seen: dict[str, str] = {}

    class _Dialog(QFileDialog):
        def __init__(self, parent=None, title="", directory="", *_args, **_kwargs):
            super().__init__(parent, title, directory)
            seen["start"] = directory
            seen["dialog"] = self

        def exec(self) -> QFileDialog.DialogCode:
            return QFileDialog.DialogCode.Rejected

    monkeypatch.setattr(module, "QFileDialog", _Dialog)
    monkeypatch.setattr(module, "_style_dialog", lambda _dialog: None)
    monkeypatch.setattr(
        "echo_personal_tool.infrastructure.recent_store.RecentStore",
        lambda *a, **k: RecentStore(settings),
    )

    start = module._default_folder()
    assert start and start != ""  # never the process working directory

    assert module.styled_select_directory() == ""
    assert seen["start"] == start
    # The "recent folders" strip is part of the dialog even when it is empty.
    from PySide6.QtWidgets import QComboBox

    combo = seen["dialog"].findChild(QComboBox, "recentFoldersCombo")
    assert combo is not None
    assert combo.isEnabled() is False
