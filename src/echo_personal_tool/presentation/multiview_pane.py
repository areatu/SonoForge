"""One pane of the Multiview layout: header, viewer and marker controls.

A pane owns exactly one ``ViewerWidget`` and one SOP Instance.  Nothing here
talks to the main controller: every interaction is forwarded to
:class:`~echo_personal_tool.presentation.multiview_controller.MultiViewController`
through signals, which keeps the two panes symmetric and the state in one place.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, Signal
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.domain.models.multiview import EventMarker, PaneId
from echo_personal_tool.presentation.multiview_marker_strip import MarkerStrip


class _ElidingFileLabel(QLabel):
    """Show long DICOM names without forcing a Multiview pane wider."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_text = "—"
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.set_elided_text(self._full_text)

    def set_elided_text(self, text: str) -> None:
        self._full_text = text
        self._apply_elision()

    def minimumSizeHint(self) -> QSize:  # noqa: N802 (Qt naming)
        return QSize(0, super().minimumSizeHint().height())

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 (Qt naming)
        super().resizeEvent(event)
        self._apply_elision()

    def _apply_elision(self) -> None:
        width = max(0, self.contentsRect().width())
        text = self.fontMetrics().elidedText(
            self._full_text,
            Qt.TextElideMode.ElideRight,
            width,
        )
        super().setText(text)


_PANE_TITLES = {PaneId.LEFT: "A", PaneId.RIGHT: "B"}

#: Standard projections offered as a pane view label. The label is never
#: guessed from the DICOM header - the user confirms it (spec 5.1).
VIEW_LABELS: tuple[str, ...] = (
    "A4C",
    "A2C",
    "A3C",
    "A5C",
    "PLAX",
    "PSAX",
    "SAX",
    "Subcostal",
    "Suprasternal",
)


