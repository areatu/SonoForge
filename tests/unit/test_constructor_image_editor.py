"""Unit tests for constructor/editors/image_editor and storage/image_storage."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.gui


# ── image_storage ──────────────────────────────────────────────────


class TestImageStorage:
    def test_creation(self, tmp_path) -> None:
        from echo_personal_tool.constructor.storage.image_storage import ImageStorage

        storage = ImageStorage(tmp_path / "images")
        assert storage.directory.exists()

    def test_resolve_existing(self, tmp_path) -> None:
        from echo_personal_tool.constructor.storage.image_storage import ImageStorage

        storage = ImageStorage(tmp_path / "images")
        (tmp_path / "images" / "test.png").write_bytes(b"\x89PNG")
        result = storage.resolve("test.png")
        assert result is not None
        assert result.name == "test.png"

    def test_resolve_nonexistent(self, tmp_path) -> None:
        from echo_personal_tool.constructor.storage.image_storage import ImageStorage

        storage = ImageStorage(tmp_path / "images")
        result = storage.resolve("missing.png")
        assert result is None

    def test_resolve_path_traversal(self, tmp_path) -> None:
        from echo_personal_tool.constructor.storage.image_storage import ImageStorage

        storage = ImageStorage(tmp_path / "images")
        assert storage.resolve("../etc/passwd") is None
        assert storage.resolve("sub/../../file.png") is None
        assert storage.resolve("a\\b\\c.png") is None

    def test_copy(self, tmp_path) -> None:
        import shutil

        from echo_personal_tool.constructor.storage.image_storage import ImageStorage

        storage = ImageStorage(tmp_path / "images")
        src = tmp_path / "source.png"
        src.write_bytes(b"\x89PNG")
        filename = storage.copy(src)
        assert (tmp_path / "images" / filename).exists()

    def test_copy_custom_name(self, tmp_path) -> None:
        from echo_personal_tool.constructor.storage.image_storage import ImageStorage

        storage = ImageStorage(tmp_path / "images")
        src = tmp_path / "source.png"
        src.write_bytes(b"\x89PNG")
        filename = storage.copy(src, "custom.png")
        assert filename == "custom.png"
        assert (tmp_path / "images" / "custom.png").exists()

    def test_list_images(self, tmp_path) -> None:
        from echo_personal_tool.constructor.storage.image_storage import ImageStorage

        storage = ImageStorage(tmp_path / "images")
        (tmp_path / "images" / "a.png").write_bytes(b"\x89PNG")
        (tmp_path / "images" / "b.jpg").write_bytes(b"\xff\xd8")
        images = storage.list_images()
        assert len(images) == 2
        names = [p.name for p in images]
        assert "a.png" in names
        assert "b.jpg" in names

    def test_delete(self, tmp_path) -> None:
        from echo_personal_tool.constructor.storage.image_storage import ImageStorage

        storage = ImageStorage(tmp_path / "images")
        (tmp_path / "images" / "del.png").write_bytes(b"\x89PNG")
        storage.delete("del.png")
        assert not (tmp_path / "images" / "del.png").exists()

    def test_directory_property(self, tmp_path) -> None:
        from echo_personal_tool.constructor.storage.image_storage import ImageStorage

        storage = ImageStorage(tmp_path / "images")
        assert storage.directory == tmp_path / "images"


# ── image_editor ───────────────────────────────────────────────────


class TestImageEditor:
    def test_creation(self, qtbot, tmp_path) -> None:
        from echo_personal_tool.constructor.editors.image_editor import ImageEditor
        from echo_personal_tool.constructor.storage.image_storage import ImageStorage

        storage = ImageStorage(tmp_path / "images")
        editor = ImageEditor(storage)
        qtbot.addWidget(editor)
        assert editor is not None

    def test_set_images(self, qtbot, tmp_path) -> None:
        from echo_personal_tool.constructor.editors.image_editor import ImageEditor
        from echo_personal_tool.constructor.storage.image_storage import ImageStorage

        storage = ImageStorage(tmp_path / "images")
        (tmp_path / "images" / "a.png").write_bytes(b"\x89PNG")
        editor = ImageEditor(storage)
        qtbot.addWidget(editor)
        editor.set_images(["a.png"])
        assert editor._images == ["a.png"]

    def test_on_zoom_changed(self, qtbot, tmp_path) -> None:
        from echo_personal_tool.constructor.editors.image_editor import ImageEditor
        from echo_personal_tool.constructor.storage.image_storage import ImageStorage

        storage = ImageStorage(tmp_path / "images")
        editor = ImageEditor(storage)
        qtbot.addWidget(editor)
        editor._on_zoom_changed("100%")
        assert editor._zoom == 1.0

    def test_on_zoom_changed_fit(self, qtbot, tmp_path) -> None:
        from echo_personal_tool.constructor.editors.image_editor import ImageEditor
        from echo_personal_tool.constructor.storage.image_storage import ImageStorage

        storage = ImageStorage(tmp_path / "images")
        editor = ImageEditor(storage)
        qtbot.addWidget(editor)
        editor._on_zoom_changed("Fit")
        assert editor._zoom == 0.5

    def test_on_zoom_changed_200(self, qtbot, tmp_path) -> None:
        from echo_personal_tool.constructor.editors.image_editor import ImageEditor
        from echo_personal_tool.constructor.storage.image_storage import ImageStorage

        storage = ImageStorage(tmp_path / "images")
        editor = ImageEditor(storage)
        qtbot.addWidget(editor)
        editor._on_zoom_changed("200%")
        assert editor._zoom == 2.0

    def test_on_zoom_changed_unknown(self, qtbot, tmp_path) -> None:
        from echo_personal_tool.constructor.editors.image_editor import ImageEditor
        from echo_personal_tool.constructor.storage.image_storage import ImageStorage

        storage = ImageStorage(tmp_path / "images")
        editor = ImageEditor(storage)
        qtbot.addWidget(editor)
        editor._on_zoom_changed("weird")
        assert editor._zoom == 1.0  # default

    def test_show_preview_nonexistent(self, qtbot, tmp_path) -> None:
        from echo_personal_tool.constructor.editors.image_editor import ImageEditor
        from echo_personal_tool.constructor.storage.image_storage import ImageStorage

        storage = ImageStorage(tmp_path / "images")
        editor = ImageEditor(storage)
        qtbot.addWidget(editor)
        editor._show_preview("nonexistent.png")
        assert "не найден" in editor._preview_label.text().lower()

    def test_delete_selected(self, qtbot, tmp_path) -> None:
        from echo_personal_tool.constructor.editors.image_editor import ImageEditor
        from echo_personal_tool.constructor.storage.image_storage import ImageStorage

        storage = ImageStorage(tmp_path / "images")
        editor = ImageEditor(storage)
        qtbot.addWidget(editor)
        editor.delete_selected()
        # Should not crash
