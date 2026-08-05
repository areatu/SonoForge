"""Thread-local DICOM session: read bytes once, decode frames lazily/parallel."""

from __future__ import annotations

import atexit
import logging
import struct
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from pathlib import Path

import cv2
import numpy as np
import pydicom
from pydicom.encaps import generate_frames, parse_basic_offsets

logger = logging.getLogger(__name__)

_thread_local = threading.local()
_all_sessions: list[DicomSession] = []
_cleanup_registered = False


def _cleanup_all_sessions() -> None:
    for session in _all_sessions:
        try:
            session.release()
        except Exception:
            pass
    _all_sessions.clear()


_UNCOMPRESSED_SYNTAXES = frozenset(
    {
        "1.2.840.10008.1.2",
        "1.2.840.10008.1.2.1",
        "1.2.840.10008.1.2.2",
    }
)

_JPEG2000_SYNTAXES = frozenset(
    {
        "1.2.840.10008.1.2.4.90",
        "1.2.840.10008.1.2.4.91",
        "1.2.840.10008.1.2.4.92",
        "1.2.840.10008.1.2.4.93",
    }
)

_MAX_DECODE_WORKERS = 4
_PIXEL_DATA_TAG = struct.pack("<HH", 0x7FE0, 0x0010)


def get_thread_dicom_session() -> DicomSession:
    global _cleanup_registered
    session = getattr(_thread_local, "dicom_session", None)
    if session is None:
        session = DicomSession()
        _thread_local.dicom_session = session
        _all_sessions.append(session)
        if not _cleanup_registered:
            atexit.register(_cleanup_all_sessions)
            _cleanup_registered = True
    return session


def read_ecg_waveform(path: Path | str):
    """Return the ECG waveform stored in a DICOM file (None when absent)."""
    session = get_thread_dicom_session()
    session.open(path)
    return session.waveform


def release_stale_sessions(exclude: DicomSession | None = None) -> None:
    """Free heavy buffers from ALL thread-local sessions except *exclude*.

    After _ensure_pixel_data() runs, _raw_bytes is set to None but
    _pixel_data_raw (19 MiB) and _encapsulated_frames remain.  The old
    check ``s._raw_bytes is not None`` skipped these sessions, so heavy
    buffers were NEVER freed → unbounded growth to 8+ GiB.
    """
    alive: list[DicomSession] = []
    for s in _all_sessions:
        if s is not exclude:
            s.release_heavy()
        else:
            alive.append(s)
    _all_sessions.clear()
    _all_sessions.extend(alive)


def _extract_pixel_data_from_bytes(raw: bytes) -> bytes | None:
    """Scan raw DICOM bytes for PixelData tag and extract its value. No pydicom parse."""
    pos = 132  # skip 128-byte preamble + "DICM"
    while pos + 8 <= len(raw):
        tag = raw[pos : pos + 4]
        if tag == _PIXEL_DATA_TAG:
            vr_bytes = raw[pos + 4 : pos + 6]
            try:
                vr = vr_bytes.decode("ascii")
                is_explicit = all(c.isalpha() for c in vr) and vr in (
                    "OB",
                    "OW",
                    "OF",
                    "SQ",
                    "UC",
                    "UN",
                    "UR",
                    "UT",
                )
            except Exception:
                is_explicit = False

            if is_explicit:
                if vr in ("OB", "OW", "OF", "SQ", "UC", "UN", "UR", "UT"):
                    length = struct.unpack_from("<I", raw, pos + 8)[0]
                    data_start = pos + 12
                else:
                    length = struct.unpack_from("<H", raw, pos + 6)[0]
                    data_start = pos + 8
            else:
                length = struct.unpack_from("<I", raw, pos + 4)[0]
                data_start = pos + 8
            return raw[data_start : data_start + length]

        group = struct.unpack_from("<H", raw, pos)[0]
        vr_bytes = raw[pos + 4 : pos + 6]
        try:
            vr = vr_bytes.decode("ascii")
            is_explicit = all(c.isalpha() for c in vr)
        except Exception:
            is_explicit = False

        if is_explicit and group != 0x7FE0:
            if vr in ("OB", "OW", "OF", "SQ", "UC", "UN", "UR", "UT"):
                length = struct.unpack_from("<I", raw, pos + 8)[0]
                data_start = pos + 12
            else:
                length = struct.unpack_from("<H", raw, pos + 6)[0]
                data_start = pos + 8
        else:
            length = struct.unpack_from("<I", raw, pos + 4)[0]
            data_start = pos + 8

        if length in (0xFFFFFFFF, 0x7FFFFFFF):
            break
        if length < 0 or length > len(raw):
            break
        pos = data_start + length
    return None


