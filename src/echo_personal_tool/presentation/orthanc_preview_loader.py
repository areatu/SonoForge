"""Background preview thumbnails for the server study browser.

The study/series lists are far easier to scan with a rendered frame next to
each row, but a preview costs at least one HTTP round trip per row.  This module
keeps the dialog responsive:

* requests are served from an in-memory LRU cache first;
* at most ``max_in_flight`` requests run at once on the global thread pool, the
  rest wait in a strict FIFO queue (visible rows are requested first);
* every failure degrades to "no preview" instead of an error;
* previews are never written to disk — they live only while the dialog is open,
  so no extra PHI store appears on the workstation.
"""

from __future__ import annotations

import logging
from collections import OrderedDict

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QImage, QPixmap

log = logging.getLogger(__name__)

#: Rendered previews per dialog instance (≈ 0.5 МБ each at 160×120).
_DEFAULT_CACHE_LIMIT = 320
_DEFAULT_MAX_IN_FLIGHT = 3


class _PreviewSignals(QObject):
    finished = Signal(str, str, object)  # study_uid, series_uid, QImage | None


class _PreviewTask(QRunnable):
    """Fetch + decode one preview off the GUI thread."""

    def __init__(
        self,
        client: object,
        study_uid: str,
        series_uid: str,
        target: QSize,
        signals: _PreviewSignals,
    ) -> None:
        super().__init__()
        self._client = client
        self._study_uid = study_uid
        self._series_uid = series_uid
        self._target = target
        self._signals = signals
        self.setAutoDelete(True)

    def run(self) -> None:
        image: QImage | None = None
        try:
            fetch = getattr(self._client, "fetch_preview", None)
            if callable(fetch):
                payload = fetch(
                    self._study_uid,
                    self._series_uid,
                    "",
                    width=self._target.width(),
                    height=self._target.height(),
                )
                # Mocks and non-Orthanc clients may return a non-bytes sentinel.
                if isinstance(payload, (bytes, bytearray)) and payload:
                    image = QImage.fromData(bytes(payload))
                    if image.isNull():
                        image = None
        except Exception as exc:  # noqa: BLE001 - a preview must never break the list
            log.debug("[PREVIEW] %s failed: %s", self._series_uid[:16], exc)
        try:
            self._signals.finished.emit(self._study_uid, self._series_uid, image)
        except RuntimeError:
            log.debug("[PREVIEW] loader deleted, dropping result")


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
        self._signals = _PreviewSignals()
        self._signals.finished.connect(self._on_finished, Qt.ConnectionType.QueuedConnection)

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
        try:
            self._signals.finished.disconnect()
        except (RuntimeError, TypeError):
            pass

    # ── internals ───────────────────────────────────────────────────

    def _pump(self) -> None:
        while self._queue and len(self._in_flight) < self._max_in_flight:
            study_uid, series_uid = self._queue.pop(0)
            key = (study_uid, series_uid)
            self._in_flight.add(key)
            task = _PreviewTask(self._client, study_uid, series_uid, self._target, self._signals)
            self._pool.start(task)

    def _on_finished(self, study_uid: str, series_uid: str, image: object) -> None:
        key = (study_uid, series_uid)
        self._in_flight.discard(key)
        if self._closed:
            return
        if isinstance(image, QImage) and not image.isNull():
            pixmap = QPixmap.fromImage(image)
            if not pixmap.isNull():
                self._pixmaps[key] = pixmap
                while len(self._pixmaps) > self._cache_limit:
                    self._pixmaps.popitem(last=False)
                self.preview_ready.emit(study_uid, series_uid)
        else:
            self._failed.add(key)
        self._pump()
