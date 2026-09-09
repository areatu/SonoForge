"""DICOM session cache: read bytes once per file, decode frames lazily/parallel.

Sessions are keyed by resolved file path and shared by the whole process.  They used to be
cached in ``threading.local()``, which silently never worked on the pool threads that
actually decode frames: PySide6 enters a ``QRunnable.run()`` override with
``PyGILState_Ensure`` and leaves it with ``PyGILState_Release``, which destroys the thread
state — and with it every ``threading.local()`` value — for threads not created by the
``threading`` module.  Every pooled call therefore built a brand-new session and re-read the
whole file (measured at 1280×720: 184–219 ms per 2–8 frame batch, of which ~16 ms was real
decoding; 192–638 ms per scrub step; peak RSS ~1 GB for a single 332 MB cine).

A shared session is guarded by a re-entrant lock, so concurrent workers serialise on the
same file instead of each paying for its I/O.  See
``docs/bench/2026-09-06-cine-720p-playback-audit.md`` §3.1.
"""

from __future__ import annotations

import atexit
import functools
import logging
import struct
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from pathlib import Path
from typing import Any, TypeVar, cast

import cv2
import numpy as np
import pydicom
from pydicom.encaps import generate_frames, parse_basic_offsets

from echo_personal_tool.infrastructure.dicom_frame_count import infer_dicom_frame_count

logger = logging.getLogger(__name__)

_thread_local = threading.local()
_session_registry: dict[str, DicomSession] = {}
_registry_lock = threading.RLock()
_all_sessions: list[DicomSession] = []
_sessions_lock = threading.Lock()
_cleanup_registered = False

_F = TypeVar("_F", bound=Callable[..., Any])


def _synchronized(method: _F) -> _F:
    """Serialise calls to a shared session (one instance per file, used from a pool)."""

    @functools.wraps(method)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            return method(self, *args, **kwargs)

    return cast(_F, wrapper)


def _stat_signature(path: Path) -> tuple[int, int] | None:
    """(size, mtime_ns) of *path*, or None when it cannot be stat'ed."""
    try:
        info = path.stat()
    except OSError:
        return None
    return (info.st_size, info.st_mtime_ns)


def _cleanup_all_sessions() -> None:
    """Release all sessions at exit.

    Uses ``_force_release_heavy()`` instead of ``release_heavy()`` to avoid blocking on
    per-session locks that a still-running worker thread may hold.  The
    process is about to die anyway; we just want to drop large buffers.
    """
    with _sessions_lock:
        sessions = list(_all_sessions)
        _all_sessions.clear()
    with _registry_lock:
        _session_registry.clear()
    for session in sessions:
        try:
            session._force_release_heavy()
        except Exception:
            pass


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
# How much of a file is read to *locate* the PixelData element. The value itself is mapped
# rather than read: for an uncompressed cine it is the whole file (332 MB for 120 frames of
# 1280x720 RGB), while its tag sits within the first kilobyte.
_HEADER_SCAN_BYTES = 4 * 1024 * 1024


_max_sessions = 10


def _track_session(session: DicomSession) -> list[DicomSession]:
    """Add *session* to the cleanup list, returning the sessions pruned out of it.

    Pruning happens here (and not while holding ``_sessions_lock``) so that the registry
    lock and the per-session locks are never acquired in a nested, order-inverted way.
    """
    global _cleanup_registered
    pruned: list[DicomSession] = []
    with _sessions_lock:
        _all_sessions.append(session)
        # Prune oldest sessions to prevent unbounded growth.
        while len(_all_sessions) > _max_sessions:
            pruned.append(_all_sessions.pop(0))
        if not _cleanup_registered:
            atexit.register(_cleanup_all_sessions)
            _cleanup_registered = True
    return pruned


def _forget_registry_entry(session: DicomSession) -> None:
    with _registry_lock:
        for key, candidate in list(_session_registry.items()):
            if candidate is session:
                del _session_registry[key]


def _drop_pruned(pruned: list[DicomSession]) -> None:
    for old in pruned:
        _forget_registry_entry(old)
        try:
            old.release()
        except Exception:
            pass


