"""A single multi-page classic CT/MR stack viewer (spec 557).

The backend already indexes classic single-frame CT/MR files into patient-space
ordered stacks (``CtMrIndex``) and decodes one slice at a time
(``CtMrSliceRequests``).  This widget is the missing presentation half: it
presents one stack as *one* multi-page image with page-flip navigation, fast
wheel scrolling and a slice slider — the way a normal DICOM viewer shows a
stack — instead of listing every file as a separate clip.

Design notes
------------
* One stack == one image surface.  A study that partitions into several
  stacks (a localizer, several phases, mixed orientations) is shown as a
  stack selector; the image surface always shows exactly one stack.
* Decoded frames are cached by ``(sop_uid, local_frame)`` in a small bounded
  LRU.  A cache hit paints instantly; a miss is requested through
  ``CtMrSliceRequests`` and painted when the result arrives on the UI thread.
  The service keeps at most one in-flight read and cancels superseded work,
  so fast scrolling always shows the newest request.
* Pixels are rendered through the shared DICOM display chain
  (``render_dicom_frame``): modality transform, VOI/W/L, MONOCHROME1.  The
  stored values are never shown raw.
* Orientation markers are derived from ``ImageOrientationPatient`` via
  :func:`orientation_labels`.  They are a best-effort rendering of the header
  facts; when a vector is oblique no marker is drawn rather than guessing.
"""

from __future__ import annotations

import logging
from collections import OrderedDict

import numpy as np
from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFontMetrics,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
    QResizeEvent,
    QShowEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.application.localization import tr
from echo_personal_tool.domain.models.ctmr_stack import CtMrIndex, CtMrStack, StackFrameRef
from echo_personal_tool.domain.models.dicom_display import (
    ANATOMICAL_WINDOW_BY_KEY,
    ANATOMICAL_WINDOW_PRESETS,
    match_anatomical_window,
)
from echo_personal_tool.domain.services.ctmr_orientation import orientation_labels, slice_plane_label
from echo_personal_tool.imaging.dicom_display import render_dicom_frame
from echo_personal_tool.presentation.dark_theme import get_theme_tokens

#: Bounded decoded-frame cache. Keeps ~96 2D slices around the cursor (~48 MB
#: for 512×512 int16) so rapid PACS-style series scrubbing hits warm RAM
#: without allocating an unbounded 3D volume.
_FRAME_CACHE_MAX = 96
#: Bounded rendered-pixmap cache keyed by (frame_identity, center, width).
_RENDERED_CACHE_MAX = 32
#: Directional lookahead prefetch counts around the active slice.
_PREFETCH_AHEAD = 8
_PREFETCH_BEHIND = 2
#: Fallback poll cadence for an in-flight slice read (milliseconds).
_POLL_MS = 8

logger = logging.getLogger(__name__)

_WARNING_LABELS = {
    "spatial_order_unverified": "ctmr.warn.order_unverified",
    "duplicate_positions": "ctmr.warn.duplicate_positions",
    "nonuniform_spacing_possible_gaps": "ctmr.warn.gaps",
    "in_plane_origin_shift": "ctmr.warn.origin_shift",
    "series_partitioned": "ctmr.warn.series_partitioned",
}


def _axis_marker(label: str) -> str:
    """Opposite patient-axis label for an orientation marker."""
    return {"L": "R", "R": "L", "A": "P", "P": "A", "S": "I", "I": "S"}.get(label, "")


