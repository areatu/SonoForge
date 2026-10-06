"""Tool-panel customization layout (Settings → Tools tab)."""

from __future__ import annotations

import copy

import pytest

from echo_personal_tool.presentation.measures_menu import (
    apply_tool_layout,
    build_measure_menu,
    decode_tool_layout,
    default_tool_layout,
    encode_tool_layout,
    tool_menu_catalog,
)

pytestmark = pytest.mark.gui
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session", autouse=True)
def _qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_default_layout_roundtrips() -> None:
    layout = default_tool_layout()
    assert decode_tool_layout(encode_tool_layout(layout)) == layout
    catalog = tool_menu_catalog()
    assert [entry["key"] for entry in layout] == [key for key, _ in catalog]
    assert sum(len(entry["items"]) for entry in layout) == sum(len(buttons) for _, buttons in catalog)


def test_decode_rejects_garbage() -> None:
    assert decode_tool_layout("") == []
    assert decode_tool_layout("not json") == []
    assert decode_tool_layout('[{"key": 1}]') == []
    assert decode_tool_layout('[{"key": "menu.general", "items": [{"id": 5}]}]') == [
        {"key": "menu.general", "items": []}
    ]


def test_moved_tool_relocates_and_disabled_hides() -> None:
    catalog = tool_menu_catalog()
    layout = copy.deepcopy(default_tool_layout())
    moved = layout[0]["items"].pop(0)  # caliper, from General
    layout[3]["items"].insert(0, moved)  # into Aorta
    disabled = layout[0]["items"][0]
    disabled["enabled"] = False

    menu = apply_tool_layout(catalog, decode_tool_layout(encode_tool_layout(layout)))
    sections = dict(menu)

    assert sections["menu.aorta"][0].label_key == "menu.caliper"
    visible_ids = {spec.tool_id for _, buttons in menu for spec in buttons}
    assert moved["id"] in visible_ids
    assert disabled["id"] not in visible_ids
    assert moved["id"] not in {spec.tool_id for spec in sections["menu.general"]}


def test_new_catalog_tool_falls_back_to_default_section() -> None:
    catalog = tool_menu_catalog()
    layout = [entry for entry in default_tool_layout() if entry["key"] != "menu.general"]

    menu = dict(apply_tool_layout(catalog, decode_tool_layout(encode_tool_layout(layout))))

    default_general = dict(catalog)["menu.general"]
    assert [spec.tool_id for spec in menu["menu.general"]] == [spec.tool_id for spec in default_general]


def test_build_measure_menu_applies_layout() -> None:
    from echo_personal_tool.infrastructure.user_preferences import default_user_preferences

    preferences = default_user_preferences()
    layout = copy.deepcopy(default_tool_layout())
    removed = layout[0]["items"][0]
    removed["enabled"] = False
    preferences.tool_panel_layout_json = encode_tool_layout(layout)

    menu = build_measure_menu(preferences)
    visible_ids = {spec.tool_id for _, buttons in menu for spec in buttons}

    assert removed["id"] not in visible_ids


def test_settings_widget_persists_and_drops_checkbox_state() -> None:
    from echo_personal_tool.presentation.tool_panel_settings import ToolPanelSettingsWidget

    widget = ToolPanelSettingsWidget()
    general = widget._lists["menu.general"]
    general.item(0).setCheckState(Qt.CheckState.Unchecked)

    layout = decode_tool_layout(widget.encoded_layout())
    general_entry = next(entry for entry in layout if entry["key"] == "menu.general")
    disabled = [item for item in general_entry["items"] if not item["enabled"]]
    assert len(disabled) == 1


def test_settings_widget_lays_sections_in_two_columns() -> None:
    from PySide6.QtWidgets import QGroupBox

    from echo_personal_tool.presentation.tool_panel_settings import ToolPanelSettingsWidget

    widget = ToolPanelSettingsWidget()
    assert widget._grid.columnCount() == 2
    assert len(widget.findChildren(QGroupBox)) == len(widget._lists)
    assert widget._grid.getItemPosition(0)[:2] == (0, 0)
    assert widget._grid.getItemPosition(1)[:2] == (0, 1)
    assert widget._grid.getItemPosition(2)[:2] == (1, 0)


def test_relocate_moves_item_between_sections() -> None:
    from PySide6.QtWidgets import QListWidgetItem

    from echo_personal_tool.presentation.tool_panel_settings import _ToolListWidget

    source = _ToolListWidget()
    target = _ToolListWidget()
    for tool_id in ("tool-a", "tool-b"):
        item = QListWidgetItem(tool_id)
        item.setData(Qt.ItemDataRole.UserRole, tool_id)
        source.addItem(item)

    assert _ToolListWidget._relocate(source, target, "tool-a", -1) is True
    assert source.count() == 1
    assert target.count() == 1
    assert str(target.item(0).data(Qt.ItemDataRole.UserRole)) == "tool-a"
    assert _ToolListWidget._relocate(source, target, "missing", -1) is False