def _extended_offsets_from_metadata(
    metadata: pydicom.Dataset,
) -> tuple[bytes, bytes] | None:
    eot = getattr(metadata, "ExtendedOffsetTable", None)
    eot_lengths = getattr(metadata, "ExtendedOffsetTableLengths", None)
    if eot is None or eot_lengths is None:
        return None
    return bytes(eot), bytes(eot_lengths)


def _build_encapsulated_frame_index(
    pixel_data: bytes,
    *,
    frame_count: int,
    extended_offsets: tuple[bytes, bytes] | None = None,
) -> tuple[list[bytes], list[int] | None]:
    """Parse BOT/EOT and build per-frame compressed byte blobs via pydicom.encaps."""
    kwargs: dict = {"number_of_frames": frame_count}
    if extended_offsets is not None:
        kwargs["extended_offsets"] = extended_offsets
    frames = list(generate_frames(pixel_data, **kwargs))
    if not frames:
        raise ValueError("Encapsulated pixel data contains no frames")
    if len(frames) != frame_count:
        logger.warning(
            "Encapsulated frame count mismatch: expected %s, got %s",
            frame_count,
            len(frames),
        )
    bot_offsets: list[int] | None
    try:
        bot_offsets = parse_basic_offsets(pixel_data)
        if not bot_offsets:
            bot_offsets = None
    except Exception:
        bot_offsets = None
    return frames, bot_offsets


def _decode_fragment_openjpeg(
    fragment: bytes,
    rows: int,
    cols: int,
) -> np.ndarray | None:
    """Decode a JPEG-2000 codestream with pylibjpeg-openjpeg."""
    try:
        import openjpeg

        img = openjpeg.decode(fragment)
        if img is None:
            return None
        if img.ndim == 3:
            if img.shape[2] == 4:
                img = img[..., :3]
            if img.shape[2] == 1:
                img = img[..., 0]
        if img.shape[:2] != (rows, cols):
            return None
        return np.ascontiguousarray(img)
    except Exception:
        return None


def _decode_compressed_frame(
    fragment: bytes,
    rows: int,
    cols: int,
    transfer_syntax_uid: str,
) -> np.ndarray | None:
    if transfer_syntax_uid in _JPEG2000_SYNTAXES:
        decoded = _decode_fragment_openjpeg(fragment, rows, cols)
        if decoded is not None:
            return decoded
    decoded = _decode_fragment_cv2(fragment, rows, cols)
    if decoded is not None:
        return decoded
    if transfer_syntax_uid not in _JPEG2000_SYNTAXES:
        return _decode_fragment_openjpeg(fragment, rows, cols)
    return None


def _decode_fragment_cv2(fragment: bytes, rows: int, cols: int) -> np.ndarray | None:
    """Try to decode a compressed fragment with cv2.imdecode."""
    try:
        buf = np.frombuffer(fragment, dtype=np.uint8)
        img = cv2.imdecode(buf, cv2.IMREAD_UNCHANGED)
        if img is None:
            return None
        if img.ndim == 3:
            if img.shape[2] == 4:
                img = img[..., :3]
            if img.shape[2] == 1:
                img = img[..., 0]
            # OpenCV returns BGR, convert to RGB for DICOM color Doppler
            if img.ndim == 3 and img.shape[2] == 3:
                img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        if img.shape[:2] != (rows, cols):
            return None
        return np.ascontiguousarray(img)
    except Exception:
        return None


