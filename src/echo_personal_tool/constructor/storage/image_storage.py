"""Image management: resolve, copy, list reference images."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


class ImageStorage:
    """Manage images in the references/images directory."""

    def __init__(self, images_dir: Path | str) -> None:
        self._dir = Path(images_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    @property
    def directory(self) -> Path:
        return self._dir

    def resolve(self, filename: str) -> Path | None:
        """Resolve a filename to full path. Returns None if not found."""
        # Prevent path traversal
        if ".." in filename or "/" in filename or "\\" in filename:
            return None
        path = self._dir / filename
        return path if path.exists() else None

    def copy(self, src: Path | str, filename: str | None = None) -> str:
        """Copy image to images dir. Returns the stored filename."""
        src = Path(src)
        name = filename or src.name
        dest = self._dir / name
        if src.resolve() == dest.resolve():
            return name  # Already in the right place
        shutil.copy2(src, dest)
        return name

    def delete(self, filename: str) -> bool:
        """Delete image from images dir. Returns True if deleted."""
        # Prevent path traversal
        if ".." in filename or "/" in filename or "\\" in filename:
            return False
        path = self._dir / filename
        if path.exists():
            path.unlink()
            return True
        return False

    def rename(self, old_name: str, new_name: str) -> str:
        """Rename image. Returns new filename."""
        # Prevent path traversal
        for name in (old_name, new_name):
            if ".." in name or "/" in name or os.sep in name:
                return old_name
        old_path = self._dir / old_name
        new_path = self._dir / new_name
        if old_path.exists():
            old_path.rename(new_path)
            return new_name
        return old_name

    def list_images(self) -> list[Path]:
        """List all image files in the directory."""
        exts = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg"}
        return sorted(p for p in self._dir.iterdir() if p.is_file() and p.suffix.lower() in exts)

    def orphaned(self, referenced: set[str]) -> list[str]:
        """Find images in dir not referenced by any pathology."""
        actual = {p.name for p in self.list_images()}
        return sorted(actual - referenced)
