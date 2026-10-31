"""The patient line under the window title bar (42 px, UI-1 PR-3).

Spec §4.1 («Строка пациента»): one 42 px row over every layout. The study /
patient label and the heart rate on the left; the study actions on the right —
«Открыть», «PACS ▾» (load / send), «Сравнить» (Multiview), «Презентация»
(Presenter, Lite build only) and «Справочник» (references, the former
«Нормативы») — and, at the far right, the work-mode switch
«Изображения | Отчёт» (UI-4 PR-1): the mode belongs to the tab, this row only
mirrors it and reports the clicks.

The window controls and the tabs live in the title bar
(:class:`~echo_personal_tool.presentation.window_chrome.title_bar.WindowTitleBar`),
the logo and the application menu (settings, layout, help, about, quit) live
there too. Caliper and the layout button left this row for the tool panel and the
logo menu; the calibration buttons are not placed in the row (they were not
visible before either: their entry points are the commands and shortcuts). The
row keeps «Сброс» until the «Ещё» menu of the tool buttons exists (UI-2 PR-3).

The drag and resize gestures come from
:class:`~echo_personal_tool.presentation.window_chrome.caption_drag.CaptionDragMixin`,
the same behaviour the title bar uses.
"""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QResizeEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QWidget,
)

from echo_personal_tool.keyboard_shortcuts import append_shortcut_hint, shortcut_label
from echo_personal_tool.presentation.ui_animations import HoverButtonMixin
from echo_personal_tool.presentation.ui_metrics import line_height, text_width
from echo_personal_tool.presentation.window_chrome.caption_drag import CaptionDragMixin

#: Height of the patient line at 100 % (spec §4.1). It grows with the font.
PATIENT_LINE_HEIGHT_PX = 42

#: Logical edge of the glyph on a system-bar button.  Set explicitly: the default
#: icon size of a QPushButton comes from the style (16 px on Fusion, a different
#: value on the Windows style), which is why the same row looked spaced
#: differently on Windows and Linux.
ACTION_ICON_EDGE = 16
#: Gap between that glyph and its caption.  Qt draws a button icon a fixed 4 px
#: from the text and offers no stylesheet knob for it, so the icon box carries
#: the gap itself (see :func:`presentation.icon_loader.load_svg_icon`): the
#: caption sits 4 px of the style plus 4 px of the box away from the glyph, as in
#: the design, instead of the label starting on top of the pictogram.
ACTION_ICON_GAP = 4
#: Vertical room kept around the controls of the row when the font is large.
_PATIENT_LINE_PADDING_PX = 16


def _load_icon(name: str) -> QIcon:
    """A bundled glyph tinted with ``text.1`` of the active theme.

    Rasterised through ``QSvgRenderer`` (:mod:`presentation.icon_loader`), not
    through ``QPixmap.loadFromData``: the latter needs Qt's ``qsvg`` image-format
    plugin, which a frozen Windows build does not always ship — the same buttons
    then render without glyphs on Windows and with them on Linux.
    """
    from echo_personal_tool.presentation.icon_loader import load_svg_icon

    return load_svg_icon(name, gap_ratio=ACTION_ICON_GAP / ACTION_ICON_EDGE)


