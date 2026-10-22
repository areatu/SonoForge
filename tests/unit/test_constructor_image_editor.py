"""Tests for editors/image_editor.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

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
def images_dir(tmp_path: Path) -> Path:
    d = tmp_path / "images"
    d.mkdir()
    return d


@pytest.fixture
def storage(images_dir: Path):
    from echo_personal_tool.constructor.storage.image_storage import ImageStorage

    return ImageStorage(images_dir)


@pytest.fixture
def editor(qtbot, storage) -> ImageEditor:
    with patch(
        "echo_personal_tool.constructor.editors.image_editor.get_theme_palette",
        return_value=_THEME,
    ):
        from echo_personal_tool.constructor.editors.image_editor import ImageEditor

        w = ImageEditor(storage)
    qtbot.addWidget(w)
    return w


class TestSetImages:
    def test_set_images(self, editor) -> None:
        editor.set_images(["a.png", "b.jpg"])
        assert editor._images == ["a.png", "b.jpg"]
        assert editor._list.count() == 2

    def test_set_empty(self, editor) -> None:
        editor.set_images([])
        assert editor._images == []
        assert editor._list.count() == 0

    def test_set_replaces(self, editor) -> None:
        editor.set_images(["a.png"])
        editor.set_images(["b.jpg"])
        assert editor._images == ["b.jpg"]
        assert editor._list.count() == 1


class TestZoom:
    def test_zoom_fit(self, editor) -> None:
        editor._on_zoom_changed("Fit")
        assert editor._zoom == 0.5

    def test_zoom_50(self, editor) -> None:
        editor._on_zoom_changed("50%")
        assert editor._zoom == 0.5

    def test_zoom_100(self, editor) -> None:
        editor._on_zoom_changed("100%")
        assert editor._zoom == 1.0

    def test_zoom_200(self, editor) -> None:
        editor._on_zoom_changed("200%")
        assert editor._zoom == 2.0

    def test_zoom_400(self, editor) -> None:
        editor._on_zoom_changed("400%")
        assert editor._zoom == 4.0

    def test_zoom_unknown(self, editor) -> None:
        editor._on_zoom_changed("Unknown")
        assert editor._zoom == 1.0


class TestDragEnterEvent:
    def test_drag_enter_with_urls(self, editor) -> None:
        event = MagicMock()
        event.mimeData.return_value.hasUrls.return_value = True
        editor.dragEnterEvent(event)
        event.acceptProposedAction.assert_called_once()

    def test_drag_enter_without_urls(self, editor) -> None:
        event = MagicMock()
        event.mimeData.return_value.hasUrls.return_value = False
        editor.dragEnterEvent(event)
        event.acceptProposedAction.assert_not_called()


class TestDragLeaveEvent:
    def test_drag_leave(self, editor) -> None:
        event = MagicMock()
        editor.dragLeaveEvent(event)
        # Should not crash; drop hint style updated


class TestDropEvent:
    @patch(
        "echo_personal_tool.constructor.editors.image_editor.get_theme_palette",
        return_value=_THEME,
    )
    def test_drop_valid_image(self, mock_palette, editor, images_dir) -> None:
        # Create a real image file
        img = images_dir / "source.png"
        img.write_bytes(b"fake png")

        url = MagicMock()
        url.toLocalFile.return_value = str(img)

        event = MagicMock()
        event.mimeData.return_value.urls.return_value = [url]

        editor.dropEvent(event)
        assert "source.png" in editor._images

    @patch(
        "echo_personal_tool.constructor.editors.image_editor.get_theme_palette",
        return_value=_THEME,
    )
    def test_drop_non_image_ignored(self, mock_palette, editor, images_dir) -> None:
        txt = images_dir / "readme.txt"
        txt.write_bytes(b"text")

        url = MagicMock()
        url.toLocalFile.return_value = str(txt)

        event = MagicMock()
        event.mimeData.return_value.urls.return_value = [url]

        editor.dropEvent(event)
        assert len(editor._images) == 0

    @patch(
        "echo_personal_tool.constructor.editors.image_editor.get_theme_palette",
        return_value=_THEME,
    )
    def test_drop_nonexistent_file(self, mock_palette, editor) -> None:
        url = MagicMock()
        url.toLocalFile.return_value = "/nonexistent/file.png"

        event = MagicMock()
        event.mimeData.return_value.urls.return_value = [url]

        editor.dropEvent(event)
        assert len(editor._images) == 0

    @patch(
        "echo_personal_tool.constructor.editors.image_editor.get_theme_palette",
        return_value=_THEME,
    )
    def test_drop_no_duplicate(self, mock_palette, editor, images_dir) -> None:
        img = images_dir / "source.png"
        img.write_bytes(b"fake png")
        editor._images = ["source.png"]

        url = MagicMock()
        url.toLocalFile.return_value = str(img)

        event = MagicMock()
        event.mimeData.return_value.urls.return_value = [url]

        editor.dropEvent(event)
        assert editor._images.count("source.png") == 1

    @patch(
        "echo_personal_tool.constructor.editors.image_editor.get_theme_palette",
        return_value=_THEME,
    )
    def test_drop_emits_signal(self, mock_palette, editor, images_dir, qtbot) -> None:
        img = images_dir / "new.png"
        img.write_bytes(b"png")

        url = MagicMock()
        url.toLocalFile.return_value = str(img)

        event = MagicMock()
        event.mimeData.return_value.urls.return_value = [url]

        received = []
        editor.images_changed.connect(lambda: received.append(True))
        editor.dropEvent(event)
        assert len(received) >= 1


class TestDeleteImage:
    @patch("echo_personal_tool.constructor.editors.image_editor.QMessageBox")
    def test_delete_confirmed(self, mock_msgbox, editor) -> None:
        mock_msgbox.question.return_value = mock_msgbox.StandardButton.Yes
        editor._images = ["test.png"]
        # Mock current item
        mock_item = MagicMock()
        mock_item.data.return_value = "test.png"
        editor._list.currentItem = MagicMock(return_value=mock_item)

        editor._delete_image()
        assert "test.png" not in editor._images

    @patch("echo_personal_tool.constructor.editors.image_editor.QMessageBox")
    def test_delete_cancelled(self, mock_msgbox, editor) -> None:
        mock_msgbox.question.return_value = mock_msgbox.StandardButton.No
        editor._images = ["test.png"]
        mock_item = MagicMock()
        mock_item.data.return_value = "test.png"
        editor._list.currentItem = MagicMock(return_value=mock_item)

        editor._delete_image()
        assert "test.png" in editor._images

    def test_delete_no_selection(self, editor) -> None:
        editor._list.currentItem = MagicMock(return_value=None)
        editor._images = ["test.png"]
        editor._delete_image()
        assert "test.png" in editor._images


class TestOnItemChanged:
    def test_on_item_changed_with_item(self, editor, images_dir) -> None:
        img = images_dir / "test.png"
        img.write_bytes(b"png")
        editor.set_images(["test.png"])

        current = editor._list.item(0)
        editor._on_item_changed(current, None)

    def test_on_item_changed_none(self, editor) -> None:
        editor._on_item_changed(None, None)


class TestDeleteSelected:
    @patch("echo_personal_tool.constructor.editors.image_editor.QMessageBox")
    def test_delete_selected_delegates(self, mock_msgbox, editor) -> None:
        mock_msgbox.question.return_value = mock_msgbox.StandardButton.Yes
        editor._images = ["test.png"]
        mock_item = MagicMock()
        mock_item.data.return_value = "test.png"
        editor._list.currentItem = MagicMock(return_value=mock_item)
        editor.delete_selected()
        assert "test.png" not in editor._images


class TestShowPreview:
    def test_show_preview_missing_file(self, editor) -> None:
        editor._show_preview("nonexistent.png")
        assert "не найден" in editor._preview_label.text()
