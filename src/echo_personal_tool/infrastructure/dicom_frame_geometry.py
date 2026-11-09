"""Per-frame size limit and pixel-data layout of a DICOM file, from the header only (#475).

A study is never refused for its *length* — a one-minute cine is ~1 500 frames and must
open (see ``DicomSession._open_impl``). A single *frame* is a different matter: its size
comes straight from ``Rows × Columns × SamplesPerPixel × BitsAllocated`` in the header, and
a decoder allocates it in one piece. A header claiming 65535 × 65535 × 3 asks a JPEG/J2K
decoder for ~12.9 GB at once — a ``MemoryError`` or an OOM kill instead of a clear
refusal. :func:`check_frame_geometry` rejects such a header before any pixel byte is read.

:func:`pixel_data_layout` locates the PixelData element without reading it: the offset of
the element comes from the header-only parse, and for encapsulated (compressed) data the
fragment items are walked with 8-byte reads. It replaces the old frame-count recovery that
read the whole file and then parsed it a second time from memory.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from pydicom.dataset import Dataset

#: Largest decoded frame the viewer accepts, in bytes.
#:
#: 256 MiB holds an 8K (7680 × 4320) RGB frame at 16 bits per sample (~199 MB) with room
#: to spare; the largest clinical echo frames are ~1920 × 1080 RGB 8-bit (~6 MB), so the
#: limit is ~40× above anything an ultrasound machine writes, and ~50× below the 12.9 GB a
#: forged 65535 × 65535 × 3 × 16-bit header would request. One constant, one place.
MAX_FRAME_BYTES = 256 * 1024 * 1024

_PIXEL_DATA_TAG = struct.pack("<HH", 0x7FE0, 0x0010)
_ITEM = (0xFFFE, 0xE000)
_SEQUENCE_DELIMITER = (0xFFFE, 0xE0DD)
_UNDEFINED_LENGTH = 0xFFFFFFFF
_EXPLICIT_LONG_VRS = frozenset({b"OB", b"OW", b"OF", b"OD", b"OL", b"OV", b"UN"})


class DicomFrameGeometryError(ValueError):
    """The header describes a frame that cannot or must not be decoded.

    ``code`` is an allowlisted diagnostic code (``safe_diagnostics._CODES``): ``"limit"``
    for a frame above :data:`MAX_FRAME_BYTES`, ``"invalid"`` for an impossible geometry.
    The message is static — it never carries a path, a UID or a header value.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class FrameGeometry:
    rows: int
    columns: int
    samples_per_pixel: int
    bits_allocated: int

    @property
    def frame_bytes(self) -> int:
        """Bytes of one decoded frame (sub-byte samples are rounded up to a byte)."""
        return self.rows * self.columns * self.samples_per_pixel * math.ceil(self.bits_allocated / 8)


def _header_int(dataset: Dataset, keyword: str, default: int | None) -> int | None:
    value = dataset.get(keyword, default)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        raise DicomFrameGeometryError("invalid", f"DICOM header has a non-numeric {keyword}") from None


def check_frame_geometry(dataset: Dataset, *, limit: int = MAX_FRAME_BYTES) -> FrameGeometry | None:
    """Validate the frame geometry of a header-only dataset before anything is allocated.

    Returns ``None`` for a dataset without pixel geometry (a Structured Report, a
    Presentation State) — those are not this check's business. Raises
    :class:`DicomFrameGeometryError` for zero/negative dimensions and for a frame above
    ``limit`` bytes.
    """
    rows = _header_int(dataset, "Rows", None)
    columns = _header_int(dataset, "Columns", None)
    if rows is None and columns is None:
        return None
    samples = _header_int(dataset, "SamplesPerPixel", 1)
    bits = _header_int(dataset, "BitsAllocated", 8)
    if rows is None or columns is None or rows <= 0 or columns <= 0:
        raise DicomFrameGeometryError("invalid", "DICOM header has no positive Rows/Columns")
    if samples is None or samples <= 0 or bits is None or bits <= 0:
        raise DicomFrameGeometryError("invalid", "DICOM header has no positive SamplesPerPixel/BitsAllocated")
    geometry = FrameGeometry(rows=rows, columns=columns, samples_per_pixel=samples, bits_allocated=bits)
    if geometry.frame_bytes > limit:
        raise DicomFrameGeometryError("limit", f"DICOM frame exceeds the {limit // (1024 * 1024)} MiB per-frame limit")
    return geometry


@dataclass(frozen=True)
class PixelDataLayout:
    """Where the PixelData value lives in the file.

    ``start``/``length`` delimit the value as pydicom would return it (for encapsulated
    data: the Basic Offset Table item and the fragment items, without the sequence
    delimiter). ``items`` counts the items of encapsulated data, ``None`` for native data.
    """

    start: int
    length: int
    items: int | None

    @property
    def encapsulated(self) -> bool:
        return self.items is not None


def pixel_data_layout(path: Path, element_offset: int) -> PixelDataLayout | None:
    """Locate the PixelData value that starts at ``element_offset``, reading O(items) bytes.

    ``element_offset`` is where a ``stop_before_pixels`` parse left the file. ``None`` when
    there is no PixelData element there, the encoding is not one this walker understands
    (big endian), or the element does not fit in the file — callers then fall back to a
    pydicom parse.
    """
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            fh.seek(element_offset)
            header = fh.read(12)
            if len(header) < 8 or header[:4] != _PIXEL_DATA_TAG:
                return None
            if header[4:6] in _EXPLICIT_LONG_VRS:
                if len(header) < 12:
                    return None
                length = struct.unpack_from("<I", header, 8)[0]
                start = element_offset + 12
            else:
                length = struct.unpack_from("<I", header, 4)[0]
                start = element_offset + 8
            if length != _UNDEFINED_LENGTH:
                return PixelDataLayout(start, length, None) if start + length <= size else None
            return _walk_items(fh, start, size)
    except OSError:
        return None


def _walk_items(stream: BinaryIO, start: int, size: int) -> PixelDataLayout | None:
    """Count the items of encapsulated pixel data by seeking over their values."""
    offset = start
    items = 0
    while offset + 8 <= size:
        stream.seek(offset)
        group, element, length = struct.unpack("<HHI", stream.read(8))
        if (group, element) == _SEQUENCE_DELIMITER:
            return PixelDataLayout(start, offset - start, items)
        if (group, element) != _ITEM or length == _UNDEFINED_LENGTH or offset + 8 + length > size:
            return None
        items += 1
        offset += 8 + length
    return None


def read_value(path: Path, layout: PixelDataLayout) -> bytes | None:
    """Read exactly the PixelData value — not the whole file."""
    try:
        with path.open("rb") as fh:
            fh.seek(layout.start)
            value = fh.read(layout.length)
    except OSError:
        return None
    return value if len(value) == layout.length else None
