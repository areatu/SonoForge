"""The patient line under the window title bar (42 px, UI-1 PR-3).

Spec §4.1 («Строка пациента»): one 42 px row over every layout. The study /
patient label and the heart rate on the left; the study actions on the right —
«Открыть», «PACS ▾» (load / send), «Сравнить» (Multiview), «Презентация»
(Presenter, Lite build only) and «Справочник» (references, the former
«Нормативы»).

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

from pathlib import Path

from PySide6.QtCore import QSignalBlocker, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
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

_ICON_DIR = Path(__file__).resolve().parent.parent / "resources" / "icons"

#: Height of the patient line at 100 % (spec §4.1). It grows with the font.
PATIENT_LINE_HEIGHT_PX = 42
#: Vertical room kept around the controls of the row when the font is large.
_PATIENT_LINE_PADDING_PX = 16


def _icon_dir() -> Path:
    import sys

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass is not None:
        return Path(meipass) / "echo_personal_tool" / "resources" / "icons"
    return _ICON_DIR


def _load_icon(name: str) -> QIcon:
    from echo_personal_tool.presentation.dark_theme import get_theme_tokens

    svg_path = _icon_dir() / f"{name}.svg"
    if svg_path.is_file():
        svg_text = svg_path.read_text(encoding="utf-8")
        # The glyph takes the primary text colour of the active theme (UI-0,
        # PR-3): a role, not a colour and not a legacy palette key.
        color = get_theme_tokens()["text.1"]
        svg_text = svg_text.replace("currentColor", color)
        pixmap = QPixmap()
        pixmap.loadFromData(svg_text.encode("utf-8"))
        if not pixmap.isNull():
            return QIcon(pixmap)
    return QIcon()


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


class SystemBar(CaptionDragMixin, QWidget):
    """The patient line: study context on the left, study actions on the right."""

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

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("systemBar")

        from echo_personal_tool.infrastructure.i18n import tr
        from echo_personal_tool.infrastructure.profile import capabilities_for

        self._profile_capabilities = capabilities_for()
        self._study_label = QLabel(tr("system_bar.no_study"))
        self._study_label.setMinimumWidth(120)
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
        ):
            if btn is not None:
                HoverButtonMixin.install(btn)

        left = QWidget()
        left.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        left_layout = QHBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 12, 0)
        left_layout.setSpacing(8)
        left_layout.addWidget(self._study_label, 1)
        left_layout.addWidget(self._status_label, 0)
        left_layout.addWidget(self._progress_bar, 0)
        left_layout.addWidget(btn_heart_rate, 0)

        self._actions_widget = QWidget()
        self._actions_widget.setSizePolicy(
            QSizePolicy.Policy.Maximum,
            QSizePolicy.Policy.Preferred,
        )
        actions_layout = QHBoxLayout(self._actions_widget)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(6)
        for button in (
            btn_open,
            self._btn_pacs,
            self._btn_multiview,
            self._btn_presenter,
            self._btn_references,
            btn_reset,
        ):
            if button is not None:
                actions_layout.addWidget(button)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)
        layout.addWidget(left, 1)
        layout.addWidget(self._actions_widget, 0)
        layout.setStretch(0, 1)
        layout.setStretch(1, 0)

        self._status_label.set_full_text("Ready")
        self.update_row_height()

    def update_row_height(self) -> None:
        """Keep the row at 42 px, and taller only when the font needs it (spec §4.1, Э4)."""
        height = max(PATIENT_LINE_HEIGHT_PX, line_height(self) + _PATIENT_LINE_PADDING_PX)
        self.setFixedHeight(height)

    def set_references_visible(self, visible: bool) -> None:
        """Hide «Справочник» (Presenter builds have no reference UI)."""
        self._btn_references.setVisible(visible)

    def set_multiview_checked(self, checked: bool) -> None:
        """Reflect the Multiview state on the «Сравнить» button."""
        self._btn_multiview.setChecked(checked)

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
