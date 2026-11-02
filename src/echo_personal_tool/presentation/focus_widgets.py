"""Qt widgets of the single-file focus view (UI-6, spec §4.8).

The layer is deliberately small: a thin header strip, the «Измерения в этом
файле» card and the floating cine plate.  None of them owns a measurement, a
frame or a playback clock — the card renders the same plain-text summary the
on-image overlay uses, and the cine plate only forwards gestures to the
controller.  The window keeps the widgets across layout rebuilds, so entering
and leaving focus never touches the viewer or its decoded frames.

The plates are children of the viewer instead of a full-size transparent
overlay: a widget that covers the image would swallow drawing clicks, and the
focus mode must not change how the snapshot is used.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QEvent, QObject, QRect, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QFont, QMouseEvent, QResizeEvent
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.application.localization import tr
from echo_personal_tool.keyboard_shortcuts import shortcut_label
from echo_personal_tool.presentation.focus_mode import (
    FocusHeaderInfo,
    FocusRect,
    focus_header_text,
    place_focus_panels,
    plate_opacity,
    split_measurement_line,
)
from echo_personal_tool.presentation.ui_metrics import control_height

#: Height of the thin strip; it grows with the UI font (§4.8, 100 % = 34 px).
FOCUS_HEADER_HEIGHT_MIN = 34

#: Colours of the focus plates. The sheet is applied to the plates themselves,
#: not appended to the application sheet: the four legacy stylesheets are
#: kept byte for byte (`test_theme_tokens` golden files), and a feature that
#: arrives later reads the tokens instead of editing the golden sheets.
_FOCUS_QSS = """
#focusHeader {{
    background: {surface_2};
    border-bottom: 1px solid {line_1};
}}
#focusFileName {{
    color: {text_1};
}}
#focusMeta {{
    color: {text_2};
}}
#focusBadge {{
    background: {accent};
    color: {accent_on};
    border-radius: 8px;
    padding: 2px 8px;
}}
#focusKeyBadge {{
    background: {surface_3};
    color: {text_2};
    border: 1px solid {line_2};
    border-radius: 4px;
    padding: 1px 6px;
}}
#focusCard, #focusCineBar {{
    background: {surface_2};
    border: 1px solid {line_1};
    border-radius: 8px;
}}
#focusCardTitle {{
    color: {text_1};
}}
#focusCardEmpty {{
    color: {text_3};
}}
#focusRowLabel {{
    color: {text_2};
}}
#focusRowValue {{
    color: {text_1};
}}
#focusFrameCounter, #focusFps {{
    color: {text_2};
}}
#focusCardBody, #focusCardScroll {{
    background: transparent;
}}
"""


def focus_stylesheet() -> str:
    """Return the QSS of the focus plates for the active theme.

    Every colour is a semantic token (UI-0, §5.3), so the four themes and the
    system mode need no branch here and the colour ratchet sees no literals.
    """
    from echo_personal_tool.presentation.dark_theme import get_theme_tokens

    tokens = get_theme_tokens()
    return _FOCUS_QSS.format(
        surface_2=tokens["surface.2"],
        surface_3=tokens["surface.3"],
        line_1=tokens["line.1"],
        line_2=tokens["line.2"],
        text_1=tokens["text.1"],
        text_2=tokens["text.2"],
        text_3=tokens["text.3"],
        accent=tokens["accent"],
        accent_on=tokens["accent.on"],
    )


class _ElidedLabel(QLabel):
    """A one-line label that elides to the right and keeps the full text in a tooltip."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_text = ""
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)
        self.set_full_text(text)

    def set_full_text(self, text: str) -> None:
        self._full_text = str(text or "")
        self.setToolTip(self._full_text)
        self._apply_elision()

    def full_text(self) -> str:
        return self._full_text

    def resizeEvent(self, event: QResizeEvent) -> None:  # type: ignore[override]  # mypy does not check this file (outside tool.mypy.files)
        super().resizeEvent(event)
        self._apply_elision()

    def _apply_elision(self) -> None:
        width = max(0, self.contentsRect().width())
        if width <= 0:
            super().setText("")
            return
        super().setText(self.fontMetrics().elidedText(self._full_text, Qt.TextElideMode.ElideRight, width))


