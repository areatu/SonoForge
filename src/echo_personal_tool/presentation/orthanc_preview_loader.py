"""Background preview thumbnails for the server study browser.

The study/series lists are far easier to scan with a rendered frame next to
each row, but a preview costs at least one HTTP round trip per row.  This module
keeps the dialog responsive:

* requests are served from an in-memory LRU cache first;
* at most ``max_in_flight`` requests run at once on the global thread pool, the
  rest wait in a strict FIFO queue (visible rows are requested first);
* every failure degrades to "no preview" instead of an error;
* a thumbnail whose first frame is blank (common for sweeps and contrast loops)
  is fetched again from the middle of the loop — but only when the first attempt
  actually looks blank, so the extra request is the exception, not the rule;
* previews are never written to disk — they live only while the dialog is open,
  so no extra PHI store appears on the workstation.

Results cross the thread boundary through :class:`_PreviewInbox`, not through a
queued Qt signal to a Python callable.  A queued signal leaves a meta-call event
in the GUI thread queue; if the loader is torn down before that event is
delivered, PySide6 walks the connection of a freed receiver and the process dies
with SIGSEGV (this is what made the preview-loader tests flaky, and it is not
specific to the tests — closing the dialog while thumbnails were still loading
did the same).  A locked container has no lifetime coupling to Qt; the loader
drains it on its own timer, and the timer dies with the loader, so no event can
ever outlive its receiver.
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict, deque

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap

log = logging.getLogger(__name__)

#: Rendered previews per dialog instance (≈ 0.5 МБ each at 160×120).
_DEFAULT_CACHE_LIMIT = 320
_DEFAULT_MAX_IN_FLIGHT = 3

#: Size of the probe used by :func:`is_informative_image`.
_PROBE_SIZE = (32, 24)
#: Mean luminance below which a probe counts as "blank".
_BLANK_MEAN = 6.0
#: Dynamic range below which a probe counts as "flat" (no structure at all).
_FLAT_RANGE = 4.0


def is_informative_image(image: QImage) -> bool:
    """True when a thumbnail shows *something* (cheap 32×24 luminance probe).

    Frames stored at the start of an echocardiographic loop are frequently
    blank.  Such a thumbnail is worse than none: the list looks like it has no
    previews.  Detecting it lets the loader ask for a frame from the middle of
    the loop instead — the check itself costs microseconds and no I/O.
    """
    if image is None or image.isNull():
        return False
    probe = image.scaled(
        _PROBE_SIZE[0],
        _PROBE_SIZE[1],
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.FastTransformation,
    )
    if probe.format() != QImage.Format.Format_Grayscale8:
        probe = probe.convertToFormat(QImage.Format.Format_Grayscale8)
    raw = bytes(probe.constBits())
    stride = probe.bytesPerLine()
    width = probe.width()
    samples = 0
    total = 0
    low = 255
    high = 0
    for row in range(probe.height()):
        line = raw[row * stride : row * stride + width]
        samples += len(line)
        total += sum(line)
        if line:
            low = min(low, min(line))
            high = max(high, max(line))
    if not samples:
        return True
    mean = total / samples
    return mean >= _BLANK_MEAN and (high - low) >= _FLAT_RANGE


class _PreviewInbox:
    """Thread-safe hand-off of finished previews to the GUI thread.

    Deliberately a plain Python object: both the worker task and the loader hold
    a reference, so the container outlives whichever of them disappears first,
    and nothing here can leave a dangling Qt connection behind (see the module
    docstring).  ``deque`` + ``list()`` under a lock is all the ordering the
    loader needs — FIFO, and draining never blocks the GUI thread for long.
    """

    def __init__(self) -> None:
        self._items: deque[tuple[str, str, object]] = deque()
        self._lock = threading.Lock()

    def add(self, study_uid: str, series_uid: str, image: object) -> None:
        with self._lock:
            self._items.append((study_uid, series_uid, image))

    def drain(self) -> list[tuple[str, str, object]]:
        with self._lock:
            items = list(self._items)
            self._items.clear()
        return items


class _PreviewTask(QRunnable):
    """Fetch + decode one preview off the GUI thread."""

    def __init__(
        self,
        client: object,
        study_uid: str,
        series_uid: str,
        target: QSize,
        inbox: _PreviewInbox,
    ) -> None:
        super().__init__()
        self._client = client
        self._study_uid = study_uid
        self._series_uid = series_uid
        self._target = target
        self._inbox = inbox
        self.setAutoDelete(True)

    def run(self) -> None:
        image: QImage | None = None
        try:
            image = self._fetch(middle_frame=False)
            if image is not None and not is_informative_image(image):
                # Blank first frame (sweeps, contrast injections): pay for one
                # more request and take the middle of the loop when it is better.
                retry = self._fetch(middle_frame=True)
                if retry is not None and is_informative_image(retry):
                    image = retry
        except Exception as exc:  # noqa: BLE001 - a preview must never break the list
            log.debug("[PREVIEW] %s failed: %s", self._series_uid[:16], exc)
        # Never raises, whatever the loader did in the meantime: the inbox is
        # owned by this task too, and nothing is delivered to a dead receiver.
        self._inbox.add(self._study_uid, self._series_uid, image)

    def _fetch(self, *, middle_frame: bool) -> QImage | None:
        """One preview request, decoded (``None`` when unavailable)."""
        fetch = getattr(self._client, "fetch_preview", None)
        if not callable(fetch):
            return None
        args = (self._study_uid, self._series_uid, "")
        kwargs = {"width": self._target.width(), "height": self._target.height()}
        try:
            payload = fetch(*args, middle_frame=middle_frame, **kwargs)
        except TypeError:
            # Client double without the hint — plain preview only.
            if middle_frame:
                return None
            payload = fetch(*args, **kwargs)
        # Mocks and non-Orthanc clients may return a non-bytes sentinel.
        if not isinstance(payload, (bytes, bytearray)) or not payload:
            return None
        image = QImage.fromData(bytes(payload))
        return None if image.isNull() else image


class OrthancPreviewLoader(QObject):
    """Fetch, cache and deliver study/series thumbnails."""

    preview_ready = Signal(str, str)  # study_uid, series_uid

    def __init__(
        self,
        client: object,
        *,
        target_size: QSize | None = None,
        cache_limit: int = _DEFAULT_CACHE_LIMIT,
        max_in_flight: int = _DEFAULT_MAX_IN_FLIGHT,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._target = target_size or QSize(160, 120)
        self._cache_limit = max(8, cache_limit)
        self._max_in_flight = max(1, max_in_flight)
        self._pixmaps: OrderedDict[tuple[str, str], QPixmap] = OrderedDict()
        self._failed: set[tuple[str, str]] = set()
        self._queue: list[tuple[str, str]] = []
        self._in_flight: set[tuple[str, str]] = set()
        self._enabled = True
        self._closed = False
        self._pool = QThreadPool.globalInstance()
        self._inbox = _PreviewInbox()
        # 0 ms: results are picked up on the next event-loop pass, so the dialog
        # never waits for a poll interval.  The timer runs only while requests
        # are in flight and is stopped as soon as the last one is drained.
        self._drain_timer = QTimer(self)
        self._drain_timer.setInterval(0)
        self._drain_timer.timeout.connect(self._drain)

    # ── public API ──────────────────────────────────────────────────

    def set_enabled(self, enabled: bool) -> None:
        """Turn thumbnails off entirely (slow link / privacy preference)."""
        self._enabled = bool(enabled)

    def is_enabled(self) -> bool:
        return self._enabled

    def cached(self, study_uid: str, series_uid: str) -> QPixmap | None:
        pixmap = self._pixmaps.get((study_uid, series_uid))
        if pixmap is not None:
            self._pixmaps.move_to_end((study_uid, series_uid))
        return pixmap

    @property
    def target_size(self) -> QSize:
        return self._target

    def request(self, study_uid: str, series_uid: str) -> QPixmap | None:
        """Return a cached preview or queue a fetch (``None`` while loading)."""
        if not study_uid or not series_uid:
            return None
        key = (study_uid, series_uid)
        cached = self.cached(study_uid, series_uid)
        if cached is not None:
            return cached
        if not self._enabled or self._closed or key in self._failed or key in self._in_flight:
            return None
        if key in self._queue:
            return None
        self._queue.append(key)
        self._pump()
        return None

    def shutdown(self) -> None:
        """Stop delivering results; in-flight requests finish and are dropped."""
        self._closed = True
        self._queue.clear()
        self._drain_timer.stop()

    # ── internals ───────────────────────────────────────────────────

    def _pump(self) -> None:
        while self._queue and len(self._in_flight) < self._max_in_flight:
            study_uid, series_uid = self._queue.pop(0)
            key = (study_uid, series_uid)
            self._in_flight.add(key)
            task = _PreviewTask(self._client, study_uid, series_uid, self._target, self._inbox)
            self._pool.start(task)
        if self._in_flight and not self._closed and not self._drain_timer.isActive():
            self._drain_timer.start()

    def _drain(self) -> None:
        """Deliver everything the workers finished (GUI thread)."""
        for study_uid, series_uid, image in self._inbox.drain():
            self._in_flight.discard((study_uid, series_uid))
            if not self._closed:
                self._deliver(study_uid, series_uid, image)
        if not self._in_flight or self._closed:
            self._drain_timer.stop()
        else:
            self._pump()

    def _deliver(self, study_uid: str, series_uid: str, image: object) -> None:
        key = (study_uid, series_uid)
        if isinstance(image, QImage) and not image.isNull():
            pixmap = QPixmap.fromImage(image)
            if not pixmap.isNull():
                self._pixmaps[key] = pixmap
                while len(self._pixmaps) > self._cache_limit:
                    self._pixmaps.popitem(last=False)
                self.preview_ready.emit(study_uid, series_uid)
        else:
            self._failed.add(key)
