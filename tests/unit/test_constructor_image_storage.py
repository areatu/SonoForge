"""Tests for storage/image_storage.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from echo_personal_tool.constructor.storage.image_storage import ImageStorage


@pytest.fixture
def images_dir(tmp_path: Path) -> Path:
    d = tmp_path / "images"
    d.mkdir()
    return d


@pytest.fixture
def storage(images_dir: Path) -> ImageStorage:
    return ImageStorage(images_dir)


class TestImageStorageInit:
    def test_creates_directory(self, tmp_path: Path) -> None:
        d = tmp_path / "new_images"
        assert not d.exists()
        ImageStorage(d)
        assert d.exists()

    def test_directory_property(self, images_dir: Path) -> None:
        storage = ImageStorage(images_dir)
        assert storage.directory == images_dir

    def test_creates_nested_directory(self, tmp_path: Path) -> None:
        d = tmp_path / "a" / "b" / "c"
        assert not d.exists()
        ImageStorage(d)
        assert d.exists()


class TestResolve:
    def test_resolve_existing(self, images_dir: Path) -> None:
        (images_dir / "test.png").write_bytes(b"fake")
        storage = ImageStorage(images_dir)
        result = storage.resolve("test.png")
        assert result == images_dir / "test.png"

    def test_resolve_missing(self, images_dir: Path) -> None:
        storage = ImageStorage(images_dir)
        assert storage.resolve("nonexistent.png") is None

    def test_resolve_path_traversal_dotdot(self, storage: ImageStorage) -> None:
        assert storage.resolve("../etc/passwd") is None

    def test_resolve_path_traversal_slash(self, storage: ImageStorage) -> None:
        assert storage.resolve("foo/bar.png") is None

    def test_resolve_path_traversal_backslash(self, storage: ImageStorage) -> None:
        assert storage.resolve("foo\\bar.png") is None


class TestCopy:
    def test_copy_file(self, images_dir: Path, tmp_path: Path) -> None:
        src = tmp_path / "source.png"
        src.write_bytes(b"image data")
        storage = ImageStorage(images_dir)
        result = storage.copy(src)
        assert result == "source.png"
        assert (images_dir / "source.png").read_bytes() == b"image data"

    def test_copy_with_custom_filename(self, images_dir: Path, tmp_path: Path) -> None:
        src = tmp_path / "source.png"
        src.write_bytes(b"data")
        storage = ImageStorage(images_dir)
        result = storage.copy(src, filename="custom.png")
        assert result == "custom.png"
        assert (images_dir / "custom.png").exists()

    def test_copy_already_in_place(self, images_dir: Path) -> None:
        src = images_dir / "existing.png"
        src.write_bytes(b"data")
        storage = ImageStorage(images_dir)
        result = storage.copy(src)
        assert result == "existing.png"


class TestDelete:
    def test_delete_existing(self, images_dir: Path) -> None:
        (images_dir / "to_delete.png").write_bytes(b"data")
        storage = ImageStorage(images_dir)
        assert storage.delete("to_delete.png") is True
        assert not (images_dir / "to_delete.png").exists()

    def test_delete_nonexistent(self, storage: ImageStorage) -> None:
        assert storage.delete("nonexistent.png") is False

    def test_delete_path_traversal_dotdot(self, storage: ImageStorage) -> None:
        assert storage.delete("../etc/passwd") is False

    def test_delete_path_traversal_slash(self, storage: ImageStorage) -> None:
        assert storage.delete("a/b.png") is False

    def test_delete_path_traversal_backslash(self, storage: ImageStorage) -> None:
        assert storage.delete("a\\b.png") is False


class TestRename:
    def test_rename_existing(self, images_dir: Path) -> None:
        (images_dir / "old.png").write_bytes(b"data")
        storage = ImageStorage(images_dir)
        result = storage.rename("old.png", "new.png")
        assert result == "new.png"
        assert (images_dir / "new.png").exists()
        assert not (images_dir / "old.png").exists()

    def test_rename_nonexistent(self, storage: ImageStorage) -> None:
        result = storage.rename("missing.png", "new.png")
        assert result == "missing.png"

    def test_rename_path_traversal_old(self, storage: ImageStorage) -> None:
        result = storage.rename("../bad.png", "ok.png")
        assert result == "../bad.png"

    def test_rename_path_traversal_new(self, storage: ImageStorage) -> None:
        result = storage.rename("ok.png", "../bad.png")
        assert result == "ok.png"


class TestListImages:
    def test_list_empty(self, storage: ImageStorage) -> None:
        assert storage.list_images() == []

    def test_list_images(self, images_dir: Path) -> None:
        (images_dir / "a.png").write_bytes(b"x")
        (images_dir / "b.jpg").write_bytes(b"y")
        (images_dir / "c.txt").write_bytes(b"z")  # not an image
        storage = ImageStorage(images_dir)
        result = storage.list_images()
        names = [p.name for p in result]
        assert "a.png" in names
        assert "b.jpg" in names
        assert "c.txt" not in names

    def test_list_sorted(self, images_dir: Path) -> None:
        (images_dir / "c.png").write_bytes(b"x")
        (images_dir / "a.png").write_bytes(b"y")
        storage = ImageStorage(images_dir)
        result = storage.list_images()
        assert result == sorted(result)

    def test_list_various_extensions(self, images_dir: Path) -> None:
        for ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg"):
            (images_dir / f"img{ext}").write_bytes(b"data")
        storage = ImageStorage(images_dir)
        assert len(storage.list_images()) == 6


class TestOrphaned:
    def test_all_orphaned(self, images_dir: Path) -> None:
        (images_dir / "a.png").write_bytes(b"x")
        (images_dir / "b.png").write_bytes(b"y")
        storage = ImageStorage(images_dir)
        result = storage.orphaned(set())
        assert result == ["a.png", "b.png"]

    def test_none_orphaned(self, images_dir: Path) -> None:
        (images_dir / "a.png").write_bytes(b"x")
        storage = ImageStorage(images_dir)
        result = storage.orphaned({"a.png"})
        assert result == []

    def test_partial_orphaned(self, images_dir: Path) -> None:
        (images_dir / "a.png").write_bytes(b"x")
        (images_dir / "b.png").write_bytes(b"y")
        storage = ImageStorage(images_dir)
        result = storage.orphaned({"a.png"})
        assert result == ["b.png"]