class _SliceCanvas(QWidget):
    """Letterboxed slice image with orientation markers, scrubbing, and W/L drag."""

    scrub_steps_requested = Signal(int)
    wl_drag_requested = Signal(float, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self._scaled_cache: tuple[int, int, int, bool, QPixmap] | None = None
        self._fast_transform = False
        self._drag_mode: str | None = None
        self._drag_last: QPoint | None = None
        self._scrub_accum_px: float = 0.0
        self._tokens = get_theme_tokens()
        self.setMinimumSize(160, 120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        #: (slice index, total, position_mm, spacing_mm, plane, column, row)
        self._caption: tuple[int, int, str, str, str, str, str] = (0, 0, "", "", "", "", "")

    def set_image(self, pixmap: QPixmap | None, *, fast: bool = False) -> None:
        self._pixmap = pixmap
        self._fast_transform = fast
        self._scaled_cache = None
        self.update()

    def set_fast_transform(self, fast: bool) -> None:
        if self._fast_transform != fast:
            self._fast_transform = fast
            self._scaled_cache = None
            self.update()

    def set_caption(self, caption: tuple[int, int, str, str, str, str, str]) -> None:
        self._caption = caption
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self._drag_mode = "scrub"
            self._drag_last = event.position().toPoint()
            self._scrub_accum_px = 0.0
            event.accept()
            return
        if event.button() in (Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton) or (
            event.button() == Qt.MouseButton.LeftButton and bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        ):
            self._drag_mode = "wl"
            self._drag_last = event.position().toPoint()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_mode is not None and self._drag_last is not None:
            pos = event.position().toPoint()
            dx = float(pos.x() - self._drag_last.x())
            dy = float(pos.y() - self._drag_last.y())
            self._drag_last = pos
            if self._drag_mode == "scrub":
                self._scrub_accum_px += dy
                steps = int(self._scrub_accum_px / 4.0)
                if steps:
                    self._scrub_accum_px -= steps * 4.0
                    self.scrub_steps_requested.emit(steps)
            elif self._drag_mode == "wl":
                self.wl_drag_requested.emit(-dy, dx)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drag_mode is not None:
            self._drag_mode = None
            self._drag_last = None
            self._scrub_accum_px = 0.0
            self.set_fast_transform(False)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _draw_markers(self, painter: QPainter) -> None:
        _, _, _, _, plane, column, row = self._caption
        ink = QPen(Qt.PenStyle.NoPen)
        painter.setPen(ink)
        font = painter.font()
        font.setBold(True)
        font.setPointSize(10)
        painter.setFont(font)
        margin = 8
        box = QPen(Qt.PenStyle.SolidLine)
        box.setWidth(1)
        box.setCosmetic(True)
        painter.setPen(box)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if column:
            # Increasing column runs left -> right across the image.
            right = column
            left = _axis_marker(column)
            for side, label in (("right", right), ("left", left)):
                if not label:
                    continue
                x = self.width() - margin - 26 if side == "right" else margin
                rect = self._badge(x, margin, label, painter)
                painter.drawRoundedRect(rect, 3, 3)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), label)
                painter.setPen(box)
        if row:
            # Increasing row runs top -> bottom across the image.
            bottom = row
            top = _axis_marker(row)
            for side, label in (("bottom", bottom), ("top", top)):
                if not label:
                    continue
                y = self.height() - margin - 24 if side == "bottom" else margin
                rect = self._badge(margin, y, label, painter)
                painter.drawRoundedRect(rect, 3, 3)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), label)
                painter.setPen(box)
        if plane:
            rect = self._badge(self.width() - margin - 46, self.height() - margin - 24, plane, painter)
            painter.drawRoundedRect(rect, 3, 3)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), plane)
            painter.setPen(box)
        del ink

    @staticmethod
    def _badge(x: int, y: int, label: str, painter: QPainter) -> QRect:  # noqa: ANN401
        font = painter.font()
        width = max(24, QFontMetrics(font).horizontalAdvance(label) + 10)
        height = max(20, QFontMetrics(font).height() + 4)
        return QRect(x, y, width, height)

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        tokens = self._tokens
        painter.fillRect(self.rect(), QColor(tokens["surface.0"]))
        if self._pixmap is not None and not self._pixmap.isNull():
            w, h = self.width(), self.height()
            key = int(self._pixmap.cacheKey())
            cached = self._scaled_cache
            if cached is not None and cached[:4] == (key, w, h, self._fast_transform):
                scaled = cached[4]
            else:
                mode = (
                    Qt.TransformationMode.FastTransformation
                    if self._fast_transform
                    else Qt.TransformationMode.SmoothTransformation
                )
                scaled = self._pixmap.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio, mode)
                self._scaled_cache = (key, w, h, self._fast_transform, scaled)
            x = (w - scaled.width()) // 2
            y = (h - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
        self._draw_markers(painter)

        index, total, position, spacing, plane, column, row = self._caption
        if total > 0:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(tokens["surface.0"]))
            fact_font = painter.font()
            fact_font.setPointSize(9)
            painter.setFont(fact_font)
            fact_font.setBold(True)
            parts = [tr("ctmr.slice_of", index=index, total=total)]
            if position:
                parts.append(tr("ctmr.position", value=position))
            if spacing:
                parts.append(tr("ctmr.spacing", value=spacing))
            text = "   ·   ".join(parts)
            metrics = painter.fontMetrics()
            width = metrics.horizontalAdvance(text) + 16
            rect = QRect(8, self.height() - 26, width, 20)
            painter.fillRect(rect, QColor(tokens["surface.0"]))
            painter.setPen(QColor(tokens["text.1"]))
            painter.drawText(rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), text)


