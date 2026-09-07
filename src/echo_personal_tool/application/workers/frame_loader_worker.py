"""Background worker for loading frames from disk (single or batch)."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from echo_personal_tool.application.decode_gate import DecodeGate, DecodePriority
from echo_personal_tool.infrastructure.dicom_session import get_thread_dicom_session
from echo_personal_tool.infrastructure.image_reader import ImageReader
from echo_personal_tool.infrastructure.video_reader import get_thread_video_reader

logger = logging.getLogger(__name__)

_FREEZE_DIAG = os.environ.get("ECHO_FREEZE_DIAG", "0") == "1"
_diag_log = logging.getLogger("echo_freeze_diag")

# ── Playback diagnostics (set ECHO_PLAYBACK_DIAG=1 to enable) ────────
try:
    from echo_personal_tool.infrastructure.playback_diagnostics import diagnostics as _playback_diag
except ImportError:
    _playback_diag = None  # type: ignore[assignment]


# Files the decode gate serialises. DICOM and still images are random-access: one frame
# costs the same wherever it sits, so a single decoder per file plus priority hand-off is
# a pure win (720p scroll: RGB 6.6 -> 3.3 ms, JPEG 16.6 -> 7.7 ms).
# Video containers are seek-bound instead - interleaving an interactive target into a
# sequential batch makes both sides re-seek, which measured *slower* than letting the pool
# run them concurrently (MJPEG 720p MP4 scroll: 44.5 ms gated vs 37.1 ms ungated), so mp4
# keeps going straight to the pool.
GATED_MEDIA_FORMATS = frozenset({"dicom", "jpeg", "png"})


class FrameLoaderSignals(QObject):
    finished = Signal(np.ndarray)
    batch_finished = Signal(list)
    # (frame count, decode milliseconds) measured inside the worker: the controller sizes
    # prefetch batches from real decode cost, not from round-trip latency that also
    # contains pool queueing and event-loop delay.
    batch_decoded = Signal(int, float)
    failed = Signal(str)
    # Emitted when a parked request is superseded by a newer interactive one and never
    # decoded (see decode_gate.DecodeGate). No pixels and no error - just bookkeeping.
    cancelled = Signal()


class FrameLoaderWorker(QRunnable):
    """Load frames from DICOM, MP4, JPEG, or PNG on a worker thread.

    Single mode: decode one frame, emit ``finished``.
    Batch mode (batch_size > 0): decode consecutive frames starting at
    ``frame_index``, emit ``batch_finished`` with ``[(idx, pixels), ...]``.
    """

    def __init__(
        self,
        path: Path,
        frame_index: int = 0,
        media_format: str = "dicom",
        parent: QObject | None = None,
        total_frames: int = 0,
        batch_size: int = 0,
    ) -> None:
        super().__init__()
        self._path = Path(path)
        self._frame_index = frame_index
        self._media_format = media_format
        self._total_frames = total_frames
        self._batch_size = batch_size
        self.signals = FrameLoaderSignals()
        self.setAutoDelete(False)
        # Assigned by AppController._start_frame_loader(). Left as None the worker decodes
        # immediately, which keeps standalone construction (tests, one-off scripts) working.
        self.decode_gate: DecodeGate | None = None
        self.priority: DecodePriority = DecodePriority.PLAYBACK

    @property
    def decode_path(self) -> Path:
        """File this worker decodes - the gate's single-flight key."""
        return self._path

    def cancel_parked(self) -> None:
        """Report that this request was superseded before it ever decoded."""
        try:
            self.signals.cancelled.emit()
        except RuntimeError:
            # Receiver already deleted - nothing to release.
            pass

    @Slot()
    def run(self) -> None:
        gate = self.decode_gate if self._media_format in GATED_MEDIA_FORMATS else None
        if gate is None:
            self._decode_request()
            return
        if not gate.enter(self):
            # Another worker already owns this file: we are parked and will be adopted by
            # it, which emits our signals from that thread (all receivers are queued).
            return
        current: FrameLoaderWorker = self
        try:
            while True:
                current._decode_request()
                nxt = gate.next_parked(current)
                if nxt is None:
                    break
                current = nxt
        finally:
            # Defensive: never leave a parked request unserved if the loop broke early.
            for orphan in gate.release(current):
                orphan._decode_request()

    def _decode_request(self) -> None:
        _t0 = time.perf_counter() if _FREEZE_DIAG else 0
        try:
            if self._batch_size > 0 and self._media_format in ("dicom", "mp4"):
                self._run_batch()
            else:
                self._run_single()
        except RuntimeError:
            # Signal receiver deleted during background work — safe to ignore.
            pass
        except Exception as exc:  # noqa: BLE001
            logger.exception("FrameLoader failed for %s", self._path)
            try:
                self.signals.failed.emit(str(exc))
            except RuntimeError:
                pass
        if _FREEZE_DIAG:
            _diag_log.warning(
                "[loader] fmt=%s start=%d size=%d elapsed=%.1fms",
                self._media_format,
                self._frame_index,
                self._batch_size or 1,
                (time.perf_counter() - _t0) * 1000,
            )

    def _drain_higher_priority(self) -> None:
        """Decode parked requests that outrank this one (called between batch frames).

        Without it a prefetch batch would hold the file for its whole length and an
        interactive scroll target would wait longer than the per-frame session lock ever
        made it wait. Ungated formats (mp4) skip it: they never own the file, and probing
        the gate between frames disturbed the read order enough to cost tens of ms per
        batch on seek-bound video.
        """
        gate = self.decode_gate
        if gate is None or self._media_format not in GATED_MEDIA_FORMATS:
            return
        while True:
            urgent = gate.steal(self)
            if urgent is None:
                return
            urgent._decode_request()

    def _run_single(self) -> None:
        _t0 = time.perf_counter()
        if self._media_format == "mp4":
            reader = get_thread_video_reader(self._path)
            reader.open(self._path)
            pixels = reader.read_frame(self._frame_index)
        elif self._media_format in ("jpeg", "png"):
            pixels = ImageReader().read_pixels(self._path)
        else:
            session = get_thread_dicom_session(self._path)
            session.open(self._path)
            pixels = session.decode_single_frame(self._frame_index)
            # No release_heavy() here: the session is shared per file and must stay warm.
            # Dropping the pixel buffers after every call made each decode re-read the whole
            # file (184-219 ms per batch at 1280x720). open() releases the buffers of the
            # *other* cached sessions when the user switches to a different file.
        _elapsed_ms = (time.perf_counter() - _t0) * 1000.0
        # ── Playback diagnostics: single decode ──
        if _playback_diag is not None:
            _playback_diag.on_decode_batch(self._frame_index, 1, _elapsed_ms)
        try:
            self.signals.finished.emit(pixels)
        except RuntimeError:
            pass

    def _run_batch(self) -> None:
        end = min(self._frame_index + self._batch_size, self._total_frames)
        results: list[tuple[int, np.ndarray]] = []
        _batch_t0 = time.perf_counter()

        if self._media_format == "mp4":
            reader = get_thread_video_reader(self._path)
            reader.open(self._path)
            for i in range(self._frame_index, end):
                pixels = reader.read_frame(i)
                results.append((i, pixels))
                self._drain_higher_priority()
        elif self._media_format == "dicom":
            # Sequential decode on the shared per-file session (kept warm between batches).
            session = get_thread_dicom_session(self._path)
            session.open(self._path)
            actual_count = session.frame_count
            end = min(end, actual_count)
            for i in range(self._frame_index, end):
                pixels = session.decode_single_frame(i)
                results.append((i, pixels))
                self._drain_higher_priority()

        _batch_elapsed_ms = (time.perf_counter() - _batch_t0) * 1000.0
        # ── Playback diagnostics: decode batch ──
        if _playback_diag is not None:
            _playback_diag.on_decode_batch(self._frame_index, len(results), _batch_elapsed_ms)

        try:
            self.signals.batch_decoded.emit(len(results), _batch_elapsed_ms)
        except RuntimeError:
            pass
        try:
            self.signals.batch_finished.emit(results)
        except RuntimeError:
            pass
