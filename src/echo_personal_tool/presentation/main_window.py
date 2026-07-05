"""Main application window."""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
from typing import Literal

import numpy as np
from PySide6.QtCore import QEvent, QPoint, QSignalBlocker, Qt, QThreadPool, QTimer
from PySide6.QtGui import QCloseEvent, QKeyEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.infrastructure.profiler import profiled as _prof
from echo_personal_tool.domain.models import Contour, InstanceMetadata
from echo_personal_tool.domain.models.viewer_state import ViewerState
from echo_personal_tool.domain.services.measurement_results_formatter import (
    format_results_overlay,
)
from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.infrastructure.orthanc_cache import OrthancSessionCache
from echo_personal_tool.infrastructure.server_client_factory import (
    make_dicom_query_service,
    make_dicom_web_client,
)
from echo_personal_tool.infrastructure.server_settings import load_server_settings
from echo_personal_tool.presentation.dicom_upload_dialog import run_dicom_upload_dialog
from echo_personal_tool.infrastructure.user_preferences import (
    UserPreferences,
    load_user_preferences,
    save_user_preferences,
)
from echo_personal_tool.presentation.ase_reference_dialog import show_ase_reference_dialog
from echo_personal_tool.presentation.echopac_theme import apply_echopac_theme
from echo_personal_tool.presentation.measurement_action import MeasurementAction
from echo_personal_tool.presentation.measurement_results_dialog import MeasurementResultsDialog
from echo_personal_tool.presentation.orthanc_study_dialog import OrthancStudyDialog
from echo_personal_tool.presentation.speckle_settings_dialog import SpeckleSettingsDialog
from echo_personal_tool.presentation.ste_results_dialog import SteResultsDialog
from echo_personal_tool.presentation.system_bar import SystemBar
from echo_personal_tool.presentation.thumbnail_gallery import ThumbnailGalleryWidget
from echo_personal_tool.presentation.tool_panel import ToolPanel
from echo_personal_tool.presentation.user_preferences_dialog import show_user_preferences_dialog
from echo_personal_tool.presentation.viewer_widget import ViewerWidget
from echo_personal_tool.resources.bundled_fonts import ui_font

logger = logging.getLogger(__name__)

_TOOL_PANEL_WIDTH = 280


@dataclass
class LayoutConfig:
    """Immutable snapshot — always replace, never mutate in place."""
    swap_places: bool = False
    gallery_horizontal: bool = False
    activity_bar: bool = False
    status_bar_visible: bool = True
    multiview: bool = False


def _loaded_file_label(instance: InstanceMetadata) -> str:
    if instance.path is not None:
        return instance.path.name
    return instance.sop_instance_uid


def apply_maximized_to_work_area(window: QMainWindow) -> None:
    """Maximize within the screen work area (taskbar-safe on Windows)."""
    screen = window.screen() or QApplication.primaryScreen()
    if screen is None:
        window.showMaximized()
        window._user_maximized = True  # type: ignore[attr-defined]
        return
    geo = screen.availableGeometry()
    if sys.platform == "win32":
        window.show()
        window.setGeometry(geo)
        window._user_maximized = True  # type: ignore[attr-defined]
        return
    window.showMaximized()
    window._user_maximized = True  # type: ignore[attr-defined]


