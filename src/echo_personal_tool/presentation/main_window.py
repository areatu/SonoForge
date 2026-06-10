"""Main application window."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStatusBar,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.domain.models import InstanceMetadata
from echo_personal_tool.presentation.doppler_widget import DopplerWidget
from echo_personal_tool.presentation.local_browser import LocalBrowserWidget
from echo_personal_tool.presentation.viewer_widget import ViewerWidget


class MainWindow(QMainWindow):
    """Phase 1 layout: browser | viewer | placeholder panel."""

    def __init__(self, controller: AppController | None = None) -> None:
        super().__init__()
        self.setWindowTitle("ECHO Personal Tool")
        self.resize(1280, 800)
        self._view_mode = "2d"

        self._controller = controller or AppController()
        self._controller.studies_loaded.connect(self._on_studies_loaded)
        self._controller.scan_failed.connect(self._on_scan_failed)
        self._controller.frame_loaded.connect(self._on_frame_loaded)
        self._controller.frame_load_failed.connect(self._on_frame_load_failed)
        self._controller.status_message.connect(self._show_status)

        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        self._open_button = QPushButton("Open folder…")
        self._open_button.clicked.connect(self._open_folder)
        left_layout.addWidget(self._open_button)
        self._browser = LocalBrowserWidget()
        self._browser.set_thumbnail_loader(self._controller.load_thumbnail)
        self._controller.thumbnail_loaded.connect(self._browser.set_thumbnail)
        left_layout.addWidget(self._browser, stretch=1)
        splitter.addWidget(left)

        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)

        toggle_row = QHBoxLayout()
        self._view_mode_group = QButtonGroup(self)
        self._view_mode_group.setExclusive(True)
        self._view_2d_button = QPushButton("2D")
        self._view_2d_button.setCheckable(True)
        self._view_2d_button.clicked.connect(lambda: self.set_view_mode("2d"))
        self._view_mode_group.addButton(self._view_2d_button)
        toggle_row.addWidget(self._view_2d_button)
        self._view_doppler_button = QPushButton("Doppler")
        self._view_doppler_button.setCheckable(True)
        self._view_doppler_button.clicked.connect(
            lambda: self.set_view_mode("doppler")
        )
        self._view_mode_group.addButton(self._view_doppler_button)
        toggle_row.addWidget(self._view_doppler_button)
        toggle_row.addStretch(1)
        center_layout.addLayout(toggle_row)

        self._view_stack = QStackedWidget()
        center_layout.addWidget(self._view_stack, stretch=1)

        self._viewer = ViewerWidget()
        self._viewer.play_pause_requested.connect(self._controller.toggle_playback)
        self._viewer.frame_selected.connect(self._controller.state_manager.set_frame)
        self._controller.state_manager.state_changed.connect(self._viewer.set_state)
        self._view_stack.addWidget(self._viewer)

        self._doppler_widget = DopplerWidget()
        self._view_stack.addWidget(self._doppler_widget)
        splitter.addWidget(center)

        right = QLabel("Measurements\n(Phase 1 — Sprint 4)")
        right.setAlignment(Qt.AlignmentFlag.AlignTop)
        right.setMinimumWidth(180)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 6)
        splitter.setStretchFactor(2, 2)
        root_layout.addWidget(splitter)

        self._browser.instance_selected.connect(self._on_instance_selected)
        self._viewer.set_state(self._controller.state_manager.snapshot)
        self._view_stack.setCurrentWidget(self._viewer)
        self._view_2d_button.setChecked(True)
        self._view_doppler_button.setChecked(False)

        status = QStatusBar()
        self.setStatusBar(status)
        self._show_status("Ready — open a DICOM folder")

    def _open_folder(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Select DICOM folder")
        if not directory:
            return
        log_path = Path(directory) / "scan_errors.log"
        self._controller.open_folder(Path(directory), error_log_path=log_path)

    def _on_studies_loaded(self, studies: object) -> None:
        self._browser.populate(list(studies))  # type: ignore[arg-type]

    def _on_scan_failed(self, message: str) -> None:
        QMessageBox.warning(self, "Scan failed", message)

    def _on_instance_selected(self, instance: object) -> None:
        if isinstance(instance, InstanceMetadata):
            self._controller.load_instance(instance)

    def _on_frame_loaded(self, pixels: object) -> None:
        image = np.asarray(pixels)
        if self._view_mode == "doppler":
            self._doppler_widget.show_spectrogram(image)
            return
        self._viewer.show_frame(image)

    def _on_frame_load_failed(self, message: str) -> None:
        QMessageBox.warning(self, "Load failed", message)

    def _show_status(self, message: str) -> None:
        if self.statusBar():
            self.statusBar().showMessage(message)

    def set_view_mode(self, mode: str) -> None:
        mode_name = mode.strip().lower()
        if mode_name not in {"2d", "doppler"}:
            raise ValueError(f"Unsupported view mode: {mode}")

        if mode_name == "doppler" and self._controller.state_manager.snapshot.is_playing:
            self._controller.set_playing(False)

        self._view_mode = mode_name
        if mode_name == "doppler":
            self._view_stack.setCurrentWidget(self._doppler_widget)
            self._view_2d_button.setChecked(False)
            self._view_doppler_button.setChecked(True)
            if self._viewer._current_frame is not None:
                self._doppler_widget.show_spectrogram(self._viewer._current_frame)
            self._show_status("Doppler view active")
        else:
            self._view_stack.setCurrentWidget(self._viewer)
            self._view_2d_button.setChecked(True)
            self._view_doppler_button.setChecked(False)
            self._show_status("2D viewer active")

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.key() == Qt.Key.Key_Space:
            self._controller.toggle_playback()
            event.accept()
            return
        if event.key() == Qt.Key.Key_D and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            self._controller.mark_ed()
            event.accept()
            return
        if event.key() == Qt.Key.Key_S and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            self._controller.mark_es()
            event.accept()
            return
        if event.key() == Qt.Key.Key_L and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            self._viewer.toggle_linear_caliper()
            event.accept()
            return
        if event.key() == Qt.Key.Key_C and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            self._viewer.start_contour()
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self._view_mode == "doppler":
                if self._doppler_widget.get_tool_mode() == "trace" and self._doppler_widget.finish_trace():
                    event.accept()
                    return
            elif self._viewer.finish_contour():
                event.accept()
                return
        if event.key() == Qt.Key.Key_Escape:
            if self._view_mode == "doppler":
                self._doppler_widget.cancel_active_tool()
                event.accept()
                return
            self._viewer.cancel_active_tool()
            event.accept()
            return
        if self._view_mode == "doppler" and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            if event.key() == Qt.Key.Key_M:
                self._doppler_widget.set_tool_mode("peak")
                event.accept()
                return
            if event.key() == Qt.Key.Key_T:
                self._doppler_widget.set_tool_mode("interval")
                event.accept()
                return
            if event.key() == Qt.Key.Key_V:
                self._doppler_widget.set_tool_mode("trace")
                event.accept()
                return
        super().keyPressEvent(event)