class FocusHeader(QWidget):
    """The thin strip over the snapshot: file facts, the «Фокус» badge and the way out."""

    OBJECT_NAME = "focusHeader"

    exit_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(self.OBJECT_NAME)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 8, 4)
        layout.setSpacing(10)

        self._file = _ElidedLabel(parent=self)
        self._file.setObjectName("focusFileName")
        font = QFont(self.font())
        font.setBold(True)
        self._file.setFont(font)
        self._file.setMinimumWidth(120)
        layout.addWidget(self._file, stretch=2)

        self._meta = _ElidedLabel(parent=self)
        self._meta.setObjectName("focusMeta")
        self._meta.setMinimumWidth(80)
        layout.addWidget(self._meta, stretch=3)

        self._badge = QLabel(tr("focus.badge"), self)
        self._badge.setObjectName("focusBadge")
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._badge, 0)

        self._exit = QPushButton(self)
        self._exit.setObjectName("focusExit")
        self._exit.setAutoDefault(False)
        self._exit.clicked.connect(self.exit_requested.emit)
        layout.addWidget(self._exit, 0)

        self._key = QLabel(shortcut_label("toggle_focus_mode"), self)
        self._key.setObjectName("focusKeyBadge")
        self._key.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._key, 0)

        self.setMinimumHeight(FOCUS_HEADER_HEIGHT_MIN)
        self.apply_theme()
        self.reload_text()
        self.set_info(FocusHeaderInfo())

    def apply_theme(self) -> None:
        """Re-read the tokens: the strip follows a theme switch without a restart."""
        self.setStyleSheet(focus_stylesheet())

    # ── content ─────────────────────────────────────────────────────

    def set_info(self, info: FocusHeaderInfo) -> None:
        """Fill the strip; an unknown patient or date simply leaves that part out."""
        self._file.set_full_text(info.file_label)
        meta = focus_header_text(info)
        self._meta.set_full_text(meta)
        self._meta.setVisible(bool(meta))

    def info_text(self) -> tuple[str, str]:
        """``(file, secondary line)`` as shown — the full, unelided strings."""
        return self._file.full_text(), self._meta.full_text()

    def reload_text(self) -> None:
        """Re-read the current language (UI-1 keeps every shell string live)."""
        self._badge.setText(tr("focus.badge"))
        self._exit.setText(tr("focus.exit"))
        self._exit.setToolTip(tr("focus.exit_tooltip"))
        self._key.setText(shortcut_label("toggle_focus_mode"))
        self._key.setToolTip(tr("focus.exit_tooltip"))

    # ── geometry ────────────────────────────────────────────────────

    def update_geometry(self) -> None:
        """The strip follows the UI font, not a hard-coded 34 px (§4.1 rule)."""
        self.setFixedHeight(max(FOCUS_HEADER_HEIGHT_MIN, control_height(self, padding=10) + 4))

    def hasHeightForWidth(self) -> bool:  # type: ignore[override]  # mypy does not check this file (outside tool.mypy.files)
        return False


