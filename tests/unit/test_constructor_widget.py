"""Tests for constructor_widget.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from echo_personal_tool.constructor.storage.yaml_storage import YamlStorage

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
def sample_data() -> dict:
    return {
        "topics": [
            {
                "name": "Левый желудочек",
                "slug": "lv",
                "pathologies": [
                    {
                        "name": "Диастолическая",
                        "slug": "lv_diag",
                        "parameters": [
                            {
                                "id": "ea_ratio",
                                "name": "E/A ratio",
                                "unit": "",
                                "norm_male": {"low": 0.8, "high": 2.0},
                            }
                        ],
                    }
                ],
            }
        ]
    }


@pytest.fixture
def yaml_file(tmp_path: Path, sample_data: dict) -> Path:
    path = tmp_path / "test.yaml"
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(sample_data, f, allow_unicode=True)
    return path


@pytest.fixture
def widget(qtbot, yaml_file) -> ConstructorWidget:
    with patch(
        "echo_personal_tool.constructor.constructor_widget.get_theme_palette",
        return_value=_THEME,
    ):
        with patch(
            "echo_personal_tool.constructor.editors.topic_editor.get_theme_palette",
            return_value=_THEME,
        ):
            with patch(
                "echo_personal_tool.constructor.editors.pathology_editor.get_theme_palette",
                return_value=_THEME,
            ):
                with patch(
                    "echo_personal_tool.constructor.editors.parameter_table_editor.get_theme_palette",
                    return_value=_THEME,
                ):
                    with patch(
                        "echo_personal_tool.constructor.editors.image_editor.get_theme_palette",
                        return_value=_THEME,
                    ):
                        with patch(
                            "echo_personal_tool.constructor.editors.metadata_editor.get_theme_palette",
                            return_value=_THEME,
                        ):
                            from echo_personal_tool.constructor.constructor_widget import (
                                ConstructorWidget,
                            )

                            storage = YamlStorage(yaml_file)
                            from echo_personal_tool.constructor.storage.schema_validator import (
                                SchemaValidator,
                            )

                            with patch.object(SchemaValidator, "__init__", lambda self: None):
                                validator = SchemaValidator()
                                validator.validate = MagicMock(return_value=[])
                            w = ConstructorWidget(
                                yaml_storage=storage,
                                validator=validator,
                            )
    qtbot.addWidget(w)
    return w


class TestInit:
    def test_loads_model(self, widget) -> None:
        assert len(widget._model.topics) == 1
        assert widget._model.topics[0].slug == "lv"

    def test_initial_not_dirty(self, widget) -> None:
        assert widget._dirty is False


class TestOnTopicSelected:
    def test_select_topic(self, widget) -> None:
        widget._on_topic_selected("lv")
        # Should set pathologies in the pathology editor
        assert len(widget._pathology_editor._pathologies) == 1

    def test_select_nonexistent(self, widget) -> None:
        widget._on_topic_selected("nonexistent")
        # Should not crash; current_pathology remains None


class TestOnPathologySelected:
    def test_select_pathology(self, widget) -> None:
        widget._on_pathology_selected("lv_diag")
        assert widget._current_pathology is not None
        assert widget._current_pathology.slug == "lv_diag"

    def test_select_nonexistent(self, widget) -> None:
        widget._on_pathology_selected("nonexistent")
        assert widget._current_pathology is None


class TestOnParameterSelected:
    def test_select_parameter(self, widget) -> None:
        widget._on_parameter_selected("ea_ratio")
        # Metadata editor should receive the parameter
        assert widget._metadata_editor._parameter is not None
        assert widget._metadata_editor._parameter.id == "ea_ratio"

    def test_select_nonexistent(self, widget) -> None:
        widget._on_parameter_selected("nonexistent")
        # Should not crash


class TestOnImagesChanged:
    def test_sync_images(self, widget) -> None:
        widget._on_topic_selected("lv")
        widget._on_pathology_selected("lv_diag")
        widget._current_pathology.image_paths = []
        widget._image_editor._images = ["new_img.png"]
        widget._on_images_changed()
        assert widget._current_pathology.image_paths == ["new_img.png"]
        assert widget._dirty is True

    def test_no_current_pathology(self, widget) -> None:
        widget._current_pathology = None
        widget._image_editor._images = ["img.png"]
        # Should not crash or mark dirty
        assert widget._dirty is False


class TestSearch:
    def test_search_empty(self, widget) -> None:
        widget._topic_editor.set_topics = MagicMock()
        widget._pathology_editor.set_pathologies = MagicMock()
        widget._param_table.set_parameters = MagicMock()
        widget._topic_editor.clear_filter = MagicMock()
        widget._pathology_editor.clear_filter = MagicMock()
        widget._param_table.clear_filter = MagicMock()
        widget._on_search("")
        widget._topic_editor.clear_filter.assert_called_once()
        widget._pathology_editor.clear_filter.assert_called_once()

    def test_search_whitespace(self, widget) -> None:
        widget._topic_editor.clear_filter = MagicMock()
        widget._pathology_editor.clear_filter = MagicMock()
        widget._param_table.clear_filter = MagicMock()
        widget._on_search("   ")
        widget._topic_editor.clear_filter.assert_called_once()

    def test_search_with_query(self, widget) -> None:
        widget._topic_editor.filter = MagicMock()
        widget._pathology_editor.filter = MagicMock()
        widget._param_table.filter = MagicMock()
        widget._on_search("test")
        widget._topic_editor.filter.assert_called_once_with("test")
        widget._pathology_editor.filter.assert_called_once_with("test")


class TestDirtyTracking:
    def test_mark_dirty(self, widget) -> None:
        received = []
        widget.dirty_changed.connect(lambda v: received.append(v))
        widget._mark_dirty()
        assert widget._dirty is True
        assert len(received) >= 1

    def test_clear_dirty(self, widget) -> None:
        widget._dirty = True
        received = []
        widget.dirty_changed.connect(lambda v: received.append(v))
        widget._clear_dirty()
        assert widget._dirty is False


class TestSave:
    def test_save_validates(self, widget) -> None:
        widget._validator.validate = MagicMock(return_value=[])
        widget._yaml_storage.save = MagicMock()
        widget._mark_dirty()
        widget.save()
        widget._validator.validate.assert_called_once()
        widget._yaml_storage.save.assert_called_once()

    def test_save_validation_errors(self, widget) -> None:
        from echo_personal_tool.constructor.storage.schema_validator import ValidationError

        widget._validator.validate = MagicMock(
            return_value=[ValidationError(path="topics", message="err")]
        )
        widget._mark_dirty()
        with patch(
            "echo_personal_tool.constructor.constructor_widget.QMessageBox"
        ) as mock_msgbox:
            widget.save()
            mock_msgbox.warning.assert_called_once()
        assert widget._dirty is True


class TestUndo:
    def test_undo_when_clean(self, widget) -> None:
        widget.undo()
        # Should return early, not crash

    @patch("echo_personal_tool.constructor.constructor_widget.QMessageBox")
    def test_undo_confirmed(self, mock_msgbox, widget) -> None:
        mock_msgbox.question.return_value = mock_msgbox.StandardButton.Yes
        widget._mark_dirty()
        widget.undo()
        assert widget._dirty is False

    @patch("echo_personal_tool.constructor.constructor_widget.QMessageBox")
    def test_undo_cancelled(self, mock_msgbox, widget) -> None:
        mock_msgbox.question.return_value = mock_msgbox.StandardButton.No
        widget._mark_dirty()
        widget.undo()
        assert widget._dirty is True


class TestValidate:
    @patch("echo_personal_tool.constructor.constructor_widget.QMessageBox")
    def test_validate_with_errors(self, mock_msgbox, widget) -> None:
        from echo_personal_tool.constructor.storage.schema_validator import ValidationError

        widget._validator.validate = MagicMock(
            return_value=[ValidationError(path="t", message="err1")]
        )
        widget.validate()
        mock_msgbox.warning.assert_called_once()

    @patch("echo_personal_tool.constructor.constructor_widget.QMessageBox")
    def test_validate_no_errors(self, mock_msgbox, widget) -> None:
        widget._validator.validate = MagicMock(return_value=[])
        widget.validate()
        mock_msgbox.information.assert_called_once()


class TestDeleteSelected:
    def test_delete_no_focus(self, widget) -> None:
        focused = MagicMock(spec=[])  # no delete_selected attr
        widget.focusWidget = MagicMock(return_value=focused)
        widget.delete_selected()
        # Should not crash


class TestFocusSearch:
    def test_focus_search(self, widget) -> None:
        widget._search_bar.setFocus = MagicMock()
        widget._search_bar.selectAll = MagicMock()
        widget.focus_search()
        widget._search_bar.setFocus.assert_called_once()
        widget._search_bar.selectAll.assert_called_once()