class _ElidingStatusLabel(QLabel):
    """Single-line status text: elide when space is tight; full text in tooltip."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_text = ""
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)

    def minimumSizeHint(self) -> QSize:  # type: ignore[override]
        base = super().minimumSizeHint()
        return QSize(0, base.height())

    def set_full_text(self, text: str) -> None:
        self._full_text = text
        self._apply_elision()

    def resizeEvent(self, event: QResizeEvent) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._apply_elision()

    def _apply_elision(self) -> None:
        if not self._full_text:
            super().setText("")
            self.setToolTip("")
            return
        available = max(self.contentsRect().width(), 0)
        if available <= 0:
            super().setText("")
            self.setToolTip(self._full_text)
            return
        elided = self.fontMetrics().elidedText(
            self._full_text,
            Qt.TextElideMode.ElideRight,
            available,
        )
        super().setText(elided)
        if elided != self._full_text:
            self.setToolTip(self._full_text)
        else:
            self.setToolTip("")


class _CollapsibleHost(QWidget):
    """The mount point of the patient editors.

    It keeps its *size hint* — the line measures it to decide whether the
    editors fit — but it asks for no minimum width: a plain host reports the
    two 76 px fields, their captions and the BSA as its minimum, and the whole
    window then refuses to shrink below ~1210 px (a 1366 × 768 screen at 150 %
    scaling has 911 logical px).  The row squeezes this host to nothing instead,
    and :meth:`SystemBar._fit_patient_metrics` hides it there.
    """

    def minimumSizeHint(self) -> QSize:  # type: ignore[override]
        base = super().minimumSizeHint()
        return QSize(0, base.height())


class SystemBar(CaptionDragMixin, QWidget):
    """The patient line: study context on the left, study actions on the right.

    This row is *not* a window caption any more (2026-10-27 UI list, item 3).
    Its empty space and its file name sit under the tabs, and dragging there
    moved the whole window instead of letting the user work with the name.  The
    OS resize gesture at the very top edge still works; moving and double-click
    maximize belong to WindowTitleBar only.
    """

    CAPTION_MOVE_ENABLED = False

    open_folder_requested = Signal()
    load_from_server_requested = Signal()
    send_to_server_requested = Signal()
    reset_session_requested = Signal()
    calibration_requested = Signal()
    doppler_calibration_requested = Signal()
    references_requested = Signal()
    heart_rate_requested = Signal()
    #: Double-click on the empty part of the row maximizes the window (the
    #: gesture comes from CaptionDragMixin; the buttons live in the title bar).
    maximize_requested = Signal()
    multiview_toggle_requested = Signal()
    presenter_toggle_requested = Signal()
    #: The work-mode switch (UI-4 PR-1, UD-08): True — «Отчёт», False — «Изображения».
    report_mode_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("systemBar")
        # Qt paints the stylesheet ground and the hairline of a plain QWidget
        # subclass only with this attribute: without it the patient line had no
        # bottom hairline and blended into the tool row (2026-10-27 list).
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        from echo_personal_tool.application.profile_settings import get_profile_capabilities
        from echo_personal_tool.infrastructure.i18n import tr

        self._profile_capabilities = get_profile_capabilities()
        self._study_label = QLabel(tr("system_bar.no_study"))
        # No reserved width: the patient phrase («Иванов · 164 см · 71 кг»)
        # is followed by the metrics, and a 120 px minimum both left a hole
        # after a short name and pushed the fields right of it.
        self._study_label.setMinimumWidth(0)
        # Expanding so the study/file name absorbs the free space and the
        # action group keeps its natural size.
        self._study_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )

        self._status_label = _ElidingStatusLabel()

        self._progress_bar = QProgressBar()
        self._progress_bar.setMaximumWidth(text_width(self, "100 %", padding=48, minimum=120))
        self._progress_bar.setTextVisible(True)
        self._progress_bar.hide()

        btn_open = QPushButton(tr("system_bar.open_folder"))
        btn_open.setIcon(_load_icon("folder_open"))
        btn_open.setToolTip(append_shortcut_hint(tr("system_bar.open_folder"), "open_folder"))
        btn_open.clicked.connect(self.open_folder_requested.emit)
        self._btn_open = btn_open

        # «PACS ▾»: one button with the two server actions. The menu opens on
        # the button itself (InstantPopup), so the first click already shows both.
        self._btn_pacs = QToolButton()
        self._btn_pacs.setObjectName("pacsButton")
        self._btn_pacs.setIcon(_load_icon("activity_dicom"))
        self._btn_pacs.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._btn_pacs.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._btn_pacs.setToolTip(tr("system_bar.pacs_tooltip"))
        self._pacs_menu = QMenu(self._btn_pacs)
        self._pacs_menu.setObjectName("pacsMenu")
        self._act_load_server = self._pacs_menu.addAction(
            _load_icon("cloud_download"), tr("system_bar.load_from_server")
        )
        self._act_load_server.triggered.connect(self.load_from_server_requested.emit)
        self._act_send_server = self._pacs_menu.addAction(_load_icon("activity_dicom"), tr("system_bar.send_to_server"))
        self._act_send_server.triggered.connect(self.send_to_server_requested.emit)
        self._btn_pacs.setMenu(self._pacs_menu)
        self._btn_pacs.setVisible(self._profile_capabilities.server_dialog)

        # Calibration buttons: not placed in the row (see the module docstring).
        btn_calibration = QPushButton(tr("system_bar.calibration_bmode"))
        btn_calibration.setIcon(_load_icon("tune"))
        btn_calibration.setToolTip(append_shortcut_hint(tr("tools.calibrate_tip"), "calibration_toggle"))
        btn_calibration.clicked.connect(self.calibration_requested.emit)
        self._btn_calibration = btn_calibration

        btn_doppler_calibration = QPushButton("Calibration Doppler")
        btn_doppler_calibration.setIcon(_load_icon("show_chart"))
        btn_doppler_calibration.setToolTip("Doppler spectrogram: ROI → baseline → velocity scale")
        btn_doppler_calibration.clicked.connect(self.doppler_calibration_requested.emit)
        self._btn_doppler_calibration = btn_doppler_calibration

        # «Справочник» — the former «Нормативы» (spec §4.1, UI-1 PR-3). An ordinary
        # button of the row: its look comes from the theme (UI-0 PR-3 removed the
        # teal inline fill), the window opens the reference dialog (S1).
        self._btn_references = QPushButton(tr("system_bar.references"))
        self._btn_references.setIcon(_load_icon("description"))
        self._btn_references.setToolTip(tr("system_bar.references_tooltip"))
        self._btn_references.clicked.connect(self.references_requested.emit)

        # «ЧСС» — the heart rate of the study. Click → measure from the cine loop.
        # The value field of the spec (DICOM or measured) comes with the patient
        # metrics in UI-1 PR-4; for now the button is the entry point.
        btn_heart_rate = QPushButton(tr("system_bar.heart_rate"))
        btn_heart_rate.setObjectName("heartRateButton")
        btn_heart_rate.setIcon(_load_icon("heart_rate"))
        btn_heart_rate.setToolTip(tr("system_bar.heart_rate_tooltip"))
        btn_heart_rate.clicked.connect(self.heart_rate_requested.emit)
        self._btn_heart_rate = btn_heart_rate

        # «Сброс» stays in the row until the «Ещё» menu of the tool buttons exists.
        btn_reset = QPushButton(tr("system_bar.reset"))
        btn_reset.setIcon(_load_icon("refresh"))
        btn_reset.setObjectName("resetButton")
        btn_reset.clicked.connect(self.reset_session_requested.emit)
        self._btn_reset = btn_reset

        # «Сравнить» — the Multiview entry point: two clips of the same study side
        # by side. Kept in sync with the layout-menu checkbox (spec §4.1).
        self._btn_multiview = QPushButton(tr("system_bar.compare"))
        self._btn_multiview.setIcon(_load_icon("two_panes"))
        self._btn_multiview.setObjectName("multiviewButton")
        self._btn_multiview.setCheckable(True)
        self._btn_multiview.setToolTip(tr("multiview.button_tooltip"))
        self._btn_multiview.clicked.connect(self.multiview_toggle_requested.emit)

        # «Презентация» — the Presenter (lite build only). A QToolButton with
        # MenuButtonPopup: the main area toggles the mode, the small arrow opens
        # the options menu (audience display, visual preset, pointer). The full
        # profile gets no button at all (same pattern as «Справочник»).
        self._btn_presenter: QToolButton | None = None
        if self._profile_capabilities.presenter_view:
            self._btn_presenter = QToolButton()
            self._btn_presenter.setIcon(_load_icon("presenter"))
            self._btn_presenter.setObjectName("presenterButton")
            self._btn_presenter.setCheckable(True)
            self._btn_presenter.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            self._btn_presenter.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
            self._btn_presenter.setText(tr("presenter.button"))
            self._btn_presenter.setToolTip(tr("presenter.tooltip", shortcut=shortcut_label("presenter_toggle")))
            self._btn_presenter.clicked.connect(self.presenter_toggle_requested.emit)

        # «Изображения | Отчёт» — the work-mode switch of the tab (UI-4 PR-1,
        # spec §4.1/§4.6, UD-08: exactly two states, no «Вместе»). A segmented
        # pair of checkable buttons; the mode itself belongs to the tab, the
        # bar only mirrors it (set_report_mode) and reports clicks.
        self._btn_mode_images = QPushButton(tr("system_bar.mode_images"))
        self._btn_mode_images.setObjectName("modeImagesButton")
        self._btn_mode_images.setCheckable(True)
        self._btn_mode_images.setChecked(True)
        self._btn_mode_report = QPushButton(tr("system_bar.mode_report"))
        self._btn_mode_report.setObjectName("modeReportButton")
        self._btn_mode_report.setCheckable(True)
        mode_tooltip = append_shortcut_hint(tr("system_bar.mode_tooltip"), "toggle_report_mode")
        self._btn_mode_images.setToolTip(mode_tooltip)
        self._btn_mode_report.setToolTip(mode_tooltip)
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        self._mode_group.addButton(self._btn_mode_images)
        self._mode_group.addButton(self._btn_mode_report)
        # The report button's own state is the boolean the window wants:
        # checking it emits True, the group unchecking it emits False.
        self._btn_mode_report.toggled.connect(self.report_mode_changed.emit)
        self._mode_switch = QWidget(self)
        self._mode_switch.setObjectName("modeSwitch")
        # The switch never shrinks (spec §6, narrow window): the study label
        # and the action captions give way first.
        self._mode_switch.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        mode_layout = QHBoxLayout(self._mode_switch)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.setSpacing(0)
        mode_layout.addWidget(self._btn_mode_images)
        mode_layout.addWidget(self._btn_mode_report)
        # No local stylesheet: the shell paints only through the global sheet
        # (UI-0 PR-3 keeps widget sheets of the bar free of colour literals),
        # and its QPushButton:checked already marks the active segment.

        # Install hover lerp mixin on all buttons
        for btn in (
            btn_open,
            self._btn_pacs,
            btn_calibration,
            btn_doppler_calibration,
            self._btn_references,
            btn_heart_rate,
            btn_reset,
            self._btn_multiview,
            self._btn_presenter,
            self._btn_mode_images,
            self._btn_mode_report,
        ):
            if btn is not None:
                btn.setIconSize(QSize(ACTION_ICON_EDGE + ACTION_ICON_GAP, ACTION_ICON_EDGE))
                HoverButtonMixin.install(btn)

        left = self._build_context_column(btn_heart_rate)

        self._actions_widget = QWidget()
        self._actions_widget.setSizePolicy(
            QSizePolicy.Policy.Maximum,
            QSizePolicy.Policy.Preferred,
        )
        actions_layout = QHBoxLayout(self._actions_widget)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(3)
        # Groups separated by a hairline, as in the design (§4.1, A1): source,
        # view mode, reference set, and the destructive «Сброс» apart from all of
        # them.  Without the separators the row read as one undifferentiated
        # line of equal buttons — the «визуал кнопок не как в концепте» remark.
        self._action_groups: list[tuple[QWidget, ...]] = [
            tuple(button for button in group if button is not None)
            for group in (
                (btn_open, self._btn_pacs),
                (self._btn_multiview, self._btn_presenter),
                (self._btn_references,),
                (btn_reset,),
            )
        ]
        self._action_separators: list[tuple[QWidget, tuple[QWidget, ...]]] = []
        self._separators_enabled = True
        for index, group in enumerate(self._action_groups):
            if index:
                # The hairline belongs to the group before it: it disappears
                # together with the group when a profile hides those actions.
                separator = self._action_separator()
                self._action_separators.append(
                    (separator, self._action_groups[index - 1]),
                )
                actions_layout.addWidget(separator)
            for button in group:
                actions_layout.addWidget(button)
        self._sync_action_separators()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(8)
        layout.addWidget(left, 1)
        layout.addWidget(self._actions_widget, 0)
        layout.addWidget(self._mode_switch, 0)
        layout.setStretch(0, 1)
        layout.setStretch(1, 0)
        layout.setStretch(2, 0)

        self._status_label.set_full_text("Ready")
        self.update_row_height()

    def _build_context_column(self, btn_heart_rate: QWidget | None) -> QWidget:
        """The left half of the line: patient, metrics, status, heart rate.

        The patient metrics of the study (height, weight, the derived BSA) are
        part of the patient line, not a strip of their own under it: the window
        used to stack three chrome rows before the image, and the mockup of the
        redesign keeps one (2026-10-27 list, item 5).  The editors themselves
        stay in the tool panel — this is only their host, so there is still one
        copy of the state.  The free space of the row belongs *after* the
        metrics, not between the patient and them: «Иванов · 164 см · 71 кг»
        reads as one phrase.
        """
        left = QWidget()
        left.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        left_layout = QHBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 12, 0)
        left_layout.setSpacing(8)
        left_layout.addWidget(self._study_label, 0)
        # Where the window mounts «Рост · Вес · ППТ» (see ``_fit_patient_metrics``
        # for why the host asks for no minimum width).
        self._metrics_host = _CollapsibleHost(self)
        self._metrics_host.setObjectName("patientMetricsToolbarHost")
        self._metrics_host.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        metrics_layout = QHBoxLayout(self._metrics_host)
        metrics_layout.setContentsMargins(0, 0, 0, 0)
        metrics_layout.setSpacing(8)
        left_layout.addWidget(self._metrics_host, 0)
        left_layout.addWidget(self._status_label, 0)
        left_layout.addWidget(self._progress_bar, 0)
        if btn_heart_rate is not None:
            left_layout.addWidget(btn_heart_rate, 0)
        left_layout.addStretch(1)
        return left

    def patient_metrics_host(self) -> QWidget:
        """The empty host the window mounts the patient editors into."""
        return self._metrics_host

    def _fit_action_separators(self) -> None:
        """Show the hairlines only while the row has room for them.

        The row never shrinks silently: when the window gets narrow the study
        label and the action captions give way first (spec §6).  The hairlines
        are decoration, so they are the first thing dropped — measured without
        them, otherwise showing and hiding would feed back into the measurement.
        """
        if not getattr(self, "_action_groups", None) or not hasattr(self, "_mode_switch"):
            return
        visible = [
            button for group in self._action_groups for button in group if button.isVisibleTo(self._actions_widget)
        ]
        if not visible:
            self.set_action_separators_visible(False)
            return
        needed = sum(button.sizeHint().width() for button in visible)
        needed += 3 * (len(visible) - 1)  # layout spacing inside the row
        needed += 12  # the three hairlines with the spacing they introduce
        needed += self._mode_switch.sizeHint().width() + 2 * 6 + 2 * 8
        self.set_action_separators_visible(self.width() >= needed)

    def _action_separator(self) -> QFrame:
        """A 1 px hairline between the action groups (styled from tokens)."""
        line = QFrame(self._actions_widget)
        line.setObjectName("systemBarSeparator")
        line.setFrameShape(QFrame.Shape.VLine)
        line.setFixedWidth(1)
        return line

    def set_action_separators_visible(self, visible: bool) -> None:
        """Hide the hairlines when the row is too narrow to afford them."""
        self._separators_enabled = bool(visible)
        self._sync_action_separators()

    def _sync_action_separators(self) -> None:
        """A hairline is shown only between two groups that are both visible."""
        for separator, group in getattr(self, "_action_separators", ()):
            separator.setVisible(
                self._separators_enabled and any(button.isVisibleTo(self._actions_widget) for button in group),
            )

    def resizeEvent(self, event: QResizeEvent) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._fit_action_separators()
        self._fit_patient_metrics()

    def _fit_patient_metrics(self) -> None:
        """Drop «Рост · Вес · ППТ» when the patient line has no room for them.

        The editors are two 76 px fields, two captions and the derived BSA —
        about 340 px.  The row used to give them a line of their own, where
        they could not widen the window; inside the line they would raise its
        minimum width by the same 340 px, and a 1366 × 768 screen at 150 %
        scaling (911 logical px) could no longer open the window at its own
        size.  The metrics are the first content of the row to give way — the
        patient, the actions and the mode switch stay — and they return as soon
        as the row has the room.  The values are still editable on the
        «Калькуляторы» tab, and the panel keeps its own copy of the state.
        """
        host = getattr(self, "_metrics_host", None)
        if host is None or host.layout() is None or host.layout().count() == 0:
            return
        if not hasattr(self, "_actions_widget") or not hasattr(self, "_mode_switch"):
            return
        # Measured from the size hints, never from the current geometry: the
        # row's minimum width follows the visibility, so measuring it would
        # make showing and hiding feed back into each other.
        actions = self._actions_widget.sizeHint().width() + self._mode_switch.sizeHint().width()
        margins = 24 + 8
        study = max(self._study_label.sizeHint().width(), 140)
        fits = self.width() >= actions + margins + study + host.sizeHint().width()
        if host.isVisibleTo(self) != fits:
            host.setVisible(fits)

    def update_row_height(self) -> None:
        """Keep the row at 42 px, and taller only when the font needs it (spec §4.1, Э4)."""
        height = max(PATIENT_LINE_HEIGHT_PX, line_height(self) + _PATIENT_LINE_PADDING_PX)
        self.setFixedHeight(height)

    def set_references_visible(self, visible: bool) -> None:
        """Hide «Справочник» (Presenter builds have no reference UI)."""
        self._btn_references.setVisible(visible)
        self._sync_action_separators()

    def set_multiview_checked(self, checked: bool) -> None:
        """Reflect the Multiview state on the «Сравнить» button."""
        self._btn_multiview.setChecked(checked)

    def report_mode(self) -> bool:
        """The state the switch shows: True — «Отчёт», False — «Изображения»."""
        return self._btn_mode_report.isChecked()

    def set_report_mode(self, report: bool) -> None:
        """Mirror the active tab's mode on the switch, without emitting it."""
        if self.report_mode() == bool(report):
            return
        with QSignalBlocker(self._btn_mode_report):
            self._btn_mode_report.setChecked(bool(report))
            self._btn_mode_images.setChecked(not report)

    def set_presenter_active(self, active: bool) -> None:
        """Checked state of the Presenter button (mirror running)."""
        from echo_personal_tool.infrastructure.i18n import tr

        if self._btn_presenter is None:
            return  # full profile — no Presenter UI
        with QSignalBlocker(self._btn_presenter):
            self._btn_presenter.setChecked(active)
        key = shortcut_label("presenter_toggle")
        tooltip_key = "presenter.tooltip_active" if active else "presenter.tooltip"
        self._btn_presenter.setToolTip(tr(tooltip_key, shortcut=key))

    def set_study_context(self, label: str, modality: str = "") -> None:
        del modality
        self._study_label.setText(label)
        self._study_label.setToolTip(label)

    def clear_study_context(self) -> None:
        from echo_personal_tool.infrastructure.i18n import tr

        self._study_label.setText(tr("system_bar.no_study"))
        self._study_label.setToolTip("")

    def reload_icons(self) -> None:
        """Reload all icons with current theme colors."""
        self._btn_open.setIcon(_load_icon("folder_open"))
        self._btn_pacs.setIcon(_load_icon("activity_dicom"))
        self._act_load_server.setIcon(_load_icon("cloud_download"))
        self._act_send_server.setIcon(_load_icon("activity_dicom"))
        self._btn_calibration.setIcon(_load_icon("tune"))
        self._btn_doppler_calibration.setIcon(_load_icon("show_chart"))
        self._btn_heart_rate.setIcon(_load_icon("heart_rate"))
        self._btn_references.setIcon(_load_icon("description"))
        self._btn_reset.setIcon(_load_icon("refresh"))
        self._btn_multiview.setIcon(_load_icon("two_panes"))
        if self._btn_presenter is not None:
            self._btn_presenter.setIcon(_load_icon("presenter"))

    def reload_text(self) -> None:
        """Update all button text and tooltips for current language."""
        from echo_personal_tool.infrastructure.i18n import tr

        self._btn_open.setText(tr("system_bar.open_folder"))
        self._btn_open.setToolTip(append_shortcut_hint(tr("system_bar.open_folder"), "open_folder"))
        self._btn_pacs.setText(tr("system_bar.pacs"))
        self._btn_pacs.setToolTip(tr("system_bar.pacs_tooltip"))
        self._act_load_server.setText(tr("system_bar.load_from_server"))
        self._act_send_server.setText(tr("system_bar.send_to_server"))
        self._btn_calibration.setText(tr("system_bar.calibration_bmode"))
        self._btn_calibration.setToolTip(append_shortcut_hint(tr("tools.calibrate_tip"), "calibration_toggle"))
        self._btn_doppler_calibration.setText(tr("system_bar.calibration_doppler"))
        self._btn_references.setText(tr("system_bar.references"))
        self._btn_references.setToolTip(tr("system_bar.references_tooltip"))
        self._btn_heart_rate.setText(tr("system_bar.heart_rate"))
        self._btn_heart_rate.setToolTip(tr("system_bar.heart_rate_tooltip"))
        self._btn_reset.setText(tr("system_bar.reset"))
        self._btn_multiview.setText(tr("system_bar.compare"))
        self._btn_multiview.setToolTip(tr("multiview.button_tooltip"))
        self._btn_multiview.setAccessibleName(tr("multiview.button_tooltip"))
        self._btn_mode_images.setText(tr("system_bar.mode_images"))
        self._btn_mode_report.setText(tr("system_bar.mode_report"))
        mode_tooltip = append_shortcut_hint(tr("system_bar.mode_tooltip"), "toggle_report_mode")
        self._btn_mode_images.setToolTip(mode_tooltip)
        self._btn_mode_report.setToolTip(mode_tooltip)
        if self._btn_presenter is not None:
            self._btn_presenter.setText(tr("presenter.button"))
            self._btn_presenter.setToolTip(tr("presenter.tooltip", shortcut=shortcut_label("presenter_toggle")))
        self._study_label.setText(tr("system_bar.no_study_loaded"))

    def set_status_message(self, message: str) -> None:
        self._status_label.set_full_text(message)

    def set_status_visible(self, visible: bool) -> None:
        """Show/hide the inline status text.

        The patient line keeps only the study/file name; load and function
        statuses live in the bottom status bar.
        """
        self._status_label.setVisible(visible)

    def show_decode_progress(self, current: int, total: int) -> None:
        self._progress_bar.show()
        self._progress_bar.setMaximum(total)
        self._progress_bar.setValue(current)

    def hide_decode_progress(self) -> None:
        self._progress_bar.hide()
        self._progress_bar.setValue(0)

    def _caption_double_clicked(self) -> None:
        """Maximize/restore on a double click of the empty row (spec §4.3)."""
        self.maximize_requested.emit()