class FocusMeasurementsCard(QFrame):
    """«Измерения в этом файле»: values of the current clip, and «Копировать».

    The rows come from the plain-text summary of the same formatter that paints
    the on-image overlay, so a value on the card and a value on the image can
    never come from two different computations.
    """

    OBJECT_NAME = "focusCard"

    copy_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(self.OBJECT_NAME)
        self._lines: tuple[str, ...] = ()
        self._row_widgets: list[QWidget] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        self._title = QLabel(self)
        self._title.setObjectName("focusCardTitle")
        title_font = QFont(self.font())
        title_font.setBold(True)
        self._title.setFont(title_font)
        layout.addWidget(self._title)

        self._empty = QLabel(self)
        self._empty.setObjectName("focusCardEmpty")
        self._empty.setWordWrap(True)
        layout.addWidget(self._empty)

        self._scroll = QScrollArea(self)
        self._scroll.setObjectName("focusCardScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._body = QWidget()
        self._body.setObjectName("focusCardBody")
        self._grid = QGridLayout(self._body)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(8)
        self._grid.setVerticalSpacing(3)
        self._grid.setColumnStretch(0, 1)
        self._grid.setColumnStretch(1, 0)
        self._scroll.setWidget(self._body)
        layout.addWidget(self._scroll, stretch=1)

        self._copy = QPushButton(self)
        self._copy.setObjectName("focusCopy")
        self._copy.setAutoDefault(False)
        self._copy.clicked.connect(self.copy_requested.emit)
        layout.addWidget(self._copy)

        self.apply_theme()
        self.reload_text()
        self.set_measurements(())

    def apply_theme(self) -> None:
        """Re-read the tokens of the card (UI-0 §5.3, no colour literals here)."""
        self.setStyleSheet(focus_stylesheet())

    # ── content ─────────────────────────────────────────────────────

    def set_measurements(self, lines: Sequence[str]) -> None:
        """Replace the rows; the empty state explains that the file has no values yet."""
        self._lines = tuple(str(line).strip() for line in lines if str(line).strip())
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._row_widgets.clear()

        for row, line in enumerate(self._lines):
            label, value = split_measurement_line(line)
            label_widget = QLabel(label, self._body)
            label_widget.setObjectName("focusRowLabel")
            label_widget.setWordWrap(False)
            value_widget = QLabel(value, self._body)
            value_widget.setObjectName("focusRowValue")
            value_widget.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            value_widget.setWordWrap(False)
            self._grid.addWidget(label_widget, row, 0)
            self._grid.addWidget(value_widget, row, 1)
            self._row_widgets.extend((label_widget, value_widget))
        self._grid.setRowStretch(len(self._lines), 1)

        has_rows = bool(self._lines)
        self._scroll.setVisible(has_rows)
        self._empty.setVisible(not has_rows)
        self._copy.setEnabled(has_rows)
        self._copy.setToolTip(tr("focus.card.copy_tooltip") if has_rows else tr("focus.card.empty_tooltip"))

    def measurement_lines(self) -> tuple[str, ...]:
        return self._lines

    def reload_text(self) -> None:
        self._title.setText(tr("focus.card.title"))
        self._empty.setText(tr("focus.card.empty"))
        self._copy.setText(tr("focus.card.copy"))
        self._copy.setToolTip(tr("focus.card.copy_tooltip"))

    def has_rows(self) -> bool:
        return bool(self._lines)


class FocusCineBar(QFrame):
    """The floating cine plate: play / step / seek, the frame counter and the rate."""

    OBJECT_NAME = "focusCineBar"

    play_pause_requested = Signal()
    frame_selected = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(self.OBJECT_NAME)
        self._playing = False
        self._total = 0
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(8)

        style = self.style()
        self._step_back = QPushButton(self)
        self._step_back.setObjectName("focusStepBack")
        self._step_back.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaSkipBackward))
        self._step_back.clicked.connect(self._step_backward)
        layout.addWidget(self._step_back)

        self._play = QPushButton(self)
        self._play.setObjectName("focusPlay")
        self._play.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self._play.clicked.connect(self.play_pause_requested.emit)
        layout.addWidget(self._play)

        self._step_forward = QPushButton(self)
        self._step_forward.setObjectName("focusStepForward")
        self._step_forward.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaSkipForward))
        self._step_forward.clicked.connect(self._step_forward_frame)
        layout.addWidget(self._step_forward)

        self._slider = QSlider(Qt.Orientation.Horizontal, self)
        self._slider.setObjectName("focusTimeline")
        self._slider.setSingleStep(1)
        self._slider.valueChanged.connect(self._on_slider_value_changed)
        layout.addWidget(self._slider, stretch=1)

        self._counter = QLabel(self)
        self._counter.setObjectName("focusFrameCounter")
        layout.addWidget(self._counter)

        self._fps = QLabel(self)
        self._fps.setObjectName("focusFps")
        layout.addWidget(self._fps)

        self.apply_theme()
        self.reload_text()
        self.set_state(playing=False, current_frame=0, total_frames=0, fps=0.0)

    def apply_theme(self) -> None:
        """Re-read the tokens of the plate (the icons come from the style)."""
        self.setStyleSheet(focus_stylesheet())

    # ── state ───────────────────────────────────────────────────────

    def set_state(self, *, playing: bool, current_frame: int, total_frames: int, fps: float) -> None:
        """Mirror the controller; programmatic updates never emit ``frame_selected``."""
        self._playing = bool(playing)
        self._total = max(0, int(total_frames))
        enabled = self._total > 1
        for button in (self._play, self._step_back, self._step_forward):
            button.setEnabled(enabled)
        self._slider.setEnabled(enabled)
        blocker = QSignalBlocker(self._slider)
        self._slider.setRange(0, max(0, self._total - 1))
        self._slider.setValue(max(0, min(int(current_frame), max(0, self._total - 1))))
        del blocker
        self._update_play_icon()
        if self._total > 0:
            self._counter.setText(tr("focus.cine.counter", current=int(current_frame) + 1, total=self._total))
        else:
            self._counter.setText(tr("viewer.frame_none"))
        self._fps.setText(tr("focus.cine.fps", fps=f"{max(0.0, float(fps)):.1f}") if fps > 0 else "")
        self._fps.setVisible(bool(fps > 0))

    def is_playing(self) -> bool:
        return self._playing

    def frame(self) -> int:
        return int(self._slider.value())

    def total_frames(self) -> int:
        return self._total

    def counter_text(self) -> str:
        return self._counter.text()

    def reload_text(self) -> None:
        self._step_back.setToolTip(tr("viewer.step_back"))
        self._step_forward.setToolTip(tr("viewer.step_forward"))
        self._slider.setToolTip(tr("viewer.timeline"))
        self._update_play_icon()
        self._counter.setText(tr("viewer.frame_none") if self._total == 0 else self._counter.text())

    # ── slots ───────────────────────────────────────────────────────

    def _update_play_icon(self) -> None:
        style = self.style()
        pixmap = QStyle.StandardPixmap.SP_MediaPause if self._playing else QStyle.StandardPixmap.SP_MediaPlay
        self._play.setIcon(style.standardIcon(pixmap))
        self._play.setToolTip(tr("viewer.pause") if self._playing else tr("viewer.play"))
        self._play.setAccessibleName(tr("viewer.pause") if self._playing else tr("viewer.play"))

    def _step_backward(self) -> None:
        if self._total > 0:
            self.frame_selected.emit(max(0, self.frame() - 1))

    def _step_forward_frame(self) -> None:
        if self._total > 0:
            self.frame_selected.emit(min(self._total - 1, self.frame() + 1))

    def _on_slider_value_changed(self, value: int) -> None:
        if self._total > 0:
            self.frame_selected.emit(int(value))


