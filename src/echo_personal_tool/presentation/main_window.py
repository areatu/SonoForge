"""Main application window."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.domain.models import Contour, InstanceMetadata
from echo_personal_tool.presentation.doppler_widget import DopplerWidget
from echo_personal_tool.presentation.local_browser import LocalBrowserWidget
from echo_personal_tool.presentation.measurement_panel import MeasurementPanel
from echo_personal_tool.presentation.viewer_widget import ViewerWidget


class MainWindow(QMainWindow):
    """Phase 1 layout: browser | viewer | placeholder panel."""

    def __init__(self, controller: AppController | None = None) -> None:
        super().__init__()
        self.setWindowTitle("ECHO Personal Tool")
        self.resize(1280, 800)
        self._view_mode = "2d"
        self._lav_workflow_active = False

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
        self._view_doppler_button.clicked.connect(lambda: self.set_view_mode("doppler"))
        self._view_mode_group.addButton(self._view_doppler_button)
        toggle_row.addWidget(self._view_doppler_button)
        toggle_row.addStretch(1)
        center_layout.addLayout(toggle_row)

        self._view_stack = QStackedWidget()
        center_layout.addWidget(self._view_stack, stretch=1)

        self._viewer = ViewerWidget()
        self._viewer.play_pause_requested.connect(self._controller.toggle_playback)
        self._viewer.frame_selected.connect(self._controller.state_manager.set_frame)
        self._viewer.contour_completed.connect(self._on_contour_completed)
        self._viewer.contours_changed.connect(self._controller.on_contours_changed)
        self._viewer.linear_measurements_changed.connect(
            self._controller.on_linear_measurements_changed
        )
        self._viewer.calibration_completed.connect(self._controller.on_manual_calibration)
        self._controller.state_manager.state_changed.connect(self._viewer.set_state)
        self._view_stack.addWidget(self._viewer)

        self._doppler_widget = DopplerWidget()
        self._doppler_widget.markers_changed.connect(self._controller.on_doppler_markers_changed)
        self._view_stack.addWidget(self._doppler_widget)
        splitter.addWidget(center)

        self._measurement_panel = MeasurementPanel()
        self._controller.state_manager.state_changed.connect(
            self._measurement_panel.update_from_state
        )
        splitter.addWidget(self._measurement_panel)

        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 6)
        splitter.setStretchFactor(2, 2)
        self._measurement_panel.setMinimumWidth(300)
        root_layout.addWidget(splitter)

        self._browser.instance_selected.connect(self._on_instance_selected)
        self._viewer.set_state(self._controller.state_manager.snapshot)
        self._measurement_panel.update_from_state(self._controller.state_manager.snapshot)
        self._wire_measurement_tools()
        self._view_stack.setCurrentWidget(self._viewer)
        self._view_2d_button.setChecked(True)
        self._view_doppler_button.setChecked(False)
        self._viewer.installEventFilter(self)
        self._viewer._graphics.installEventFilter(self)
        self._viewer._view.installEventFilter(self)
        self._doppler_widget.installEventFilter(self)

        status = QStatusBar()
        self.setStatusBar(status)
        self._show_status(
            "Ready — open a study; use Measurement tools (right panel, above summary)"
        )
        self._install_shortcuts()

    def _install_shortcuts(self) -> None:
        """Window-level shortcuts that work when the viewer or browser has focus."""
        bindings: list[tuple[str, object]] = [
            ("Space", self._toggle_playback_shortcut),
            ("L", self._viewer.toggle_linear_caliper),
            ("C", self._start_manual_contour_shortcut),
            ("M", self._start_model_contour_shortcut),
            ("I", self._request_auto_segment_shortcut),
            ("Return", self._finish_active_tool_shortcut),
            ("Enter", self._finish_active_tool_shortcut),
            ("Escape", self._cancel_active_tool),
            ("Backspace", self._delete_current_contour),
            ("Delete", self._delete_current_contour),
        ]
        for sequence, handler in bindings:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(handler)

    def _toggle_playback_shortcut(self) -> None:
        if not self._controller.state_manager.snapshot.decode_in_progress:
            self._controller.toggle_playback()

    def _start_manual_contour_shortcut(self) -> None:
        if self._view_mode != "2d":
            return
        if self._viewer.start_contour():
            self._show_status("Manual contour: click MA septal, lateral, then apex")
        else:
            self._show_status("Load a frame first (or finish the active contour)")

    def _start_model_contour_shortcut(self) -> None:
        if self._view_mode != "2d":
            return
        start_mode = self._viewer.start_model_contour()
        if start_mode:
            self._viewer.clear_frame_overlay()
            self._viewer.append_frame_overlay("MBS-lite: MA septal → lateral → apex")
            self._show_status("MBS-lite: click MA septal, lateral, apex")
        else:
            self._show_status("Load a frame first (or finish the active contour)")

    def _request_auto_segment_shortcut(self) -> None:
        if (
            self._view_mode == "2d"
            and not self._controller.state_manager.snapshot.is_playing
        ):
            self._controller.request_auto_segment()

    def _finish_active_tool_shortcut(self) -> None:
        if self._view_mode == "doppler":
            if (
                self._doppler_widget.get_tool_mode() == "trace"
                and self._doppler_widget.finish_trace()
            ):
                return
        elif self._viewer.finish_calibration():
            return
        elif self._viewer.finish_contour():
            return

    def _cancel_active_tool(self) -> None:
        if self._view_mode == "doppler":
            self._doppler_widget.cancel_active_tool()
            return
        self._measurement_panel.tools.stop_es_prompt()
        self._viewer.cancel_active_tool()

    def _delete_current_contour(self) -> None:
        if self._view_mode != "2d":
            return
        if self._viewer.delete_contour_for_current_phase():
            self._controller.on_contours_changed(self._viewer.contours())
            self._show_status("Contour deleted")

    def _open_folder(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Select study folder")
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
            self._measurement_panel.tools.stop_es_prompt()
            self._doppler_widget.clear_measurements()
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

    def _wire_measurement_tools(self) -> None:
        tools = self._measurement_panel.tools
        tools.manual_simpson_requested.connect(self._on_manual_simpson_requested)
        tools.mbs_simpson_requested.connect(self._on_mbs_simpson_requested)
        tools.manual_simpson_requested.connect(self._on_es_button_pressed)
        tools.mbs_simpson_requested.connect(self._on_es_button_pressed)
        tools.lv2d_all_diastole_requested.connect(self._on_lv2d_all_diastole)
        tools.lv2d_es_requested.connect(self._on_lv2d_es)
        tools.la_diameter_requested.connect(self._on_la_diameter)
        tools.la_volume_requested.connect(self._on_la_volume)
        tools.rv_basal_requested.connect(self._on_rv_basal)
        tools.rv_tapse_requested.connect(self._on_rv_tapse)

    def _on_manual_simpson_requested(self, view: str, phase: str) -> None:
        if self._view_mode != "2d":
            self._show_status("Switch to 2D view for Simpson contour")
            return
        if phase == "ED":
            self._measurement_panel.tools.stop_es_prompt()
        if self._viewer.start_contour(phase=phase, view=view):
            self._viewer.clear_frame_overlay()
            self._viewer.append_frame_overlay(
                f"Manual {view} {phase}: MA septal → lateral → apex"
            )
            self._show_status(
                f"Manual Simpson {view} {phase}: click MA septal, lateral, apex"
            )
        else:
            self._show_status("Load a frame first or cancel the active tool (Esc)")

    def _on_mbs_simpson_requested(self, view: str, phase: str) -> None:
        if self._view_mode != "2d":
            self._show_status("Switch to 2D view for MBS-lite")
            return
        if phase == "ED":
            self._measurement_panel.tools.stop_es_prompt()
        if self._viewer.start_model_contour(phase=phase, view=view):
            self._viewer.clear_frame_overlay()
            self._viewer.append_frame_overlay(
                f"MBS-lite {view} {phase}: MA septal → lateral → apex"
            )
            self._show_status(
                f"MBS-lite {view} {phase}: click MA septal, lateral, apex"
            )
        else:
            self._show_status("Load a frame first or cancel the active tool (Esc)")

    def _on_es_button_pressed(self, view: str, phase: str) -> None:
        if phase == "ES":
            self._measurement_panel.tools.stop_es_prompt()

    def _on_lv2d_all_diastole(self) -> None:
        if self._view_mode != "2d":
            self._show_status("Switch to 2D view for LV-2D measurements")
            return
        if self._viewer.start_linear_caliper_sequence(("IVSd", "LVEDD", "LVPWd")):
            self._viewer.clear_frame_overlay()
            self._viewer.append_frame_overlay("LV diastole: IVSd → LVEDD → LVPWd")
            self._show_status("LV diastole: place IVSd, then LVEDD, then LVPWd")
        else:
            self._show_status("Load a frame first")

    def _on_lv2d_es(self) -> None:
        if self._view_mode != "2d":
            self._show_status("Switch to 2D view for LV-2D measurements")
            return
        if self._viewer.start_linear_caliper_for("LVESD"):
            self._show_status("LV systole: place LVESD caliper")
        else:
            self._show_status("Load a frame first")

    def _on_la_diameter(self) -> None:
        if self._view_mode != "2d":
            return
        if self._viewer.start_linear_caliper_for("LA"):
            self._show_status("Left atrium: place AP diameter caliper")
        else:
            self._show_status("Load a frame first")

    def _on_la_volume(self) -> None:
        if self._view_mode != "2d":
            return
        self._lav_workflow_active = True
        if self._viewer.start_closed_contour(chamber="LA", phase="ES"):
            self._viewer.clear_frame_overlay()
            self._viewer.append_frame_overlay("LAV: trace LA border → Enter → length")
            self._show_status("LAV: trace LA border, press Enter, then place length")
        else:
            self._lav_workflow_active = False
            self._show_status("Load a frame first")

    def _on_contour_completed(self, contour: object) -> None:
        if not isinstance(contour, Contour):
            return
        if contour.chamber.upper() == "LA" and self._lav_workflow_active:
            self._lav_workflow_active = False
            if self._viewer.start_linear_caliper_for("LAL"):
                self._show_status("LAV: place LA length caliper")
            return
        if contour.chamber.upper() != "LV":
            return

        extra_lines: tuple[str, ...] = ()
        if contour.phase.upper() == "ED":
            mode = "mbs" if contour.source == "model" else "manual"
            view_label = "4C" if contour.view.upper() == "A4C" else "2C"
            es_name = "ESV Auto" if mode == "mbs" else "Systole"
            extra_lines = (
                f"Перейдите на кадр систолы и нажмите {es_name} ({view_label})",
            )
            self._measurement_panel.tools.start_es_prompt(mode, view_label)
            status = (
                f"Перейдите на кадр систолы и нажмите {es_name} ({view_label})"
            )
            if (
                self._controller.state_manager.snapshot.effective_pixel_spacing is None
            ):
                status += " · нет PixelSpacing (K — калибровка, px / px³)"
            self._show_status(status)
        elif contour.phase.upper() == "ES":
            self._measurement_panel.tools.stop_es_prompt()

        self._viewer._refresh_lv_frame_overlay(extra_lines=extra_lines)

    def _on_rv_basal(self) -> None:
        if self._view_mode != "2d":
            return
        if self._viewer.start_linear_caliper_for("RV basal"):
            self._show_status("RV: place basal diameter caliper")
        else:
            self._show_status("Load a frame first")

    def _on_rv_tapse(self) -> None:
        if self._view_mode != "2d":
            return
        if self._viewer.start_linear_caliper_for("TAPSE"):
            self._show_status("RV: place TAPSE caliper")
        else:
            self._show_status("Load a frame first")

    def eventFilter(self, watched: object, event: QEvent) -> bool:  # type: ignore[override]
        if event.type() == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
            if watched in (
                self._viewer,
                self._viewer._graphics,
                self._viewer._view,
                self._doppler_widget,
            ):
                if self._handle_key_press(event):
                    return True
        return super().eventFilter(watched, event)

    def event(self, event) -> bool:  # type: ignore[override]
        if (
            event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Tab
            and self._view_mode == "2d"
        ):
            self._viewer.cycle_caliper_label()
            event.accept()
            return True
        return super().event(event)

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
        if self._handle_key_press(event):
            return
        super().keyPressEvent(event)

    def _handle_key_press(self, event: QKeyEvent) -> bool:
        if event.key() == Qt.Key.Key_Space:
            if not self._controller.state_manager.snapshot.decode_in_progress:
                self._controller.toggle_playback()
            event.accept()
            return True
        if event.key() == Qt.Key.Key_L and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            self._viewer.toggle_linear_caliper()
            event.accept()
            return True
        if event.key() == Qt.Key.Key_K and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            if self._view_mode == "2d":
                self._viewer.toggle_calibration_caliper()
                if self._viewer.is_calibration_active:
                    self._show_status(
                        "Калибровка: линия по шкале глубины → Enter (Escape — отмена)"
                    )
            event.accept()
            return True
        if (
            event.key() == Qt.Key.Key_K
            and event.modifiers() == Qt.KeyboardModifier.ShiftModifier
            and self._view_mode == "2d"
        ):
            self._controller.clear_manual_calibration()
            event.accept()
            return True
        if event.key() == Qt.Key.Key_Tab and self._view_mode == "2d":
            self._viewer.cycle_caliper_label()
            event.accept()
            return True
        if event.key() == Qt.Key.Key_C and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            if self._viewer.start_contour():
                self._show_status("Manual contour: click MA septal, lateral, then arc")
            else:
                self._show_status("Load a frame first (or finish the active contour)")
            event.accept()
            return True
        if (
            event.key() == Qt.Key.Key_M
            and event.modifiers() == Qt.KeyboardModifier.NoModifier
            and self._view_mode == "2d"
        ):
            if self._viewer.start_model_contour():
                self._show_status("MBS-lite: click MA septal, lateral, then apex")
            else:
                self._show_status("Load a frame first (or finish the active contour)")
            event.accept()
            return True
        if (
            event.key() == Qt.Key.Key_R
            and event.modifiers() == Qt.KeyboardModifier.NoModifier
            and self._view_mode == "2d"
        ):
            if self._viewer.refine_active_open_contour():
                self._controller.on_contours_changed(self._viewer.contours())
                self._show_status("Уточнение границ (active contour)")
            else:
                self._show_status("Нет LV open-arc контура на текущем кадре")
            event.accept()
            return True
        if (
            event.key() == Qt.Key.Key_I
            and event.modifiers() == Qt.KeyboardModifier.NoModifier
            and self._view_mode == "2d"
            and not self._controller.state_manager.snapshot.is_playing
        ):
            self._controller.request_auto_segment()
            event.accept()
            return True
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self._view_mode == "doppler":
                is_trace = self._doppler_widget.get_tool_mode() == "trace"
                if is_trace and self._doppler_widget.finish_trace():
                    event.accept()
                    return True
            elif self._viewer.finish_calibration():
                event.accept()
                return True
            elif self._viewer.finish_contour():
                event.accept()
                return True
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            if self._view_mode == "2d" and self._viewer.delete_contour_for_current_phase():
                self._controller.on_contours_changed(self._viewer.contours())
                self._show_status("Contour deleted")
            event.accept()
            return True
        if event.key() == Qt.Key.Key_Escape:
            self._cancel_active_tool()
            event.accept()
            return True
        if self._view_mode == "doppler" and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            if event.key() == Qt.Key.Key_M:
                self._doppler_widget.set_tool_mode("peak")
                event.accept()
                return True
            if event.key() == Qt.Key.Key_T:
                self._doppler_widget.set_tool_mode("interval")
                event.accept()
                return True
            if event.key() == Qt.Key.Key_V:
                self._doppler_widget.set_tool_mode("trace")
                event.accept()
                return True
        return False
