"""Tag-independent DICOM frame count inference.

Vendors frequently omit (0028,0008) ``NumberOfFrames`` on genuinely multi-frame
US clips.  Relying on that tag alone then reports 1 frame and the clip is
classified as a still (no CINE playback, no speckle tracking) — the "not always
recognized as a CINE sequence" symptom.  This module recovers the real frame
count from the pixel data whenever the tag is absent or degenerate.
"""

from __future__ import annotations

# (FFFE,E000) Item tag in explicit-VR little-endian byte order.  Every
# encapsulated pixel data stream starts with a Basic Offset Table item followed
# by one item per frame, so the frame count is (item count - 1).
_ITEM_TAG = b"\xfe\xff\x00\xe0"


def infer_dicom_frame_count(dataset, *, pixel_data: bytes | None = None) -> int:
    """Return the best-known frame count for a DICOM dataset.

    Priority order:
      1. (0028,0008) ``NumberOfFrames`` tag when it is present and > 1.
      2. Uncompressed pixel data: ``len(PixelData) / (Rows*Cols*bpp)`` when the
         length is an exact multiple (i.e. the file really holds whole frames).
      3. Encapsulated (compressed) pixel data: number of Item elements minus the
         leading Basic Offset Table item.
      4. Fallback: 1 (a genuine still, or nothing to go on).

    The helper never returns a value larger than 1 unless there is concrete
    evidence, so a true single-frame image always stays at 1.
    """
    tag = dataset.get("NumberOfFrames")
    if tag is not None:
        try:
            tag_n = int(tag)
            if tag_n > 1:
                return tag_n
        except (TypeError, ValueError):
            pass

    if pixel_data:
        rows = dataset.get("Rows")
        cols = dataset.get("Columns")
        if rows and cols:
            try:
                rows, cols = int(rows), int(cols)
                bits_allocated = int(dataset.get("BitsAllocated", 8) or 8)
                samples = int(dataset.get("SamplesPerPixel", 1) or 1)
                frame_size = rows * cols * (bits_allocated // 8) * samples
            except (TypeError, ValueError):
                frame_size = 0
            if frame_size > 0:
                # Uncompressed path: a multi-frame file's raw pixel data is an
                # exact multiple of one frame's size.
                if len(pixel_data) > frame_size and len(pixel_data) % frame_size == 0:
                    n = len(pixel_data) // frame_size
                    if n > 1:
                        return n
                # Encapsulated path: count item tags in the raw stream.
                items = pixel_data.count(_ITEM_TAG)
                n = items - 1  # drop the Basic Offset Table item
                if n > 1:
                    return n
    return 1