def get_dicom_session(path: Path | str) -> DicomSession:
    """Return the process-wide session cached for *path*, creating it on first use.

    Keying by resolved path (instead of by thread) is what makes "read the file once"
    true for pooled workers — see the module docstring.
    """
    key = str(Path(path).resolve())
    with _registry_lock:
        session = _session_registry.get(key)
        if session is not None:
            return session
        session = DicomSession()
        _session_registry[key] = session
    _drop_pruned(_track_session(session))
    return session


def get_thread_dicom_session(path: Path | str | None = None) -> DicomSession:
    """Return the shared session for *path*, or a thread-local one when *path* is None.

    The path-less form is kept for callers that pick the file later and for tests; pass the
    path whenever it is known so the session cache can do its job.
    """
    if path is not None:
        return get_dicom_session(path)
    session = getattr(_thread_local, "dicom_session", None)
    if session is None:
        session = DicomSession()
        _thread_local.dicom_session = session
        _drop_pruned(_track_session(session))
    return session


def read_ecg_waveform(path: Path | str):
    """Return the ECG waveform stored in a DICOM file (None when absent)."""
    session = get_thread_dicom_session(path)
    session.open(path)
    return session.waveform


def release_stale_sessions(exclude: DicomSession | None = None) -> None:
    """Free heavy buffers from ALL cached sessions except *exclude*.

    After _ensure_pixel_data() runs, _raw_bytes is set to None but
    _pixel_data_raw and _encapsulated_frames remain.  The old check
    ``s._raw_bytes is not None`` skipped these sessions, so heavy buffers were
    NEVER freed → unbounded growth to 8+ GiB.

    Sessions stay registered after being released: they keep their parsed metadata and can
    be re-warmed cheaply.  This function must be called *outside* any per-session
    ``_lock`` — ``DicomSession.open()`` calls it before acquiring its own lock to
    prevent ABBA deadlocks when two threads open different files concurrently.
    """
    with _sessions_lock:
        stale = [s for s in _all_sessions if s is not exclude]
    for session in stale:
        try:
            session.release_heavy()
        except Exception:
            pass


def _scan_pixel_data_span(raw: bytes) -> tuple[int, int] | None:
    """Locate the PixelData value in raw DICOM bytes as (offset, length). No pydicom parse.

    Returns a span instead of the value so callers can map or slice it without copying -
    for an uncompressed cine the value is essentially the whole file. None when the element
    is encapsulated (undefined length) or cannot be parsed.
    """
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
            if length in (0xFFFFFFFF, 0x7FFFFFFF):
                return None  # encapsulated: the caller needs the fragment index anyway
            return (data_start, length)

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


def _extract_pixel_data_from_bytes(raw: bytes) -> bytes | None:
    """Value of the PixelData element as bytes (a copy), or None if it cannot be located."""
    span = _scan_pixel_data_span(raw)
    if span is None:
        return None
    start, length = span
    return raw[start : start + length]


def _pixel_data_span_from_header(path: Path) -> tuple[int, int] | None:
    """(offset, length) of the PixelData value, reading only a header prefix of the file.

    The element length comes from its tag, so the pixels never have to be resident to know
    where they start. None when the tag is not inside the prefix (a large sequence ahead of
    the pixels), the length is undefined, or the element does not fit the file on disk.
    """
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            prefix = fh.read(min(size, _HEADER_SCAN_BYTES))
    except OSError:
        return None
    span = _scan_pixel_data_span(prefix)
    if span is None:
        return None
    start, length = span
    if start + length > size:
        return None
    return (start, length)


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
    try:
        frames = list(generate_frames(pixel_data, **kwargs))
    except (struct.error, ValueError, TypeError) as exc:
        logger.debug("Encapsulated frame index failed (%s), trying raw parse", exc)
        if len(pixel_data) >= 8:
            return [pixel_data], None
        raise ValueError("Pixel data too small for encapsulated frame parsing") from exc
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
    pixel_data: bytes | np.ndarray,
    offset: int,
    size: int,
    rows: int,
    cols: int,
    bytes_per_pixel: int,
) -> np.ndarray:
    """Decode single uncompressed frame. Returns OWNED WRITABLE array.
    This is the ONLY copy for single-frame path.

    ``pixel_data`` is either a bytes object or a read-only memory map of the pixel block;
    for the map the slice is a view, so this copy is the only allocation per frame.
    """
    raw = pixel_data[offset : offset + size]
    if bytes_per_pixel == 1:
        return np.frombuffer(raw, dtype=np.uint8).reshape(rows, cols).copy()
    if bytes_per_pixel == 2:
        return np.frombuffer(raw, dtype=np.uint16).reshape(rows, cols).copy()
    return np.frombuffer(raw, dtype=np.uint8).reshape(rows, cols, bytes_per_pixel).copy()


