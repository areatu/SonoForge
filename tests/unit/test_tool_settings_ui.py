"""Tools settings 2.0 editor (TP-5 PR-2)."""

from __future__ import annotations

import json

import pytest

from echo_personal_tool.domain import tool_settings as settings
from echo_personal_tool.domain.tool_layout_v3 import CONTEXT_COMMON, default_layout

pytestmark = pytest.mark.gui

from PySide6.QtWidgets import QApplication, QMessageBox


@pytest.fixture(scope="module", autouse=True)
def _qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture()
def widget(monkeypatch):
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *args, **kwargs: None))
    from echo_personal_tool.presentation.tool_settings_2 import ToolSettings2Widget

    return ToolSettings2Widget()


def _profile(widget, profile_id: str | None = None):
    profile = widget.current_layout().profile(profile_id)
    assert profile is not None
    return profile


def test_builtin_profile_is_read_only(widget) -> None:
    assert widget._editable is False
    assert json.loads(widget.encoded_layout())["version"] == 3
    assert widget.duplicate_profile("Моя эхо") != "builtin.adult_echo"
    assert widget._editable is True


def test_duplicate_and_undo_restore_the_builtin_profile(widget) -> None:
    widget.duplicate_profile("Моя эхо")
    assert widget.current_layout().active_profile != "builtin.adult_echo"
    assert widget.undo() is True
    assert widget.current_layout().active_profile == "builtin.adult_echo"
    assert widget.redo() is True
    assert widget.current_layout().active_profile != "builtin.adult_echo"


def test_key_conflict_is_not_saved_without_force(widget) -> None:
    widget.duplicate_profile("Моя эхо")
    assert widget.assign_key("lv.linear_ed", "L") is False
    assert settings.tool_props(widget.current_layout(), "lv.linear_ed").key is None
    assert widget.find_conflict("lv.linear_ed", "L") is not None


def test_invalid_import_keeps_the_current_layout(widget, monkeypatch) -> None:
    widget.duplicate_profile("Моя эхо")
    before = widget.encoded_layout()
    assert widget.import_text("not json") is False
    assert widget.encoded_layout() == before
    assert widget.import_text('{"version": 3, "profiles": []}') is False
    assert widget.encoded_layout() == before


def test_valid_import_replaces_the_layout(widget, tmp_path) -> None:
    source = settings.duplicate_profile(default_layout(), new_id="user-9", name="Импорт")
    source = settings.set_context_quick(source, "2d", ("tool.caliper",))
    document = settings.export_layout(source)
    assert widget.import_text(document) is True
    assert widget.current_layout().active_profile == "user-9"
    context = _profile(widget, "user-9").contexts["2d"]
    assert context.quick == ("tool.caliper",)

    path = tmp_path / "layout.json"
    assert widget.export_to(path) is True
    exported = json.loads(path.read_text(encoding="utf-8"))
    assert [profile["id"] for profile in exported["profiles"]] == ["builtin.adult_echo", "user-9"]


def test_reset_context_returns_an_inherited_context(widget) -> None:
    widget.duplicate_profile("Моя эхо")
    widget._context = "2d"
    widget._refresh_all()
    layout = settings.set_context_quick(widget.current_layout(), "2d", ("tool.caliper",))
    widget._apply(layout)
    assert "2d" in _profile(widget).contexts
    widget.reset_context()
    assert "2d" not in _profile(widget).contexts


def test_custom_section_is_added_to_the_active_context(widget) -> None:
    widget.duplicate_profile("Моя эхо")
    key = widget.add_custom_section("Мои")
    assert key is not None
    section = next(
        block for block in widget.current_layout().context(CONTEXT_COMMON).sections if block.key == key
    )
    assert section.title == "Мои"