def _decode_uncompressed_frame(
    pixel_data: bytes, offset: int, size: int, rows: int, cols: int, bytes_per_pixel: int
) -> np.ndarray:
    """Decode single uncompressed frame. Returns OWNED WRITABLE array.
    This is the ONLY copy for single-frame path."""
    raw = pixel_data[offset : offset + size]
    if bytes_per_pixel == 1:
        return np.frombuffer(raw, dtype=np.uint8).reshape(rows, cols).copy()
    if bytes_per_pixel == 2:
        return np.frombuffer(raw, dtype=np.uint16).reshape(rows, cols).copy()
    return np.frombuffer(raw, dtype=np.uint8).reshape(rows, cols, bytes_per_pixel).copy()


class DicomSession:
    def __init__(self) -> None:
        self._open_path: Path | None = None
        self._raw_bytes: bytes | None = None
        self._metadata: pydicom.Dataset | None = None
        self._frame_count: int = 0
        self._frames: np.ndarray | None = None
        self._is_uncompressed: bool = True
        self._frame_slices: list[tuple[int, int]] | None = None
        self._pixel_data_raw: bytes | None = None
        self._encapsulated_frames: list[bytes] | None = None
        self._bot_offsets: list[int] | None = None
        self._extended_offsets: tuple[bytes, bytes] | None = None
        self._transfer_syntax_uid: str = "1.2.840.10008.1.2.1"
        self._first_frame: np.ndarray | None = None

    @property
    def frame_count(self) -> int:
        if self._frames is not None:
            return int(self._frames.shape[0])
        return self._frame_count

    @property
    def is_decoded(self) -> bool:
        return self._frames is not None and self._frames.shape[0] == self._frame_count

    def _has_loadable_pixels(self) -> bool:
        """Return True if heavy pixel bytes are still held for the open file."""
        if self._raw_bytes is not None or self._pixel_data_raw is not None:
            return True
        if self._encapsulated_frames is not None:
            return True
        return False

    def open(self, path: Path | str) -> None:
        resolved = Path(path).resolve()
        if self._open_path == resolved and self._metadata is not None:
            # Reopening the SAME file. If a previous release_heavy() freed the
            # heavy pixel buffers on this thread-local session, we MUST reload
            # raw bytes, otherwise _decode_single_frame() would later hit
            # _pixel_data_raw=None → TypeError.  Only early-return when the
            # decode buffers are still alive.
            if self._has_loadable_pixels():
                return
        else:
            # When switching to a different file, release heavy buffers in ALL
            # other thread-local sessions.  This is now safe because
            # release_stale_sessions() no longer checks _raw_bytes — it frees
            # _pixel_data_raw and _encapsulated_frames too.
            release_stale_sessions(exclude=self)
        self.release()
        if not resolved.is_file():
            raise FileNotFoundError(f"DICOM file not found: {resolved}")
        self._open_path = resolved
        self._raw_bytes = resolved.read_bytes()
        self._metadata = pydicom.dcmread(BytesIO(self._raw_bytes), stop_before_pixels=True, force=True)
        self._frame_count = int(getattr(self._metadata, "NumberOfFrames", 1))
        tsuid = str(getattr(self._metadata.file_meta, "TransferSyntaxUID", "1.2.840.10008.1.2.1"))
        self._transfer_syntax_uid = tsuid
        self._extended_offsets = _extended_offsets_from_metadata(self._metadata)
        self._is_uncompressed = tsuid in _UNCOMPRESSED_SYNTAXES
        if self._is_uncompressed:
            self._compute_frame_slices()

    def _compute_frame_slices(self) -> None:
        ds = self._metadata
        rows = getattr(ds, "Rows", None)
        cols = getattr(ds, "Columns", None)
        if rows is None or cols is None:
            # Missing pixel geometry — cannot compute slices, fall back to pydicom decode
            self._is_uncompressed = False
            return
        rows, cols = int(rows), int(cols)
        samples = int(getattr(ds, "SamplesPerPixel", 1))
        bytes_per_pixel = (int(getattr(ds, "BitsAllocated", 8)) // 8) * samples
        frame_size = rows * cols * bytes_per_pixel
        self._frame_slices = [(i * frame_size, frame_size) for i in range(self._frame_count)]

    def annotations(self) -> tuple:
        """Extract calipers and contours from DICOM Graphic Annotation."""
        if self._metadata is None:
            return ([], [])
        return read_annotations_from_dicom(self._metadata)

    @property
    def waveform(self):
        """Extract ECG waveform from DICOM WaveformSequence (lazy)."""
        from echo_personal_tool.infrastructure.dicom_waveform_parser import (
            parse_waveform_from_dicom,
        )

        if self._metadata is None:
            return None
        return parse_waveform_from_dicom(self._metadata)

    def _ensure_pixel_data(self) -> None:
        """Load raw pixel data bytes, avoiding a second pydicom parse when possible."""
        if self._pixel_data_raw is not None:
            return
        if self._raw_bytes is None:
            return

        extracted = _extract_pixel_data_from_bytes(self._raw_bytes)
        if extracted is not None:
            self._pixel_data_raw = extracted
        else:
            full_ds = pydicom.dcmread(BytesIO(self._raw_bytes), force=True)
            # Ensure file_meta exists with Transfer Syntax UID
            if not hasattr(full_ds, "file_meta") or full_ds.file_meta is None:
                from pydicom.dataset import FileMetaDataset

                full_ds.file_meta = FileMetaDataset()
            if not hasattr(full_ds.file_meta, "TransferSyntaxUID") or full_ds.file_meta.TransferSyntaxUID is None:
                from pydicom.uid import ImplicitVRLittleEndian

                full_ds.file_meta.TransferSyntaxUID = ImplicitVRLittleEndian

            # SAFE EXTRACTION: Check for any type of PixelData
            if hasattr(full_ds, "PixelData"):
                self._pixel_data_raw = bytes(full_ds.PixelData)
            elif hasattr(full_ds, "FloatPixelData"):
                self._pixel_data_raw = bytes(full_ds.FloatPixelData)
            elif hasattr(full_ds, "DoubleFloatPixelData"):
                self._pixel_data_raw = bytes(full_ds.DoubleFloatPixelData)
            else:
                # File has no pixels (e.g., SR or PR). Mark as empty bytes
                # to avoid repeated parsing.
                self._pixel_data_raw = b""

        # _pixel_data_raw is a bytes COPY — free the full file (20-200 MB).
        self._raw_bytes = None
        if not self._is_uncompressed:
            self._encapsulated_frames, self._bot_offsets = _build_encapsulated_frame_index(
                self._pixel_data_raw,
                frame_count=self._frame_count,
                extended_offsets=self._extended_offsets,
            )

    def _encapsulated_frame_bytes(self, index: int) -> bytes | None:
        if self._encapsulated_frames is None:
            return None
        if index < 0 or index >= len(self._encapsulated_frames):
            return None
        return self._encapsulated_frames[index]

    def decode_first_frame(self) -> np.ndarray:
        """Decode only the first frame for fast initial display."""
        if self._open_path is None:
            raise RuntimeError("DICOM is not open; call open() first")
        self._ensure_pixel_data()
        frame = self._decode_single_frame(0)
        self._first_frame = np.ascontiguousarray(frame)
        return self._first_frame

    def decode_all_frames(self) -> np.ndarray:
        """Decode all frames, returning the full (N,H,W) or (N,H,W,C) array."""
        if self._open_path is None:
            raise RuntimeError("DICOM is not open; call open() first")
        if self._frames is not None and self._frames.shape[0] == self._frame_count:
            return self._frames

        self._ensure_pixel_data()

        # FAST PATH: uncompressed → direct 3D view into _pixel_data_raw (zero-copy)
        if self._is_uncompressed and self._pixel_data_raw is not None and self._frame_slices:
            ds = self._metadata
            rows, cols = int(ds.Rows), int(ds.Columns)
            samples = int(getattr(ds, "SamplesPerPixel", 1))
            bits_allocated = int(ds.BitsAllocated)
            bpp = (bits_allocated // 8) * samples
            expected = self._frame_count * rows * cols * bpp
            if len(self._pixel_data_raw) >= expected:
                # dtype based on BitsAllocated, not bpp
                dtype = np.dtype(f"uint{bits_allocated}")
                element_size = np.dtype(dtype).itemsize
                count_elements = expected // element_size
                buf = np.frombuffer(self._pixel_data_raw, dtype=dtype, count=count_elements)
                if samples == 1:
                    self._frames = buf.reshape((self._frame_count, rows, cols))
                else:
                    self._frames = buf.reshape((self._frame_count, rows, cols, samples))

                # SPEC-001 ENFORCEMENT: Mark as read-only to prevent downstream mutations
                self._frames.flags.writeable = False
                self._first_frame = self._frames[0]
                return self._frames

        # SLOW PATH: compressed (JPEG-2000) — parallel decode
        first_frame = getattr(self, "_first_frame", None)
        if first_frame is None:
            first_frame = self._decode_single_frame(0)
        self._frames = np.empty((self._frame_count,) + first_frame.shape, dtype=first_frame.dtype)
        self._frames[0] = first_frame

        remaining = list(range(1, self._frame_count))
        if not remaining:
            return self._frames

        max_workers = min(len(remaining), _MAX_DECODE_WORKERS)
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(self._decode_single_frame, i): i for i in remaining}
            for future in as_completed(futures):
                idx = futures[future]
                self._frames[idx] = future.result()

        return self._frames

    def _decode_single_frame(self, index: int) -> np.ndarray:
        ds = self._metadata
        if index < 0 or index >= self._frame_count:
            raise IndexError(f"Frame index {index} out of range [0, {self._frame_count})")
        rows, cols = int(ds.Rows), int(ds.Columns)

        if self._is_uncompressed and self._frame_slices is not None and self._pixel_data_raw is not None:
            samples = int(getattr(ds, "SamplesPerPixel", 1))
            bytes_per_pixel = (int(ds.BitsAllocated) // 8) * samples
            offset, size = self._frame_slices[index]
            return _decode_uncompressed_frame(self._pixel_data_raw, offset, size, rows, cols, bytes_per_pixel)

        compressed = self._encapsulated_frame_bytes(index)
        if compressed is not None:
            decoded = _decode_compressed_frame(
                compressed,
                rows,
                cols,
                self._transfer_syntax_uid,
            )
            if decoded is not None:
                return decoded

        return self._decode_pydicom_fallback(index)

    def _decode_pydicom_fallback(self, index: int) -> np.ndarray:
        """Fallback: full pydicom decode, extract frame index."""
        # _ensure_pixel_data() frees _raw_bytes after extracting pixel bytes.
        # If a compressed frame cannot be fast-decoded we still need the full
        # file here, so reload it from disk (cached until release_heavy()).
        if self._raw_bytes is None:
            if self._open_path is not None and Path(self._open_path).is_file():
                self._raw_bytes = Path(self._open_path).read_bytes()
            else:
                raise ValueError(
                    "Cannot decode fallback: raw bytes are not available. "
                    "The file may have no pixel data or heavy buffers were released."
                )

        full_ds = pydicom.dcmread(BytesIO(self._raw_bytes), force=True)
        # Ensure file_meta exists with Transfer Syntax UID
        if not hasattr(full_ds, "file_meta") or full_ds.file_meta is None:
            from pydicom.dataset import FileMetaDataset

            full_ds.file_meta = FileMetaDataset()
        if not hasattr(full_ds.file_meta, "TransferSyntaxUID") or full_ds.file_meta.TransferSyntaxUID is None:
            from pydicom.uid import ImplicitVRLittleEndian

            full_ds.file_meta.TransferSyntaxUID = ImplicitVRLittleEndian

        # PROTECTION 2: Explicit check for pixel data
        has_pixel_data = (
            hasattr(full_ds, "PixelData")
            or hasattr(full_ds, "FloatPixelData")
            or hasattr(full_ds, "DoubleFloatPixelData")
        )
        if not has_pixel_data:
            raise ValueError(
                "DICOM file has no pixel data to decode. "
                "It may be a non-image DICOM (e.g., Structured Report, Presentation State)."
            )

        pixel_array = full_ds.pixel_array
        frames = stack_pixel_array(pixel_array)
        return np.ascontiguousarray(frames[index])

    def decode_single_frame(self, index: int) -> np.ndarray:
        """Decode a single frame on demand without decoding all frames."""
        if self._open_path is None:
            raise RuntimeError("DICOM is not open; call open() first")
        self._ensure_pixel_data()
        return self._decode_single_frame(index)

    def read_frame(self, frame_index: int) -> np.ndarray:
        """Return frame array. MAY BE READ-ONLY. Caller MUST NOT modify in-place.
        Decoder already guarantees owned contiguous memory for single frames,
        or read-only view for bulk decode_all_frames()."""
        if self._frames is not None:
            if frame_index < 0 or frame_index >= self._frames.shape[0]:
                raise IndexError(f"Frame index {frame_index} out of range [0, {self._frames.shape[0]})")
            return self._frames[frame_index]  # Zero-copy view (read-only if bulk)

        if frame_index < 0 or frame_index >= self._frame_count:
            raise IndexError(f"Frame index {frame_index} out of range [0, {self._frame_count})")
        self._ensure_pixel_data()
        return self._decode_single_frame(frame_index)  # Writable owned copy

    def release(self) -> None:
        self._open_path = None
        self._raw_bytes = None
        self._metadata = None
        self._frame_count = 0
        self._frames = None
        self._frame_slices = None
        self._pixel_data_raw = None
        self._encapsulated_frames = None
        self._bot_offsets = None
        self._extended_offsets = None
        self._transfer_syntax_uid = "1.2.840.10008.1.2.1"
        self._first_frame = None

    def release_heavy(self) -> None:
        """Free large buffers while keeping metadata for future re-open."""
        # MATERIALIZE VIEWS: If _frames is a read-only view into _pixel_data_raw,
        # copy it to detach from _pixel_data_raw before clearing.
        if self._frames is not None and self._frames.base is not None:
            self._frames = self._frames.copy()  # Now it's a writable owned array
            self._first_frame = self._frames[0]

        self._raw_bytes = None
        self._pixel_data_raw = None
        self._encapsulated_frames = None
        self._bot_offsets = None


def stack_pixel_array(pixel_array: np.ndarray) -> np.ndarray:
    """Normalize pydicom pixel_array to shape (N,H,W) or (N,H,W,C)."""
    arr = np.asarray(pixel_array)
    if arr.ndim == 2:
        return np.ascontiguousarray(arr[np.newaxis, ...])
    if arr.ndim == 3:
        if arr.shape[-1] in (3, 4):
            frames = arr[np.newaxis, ...]
        else:
            frames = arr
    elif arr.ndim == 4:
        frames = arr
    else:
        raise ValueError(f"Unsupported pixel_array ndim: {arr.ndim}")

    if frames.ndim == 4 and frames.shape[-1] == 4:
        frames = frames[..., :3]
    if frames.ndim == 4 and frames.shape[-1] not in (3,):
        raise ValueError(f"Expected color channels last in {frames.shape}")
    if frames.ndim not in (3, 4):
        raise ValueError(f"Expected (N,H,W) or (N,H,W,C) after normalization, got {frames.shape}")
    return np.ascontiguousarray(frames)