class FocusLayer(QObject):
    """Owns the floating plates and keeps them glued to the viewer edges.

    The card and the cine plate are direct children of the viewer: each one is
    as small as its content, so drawing anywhere else on the snapshot is not
    intercepted.  Geometry comes from the pure :func:`place_focus_panels`.
    """

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._parent = parent
        self.card = FocusMeasurementsCard(parent)
        self.cine = FocusCineBar(parent)
        self.card.hide()
        self.cine.hide()
        # §4.8: the plates step back while the pointer draws near them, so a
        # measurement started underneath them stays reachable.  The effect is
        # per plate and lives as long as the widget.
        self._card_fade = QGraphicsOpacityEffect(self.card)
        self._card_fade.setOpacity(1.0)
        self.card.setGraphicsEffect(self._card_fade)
        self._cine_fade = QGraphicsOpacityEffect(self.cine)
        self._cine_fade.setOpacity(1.0)
        self.cine.setGraphicsEffect(self._cine_fade)
        parent.installEventFilter(self)
        # The drawing happens in the graphics view's viewport, so the pointer is
        # tracked there (the viewer enables mouse tracking on it already).
        graphics = getattr(parent, "_graphics", None)
        viewport = graphics.viewport() if graphics is not None else None
        self._viewport: QWidget | None = viewport
        if viewport is not None:
            viewport.setMouseTracking(True)
            viewport.installEventFilter(self)
        self.set_visible(False)

    # ── visibility ──────────────────────────────────────────────────

    def set_visible(self, visible: bool) -> None:
        self.card.setVisible(bool(visible))
        self.cine.setVisible(bool(visible))
        if visible:
            self.sync_geometry()
            self.card.raise_()
            self.cine.raise_()

    def is_visible(self) -> bool:
        return self.card.isVisible() or self.cine.isVisible()

    # ── content ─────────────────────────────────────────────────────

    def set_measurements(self, lines: Sequence[str]) -> None:
        self.card.set_measurements(lines)
        self.sync_geometry()

    def set_cine_state(self, *, playing: bool, current_frame: int, total_frames: int, fps: float) -> None:
        self.cine.set_state(
            playing=playing,
            current_frame=current_frame,
            total_frames=total_frames,
            fps=fps,
        )

    def reload_text(self) -> None:
        self.card.reload_text()
        self.cine.reload_text()

    def apply_theme(self) -> None:
        """Re-colour the plates after a theme or font-size change."""
        self.card.apply_theme()
        self.cine.apply_theme()

    # ── geometry ────────────────────────────────────────────────────

    def sync_geometry(self) -> None:
        """Re-place both plates inside the viewer (safe before the first resize)."""
        rect = self._parent.rect()
        rects = place_focus_panels(
            rect.width(),
            rect.height(),
            card_height=self._card_height(rect.height()),
        )
        self.card.setGeometry(_to_qrect(rects.card))
        self.cine.setGeometry(_to_qrect(rects.cine))

    def _card_height(self, area_height: int) -> int:
        """Natural height of the card, capped by the placement rules."""
        self.card.adjustSize()
        return max(0, min(self.card.sizeHint().height(), max(0, area_height)))

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # type: ignore[override]  # mypy does not check this file (outside tool.mypy.files)
        if watched is self._parent and event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            if self.card.isVisible() or self.cine.isVisible():
                self.sync_geometry()
            return False
        if self._viewport is not None and watched is self._viewport:
            if event.type() == QEvent.Type.MouseMove and isinstance(event, QMouseEvent):
                # The plates live in the viewer's coordinates, the pointer arrives
                # in the viewport's: map it, or the fade would be offset by the
                # position of the graphics view inside the viewer.
                position = self._viewport.mapTo(self._parent, event.position().toPoint())
                self.fade_at(position.x(), position.y())
            elif event.type() == QEvent.Type.Leave:
                # The pointer left the image: nothing can be drawn under a plate.
                self.reset_fade()
        return False

    def fade_at(self, x: int, y: int) -> None:
        """Fade each plate the pointer is close to (§4.8); coordinates in the viewport."""
        if not self.is_visible():
            return
        self._card_fade.setOpacity(plate_opacity(x, y, _to_focus_rect(self.card.geometry())))
        self._cine_fade.setOpacity(plate_opacity(x, y, _to_focus_rect(self.cine.geometry())))

    def reset_fade(self) -> None:
        self._card_fade.setOpacity(1.0)
        self._cine_fade.setOpacity(1.0)

    def plate_opacities(self) -> tuple[float, float]:
        """Current fade of ``(card, cine)`` — the pointer-driven state, for tests."""
        return float(self._card_fade.opacity()), float(self._cine_fade.opacity())

    # ── tests and the window ────────────────────────────────────────

    def geometry_snapshot(self) -> tuple[QRect, QRect]:
        return self.card.geometry(), self.cine.geometry()


def _to_qrect(rect: FocusRect) -> QRect:
    return QRect(int(rect.x), int(rect.y), int(rect.width), int(rect.height))


def _to_focus_rect(rect: QRect) -> FocusRect:
    return FocusRect(int(rect.x()), int(rect.y()), int(rect.width()), int(rect.height()))


__all__ = [
    "FOCUS_HEADER_HEIGHT_MIN",
    "FocusCineBar",
    "FocusHeader",
    "FocusLayer",
    "FocusMeasurementsCard",
]
