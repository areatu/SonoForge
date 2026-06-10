"""Main application window."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.domain.models import InstanceMetadata
from echo_personal_tool.presentation.local_browser import LocalBrowserWidget
from echo_personal_tool.presentation.viewer_widget import ViewerWidget


class MainWindow(QMainWindow):
    """Phase 1 layout: browser | viewer | placeholder panel."""

    def __init__(self, controller: AppController | None = None) -> None:
        super().__init__()
        self.setWindowTitle("ECHO Personal Tool")
        self.resize(1280, 800)

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
        left_layout.addWidget(self._browser, stretch=1)
        splitter.addWidget(left)

        self._viewer = ViewerWidget()
        self._viewer.play_pause_requested.connect(self._controller.toggle_playback)
        self._viewer.frame_selected.connect(self._controller.state_manager.set_frame)
        self._controller.state_manager.state_changed.connect(self._viewer.set_state)
        splitter.addWidget(self._viewer)

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
        self._viewer.show_frame(np.asarray(pixels))

    def _on_frame_load_failed(self, message: str) -> None:
        QMessageBox.warning(self, "Load failed", message)

    def _show_status(self, message: str) -> None:
        if self.statusBar():
            self.statusBar().showMessage(message)

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
        super().keyPressEvent(event)