class MultiViewPaneWidget(QWidget):
    """Left/right pane of the two-clip Multiview layout."""

    activated = Signal(PaneId)
    replace_requested = Signal(PaneId)
    pane_cleared = Signal(PaneId)
    marker_place_requested = Signal(PaneId, int)  # ordinal
    marker_remove_requested = Signal(PaneId, int)  # ordinal
    marker_rename_requested = Signal(PaneId, int, str)  # ordinal, label
    marker_seek_requested = Signal(PaneId, int)  # frame index
    markers_cleared = Signal(PaneId)
    all_markers_cleared = Signal(PaneId)
    view_label_changed = Signal(PaneId, str)

    def __init__(self, pane_id: PaneId, viewer, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.pane_id = pane_id
        self._viewer = viewer
        self._view_label = ""
        self._active = False
        self._cycle_count = 1
        self._markers: tuple[EventMarker, ...] = ()
        self._marker_total_frames = 0
        self._marker_current_frame = 0
        self._marker_buttons: list[QPushButton] = []
        self._marker_left_spacer: QSpacerItem | None = None
        self._marker_right_spacer: QSpacerItem | None = None

        self.setObjectName(f"multiviewPane_{pane_id.value}")
        # A loaded frame or a long DICOM UID must not become this pane's
        # minimum width; QSplitter is responsible for allocating both panes.
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.setMinimumWidth(0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # ── header ──────────────────────────────────────────────────
        header = QWidget()
        header.setObjectName("multiviewPaneHeader")
        self._header = header
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(6, 3, 6, 3)
        header_layout.setSpacing(6)

        self._letter_label = QLabel(_PANE_TITLES[pane_id])
        self._letter_label.setObjectName("multiviewPaneLetter")
        header_layout.addWidget(self._letter_label)

        self._file_label = _ElidingFileLabel()
        self._file_label.setObjectName("multiviewPaneFile")
        header_layout.addWidget(self._file_label, 1)

        self._view_button = QPushButton("—")
        self._view_button.setObjectName("multiviewPaneView")
        self._view_button.setToolTip(self._tr("multiview.view.tooltip"))
        self._view_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._view_button.clicked.connect(self._show_view_menu)
        header_layout.addWidget(self._view_button)

        self._frame_label = QLabel("—")
        self._frame_label.setObjectName("multiviewPaneFrame")
        header_layout.addWidget(self._frame_label)

        self._active_label = QLabel(self._tr("multiview.pane.active"))
        self._active_label.setObjectName("multiviewPaneActive")
        self._active_label.setVisible(False)
        header_layout.addWidget(self._active_label)

        self._replace_button = QPushButton(self._tr("multiview.pane.replace"))
        self._replace_button.setObjectName("multiviewPaneReplace")
        self._replace_button.setToolTip(self._tr("multiview.pane.replace_tooltip"))
        self._replace_button.clicked.connect(lambda: self.replace_requested.emit(self.pane_id))
        header_layout.addWidget(self._replace_button)

        self._menu_button = QPushButton("⋮")
        self._menu_button.setObjectName("multiviewPaneMenu")
        self._menu_button.setFixedWidth(24)
        self._menu_button.setToolTip(self._tr("multiview.pane.menu"))
        self._menu_button.clicked.connect(self._show_pane_menu)
        header_layout.addWidget(self._menu_button)

        layout.addWidget(header)

        # ── viewer ──────────────────────────────────────────────────
        layout.addWidget(self._viewer, 1)

        # ── marker strip, aligned with the viewer's frame slider ────
        marker_row = QHBoxLayout()
        marker_row.setContentsMargins(0, 0, 0, 0)
        marker_row.setSpacing(0)
        self._marker_left_spacer = QSpacerItem(0, 0)
        self._marker_right_spacer = QSpacerItem(0, 0)
        marker_row.addSpacerItem(self._marker_left_spacer)
        self._marker_strip = MarkerStrip()
        self._marker_strip.marker_clicked.connect(lambda frame: self.marker_seek_requested.emit(self.pane_id, frame))
        self._marker_strip.marker_remove_requested.connect(
            lambda ordinal: self.marker_remove_requested.emit(self.pane_id, ordinal)
        )
        self._marker_strip.marker_renamed.connect(
            lambda ordinal, label: self.marker_rename_requested.emit(self.pane_id, ordinal, label)
        )
        marker_row.addWidget(self._marker_strip, 1)
        marker_row.addSpacerItem(self._marker_right_spacer)
        layout.addLayout(marker_row)

        # ── marker buttons (event-marker mode) ──────────────────────
        self._marker_bar = QWidget()
        self._marker_bar.setObjectName("multiviewMarkerBar")
        marker_bar_layout = QHBoxLayout(self._marker_bar)
        marker_bar_layout.setContentsMargins(6, 2, 6, 4)
        marker_bar_layout.setSpacing(4)
        self._marker_buttons_layout = marker_bar_layout
        self._rebuild_marker_buttons()
        layout.addWidget(self._marker_bar)

        # ── empty placeholder over the image area ───────────────────
        self._placeholder = QLabel(self._tr("multiview.placeholder.select_second"), self)
        self._placeholder.setObjectName("multiviewPlaceholder")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setWordWrap(True)
        self._placeholder.setCursor(Qt.CursorShape.PointingHandCursor)
        self._placeholder.setToolTip(self._tr("multiview.pane.replace_tooltip"))
        self._placeholder.hide()

        self.set_active(False)
        self._viewer.installEventFilter(self)
        for child in self._viewer_widgets_to_watch():
            child.installEventFilter(self)
        self._viewer._timeline_slider.installEventFilter(self)
        self._placeholder.installEventFilter(self)
        # a click on the header activates the pane too (spec 10.1)
        header.installEventFilter(self)

    # ── helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _tr(key: str, **kwargs: str) -> str:
        from echo_personal_tool.infrastructure.i18n import tr

        return tr(key, **kwargs)

    def _viewer_widgets_to_watch(self) -> list[QWidget]:
        candidates = [getattr(self._viewer, "_graphics", None), getattr(self._viewer, "_view", None)]
        return [widget for widget in candidates if widget is not None]

    @property
    def viewer(self):
        return self._viewer

    @property
    def marker_strip(self) -> MarkerStrip:
        return self._marker_strip

    @property
    def view_label(self) -> str:
        return self._view_label

    # ── state ───────────────────────────────────────────────────────

    def set_active(self, active: bool) -> None:
        self._active = active
        self._active_label.setVisible(active)
        self.setProperty("active", active)
        self.style().unpolish(self)
        self.style().polish(self)

    def is_active(self) -> bool:
        return self._active

    def set_header(self, *, file_name: str, frame_text: str, has_clip: bool, error: str | None) -> None:
        self._file_label.set_elided_text(file_name)
        self._file_label.setToolTip(error or file_name)
        self._frame_label.setText(frame_text)
        self._replace_button.setEnabled(True)
        # A failed read keeps its message: the pane must not show the previous
        # clip's frame under the new name (spec 6.2), nor invite the user to
        # pick a clip they already picked.
        if error:
            self._placeholder.setVisible(True)
            self._placeholder.setText(error)
            return
        self._placeholder.setVisible(not has_clip)
        if not has_clip:
            self._placeholder.setText(self._tr("multiview.placeholder.select_second"))

    def set_cycle_count(self, cycle_count: int) -> None:
        if self._cycle_count == cycle_count:
            return
        self._cycle_count = cycle_count
        self._rebuild_marker_buttons()

    def set_markers(self, markers, total_frames: int, current_frame: int) -> None:
        self._markers = tuple(markers)
        self._marker_total_frames = int(total_frames)
        self._marker_current_frame = int(current_frame)
        self._marker_strip.set_markers(self._markers, total_frames)
        self._marker_strip.set_current_frame(current_frame)
        self._marker_strip.refresh_tooltip()
        self._apply_marker_button_state()

    def _apply_marker_button_state(self) -> None:
        """Mark the placed markers and keep the unplaceable ones disabled.

        A marker may only be placed when every earlier one exists, so the user
        cannot leave a hole in the МК₀→МК₁→МК₂ chain (spec §9).
        """
        for ordinal, button in enumerate(self._marker_buttons):
            placed = ordinal < len(self._markers)
            button.setEnabled(ordinal <= len(self._markers) and ordinal < self._cycle_count + 1)
            button.setProperty("placed", placed)
            button.style().unpolish(button)
            button.style().polish(button)

    def _rebuild_marker_buttons(self) -> None:
        while self._marker_buttons_layout.count():
            item = self._marker_buttons_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._marker_buttons = []
        labels = [f"MK{index}" for index in range(self._cycle_count + 1)]
        for ordinal, label in enumerate(labels):
            button = QPushButton(self._tr("multiview.marker.set", label=label))
            button.setObjectName("multiviewMarkerButton")
            button.setCheckable(False)
            button.clicked.connect(
                lambda _checked=False, ordinal=ordinal: self.marker_place_requested.emit(self.pane_id, ordinal)
            )
            self._marker_buttons.append(button)
            self._marker_buttons_layout.addWidget(button)
        clear_button = QPushButton(self._tr("multiview.marker.clear"))
        clear_button.setObjectName("multiviewMarkerClear")
        clear_button.clicked.connect(lambda: self.markers_cleared.emit(self.pane_id))
        self._marker_buttons_layout.addWidget(clear_button)
        clear_all_button = QPushButton(self._tr("multiview.marker.clear_all"))
        clear_all_button.setObjectName("multiviewMarkerClearAll")
        clear_all_button.clicked.connect(lambda: self.all_markers_cleared.emit(self.pane_id))
        self._marker_buttons_layout.addWidget(clear_all_button)
        self._marker_buttons_layout.addStretch(1)
        self._apply_marker_button_state()

    def set_window(self, span: tuple[int, int] | None) -> None:
        """Show the shared common window on this pane's timeline (spec 8.2)."""
        if span is None:
            self._marker_strip.set_window(None, None)
        else:
            self._marker_strip.set_window(span[0], span[1])

    def set_marker_bar_visible(self, visible: bool) -> None:
        self._marker_bar.setVisible(visible)

    # ── geometry ────────────────────────────────────────────────────

    def _in_same_window(self, widget: QWidget) -> bool:
        """True when ``widget`` already shares a window with this pane."""
        try:
            return self.window() is widget.window()
        except RuntimeError:
            return False

    def _sync_marker_alignment(self) -> None:
        """Keep the marker strip horizontally aligned with the frame slider."""
        try:
            slider = self._viewer._timeline_slider
        except RuntimeError:
            return
        if not self.isVisible() or not slider.isVisible():
            return
        if not self._in_same_window(slider):
            return
        # ``self`` is not necessarily an ancestor of the slider (the left pane
        # can wrap the application's pre-existing viewer).  mapTo(self, ...)
        # therefore triggers QWidget::mapTo() warnings and may return a wrong
        # offset.  Global coordinates are valid for any widgets in one window.
        offset = self.mapFromGlobal(slider.mapToGlobal(QPoint(0, 0)))
        left = max(0, offset.x())
        right = max(0, self.width() - left - slider.width())
        if self._marker_left_spacer is not None:
            self._marker_left_spacer.changeSize(left, 0)
        if self._marker_right_spacer is not None:
            self._marker_right_spacer.changeSize(right, 0)
        if self._marker_row_layout() is not None:
            self._marker_row_layout().invalidate()

    def _marker_row_layout(self):
        return self._marker_strip.parentWidget().layout() if self._marker_strip.parentWidget() else None

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        super().resizeEvent(event)
        self._sync_marker_alignment()
        self._reposition_placeholder()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        super().showEvent(event)
        self._sync_marker_alignment()
        self._reposition_placeholder()

    def _reposition_placeholder(self) -> None:
        geometry = self._viewer.geometry()
        top = geometry.top()
        if geometry.width() <= 0 or geometry.height() <= 0:
            return
        self._placeholder.setGeometry(
            geometry.left(),
            top,
            geometry.width(),
            geometry.height(),
        )
        if self._placeholder.isVisible() and self._in_same_window(self._viewer):
            self._placeholder.raise_()

    def eventFilter(self, watched: object, event: QEvent) -> bool:  # noqa: N802 (Qt naming)
        if event.type() == QEvent.Type.Resize and watched is self._viewer:
            self._sync_marker_alignment()
            self._reposition_placeholder()
        if event.type() == QEvent.Type.MouseButtonPress:
            if watched is self._placeholder:
                self.replace_requested.emit(self.pane_id)
                return True
            if watched is self._viewer or watched in self._viewer_widgets_to_watch() or watched is self._header:
                self.activated.emit(self.pane_id)
        return super().eventFilter(watched, event)

    # ── menus ───────────────────────────────────────────────────────

    def _show_view_menu(self) -> None:
        menu = QMenu(self)
        none_action = menu.addAction(self._tr("multiview.view.none"))
        none_action.setCheckable(True)
        none_action.setChecked(not self._view_label)
        for label in VIEW_LABELS:
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(label == self._view_label)
        chosen = menu.exec(self._view_button.mapToGlobal(QPoint(0, self._view_button.height())))
        if chosen is None:
            return
        if chosen is none_action:
            self._set_view_label("")
        else:
            self._set_view_label(chosen.text())

    def _set_view_label(self, label: str) -> None:
        if label == self._view_label:
            return
        self._view_label = label
        self._view_button.setText(label or "—")
        self._view_button.setToolTip(self._tr("multiview.view.tooltip"))
        self.view_label_changed.emit(self.pane_id, label)

    def _show_pane_menu(self) -> None:
        menu = QMenu(self)
        menu.addAction(self._tr("multiview.pane.replace"), lambda: self.replace_requested.emit(self.pane_id))
        menu.addAction(self._tr("multiview.marker.clear"), lambda: self.markers_cleared.emit(self.pane_id))
        menu.addAction(self._tr("multiview.marker.clear_all"), lambda: self.all_markers_cleared.emit(self.pane_id))
        menu.addSeparator()
        menu.addAction(self._tr("multiview.pane.clear"), lambda: self.pane_cleared.emit(self.pane_id))
        menu.exec(self._menu_button.mapToGlobal(QPoint(0, self._menu_button.height())))
