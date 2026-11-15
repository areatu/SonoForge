"""Public read-only frame access for presentation projections (issue #552).

The frame cache owns decoding residency and eviction.  Presentation needs to
know whether a clip is cached, which frame to paint and whether a complete
cine is available, but it must not reach into ``AppController._frame_cache``
or mutate the cache while a background decode is running.  ``FrameAccess`` is
that narrow read-only seam; it is intentionally not a second cache.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from echo_personal_tool.application.frame_cache import FrameCache, FrameCacheStatus
from echo_personal_tool.domain.exceptions import IncompleteCineError


@dataclass(frozen=True)
class FrameAccess:
    """Read-only questions the UI may ask about decoded frames."""

    _cache: FrameCache

    def status(self) -> FrameCacheStatus:
        """Readiness, total and resident frame counts without mutating the cache."""
        return self._cache.status()

    def frame(self, source_path: Path | str | None, index: int) -> np.ndarray | None:
        """Return one resident frame for ``source_path``, or ``None`` on a miss.

        A miss covers every expected lifetime case: no source, another clip
        after a tab switch, an evicted frame and an out-of-range index.  The
        caller falls back to its loader instead of handling cache exceptions.
        """
        if source_path is None or not self._cache.is_ready(Path(source_path)):
            return None
        pixels = self._cache.get_loaded(index)
        return None if pixels is None else np.asarray(pixels)

    def full_cine(self) -> np.ndarray | None:
        """Return the complete cine, or ``None`` while it is incomplete.

        Stacking a full cine is the one operation that may exceed the
        process budget; the results window then keeps the frames carried by
        the analysis result instead of taking the application down.
        """
        try:
            return self._cache.require_full_cine()
        except (IncompleteCineError, MemoryError):
            return None

    def frames(self) -> list[np.ndarray]:
        """Loaded frames in source order, as the legacy M-mode helper expects."""
        frames = self._cache.frames
        if frames is None:
            return []
        return [frames[i] for i in range(frames.shape[0])]
