"""Top system bar: study context, global actions."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QSize, QPoint
from PySide6.QtGui import QResizeEvent, QIcon, QPixmap, QPainter, QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from echo_personal_tool.presentation.ui_animations import HoverButtonMixin

_ICON_DIR = Path(__file__).resolve().parent.parent / "resources" / "icons"


def _icon_dir() -> Path:
    import sys
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass is not None:
        return Path(meipass) / "echo_personal_tool" / "resources" / "icons"
    return _ICON_DIR


def _load_icon(name: str) -> QIcon:
    from echo_personal_tool.presentation.echopac_theme import get_theme_palette
    svg_path = _icon_dir() / f"{name}.svg"
    if svg_path.is_file():
        svg_text = svg_path.read_text(encoding="utf-8")
        color = get_theme_palette().get("text", "#f1f5f9")
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


class SystemBar(QWidget):
    """EchoPac-style header above the main splitter."""

    open_folder_requested = Signal()
    load_from_server_requested = Signal()
    send_to_server_requested = Signal()
    reset_session_requested = Signal()
    caliper_requested = Signal()
    calibration_requested = Signal()
    doppler_calibration_requested = Signal()
    settings_requested = Signal()
    references_requested = Signal()
    minimize_requested = Signal()
    maximize_requested = Signal()
    close_requested = Signal()
    layout_customize_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("systemBar")

        from echo_personal_tool.infrastructure.i18n import tr
        self._study_label = QLabel(tr("system_bar.no_study"))
        self._study_label.setMinimumWidth(120)
        self._study_label.setSizePolicy(
            QSizePolicy.Policy.Maximum,
            QSizePolicy.Policy.Preferred,
        )

        self._status_label = _ElidingStatusLabel()

        self._progress_bar = QProgressBar()
        self._progress_bar.setMaximumWidth(160)
        self._progress_bar.setMaximumHeight(16)
        self._progress_bar.setTextVisible(True)
        self._progress_bar.hide()

        btn_open = QPushButton("Open folder…")
        btn_open.setIcon(_load_icon("folder_open"))
        btn_open.clicked.connect(self.open_folder_requested.emit)
        self._btn_open = btn_open

        btn_load_server = QPushButton("Загрузить с сервера…")
        btn_load_server.setIcon(_load_icon("cloud_download"))
        btn_load_server.clicked.connect(self.load_from_server_requested.emit)
        self._btn_load_server = btn_load_server

        btn_send_server = QPushButton("Send to server…")
        btn_send_server.setIcon(_load_icon("activity_dicom"))
        btn_send_server.clicked.connect(self.send_to_server_requested.emit)
        self._btn_send_server = btn_send_server

        self._btn_settings = QPushButton(tr("system_bar.settings"))
        self._btn_settings.setIcon(_load_icon("settings"))
        self._btn_settings.setToolTip("Параметры измерений и отображения")
        self._btn_settings.clicked.connect(self.settings_requested.emit)

        btn_caliper = QPushButton("Caliper")
        btn_caliper.setIcon(_load_icon("straighten"))
        btn_caliper.setToolTip("Linear distance (Dist1, Dist2, …)")
        btn_caliper.clicked.connect(self.caliper_requested.emit)
        self._btn_caliper = btn_caliper

        btn_calibration = QPushButton("Calibration B-mode")
        btn_calibration.setIcon(_load_icon("tune"))
        btn_calibration.setToolTip("B-mode pixel spacing: depth scale line")
        btn_calibration.clicked.connect(self.calibration_requested.emit)
        self._btn_calibration = btn_calibration

        btn_doppler_calibration = QPushButton("Calibration Doppler")
        btn_doppler_calibration.setIcon(_load_icon("show_chart"))
        btn_doppler_calibration.setToolTip(
            "Doppler spectrogram: ROI → baseline → velocity scale"
        )
        btn_doppler_calibration.clicked.connect(self.doppler_calibration_requested.emit)
        self._btn_doppler_calibration = btn_doppler_calibration

        self._btn_references = QPushButton(tr("system_bar.references"))
        self._btn_references.setIcon(_load_icon("description"))
        self._btn_references.setToolTip("Справочник нормативных значений ASE")
        self._btn_references.clicked.connect(self.references_requested.emit)

        btn_reset = QPushButton("Reset")
        btn_reset.setIcon(_load_icon("refresh"))
        btn_reset.setObjectName("resetButton")
        btn_reset.clicked.connect(self.reset_session_requested.emit)
        self._btn_reset = btn_reset

        self._btn_layout = QPushButton()
        self._btn_layout.setIcon(_load_icon("layout"))
        self._btn_layout.setObjectName("layoutButton")
        self._btn_layout.setToolTip("Customize Layout")
        self._btn_layout.clicked.connect(self.layout_customize_requested.emit)

        # Window control buttons
        self._btn_minimize = QPushButton()
        self._btn_minimize.setIcon(_load_icon("minimize"))
        self._btn_minimize.setObjectName("minimizeButton")
        self._btn_minimize.setToolTip(tr("system_bar.minimize"))
        self._btn_minimize.clicked.connect(self.minimize_requested.emit)

        self._btn_maximize = QPushButton()
        self._btn_maximize.setIcon(_load_icon("maximize"))
        self._btn_maximize.setObjectName("maximizeButton")
        self._btn_maximize.setToolTip(tr("system_bar.maximize"))
        self._btn_maximize.clicked.connect(self.maximize_requested.emit)

        self._btn_close = QPushButton()
        self._btn_close.setIcon(_load_icon("close"))
        self._btn_close.setObjectName("closeButton")
        self._btn_close.setToolTip(tr("system_bar.close"))
        self._btn_close.clicked.connect(self.close_requested.emit)

        # Install hover lerp mixin on all buttons
        for btn in (
            btn_open, btn_load_server, btn_send_server,
            self._btn_settings, btn_caliper, btn_calibration,
            btn_doppler_calibration, self._btn_references, btn_reset,
            self._btn_layout, self._btn_minimize, self._btn_maximize,
            self._btn_close,
        ):
            HoverButtonMixin.install(btn)

        left = QWidget()
        left.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        left_layout = QHBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 12, 0)
        left_layout.setSpacing(8)
        left_layout.addWidget(btn_open, 0)
        left_layout.addWidget(btn_load_server, 0)
        left_layout.addWidget(btn_send_server, 0)
        left_layout.addWidget(self._study_label, 0)
        left_layout.addWidget(self._status_label, 1)
        left_layout.addWidget(self._progress_bar, 0)

        self._actions_widget = QWidget()
        self._actions_widget.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Preferred,
        )
        actions_layout = QHBoxLayout(self._actions_widget)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(6)
        for button in (
            self._btn_settings,
            btn_caliper,
            btn_calibration,
            btn_doppler_calibration,
            self._btn_references,
            btn_reset,
            self._btn_layout,
        ):
            actions_layout.addWidget(button)

        self._window_controls = QWidget()
        self._window_controls.setObjectName("windowControls")
        self._window_controls.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Preferred,
        )
        window_controls_layout = QHBoxLayout(self._window_controls)
        window_controls_layout.setContentsMargins(0, 0, 0, 0)
        window_controls_layout.setSpacing(0)
        window_controls_layout.addWidget(self._btn_minimize)
        window_controls_layout.addWidget(self._btn_maximize)
        window_controls_layout.addWidget(self._btn_close)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 6, 0, 6)
        layout.setSpacing(8)
        layout.addWidget(left, 1)
        layout.addWidget(self._actions_widget, 0)
        layout.addWidget(self._window_controls, 0)
        layout.setStretch(0, 1)
        layout.setStretch(1, 0)
        layout.setStretch(2, 0)

        self._status_label.set_full_text("Ready")

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
        self._btn_load_server.setIcon(_load_icon("cloud_download"))
        self._btn_send_server.setIcon(_load_icon("activity_dicom"))
        self._btn_settings.setIcon(_load_icon("settings"))
        self._btn_caliper.setIcon(_load_icon("straighten"))
        self._btn_calibration.setIcon(_load_icon("tune"))
        self._btn_doppler_calibration.setIcon(_load_icon("show_chart"))
        self._btn_references.setIcon(_load_icon("description"))
        self._btn_reset.setIcon(_load_icon("refresh"))
        self._btn_layout.setIcon(_load_icon("layout"))
        self._btn_minimize.setIcon(_load_icon("minimize"))
        self._btn_maximize.setIcon(_load_icon("maximize"))
        self._btn_close.setIcon(_load_icon("close"))

    def reload_text(self) -> None:
        """Update all button text and tooltips for current language."""
        from echo_personal_tool.infrastructure.i18n import tr
        self._btn_open.setText(tr("system_bar.open_folder"))
        self._btn_load_server.setText(tr("system_bar.load_from_server"))
        self._btn_send_server.setText(tr("system_bar.send_to_server"))
        self._btn_settings.setText(tr("system_bar.settings"))
        self._btn_settings.setToolTip(tr("system_bar.settings"))
        self._btn_caliper.setText(tr("system_bar.caliper"))
        self._btn_calibration.setText(tr("system_bar.calibration_bmode"))
        self._btn_doppler_calibration.setText(tr("system_bar.calibration_doppler"))
        self._btn_references.setText(tr("system_bar.references"))
        self._btn_references.setToolTip(tr("system_bar.references"))
        self._btn_reset.setText(tr("system_bar.reset"))
        self._btn_minimize.setToolTip(tr("system_bar.minimize"))
        self._btn_maximize.setToolTip(tr("system_bar.maximize"))
        self._btn_close.setToolTip(tr("system_bar.close"))
        self._study_label.setText(tr("system_bar.no_study_loaded"))

    def set_status_message(self, message: str) -> None:
        self._status_label.set_full_text(message)

    def show_decode_progress(self, current: int, total: int) -> None:
        self._progress_bar.show()
        self._progress_bar.setMaximum(total)
        self._progress_bar.setValue(current)

    def hide_decode_progress(self) -> None:
        self._progress_bar.hide()
        self._progress_bar.setValue(0)

    def update_maximize_button(self, is_maximized: bool) -> None:
        from echo_personal_tool.infrastructure.i18n import tr
        if is_maximized:
            self._btn_maximize.setIcon(_load_icon("restore"))
            self._btn_maximize.setToolTip(tr("system_bar.restore"))
        else:
            self._btn_maximize.setIcon(_load_icon("maximize"))
            self._btn_maximize.setToolTip(tr("maximize"))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            window = self.window()
            if window.isMaximized():
                return
            self._drag_pos = event.globalPosition().toPoint() - window.pos()

    def mouseMoveEvent(self, event) -> None:
        if (
            hasattr(self, "_drag_pos")
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            self.window().move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.maximize_requested.emit()
