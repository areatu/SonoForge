"""Main application window."""

from __future__ import annotations

import logging
from pathlib import Path
from time import perf_counter

import numpy as np
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.domain.models import Contour, InstanceMetadata
from echo_personal_tool.domain.models.viewer_state import ViewerState
from echo_personal_tool.presentation.doppler_widget import DopplerWidget
from echo_personal_tool.presentation.local_browser import LocalBrowserWidget
from echo_personal_tool.presentation.measurement_action import MeasurementAction
from echo_personal_tool.presentation.measurement_panel import MeasurementPanel
from echo_personal_tool.presentation.measurement_worksheet import MeasurementWorksheet
from echo_personal_tool.presentation.system_bar import SystemBar
from echo_personal_tool.presentation.viewer_widget import ViewerWidget

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Phase 1 layout: browser | viewer | placeholder panel."""

    def __init__(self, controller: AppController | None = None) -> None:
        super().__init__()
        self.setWindowTitle("ECHO Personal Tool")
        self.resize(1280, 800)
        self._view_mode = "2d"
        self._click_to_frame_started_at: float | None = None
        self._lav_bi_active = False

        self._controller = controller or AppController()
        self._controller.studies_loaded.connect(self._on_studies_loaded)
        self._controller.scan_failed.connect(self._on_scan_failed)
        self._controller.frame_loaded.connect(self._on_frame_loaded)
        self._controller.frame_load_failed.connect(self._on_frame_load_failed)
        self._controller.status_message.connect(self._show_status)

        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._system_bar = SystemBar()
        root_layout.addWidget(self._system_bar)

        content = QWidget()
        root_layout.addWidget(content, stretch=1)
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(4, 4, 4, 4)
        self._browser = LocalBrowserWidget()
        self._browser.set_thumbnail_loader(self._controller.load_thumbnail)
        self._controller.thumbnail_loaded.connect(self._browser.set_thumbnail)
        left_layout.addWidget(self._browser, stretch=3)

        self._worksheet = MeasurementWorksheet()
        left_layout.addWidget(self._worksheet, stretch=2)
        splitter.addWidget(left)

        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)

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
        self._measurement_panel.setMinimumWidth(280)
        content_layout.addWidget(splitter)

        self._browser.instance_selected.connect(self._on_instance_selected)
        self._viewer.set_state(self._controller.state_manager.snapshot)
        self._measurement_panel.update_from_state(self._controller.state_manager.snapshot)
        self._sync_worksheet_from_state(self._controller.state_manager.snapshot)
        self._wire_ui()
        self._view_stack.setCurrentWidget(self._viewer)
        self._viewer.installEventFilter(self)
        self._viewer._graphics.installEventFilter(self)
        self._viewer._view.installEventFilter(self)
        self._doppler_widget.installEventFilter(self)

        status = QStatusBar()
        self.setStatusBar(status)
        self._show_status("Ready — open a study folder; use worksheet (left) for measurements")
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
        elif self._viewer.finish_contour():
            return

    def _cancel_active_tool(self) -> None:
        if self._view_mode == "doppler":
            self._doppler_widget.cancel_active_tool()
            return
        self._worksheet.stop_es_prompt()
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
        study_list = list(studies)  # type: ignore[arg-type]
        populate_started_at = perf_counter()
        self._browser.populate(study_list)
        populate_elapsed_ms = (perf_counter() - populate_started_at) * 1000.0
        logger.info(
            "tree_populate_done studies=%d duration_ms=%.2f",
            len(study_list),
            populate_elapsed_ms,
        )
        self._browser.request_visible_previews()

    def _on_scan_failed(self, message: str) -> None:
        QMessageBox.warning(self, "Scan failed", message)

    def _on_instance_selected(self, instance: object) -> None:
        if isinstance(instance, InstanceMetadata):
            self._click_to_frame_started_at = perf_counter()
            self._worksheet.stop_es_prompt()
            self._doppler_widget.clear_measurements()
            label = instance.series_description or instance.sop_instance_uid
            self._system_bar.set_study_context(label, instance.modality or "US")
            self._controller.load_instance(instance)

    def _on_frame_loaded(self, pixels: object) -> None:
        if self._click_to_frame_started_at is not None:
            elapsed_ms = (perf_counter() - self._click_to_frame_started_at) * 1000.0
            logger.info("click_to_frame_loaded duration_ms=%.2f", elapsed_ms)
            self._click_to_frame_started_at = None
        image = np.asarray(pixels)
        if self._view_mode == "doppler":
            self._doppler_widget.show_spectrogram(image)
            return
        self._viewer.show_frame(image)
        if self._controller.needs_manual_calibration():
            if self._viewer.start_calibration_caliper():
                self._show_status(
                    "Калибровка: 1-й клик — верхняя метка, 2-й — нижняя (Escape — отмена)"
                )

    def _on_frame_load_failed(self, message: str) -> None:
        self._click_to_frame_started_at = None
        QMessageBox.warning(self, "Load failed", message)

    def _show_status(self, message: str) -> None:
        self._system_bar.set_status_message(message)
        if self.statusBar():
            self.statusBar().showMessage(message)

    def _sync_worksheet_from_state(self, state: object) -> None:
        if not isinstance(state, ViewerState):
            return
        self._worksheet.update_from_snapshot(
            state.measurement_snapshot,
            state.contours,
        )

    def _wire_ui(self) -> None:
        self._system_bar.open_folder_requested.connect(self._open_folder)
        self._system_bar.reset_session_requested.connect(self._on_reset_measurements_requested)
        self._system_bar.caliper_requested.connect(self._on_caliper_requested)
        self._system_bar.auto_segment_requested.connect(self._request_auto_segment_shortcut)
        self._system_bar.view_mode_changed.connect(self.set_view_mode)
        self._worksheet.action_requested.connect(self._on_worksheet_action)
        self._controller.state_manager.state_changed.connect(self._sync_worksheet_from_state)
        self._measurement_panel.patient_metrics_changed.connect(
            self._controller.on_patient_metrics_changed
        )

    def _on_worksheet_action(self, action: object, view: str, phase: str) -> None:
        if not isinstance(action, MeasurementAction):
            return
        if action in {MeasurementAction.MANUAL_SIMPSON, MeasurementAction.MBS_SIMPSON}:
            self._controller.set_simpson_workflow_context(
                phase=phase,
                view=view,
                chamber="LV",
            )
            self._system_bar.set_auto_segment_enabled(True)
        handlers: dict[MeasurementAction, object] = {
            MeasurementAction.CALIBRATION: self._on_calibration_requested,
            MeasurementAction.CALIPER: self._on_caliper_requested,
            MeasurementAction.RESET: self._on_reset_measurements_requested,
            MeasurementAction.MANUAL_SIMPSON: (
                lambda: self._on_manual_simpson_requested(view, phase)
            ),
            MeasurementAction.MBS_SIMPSON: (
                lambda: self._on_mbs_simpson_requested(view, phase)
            ),
            MeasurementAction.LV2D_ALL_DIASTOLE: self._on_lv2d_all_diastole,
            MeasurementAction.LV2D_ES: self._on_lv2d_es,
            MeasurementAction.LA_DIAMETER: self._on_la_diameter,
            MeasurementAction.LAV_4C: self._on_lav_4c,
            MeasurementAction.LAV_BI: self._on_lav_bi,
            MeasurementAction.RA_DIAMETER: self._on_ra_diameter,
            MeasurementAction.RA_AREA: self._on_ra_area,
            MeasurementAction.RAV_VOLUME: self._on_rav_volume,
            MeasurementAction.RV_BASAL: self._on_rv_basal,
            MeasurementAction.RV_TAPSE: self._on_rv_tapse,
            MeasurementAction.RV_S_PRIME: self._on_rv_s_prime,
            MeasurementAction.RV_FAC_ED: lambda: self._on_rv_fac_contour("ED"),
            MeasurementAction.RV_FAC_ES: lambda: self._on_rv_fac_contour("ES"),
            MeasurementAction.DOPPLER_PEAK: self._on_doppler_peak_tool,
            MeasurementAction.DOPPLER_INTERVAL: self._on_doppler_interval_tool,
            MeasurementAction.DOPPLER_TRACE: self._on_doppler_trace_tool,
            MeasurementAction.AUTO_SEGMENT: self._request_auto_segment_shortcut,
        }
        handler = handlers.get(action)
        if handler is not None:
            handler()  # type: ignore[operator]

    def _on_doppler_peak_tool(self) -> None:
        self.set_view_mode("doppler")
        self._doppler_widget.set_tool_mode("peak")
        self._show_status("Doppler peak: click spectral envelope (M hotkey)")

    def _on_doppler_interval_tool(self) -> None:
        self.set_view_mode("doppler")
        self._doppler_widget.set_tool_mode("interval")
        self._show_status("Doppler interval: click start and end (T hotkey)")

    def _on_doppler_trace_tool(self) -> None:
        self.set_view_mode("doppler")
        self._doppler_widget.set_tool_mode("trace")
        self._show_status("Doppler VTI: trace envelope, Enter to finish (V hotkey)")

    def _on_rv_s_prime(self) -> None:
        self.set_view_mode("doppler")
        self._doppler_widget.set_tool_mode("peak")
        self._doppler_widget.set_peak_label("s_sept")
        self._show_status("RV s': place septal TDI peak marker")

    def _on_rv_fac_contour(self, phase: str) -> None:
        if self._view_mode != "2d":
            self._show_status("Switch to 2D view for RV FAC area")
            return
        if not self._start_chamber_contour(
            "RV",
            phase,
            "A4C",
            overlay=f"RV FAC {phase}: trace RV endocardium",
            status=f"RV FAC {phase}: annulus septal → lateral → apex",
        ):
            self._show_status("Load a frame first or cancel the active tool (Esc)")

    def _wire_measurement_tools(self) -> None:
        """Backward-compatible alias for tests."""
        self._wire_ui()

    def _on_caliper_requested(self) -> None:
        if self._view_mode != "2d":
            self._show_status("Switch to 2D view for linear caliper")
            return
        if self._viewer.activate_linear_caliper():
            self._show_status("Linear caliper: 1-й клик — начало, 2-й — конец")
        else:
            self._show_status("Load a frame first")

    def _on_reset_measurements_requested(self) -> None:
        self._worksheet.stop_es_prompt()
        self._lav_bi_active = False
        self._viewer.cancel_active_tool()
        self._doppler_widget.clear_measurements()
        self._controller.reset_measurements_and_calibration()
        if (
            self._view_mode == "2d"
            and self._controller.needs_manual_calibration()
            and self._viewer._current_frame is not None
        ):
            self._viewer.start_calibration_caliper()
        self._show_status("Измерения и калибровка сброшены")

    def _on_calibration_requested(self) -> None:
        if self._view_mode != "2d":
            self._show_status("Switch to 2D view for calibration")
            return
        self._viewer.toggle_calibration_caliper()
        if self._viewer.is_calibration_active:
            self._show_status(
                "Калибровка: 1-й клик — верхняя метка, 2-й — нижняя (Escape — отмена)"
            )
        elif self._viewer._current_frame is None:
            self._show_status("Load a frame first")
        else:
            self._show_status("Калибровка отменена")

    def _on_manual_simpson_requested(self, view: str, phase: str) -> None:
        if self._view_mode != "2d":
            self._show_status("Switch to 2D view for Simpson contour")
            return
        if phase == "ED":
            self._worksheet.stop_es_prompt()
        if self._viewer.start_contour(phase=phase, view=view, chamber="LV"):
            self._viewer.clear_frame_overlay()
            self._viewer.append_frame_overlay(
                f"Manual LV {view} {phase}: annulus septal → lateral → apex"
            )
            self._show_status(
                f"Manual Simpson {view} {phase}: click annulus septal, lateral, apex"
            )
        else:
            self._show_status("Load a frame first or cancel the active tool (Esc)")

    def _on_mbs_simpson_requested(self, view: str, phase: str) -> None:
        if self._view_mode != "2d":
            self._show_status("Switch to 2D view for MBS-lite")
            return
        if phase == "ED":
            self._worksheet.stop_es_prompt()
        if self._viewer.start_model_contour(phase=phase, view=view, chamber="LV"):
            self._viewer.clear_frame_overlay()
            self._viewer.append_frame_overlay(
                f"MBS-lite LV {view} {phase}: annulus septal → lateral → apex"
            )
            self._show_status(
                f"MBS-lite {view} {phase}: click annulus septal, lateral, apex"
            )
        else:
            self._show_status("Load a frame first or cancel the active tool (Esc)")

    def _on_es_button_pressed(self, view: str, phase: str) -> None:
        if phase == "ES":
            self._worksheet.stop_es_prompt()

    def _on_lv2d_all_diastole(self) -> None:
        if self._view_mode != "2d":
            self._show_status("Switch to 2D view for LV-2D measurements")
            return
        if self._viewer.start_linear_caliper_sequence(("IVSd", "LVEDD", "LVPWd")):
            self._viewer.clear_frame_overlay()
            self._viewer.append_frame_overlay("LV diastole: IVSd → LVEDD → LVPWd")
            self._show_status(
                "All Diastole: IVSd (2 клика) → LVEDD (2 клика) → LVPWd (2 клика)"
            )
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

    def _has_chamber_contour(self, chamber: str, view: str, phase: str) -> bool:
        for contour in self._controller.state_manager.snapshot.contours:
            if (
                contour.chamber.upper() == chamber.upper()
                and contour.view.upper() == view.upper()
                and contour.phase.upper() == phase.upper()
            ):
                return True
        return False

    def _start_chamber_contour(
        self,
        chamber: str,
        phase: str,
        view: str,
        *,
        model: bool = False,
        overlay: str,
        status: str,
    ) -> bool:
        starter = (
            self._viewer.start_model_contour if model else self._viewer.start_contour
        )
        if not starter(chamber=chamber, phase=phase, view=view):
            return False
        self._viewer.clear_frame_overlay()
        self._viewer.append_frame_overlay(overlay)
        self._show_status(status)
        return True

    def _on_la_diameter(self) -> None:
        if self._view_mode != "2d":
            return
        if self._viewer.start_linear_caliper_for("LA"):
            self._show_status("Left atrium: place AP diameter caliper")
        else:
            self._show_status("Load a frame first")

    def _on_lav_4c(self) -> None:
        if self._view_mode != "2d":
            return
        self._lav_bi_active = False
        if not self._start_chamber_contour(
            "LA",
            "ES",
            "A4C",
            overlay="LAV 4C: LA A4C ES — annulus septal → lateral → apex",
            status="LAV 4C: annulus septal → lateral → apex",
        ):
            self._show_status("Load a frame first or cancel the active tool (Esc)")

    def _on_lav_bi(self) -> None:
        if self._view_mode != "2d":
            return
        has_a4c = self._has_chamber_contour("LA", "A4C", "ES")
        has_a2c = self._has_chamber_contour("LA", "A2C", "ES")
        if has_a4c and not has_a2c:
            self._lav_bi_active = True
            if not self._start_chamber_contour(
                "LA",
                "ES",
                "A2C",
                overlay="LAV Bi: LA A2C ES — annulus septal → lateral → apex",
                status="LAV Bi: annulus septal → lateral → apex",
            ):
                self._show_status("Load a frame first or cancel the active tool (Esc)")
            return
        self._lav_bi_active = True
        if not self._start_chamber_contour(
            "LA",
            "ES",
            "A4C",
            overlay="LAV Bi: шаг 1 — LA A4C ES — annulus septal → lateral → apex",
            status="LAV Bi: annulus septal → lateral → apex",
        ):
            self._show_status("Load a frame first or cancel the active tool (Esc)")

    def _on_ra_diameter(self) -> None:
        if self._view_mode != "2d":
            return
        if self._viewer.start_linear_caliper_for("RA"):
            self._show_status("Right atrium: place diameter caliper")
        else:
            self._show_status("Load a frame first")

    def _on_ra_area(self) -> None:
        if self._view_mode != "2d":
            return
        if not self._start_chamber_contour(
            "RA",
            "ES",
            "A4C",
            overlay="S ПП: RA A4C ES — annulus septal → lateral → apex",
            status="S ПП: annulus septal → lateral → apex",
        ):
            self._show_status("Load a frame first or cancel the active tool (Esc)")

    def _on_rav_volume(self) -> None:
        if self._view_mode != "2d":
            return
        if not self._start_chamber_contour(
            "RA",
            "ES",
            "A4C",
            overlay="RAV: RA A4C ES — annulus septal → lateral → apex",
            status="RAV: annulus septal → lateral → apex",
        ):
            self._show_status("Load a frame first or cancel the active tool (Esc)")

    def _on_contour_completed(self, contour: object) -> None:
        if not isinstance(contour, Contour):
            return
        chamber = contour.chamber.upper()
        if chamber not in {"LV", "LA", "RA", "RV"}:
            return
        if not contour.is_open_arc:
            return

        extra_lines: tuple[str, ...] = ()
        if (
            chamber == "LV"
            and contour.phase.upper() == "ED"
        ):
            mode = "mbs" if contour.source == "model" else "manual"
            view_label = "4C" if contour.view.upper() == "A4C" else "2C"
            es_name = "ESV Auto" if mode == "mbs" else "Systole"
            extra_lines = (
                f"Перейдите на кадр систолы и нажмите {es_name} ({view_label})",
            )
            self._worksheet.start_es_prompt(mode, view_label)
            status = (
                f"Перейдите на кадр систолы и нажмите {es_name} ({view_label})"
            )
            if (
                self._controller.state_manager.snapshot.effective_pixel_spacing is None
            ):
                status += " · нет PixelSpacing (K — калибровка, px / px³)"
            self._show_status(status)
        elif (
            self._lav_bi_active
            and chamber == "LA"
            and contour.phase.upper() == "ES"
            and contour.view.upper() == "A4C"
        ):
            extra_lines = (
                "LAV Bi: перейдите на 2C ES и нажмите LAV Bi",
            )
            self._show_status(
                "LAV Bi: шаг 1 завершён — перейдите на 2C ES и нажмите LAV Bi"
            )
        elif (
            contour.phase.upper() == "ES"
            and chamber == "LA"
            and contour.view.upper() == "A2C"
        ):
            self._lav_bi_active = False
        elif contour.phase.upper() == "ES":
            self._worksheet.stop_es_prompt()

        self._viewer._refresh_frame_overlays(extra_lines=extra_lines)

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
        self._system_bar.set_view_mode(mode_name)
        if mode_name == "doppler":
            self._view_stack.setCurrentWidget(self._doppler_widget)
            if self._viewer._current_frame is not None:
                self._doppler_widget.show_spectrogram(self._viewer._current_frame)
            self._show_status("Doppler view active")
        else:
            self._view_stack.setCurrentWidget(self._viewer)
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
                        "Калибровка: 1-й клик — верхняя метка, 2-й — нижняя (Escape — отмена)"
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
            refined, mode = self._viewer.refine_active_open_contour()
            if refined:
                self._controller.on_contours_changed(self._viewer.contours())
                self._show_status(
                    "Gradient refine (R)"
                    if mode == "gradient"
                    else "Geometry smooth (R)"
                )
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
