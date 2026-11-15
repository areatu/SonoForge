"""Key-image references that survive sorting and cache eviction (#561).

A key image is a *reference*, not a copy of pixels: the study UID is the file
that owns it, the SOP Instance UID names the clip, the frame index names the
still, and a stable ``measurement_id`` names the measurement to return to.
The recorded size/mtime are a local file identity used to tell an unchanged
source from a replaced one; no filesystem path is persisted.
"""

from __future__ import annotations

from dataclasses import dataclass

#: The source is present, unchanged and still has the recorded frame.
KEY_IMAGE_AVAILABLE = "available"
#: The clip is not in the open study, or its file is gone.
KEY_IMAGE_MISSING = "missing"
#: The file or the clip geometry changed since the key image was saved.
KEY_IMAGE_CHANGED = "changed"


@dataclass(frozen=True)
class KeyImage:
    """One saved still of a study, addressed by identity rather than list order."""

    bookmark_id: str
    sop_instance_uid: str
    series_uid: str
    frame_index: int
    frame_count: int
    measurement_id: str = ""
    source_size: int = 0
    source_mtime_ns: int = 0
    created_at: str = ""
