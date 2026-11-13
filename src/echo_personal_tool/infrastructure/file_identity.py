"""Shared, inexpensive identity for on-disk media generations.

Not a content hash or an atomic filesystem snapshot. Size/mtime plus ctime and
file ID detect ordinary in-place writes and atomic replacement (even if a tool
preserves mtime). All paths are canonicalized before comparison.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FileIdentity:
    path: Path
    size: int
    mtime_ns: int
    ctime_ns: int
    device: int
    inode: int

    @classmethod
    def capture(cls, path: Path) -> FileIdentity:
        resolved = path.resolve()
        stat = resolved.stat()
        return cls(resolved, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_dev, stat.st_ino)
