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
    section = next(block for block in widget.current_layout().context(CONTEXT_COMMON).sections if block.key == key)
    assert section.title == "Мои"


def test_tools_editor_fits_narrow_settings_viewport() -> None:
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QPushButton, QScrollArea

    from echo_personal_tool.infrastructure.i18n import get_language, set_language
    from echo_personal_tool.presentation.dark_theme import build_clinical_stylesheet
    from echo_personal_tool.presentation.tool_settings_2 import ToolSettings2Widget

    original_language = get_language()
    try:
        for language in ("ru", "en"):
            set_language(language)
            editor = ToolSettings2Widget()
            editor.ensure_editable_profile()
            editor._catalog_ru.setText("Диаметр аорты на уровне синусов Вальсальвы")
            editor._catalog_en.setText("Long catalog caption that must wrap inside the properties pane")
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setStyleSheet(build_clinical_stylesheet(13, theme="vscode_dark"))
            scroll.setWidget(editor)
            try:
                for width in (560, 680):
                    scroll.resize(width, 460)
                    scroll.show()
                    QApplication.processEvents()
                    assert editor.width() <= scroll.viewport().width()
                    assert scroll.horizontalScrollBar().maximum() == 0
                    for button in editor.findChildren(QPushButton):
                        origin = button.mapTo(editor, QPoint(0, 0))
                        assert origin.x() >= 0
                        assert origin.x() + button.width() <= editor.width()
            finally:
                scroll.close()
                scroll.deleteLater()
    finally:
        set_language(original_language)


@pytest.mark.parametrize("theme", ["graphite", "light"])
def test_section_checkboxes_fit_rows_and_toggle_visibility(qtbot, widget, theme) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QStyle, QStyleOptionViewItem

    from echo_personal_tool.presentation.dark_theme import build_clinical_stylesheet

    app = QApplication.instance()
    before = app.styleSheet()
    try:
        app.setStyleSheet(build_clinical_stylesheet(13, theme=theme))
        qtbot.addWidget(widget)
        widget.duplicate_profile("Checkbox test")
        widget.resize(1050, 800)
        widget.show()
        app.processEvents()
        tree = widget._sections
        item = tree.topLevelItem(0)
        index = tree.indexFromItem(item)
        option = QStyleOptionViewItem()
        option.initFrom(tree)
        tree.itemDelegate().initStyleOption(option, index)
        option.rect = tree.visualRect(index)
        check = tree.style().subElementRect(QStyle.SubElement.SE_ItemViewItemCheckIndicator, option, tree)
        text = tree.style().subElementRect(QStyle.SubElement.SE_ItemViewItemText, option, tree)
        assert option.rect.height() >= check.height() >= 16
        assert text.left() >= check.right()
        assert item.checkState(0) == Qt.CheckState.Checked
        qtbot.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=check.center())
        assert widget._resolved_sections()[0].visible is False
        assert widget.undo()
        assert widget._resolved_sections()[0].visible is True
    finally:
        app.setStyleSheet(before)