class CtMrStackViewer(QWidget):
    """Multi-page viewer for one classic CT/MR stack.

    The widget is self-contained: it owns a ``CtMrSliceRequests`` service (or
    an injected stand-in) and its bounded decoded-frame cache.  ``set_index``
    replaces the content; ``clear`` releases the stack and all decoded frames.
    """

    #: Emitted with the active stack index whenever the user changes stacks.
    stack_changed = Signal(int)
    _slice_ready = Signal()

    def __init__(self, parent: QWidget | None = None, *, slice_requests: object | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ctmrStackViewer")
        self._tokens = get_theme_tokens()
        self._index: CtMrIndex | None = None
        self._stack_index = 0
        self._slice_index = 0
        self._scroll_direction = 1
        self._wheel_remainder = 0
        self._slice_requests = slice_requests
        #: A service injected by the caller is not owned here: it is never
        #: closed, only re-selected.  One created lazily is closed with the stack.
        self._owns_service = slice_requests is None
        self._cache: OrderedDict[tuple[str, int], np.ndarray] = OrderedDict()
        self._rendered: OrderedDict[tuple[tuple[str, int], float, float], QPixmap] = OrderedDict()
        self._pending_index: int | None = None
        self._wl_initialized = False

        self._build_ui()

        self._poll = QTimer(self)
        self._poll.setInterval(_POLL_MS)
        self._poll.timeout.connect(self._on_poll)
        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.setInterval(80)
        self._settle_timer.timeout.connect(lambda: self._canvas.set_fast_transform(False))
        self._slice_ready.connect(self._on_poll, Qt.ConnectionType.QueuedConnection)
        self._bind_service_ready()

        self._refresh_caption()

    # ── size policy ──────────────────────────────────────────────

    def minimumSizeHint(self) -> QSize:
        """Return a zero minimum so the QStackedWidget does not raise the
        window's minimum width while this viewer is hidden.

        The internal canvas has ``setMinimumSize(160, 120)``; when the viewer
        is mounted in a QStackedWidget that minimum propagates to the stack
        and then to the window, preventing narrow window widths.  The Expanding
        size policy still fills available space when the viewer is shown.
        """
        return QSize(0, 0)

    # ── construction ──────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self._canvas = _SliceCanvas(self)
        self._canvas.scrub_steps_requested.connect(self.scrub_slices)
        self._canvas.wl_drag_requested.connect(self.adjust_window_by_drag)
        layout.addWidget(self._canvas, stretch=1)

        controls = QHBoxLayout()
        controls.setSpacing(6)
        self._prev_button = QPushButton(self)
        self._prev_button.setObjectName("ctmrPrevButton")
        self._prev_button.setText("◀")
        self._prev_button.setToolTip(tr("ctmr.prev_slice"))
        self._prev_button.setAccessibleName(tr("ctmr.prev_slice"))
        self._prev_button.clicked.connect(lambda: self.step_slice(-1))
        self._next_button = QPushButton(self)
        self._next_button.setObjectName("ctmrNextButton")
        self._next_button.setText("▶")
        self._next_button.setToolTip(tr("ctmr.next_slice"))
        self._next_button.setAccessibleName(tr("ctmr.next_slice"))
        self._next_button.clicked.connect(lambda: self.step_slice(1))

        self._slider = QSlider(Qt.Orientation.Horizontal, self)
        self._slider.setObjectName("ctmrSliceSlider")
        self._slider.setRange(0, 0)
        self._slider.valueChanged.connect(self._on_slider_changed)

        self._slice_label = QLabel(self)
        self._slice_label.setObjectName("ctmrSliceLabel")
        self._slice_label.setMinimumWidth(96)

        controls.addWidget(self._prev_button)
        controls.addWidget(self._next_button)
        controls.addWidget(self._slider, stretch=1)
        controls.addWidget(self._slice_label)
        layout.addLayout(controls)

        wl_row = QHBoxLayout()
        wl_row.setSpacing(6)
        self._preset_combo = QComboBox(self)
        self._preset_combo.setObjectName("ctmrPresetCombo")
        self._reset_preset_combo_items()
        self._preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        self._center_spin = QDoubleSpinBox(self)
        self._center_spin.setObjectName("ctmrCenterSpin")
        self._center_spin.setRange(-1e7, 1e7)
        self._center_spin.setDecimals(1)
        self._center_spin.valueChanged.connect(self._on_wl_changed)
        self._width_spin = QDoubleSpinBox(self)
        self._width_spin.setObjectName("ctmrWidthSpin")
        self._width_spin.setRange(0.1, 1e7)
        self._width_spin.setDecimals(1)
        self._width_spin.setValue(1.0)
        self._width_spin.valueChanged.connect(self._on_wl_changed)
        self._auto_button = QPushButton(self)
        self._auto_button.setObjectName("ctmrAutoWlButton")
        self._auto_button.setText(tr("ctmr.auto_wl"))
        self._auto_button.clicked.connect(self._auto_window)

        wl_row.addWidget(QLabel(tr("ctmr.wl_center"), self))
        wl_row.addWidget(self._center_spin)
        wl_row.addWidget(QLabel(tr("ctmr.wl_width"), self))
        wl_row.addWidget(self._width_spin)
        wl_row.addWidget(self._auto_button)
        wl_row.addStretch(1)
        wl_row.addWidget(QLabel(tr("ctmr.preset"), self))
        wl_row.addWidget(self._preset_combo)
        layout.addLayout(wl_row)

        self._stack_row = QHBoxLayout()
        self._stack_label = QLabel(tr("ctmr.stack"), self)
        self._stack_combo = QComboBox(self)
        self._stack_combo.setObjectName("ctmrStackCombo")
        self._stack_combo.currentIndexChanged.connect(self._on_stack_changed)
        self._stack_row.addWidget(self._stack_label)
        self._stack_row.addWidget(self._stack_combo)
        self._stack_row.addStretch(1)
        layout.addLayout(self._stack_row)

        self._warning_label = QLabel(self)
        self._warning_label.setObjectName("ctmrWarningLabel")
        self._warning_label.setWordWrap(True)
        self._warning_label.hide()
        layout.addWidget(self._warning_label)

        self._status_label = QLabel(self)
        self._status_label.setObjectName("ctmrStatusLabel")
        layout.addWidget(self._status_label)

        self._apply_theme()

    def _apply_theme(self) -> None:
        self._tokens = get_theme_tokens()
        tokens = self._tokens
        sheet = (
            f"#ctmrStackViewer {{ background: {tokens['surface.0']}; }}"
            f"#ctmrSliceSlider::handle:horizontal {{ background: {tokens['accent.text']}; }}"
            f"QPushButton#ctmrPrevButton, QPushButton#ctmrNextButton, QPushButton#ctmrAutoWlButton {{"
            f" background: {tokens['surface.2']}; border: 1px solid {tokens['line.1']};"
            f" border-radius: 5px; padding: 2px 8px; }}"
            f"QPushButton#ctmrPrevButton:hover, QPushButton#ctmrNextButton:hover,"
            f" QPushButton#ctmrAutoWlButton:hover {{ background: {tokens['surface.hover']}; }}"
            f"QLabel {{ color: {tokens['text.1']}; }}"
            f"#ctmrWarningLabel {{ color: {tokens['gallery.group.text.light']};"
            f" background: {tokens['surface.3']}; border: 1px solid {tokens['line.1']};"
            " border-radius: 4px; padding: 4px 8px; }"
            f"#ctmrStatusLabel {{ color: {tokens['text.3']}; }}"
        )
        self.setStyleSheet(sheet)
        self._canvas._tokens = self._tokens

    # ── content ────────────────────────────────────────────────────

    @property
    def index(self) -> CtMrIndex | None:
        """The index currently shown (``None`` when cleared)."""
        return self._index

    @property
    def slice_index(self) -> int:
        """Index of the slice currently on screen (0-based)."""
        return self._slice_index

    @property
    def stack_index(self) -> int:
        """Index of the active stack (0-based)."""
        return self._stack_index

    @property
    def slice_label(self) -> str:
        """The caption text of the current slice (e.g. ``«2 / 3»``)."""
        return self._slice_label.text()

    @property
    def warning_label(self) -> str:
        """The warning caption (empty when the order is verified)."""
        return self._warning_label.text()

    @property
    def warning_visible(self) -> bool:
        """True when the order-verification warning is shown."""
        return not self._warning_label.isHidden()

    @property
    def slice_requests(self) -> object:
        """The slice service (injected or lazily created)."""
        return self._slice_requests

    @property
    def canvas_pixmap(self) -> QPixmap | None:
        """The pixmap painted on the slice canvas (``None`` when empty)."""
        return self._canvas._pixmap

    @property
    def slider_maximum(self) -> int:
        """Maximum value of the slice slider (0 when no stack is loaded)."""
        return self._slider.maximum()

    def poll(self) -> None:
        """Process one pending slice result (public alias of ``_on_poll``)."""
        self._on_poll()

    def go_to_slice(self, index: int) -> None:
        """Navigate to the given slice index (public alias of ``_go_to_slice``)."""
        self._go_to_slice(index)

    def set_slice(self, index: int) -> None:
        """Set the slider to the given slice index (public alias of ``_slider.setValue``)."""
        self._slider.setValue(index)

    def select_stack(self, index: int) -> None:
        """Select the stack at the given index in the stack selector."""
        self._stack_combo.setCurrentIndex(index)

    def stack_combo_count(self) -> int:
        """Number of stacks in the selector."""
        return self._stack_combo.count()

    def set_index(self, index: CtMrIndex | None) -> None:
        """Show a fresh index; ``None`` or an empty index clears the viewer."""
        if self._owns_service:
            self._close_service()
        self._cache.clear()
        self._rendered.clear()
        self._index = index
        self._pending_index = None
        self._wl_initialized = False
        self._slice_index = 0
        self._status_label.clear()
        self._preset_combo.blockSignals(True)
        self._reset_preset_combo_items()
        self._preset_combo.blockSignals(False)
        self._center_spin.setValue(0.0)
        self._width_spin.setValue(1.0)
        self._canvas.set_image(None)

        if index is None or not index.stacks:
            self._stack_combo.blockSignals(True)
            self._stack_combo.clear()
            self._stack_combo.blockSignals(False)
            self._slider.setRange(0, 0)
            self._refresh_caption()
            return

        self._ensure_service()
        self._stack_combo.blockSignals(True)
        self._stack_combo.clear()
        for position, stack in enumerate(index.stacks):
            label = self._stack_label_text(stack, position)
            self._stack_combo.addItem(label, position)
        self._stack_combo.blockSignals(False)
        self._stack_index = 0
        self._stack_combo.setCurrentIndex(0)
        self._apply_stack_warnings()
        self._select_stack(0)

    @staticmethod
    def _stack_label_text(stack: CtMrStack, position: int) -> str:
        first = stack.frames[0]
        modality = first.modality
        frames = len(stack.frames)
        series = first.series_uid[-6:] if first.series_uid else ""
        return tr("ctmr.stack_item", modality=modality, frames=frames, series=series, index=position + 1)

    def clear(self) -> None:
        self.set_index(None)

    def _bind_service_ready(self) -> None:
        service = self._slice_requests
        if service is not None and hasattr(service, "set_on_ready"):
            service.set_on_ready(self._slice_ready.emit)

    def _ensure_service(self) -> None:
        if self._slice_requests is None:
            from echo_personal_tool.application.composition import make_ctmr_slice_requests

            self._slice_requests = make_ctmr_slice_requests()
        self._bind_service_ready()

    def _close_service(self) -> None:
        service = self._slice_requests
        self._slice_requests = None
        if service is not None and hasattr(service, "close"):
            try:
                service.close()
            except Exception as exc:  # noqa: BLE001 - closing is best-effort
                logger.debug("ctmr slice service close failed: %s", type(exc).__name__)
        self._poll.stop()

    # ── stack / slice selection ───────────────────────────────────

    def _on_stack_changed(self, index: int) -> None:
        self._stack_index = index
        self._slice_index = 0
        self._apply_stack_warnings()
        self._select_stack(index)
        self.stack_changed.emit(index)

    def _select_stack(self, index: int) -> None:
        service = self._slice_requests
        if self._index is None or not (0 <= index < len(self._index.stacks)):
            return
        stack = self._index.stacks[index]
        if service is not None and hasattr(service, "select_stack"):
            service.select_stack(stack)
        self._slice_index = 0
        self._wl_initialized = False
        self._slider.setRange(0, max(0, len(stack.frames) - 1))
        self._slider.setValue(0)
        self._clear_rendered()
        self._request_slice(0)

    def step_slice(self, delta: int) -> None:
        if self._index is None or not self._index.stacks:
            return
        total = len(self._index.stacks[self._stack_index].frames)
        if total <= 0:
            return
        target = max(0, min(total - 1, self._slice_index + delta))
        self._go_to_slice(target)

    def _on_slider_changed(self, value: int) -> None:
        if value != self._slice_index:
            self._go_to_slice(value)

    def _go_to_slice(self, index: int, *, fast: bool = False) -> None:
        if self._index is None or not self._index.stacks:
            return
        total = len(self._index.stacks[self._stack_index].frames)
        if not 0 <= index < total:
            return
        if index != self._slice_index:
            self._scroll_direction = 1 if index > self._slice_index else -1
        self._slice_index = index
        self._slider.blockSignals(True)
        self._slider.setValue(index)
        self._slider.blockSignals(False)
        if fast:
            self._canvas.set_fast_transform(True)
            self._settle_timer.start()
        self._request_slice(index)
        self._refresh_caption()

    def _store_cached_pixels(self, identity: tuple[str, int], pixels: np.ndarray) -> None:
        self._cache[identity] = pixels
        self._cache.move_to_end(identity)
        while len(self._cache) > _FRAME_CACHE_MAX:
            dropped, _ = self._cache.popitem(last=False)
            stale_keys = [rk for rk in self._rendered if rk[0] == dropped]
            for rk in stale_keys:
                self._rendered.pop(rk, None)

    def _schedule_prefetch(self) -> None:
        if self._index is None or not self._index.stacks or self._pending_index is not None:
            return
        service = self._slice_requests
        if service is None or not hasattr(service, "prefetch"):
            return
        stack = self._index.stacks[self._stack_index]
        total = len(stack.frames)
        if total <= 1:
            return
        direction = 1 if self._scroll_direction >= 0 else -1
        candidates: list[int] = []
        for step in range(1, _PREFETCH_AHEAD + 1):
            idx = self._slice_index + step * direction
            if 0 <= idx < total and stack.frames[idx].identity not in self._cache:
                candidates.append(idx)
        for step in range(1, _PREFETCH_BEHIND + 1):
            idx = self._slice_index - step * direction
            if 0 <= idx < total and stack.frames[idx].identity not in self._cache:
                candidates.append(idx)
        if candidates:
            service.prefetch(candidates)
            self._poll.start()

    def _request_slice(self, index: int) -> None:
        if self._index is None or not self._index.stacks:
            return
        stack = self._index.stacks[self._stack_index]
        ref = stack.frames[index]
        if ref.identity in self._cache:
            self._cache.move_to_end(ref.identity)
            self._publish_slice(ref)
            self._schedule_prefetch()
            return
        service = self._slice_requests
        if service is None or not hasattr(service, "request"):
            self._set_status(tr("ctmr.status_unavailable"))
            return
        self._pending_index = index
        self._poll.start()
        try:
            service.request(index)
        except IndexError:
            self._pending_index = None
            self._poll.stop()
            self._set_status(tr("ctmr.status_error"))

    def _on_poll(self) -> None:
        service = self._slice_requests
        if service is None or not hasattr(service, "poll"):
            return
        if hasattr(service, "drain_prefetched"):
            for _idx, pref_ref, pref_pixels in service.drain_prefetched():
                self._store_cached_pixels(pref_ref.identity, pref_pixels)
        result = service.poll()
        if result is None:
            if self._pending_index is None:
                self._poll.stop()
            return
        claimed = service.claim(result) if hasattr(service, "claim") else False
        if not claimed:
            return
        ticket = getattr(result, "ticket", None)
        if ticket is None:
            return
        ref = getattr(ticket, "ref", None)
        if not isinstance(ref, StackFrameRef):
            return
        if result.error is not None:
            if self._pending_index == getattr(ticket, "stack_index", None):
                self._pending_index = None
                self._set_status(tr("ctmr.status_error"))
            return
        pixels = result.pixels
        if pixels is None:
            return
        self._store_cached_pixels(ref.identity, pixels)
        if self._pending_index == getattr(ticket, "stack_index", None):
            self._pending_index = None
            self._publish_slice(ref)
            self._schedule_prefetch()

    def _publish_slice(self, ref: StackFrameRef) -> None:
        cached = self._cache.get(ref.identity)
        if cached is None:
            return
        if not self._wl_initialized:
            self._initialise_wl(ref, cached)
        center = round(float(self._center_spin.value()), 2)
        width = round(float(self._width_spin.value()), 2)
        render_key = (ref.identity, center, width)
        rendered = self._rendered.get(render_key)
        if rendered is not None:
            self._rendered.move_to_end(render_key)
        else:
            rendered = self._render_frame(ref, cached)
            if rendered is None:
                self._set_status(tr("ctmr.status_error"))
                return
            self._rendered[render_key] = rendered
            while len(self._rendered) > _RENDERED_CACHE_MAX:
                self._rendered.popitem(last=False)
        self._canvas.set_image(rendered, fast=self._canvas._fast_transform)
        self._refresh_caption()

    def _render_frame(self, ref: StackFrameRef, stored: np.ndarray) -> QPixmap | None:
        display = ref.display
        if display is None:
            return None
        # The W/L spinboxes are the single source of truth: a header preset or
        # the Auto button only update them, and rendering always uses them.
        numeric = (float(self._center_spin.value()), float(self._width_spin.value()))
        try:
            rendered = render_dicom_frame(stored, display, numeric_window=numeric)
        except (ValueError, TypeError, FloatingPointError):
            return None
        array = np.ascontiguousarray(rendered.pixels)
        height, width = array.shape
        image = QImage(array.data, width, height, width, QImage.Format.Format_Grayscale8)
        if image.isNull():
            return None
        # ``copy()`` gives the image its own buffer, which the pixmap then owns.
        return QPixmap.fromImage(image.copy())

    # ── W/L ───────────────────────────────────────────────────────

    def _reset_preset_combo_items(self) -> None:
        self._preset_combo.clear()
        self._preset_combo.addItem(tr("ctmr.preset_auto"), None)
        for spec in ANATOMICAL_WINDOW_PRESETS:
            label = f"{tr(spec.i18n_key)} ({spec.center:g}/{spec.width:g})"
            self._preset_combo.addItem(label, (float(spec.center), float(spec.width)))

    def anatomical_window_keys(self) -> tuple[str, ...]:
        """Return canonical anatomical window keys available in the stack viewer."""
        return tuple(spec.key for spec in ANATOMICAL_WINDOW_PRESETS)

    def apply_anatomical_window(self, name_or_key: str) -> bool:
        """Apply a named anatomical window map (brain, lungs, bones, chest, abdomen, angio)."""
        spec = ANATOMICAL_WINDOW_BY_KEY.get(name_or_key.strip().lower())
        if spec is None:
            spec = match_anatomical_window(name_or_key)
        if spec is None:
            return False
        target = (float(spec.center), float(spec.width))
        matched_index = -1
        for idx in range(self._preset_combo.count()):
            if self._preset_combo.itemData(idx) == target:
                matched_index = idx
                break
        self._center_spin.blockSignals(True)
        self._width_spin.blockSignals(True)
        self._center_spin.setValue(target[0])
        self._width_spin.setValue(target[1])
        self._center_spin.blockSignals(False)
        self._width_spin.blockSignals(False)
        if matched_index >= 0:
            self._preset_combo.blockSignals(True)
            self._preset_combo.setCurrentIndex(matched_index)
            self._preset_combo.blockSignals(False)
        self._rerender_current()
        return True

    def _on_preset_changed(self, _index: int) -> None:
        data = self._preset_combo.currentData()
        if isinstance(data, tuple) and len(data) == 2:
            self._center_spin.blockSignals(True)
            self._width_spin.blockSignals(True)
            self._center_spin.setValue(float(data[0]))
            self._width_spin.setValue(float(data[1]))
            self._center_spin.blockSignals(False)
            self._width_spin.blockSignals(False)
            self._rerender_current()
        elif data is None and _index == 0 and self._wl_initialized:
            self._auto_window()

    def _on_wl_changed(self) -> None:
        # A manual edit is a real choice: fall back to the Auto entry so the
        # combo never claims a preset that no longer matches the boxes.
        if self._preset_combo.currentIndex() != 0:
            self._preset_combo.blockSignals(True)
            self._preset_combo.setCurrentIndex(0)
            self._preset_combo.blockSignals(False)
        self._rerender_current()

    @property
    def window_level(self) -> tuple[float, float]:
        """Current (center, width) window/level values."""
        return (float(self._center_spin.value()), float(self._width_spin.value()))

    def scrub_slices(self, steps: int) -> None:
        if self._index is None or not self._index.stacks or steps == 0:
            return
        total = len(self._index.stacks[self._stack_index].frames)
        if total == 0:
            return
        target = max(0, min(total - 1, self._slice_index + steps))
        if target != self._slice_index:
            self._go_to_slice(target, fast=True)

    def adjust_window_by_drag(self, d_center: float, d_width: float) -> None:
        if self._index is None or not self._index.stacks:
            return
        cur_w = float(self._width_spin.value())
        cur_c = float(self._center_spin.value())
        scale = max(1.0, cur_w / 250.0)
        new_c = cur_c + d_center * scale
        new_w = max(1.0, cur_w + d_width * scale * 2.0)
        self._canvas.set_fast_transform(True)
        self._settle_timer.start()
        self._center_spin.blockSignals(True)
        self._width_spin.blockSignals(True)
        self._center_spin.setValue(new_c)
        self._width_spin.setValue(new_w)
        self._center_spin.blockSignals(False)
        self._width_spin.blockSignals(False)
        if self._preset_combo.currentIndex() != 0:
            self._preset_combo.blockSignals(True)
            self._preset_combo.setCurrentIndex(0)
            self._preset_combo.blockSignals(False)
        self._rerender_current()

    def _auto_window(self) -> None:
        ref = self._current_ref()
        cached = self._cache.get(ref.identity) if ref is not None else None
        if ref is not None and cached is not None and ref.display is not None:
            self._set_window_from_auto(ref, cached)
        self._preset_combo.blockSignals(True)
        self._preset_combo.setCurrentIndex(0)
        self._preset_combo.blockSignals(False)
        self._rerender_current()

    def _set_window_from_auto(self, ref: StackFrameRef, stored: np.ndarray) -> None:
        display = ref.display
        if display is None:
            return
        from echo_personal_tool.imaging.dicom_display import stored_to_modality

        sample = stored
        if stored.size > 65_536 and stored.ndim >= 2:
            step = max(2, int(round((stored.size / 65_536) ** 0.5)))
            sample = stored[::step, ::step]
        modality = stored_to_modality(sample, display)
        low = float(np.percentile(modality, 0.5))
        high = float(np.percentile(modality, 99.5))
        span = max(high - low, 1.0)
        center = low + span / 2.0
        width = span
        self._center_spin.blockSignals(True)
        self._width_spin.blockSignals(True)
        self._center_spin.setValue(center)
        self._width_spin.setValue(width)
        self._center_spin.blockSignals(False)
        self._width_spin.blockSignals(False)

    def _populate_presets(self, ref: StackFrameRef) -> None:
        display = ref.display
        self._preset_combo.blockSignals(True)
        self._reset_preset_combo_items()
        if display is not None and display.window_presets:
            insert_at = 1
            for preset in display.window_presets:
                label = preset.label or tr("ctmr.preset_custom", center=preset.center, width=preset.width)
                self._preset_combo.insertItem(insert_at, label, (float(preset.center), float(preset.width)))
                insert_at += 1
        self._preset_combo.blockSignals(False)

    def _initialise_wl(self, ref: StackFrameRef, stored: np.ndarray) -> None:
        if self._wl_initialized:
            return
        display = ref.display
        if display is None:
            return
        self._populate_presets(ref)
        preset = display.default_window
        if preset is not None:
            self._center_spin.blockSignals(True)
            self._width_spin.blockSignals(True)
            self._center_spin.setValue(float(preset.center))
            self._width_spin.setValue(float(preset.width))
            self._center_spin.blockSignals(False)
            self._width_spin.blockSignals(False)
            target = (float(preset.center), float(preset.width))
            for idx in range(self._preset_combo.count()):
                if self._preset_combo.itemData(idx) == target:
                    self._preset_combo.blockSignals(True)
                    self._preset_combo.setCurrentIndex(idx)
                    self._preset_combo.blockSignals(False)
                    break
        else:
            self._set_window_from_auto(ref, stored)
        self._wl_initialized = True

    def _rerender_current(self) -> None:
        if self._index is None or not self._index.stacks:
            return
        ref = self._current_ref()
        if ref is None:
            return
        cached = self._cache.get(ref.identity)
        if cached is None:
            return
        self._publish_slice(ref)

    def _current_ref(self) -> StackFrameRef | None:
        if self._index is None or not self._index.stacks:
            return None
        stack = self._index.stacks[self._stack_index]
        if not stack.frames:
            return None
        return stack.frames[min(self._slice_index, len(stack.frames) - 1)]

    # ── caption / warnings ────────────────────────────────────────

    def _refresh_caption(self) -> None:
        if self._index is None or not self._index.stacks:
            self._canvas.set_caption((0, 0, "", "", "", "", ""))
            self._slice_label.setText("")
            return
        stack = self._index.stacks[self._stack_index]
        total = len(stack.frames)
        index = min(self._slice_index, total - 1) if total else 0
        self._slice_label.setText(tr("ctmr.slice_of", index=index + 1, total=total))
        position, spacing, plane, column, row = "", "", "", "", ""
        if total and index < total:
            ref = stack.frames[index]
            geometry = ref.geometry
            if geometry is not None:
                position = f"{geometry.position[2]:.1f}"
                if stack.adjacent_spacing_mm:
                    spacing = f"{stack.adjacent_spacing_mm[0]:.2f}"
                plane = slice_plane_label(geometry.orientation)
                column, row = orientation_labels(geometry.orientation)
        self._canvas.set_caption((index, total, position, spacing, plane, column, row))

    def _apply_stack_warnings(self) -> None:
        if self._index is None or not self._index.stacks:
            self._warning_label.hide()
            return
        stack = self._index.stacks[self._stack_index]
        codes = [code for code in stack.warnings if code in _WARNING_LABELS]
        if not codes:
            self._warning_label.hide()
            return
        text = " · ".join(tr(_WARNING_LABELS[code]) for code in dict.fromkeys(codes))
        self._warning_label.setText(tr("ctmr.warnings_prefix", warnings=text))
        self._warning_label.show()

    def _set_status(self, message: str) -> None:
        self._status_label.setText(message)

    # ── keyboard / wheel ──────────────────────────────────────────

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self._index is None or not self._index.stacks:
            super().wheelEvent(event)
            return
        delta = -event.angleDelta().y()
        if delta == 0:
            delta = -event.pixelDelta().y() * 4
        if delta == 0:
            super().wheelEvent(event)
            return
        if (delta > 0 > self._wheel_remainder) or (delta < 0 < self._wheel_remainder):
            self._wheel_remainder = 0
        self._wheel_remainder += delta
        steps = int(self._wheel_remainder / 120)
        if steps:
            self._wheel_remainder -= steps * 120
            total = len(self._index.stacks[self._stack_index].frames)
            target = max(0, min(total - 1, self._slice_index + steps))
            if target != self._slice_index:
                self._go_to_slice(target, fast=True)
            event.accept()
        else:
            event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._index is None or not self._index.stacks:
            super().keyPressEvent(event)
            return
        key = event.key()
        total = len(self._index.stacks[self._stack_index].frames)
        page_jump = 10 if total > 10 else 1
        shortcut_presets: dict[int, str] = {
            int(Qt.Key.Key_1): "brain",
            int(Qt.Key.Key_2): "lungs",
            int(Qt.Key.Key_3): "bones",
            int(Qt.Key.Key_4): "chest",
            int(Qt.Key.Key_5): "abdomen",
            int(Qt.Key.Key_6): "angio",
        }
        if key in (Qt.Key.Key_Right, Qt.Key.Key_Up):
            self.step_slice(1)
            event.accept()
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Down):
            self.step_slice(-1)
            event.accept()
        elif key == Qt.Key.Key_PageDown:
            self.step_slice(page_jump)
            event.accept()
        elif key == Qt.Key.Key_PageUp:
            self.step_slice(-page_jump)
            event.accept()
        elif key == Qt.Key.Key_Home:
            self._go_to_slice(0)
            event.accept()
        elif key == Qt.Key.Key_End:
            self._go_to_slice(total - 1)
            event.accept()
        elif key in shortcut_presets and not event.modifiers():
            self.apply_anatomical_window(shortcut_presets[key])
            event.accept()
        else:
            super().keyPressEvent(event)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self._index is not None and self._index.stacks and self._canvas._pixmap is None:
            self._request_slice(self._slice_index)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self._index is not None and self._index.stacks:
            self._canvas.update()

    def _clear_rendered(self) -> None:
        self._rendered.clear()