class DicomSession:
    def __init__(self, *, isolated: bool = False) -> None:
        # Short-lived preview readers own their buffers and never evict shared playback
        # sessions. Their caller releases them in finally; they are not registered.
        self._isolated = isolated
        # Guards every public entry point: a session is shared by all threads that work
        # with the same file, so its buffers must not be swapped underneath a decoder.
        self._lock = threading.RLock()
        self._open_path: Path | None = None
        self._open_stat: tuple[int, int] | None = None
        self._raw_bytes: bytes | None = None
        self._metadata: pydicom.Dataset | None = None
        self._frame_count: int = 0
        self._frames: np.ndarray | None = None
        self._is_uncompressed: bool = True
        self._frame_slices: list[tuple[int, int]] | None = None
        # Pixel block of the open file: a read-only np.memmap for uncompressed cines (no
        # copy in RAM), bytes for encapsulated ones (the fragment index needs real bytes).
        self._pixel_data_raw: bytes | np.ndarray | None = None
        self._encapsulated_frames: list[bytes] | None = None
        self._bot_offsets: list[int] | None = None
        self._extended_offsets: tuple[bytes, bytes] | None = None
        self._transfer_syntax_uid: str = "1.2.840.10008.1.2.1"
        self._first_frame: np.ndarray | None = None

    @property
    @_synchronized
    def frame_count(self) -> int:
        if self._frames is not None:
            return int(self._frames.shape[0])
        return self._frame_count

    @property
    @_synchronized
    def is_decoded(self) -> bool:
        return self._frames is not None and self._frames.shape[0] == self._frame_count

    @_synchronized
    def _has_loadable_pixels(self) -> bool:
        """Return True if heavy pixel bytes are still held for the open file."""
        if self._raw_bytes is not None or self._pixel_data_raw is not None:
            return True
        if self._encapsulated_frames is not None:
            return True
        return False

    def _stat_matches(self, resolved: Path) -> bool:
        """True when the file on disk is still the one this session parsed."""
        if self._open_stat is None:
            return True
        return _stat_signature(resolved) == self._open_stat

    def open(self, path: Path | str) -> None:
        """Open a DICOM file, releasing heavy buffers from other sessions first.

        The public entry point is intentionally NOT ``@_synchronized``: calling
        ``release_stale_sessions()`` while holding ``self._lock`` creates an
        ABBA deadlock when two threads open different files concurrently — each
        holds its own session lock and waits for the other's inside
        ``release_heavy()``.  Splitting the method lets us release stale
        sessions *before* acquiring our lock.
        """
        resolved = Path(path).resolve()
        # Fast path: same file, pixels still loaded → nothing to do.
        # ``_has_loadable_pixels()`` is ``@_synchronized`` so it briefly acquires
        # and releases ``self._lock``; the worst case of reading ``_open_path``
        # without the lock is a redundant ``release_stale_sessions`` call.
        if (
            self._open_path == resolved
            and self._metadata is not None
            and self._has_loadable_pixels()
            and self._stat_matches(resolved)
        ):
            return
        # Release heavy buffers in ALL other cached sessions *outside* our lock
        # so that two concurrent ``open()`` calls cannot deadlock.
        if not self._isolated:
            release_stale_sessions(exclude=self)
        self._open_impl(resolved)

    @_synchronized
    def _open_impl(self, resolved: Path) -> None:
        # Re-check under the lock: another thread may have opened the same file
        # while we were waiting for the lock (or inside release_stale_sessions).
        if self._open_path == resolved and self._metadata is not None and self._stat_matches(resolved):
            if self._has_loadable_pixels():
                return
        self.release()
        if not resolved.is_file():
            raise FileNotFoundError(f"DICOM file not found: {resolved}")
        self._open_path = resolved
        self._open_stat = _stat_signature(resolved)
        # Metadata straight from the file: stop_before_pixels only reads the header, so
        # opening a 332 MB cine no longer means reading 332 MB into RAM.
        self._metadata = pydicom.dcmread(str(resolved), stop_before_pixels=True, force=True)
        self._frame_count = infer_dicom_frame_count(self._metadata)
        if self._frame_count <= 1:
            # Vendors sometimes omit (0028,0008) NumberOfFrames on genuinely
            # multi-frame clips; recover the count from the pixel bytes.
            raw = resolved.read_bytes()
            pixel_data = _extract_pixel_data_from_bytes(raw)
            if not pixel_data:
                # Encapsulated (JPEG/J2K) uses undefined-length pixel data
                # which the simple tag scanner cannot locate.  Fall back to
                # a full pydicom parse for the pixel blob.
                full_ds = pydicom.dcmread(BytesIO(raw), force=True)
                pd_tag = getattr(full_ds, "PixelData", None)
                if pd_tag is not None:
                    pixel_data = bytes(pd_tag)
            if pixel_data:
                self._frame_count = infer_dicom_frame_count(self._metadata, pixel_data=pixel_data)
        tsuid = str(getattr(self._metadata.file_meta, "TransferSyntaxUID", "1.2.840.10008.1.2.1"))
        self._transfer_syntax_uid = tsuid
        self._extended_offsets = _extended_offsets_from_metadata(self._metadata)
        self._is_uncompressed = tsuid in _UNCOMPRESSED_SYNTAXES
        if self._is_uncompressed:
            self._compute_frame_slices()
            if self._map_pixel_data(resolved):
                # Pixels stay on disk, mapped rather than resident: the OS pages in what a
                # decode touches and can drop those clean pages again under pressure. The
                # old path read the whole file and then copied the pixel block out of it,
                # which put a 120-frame 720p cine in RAM twice (peak RSS ~1.0 GB).
                return
        # Encapsulated (compressed) pixel data, or a file that cannot be mapped: fall back
        # to holding the bytes, which the fragment index needs anyway.
        self._raw_bytes = resolved.read_bytes()

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

    @_synchronized
    def annotations(self) -> tuple:
        """Extract calipers and contours from DICOM Graphic Annotation."""
        if self._metadata is None:
            return ([], [])
        return read_annotations_from_dicom(self._metadata)

    @property
    @_synchronized
    def waveform(self):
        """Extract ECG waveform from DICOM WaveformSequence (lazy)."""
        from echo_personal_tool.infrastructure.dicom_waveform_parser import (
            parse_waveform_from_dicom,
        )

        if self._metadata is None:
            return None
        return parse_waveform_from_dicom(self._metadata)

    def _map_pixel_data(self, path: Path) -> bool:
        """Map the uncompressed pixel block instead of copying it into RAM.

        Returns False when the element cannot be located from the header prefix, is shorter
        than the frames need, or the mapping fails (network share, exotic filesystem); the
        caller then falls back to reading the file. The map is released by dropping the
        reference (release_heavy) - never by closing it, because arrays handed to callers
        may still be views into it.
        """
        if not self._is_uncompressed or not self._frame_slices:
            return False
        span = _pixel_data_span_from_header(path)
        if span is None:
            return False
        start, length = span
        if length < self._frame_count * self._frame_slices[0][1]:
            return False
        try:
            mapped = np.memmap(path, dtype=np.uint8, mode="r", offset=start, shape=(length,))
        except (OSError, ValueError) as exc:
            logger.debug("Pixel data mapping failed for %s (%s); reading the file instead", path, exc)
            return False
        self._pixel_data_raw = mapped
        return True

    @_synchronized
    def _ensure_pixel_data(self) -> None:
        """Make the pixel block available, avoiding a second pydicom parse when possible."""
        if self._pixel_data_raw is not None:
            return
        # Uncompressed cines are re-mapped from disk - also after release_heavy(), which is
        # now free of I/O instead of a full-file read.
        if self._is_uncompressed and self._open_path is not None and self._map_pixel_data(self._open_path):
            return
        if self._raw_bytes is None:
            if self._open_path is None:
                raise RuntimeError("DICOM is not open; call open() first")
            # A shared session may have been released between frames of a batch.
            # Rebuild the compressed index instead of falling through to a full decode.
            self._raw_bytes = Path(self._open_path).read_bytes()

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
                raise ValueError(
                    "DICOM file has no pixel data to decode. "
                    "It may be a non-image DICOM (e.g., Structured Report, Presentation State)."
                )

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

    @_synchronized
    def decode_first_frame(self) -> np.ndarray:
        """Decode only the first frame for fast initial display."""
        if self._open_path is None:
            raise RuntimeError("DICOM is not open; call open() first")
        self._ensure_pixel_data()
        frame = self._decode_single_frame(0)
        self._first_frame = np.ascontiguousarray(frame)
        return self._first_frame

    @_synchronized
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
            # pylibjpeg-openjpeg 2.3 holds the GIL for the entire decode. OpenCV
            # releases it. Restrict this route to lossless unsigned monochrome
            # images with a tested output dtype; color/signed/lossy data keep the
            # existing backend to avoid changing medical pixel interpretation.
            if (
                self._transfer_syntax_uid == "1.2.840.10008.1.2.4.90"
                and int(getattr(ds, "SamplesPerPixel", 1)) == 1
                and int(getattr(ds, "PixelRepresentation", 0)) == 0
                and int(ds.BitsAllocated) in (8, 16)
                and str(ds.PhotometricInterpretation) in ("MONOCHROME1", "MONOCHROME2")
            ):
                decoded = _decode_fragment_cv2(compressed, rows, cols)
                if (
                    decoded is not None
                    and decoded.ndim == 2
                    and decoded.dtype == np.dtype(f"uint{int(ds.BitsAllocated)}")
                ):
                    return decoded
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
        """Decode only the requested frame, including syntaxes without a fast path.

        A new Dataset.pixel_array per request used to decode N frames N times on
        bulk/scroll, and returned views pinned the *whole* cine behind each frame.
        pydicom 3's indexed API reads one frame; own it at this boundary as well.
        """
        if self._open_path is None:
            raise RuntimeError("DICOM is not open; call open() first")
        try:
            pixels = pydicom.pixels.pixel_array(str(self._open_path), index=index, number_of_frames=self._frame_count)
        except AttributeError as exc:
            raise ValueError(
                "DICOM file has no pixel data to decode. "
                "It may be a non-image DICOM (e.g., Structured Report, Presentation State)."
            ) from exc
        return np.array(pixels, copy=True, order="C")

    @_synchronized
    def decode_single_frame(self, index: int) -> np.ndarray:
        """Decode a single frame on demand without decoding all frames."""
        if self._open_path is None:
            raise RuntimeError("DICOM is not open; call open() first")
        self._ensure_pixel_data()
        return self._decode_single_frame(index)

    @_synchronized
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

    @_synchronized
    def release(self) -> None:
        self._open_path = None
        self._open_stat = None
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

    @_synchronized
    def release_heavy(self) -> None:
        """Free large buffers while keeping metadata for future re-open.

        Callers keep the reference returned by decode_all_frames(), so dropping
        _frames here is safe — it prevents thread-local sessions from pinning
        the full cine for the life of a pooled thread (was the cause of
        multi-GB growth).  A read-only _frames view keeps its backing buffer
        alive on its own, so no materialize copy is needed.
        """
        self._raw_bytes = None
        self._pixel_data_raw = None
        self._encapsulated_frames = None
        self._bot_offsets = None
        self._frames = None
        self._first_frame = None

    def _force_release_heavy(self) -> None:
        """Drop large buffers without acquiring the lock (atexit cleanup only).

        Called from ``_cleanup_all_sessions`` when the process is about to die.
        Worker threads may still hold ``_lock`` — blocking here would hang the
        interpreter shutdown.  GIL protects against torn pointer writes.
        """
        self._raw_bytes = None
        self._pixel_data_raw = None
        self._encapsulated_frames = None
        self._bot_offsets = None
        self._frames = None
        self._first_frame = None


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
