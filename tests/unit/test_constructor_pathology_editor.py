"""Tests for editors/pathology_editor.py."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from echo_personal_tool.constructor.models import PathologyModel

pytestmark = pytest.mark.gui

_THEME = {
    "bg_dark": "#111827",
    "bg_panel": "#1a2332",
    "bg_control": "#243044",
    "bg_button": "#2e4054",
    "bg_button_hover": "#3a5068",
    "bg_button_pressed": "#1e2a38",
    "accent": "#9ca3b0",
    "accent_bright": "#b0b8c0",
    "accent_tab": "#3b82f6",
    "text": "#f1f5f9",
    "text_dim": "#94a3b8",
    "border": "#334155",
}


@pytest.fixture
def pathologies() -> list[PathologyModel]:
    return [
        PathologyModel(name="Диастолическая", slug="diastolic"),
        PathologyModel(name="Систолическая", slug="systolic"),
    ]


@pytest.fixture
def editor(qtbot) -> PathologyEditor:
    from echo_personal_tool.constructor.editors.pathology_editor import PathologyEditor

    with patch(
        "echo_personal_tool.constructor.editors.pathology_editor.get_theme_palette",
        return_value=_THEME,
    ):
        w = PathologyEditor()
    qtbot.addWidget(w)
    return w


class TestSetPathologies:
    def test_set_pathologies(self, editor, pathologies) -> None:
        editor.set_pathologies(pathologies)
        assert len(editor._pathologies) == 2
        assert len(editor._all_items) == 2

    def test_set_empty(self, editor) -> None:
        editor.set_pathologies([])
        assert editor._list.count() == 0


class TestGetSelectedSlugs:
    def test_get_selected_empty(self, editor) -> None:
        assert editor.get_selected_slugs() == []


class TestFilter:
    def test_filter_match_name(self, editor, pathologies) -> None:
        editor.set_pathologies(pathologies)
        editor.filter("диастолич")
        assert editor._list.count() == 1

    def test_filter_match_slug(self, editor, pathologies) -> None:
        editor.set_pathologies(pathologies)
        editor.filter("systolic")
        assert editor._list.count() == 1

    def test_filter_no_match(self, editor, pathologies) -> None:
        editor.set_pathologies(pathologies)
        editor.filter("zzz")
        assert editor._list.count() == 0

    def test_clear_filter(self, editor, pathologies) -> None:
        editor.set_pathologies(pathologies)
        editor.filter("диастолич")
        editor.clear_filter()
        assert editor._list.count() == 2


class TestAddPathology:
    def test_add_pathology(self, editor) -> None:
        editor.set_pathologies([])
        editor._add_pathology()
        assert len(editor._pathologies) == 1
        assert editor._pathologies[0].slug == "new_pathology_1"

    def test_add_pathology_unique_slug(self, editor) -> None:
        existing = [PathologyModel(name="N", slug="new_pathology_1")]
        editor.set_pathologies(existing)
        editor._add_pathology()
        assert editor._pathologies[-1].slug == "new_pathology_2"

    def test_add_pathology_emits_signal(self, editor) -> None:
        editor.set_pathologies([])
        received = []
        editor.pathologies_changed.connect(lambda: received.append(True))
        editor._add_pathology()
        assert len(received) >= 1


class TestDuplicatePathology:
    def test_duplicate(self, editor, pathologies) -> None:
        editor.set_pathologies(pathologies)
        editor._list.setCurrentRow(0)
        editor._duplicate_pathology()
        assert len(editor._pathologies) == 3
        assert "copy_1" in editor._pathologies[-1].slug

    def test_duplicate_no_selection(self, editor) -> None:
        editor.set_pathologies([])
        editor._duplicate_pathology()
        assert len(editor._pathologies) == 0

    def test_duplicate_emits_signal(self, editor, pathologies) -> None:
        editor.set_pathologies(pathologies)
        editor._list.setCurrentRow(0)
        received = []
        editor.pathologies_changed.connect(lambda: received.append(True))
        editor._duplicate_pathology()
        assert len(received) >= 1


class TestDeleteSelected:
    @patch("echo_personal_tool.constructor.editors.pathology_editor.QMessageBox")
    def test_delete_confirmed(self, mock_msgbox, editor, pathologies) -> None:
        mock_msgbox.question.return_value = mock_msgbox.StandardButton.Yes
        editor.set_pathologies(pathologies)
        editor._list.setCurrentRow(0)
        editor.delete_selected()
        assert len(editor._pathologies) == 1

    @patch("echo_personal_tool.constructor.editors.pathology_editor.QMessageBox")
    def test_delete_cancelled(self, mock_msgbox, editor, pathologies) -> None:
        mock_msgbox.question.return_value = mock_msgbox.StandardButton.No
        editor.set_pathologies(pathologies)
        editor._list.setCurrentRow(0)
        editor.delete_selected()
        assert len(editor._pathologies) == 2

    def test_delete_no_selection(self, editor) -> None:
        editor.set_pathologies([])
        editor.delete_selected()
        assert len(editor._pathologies) == 0