class MainWindow(QMainWindow):
    """EchoPac-style layout: thumbnails | viewer | tool panel."""

    @property
    def _browser(self):
        """Backward-compatible alias (tests); thumbnail gallery replaces tree browser."""
        return self._gallery

    def __init__(
        self,
        controller: AppController | None = None,
        *,
        user_preferences: UserPreferences | None = None,
    ) -> None:
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setWindowTitle("ECHO Personal Tool")
        self._user_preferences = user_preferences or load_user_preferences()
        self._click_to_frame_started_at: float | None = None
        self._playback_active = False
        self._lav_bi_active = False
        self._rv_fac_awaiting_es = False
        self._instance_overlay_cache: dict[str, str] = {}
        self._instance_overlay_positions: dict[str, tuple[float, float]] = {}
        self._study_overlay_positions: dict[str, tuple[float, float]] = {}
        self._current_overlay_study_uid: str | None = None
        self._overlay_sync_instance_uid: str | None = None
        self._last_overlay_state: ViewerState | None = None
        self._manual_ed_frame: int | None = None
        self._manual_es_frame: int | None = None
        self._layout_config = self._load_layout_state()
        self._bottom_container: QWidget | None = None
        self._viewer2: ViewerWidget | None = None
        self._viewer2_instance: InstanceMetadata | None = None
        self._viewer2_frame_index: int = 0
        self._viewer2_playing: bool = False
        self._viewer2_total_frames: int = 0
        self._active_viewer: ViewerWidget | None = None
        self._activity_bar = None
        self._user_maximized = False
        self._slider_navigating = False

        self._controller = controller or AppController()
        orthanc_root = Path.home() / ".echo-personal-tool" / "orthanc"
        orthanc_root.parent.mkdir(parents=True, exist_ok=True)
        self._orthanc_cache = OrthancSessionCache(orthanc_root)
        self._controller.studies_loaded.connect(self._on_studies_loaded)
        self._controller.scan_failed.connect(self._on_scan_failed)
        self._controller.frame_loaded.connect(self._on_frame_loaded)
        self._controller.frame_load_failed.connect(self._on_frame_load_failed)
        self._controller.scroll_settled.connect(self._on_scroll_settled)
        self._controller.status_message.connect(self._show_status)
        apply_echopac_theme(
            font_size=self._user_preferences.ui_font_size,
            theme=self._user_preferences.theme_mode,
        )

        central = QWidget()
        self.setCentralWidget(central)
        self._root_layout = QVBoxLayout(central)
        self._root_layout.setContentsMargins(0, 0, 0, 0)
        self._root_layout.setSpacing(0)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._system_bar = SystemBar()
        self._controller.decode_progress.connect(self._system_bar.show_decode_progress)
        self._controller.decode_finished.connect(self._system_bar.hide_decode_progress)
        self._root_layout.addWidget(self._system_bar)

        self._content_widget = QWidget()
        self._root_layout.addWidget(self._content_widget, stretch=1)
        self._content_layout = QHBoxLayout(self._content_widget)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(0)

        self._gallery = ThumbnailGalleryWidget()
        self._gallery.set_thumbnail_loader(self._controller.load_thumbnail)
        self._controller.thumbnail_loaded.connect(self._gallery.set_thumbnail)
        self._gallery.instance_selected.connect(self._on_instance_selected)
        self._gallery.export_mp4_requested.connect(self._on_export_mp4_requested)

        self._content_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._content_splitter.setHandleWidth(2)

        self._viewer = ViewerWidget()
        self._viewer.set_scroll_debounce_ms(self._controller.playback_config.scroll_debounce_ms)
        self._viewer.play_pause_requested.connect(self._controller.toggle_playback)
        self._viewer.frame_selected.connect(self._on_slider_frame_selected)
        self._viewer.scroll_frame_selected.connect(
            lambda index: self._controller.state_manager.set_frame(index, scroll=True)
        )
        self._viewer.contour_completed.connect(self._on_contour_completed)
        self._viewer.contour_landmark_rejected.connect(self._show_status)
        self._viewer.contours_changed.connect(self._controller.on_contours_changed)
        self._viewer.linear_measurements_changed.connect(
            self._controller.on_linear_measurements_changed
        )
        self._viewer.linear_caliper_sequence_completed.connect(
            self._on_linear_caliper_sequence_completed
        )
        self._viewer.calibration_completed.connect(self._controller.on_manual_calibration)
        self._viewer.doppler_markers_changed.connect(self._controller.on_doppler_markers_changed)
        self._viewer.doppler_calibration_changed.connect(
            self._controller.on_doppler_calibration_changed
        )
        self._viewer.doppler_frame_changing.connect(self._on_doppler_frame_changing)
        self._viewer.doppler_frame_changed.connect(self._on_doppler_frame_changed)
        self._viewer.mmode_time_calibration_completed.connect(
            self._controller.on_mmode_time_calibration
        )
        self._viewer.mmode_calibration_changed.connect(
            self._controller.on_mmode_calibration_changed
        )
        self._viewer.results_overlay_position_changed.connect(
            self._on_results_overlay_position_changed
        )
        self._controller.state_manager.state_changed.connect(self._viewer.set_state)
        self._controller.state_manager.state_changed.connect(self._on_state_changed_for_viewer2)
        self._doppler_frame_context: tuple[str | None, int | None] = (None, None)
        self._ste_dialog: SteResultsDialog | None = None

        self._tool_panel = ToolPanel()
        self._tool_panel.setFixedWidth(_TOOL_PANEL_WIDTH)

        self._viewer.set_state(self._controller.state_manager.snapshot)
        self._sync_results_overlay(self._controller.state_manager.snapshot)
        self._viewer.bind_display_controls(
            self._tool_panel.controls.window_slider,
            self._tool_panel.controls.level_slider,
            self._tool_panel.controls.dr_slider,
        )
        self._wire_wl_persistence()
        self._apply_user_preferences(self._user_preferences)
        self._controller.state_manager.state_changed.connect(self._on_state_changed)
        self._wire_ui()
        self._viewer.installEventFilter(self)
        self._viewer._graphics.installEventFilter(self)
        self._viewer._view.installEventFilter(self)

        status = QStatusBar()
        self.setStatusBar(status)
        self._show_status(tr("status.startup"))
        self._install_shortcuts()
        self._rebuild_layout()

    def _install_shortcuts(self) -> None:
        """Window-level shortcuts that work when the viewer or browser has focus."""
        bindings: list[tuple[str, object]] = [
            ("L", self._viewer.toggle_linear_caliper),
            ("C", self._start_manual_contour_shortcut),
            ("M", self._start_model_contour_shortcut),
            ("I", self._request_auto_segment_shortcut),
            ("Return", self._finish_active_tool_shortcut),
            ("Enter", self._finish_active_tool_shortcut),
            ("Escape", self._cancel_active_tool),
            ("Backspace", self._delete_current_contour),
            ("Delete", self._delete_current_contour),
            ("`", self._toggle_gallery_shortcut),
            ("F11", self._toggle_fullscreen_shortcut),
            ("Up", self._gallery.select_previous_instance),
            ("Down", self._gallery.select_next_instance),
        ]
        for sequence, handler in bindings:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(handler)

    @_prof
    def _toggle_playback_shortcut(self) -> None:
        if self._controller.state_manager.snapshot.decode_in_progress:
            return
        self._controller.toggle_playback()

    @_prof
    def _start_manual_contour_shortcut(self) -> None:
        if self._viewer.start_contour():
            self._show_status(tr("status.manual_contour"))
        else:
            self._show_status(tr("status.load_frame_or_finish_contour"))

    @_prof
    def _start_model_contour_shortcut(self) -> None:
        start_mode = self._viewer.start_model_contour()
        if start_mode:
            self._viewer.clear_frame_overlay()
            self._viewer.append_frame_overlay("MBS-lite: MA septal → lateral → apex")
            self._show_status(tr("status.mbs_lite_contour"))
        else:
            self._show_status(tr("status.load_frame_or_finish_contour"))

    @_prof
    def _request_auto_segment_shortcut(self) -> None:
        if self._viewer.get_doppler_tool_mode() != "none":
            return
        if not self._controller.is_lv_auto_session_active():
            self._show_status(tr("status.select_lv_auto"))
            return
        if not self._controller.state_manager.snapshot.is_playing:
            self._controller.request_auto_segment()

    @_prof
    def _finish_active_tool_shortcut(self) -> None:
        pending = self._viewer.pending_ai_review_contour()
        if pending is not None:
            if self._controller.accept_ai_contour_review(pending.view, pending.phase):
                self._viewer.clear_frame_overlay()
                mode = "mbs" if pending.source in {"ai", "model"} else "manual"
                self._maybe_prompt_es_auto(pending.view, pending.phase, mode=mode)
            return
        if self._viewer.get_doppler_tool_mode() == "trace" and self._viewer.finish_doppler_trace():
            return
        if self._viewer.finish_contour():
            return

    @_prof
    def _cancel_active_tool(self) -> None:
        if self._viewer.discard_pending_ai_contour():
            self._controller.on_contours_changed(self._viewer.contours())
            self._show_status(tr("status.ai_contour_cancelled"))
            return
        self._viewer.cancel_active_tool()

    @_prof
    def _delete_current_contour(self) -> None:
        if self._viewer._delete_selected_caliper():
            self._show_status(tr("status.caliper_deleted"))
            return
        if self._viewer.delete_contour_for_current_phase():
            self._controller.on_contours_changed(self._viewer.contours())
            self._show_status(tr("status.contour_deleted"))

    def _toggle_gallery_shortcut(self) -> None:
        self._gallery.toggle_collapse()

    def _toggle_fullscreen_shortcut(self) -> None:
        if self.isFullScreen():
            self.showNormal()
            self._gallery.show()
            if not self._layout_config.activity_bar:
                self._tool_panel.show()
        else:
            self._gallery.hide()
            self._tool_panel.hide()
            self.showFullScreen()

    def _toggle_maximize(self) -> None:
        if self.isMaximized():
            self.showNormal()
            self._user_maximized = False
        else:
            apply_maximized_to_work_area(self)
        self._system_bar.update_maximize_button(self.isMaximized())

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.Type.WindowStateChange:
            self._system_bar.update_maximize_button(self.isMaximized())
            if self.isMaximized() and self._user_maximized:
                screen = self.screen() or QApplication.primaryScreen()
                if screen is not None:
                    geo = screen.availableGeometry()
                    if self.geometry() != geo:
                        self.setGeometry(geo)
        super().changeEvent(event)

    def _load_layout_state(self) -> LayoutConfig:
        raw = self._user_preferences.layout_state_json
        if not raw:
            return LayoutConfig()
        try:
            cfg = LayoutConfig(**json.loads(raw))
            return cfg
        except (json.JSONDecodeError, TypeError, ValueError):
            return LayoutConfig()

    def reset_layout_to_default(self) -> None:
        self._layout_config = LayoutConfig()
        self._rebuild_layout()

    def _save_layout_state(self) -> None:
        self._user_preferences.layout_state_json = json.dumps(asdict(self._layout_config))
        save_user_preferences(self._user_preferences)

    def _show_layout_menu(self) -> None:
        menu = QMenu(self._system_bar._btn_layout)
        menu.setObjectName("layoutMenu")
        items = [
            ("swap_places", tr("layout.swap_places")),
            ("gallery_horizontal", tr("layout.gallery_horizontal")),
            ("activity_bar", tr("layout.activity_bar_mode")),
            ("status_bar_visible", tr("layout.status_bar_mode")),
            ("multiview", tr("layout.multiview_mode")),
        ]
        for attr, tooltip in items:
            action = menu.addAction(tooltip)
            action.setCheckable(True)
            action.setChecked(getattr(self._layout_config, attr))
            action.triggered.connect(lambda checked, a=attr: self._on_layout_toggle(a, checked))
        menu.exec(self._system_bar._btn_layout.mapToGlobal(
            QPoint(0, self._system_bar._btn_layout.height())
        ))

    def _on_layout_toggle(self, attr: str, checked: bool) -> None:
        from dataclasses import replace
        self._layout_config = replace(self._layout_config, **{attr: checked})
        self._rebuild_layout()

    def _release_content_layout(self) -> None:
        """Remove widgets from the horizontal content row without destroying them."""
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(self._content_widget)

    def _teardown_bottom_gallery(self) -> None:
        """Reparent gallery before deleting the bottom strip (avoids destroying gallery)."""
        if self._bottom_container is None:
            return
        bottom_layout = self._bottom_container.layout()
        if bottom_layout is not None:
            while bottom_layout.count():
                item = bottom_layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.setParent(self._content_widget)
        self._root_layout.removeWidget(self._bottom_container)
        self._bottom_container.deleteLater()
        self._bottom_container = None

    def _clear_splitter(self, splitter: QSplitter) -> None:
        while splitter.count():
            child = splitter.widget(0)
            child.setParent(self._content_widget)

    def _apply_layout_visibility(
        self,
        cfg: LayoutConfig,
        *,
        use_splitter: bool,
        left: QWidget | None,
        right: QWidget | None,
    ) -> None:
        self._viewer.show()
        if cfg.multiview and self._viewer2 is not None:
            self._viewer2.show()

        if cfg.gallery_horizontal:
            if self._bottom_container is not None:
                self._bottom_container.show()
            self._gallery.show()
        elif left is self._gallery or right is self._gallery:
            self._gallery.show()

        if cfg.activity_bar:
            if self._activity_bar is not None:
                self._activity_bar.show()
            if not use_splitter and self._tool_panel not in (left, right):
                self._tool_panel.hide()
        else:
            if self._activity_bar is not None:
                self._activity_bar.hide()
            if use_splitter or self._tool_panel in (left, right):
                self._tool_panel.show()

    def _rebuild_layout(self) -> None:
        cfg = self._layout_config
        self._content_widget.setUpdatesEnabled(False)
        try:
            self._release_content_layout()
            self._teardown_bottom_gallery()
            self._clear_splitter(self._content_splitter)

            if cfg.activity_bar:
                self._ensure_activity_bar()

            use_splitter = (
                not cfg.activity_bar
                and not cfg.gallery_horizontal
                and not cfg.multiview
                and not cfg.swap_places
            )

            if cfg.multiview:
                self._ensure_viewer2()
                self._content_splitter.addWidget(self._viewer)
                self._content_splitter.addWidget(self._viewer2)
                self._content_splitter.setHandleWidth(2)
                self._content_splitter.blockSignals(True)
                self._content_splitter.setSizes([800, 800])
                self._content_splitter.blockSignals(False)
                center: QWidget = self._content_splitter
            elif use_splitter:
                self._content_splitter.blockSignals(True)
                self._content_splitter.addWidget(self._viewer)
                self._content_splitter.addWidget(self._tool_panel)
                self._content_splitter.setStretchFactor(0, 1)
                self._content_splitter.setStretchFactor(1, 0)
                self._content_splitter.setSizes([800, _TOOL_PANEL_WIDTH])
                self._content_splitter.blockSignals(False)
                center = self._content_splitter
            else:
                center = self._viewer

            if not cfg.multiview:
                self._detach_viewer2()

            left = self._decide_left(cfg)
            right = self._decide_right(cfg)

            if left is not None:
                left.show()
                self._content_layout.addWidget(left)
            if center is not None:
                center.show()
                self._content_layout.addWidget(center, stretch=1)
            if right is not None:
                right.show()
                self._content_layout.addWidget(right)

            if cfg.gallery_horizontal:
                self._gallery.set_horizontal_mode(True)
                self._bottom_container = QWidget()
                bottom_layout = QHBoxLayout(self._bottom_container)
                bottom_layout.setContentsMargins(0, 0, 0, 0)
                bottom_layout.addWidget(self._gallery)
                if self.statusBar() is not None:
                    status_index = self._root_layout.indexOf(self.statusBar())
                    self._root_layout.insertWidget(status_index, self._bottom_container)
                else:
                    self._root_layout.addWidget(self._bottom_container)
            else:
                self._gallery.set_horizontal_mode(False)

            self.statusBar().setVisible(cfg.status_bar_visible)
            self._apply_layout_visibility(cfg, use_splitter=use_splitter, left=left, right=right)
            if cfg.activity_bar:
                self._restore_activity_tool_panel_if_needed()
            elif self._activity_bar is not None:
                self._activity_bar.set_active(None)
            self._save_layout_state()
        finally:
            self._content_widget.setUpdatesEnabled(True)

    def _clear_content_layout(self) -> None:
        """Backward-compatible alias for tests."""
        self._release_content_layout()

    def _decide_left(self, cfg: LayoutConfig) -> QWidget | None:
        if cfg.activity_bar and cfg.swap_places:
            return self._activity_bar
        if cfg.swap_places:
            return self._tool_panel
        if cfg.activity_bar:
            return None if cfg.gallery_horizontal else self._gallery
        if cfg.gallery_horizontal:
            return None
        return self._gallery

    def _decide_right(self, cfg: LayoutConfig) -> QWidget | None:
        if cfg.activity_bar and not cfg.swap_places:
            return self._activity_bar
        if cfg.activity_bar and cfg.swap_places:
            return None if cfg.gallery_horizontal else self._gallery
        if cfg.swap_places:
            return None if cfg.gallery_horizontal else self._gallery
        if cfg.gallery_horizontal or cfg.multiview:
            return self._tool_panel
        return None

    def _ensure_viewer2(self) -> None:
        if self._viewer2 is not None:
            try:
                _ = self._viewer2.width()
                return
            except RuntimeError:
                self._viewer2 = None
        self._viewer2 = ViewerWidget()
        self._viewer2.set_scroll_debounce_ms(self._controller.playback_config.scroll_debounce_ms)
        self._viewer2.installEventFilter(self)
        self._viewer2._graphics.installEventFilter(self)
        self._viewer2._view.installEventFilter(self)
        self._viewer2.play_pause_requested.connect(self._toggle_viewer2_playback)
        self._viewer2.frame_selected.connect(self._on_viewer2_frame_selected)
        self._viewer2.scroll_frame_selected.connect(self._on_viewer2_frame_selected)
        self._viewer2.contour_completed.connect(self._on_contour_completed)
        self._viewer2.contours_changed.connect(self._controller.on_contours_changed)
        # Sync viewer2 state from controller's current instance
        self._sync_viewer2_state()

    def _detach_viewer2(self) -> None:
        if self._viewer2 is None:
            return
        try:
            self._viewer2.hide()
        except RuntimeError:
            self._viewer2 = None

    def _ensure_activity_bar(self) -> None:
        if self._activity_bar is not None:
            return
        from echo_personal_tool.presentation.activity_bar import ActivityBar
        self._activity_bar = ActivityBar()
        self._activity_bar.tab_activated.connect(self._on_activity_tab_activated)
        self._activity_bar.tab_deactivated.connect(self._on_activity_tab_deactivated)
        self._activity_bar.action_requested.connect(self._on_activity_action)

    def _on_activity_action(self, action: str) -> None:
        if action == "caliper":
            self._on_caliper_requested()
        elif action == "lv2d":
            self._on_lv2d_all_diastole()
        elif action == "esv":
            self._on_lv2d_es()
        elif action == "edv":
            self._on_measure_action(
                MeasurementAction.MANUAL_SIMPSON, "A4C", "ED", ""
            )
        elif action == "es":
            self._on_measure_action(
                MeasurementAction.MANUAL_SIMPSON, "A4C", "ES", ""
            )

    def _remove_tool_panel_from_content_layout(self) -> None:
        idx = self._content_layout.indexOf(self._tool_panel)
        if idx >= 0:
            self._content_layout.takeAt(idx)

    def _attach_tool_panel_after(self, anchor: QWidget) -> None:
        bar_idx = self._content_layout.indexOf(anchor)
        if bar_idx < 0:
            return
        self._remove_tool_panel_from_content_layout()
        self._content_layout.insertWidget(bar_idx + 1, self._tool_panel)

    def _restore_activity_tool_panel_if_needed(self) -> None:
        if self._activity_bar is None or not self._layout_config.activity_bar:
            return
        for name, button in self._activity_bar._buttons.items():
            if button.isChecked():
                self._on_activity_tab_activated(name)
                return

    def _on_activity_tab_activated(self, tab: str) -> None:
        tab_map = {"measures": 0, "controls": 1, "properties": 2, "dicom": 3}
        if tab in tab_map:
            self._tool_panel._tabs.setCurrentIndex(tab_map[tab])
        self._tool_panel.setFixedWidth(_TOOL_PANEL_WIDTH)
        if self._activity_bar is not None:
            if self._content_layout.indexOf(self._activity_bar) >= 0:
                self._attach_tool_panel_after(self._activity_bar)
            elif self._content_layout.indexOf(self._tool_panel) < 0:
                self._content_layout.addWidget(self._tool_panel)
        self._tool_panel.show()

    def _on_activity_tab_deactivated(self, tab: str) -> None:
        self._tool_panel.hide()
        self._remove_tool_panel_from_content_layout()

    @_prof
    def _show_references(self) -> None:
        show_ase_reference_dialog(self)

    @_prof
    def _show_user_preferences(self) -> None:
        show_user_preferences_dialog(self, on_apply=self._apply_user_preferences)

    def _apply_user_preferences(self, preferences: UserPreferences) -> None:
        self._user_preferences = preferences
        if not preferences.results_overlay_custom_position:
            self._instance_overlay_positions.clear()
            self._study_overlay_positions.clear()
            self._current_overlay_study_uid = None
        from echo_personal_tool.infrastructure.i18n import set_language
        set_language(preferences.language)
        self._reload_ui_language()
        app = QApplication.instance()
        if app is not None:
            app.setFont(ui_font(point_size=preferences.ui_font_size))
        apply_echopac_theme(
            font_size=preferences.ui_font_size,
            theme=preferences.theme_mode,
        )
        self._system_bar.reload_icons()
        with QSignalBlocker(self._tool_panel.controls._magnetic_snap_check):
            self._tool_panel.controls._magnetic_snap_check.setChecked(
                preferences.magnetic_snap_enabled
            )
        self._tool_panel.set_auto_play(preferences.auto_play)
        self._viewer.set_magnetic_snap_enabled(preferences.magnetic_snap_enabled)
        self._viewer.apply_user_preferences(preferences)
        self._gallery.apply_scale(preferences.thumbnail_scale)
        self._controller.set_playback_speed_multiplier(preferences.playback_speed_multiplier)
        self._tool_panel.set_dicom_inspector_visible(preferences.show_dicom_tag_inspector)
        self._refresh_dicom_inspector()
        self._sync_results_overlay(self._controller.state_manager.snapshot)

    def _reload_ui_language(self) -> None:
        self._system_bar.reload_text()
        if self._activity_bar is not None:
            self._activity_bar.reload_text()
        self._viewer.reload_text()
        self._tool_panel.reload_text()
        self._sync_results_overlay(self._controller.state_manager.snapshot)

    def _on_magnetic_snap_changed(self, enabled: bool) -> None:
        self._viewer.set_magnetic_snap_enabled(enabled)
        self._user_preferences.magnetic_snap_enabled = enabled
        save_user_preferences(self._user_preferences)

    def _on_results_overlay_position_changed(self, x_ratio: float, y_ratio: float) -> None:
        instance = self._controller.state_manager.snapshot.instance
        if instance is not None:
            self._instance_overlay_positions[instance.sop_instance_uid] = (x_ratio, y_ratio)
        if self._viewer._results_overlay_label._pinned:
            study_uid = self._controller._resolve_study_uid(instance)
            self._study_overlay_positions[study_uid] = (x_ratio, y_ratio)

    def _restore_results_overlay_position(self, instance_uid: str | None) -> None:
        instance = self._controller.state_manager.snapshot.instance
        study_uid = self._controller._resolve_study_uid(instance)
        if study_uid != self._current_overlay_study_uid:
            self._current_overlay_study_uid = study_uid
            if study_uid in self._study_overlay_positions:
                x_ratio, y_ratio = self._study_overlay_positions[study_uid]
                self._viewer.set_results_overlay_position(x_ratio, y_ratio, custom=True)
                return
            self._viewer.reset_results_overlay_to_default()
            return
        if instance_uid and instance_uid in self._instance_overlay_positions:
            x_ratio, y_ratio = self._instance_overlay_positions[instance_uid]
            self._viewer.set_results_overlay_position(x_ratio, y_ratio, custom=True)
            return
        self._viewer.reset_results_overlay_to_default()

    def _wire_wl_persistence(self) -> None:
        for slider_widget in (
            self._tool_panel.controls.window_slider,
            self._tool_panel.controls.level_slider,
            self._tool_panel.controls.dr_slider,
        ):
            slider_widget.slider().valueChanged.connect(self._persist_window_level_preferences)

    def _persist_window_level_preferences(self) -> None:
        self._user_preferences.wl_preset = "last_used"
        self._user_preferences.wl_window = self._tool_panel.controls.window_slider.slider().value()
        self._user_preferences.wl_level = self._tool_panel.controls.level_slider.slider().value()
        self._user_preferences.wl_dr = self._tool_panel.controls.dr_slider.slider().value()
        save_user_preferences(self._user_preferences)

    def _refresh_dicom_inspector(self) -> None:
        instance = self._controller.state_manager.snapshot.instance
        path = instance.path if instance is not None else None
        self._tool_panel.load_dicom_inspector(path)

    def open_folder_path(self, directory: Path) -> None:
        log_path = directory / "scan_errors.log"
        self._controller.open_folder(directory, error_log_path=log_path)

    @_prof
    def _open_folder(self) -> None:
        from echo_personal_tool.infrastructure.i18n import tr
        directory = QFileDialog.getExistingDirectory(self, tr("dialog.select_folder"))
        if not directory:
            return
        folder = Path(directory)
        self._user_preferences.last_opened_folder = str(folder)
        save_user_preferences(self._user_preferences)
        self.open_folder_path(folder)

    def _on_export_mp4_requested(self, instance: object) -> None:
        if not isinstance(instance, InstanceMetadata) or instance.path is None:
            return
        dest, _ = QFileDialog.getSaveFileName(
            self, tr("dialog.export_mp4.title"), "", "MP4 (*.mp4)",
        )
        if not dest:
            return
        if instance.media_format == "mp4":
            import shutil as _shutil
            _shutil.copy2(str(instance.path), dest)
            self._show_status(tr("status.mp4_copied", dest=dest))
            return
        from echo_personal_tool.application.workers.mp4_export_worker import (
            Mp4ExportWorker,
        )
        self._show_status(tr("status.mp4_exporting"))
        worker = Mp4ExportWorker(
            source_path=Path(instance.path),
            dest_path=dest,
            media_format=instance.media_format,
            frame_time_ms=instance.frame_time_ms,
            parent=self,
        )
        worker.signals.progress.connect(self._on_mp4_export_progress)
        worker.signals.finished.connect(self._on_mp4_export_finished)
        worker.signals.failed.connect(self._on_mp4_export_failed)
        QThreadPool.globalInstance().start(worker)

    def _on_mp4_export_progress(self, current: int, total: int) -> None:
        self._show_status(tr("status.mp4_export_progress", current=current, total=total))

    def _on_mp4_export_finished(self, path: str) -> None:
        self._show_status(tr("status.mp4_exported", path=path))

    def _on_mp4_export_failed(self, error: str) -> None:
        QMessageBox.warning(self, tr("dialog.export_error.title"), error)
        self._show_status(tr("status.mp4_export_failed"))

    @_prof
    def _open_orthanc_dialog(self) -> None:
        from echo_personal_tool.presentation.ui_animations import exec_animated
        settings = load_server_settings()
        client = make_dicom_web_client(settings)
        query_service = make_dicom_query_service(settings)
        dialog = OrthancStudyDialog(
            client,
            self._orthanc_cache,
            self,
            server_settings=settings,
            query_service=query_service,
        )
        exec_animated(dialog)
        result = dialog.result_data()
        downloaded = dialog.downloaded_studies()
        logger.info(
            "[MW] dialog closed: result=%s downloaded_count=%d total_instances=%d",
            result,
            len(downloaded),
            sum(len(s.instances) for st in downloaded for s in st.series),
        )
        if result:
            downloaded = dialog.downloaded_studies()
            if downloaded:
                self._controller.load_pre_scanned_studies(downloaded)
            else:
                session_id, _study_uid = result
                path = self._orthanc_cache.session_path(session_id)
                log_path = path / "scan_errors.log"
                logger.info("[MW] scan fallback: session=%s path=%s exists=%s",
                            session_id[:8], path, path.exists())
                self._controller.open_folder(path, error_log_path=log_path)
        else:
            logger.warning("[MW] dialog closed with no result (user cancelled or error)")

    def _send_to_server(self) -> None:
        studies = self._controller.studies
        if not studies:
            QMessageBox.information(
                self,
                tr("dialog.dicom_upload.title"),
                tr("dialog.dicom_upload.no_files"),
            )
            return
        run_dicom_upload_dialog(self, studies, load_server_settings())

    def closeEvent(self, event: QCloseEvent) -> None:
        self._orthanc_cache.clear_all()
        super().closeEvent(event)

    @_prof
    def _on_studies_loaded(self, studies: object) -> None:
        study_list = list(studies)  # type: ignore[arg-type]
        n_inst = sum(len(s.instances) for st in study_list for s in st.series)
        logger.info("[MW] _on_studies_loaded: %d studies, %d instances", len(study_list), n_inst)
        self._instance_overlay_cache.clear()
        self._instance_overlay_positions.clear()
        self._study_overlay_positions.clear()
        self._current_overlay_study_uid = None
        self._overlay_sync_instance_uid = None
        self._last_overlay_state = None
        self._viewer.set_results_overlay("")
        populate_started_at = perf_counter()
        self._gallery.populate(study_list)
        populate_elapsed_ms = (perf_counter() - populate_started_at) * 1000.0
        logger.info(
            "tree_populate_done studies=%d duration_ms=%.2f",
            len(study_list),
            populate_elapsed_ms,
        )
        self._gallery.request_visible_previews()

    def _on_scan_failed(self, message: str) -> None:
        from echo_personal_tool.infrastructure.i18n import tr
        QMessageBox.warning(self, tr("error.scan_failed"), message)

    def _on_instance_selected(self, selected: object) -> None:
        if not isinstance(selected, InstanceMetadata):
            return
        modifiers = QApplication.keyboardModifiers()
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            if not self._layout_config.multiview:
                from dataclasses import replace
                self._layout_config = replace(self._layout_config, multiview=True)
                self._rebuild_layout()
            self._load_instance_into_viewer2(selected)
            return
        self._click_to_frame_started_at = perf_counter()
        previous = self._controller.state_manager.snapshot.instance
        if previous is not None:
            self._instance_overlay_cache[previous.sop_instance_uid] = (
                self._viewer.results_overlay_text()
            )
            if self._viewer.results_overlay_custom_position():
                x_ratio, y_ratio = self._viewer.results_overlay_position()
                self._instance_overlay_positions[previous.sop_instance_uid] = (x_ratio, y_ratio)
                if self._viewer._results_overlay_label._pinned:
                    study_uid = self._controller._resolve_study_uid(previous)
                    self._study_overlay_positions[study_uid] = (x_ratio, y_ratio)
            frame_index = self._controller.state_manager.snapshot.current_frame_index
            self._controller.save_doppler_for_frame(
                previous.sop_instance_uid,
                frame_index,
                self._viewer.get_doppler_dto(),
            )
            calibration = self._viewer.get_doppler_calibration_state()
            self._controller.save_current_doppler_calibration(calibration)
            if calibration is not None:
                self._controller.save_doppler_calibration_for_frame(
                    previous.sop_instance_uid,
                    frame_index,
                    calibration,
                )
            mmode_cal = self._viewer.get_mmode_calibration_state()
            if mmode_cal is not None:
                self._controller.on_mmode_calibration_changed(mmode_cal)
        label = _loaded_file_label(selected)
        self._system_bar.set_study_context(label)
        self._controller.load_instance(selected)
        self._restore_results_overlay_position(selected.sop_instance_uid)

    def _load_instance_into_viewer2(self, instance: InstanceMetadata) -> None:
        self._ensure_viewer2()
        if instance.path is None:
            return
        self._viewer2_instance = instance
        self._viewer2_frame_index = 0
        self._load_viewer2_frame(0)

    def _load_viewer2_frame(self, frame_index: int) -> None:
        if self._viewer2 is None or self._viewer2_instance is None:
            return
        instance = self._viewer2_instance
        cache = self._controller._frame_cache
        if cache is not None and cache.is_ready(instance.path):
            try:
                pixels = cache.get(frame_index)
                self._on_viewer2_frame_loaded(np.asarray(pixels), instance)
                return
            except (RuntimeError, IndexError):
                pass
        from echo_personal_tool.application.workers.frame_loader_worker import FrameLoaderWorker
        worker = FrameLoaderWorker(
            instance.path, frame_index, instance.media_format,
            total_frames=instance.number_of_frames,
        )
        worker.signals.finished.connect(
            lambda pixels, inst=instance: self._on_viewer2_frame_loaded(pixels, inst)
        )
        worker.signals.failed.connect(lambda msg: self._show_status(f"viewer2 load failed: {msg}"))
        QThreadPool.globalInstance().start(worker)

    def _on_viewer2_frame_selected(self, frame_index: int) -> None:
        self._viewer2_frame_index = frame_index
        self._load_viewer2_frame(frame_index)

    def _on_viewer2_frame_loaded(self, pixels: object, instance: InstanceMetadata) -> None:
        if self._viewer2 is None:
            return
        image = np.asarray(pixels)
        self._viewer2.show_frame(image)

    def _toggle_viewer2_playback(self) -> None:
        """Toggle playback for viewer2 independently."""
        if self._viewer2_instance is None or self._viewer2 is None:
            return
        self._viewer2_playing = not self._viewer2_playing
        if self._viewer2_playing:
            self._start_viewer2_playback()
        else:
            self._stop_viewer2_playback()

    def _start_viewer2_playback(self) -> None:
        """Start playback timer for viewer2."""
        if not self._viewer2_playing or self._viewer2_instance is None:
            return
        instance = self._viewer2_instance
        total = instance.number_of_frames or 1
        self._viewer2_total_frames = total
        frame_time_ms = instance.frame_time_ms or 33.3
        self._viewer2_timer = QTimer(self)
        self._viewer2_timer.setInterval(int(frame_time_ms))
        self._viewer2_timer.timeout.connect(self._viewer2_tick)
        self._viewer2_timer.start()

    def _stop_viewer2_playback(self) -> None:
        """Stop playback timer for viewer2."""
        if hasattr(self, "_viewer2_timer") and self._viewer2_timer is not None:
            self._viewer2_timer.stop()
            self._viewer2_timer = None

    def _viewer2_tick(self) -> None:
        """Advance viewer2 by one frame during playback."""
        if not self._viewer2_playing or self._viewer2_instance is None:
            self._stop_viewer2_playback()
            return
        self._viewer2_frame_index += 1
        if self._viewer2_frame_index >= self._viewer2_total_frames:
            self._viewer2_frame_index = 0
        self._load_viewer2_frame(self._viewer2_frame_index)

    def _sync_viewer2_state(self) -> None:
        """Sync viewer2 display with controller's current instance."""
        if self._viewer2 is None:
            return
        state = self._controller.state_manager.snapshot
        if state.instance is not None:
            # Show same instance in viewer2 if not already loaded
            if self._viewer2_instance != state.instance:
                self._load_instance_into_viewer2(state.instance)
        elif self._viewer2_instance is not None:
            self._viewer2_instance = None
            self._viewer2_playing = False
            self._stop_viewer2_playback()

    def _on_state_changed_for_viewer2(self, state: ViewerState) -> None:
        """Sync viewer2 when main viewer changes instance."""
        if self._viewer2 is None:
            return
        # If main viewer changed instance, sync viewer2 to show same instance
        if state.instance is not None and self._viewer2_instance != state.instance:
            self._load_instance_into_viewer2(state.instance)

    @_prof
    def _on_frame_loaded(self, pixels: object) -> None:
        instance_switch = self._click_to_frame_started_at is not None
        if instance_switch:
            elapsed_ms = (perf_counter() - self._click_to_frame_started_at) * 1000.0
            logger.info("click_to_frame_loaded duration_ms=%.2f", elapsed_ms)
            self._click_to_frame_started_at = None
        image = np.asarray(pixels)
        is_playing = self._controller.state_manager.snapshot.is_playing
        scroll_active = self._controller.is_scroll_active()
        slider_nav = self._slider_navigating
        self._slider_navigating = False
        if is_playing or scroll_active:
            self._viewer.show_frame_fast(image)
        elif instance_switch:
            self._viewer.show_frame_fast(image)
            QTimer.singleShot(0, lambda: self._deferred_instance_switch_restore(image, is_playing))
        else:
            self._viewer.show_frame(image)
            self._viewer.reposition_overlays()
            self._viewer.refresh_dicom_tags_overlay()
            self._restore_doppler_for_current_instance()
            self._restore_mmode_for_current_instance()
            self._sync_doppler_tool_availability()
            if self._user_preferences.auto_play and not is_playing and not slider_nav:
                self._controller.toggle_playback()
            if self._controller.needs_manual_calibration():
                self._viewer._auto_calibration_succeeded = False
                if self._controller.try_auto_depth_calibration(image):
                    self._viewer.show_calibration_ok_overlay()
                elif self._viewer.start_calibration_caliper():
                    self._show_status(
                        tr("status.calibration_click")
                    )

    def _deferred_instance_switch_restore(self, image: np.ndarray, is_playing: bool) -> None:
        self._viewer.show_frame(image)
        self._viewer.reposition_overlays()
        self._viewer.refresh_dicom_tags_overlay()
        self._viewer._refresh_frame_overlays()
        self._restore_doppler_for_current_instance()
        self._restore_mmode_for_current_instance()
        self._sync_doppler_tool_availability()
        if self._user_preferences.auto_play and not is_playing:
            self._controller.toggle_playback()
        if self._controller.needs_manual_calibration():
            self._viewer._auto_calibration_succeeded = False
            if self._controller.try_auto_depth_calibration(image):
                self._viewer.show_calibration_ok_overlay()
            elif self._viewer.start_calibration_caliper():
                self._show_status(
                    tr("status.calibration_click")
                )

    def _on_slider_frame_selected(self, index: int) -> None:
        self._slider_navigating = True
        self._controller.state_manager.set_frame(index)

    @_prof
    def _on_scroll_settled(self) -> None:
        if self._controller.state_manager.snapshot.is_playing:
            return
        self._viewer.refresh_after_scroll()
        self._viewer.reposition_overlays()
        self._viewer.refresh_dicom_tags_overlay()
        self._restore_doppler_for_current_instance()
        self._restore_mmode_for_current_instance()
        self._sync_doppler_tool_availability()

    @_prof
    def _on_frame_load_failed(self, message: str) -> None:
        from echo_personal_tool.infrastructure.i18n import tr
        self._click_to_frame_started_at = None
        QMessageBox.warning(self, tr("error.load_failed"), message)

    def _show_status(self, message: str) -> None:
        self._system_bar.set_status_message(message)
        if self.statusBar():
            self.statusBar().showMessage(message)

    @_prof
    def _on_state_changed(self, state: object) -> None:
        if not isinstance(state, ViewerState):
            return
        instance_uid = state.instance.sop_instance_uid if state.instance else None
        instance_changed = instance_uid != self._overlay_sync_instance_uid
        content_changed = False
        if self._last_overlay_state is not None:
            previous = self._last_overlay_state
            content_changed = (
                previous.contours != state.contours
                or previous.linear_measurements != state.linear_measurements
                or previous.measurement_snapshot != state.measurement_snapshot
            )
        if instance_changed:
            self._overlay_sync_instance_uid = instance_uid
            self._restore_results_overlay_position(instance_uid)
            self._sync_results_overlay(state)
        elif content_changed:
            self._sync_results_overlay(state)
        self._last_overlay_state = state
        if instance_changed:
            self._refresh_dicom_inspector()
        self._update_properties_panel(state)

    def _update_properties_panel(self, state: ViewerState) -> None:
        """Update the properties panel with current instance info."""
        panel = self._tool_panel.properties_panel
        if state.instance is None:
            panel.clear_all()
            return
        inst = state.instance
        # Instance info
        panel.update_instance_info(
            modality=inst.modality or "",
            series_desc=inst.series_description or "",
            frame_rate=1000.0 / inst.frame_time_ms if inst.frame_time_ms else None,
            pixel_spacing=f"{inst.pixel_spacing[0]:.2f}×{inst.pixel_spacing[1]:.2f} mm" if inst.pixel_spacing else "",
        )
        # Latest measurement
        if state.linear_measurements:
            m = state.linear_measurements[-1]
            panel.update_measurement_info(
                label=m.label,
                value_mm=m.millimeter_length,
                start=m.start,
                end=m.end,
            )
        else:
            panel.update_measurement_info()

    def _restore_doppler_for_current_frame(self) -> None:
        instance = self._controller.state_manager.snapshot.instance
        if instance is None:
            return
        frame_index = self._controller.state_manager.snapshot.current_frame_index
        calibration = self._controller.get_doppler_calibration_for_instance_frame(
            instance.sop_instance_uid,
            frame_index,
        )
        if calibration is None and instance.media_format == "dicom":
            calibration = self._controller.get_doppler_calibration_for_instance(
                instance.sop_instance_uid
            )
            if calibration is not None and instance.number_of_frames > 1:
                calibration = None
        dto = self._controller.get_doppler_dto_for_instance_frame(
            instance.sop_instance_uid,
            frame_index,
        )
        self._viewer.restore_doppler_state(calibration, dto)
        self._doppler_frame_context = (instance.sop_instance_uid, frame_index)

    def _restore_doppler_for_current_instance(self) -> None:
        self._restore_doppler_for_current_frame()

    def _on_doppler_frame_changing(self, previous_frame: int, dto: object) -> None:
        from echo_personal_tool.domain.models.doppler import DopplerMeasurementDTO

        instance = self._controller.state_manager.snapshot.instance
        if instance is None:
            return
        if isinstance(dto, DopplerMeasurementDTO):
            self._controller.save_doppler_for_frame(
                instance.sop_instance_uid,
                previous_frame,
                dto,
            )
        calibration = self._viewer.get_doppler_calibration_state()
        if calibration is not None:
            self._controller.save_doppler_calibration_for_frame(
                instance.sop_instance_uid,
                previous_frame,
                calibration,
            )

    def _on_doppler_frame_changed(self, frame_index: int) -> None:
        self._restore_doppler_for_current_frame()

    def _restore_mmode_for_current_instance(self) -> None:
        instance = self._controller.state_manager.snapshot.instance
        if instance is None:
            return
        calibration = self._controller.get_mmode_calibration_for_instance(
            instance.sop_instance_uid
        )
        self._viewer.restore_mmode_state(calibration)

    def _ensure_mmode_ready_for_tapse(self) -> bool:
        if self._viewer.is_mmode_calibrated():
            return True
        instance = self._controller.state_manager.snapshot.instance
        if instance is not None:
            saved = self._controller.get_mmode_calibration_for_instance(
                instance.sop_instance_uid
            )
            if saved is not None:
                self._viewer.apply_mmode_calibration_state(saved)
                return True
        if self._viewer.try_apply_mmode_from_dicom_or_heuristic():
            state = self._viewer.get_mmode_calibration_state()
            if state is not None:
                self._controller.on_mmode_calibration_changed(state)
            return True
        if self._viewer.start_mmode_panel_calibration():
            self._show_status(
                tr("status.mmode_tapse_click")
            )
        else:
            self._show_status(tr("status.load_first_frame_mmode"))
        return False

    @_prof
    def _sync_results_overlay(self, state: ViewerState) -> None:
        time_calibrated = self._viewer.is_doppler_time_calibrated()
        instance = state.instance
        instance_uid = instance.sop_instance_uid if instance is not None else None

        overlay_snapshot = self._controller.compute_overlay_snapshot(state)
        fresh_text = format_results_overlay(
            overlay_snapshot,
            time_calibrated=time_calibrated,
            length_display_unit=self._user_preferences.length_display_unit,
        )

        if instance_uid is not None:
            if fresh_text.strip():
                self._instance_overlay_cache[instance_uid] = fresh_text
                display_text = fresh_text
            else:
                self._instance_overlay_cache.pop(instance_uid, None)
                display_text = ""
        else:
            display_text = fresh_text

        self._viewer.set_results_overlay(display_text)

        snapshot = state.measurement_snapshot
        if snapshot is not None:
            self._tool_panel.set_patient_metrics(snapshot.height_cm, snapshot.weight_kg)
        self._sync_doppler_tool_availability()

    def _show_results_dialog(self) -> None:
        snapshot = self._controller.state_manager.snapshot.measurement_snapshot
        default_name = "echo_measurements.pdf"
        instance = self._controller.state_manager.snapshot.instance
        if instance is not None and instance.path is not None:
            default_name = f"{instance.path.stem}_results.pdf"
        dialog = MeasurementResultsDialog(
            snapshot,
            parent=self,
            default_pdf_name=default_name,
            length_display_unit=self._user_preferences.length_display_unit,
            pdf_font_size=self._user_preferences.pdf_font_size,
        )
        dialog.exec()

    def _sync_doppler_tool_availability(self) -> None:
        self._tool_panel.set_doppler_tool_availability(
            time_ok=self._viewer.is_doppler_time_calibrated(),
        )

    def _ensure_doppler_ready(self, *, require_time: bool = False) -> bool:
        if self._viewer._current_frame is None:
            self._show_status(tr("status.load_first_frame_doppler"))
            return False
        if require_time:
            if self._viewer.is_doppler_time_calibrated():
                return True
            self._show_status(
                tr("status.doppler_no_time")
            )
            return False
        return True

    def _wire_ui(self) -> None:
        self._system_bar.open_folder_requested.connect(self._open_folder)
        self._system_bar.load_from_server_requested.connect(self._open_orthanc_dialog)
        self._system_bar.send_to_server_requested.connect(self._send_to_server)
        self._system_bar.reset_session_requested.connect(self._on_reset_measurements_requested)
        self._system_bar.caliper_requested.connect(lambda: self._on_caliper_requested())
        self._system_bar.calibration_requested.connect(self._on_calibration_requested)
        self._system_bar.doppler_calibration_requested.connect(
            self._on_doppler_calibration_requested
        )
        self._system_bar.settings_requested.connect(self._show_user_preferences)
        self._system_bar.references_requested.connect(self._show_references)
        self._system_bar.minimize_requested.connect(self.showMinimized)
        self._system_bar.maximize_requested.connect(self._toggle_maximize)
        self._system_bar.close_requested.connect(self.close)
        self._system_bar.layout_customize_requested.connect(self._show_layout_menu)
        self._tool_panel.action_requested.connect(self._on_measure_action)
        self._tool_panel.patient_metrics_changed.connect(
            self._controller.on_patient_metrics_changed
        )
        self._tool_panel.results_requested.connect(self._show_results_dialog)
        self._tool_panel.magnetic_snap_changed.connect(self._on_magnetic_snap_changed)
        self._tool_panel.auto_play_changed.connect(self._on_auto_play_changed)
        self._controller.speckle_result_ready.connect(self._on_speckle_result_ready)
        self._apply_magnetic_snap_from_preferences()

    def _apply_magnetic_snap_from_preferences(self) -> None:
        enabled = self._user_preferences.magnetic_snap_enabled
        with QSignalBlocker(self._tool_panel.controls._magnetic_snap_check):
            self._tool_panel.controls._magnetic_snap_check.setChecked(enabled)
        self._viewer.set_magnetic_snap_enabled(enabled)

    def _on_auto_play_changed(self, enabled: bool) -> None:
        self._user_preferences.auto_play = enabled
        save_user_preferences(self._user_preferences)

    def _on_measure_action(
        self,
        action: object,
        view: str,
        phase: str,
        extra: str = "",
    ) -> None:
        if not isinstance(action, MeasurementAction):
            return
        if action in {MeasurementAction.MANUAL_SIMPSON, MeasurementAction.MBS_SIMPSON}:
            self._controller.set_simpson_workflow_context(
                phase=phase,
                view=view,
                chamber="LV",
            )
        handlers: dict[MeasurementAction, object] = {
            MeasurementAction.CALIBRATION: self._on_calibration_requested,
            MeasurementAction.RESET: self._on_reset_measurements_requested,
            MeasurementAction.SPLINE_AREA: self._on_spline_area_requested,
            MeasurementAction.SPLINE_VOLUME: self._on_spline_volume_requested,
            MeasurementAction.MANUAL_SIMPSON: (
                lambda: self._on_manual_simpson_requested(view, phase)
            ),
            MeasurementAction.MBS_SIMPSON: (lambda: self._on_mbs_simpson_requested(view, phase)),
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
            MeasurementAction.RV_FAC: self._on_rv_fac,
            MeasurementAction.AUTO_SEGMENT: self._request_auto_segment_shortcut,
            MeasurementAction.SPECKLE_TRACKING: self._on_speckle_tracking_requested,
        }
        if action == MeasurementAction.CALIPER:
            self._on_caliper_requested(extra or None)
            return
        if action == MeasurementAction.DOPPLER_PEAK:
            self._on_doppler_peak_tool(extra or None)
            return
        if action == MeasurementAction.DOPPLER_MITRAL_INFLOW:
            self._on_doppler_mitral_inflow()
            return
        if action == MeasurementAction.DOPPLER_INTERVAL:
            self._on_doppler_interval_tool(extra or None)
            return
        if action == MeasurementAction.DOPPLER_TRACE:
            self._on_doppler_trace_tool(extra or "VTI")
            return
        handler = handlers.get(action)
        if handler is not None:
            handler()  # type: ignore[operator]

    def _on_spline_area_requested(self) -> None:
        self._tool_panel.measure.clear_action_highlight()
        if self._viewer.start_generic_area_contour():
            self._viewer.clear_frame_overlay()
            self._show_status(tr("status.area_tool"))
        else:
            self._show_status("Load a frame first (or finish the active tool)")

    def _on_spline_volume_requested(self) -> None:
        self._tool_panel.measure.clear_action_highlight()
        if self._viewer.start_generic_volume_contour():
            self._viewer.clear_frame_overlay()
            self._show_status(tr("status.volume_tool"))
        else:
            self._show_status("Load a frame first (or finish the active tool)")

    def _on_doppler_peak_tool(self, label: str | None = None) -> None:
        if not self._ensure_doppler_ready():
            return
        self._viewer.set_doppler_tool_mode("peak", peak_label=label or "E")
        self._show_status(tr("status.doppler_peak_tool", label=label or 'E'))

    def _on_doppler_mitral_inflow(self) -> None:
        if not self._ensure_doppler_ready(require_time=True):
            return
        if self._viewer.start_mitral_inflow_workflow():
            self._show_status(tr("status.mitral_inflow_tool"))
        else:
            self._show_status(tr("status.load_first_frame_doppler"))

    def _on_doppler_interval_tool(self, label: str | None = None) -> None:
        if not self._ensure_doppler_ready(require_time=True):
            return
        self._viewer.set_doppler_tool_mode("interval", interval_label=label or "DT")
        self._show_status(tr("status.doppler_interval_tool", label=label or 'DT'))

    def _on_doppler_trace_tool(self, trace_label: str = "VTI") -> None:
        if not self._ensure_doppler_ready(require_time=True):
            return
        self._viewer.set_doppler_tool_mode("trace", trace_label=trace_label)
        self._show_status(
            tr("status.doppler_trace_tool", trace_label=trace_label)
        )

    def _on_rv_s_prime(self) -> None:
        if not self._ensure_doppler_ready():
            return
        self._viewer.set_doppler_tool_mode("peak", peak_label="s_sept")
        self._show_status(tr("status.rv_s_prime_tool"))

    def _on_rv_fac(self) -> None:
        phase = "ES" if self._rv_fac_awaiting_es else "ED"
        if not self._start_chamber_contour(
            "RV",
            phase,
            "A4C",
            overlay=f"RV FAC {phase}: TV lateral → septal → free wall",
            status=(
                f"RV FAC {phase}: 1) TV lateral  2) TV septal  3) free wall · Enter — {tr('status.ready_done', line='confirm')}"
            ),
        ):
            self._show_status("Load a frame first or cancel the active tool (Esc)")

    def _wire_measurement_tools(self) -> None:
        """Backward-compatible alias for tests."""
        self._wire_ui()

    def _on_caliper_requested(self, label: str | None = None) -> None:
        if label and self._viewer.start_linear_caliper_for(label):
            self._show_status(tr("status.linear_caliper_tool", label=label))
        elif (label := self._viewer.activate_generic_dist_caliper()):
            self._show_status(tr("status.linear_caliper_tool", label=label))
        else:
            self._show_status("Load a frame first")

    @_prof
    def _on_reset_measurements_requested(self) -> None:
        if self._user_preferences.confirm_reset:
            answer = QMessageBox.question(
                self,
                tr("status.reset_session_title"),
                tr("status.reset_session_body"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._lav_bi_active = False
        self._rv_fac_awaiting_es = False
        self._instance_overlay_cache.clear()
        self._viewer.cancel_active_tool()
        self._viewer.set_results_overlay("")
        self._viewer.clear_doppler_calibration_display()
        self._viewer.clear_doppler_measurements()
        self._viewer.clear_speckle_overlay()
        if self._ste_dialog is not None:
            self._ste_dialog.clear()
        self._viewer.reset_dist_caliper_serial()
        self._controller.reset_measurements_and_calibration()
        self._viewer.set_results_overlay("")
        self._last_overlay_state = None
        if self._viewer._current_frame is None:
            self._show_status(tr("status.measurements_reset"))
            return
        if self._controller.needs_manual_calibration():
            self._viewer._auto_calibration_succeeded = False
            if self._controller.try_auto_depth_calibration(self._viewer._current_frame):
                self._viewer.show_calibration_ok_overlay()
            else:
                self._viewer.start_calibration_caliper()
        elif self._viewer.is_doppler_context():
            if self._viewer.start_doppler_scale_calibration():
                self._show_status(self._viewer.doppler_calibration_prompt())
            else:
                self._show_status(tr("status.load_first_frame_doppler"))
        self._sync_doppler_tool_availability()
        self._show_status(tr("status.measurements_reset"))

    def _on_calibration_requested(self) -> None:
        if self._viewer._current_frame is None:
            self._show_status("Load a frame first")
            return
        self._viewer.toggle_calibration_caliper()
        if self._viewer.is_calibration_active:
            self._show_status(
                tr("status.calibration_bmode_click")
            )
        else:
            self._show_status(tr("status.calibration_cancelled"))

    def _get_current_frame_index(self) -> int | None:
        snapshot = self._controller.state_manager.snapshot
        if snapshot.instance is None:
            return None
        return snapshot.current_frame_index

    def _mark_current_frame_as_ed(self) -> None:
        idx = self._get_current_frame_index()
        if idx is None:
            self._show_status("Load a frame first")
            return
        self._manual_ed_frame = idx
        self._show_status(tr("status.ed_frame", idx=idx))

    def _mark_current_frame_as_es(self) -> None:
        idx = self._get_current_frame_index()
        if idx is None:
            self._show_status("Load a frame first")
            return
        self._manual_es_frame = idx
        self._show_status(tr("status.es_frame", idx=idx))

    def _on_speckle_tracking_requested(self) -> None:
        if self._viewer._current_frame is None:
            self._show_status("Load a frame first")
            return
        contour = self._viewer.get_lv_contour()
        if contour is None:
            self._show_status(tr("status.speckle_no_contour"))
            return
        current_idx = self._get_current_frame_index() or 0
        cache = self._controller._frame_cache
        n_frames = cache._total_frames if cache else 0
        settings = SpeckleSettingsDialog(
            self,
            current_frame=current_idx,
            manual_ed=self._manual_ed_frame,
            manual_es=self._manual_es_frame,
            n_frames=n_frames,
        )
        from echo_personal_tool.presentation.ui_animations import exec_animated
        if exec_animated(settings) != QDialog.DialogCode.Accepted:
            self._show_status(tr("status.speckle_cancelled"))
            return
        config = settings.get_config()
        config_preset = settings.selected_preset_name()
        self._manual_ed_frame = settings.manual_ed
        self._manual_es_frame = settings.manual_es
        self._viewer.clear_speckle_overlay()
        if self._manual_ed_frame is not None and self._manual_es_frame is not None:
            phase_hint = f"ED={self._manual_ed_frame}, ES={self._manual_es_frame}"
        else:
            phase_hint = tr("status.speckle_phase_hint")
        self._show_status(tr("status.speckle_compute", phase_hint=phase_hint))
        self._controller.run_speckle_tracking(
            contour,
            config=config,
            config_preset=config_preset,
            manual_ed=self._manual_ed_frame,
            manual_es=self._manual_es_frame,
        )

    def _ensure_ste_dialog(self) -> SteResultsDialog:
        if self._ste_dialog is None:
            self._ste_dialog = SteResultsDialog(self)
        return self._ste_dialog

    def _on_speckle_result_ready(self, result: object) -> None:
        from echo_personal_tool.domain.models.speckle import StrainResult

        if not isinstance(result, StrainResult):
            return
        gls = result.gls
        dialog = self._ensure_ste_dialog()
        dialog.update_results(
            result.longitudinal,
            result.radial,
            result.segment_strain,
            result.segment_quality,
            gls=gls,
            ed_index=result.ed_index,
            es_index=result.es_index,
            window_start=result.tracking_window_start,
            window_end=result.tracking_window_end,
        )
        quality_pct = result.tracking_quality_mean * 100.0
        drift = "ON" if result.drift_compensation_applied else "OFF"
        preset_name = self._format_speckle_preset_name(result.config_preset)
        self._show_status(
            f"GLS: {gls:.1f}% | Quality: {quality_pct:.0f}% | Drift comp: {drift} | Preset: {preset_name}"
        )
        self._viewer.show_speckle_result(result)

    @staticmethod
    def _format_speckle_preset_name(preset_name: str) -> str:
        mapping = {
            "echo_pac": "EchoPAC",
            "tomtec": "TomTec",
            "debug": "Debug",
        }
        return mapping.get(preset_name, preset_name)

    def _on_doppler_calibration_requested(self) -> None:
        if self._viewer._current_frame is None:
            self._show_status("Load a frame first")
            return
        if self._viewer.start_doppler_scale_calibration():
            self._show_status(self._viewer.doppler_calibration_prompt())
        else:
            self._show_status(tr("status.load_first_frame"))

    def _on_manual_simpson_requested(self, view: str, phase: str) -> None:
        if self._viewer.start_contour(phase=phase, view=view, chamber="LV"):
            self._viewer.clear_frame_overlay()
            self._viewer.append_frame_overlay(
                f"Manual LV {view} {phase}: annulus septal → lateral → apex"
            )
            self._show_status(f"Manual Simpson {view} {phase}: click annulus septal, lateral, apex")
        else:
            self._show_status("Load a frame first or cancel the active tool (Esc)")

    def _on_mbs_simpson_requested(self, view: str, phase: str) -> None:
        if view.upper() != "A4C":
            self._show_status(tr("status.a2c_auto_next"))
            return
        self._controller.set_simpson_workflow_context(phase=phase, view=view, chamber="LV")
        self._viewer.clear_frame_overlay()
        self._viewer.append_frame_overlay(tr("status.lv_auto_segmenting", view=view, phase=phase))
        self._controller.request_auto_segment(phase=phase, view=view, chamber="LV")

    def _maybe_prompt_es_auto(
        self,
        view: str,
        phase: str,
        *,
        mode: Literal["manual", "mbs"],
    ) -> None:
        if phase.upper() != "ED":
            return
        view_label = "4C" if view.upper() == "A4C" else "2C"
        es_name = "ESV Auto" if mode == "mbs" else "Systole"
        status = tr("status.lv_go_systole", es_name=es_name, view_label=view_label)
        if self._controller.state_manager.snapshot.effective_pixel_spacing is None:
            status += tr("status.lv_no_pixel_spacing")
        self._show_status(status)
        self._viewer.append_frame_overlay(status)

    def _on_es_button_pressed(self, view: str, phase: str) -> None:
        del view, phase

    def _on_lv2d_all_diastole(self) -> None:
        self._tool_panel.measure.clear_action_highlight()
        if self._viewer.start_linear_caliper_sequence(("IVSd", "LVEDD", "LVPWd")):
            self._viewer.clear_frame_overlay()
            self._viewer.append_frame_overlay(tr("status.lv_diastole_overlay"))
            self._show_status(tr("status.lv_diastole_sequence"))
        else:
            self._show_status(tr("status.load_frame"))

    def _on_linear_caliper_sequence_completed(self) -> None:
        self._tool_panel.measure.highlight_action(MeasurementAction.LV2D_ES)
        self._show_status(tr("status.lv_diastole_done"))

    def _on_lv2d_es(self) -> None:
        if self._viewer.start_linear_caliper_for("LVESD"):
            self._show_status(tr("status.lv_systole_place"))
        else:
            self._show_status(tr("status.load_frame"))

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
        starter = self._viewer.start_model_contour if model else self._viewer.start_contour
        if not starter(chamber=chamber, phase=phase, view=view):
            return False
        self._viewer.clear_frame_overlay()
        self._viewer.append_frame_overlay(overlay)
        self._show_status(status)
        return True

    def _on_la_diameter(self) -> None:
        if self._viewer.start_linear_caliper_for("LA"):
            self._show_status("Left atrium: place AP diameter caliper")
        else:
            self._show_status("Load a frame first")

    def _on_lav_4c(self) -> None:
        self._lav_bi_active = False
        if self._start_chamber_contour(
            "LA",
            "ES",
            "A4C",
            overlay=tr("status.lav4c_overlay"),
            status=tr("status.lav4c_status"),
        ):
            pass
        else:
            self._show_status("Load a frame first or cancel the active tool (Esc)")

    def _on_lav_bi(self) -> None:
        has_a4c = self._has_chamber_contour("LA", "A4C", "ES")
        has_a2c = self._has_chamber_contour("LA", "A2C", "ES")
        if has_a4c and not has_a2c:
            self._lav_bi_active = True
            if self._start_chamber_contour(
                "LA",
                "ES",
                "A2C",
                overlay=tr("status.lav2c_overlay"),
                status=tr("status.lav2c_status"),
            ):
                pass
            else:
                self._show_status("Load a frame first or cancel the active tool (Esc)")
            return
        self._lav_bi_active = True
        if self._start_chamber_contour(
            "LA",
            "ES",
            "A4C",
            overlay=tr("status.lavbi_overlay"),
            status=tr("status.lavbi_status"),
        ):
            pass
        else:
            self._show_status("Load a frame first or cancel the active tool (Esc)")

    def _on_ra_diameter(self) -> None:
        if self._viewer.start_linear_caliper_for("RA"):
            self._show_status("Right atrium: place diameter caliper")
        else:
            self._show_status("Load a frame first")

    def _on_ra_area(self) -> None:
        if not self._start_chamber_contour(
            "RA",
            "ES",
            "A4C",
            overlay=tr("status.ra_s_overlay"),
            status=tr("status.ra_s_status"),
        ):
            self._show_status("Load a frame first or cancel the active tool (Esc)")

    def _on_rav_volume(self) -> None:
        if self._start_chamber_contour(
            "RA",
            "ES",
            "A4C",
            overlay="RAV 4C: TV septal → lateral → apex",
            status=tr("status.rav4c_status"),
        ):
            pass
        else:
            self._show_status("Load a frame first or cancel the active tool (Esc)")

    def _on_contour_completed(self, contour: object) -> None:
        if not isinstance(contour, Contour):
            return
        chamber = contour.chamber.upper()
        if chamber not in {"LV", "LA", "RA", "RV", "AREA", "VOL"}:
            return
        extra_lines: tuple[str, ...] = ()
        if chamber in {"AREA", "VOL"}:
            spacing = self._controller.state_manager.snapshot.effective_pixel_spacing
            calibrated = spacing is not None
            from echo_personal_tool.domain.services.planimeter_formatter import (
                format_planimeter_overlay_line,
            )

            line = format_planimeter_overlay_line(
                contour,
                spacing,
                spacing_calibrated=calibrated,
            )
            if line:
                self._show_status(tr("status.ready_done", line=line))
            self._viewer._refresh_frame_overlays()
            self._sync_results_overlay(self._controller.state_manager.snapshot)
            return
        if not contour.is_open_arc:
            return

        if chamber == "LV" and contour.phase.upper() == "ED":
            mode = "mbs" if contour.source in {"model", "ai"} else "manual"
            view = contour.view.upper()
            es_action = (
                MeasurementAction.MBS_SIMPSON if mode == "mbs" else MeasurementAction.MANUAL_SIMPSON
            )
            self._tool_panel.measure.highlight_action(es_action, view=view, phase="ES")
            view_label = "4C" if view == "A4C" else "2C"
            es_name = "ESV Auto" if mode == "mbs" else "LVEF Simpson ESV"
            extra_lines = (tr("status.press_es", es_name=es_name, view_label=view_label),)
            status = tr("status.press_es", es_name=es_name, view_label=view_label)
            if self._controller.state_manager.snapshot.effective_pixel_spacing is None:
                status += tr("status.lv_no_pixel_spacing")
            self._show_status(status)
        elif chamber == "LV" and contour.phase.upper() == "ES":
            self._tool_panel.measure.clear_action_highlight()
        elif chamber == "LA" and contour.phase.upper() == "ES":
            if self._lav_bi_active and contour.view.upper() == "A4C":
                self._tool_panel.measure.highlight_action(MeasurementAction.LAV_BI)
                extra_lines = (
                    *extra_lines,
                    tr("status.lavbi_go_2c"),
                )
            elif contour.view.upper() == "A2C":
                self._lav_bi_active = False
                self._tool_panel.measure.clear_action_highlight()

            spacing, spacing_calibrated = self._viewer._effective_pixel_spacing()
            from echo_personal_tool.domain.calculations.chamber_simpson import (
                biplane_es_volume_ml,
                es_volume_from_view,
            )
            from echo_personal_tool.domain.calculations.lvef_simpson import format_contour_overlay

            line = format_contour_overlay(
                contour,
                spacing,
                spacing_calibrated=spacing_calibrated,
            )
            self._show_status(line)
            snapshot = self._controller.state_manager.snapshot.measurement_snapshot
            if snapshot is not None and snapshot.la_simpson is not None:
                volume_unit = "mL" if snapshot.spacing_calibrated else "px³"
                lav_4c = es_volume_from_view(snapshot.la_simpson.a4c)
                if lav_4c is not None and contour.view.upper() == "A4C":
                    extra_lines = (
                        *extra_lines,
                        f"LAV 4C: {lav_4c:.1f} {volume_unit}",
                    )
                lav_bi = biplane_es_volume_ml(
                    snapshot.la_simpson.a4c,
                    snapshot.la_simpson.a2c,
                )
                if lav_bi is not None:
                    extra_lines = (
                        *extra_lines,
                        f"LAV Bi: {lav_bi:.1f} {volume_unit}",
                    )
        elif chamber == "RA" and contour.phase.upper() == "ES":
            spacing, spacing_calibrated = self._viewer._effective_pixel_spacing()
            from echo_personal_tool.domain.calculations.chamber_simpson import es_volume_from_view
            from echo_personal_tool.domain.calculations.lvef_simpson import format_contour_overlay

            line = format_contour_overlay(
                contour,
                spacing,
                spacing_calibrated=spacing_calibrated,
            )
            self._show_status(line)
            snapshot = self._controller.state_manager.snapshot.measurement_snapshot
            if snapshot is not None and snapshot.ra_simpson is not None:
                volume_unit = "mL" if snapshot.spacing_calibrated else "px³"
                rav = es_volume_from_view(snapshot.ra_simpson.a4c) or snapshot.ra_simpson.max_volume_ml
                if rav is not None:
                    extra_lines = (
                        *extra_lines,
                        f"RAV 4C: {rav:.1f} {volume_unit}",
                    )
        elif chamber == "RV":
            spacing, spacing_calibrated = self._viewer._effective_pixel_spacing()
            from echo_personal_tool.domain.calculations.rv_fac import format_rv_area_overlay_line

            line = format_rv_area_overlay_line(
                contour,
                spacing,
                spacing_calibrated=spacing_calibrated,
            )
            self._show_status(line)
            phase = contour.phase.upper()
            if phase == "ED":
                self._rv_fac_awaiting_es = True
                self._tool_panel.measure.highlight_action(MeasurementAction.RV_FAC)
                extra_lines = (*extra_lines, tr("status.press_fac"))
            elif phase == "ES":
                self._rv_fac_awaiting_es = False
                self._tool_panel.measure.clear_action_highlight()
                snapshot = self._controller.state_manager.snapshot.measurement_snapshot
                if snapshot is not None and snapshot.rv_fac_percent is not None:
                    extra_lines = (
                        *extra_lines,
                        f"FAC: {snapshot.rv_fac_percent:.1f} %",
                    )

        self._viewer._refresh_frame_overlays(extra_lines=extra_lines)
        self._sync_results_overlay(self._controller.state_manager.snapshot)

    def _on_rv_basal(self) -> None:
        if self._viewer.start_linear_caliper_for("RV basal"):
            self._show_status("RV: place basal diameter caliper")
        else:
            self._show_status("Load a frame first")

    def _on_rv_tapse(self) -> None:
        if not self._ensure_mmode_ready_for_tapse():
            return
        if self._viewer.start_linear_caliper_for("TAPSE"):
            self._show_status(tr("status.rv_tapse_tool"))
        else:
            self._show_status("Load a frame first")

    def eventFilter(self, watched: object, event: QEvent) -> bool:  # type: ignore[override]
        if event.type() == QEvent.Type.MouseButtonPress:
            if watched in (self._viewer, self._viewer._graphics, self._viewer._view):
                self._active_viewer = self._viewer
            elif self._viewer2 is not None and watched in (
                self._viewer2, self._viewer2._graphics, self._viewer2._view,
            ):
                self._active_viewer = self._viewer2
        if event.type() == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
            if watched in (self._viewer, self._viewer._graphics, self._viewer._view):
                if self._handle_key_press(event):
                    return True
            if self._viewer2 is not None and watched in (
                self._viewer2, self._viewer2._graphics, self._viewer2._view,
            ):
                if self._handle_key_press(event):
                    return True
        return super().eventFilter(watched, event)

    @_prof
    def event(self, event) -> bool:  # type: ignore[override]
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Tab:
            v = self._active_viewer or self._viewer
            v.cycle_caliper_label()
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if self._handle_key_press(event):
            return
        super().keyPressEvent(event)

    def _handle_key_press(self, event: QKeyEvent) -> bool:
        v = self._active_viewer or self._viewer
        if event.key() == Qt.Key.Key_Space:
            if self._controller.state_manager.snapshot.decode_in_progress:
                event.accept()
                return True
            self._controller.toggle_playback()
            event.accept()
            return True
        if event.key() == Qt.Key.Key_L and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            v.toggle_linear_caliper()
            event.accept()
            return True
        if event.key() == Qt.Key.Key_K and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            v.toggle_calibration_caliper()
            if v.is_calibration_active:
                self._show_status(
                    tr("status.calibration_click")
                )
            event.accept()
            return True
        if event.key() == Qt.Key.Key_K and event.modifiers() == Qt.KeyboardModifier.ShiftModifier:
            self._controller.clear_manual_calibration()
            event.accept()
            return True
        if event.key() == Qt.Key.Key_Tab:
            v.cycle_caliper_label()
            event.accept()
            return True
        if event.key() == Qt.Key.Key_C and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            if v.start_contour():
                self._show_status("Manual contour: click MA septal, lateral, then arc")
            else:
                self._show_status("Load a frame first (or finish the active contour)")
            event.accept()
            return True
        if event.key() == Qt.Key.Key_M and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            if v.get_doppler_tool_mode() != "none":
                v.set_doppler_tool_mode("peak")
                self._show_status("Doppler peak (M)")
            elif v.start_model_contour():
                self._show_status("MBS-lite: click MA septal, lateral, then apex")
            else:
                self._show_status("Load a frame first (or finish the active contour)")
            event.accept()
            return True
        if event.key() == Qt.Key.Key_T and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            if self._ensure_doppler_ready(require_time=True):
                v.set_doppler_tool_mode("interval")
                self._show_status("Doppler interval (T)")
            event.accept()
            return True
        if event.key() == Qt.Key.Key_V and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            if self._ensure_doppler_ready(require_time=True):
                self._on_doppler_trace_tool("VTI")
            event.accept()
            return True
        if event.key() == Qt.Key.Key_R and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            refined, mode = v.refine_active_open_contour()
            if refined:
                self._controller.on_contours_changed(v.contours())
                if mode.startswith(("step:", "complete")):
                    self._show_status(f"Refine {mode}")
                elif mode == "gradient":
                    self._show_status("Gradient refine (R)")
                else:
                    self._show_status("Geometry smooth (R)")
            else:
                self._show_status(tr("status.no_lv_open_arc"))
            event.accept()
            return True
        if (
            event.key() == Qt.Key.Key_I
            and event.modifiers() == Qt.KeyboardModifier.NoModifier
        ):
            self._request_auto_segment_shortcut()
            event.accept()
            return True
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            trace_active = v.get_doppler_tool_mode() == "trace"
            if trace_active and v.finish_doppler_trace():
                event.accept()
                return True
            if v.finish_contour():
                event.accept()
                return True
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            if v.delete_contour_for_current_phase():
                self._controller.on_contours_changed(v.contours())
                self._show_status(tr("status.contour_deleted"))
            event.accept()
            return True
        if event.key() == Qt.Key.Key_Escape:
            self._cancel_active_tool()
            event.accept()
            return True
        return False
