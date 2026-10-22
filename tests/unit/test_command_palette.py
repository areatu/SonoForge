"""TP-6 command palette interaction, filtering and recent-command behavior."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.gui

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog

from echo_personal_tool.presentation.command_palette import CommandPalette


@pytest.fixture(autouse=True)
def _isolate_palette_settings(isolated_qsettings):
    return isolated_qsettings


def _palette(qtbot, isolated_qsettings) -> CommandPalette:
    """A palette whose recents live in the per-test isolated store."""
    palette = CommandPalette("full", settings=isolated_qsettings)
    qtbot.addWidget(palette)
    return palette


def _command_items(palette: CommandPalette) -> list[str]:
    return [
        palette._results.item(i).data(Qt.ItemDataRole.UserRole).id
        for i in range(palette._results.count())
        if palette._results.item(i).data(Qt.ItemDataRole.UserRole) is not None
    ]


def test_empty_palette_shows_catalogue_when_no_history(qtbot, isolated_qsettings) -> None:
    palette = _palette(qtbot, isolated_qsettings)

    assert _command_items(palette)
    headers = [
        palette._results.item(i).text()
        for i in range(palette._results.count())
        if palette._results.item(i).flags() == Qt.ItemFlag.NoItemFlags
    ]
    assert "Измерения" in headers or "Measurements" in headers
    assert "Действия" in headers or "Actions" in headers
    assert "Расчёты" in headers or "Calculations" in headers
    assert palette._results.currentItem().data(Qt.ItemDataRole.UserRole) is not None


def test_down_moves_focus_from_search_to_results(qtbot, isolated_qsettings) -> None:
    palette = _palette(qtbot, isolated_qsettings)
    palette.show()
    palette._query.setFocus()

    qtbot.keyClick(palette._query, Qt.Key.Key_Down)
    assert palette.focusWidget() is palette._results


def test_search_filters_bilingually_and_enter_resolves(qtbot, isolated_qsettings) -> None:
    palette = _palette(qtbot, isolated_qsettings)
    palette._query.setText("settings")

    assert _command_items(palette) == ["settings"]
    palette._activate_current()
    assert palette.result() == QDialog.DialogCode.Accepted
    assert palette.selected_command.id == "settings"


def test_tool_row_exposes_and_hides_registered_key_badges(qtbot) -> None:
    from echo_personal_tool.presentation.tool_buttons.buttons import key_hint
    from echo_personal_tool.presentation.tool_buttons.row import ToolButtonRow

    row = ToolButtonRow()
    qtbot.addWidget(row)
    spec = next(item for item in row.specs() if key_hint(item))
    button = row.button(spec.id)
    assert button is not None
    assert key_hint(spec) not in button.text()

    row.set_key_hints_visible(True)
    assert key_hint(spec) in button.text()
    row.set_key_hints_visible(False)
    assert key_hint(spec) not in button.text()


def test_palette_retains_five_most_recent_commands(qtbot, isolated_qsettings) -> None:
    palette = _palette(qtbot, isolated_qsettings)
    ids = [command.id for command in list(palette._commands.values())[:6]]
    palette._settings.setValue("command_palette/recent", list(reversed(ids)))
    palette._populate("")

    assert _command_items(palette) == list(reversed(ids))[:5]


def _headers(palette: CommandPalette) -> list[str]:
    return [
        palette._results.item(i).text()
        for i in range(palette._results.count())
        if palette._results.item(i).flags() == Qt.ItemFlag.NoItemFlags
    ]


def test_empty_palette_lists_protocols_first(qtbot, isolated_qsettings) -> None:
    palette = _palette(qtbot, isolated_qsettings)

    assert _headers(palette)[0] in {"Протоколы", "Protocols"}
    protocol_items = [item_id for item_id in _command_items(palette) if item_id.startswith("protocol.")]
    assert len(protocol_items) == 6


def test_search_finds_a_protocol_by_its_name(qtbot, isolated_qsettings) -> None:
    palette = _palette(qtbot, isolated_qsettings)
    palette._query.setText("Симпсон")

    assert "protocol.simpson_biplane" in _command_items(palette)
    palette._activate_current()
    assert palette.selected_command.action == "protocol:simpson_biplane"
