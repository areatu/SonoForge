"""Tool-panel customization layout (Settings → Tools tab)."""

from __future__ import annotations

import copy
import json
from unittest.mock import patch

import pytest

from echo_personal_tool.presentation.measures_menu import (
    MAX_CUSTOM_SECTION_TITLE,
    MAX_CUSTOM_SECTIONS,
    apply_tool_layout,
    build_measure_menu,
    custom_section_titles,
    decode_tool_layout,
    default_tool_layout,
    encode_tool_layout,
    normalize_tool_layout,
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
        {"key": "menu.general", "title": None, "items": []}
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
    assert len(widget._columns) == 2
    boxes = widget.findChildren(QGroupBox)
    assert len(boxes) == len(widget._lists)
    # Masonry: every section sits in exactly one column, so a tall section
    # never leaves a grid-row gap under its shorter neighbour.
    per_column: list[list] = []
    for column in widget._columns:
        in_column = [
            column.itemAt(index).widget() for index in range(column.count()) if column.itemAt(index).widget() in boxes
        ]
        per_column.append(in_column)
    assert all(len(items) > 0 for items in per_column)
    flat = [box for items in per_column for box in items]
    assert sorted(map(id, flat)) == sorted(map(id, boxes))
    # Columns are balanced by row count: the gap is at most one section.
    key_of = {id(box): key for key, box in widget._section_boxes.items()}
    rows = [sum(max(1, widget._lists[key_of[id(box)]].count()) for box in items) for items in per_column]
    biggest = max(max(1, widget._lists[key].count()) for key in widget._lists)
    assert abs(rows[0] - rows[1]) <= biggest


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


# ── layout version 2: explicit order, user sections ─────────────────────────


def _visible(menu) -> list[tuple[str, list[str]]]:
    return [(key, [spec.tool_id for spec in buttons]) for key, buttons in menu]


def _preferences_with(layout: list[dict[str, object]]):
    from echo_personal_tool.infrastructure.user_preferences import default_user_preferences

    preferences = default_user_preferences()
    preferences.tool_panel_layout_json = encode_tool_layout(layout)
    return preferences


def test_v1_bare_list_reads_sections_in_catalog_order() -> None:
    catalog = tool_menu_catalog()
    v1_reversed = [
        {"key": key, "items": [{"id": spec.tool_id, "enabled": True} for spec in buttons]}
        for key, buttons in reversed(catalog)
    ]

    layout = decode_tool_layout(json.dumps(v1_reversed))

    assert [entry["key"] for entry in layout] == [key for key, _ in catalog]
    assert all(entry["title"] is None for entry in layout)
    assert _visible(apply_tool_layout(catalog, layout)) == _visible(catalog)


def test_v1_layout_applies_moves_and_hidden_tools_like_before() -> None:
    catalog = tool_menu_catalog()
    v1 = copy.deepcopy(default_tool_layout())
    for entry in v1:
        entry.pop("title")
    moved = v1[0]["items"].pop(0)  # caliper: General -> Aorta
    v1[3]["items"].insert(0, moved)
    hidden = v1[0]["items"][0]
    hidden["enabled"] = False

    menu = apply_tool_layout(catalog, decode_tool_layout(json.dumps(v1)))
    sections = dict(menu)

    assert sections["menu.aorta"][0].tool_id == moved["id"]
    visible_ids = {spec.tool_id for _, buttons in menu for spec in buttons}
    assert moved["id"] in visible_ids
    assert hidden["id"] not in visible_ids


def test_v2_roundtrip_keeps_order_titles_and_user_sections() -> None:
    layout = copy.deepcopy(default_tool_layout())
    moved = layout[0]["items"].pop(0)
    layout.insert(0, {"key": "custom:3f2a", "title": "Мои", "items": [moved]})

    raw = encode_tool_layout(layout)

    assert json.loads(raw)["version"] == 2
    assert decode_tool_layout(raw) == layout


def test_decode_v2_skips_untitled_custom_and_unknown_keys() -> None:
    raw = json.dumps(
        {
            "version": 2,
            "sections": [
                {"key": "custom:a", "title": "   ", "items": []},
                {"key": "custom:b", "items": []},
                {"key": "menu.unknown", "title": None, "items": []},
                {"key": "menu.general", "title": None, "items": []},
                {"key": "menu.general", "title": None, "items": [{"id": "x"}]},
            ],
        }
    )

    assert [entry["key"] for entry in decode_tool_layout(raw)] == ["menu.general"]


def test_decode_v2_trims_and_caps_title() -> None:
    raw = json.dumps({"version": 2, "sections": [{"key": "custom:a", "title": "  " + "я" * 60 + "  ", "items": []}]})

    title = decode_tool_layout(raw)[0]["title"]

    assert title == "я" * MAX_CUSTOM_SECTION_TITLE


def test_unknown_layout_version_falls_back_to_default() -> None:
    assert decode_tool_layout('{"version": 3, "sections": []}') == []
    assert decode_tool_layout('{"sections": []}') == []


def test_stored_section_order_is_applied() -> None:
    catalog = tool_menu_catalog()
    layout = list(reversed(default_tool_layout()))

    menu = apply_tool_layout(catalog, decode_tool_layout(encode_tool_layout(layout)))

    assert [key for key, _ in menu] == [entry["key"] for entry in layout]


def test_custom_section_is_kept_when_empty_and_placed_first() -> None:
    layout = [{"key": "custom:e1", "title": "Пусто", "items": []}, *default_tool_layout()]

    menu = apply_tool_layout(tool_menu_catalog(), decode_tool_layout(encode_tool_layout(layout)))

    assert menu[0] == ("custom:e1", ())
    assert len(menu) == len(tool_menu_catalog()) + 1


def test_builtin_section_missing_from_layout_goes_last() -> None:
    catalog = tool_menu_catalog()
    layout = [entry for entry in default_tool_layout() if entry["key"] != "menu.general"]

    sections = normalize_tool_layout(catalog, layout)

    assert sections[-1]["key"] == "menu.general"
    general_ids = [item["id"] for item in sections[-1]["items"]]
    assert general_ids == [spec.tool_id for spec in dict(catalog)["menu.general"]]


def test_tools_in_user_section_reach_the_panel_and_respect_visibility() -> None:
    layout = copy.deepcopy(default_tool_layout())
    moved = layout[0]["items"].pop(0)
    hidden = layout[0]["items"][0]
    hidden["enabled"] = False
    layout.append({"key": "custom:mine", "title": "Мои", "items": [moved]})

    preferences = _preferences_with(layout)
    menu = dict(build_measure_menu(preferences))

    assert [spec.tool_id for spec in menu["custom:mine"]] == [moved["id"]]
    assert hidden["id"] not in {spec.tool_id for _, buttons in build_measure_menu(preferences) for spec in buttons}
    assert custom_section_titles(preferences) == {"custom:mine": "Мои"}


def test_custom_titles_are_empty_without_user_sections() -> None:
    from echo_personal_tool.infrastructure.user_preferences import default_user_preferences

    assert custom_section_titles(default_user_preferences()) == {}
    assert custom_section_titles(None) == {}


# ── Settings → Tools editor ──────────────────────────────────────────────────


def _editor(layout_json: str = ""):
    from echo_personal_tool.presentation.tool_panel_settings import ToolPanelSettingsWidget

    return ToolPanelSettingsWidget(layout_json)


def _answer_prompt(value: str | None):
    """Patch QInputDialog.getText: ``None`` simulates Cancel."""
    from PySide6.QtWidgets import QInputDialog

    reply = (value or "", value is not None)
    return patch.object(QInputDialog, "getText", return_value=reply)


def _encoded_keys(widget) -> list[str]:
    return [entry["key"] for entry in decode_tool_layout(widget.encoded_layout())]


def test_editor_adds_section_at_the_end_with_title() -> None:
    widget = _editor()
    with _answer_prompt("Мои"):
        widget._on_add_section()

    layout = decode_tool_layout(widget.encoded_layout())
    assert layout[-1]["key"].startswith("custom:")
    assert layout[-1]["title"] == "Мои"
    assert layout[-1]["items"] == []


def test_editor_ignores_cancel_and_blank_names() -> None:
    widget = _editor()
    before = widget.encoded_layout()
    with _answer_prompt(None):
        widget._on_add_section()
    with _answer_prompt("   "):
        widget._on_add_section()

    assert widget.encoded_layout() == before


def test_editor_truncates_long_names() -> None:
    widget = _editor()
    with _answer_prompt("б" * 80):
        widget._on_add_section()

    title = decode_tool_layout(widget.encoded_layout())[-1]["title"]
    assert title == "б" * MAX_CUSTOM_SECTION_TITLE


def test_editor_add_button_disables_at_limit() -> None:
    widget = _editor()
    for index in range(MAX_CUSTOM_SECTIONS):
        with _answer_prompt(f"S{index}"):
            widget._on_add_section()
    assert not widget._add_button.isEnabled()

    with _answer_prompt("лишняя"):
        widget._on_add_section()  # guarded even if the button is pressed programmatically
    customs = [key for key in _encoded_keys(widget) if key.startswith("custom:")]
    assert len(customs) == MAX_CUSTOM_SECTIONS


def test_editor_moves_sections_and_disables_edge_buttons() -> None:
    widget = _editor()
    first, second = _encoded_keys(widget)[:2]

    widget._move_section(second, -1)

    keys = _encoded_keys(widget)
    assert keys[:2] == [second, first]
    up, _down = widget._move_buttons[second]
    assert not up.isEnabled()
    last = keys[-1]
    assert not widget._move_buttons[last][1].isEnabled()


def test_editor_renames_user_section() -> None:
    widget = _editor()
    with _answer_prompt("Мои"):
        widget._on_add_section()
    key = _encoded_keys(widget)[-1]

    with _answer_prompt("Для Доплера"):
        widget._on_rename_section(key)

    assert decode_tool_layout(widget.encoded_layout())[-1]["title"] == "Для Доплера"


def test_editor_user_section_collects_tools_and_delete_returns_them() -> None:
    widget = _editor()
    with _answer_prompt("Мои"):
        widget._on_add_section()
    custom = _encoded_keys(widget)[-1]

    moved = widget._lists["menu.general"].takeItem(0)
    moved_id = str(moved.data(Qt.ItemDataRole.UserRole))
    widget._lists[custom].addItem(moved)
    stored = decode_tool_layout(widget.encoded_layout())
    assert [item["id"] for item in stored[-1]["items"]] == [moved_id]

    widget._on_delete_section(custom)

    assert custom not in _encoded_keys(widget)
    general_ids = [
        str(widget._lists["menu.general"].item(index).data(Qt.ItemDataRole.UserRole))
        for index in range(widget._lists["menu.general"].count())
    ]
    assert moved_id in general_ids


def test_editor_delete_ignores_builtin_sections() -> None:
    widget = _editor()
    before = widget.encoded_layout()

    widget._on_delete_section("menu.general")

    assert widget.encoded_layout() == before


def test_editor_layout_survives_restart_with_order_and_titles() -> None:
    widget = _editor()
    with _answer_prompt("Мои"):
        widget._on_add_section()
    custom = _encoded_keys(widget)[-1]
    widget._move_section(custom, -3)

    reopened = _editor(widget.encoded_layout())

    assert _encoded_keys(reopened) == _encoded_keys(widget)
    assert reopened._titles[custom] == "Мои"
