"""Main application window."""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from time import perf_counter
from typing import Literal

import numpy as np
from PySide6.QtCore import (
    QByteArray,
    QEasingCurve,
    QEvent,
    QPoint,
    QPropertyAnimation,
    QRect,
    QSignalBlocker,
    Qt,
    QThreadPool,
    QTimer,
)
from PySide6.QtGui import QActionGroup, QCloseEvent, QCursor, QKeyEvent
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool import __version__
from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.application.download_history import DownloadHistory
from echo_personal_tool.application.profile_settings import (
    active_profile_name,
    get_profile_capabilities,
    profile_display_name,
)
from echo_personal_tool.application.protocol_runner import EscapeResult, StepAction
from echo_personal_tool.application.protocol_session import ProtocolSession
from echo_personal_tool.application.recent_folders import make_recent_folder_store
from echo_personal_tool.application.report_conclusion import ConclusionAutofillResult, autofill_conclusion
from echo_personal_tool.application.report_export import ReportExportError, export_report_document_pdf
from echo_personal_tool.application.report_phrases import ReportPhraseStore, make_report_phrase_store
from echo_personal_tool.application.server_io import OrthancCache, make_orthanc_session_cache
from echo_personal_tool.application.tab_session import (
    TAB_ORIGIN_EMPTY,
    TAB_ORIGIN_FOLDER,
    TAB_ORIGIN_SERVER,
    TabSessionManager,
)
from echo_personal_tool.domain.doppler_catalog import HEART_RATE_INTERVAL_LABEL
from echo_personal_tool.domain.models import Contour, InstanceMetadata, StudyMetadata
from echo_personal_tool.domain.models.multiview import PaneId, PlaybackMode
from echo_personal_tool.domain.models.viewer_state import ViewerState
from echo_personal_tool.domain.protocol_definitions import PROTOCOLS, PROTOCOLS_BY_ID
from echo_personal_tool.domain.services.measurement_results_formatter import (
    format_results_overlay,
    format_results_overlay_html,
)
from echo_personal_tool.domain.services.report_builder import (
    PatientInfo,
    ReportDocument,
    build_report_document,
    with_extra_values,
)
from echo_personal_tool.domain.services.report_sections import not_evaluated_values
from echo_personal_tool.infrastructure.i18n import get_language, tr
from echo_personal_tool.infrastructure.profiler import profiled as _prof
from echo_personal_tool.infrastructure.safe_diagnostics import (
    log_boundary_failure,
    safe_error_category,
)
from echo_personal_tool.infrastructure.user_preferences import (
    SESSION_SOURCE_FOLDER,
    SESSION_SOURCE_SERVER,
    UserPreferences,
    load_user_preferences,
    save_user_preferences,
)
from echo_personal_tool.keyboard_shortcuts import (
    configure_shortcuts,
    event_matches_shortcut,
    favorite_shortcut_index,
    install_qshortcuts,
    main_window_shortcuts,
    shortcut_label,
    shortcuts_for_profile,
)
from echo_personal_tool.presentation.anonymization_filter import frame_masker
from echo_personal_tool.presentation.command_catalog import (
    command_label,
    commands_for_profile,
    resolve_command,
)
from echo_personal_tool.presentation.command_palette import CommandPalette
from echo_personal_tool.presentation.comparison_coordinator import ComparisonCoordinator
from echo_personal_tool.presentation.dark_theme import apply_clinical_theme
from echo_personal_tool.presentation.download_coordinator import DownloadCoordinator
from echo_personal_tool.presentation.focus_mode import (
    FocusHeaderInfo,
    focus_plan,
    measurement_lines,
    should_enter_focus,
)
from echo_personal_tool.presentation.focus_widgets import FocusHeader, FocusLayer
from echo_personal_tool.presentation.layout.presets import (
    PRESETS,
    SLOT_GALLERY,
    SLOT_PANES,
    SLOT_RAIL,
    SLOT_SPLIT,
    SLOT_TOOL_PANEL,
    SLOT_TOOL_ROW,
    TOOL_BUTTONS_RAIL,
    TOOL_BUTTONS_ROW,
    LayoutConfigV2,
    SlotPlan,
    gallery_mode_for_plan,
    resolve_buttons,
    resolve_document,
    slot_plan,
)
from echo_personal_tool.presentation.measurement_action import MeasurementAction
from echo_personal_tool.presentation.mmode_widget import MModeWidget
from echo_personal_tool.presentation.multiview_controller import MultiViewController
from echo_personal_tool.presentation.multiview_pane import MultiViewPaneWidget
from echo_personal_tool.presentation.multiview_transport import MultiViewTransportBar
from echo_personal_tool.presentation.presenter_view import TOP_EDGE_REVEAL_PX, PresenterMode
from echo_personal_tool.presentation.protocol_step_bar import ProtocolStepBar
from echo_personal_tool.presentation.report_mode import ReportModePage
from echo_personal_tool.presentation.report_mode.print_job import print_report_pdf
from echo_personal_tool.presentation.speckle_settings_dialog import SpeckleSettingsDialog
from echo_personal_tool.presentation.start_page import RecentStudySummary, StartPage
from echo_personal_tool.presentation.study_loading_overlay import StudyLoadingOverlay
from echo_personal_tool.presentation.system_bar import SystemBar
from echo_personal_tool.presentation.tab_bar import EmptyTabPlaceholder, TabStrip
from echo_personal_tool.presentation.tab_coordinator import TabCoordinator
from echo_personal_tool.presentation.thumbnail_gallery import ThumbnailGalleryWidget
from echo_personal_tool.presentation.tool_buttons import buttons as tool_buttons
from echo_personal_tool.presentation.tool_buttons.rail import ToolButtonRail
from echo_personal_tool.presentation.tool_buttons.row import ToolButtonRow
from echo_personal_tool.presentation.tool_panel import ToolPanel
from echo_personal_tool.presentation.user_preferences_dialog import show_user_preferences_dialog
from echo_personal_tool.presentation.viewer_column import ViewerColumn
from echo_personal_tool.presentation.viewer_widget import ViewerWidget
from echo_personal_tool.presentation.window_chrome import (
    DEFAULT_RESIZE_BORDER_PX,
    RESIZE_ZONES,
    Win32Chrome,
    WindowTitleBar,
    Zone,
    collect_caption_geometry,
    hit_test,
    start_system_move,
    start_system_resize,
    zone_to_cursor_shape,
    zone_to_qt_edges,
)
from echo_personal_tool.resources.bundled_fonts import ui_font
from echo_personal_tool.ui.strain_window import StrainWindow

logger = logging.getLogger(__name__)


def _age_of(raw: object) -> int | None:
    """Age of the report header as an int (it is a free-text field there)."""
    if isinstance(raw, int):
        return raw
    digits = "".join(ch for ch in str(raw or "") if ch.isdigit())
    return int(digits) if digits else None


def _normalize_patient_sex(raw: object) -> str:
    """«female» / «male» / \"\" out of the free-text sex of the header.

    An unknown wording stays empty: the norm without a sex must say that it is
    the male one (UI-5 PR-1) and never guess the patient.
    """
    text = str(raw or "").strip().lower()
    if text.startswith(("f", "ж")):
        return "female"
    if text.startswith(("m", "м")):
        return "male"
    return ""


_FREEZE_DIAG = os.environ.get("ECHO_FREEZE_DIAG", "0") == "1"
_diag_log = logging.getLogger("echo_freeze_diag")

_TOOL_PANEL_WIDTH = 280


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
    if sys.platform == "win32" and not getattr(window, "is_native_window_frame", lambda: False)():
        # Install the native frame before the first show to avoid changing it
        # while the window is already on screen.
        if not window.isVisible():
            install = getattr(window, "_install_win32_chrome", None)
            if install is not None:
                install()
        # Geometry first, show second: showing a small window and resizing it
        # afterwards flashes on Windows (frameless + GL viewport repaint).
        window.setGeometry(geo)
        window.show()
        window._user_maximized = True  # type: ignore[attr-defined]
        return
    window.showMaximized()
    window._user_maximized = True  # type: ignore[attr-defined]


class MainWindow(QMainWindow):
    """Clinical-style layout: thumbnails | viewer | tool panel."""

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
        self._profile_capabilities = get_profile_capabilities()
        self._profile_name = active_profile_name()
        self.setWindowTitle(profile_display_name())
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._user_preferences = user_preferences or load_user_preferences()
        self._enforce_profile_preferences(self._user_preferences)
        self._resize_cursor_active = False
        self._normal_geometry: QRect | None = None
        self._win32_chrome = Win32Chrome(
            self,
            geometry_provider=self._chrome_geometry_provider,
            button_Lookup=self._chrome_button_lookup,
        )
        self._apply_window_frame_flags(native=self.is_native_window_frame(), preserve_visibility=False)
        self._recent_store = make_recent_folder_store(enabled=self._profile_capabilities.recent_folders)
        # Presenter may remember a folder for the next picker during this run,
        # but does not persist the path to its portable preferences.
        self._last_folder_for_picker = ""
        self._has_loaded_study = False
        self._click_to_frame_started_at: float | None = None
        # Armed on gallery click, consumed when the new file's first frame is
        # painted: visual reset of the previous clip (strain window, manual
        # ED/ES) runs atomically with the swap, not on click.
        self._pending_swap_uid: str | None = None
        #: Frame of the «откуда значение» card to jump to once its clip loads.
        self._pending_report_frame: int | None = None
        self._playback_active = False
        self._lav_bi_active = False
        self._rv_fac_awaiting_es = False
        self._instance_overlay_cache: dict[str, str] = {}
        self._instance_overlay_positions: dict[str, tuple[float, float]] = {}
        self._study_overlay_positions: dict[str, tuple[float, float]] = {}
        self._last_overlay_position: tuple[float, float] | None = None
        self._current_overlay_study_uid: str | None = None
        #: DICOM header snapshots cached per instance path so that rapid
        #: state changes (frame scrubbing, mode switches 2D/doppler/M) do not
        #: re-read the file from disk on every tick — that froze the UI.
        self._properties_cache: dict[str, object] = {}
        self._overlay_sync_instance_uid: str | None = None
        self._last_overlay_state: ViewerState | None = None
        self._manual_ed_frame: int | None = None
        self._manual_es_frame: int | None = None
        self._ste_position: str = "A4C"
        # Last wall thickness confirmed in the STE dialog: the auto-created
        # epicardium of a new view uses it instead of the 8 mm default, so a
        # hypertrophied wall does not have to be re-drawn by hand every time.
        self._ste_wall_thickness_mm: float = 8.0
        self._strain_result_for_window: object | None = None
        self._strain_frames_for_window: np.ndarray | None = None
        # UI-2 PR-2: the version-2 document (preset + tool buttons, spec §8.1)
        # is the in-memory layout state; the five version-1 flags are gone.
        # Multiview is a session mode and is never stored.
        self._layout_document = self._load_layout_document()
        self._multiview_mode = False
        self._bottom_container: QWidget | None = None
        self._viewer2: ViewerWidget | None = None
        # UI-2 PR-3: the tool row, the tool rail and the column that carries them
        # (spec §4.1) are built on demand, and the column is the one centre widget
        # every preset assembles.  ``_tool_doppler_mode`` is what the panel's
        # context chip reports; the buttons dim themselves against it (D-08).
        self._viewer_column: ViewerColumn | None = None
        self._tool_row: ToolButtonRow | None = None
        self._tool_rail: ToolButtonRail | None = None
        #: The mode button currently armed (row id), mirrored into both views.
        self._tool_button_active: str | None = None
        #: The area / volume button that started the closed contour being drawn.
        self._last_contour_button: str | None = None
        self._alt_focus_widget: QWidget | None = None
        # UI-5 PR-2: the cached handbook window (None until the first opening).
        self._reference_window: QWidget | None = None
        # UI-5 PR-4: the sex for the S2 card, re-read once per open study.
        self._row_sex_token: object = None
        self._row_sex_value = ""
        self._tool_doppler_mode: str | None = None
        self._rail_panels_pinned = False
        self._user_maximized = False
        self._screen_change_connected = False
        self._slider_navigating = False
        self._mmode_widget: MModeWidget | None = None
        self._mmode_active = False
        self._mmode_vertical_splitter: QSplitter | None = None
        self._mmode_collapse_anim = None
        # TP-3 PR-3: the step bar under the snapshot and the protocol session of
        # this tab. Both are created on demand so a preset rebuild is cheap.
        self._protocol_step_bar: ProtocolStepBar | None = None
        self._protocol_session: ProtocolSession | None = None
        self._protocol_armed_index: int | None = None
        #: Per-protocol «Авто-переход» flags of this window (default on).
        self._protocol_auto_advance: dict[str, bool] = {}
        # UI-4 PR-1: the report mode page (spec §4.6). One per window, built on
        # first entry; which tab is in «Отчёт» lives in the TabSession (S-02).
        self._report_page: ReportModePage | None = None
        # UI-6: the focus view of §4.8. The strip, the card and the cine plate
        # are built on the first entry, so a window that never opens a single
        # file pays nothing for the mode.  ``_focus_layout_active`` is what the
        # assembly reads; the tab owns the persisted flag (S-02).
        self._focus_header: FocusHeader | None = None
        self._focus_layer: FocusLayer | None = None
        self._focus_layout_active = False
        #: Header facts are read from the DICOM header once per file: a
        #: demographic read on every state change would re-open the container
        #: on each played frame.
        self._focus_demographics_cache: dict[str, object] = {}

        self._controller = controller or AppController()
        # Multiview session (two clips of one study). Created before the first
        # _rebuild_layout() so the panes exist when the layout asks for them.
        # N-08: the comparison — panes, transport, routing, tool gate — lives in
        # ComparisonCoordinator; the window keeps the layout and the viewer.
        self._comparison = ComparisonCoordinator(self)
        # Presenter mode (PowerPoint-style presenter view on a second display)
        self._presenter = PresenterMode(self)
        self._fullscreen_chrome_timer: QTimer | None = None
        orthanc_cache = make_orthanc_session_cache()
        try:
            orthanc_cache.root.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            # Read-only media (e.g. write-protected stick): the app still runs,
            # only server downloads that need the cache will fail later.
            pass
        # N-08: the Z3 cache, the run's download history and the purge queue of
        # closed tabs live in DownloadCoordinator; the window keeps the widgets.
        self._download_coordinator = DownloadCoordinator(
            self,
            cache=orthanc_cache,
        )
        self._download_coordinator.prepare()
        self._controller.studies_loaded.connect(self._on_studies_loaded)
        self._controller.scan_failed.connect(self._on_scan_failed)
        # D-29 parallel tabs: a download superseded by a tab switch still
        # completes — for the tab that started it, not for the visible one.
        self._controller.studies_loaded_background.connect(self._on_studies_loaded_background)
        self._controller.scan_failed_background.connect(self._on_scan_failed_background)
        self._controller.frame_loaded.connect(self._on_frame_loaded)
        self._controller.frame_load_failed.connect(self._on_frame_load_failed)
        self._controller.scroll_settled.connect(self._on_scroll_settled)
        self._controller.status_message.connect(self._show_status)
        self._apply_current_theme()

        # Tabs (Э9, PR-B): one study set per tab; the controller shows the active one.
        # N-08: the load sequence lives in TabCoordinator; the window owns the widgets
        # and the policies the coordinator asks for (flush, cache purge, layouts).
        self._tab_coordinator = TabCoordinator(self)

        central = QWidget()
        self.setCentralWidget(central)
        self._root_layout = QVBoxLayout(central)
        self._root_layout.setContentsMargins(0, 0, 0, 0)
        self._root_layout.setSpacing(0)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._system_bar = SystemBar()
        self._system_bar.set_references_visible(self._profile_capabilities.reference_ui)
        # Top bar shows only the study/file name; statuses go to the bottom bar.
        self._system_bar.set_status_visible(False)
        self._system_bar.multiview_toggle_requested.connect(self._on_multiview_button)
        self._system_bar.set_multiview_checked(self._multiview_mode)
        self._controller.decode_progress.connect(self._system_bar.show_decode_progress)
        self._controller.decode_finished.connect(self._system_bar.hide_decode_progress)
        # UI-1 PR-2 (§4.1): the caption owns the tabs, the «+», the command
        # field and the window controls; the strip below the bar is gone.
        self._title_bar = WindowTitleBar()
        self._title_bar.set_app_menu(self._build_app_menu())
        self._title_bar.set_window_controls_visible(not self.is_native_window_frame())
        self._title_bar.minimize_requested.connect(self.showMinimized)
        self._title_bar.maximize_requested.connect(self._toggle_maximize)
        self._title_bar.close_requested.connect(self.close)
        self._title_bar.command_text_changed.connect(self._on_command_text_changed)
        self._title_bar.command_submitted.connect(self._on_command_submitted)
        self._tab_strip = TabStrip()
        self._title_bar.adopt_tab_strip(self._tab_strip)
        self._tab_strip.tab_selected.connect(self._on_tab_selected)
        self._tab_strip.tab_close_requested.connect(self._on_tab_close_requested)
        self._tab_strip.tab_close_others_requested.connect(self._on_tab_close_others_requested)
        self._tab_strip.tab_moved.connect(self._on_tab_moved)
        self._sync_command_choices()
        self._root_layout.addWidget(self._title_bar)
        self._root_layout.addWidget(self._system_bar)

        self._content_widget = QWidget()
        self._empty_tab_page = EmptyTabPlaceholder()
        self._main_stack = QStackedWidget()
        self._main_stack.addWidget(self._content_widget)
        self._main_stack.addWidget(self._empty_tab_page)
        self._root_layout.addWidget(self._main_stack, stretch=1)
        self._content_layout = QHBoxLayout(self._content_widget)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(0)

        self._gallery = ThumbnailGalleryWidget()
        self._gallery.set_thumbnail_loader(self._controller.load_thumbnail)
        self._controller.set_thumbnail_preview_size_provider(self._gallery.thumbnail_preview_size)
        self._controller.thumbnail_loaded.connect(self._gallery.set_thumbnail)
        self._gallery.instance_selected.connect(self._on_instance_selected)
        self._gallery.export_mp4_requested.connect(self._on_export_mp4_requested)
        self._gallery.open_in_pane_requested.connect(self._on_open_in_pane_requested)

        self._content_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._content_splitter.setHandleWidth(2)
        self._content_splitter.splitterMoved.connect(self._on_content_splitter_moved)
        self._panel_width_timer = QTimer(self)
        self._panel_width_timer.setSingleShot(True)
        self._panel_width_timer.setInterval(400)
        self._panel_width_timer.timeout.connect(self._save_tool_panel_width)

        self._viewer = ViewerWidget()
        self._viewer._controller_ref = self._controller
        self._viewer.set_protocol_active_provider(self._is_protocol_active)
        self._viewer.set_label_picker_enabled(self._user_preferences.label_picker_enabled)
        self._viewer.set_scroll_debounce_ms(self._controller.playback_config.scroll_debounce_ms)
        self._viewer.play_pause_requested.connect(self._on_main_play_pause_requested)
        self._viewer.frame_selected.connect(self._on_slider_frame_selected)
        self._viewer.scroll_frame_selected.connect(
            lambda index: self._controller.state_manager.set_frame(index, scroll=True)
        )
        self._viewer.contour_completed.connect(self._on_contour_completed)
        self._viewer.contour_landmark_rejected.connect(self._on_contour_landmark_rejected)
        self._viewer.contours_changed.connect(self._controller.on_contours_changed)
        self._viewer.linear_measurements_changed.connect(self._controller.on_linear_measurements_changed)
        # Contour/caliper edits are stored with emit=False (no state_changed):
        # the presentation viewer needs this explicit forward to re-render.
        self._viewer.contours_changed.connect(self._presenter.forward_contours)
        self._viewer.linear_measurements_changed.connect(self._presenter.forward_linear_measurements)
        # Doppler markers/VTI traces/calibration/vessel live viewer-locally
        # and never reach state_changed — forward them explicitly.
        self._viewer.doppler_markers_changed.connect(self._presenter.forward_doppler)
        # Results-overlay drags reposition the audience label live.
        self._viewer.results_overlay_position_changed.connect(self._presenter.forward_results_overlay_position)
        self._viewer.doppler_calibration_changed.connect(self._presenter.forward_doppler)
        self._viewer.spectral_calibration_completed.connect(self._presenter.forward_doppler)
        self._viewer._doppler.vessel_changed.connect(self._presenter.forward_doppler)
        self._viewer.linear_caliper_sequence_completed.connect(self._on_linear_caliper_sequence_completed)
        self._viewer.calibration_completed.connect(self._controller.on_manual_calibration)
        self._viewer.doppler_markers_changed.connect(self._controller.on_doppler_markers_changed)
        self._viewer.doppler_calibration_changed.connect(self._controller.on_doppler_calibration_changed)
        self._viewer.doppler_frame_changing.connect(self._on_doppler_frame_changing)
        self._viewer.doppler_frame_changed.connect(self._on_doppler_frame_changed)
        self._viewer.mmode_time_calibration_completed.connect(self._controller.on_mmode_time_calibration)
        self._viewer.mmode_calibration_changed.connect(self._controller.on_mmode_calibration_changed)
        self._viewer.results_overlay_position_changed.connect(self._on_results_overlay_position_changed)
        self._viewer.results_overlay_parameter_clicked.connect(self._on_results_overlay_parameter_clicked)
        self._viewer.gold_export_requested.connect(self._on_gold_export_requested)
        self._viewer.mmode_column_ready.connect(self._on_mmode_column_ready)
        self._viewer.mmode_line_completed.connect(self._on_mmode_line_completed)
        self._viewer.vessel_accept_requested.connect(self._on_vessel_accept_requested)
        self._viewer.context_calibration_bmode_requested.connect(self._on_calibration_requested)
        self._viewer.context_doppler_calibration_requested.connect(self._on_doppler_calibration_requested)
        self._viewer.context_properties_requested.connect(self._show_properties_tab)
        self._viewer.context_reset_requested.connect(self._on_reset_measurements_requested)
        self._start_page = StartPage(
            recent_store=self._recent_store,
            version=__version__,
            profile_name=self._profile_name,
            profile_capabilities=self._profile_capabilities,
            measurement_persistence_enabled=self._user_preferences.measurement_persistence_enabled,
            ui_font_size=self._user_preferences.ui_font_size,
        )
        self._start_page.set_continue_target(
            self._user_preferences.last_session_source,
            self._user_preferences.last_opened_folder,
            date=self._user_preferences.last_session_date,
            clip_count=self._user_preferences.last_session_clip_count,
        )
        self._viewer_stack = QStackedWidget(self._content_widget)
        self._viewer_stack.setObjectName("viewerStack")
        self._viewer_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._viewer_stack.addWidget(self._viewer)
        self._viewer_stack.addWidget(self._start_page)
        self._viewer_stack.setCurrentWidget(self._start_page)
        self._study_loading_overlay = StudyLoadingOverlay(self._viewer_stack)
        self._start_page.open_folder_requested.connect(self._open_folder)
        self._start_page.load_from_server_requested.connect(self._open_orthanc_dialog)
        self._start_page.continue_requested.connect(self._continue_last_session)
        self._start_page.recent_folder_requested.connect(self._open_recent_folder)
        self._start_page.references_requested.connect(self._show_references)
        self._start_page.documents_requested.connect(self._open_user_reference_document)
        self._start_page.feedback_requested.connect(self._show_support_feedback)
        self._start_page.settings_requested.connect(self._show_user_preferences)
        self._start_page.help_requested.connect(self._show_help)
        self._start_page.theme_changed.connect(self._on_welcome_theme_changed)
        self._start_page.language_changed.connect(self._on_welcome_language_changed)
        self._start_page.recent_study_requested.connect(self._on_start_page_recent_study)
        # Cached summaries of the stored records; filled by the persistence
        # worker (QH-1a). None means "not read yet", never "nothing stored".
        self._saved_records_listing: object | None = None
        self._saved_records_pending = False
        self._refresh_start_page_recents()
        self._controller.state_manager.state_changed.connect(self._viewer.set_state)
        self._doppler_frame_context: tuple[str | None, int | None] = (None, None)
        self._strain_window: StrainWindow | None = None

        self._build_tool_panel()
        if self._tool_panel.is_v2:
            self._tool_panel.set_splitter_resizable(True)
        else:
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
        # TP-6: the radial wheel — the window owns the controller, the viewer
        # only forwards press/move/release (spec §4.4, Q-09).
        from echo_personal_tool.presentation.radial_menu import RadialMenuController

        self._radial = RadialMenuController(
            sectors=self._radial_sector_labels,
            on_tool=self._on_radial_tool,
            on_more=self._on_radial_more,
            parent=self,
        )
        self._viewer.radial_controller = self._radial

        status = QStatusBar()
        self.setStatusBar(status)
        self._show_status(tr("status.startup"))

        # Permanent "Research use only" warning in status bar
        from PySide6.QtWidgets import QLabel

        self._persistence_label = QLabel(
            tr("persistence.ready")
            if self._user_preferences.measurement_persistence_enabled
            else tr("persistence.disabled")
        )
        status.addPermanentWidget(self._persistence_label)
        if hasattr(self._controller, "persistence_status"):
            self._controller.persistence_status.connect(self._on_persistence_status)
        if hasattr(self._controller, "persistence_blocked"):
            self._controller.persistence_blocked.connect(self._on_persistence_blocked)
        if hasattr(self._controller, "persistence_conflict"):
            self._controller.persistence_conflict.connect(self._on_persistence_conflict)
        self._research_warning = QLabel(tr("layout.research_use_only"))
        status.addPermanentWidget(self._research_warning)

        # Permanent release version label, shown left of the research warning
        self._version_label = QLabel(f"SonoForge {__version__}")
        status.addPermanentWidget(self._version_label)
        self.apply_status_bar_tokens()

        self._install_shortcuts()
        self._rebuild_layout()
        # The first tab exists from the start; the startup load fills it (D-29).
        self._tab_coordinator.open_empty_tab()
        self._refresh_tab_strip()
        self._update_main_stack()

    def _install_shortcuts(self) -> None:
        """Install the registry's window-level shortcuts for the active build."""
        handlers = {
            "open_folder": self._open_folder,
            "load_server": self._open_orthanc_dialog,
            "caliper": self._viewer.toggle_linear_caliper,
            "manual_contour": self._start_manual_contour_shortcut,
            "model_contour": self._start_model_contour_shortcut,
            "auto_segment": self._request_auto_segment_shortcut,
            "finish_tool": self._finish_active_tool_shortcut,
            "cancel_tool": self._cancel_active_tool,
            "skip_step": self._skip_protocol_step_shortcut,
            "delete_selection": self._delete_current_contour,
            "measurement_undo": self._undo_measurement,
            "measurement_redo": self._redo_measurement,
            "toggle_gallery": self._toggle_gallery_shortcut,
            "toggle_fullscreen": self._toggle_fullscreen_shortcut,
            "gallery_previous": self._gallery.select_previous_instance,
            "gallery_next": self._gallery.select_next_instance,
            "new_tab": self._open_empty_tab_shortcut,
            "command_field": self._open_command_palette,
            "next_tab": lambda: self._cycle_tab(1),
            "previous_tab": lambda: self._cycle_tab(-1),
            "close_tab": self._close_active_tab_shortcut,
            "presenter_toggle": self._presenter.toggle,
            "toggle_report_mode": self._toggle_report_mode_shortcut,
            "toggle_focus_mode": self.toggle_focus_mode,
            "start_page_search": self._focus_start_page_search,
        }
        # UI-2 PR-3: the row and the rail dispatch mode buttons through the same
        # table, so a button and its key can never call different code.
        self._shortcut_handlers = handlers
        app = QApplication.instance()
        if app is not None:
            app.focusChanged.connect(self._on_application_focus_changed)
            self._on_application_focus_changed(None, app.focusWidget())
        for shortcut in main_window_shortcuts(active_profile_name()):
            install_qshortcuts(self, shortcut.id, handlers[shortcut.id])

    @_prof
    def _toggle_playback_shortcut(self) -> None:
        if self._controller.state_manager.snapshot.decode_in_progress:
            return
        self._controller.toggle_playback()

    @_prof
    def _start_manual_contour_shortcut(self) -> None:
        if self._multiview_tool_blocked("manual_contour"):
            return
        if self._viewer.start_contour():
            self._show_hint(tr("status.manual_contour"))
        else:
            self._show_status(tr("status.load_frame_or_finish_contour"))

    @_prof
    def _start_model_contour_shortcut(self) -> None:
        if self._multiview_tool_blocked("model_contour"):
            return
        start_mode = self._viewer.start_model_contour()
        if start_mode:
            self._viewer.clear_frame_overlay()
            self._viewer.append_frame_overlay("MBS-lite: MA septal → lateral → apex")
            self._show_hint(tr("status.mbs_lite_contour"))
        else:
            self._show_status(tr("status.load_frame_or_finish_contour"))

    @_prof
    def _request_auto_segment_shortcut(self) -> None:
        if self._multiview_tool_blocked("lv_auto"):
            return
        if self._viewer.get_doppler_tool_mode() != "none":
            return
        if not self._controller.is_lv_auto_session_active():
            self._show_hint(tr("status.select_lv_auto"))
            return
        if not self._controller.state_manager.snapshot.is_playing:
            self._controller.request_auto_segment()

    def _is_protocol_active(self) -> bool:
        session = getattr(self, "_protocol_session", None)
        if session is not None and bool(getattr(session, "active_protocol_id", "")):
            return True
        return False

    @_prof
    def _finish_active_tool_shortcut(self) -> None:
        if self._viewer.is_label_picker_visible() and self._viewer.accept_label_picker():
            return
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
        # Manual protocol advance: Enter confirms the pending next step (the
        # auto timer is off by default — 2026-10-25, «ждать подтверждение»).
        session = self._protocol_session
        if session is not None and session.runner.pending_advance is not None:
            session.runner.advance_now()
            return

    @_prof
    def _cancel_active_tool(self) -> None:
        """«Esc»: drop whatever tool is armed — and unlight its button.

        The button state is derived from the viewer, so every way out of a tool
        has to push it again, including the early returns (item 3 of the
        2026-10-23 list: the row kept a pressed button after Esc)."""
        try:
            if self._viewer.is_label_picker_visible() and self._viewer.dismiss_label_picker():
                return
            if self._protocol_escape():
                return
            if self._viewer.discard_pending_ai_contour():
                self._controller.on_contours_changed(self._viewer.contours())
                self._show_status(tr("status.ai_contour_cancelled"))
                return
            self._viewer.cancel_active_tool()
        finally:
            self._sync_tool_button_active()

    @_prof
    def _delete_current_contour(self) -> None:
        if self._viewer._delete_selected_caliper():
            self._show_status(tr("status.caliper_deleted"))
            self._sync_tool_button_active()
            return
        if self._viewer.delete_contour_for_current_phase():
            self._controller.on_contours_changed(self._viewer.contours())
            self._sync_tool_button_active()
            self._show_status(tr("status.contour_deleted"))

    def _undo_measurement(self) -> None:
        """Undo the last measurement deletion (Ctrl+Z)."""
        if not self._viewer.can_undo():
            return
        if self._viewer.undo():
            self._controller.on_contours_changed(self._viewer.contours())
            self._sync_tool_button_active()
            self._show_status(tr("status.measurement_undone"))

    def _redo_measurement(self) -> None:
        """Redo the last undone measurement deletion (Ctrl+Y)."""
        if not self._viewer.can_redo():
            return
        if self._viewer.redo():
            self._controller.on_contours_changed(self._viewer.contours())
            self._sync_tool_button_active()
            self._show_status(tr("status.measurement_redone"))

    # ── Protocol (TP-3 PR-3) ────────────────────────────────────────
    #
    # One session per tab owns the runner and the study projection; the window
    # only translates its signals into the card, the step bar and the tools.

    def _ensure_protocol_step_bar(self) -> ProtocolStepBar:
        """The strip under the snapshot (UI-3); created once, then reused."""
        if self._protocol_step_bar is None:
            bar = ProtocolStepBar(self._content_widget)
            bar.skip_requested.connect(self._on_protocol_skip_requested)
            bar.done_requested.connect(self._finish_active_tool_shortcut)
            bar.cancel_point_requested.connect(self._on_protocol_cancel_point)
            bar.rap_chosen.connect(self._on_rap_chosen)
            bar.rap_other_requested.connect(self._on_rap_other_requested)
            bar.rap_reference_requested.connect(self._open_reference_dialog)
            self._protocol_step_bar = bar
        self._apply_protocol_step_bar_labels()
        return self._protocol_step_bar

    def _apply_protocol_step_bar_labels(self) -> None:
        if self._protocol_step_bar is None:
            return
        self._protocol_step_bar.set_labels(
            cancel=tr("protocol.cancel_point"),
            skip=tr("protocol.skip"),
            done=tr("protocol.done"),
            rap_hint=tr("protocol.rap_hint"),
            notification_hint=tr("protocol.notification_hint"),
        )

    def _ensure_protocol_session(self) -> ProtocolSession:
        """The protocol session of this tab (created on the first use)."""
        if self._protocol_session is None:
            session = ProtocolSession(
                self._controller,
                clip_context=self._protocol_clip_context,
                parent=self,
            )
            session.progress_changed.connect(self._on_protocol_progress)
            session.action_requested.connect(self._on_protocol_step_action)
            session.notification.connect(self._on_protocol_notification)
            session.finished.connect(self._on_protocol_finished)
            session.stopped.connect(self._on_protocol_stopped)
            session.statuses_changed.connect(self._on_protocol_statuses)
            session.drawing_cancel_requested.connect(self._on_protocol_drawing_cancel)
            self._protocol_session = session
        return self._protocol_session

    def _protocol_clip_context(self) -> tuple[frozenset[str], str]:
        """What the open clip offers — read through the thin viewer adapter."""
        from echo_personal_tool.presentation.viewer_clip_context import clip_modes, clip_view

        return clip_modes(self._viewer, mmode_active=self._mmode_active), clip_view(self._viewer)

    def _on_protocol_selected(self, protocol_id: str) -> None:
        self._ensure_protocol_session().start(protocol_id)

    def _on_protocol_step_activated(self, index: int) -> None:
        session = self._protocol_session
        if session is not None and session.active:
            session.arm(index)

    def _on_protocol_stop_requested(self) -> None:
        self._ensure_protocol_session().stop("user")

    def _on_protocol_auto_advance_toggled(self, protocol_id: str, enabled: bool) -> None:
        """The footer switch: remember the flag and retime the live runner."""
        self._protocol_auto_advance[protocol_id] = bool(enabled)
        session = self._protocol_session
        if session is None or not session.active:
            return
        from echo_personal_tool.application.protocol_runner import DEFAULT_AUTO_ADVANCE_MS

        session.runner.auto_advance_ms = DEFAULT_AUTO_ADVANCE_MS if enabled else 0

    def _push_protocol_auto_advance(self, protocol_id: str) -> None:
        """Sync the card footer with the remembered flag of the protocol.

        Default is **off**: a finished step waits for Enter or a click on the
        next tile instead of yanking the tool away mid-correction (2026-10-25).
        """
        enabled = self._protocol_auto_advance.get(protocol_id, False)
        self._tool_panel.set_protocol_auto_advance(protocol_id, enabled)
        session = self._protocol_session
        if session is not None and session.active:
            from echo_personal_tool.application.protocol_runner import DEFAULT_AUTO_ADVANCE_MS

            session.runner.auto_advance_ms = DEFAULT_AUTO_ADVANCE_MS if enabled else 0

    def _on_study_projection_changed(self, _projection: object = None) -> None:
        if self._protocol_session is not None:
            self._protocol_session.refresh()

    def _on_protocol_progress(self, progress: object) -> None:
        self._tool_panel.set_protocol_progress(progress)
        protocol_id = getattr(progress, "protocol_id", "")
        if protocol_id:
            self._push_protocol_auto_advance(protocol_id)
        self._sync_protocol_step_bar(progress)
        self._sync_protocol_step_highlight(progress)

    def _on_protocol_statuses(self, statuses: object) -> None:
        self._tool_panel.set_tool_statuses(statuses)

    def _on_protocol_step_action(self, action: object) -> None:
        if not isinstance(action, StepAction):
            return
        self._protocol_armed_index = action.index
        if action.open_protocol:
            self._ensure_protocol_session().start(action.open_protocol)
            return
        if not action.tool_id:
            # A step without a tool (the RAP chips, П6.2) is driven by the bar.
            return
        if self._tool_panel.is_v2:
            self._tool_panel.activate_tool(action.tool_id)
            self._tool_panel.measure.highlight_tool(action.tool_id)

    def _on_protocol_notification(self, code: str) -> None:
        bar = self._ensure_protocol_step_bar()
        if code == "auto_advance":
            text = self._auto_advance_text()
            if text:
                bar.show_notification(text, hint=self._advance_hint_text())

    def _advance_hint_text(self) -> str:
        """Hint of the advance notification: the timer's Esc, or Enter to confirm."""
        session = self._protocol_session
        auto = self._protocol_auto_advance.get(session.active_protocol_id, False) if session else False
        return tr("protocol.notification_hint") if auto else tr("protocol.notification_confirm")

    def _auto_advance_text(self) -> str:
        """«✓ шаг → далее: следующий» — уведомление Q-07 по текущему прогрессу."""
        session = self._protocol_session
        if session is None:
            return ""
        spec = PROTOCOLS_BY_ID.get(session.active_protocol_id)
        progress = session.progress
        if spec is None or progress is None or progress.current_index is None:
            return ""
        language = get_language()
        next_label = spec.steps[progress.current_index].label(language)
        armed = self._protocol_armed_index
        done_label = (
            spec.steps[armed].label(language)
            if armed is not None and 0 <= armed < len(spec.steps)
            else tr("protocol.notification_advance")
        )
        return f"✓ {done_label} → {tr('protocol.notification_next', step=next_label)}"

    def _on_protocol_finished(self, _protocol_id: str) -> None:
        bar = self._ensure_protocol_step_bar()
        bar.show_notification(tr("protocol.notification_done"), hint=tr("protocol.notification_hint"))
        if self._tool_panel.is_v2:
            self._tool_panel.measure.clear_action_highlight()

    def _on_protocol_stopped(self, _reason: str) -> None:
        self._tool_panel.set_protocol_progress(None)
        self._protocol_armed_index = None
        self._ensure_protocol_step_bar().clear()
        if self._tool_panel.is_v2:
            self._tool_panel.measure.clear_action_highlight()

    def _on_protocol_drawing_cancel(self) -> None:
        self._viewer.cancel_active_tool()

    def _on_protocol_skip_requested(self) -> None:
        session = self._protocol_session
        if session is not None and session.active:
            session.skip()

    def _on_protocol_cancel_point(self) -> None:
        if self._viewer_drawing():
            self._viewer.cancel_active_tool()
            return
        session = self._protocol_session
        if session is not None and session.active:
            session.runner.cancel_point()

    def _on_rap_chosen(self, value: float) -> None:
        self._controller.set_calculator_input("rap", float(value))

    def _on_rap_other_requested(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        value, accepted = QInputDialog.getDouble(
            self,
            tr("protocol.rap_other_title"),
            tr("protocol.rap_other_prompt"),
            5.0,
            0.0,
            40.0,
            0,
        )
        if accepted:
            self._controller.set_calculator_input("rap", float(value))

    def _protocol_escape(self) -> bool:
        """A-09: drawing → auto-advance → stop; only a running protocol answers."""
        session = self._protocol_session
        if session is None or not session.active:
            return False
        drawing = self._viewer_drawing()
        session.runner.set_drawing_active(drawing)
        result = session.on_escape()
        if result is EscapeResult.DRAWING_CANCELLED:
            if drawing:
                self._viewer.cancel_active_tool()
            else:
                # The step was armed but nothing was drawn yet: drop the point
                # so the next Esc stops the protocol (A-09).
                session.runner.cancel_point()
            return True
        if result is EscapeResult.ADVANCE_CANCELLED:
            self._show_status(tr("protocol.advance_cancelled"))
            return True
        return result is EscapeResult.STOPPED

    def _viewer_drawing(self) -> bool:
        """Whether the viewer is mid-contour or mid-caliper — the Esc stage 1."""
        return bool(self._viewer.is_contour_mode_active or self._viewer.is_linear_caliper_active)

    def _sync_protocol_step_bar(self, progress: object | None = None) -> None:
        """Show the current (or armed) step of a running protocol; else hide."""
        bar = self._ensure_protocol_step_bar()
        session = self._protocol_session
        if session is None or not session.active:
            bar.clear()
            return
        if progress is None:
            progress = session.progress
        spec = PROTOCOLS_BY_ID.get(session.active_protocol_id)
        if spec is None or progress is None:
            bar.clear()
            return
        runner = session.runner
        index = runner.armed_index if runner.armed_index is not None else progress.current_index
        if index is None or not (0 <= index < len(spec.steps)):
            bar.clear()
            return
        step = spec.steps[index]
        bar.set_step(
            protocol_label=spec.label(get_language()),
            index=index,
            total=len(spec.steps),
            step_label=step.label(get_language()),
            frame_hint=self._frame_hint_label(step.frame_hint),
            can_cancel=runner.armed_index is not None,
            rap=not step.tool_id and "ra.rap" in step.satisfied_keys,
        )

    def _sync_protocol_step_highlight(self, _progress: object | None = None) -> None:
        """Keep the armed step's row marked in the panel (spec §6.2)."""
        if not self._tool_panel.is_v2:
            return
        session = self._protocol_session
        armed = session.runner.armed_index if session is not None and session.active else None
        if armed is None:
            self._tool_panel.measure.clear_action_highlight()
            return
        spec = PROTOCOLS_BY_ID.get(session.active_protocol_id)
        if spec is None:
            return
        tool_id = spec.steps[armed].tool_id
        if tool_id:
            self._tool_panel.measure.highlight_tool(tool_id)

    def _frame_hint_label(self, frame_hint: str | None) -> str:
        key = {"ed": "protocol.frame_ed", "es": "protocol.frame_es"}.get(frame_hint or "")
        return tr(key) if key else (frame_hint or "")

    def _skip_protocol_step_shortcut(self) -> None:
        session = self._protocol_session
        if session is not None and session.active:
            session.skip()

    def _toggle_gallery_shortcut(self) -> None:
        self._gallery.toggle_collapse()

    def _toggle_fullscreen_shortcut(self) -> None:
        if self.isFullScreen():
            self._exit_fullscreen_kiosk()
        else:
            self._enter_fullscreen_kiosk()

    # ── Fullscreen (F11) kiosk mode ─────────────────────────────────
    #
    # Hides ALL chrome — gallery, tool/activity panel, system bar and the
    # status bar — leaving only the viewer.  Moving the mouse to the top
    # edge slides the system bar in (auto-hides again after a short delay),
    # like a video player in fullscreen.  F11 or Esc-chrome returns.

    def _enter_fullscreen_kiosk(self) -> None:
        self._gallery.hide()
        self._tool_panel.hide()
        for widget in (self._tool_row, self._tool_rail):
            if widget is not None:
                widget.hide()
        self._title_bar.hide()
        self._tab_strip.hide()
        self._system_bar.hide()
        self.statusBar().hide()
        self.showFullScreen()
        self._show_status(tr("status.fullscreen_hint", shortcut=shortcut_label("toggle_fullscreen")))
        self._install_fullscreen_chrome_filter()

    def _exit_fullscreen_kiosk(self) -> None:
        self._remove_fullscreen_chrome_filter()
        self.showNormal()
        self._title_bar.show()
        self._title_bar.set_tabs_visible(self._profile_capabilities.tabs and self._user_preferences.tabs_enabled)
        self._system_bar.show()
        document = self._layout_document
        self.statusBar().setVisible(document.status_bar_visible)
        self._gallery.show()
        mode = resolve_buttons(document)
        if self._tool_row is not None:
            self._tool_row.setVisible(mode == TOOL_BUTTONS_ROW)
        if self._tool_rail is not None:
            self._tool_rail.setVisible(mode == TOOL_BUTTONS_RAIL)
        if mode == TOOL_BUTTONS_RAIL:
            # The rail keeps the wide panel hidden until its bottom button
            # asked for it (§4.2); kiosk exit restores exactly that state.
            self._tool_panel.setVisible(self._rail_panels_pinned)
        else:
            self._tool_panel.show()
        self._title_bar.set_window_controls_visible(not self.is_native_window_frame())
        self._sync_maximize_button_state()

    def _fullscreen_hover_targets(self) -> tuple[QWidget, ...]:
        targets: list[QWidget] = [self._title_bar, self._system_bar]
        graphics = getattr(self._viewer, "_graphics", None)
        viewport = graphics.viewport() if graphics is not None else None
        if viewport is not None:
            targets.append(viewport)
        return tuple(targets)

    def _install_fullscreen_chrome_filter(self) -> None:
        # Local hover sources only.  A QApplication filter would also receive
        # QtWebEngine compositor events and can crash in Shiboken before Python
        # gets a chance to ignore them.
        for widget in self._fullscreen_hover_targets():
            widget.setMouseTracking(True)
            widget.installEventFilter(self)

    def _remove_fullscreen_chrome_filter(self) -> None:
        for widget in self._fullscreen_hover_targets():
            widget.removeEventFilter(self)
        if self._fullscreen_chrome_timer is not None:
            self._fullscreen_chrome_timer.stop()

    def _fullscreen_reveal_chrome(self, *, auto_hide: bool) -> None:
        """Slide the title bar and the system bar in while in fullscreen (top-edge hover)."""
        if not self.isFullScreen():
            return
        self._title_bar.show()
        self._system_bar.show()
        self._title_bar.set_tabs_visible(self._profile_capabilities.tabs and self._user_preferences.tabs_enabled)
        if auto_hide:
            if self._fullscreen_chrome_timer is None:
                self._fullscreen_chrome_timer = QTimer(self)
                self._fullscreen_chrome_timer.setSingleShot(True)
                self._fullscreen_chrome_timer.setInterval(2500)
                self._fullscreen_chrome_timer.timeout.connect(self._fullscreen_hide_chrome)
            self._fullscreen_chrome_timer.start()

    def _fullscreen_hide_chrome(self) -> None:
        if not self.isFullScreen():
            return
        pos = QCursor.pos()
        if not self._fullscreen_cursor_over_chrome(pos):
            self._title_bar.hide()
            self._system_bar.hide()
            self._tab_strip.hide()

    def _fullscreen_cursor_over_chrome(self, global_pos: QPoint) -> bool:
        """True while the pointer rests on a revealed bar of the kiosk chrome."""
        for bar in (self._title_bar, self._system_bar):
            if bar.isVisible() and bar.geometry().contains(bar.mapFromGlobal(global_pos)):
                return True
        return False

    def _fullscreen_handle_hover(self, event: QEvent) -> None:
        """Top-edge hover reveal for the F11 kiosk mode (widget-local filters)."""
        try:
            global_pos = event.globalPosition().toPoint()
        except AttributeError:
            return
        window_top = self.mapToGlobal(QPoint(0, 0)).y()
        if global_pos.y() - window_top <= TOP_EDGE_REVEAL_PX:
            self._fullscreen_reveal_chrome(auto_hide=True)
            return
        if not self._fullscreen_cursor_over_chrome(global_pos) and self._system_bar.isVisible():
            if self._fullscreen_chrome_timer is None or not self._fullscreen_chrome_timer.isActive():
                self._fullscreen_reveal_chrome(auto_hide=True)

    # ── Presenter mode (second-display mirror) ──────────────────────

    def _build_presenter_menu(self) -> QMenu:
        # Reuse the button's menu when possible: rebuilding the menu object
        # on every state change would leak QMenu instances.
        menu = self._system_bar._btn_presenter.menu()
        if menu is None:
            menu = QMenu(self._system_bar._btn_presenter)
            menu.setObjectName("presenterMenu")
        menu.clear()
        # clear() removes actions but not the submenu widget instances
        # (audience-display picker) — drop them explicitly.
        for submenu in menu.findChildren(QMenu, options=Qt.FindDirectChildrenOnly):
            submenu.deleteLater()
        toggle_action = menu.addAction(tr("presenter.menu_toggle", shortcut=shortcut_label("presenter_toggle")))
        toggle_action.triggered.connect(self._presenter.toggle)

        base = self._presenter.prefs_for_options()
        screens_menu = menu.addMenu(tr("presenter.menu_screen"))
        app = QApplication.instance()
        screens = app.screens() if app is not None else []
        checked_name = self._presenter.screen_action_checked_name()
        for screen in screens:
            action = screens_menu.addAction(screen.name())
            action.setCheckable(True)
            action.setChecked(screen.name() == checked_name)
            action.triggered.connect(lambda _, s=screen: self._presenter.set_screen(s))

        preset_action = menu.addAction(tr("presenter.menu_visual_preset"))
        preset_action.setCheckable(True)
        preset_action.setChecked(bool(getattr(base, "presenter_visual_preset", True)))
        preset_action.triggered.connect(lambda checked: self._presenter.set_visual_preset_enabled(checked))

        pointer_action = menu.addAction(tr("presenter.menu_pointer"))
        pointer_action.setCheckable(True)
        pointer_action.setChecked(bool(getattr(base, "presenter_pointer", True)))
        pointer_action.triggered.connect(lambda checked: self._presenter.set_pointer_enabled(checked))
        return menu

    def _presenter_active_changed(self, active: bool) -> None:
        """Sync the system-bar button with the mirror state."""
        self._system_bar.set_presenter_active(active)
        self._install_presenter_menu()

    def _install_presenter_menu(self) -> None:
        """(Re)build the Presenter options menu, updating it in place."""
        if self._system_bar._btn_presenter is None:
            return  # full profile — no Presenter UI
        self._system_bar._btn_presenter.setMenu(self._build_presenter_menu())

    def _toggle_mmode(self) -> None:
        self._mmode_active = not self._mmode_active
        self._refresh_tool_buttons()
        if self._mmode_active:
            self._activate_mmode()
            try:
                self._viewer.start_mmode_line()
            except Exception as exc:  # noqa: BLE001
                log_boundary_failure(logger, "ui.cleanup", exc, code="unexpected", level=logging.DEBUG)
            self._sync_tool_panel_context()
            self._show_status(tr("status.mmode_activated"))
        else:
            try:
                self._viewer.cancel_mmode_line()
            except Exception as exc:  # noqa: BLE001
                log_boundary_failure(logger, "ui.cleanup", exc, code="cleanup", level=logging.DEBUG)
            self._deactivate_mmode()
            self._sync_tool_panel_context()
            self.setFocus()
            self.activateWindow()
            self._show_status(tr("status.mmode_deactivated"))

    def _activate_mmode(self) -> None:
        if self._mmode_widget is None:
            self._mmode_widget = MModeWidget()
            self._mmode_widget.deactivate_requested.connect(self._toggle_mmode)
            self._mmode_widget.teichholz_ed_complete.connect(self._on_teichholz_ed_complete)
            self._mmode_widget.teichholz_es_complete.connect(self._on_teichholz_es_complete)
        # Find the viewer surface's current position BEFORE reparenting.
        idx = self._content_splitter.indexOf(self._viewer_stack)
        if idx < 0:
            for i in range(self._content_splitter.count()):
                w = self._content_splitter.widget(i)
                if isinstance(w, QSplitter) and w.indexOf(self._viewer_stack) >= 0:
                    idx = i
                    break
        content_index = self._content_layout.indexOf(self._viewer_stack)
        column = self._viewer_column
        in_column = column is not None and column.part("center") is self._viewer_stack
        self._mmode_vertical_splitter = QSplitter(Qt.Orientation.Vertical)
        self._mmode_vertical_splitter.setHandleWidth(4)
        self._mmode_vertical_splitter.addWidget(self._viewer_stack)
        self._mmode_vertical_splitter.addWidget(self._mmode_widget)
        self._mmode_vertical_splitter.setSizes([400, 600])
        self._mmode_vertical_splitter.setStretchFactor(0, 1)
        self._mmode_vertical_splitter.setStretchFactor(1, 1)

        if in_column:
            # UI-2 PR-3: the trace joins the image inside the snapshot column, so the
            # tool row keeps sitting above both of them (§4.1).
            column.set_center(self._mmode_vertical_splitter)
        elif idx >= 0:
            self._content_splitter.insertWidget(idx, self._mmode_vertical_splitter)
            self._content_splitter.setStretchFactor(idx, 1)
        elif content_index >= 0:
            self._content_layout.insertWidget(content_index, self._mmode_vertical_splitter, stretch=1)
        self._mmode_vertical_splitter.show()

        # Animate M-mode widget expand
        widget = self._mmode_widget
        if widget is not None:
            widget.setMaximumHeight(0)
            anim = QPropertyAnimation(widget, b"maximumHeight")
            anim.setDuration(200)
            anim.setStartValue(0)
            anim.setEndValue(600)
            anim.setEasingCurve(QEasingCurve.Type.OutQuad)
            anim.start()
            self._mmode_collapse_anim = anim
        self._sync_tool_panel_context()

    def _deactivate_mmode(self) -> None:
        if self._mmode_vertical_splitter is None:
            return
        # Animate M-mode widget collapse
        widget = self._mmode_widget
        if widget is not None and widget.isVisible():
            widget.setMaximumHeight(widget.height())
            anim = QPropertyAnimation(widget, b"maximumHeight")
            anim.setDuration(200)
            anim.setStartValue(widget.height())
            anim.setEndValue(0)
            anim.setEasingCurve(QEasingCurve.Type.InQuad)
            anim.finished.connect(self._finish_mmode_deactivation)
            anim.start()
            # Keep reference to prevent GC
            self._mmode_collapse_anim = anim
        else:
            self._finish_mmode_deactivation()

    def _finish_mmode_deactivation(self) -> None:
        if self._mmode_vertical_splitter is None:
            return
        # Remove the viewer surface from the vertical splitter before rebuilding.
        self._viewer_stack.setParent(self._content_widget)
        # Schedule splitter deletion
        self._mmode_vertical_splitter.deleteLater()
        self._mmode_vertical_splitter = None
        self._mmode_widget = None
        self._mmode_collapse_anim = None
        # Rebuild layout to restore proper structure
        self._rebuild_layout()
        self._sync_tool_panel_context()

    # ── Window chrome, hit-testing, Win32 & fallback OS frame (UI-1 PR-1) ──

    def is_native_window_frame(self) -> bool:
        """Return ``True`` when the fallback operating-system window frame is active."""
        prefs = getattr(self, "_user_preferences", None)
        return bool(getattr(prefs, "native_window_frame", False))

    def _is_effectively_maximized(self) -> bool:
        return bool(self.isMaximized() or getattr(self, "_user_maximized", False))

    def _sync_maximize_button_state(self) -> None:
        title_bar = getattr(self, "_title_bar", None)
        if title_bar is not None:
            title_bar.update_maximize_button(self._is_effectively_maximized())

    def _apply_window_frame_flags(self, *, native: bool, preserve_visibility: bool = True) -> None:
        was_visible = preserve_visibility and self.isVisible()
        was_maximized = self._is_effectively_maximized()
        saved_geo = self.geometry() if was_visible else None
        base_flags = (
            Qt.WindowType.Window
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowMinMaxButtonsHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        desired_flags = base_flags if native else (base_flags | Qt.WindowType.FramelessWindowHint)
        if self.windowFlags() != desired_flags:
            self.setWindowFlags(desired_flags)
        title_bar = getattr(self, "_title_bar", None)
        if title_bar is not None:
            title_bar.set_window_controls_visible(not native)
        if native and getattr(self, "_resize_cursor_active", False):
            self.unsetCursor()
            self._resize_cursor_active = False
        if was_visible:
            if saved_geo is not None and not was_maximized:
                self.setGeometry(saved_geo)
            self.show()
            if was_maximized:
                apply_maximized_to_work_area(self)
            if not native:
                self._install_win32_chrome()
        # Keep the preference-frame cache aligned with the flags actually applied.
        self._last_native_frame_applied = self.is_native_window_frame()

    def apply_window_frame_mode(self, native: bool | None = None) -> None:
        """Switch between custom frameless chrome and the standard OS window frame."""
        if native is None:
            native = self.is_native_window_frame()
        else:
            self._user_preferences.native_window_frame = bool(native)
        self._apply_window_frame_flags(native=bool(native), preserve_visibility=True)

    def _install_win32_chrome(self) -> bool:
        if self.is_native_window_frame():
            return False
        from echo_personal_tool.presentation.dark_theme import _is_dark_theme

        mode = getattr(self._user_preferences, "theme_mode", "graphite")
        return self._win32_chrome.install(dark=_is_dark_theme(mode), round_corners=True)

    def _chrome_geometry_provider(self) -> tuple[QRect, dict[Zone, QRect], list[QRect]]:
        """Captions of the custom chrome: the title bar (UI-1 PR-2) and, until PR-3, the bar."""
        title_bar = getattr(self, "_title_bar", None)
        if title_bar is None:
            return QRect(), {}, []
        return collect_caption_geometry(
            self,
            [title_bar],
            button_widgets=title_bar.caption_buttons(),
        )

    def _chrome_button_lookup(self):
        title_bar = getattr(self, "_title_bar", None)
        if title_bar is None:
            return {}
        return title_bar.caption_buttons()

    def chrome_hit_test(self, pos: QPoint) -> Zone:
        """Classify ``pos`` (in window-local logical coordinates) into a :class:`Zone`."""
        if self.is_native_window_frame() or self.isFullScreen():
            return Zone.CLIENT
        caption_rect, buttons, interactive = self._chrome_geometry_provider()
        return hit_test(
            pos,
            self.size(),
            border=DEFAULT_RESIZE_BORDER_PX,
            caption=caption_rect,
            buttons=buttons,
            interactive=interactive,
            maximized=self._is_effectively_maximized(),
        )

    def _update_resize_cursor(self, local_pos: QPoint) -> None:
        if self.is_native_window_frame() or self.isFullScreen() or self._is_effectively_maximized():
            if self._resize_cursor_active:
                self.unsetCursor()
                self._resize_cursor_active = False
            return
        zone = self.chrome_hit_test(local_pos)
        shape = zone_to_cursor_shape(zone)
        if shape is not None:
            self.setCursor(shape)
            self._resize_cursor_active = True
        elif self._resize_cursor_active:
            self.unsetCursor()
            self._resize_cursor_active = False

    def nativeEvent(self, eventType: QByteArray | bytes, message: int):  # type: ignore[override]  # noqa: N803
        if not self.is_native_window_frame() and not self.isFullScreen():
            handled = self._win32_chrome.handle_native_event(eventType, int(message))
            if handled is not None:
                return handled
        return super().nativeEvent(eventType, message)

    def _toggle_maximize(self) -> None:
        if self._is_effectively_maximized():
            self._user_maximized = False
            if self.isMaximized():
                self.showNormal()
            elif self._normal_geometry is not None and self._normal_geometry.isValid():
                self.setGeometry(self._normal_geometry)
        else:
            self._normal_geometry = self.geometry()
            apply_maximized_to_work_area(self)
        self._sync_maximize_button_state()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._sync_gallery_mode()

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._sync_gallery_mode()
        if not self.is_native_window_frame():
            self._install_win32_chrome()
        # Recompute the work area when the window lands on another monitor
        # (mixed-DPI setup) instead of caching the screen captured at startup.
        handle = self.windowHandle()
        if handle is not None and not self._screen_change_connected:
            handle.screenChanged.connect(self._on_screen_changed)
            self._screen_change_connected = True

    def _on_screen_changed(self, screen) -> None:  # noqa: ANN001 - QScreen | None
        """Win32 ``WM_DPICHANGED`` analogue: re-apply the maximize geometry."""
        self._reapply_maximized_geometry(screen)
        self._sync_gallery_mode()

    def _reapply_maximized_geometry(self, screen=None) -> None:  # noqa: ANN001
        if not self._user_maximized:
            return
        screen = screen or self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        if self.geometry() != geo:
            self.setGeometry(geo)

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.Type.WindowStateChange:
            self._sync_maximize_button_state()
            if self.isMaximized() and self._user_maximized:
                self._reapply_maximized_geometry()
        # Qt 6 informs widgets about a DPR change; a maximized frameless window
        # must re-fit the (now different) work area.
        if event.type() == QEvent.Type.DevicePixelRatioChange:
            self._reapply_maximized_geometry()
            self._sync_gallery_mode()
        super().changeEvent(event)

    def _load_layout_document(self) -> LayoutConfigV2:
        """Version-2 document; the version-1 key is migrated when no version-2 exists.

        A fresh install (both keys empty) gets the defaults: the classic preset
        with the wide tool panel on the right and the gallery on the left.
        """
        return resolve_document(
            self._user_preferences.layout_state_v2_json,
            self._user_preferences.layout_state_json,
        )

    def reset_layout_to_default(self) -> None:
        self._layout_document = LayoutConfigV2()
        self._multiview_mode = False
        self._system_bar.set_multiview_checked(False)
        self._rebuild_layout()

    def _save_layout_state(self) -> None:
        """Persist the layout as a version-2 document (spec §8.1).

        The version-1 key is not written: it stays as the older build left it, so a
        rollback reads its own settings. Multiview is never part of the document.
        """
        self._user_preferences.layout_state_v2_json = self._layout_document.to_json()
        save_user_preferences(self._user_preferences)

    def _build_layout_menu(self, parent: QWidget | None = None) -> QMenu:
        """The «Компоновка» submenu (spec §4.1): preset radios, tool buttons, «Настроить…».

        Shared by the logo menu and the ``layout`` command; both build a fresh
        menu from the current document, so no stale checks survive a rebuild.
        The status bar and the single-file focus live in the settings section
        (UI-2 PR-2); Multiview is toggled by the «Сравнить» button.
        """
        from echo_personal_tool.presentation.layout.layout_settings import LayoutSettingsWidget

        menu = QMenu(parent)
        menu.setObjectName("layoutMenu")
        preset_group = QActionGroup(menu)
        preset_group.setExclusive(True)
        for preset in PRESETS:
            action = menu.addAction(tr(f"layout.preset_{preset}"))
            action.setCheckable(True)
            action.setData(("preset", preset))
            action.setChecked(self._layout_document.preset == preset)
            action.triggered.connect(lambda checked, p=preset: self._on_layout_preset_selected(p) if checked else None)
            preset_group.addAction(action)
        menu.addSeparator()
        tools_menu = menu.addMenu(tr("layout.tool_buttons"))
        tools_menu.setObjectName("layoutToolButtonsMenu")
        tools_group = QActionGroup(tools_menu)
        tools_group.setExclusive(True)
        for mode in LayoutSettingsWidget.TOOL_BUTTON_MODES:
            action = tools_menu.addAction(tr(f"layout.tool_buttons_{mode}"))
            action.setCheckable(True)
            action.setData(("tool_buttons", mode))
            action.setChecked(self._layout_document.tool_buttons == mode)
            action.triggered.connect(
                lambda checked, m=mode: self._on_layout_tool_buttons_selected(m) if checked else None
            )
            tools_group.addAction(action)
        menu.addSeparator()
        configure = menu.addAction(tr("layout.configure"))
        configure.setData(("configure", ""))
        configure.triggered.connect(self._open_layout_settings)
        return menu

    def _show_layout_menu(self) -> None:
        """The «Компоновка» command: the same menu as the logo menu, opened at the logo."""
        anchor = self._title_bar.app_button
        menu = self._build_layout_menu(anchor)
        menu.exec(anchor.mapToGlobal(QPoint(0, anchor.height())))

    def _sync_layout_menu_selection(self) -> None:
        """Re-read the radio checks of the logo menu after a change made elsewhere.

        The settings dialog and the ``layout`` command change the same document
        behind the open menu's back: without the sync the menu would keep showing
        the previous choice.
        """
        app_menu = self._title_bar.app_button.menu()
        if app_menu is None:
            return
        layout_menu = app_menu.findChild(QMenu, "appMenuLayout")
        if layout_menu is None:
            return
        for action in layout_menu.actions():
            data = action.data()
            if isinstance(data, tuple) and len(data) == 2 and data[0] == "preset":
                action.setChecked(self._layout_document.preset == data[1])
        tools_menu = layout_menu.findChild(QMenu, "layoutToolButtonsMenu")
        if tools_menu is not None:
            for action in tools_menu.actions():
                data = action.data()
                if isinstance(data, tuple) and len(data) == 2 and data[0] == "tool_buttons":
                    action.setChecked(self._layout_document.tool_buttons == data[1])

    def _open_layout_settings(self) -> None:
        """«Настроить…»: the settings dialog opens on the layout section (tab 0)."""
        self._show_user_preferences()

    def _build_app_menu(self) -> QMenu:
        """The application menu of the logo button (spec §4.1).

        Settings, layout, the reference set, help, about and quit move here from
        the button row of the system bar; UI-1 PR-3 empties the bar further.
        """
        menu = QMenu(self)
        menu.setObjectName("appMenu")
        menu.addAction(tr("app_menu.settings")).triggered.connect(self._show_user_preferences)
        layout_menu = self._build_layout_menu(menu)
        layout_menu.setObjectName("appMenuLayout")
        layout_menu.setTitle(tr("app_menu.layout"))
        menu.addMenu(layout_menu)
        menu.addSeparator()
        menu.addAction(tr("app_menu.references")).triggered.connect(self._show_references)
        menu.addAction(tr("app_menu.help")).triggered.connect(self._show_help)
        menu.addAction(tr("app_menu.guide")).triggered.connect(self._open_user_guide)
        menu.addSeparator()
        menu.addAction(tr("app_menu.about")).triggered.connect(self._show_about)
        menu.addAction(tr("app_menu.quit")).triggered.connect(self.close)
        return menu

    def _show_about(self) -> None:
        """«О программе»: name, version and the research-use disclaimer."""
        QMessageBox.about(self, tr("app_menu.about"), tr("system_bar.about_text", version=__version__))

    # ── The command field of the caption (UI-1 PR-2, spec §4.1) ─────────────

    def _sync_command_choices(self) -> None:
        """Feed the completion model with the localized commands of this build."""
        labels = [command_label(command, with_shortcut=False) for command in commands_for_profile(self._profile_name)]
        self._title_bar.set_command_choices(labels)

    def _open_command_palette(self) -> None:
        """Open the searchable TP-6 command palette (Ctrl+K / ⌘K)."""
        palette = CommandPalette(self._profile_name, self)
        if palette.exec() == QDialog.DialogCode.Accepted and palette.selected_command is not None:
            command = palette.selected_command
            self._run_command(command.action)
            self._show_status(tr("title_bar.command_done", label=command_label(command)))

    def _open_calculators(self) -> None:
        """Open the existing calculator tab from the command palette."""
        if not self._profile_capabilities.calculators:
            self._show_status(tr("tool_panel.calculators_unavailable"))
            return
        if self._tool_rail is not None and self._layout_document.rail:
            self._rail_panels_pinned = True
            self._attach_pinned_tool_panel()
        self._tool_panel.show_calculators_tab()
        self._tool_panel.show()

    def _on_command_text_changed(self, _text: str) -> None:
        """The legacy inline field remains available for direct command entry."""
        return None

    def _on_command_submitted(self, query: str) -> None:
        """Enter in the command field: run the first match of the catalogue."""
        command = resolve_command(query, profile=self._profile_name)
        if command is None:
            if query.strip():
                self._show_status(tr("title_bar.command_empty", query=query.strip()))
            self._title_bar.focus_command_field()
            return
        self._run_command(command.action)
        label = command_label(command)
        self._show_status(tr("title_bar.command_done", label=label))
        self._title_bar.set_command_text("")

    def _command_handlers(self) -> dict[str, object]:
        """Action id of the catalogue -> handler of this window (spec §4.1).

        Every :data:`~echo_personal_tool.presentation.command_catalog.COMMANDS`
        action must have an entry here; ``test_command_handlers_cover_the_whole_catalogue``
        keeps the field from offering a command that does nothing.
        """
        handlers: dict[str, object] = {
            "open_folder": self._open_folder,
            "load_server": self._open_orthanc_dialog,
            "new_tab": self._open_empty_tab_shortcut,
            "settings": self._show_user_preferences,
            "layout": self._show_layout_menu,
            "open_calculators": self._open_calculators,
            "references": self._show_references,
            "help": self._show_help,
            "guide": self._open_user_guide,
            "about": self._show_about,
            "caliper": lambda: self._on_caliper_requested(),
            "tool_spline_area": lambda: self._on_tool_button_requested("spline_area"),
            "tool_spline_volume": lambda: self._on_tool_button_requested("spline_volume"),
            "tool_manual_contour": lambda: self._on_tool_button_requested("manual_contour"),
            "tool_model_contour": lambda: self._on_tool_button_requested("model_contour"),
            "tool_vti_trace": lambda: self._on_tool_button_requested("vti_trace"),
            "tool_doppler_interval": lambda: self._on_tool_button_requested("doppler_interval"),
            "tool_auto_segment": lambda: self._on_tool_button_requested("auto_segment"),
            "heart_rate": self._on_heart_rate_requested,
            "calibration_bmode": self._on_calibration_requested,
            "calibration_doppler": self._on_doppler_calibration_requested,
            "reset": self._on_reset_measurements_requested,
            "multiview": self._on_multiview_button,
            "focus": self.toggle_focus_mode,
            "presenter": self._presenter.toggle,
            "quit": self.close,
        }
        return handlers

    def _run_command(self, action: str) -> None:
        """Dispatch a command-catalogue action to the handler it names."""
        from echo_personal_tool.presentation.command_catalog import (
            PROTOCOL_ACTION_PREFIX,
            REFERENCE_PARAM_PREFIX,
        )

        if action.startswith(REFERENCE_PARAM_PREFIX):
            # «Справочник: КДР» of the palette opens S1 on the row (UI-5 PR-2).
            self._open_reference_window(action[len(REFERENCE_PARAM_PREFIX) :])
            return
        if action.startswith(PROTOCOL_ACTION_PREFIX):
            # «Протоколы» of the palette start the runner (TP-6, same as the card).
            self._on_protocol_selected(action[len(PROTOCOL_ACTION_PREFIX) :])
            return
        handler = self._command_handlers().get(action)
        if callable(handler):
            handler()

    def _on_layout_preset_selected(self, preset: str) -> None:
        """A preset radio of the layout menu: rebuild without a restart (G-2)."""
        if preset not in PRESETS or preset == self._layout_document.preset:
            return
        self._layout_document = replace(self._layout_document, preset=preset)
        self._rebuild_layout()
        self._sync_layout_menu_selection()

    def _on_layout_tool_buttons_selected(self, mode: str) -> None:
        """A tool-buttons radio of the layout menu: ``row``/``panel`` wait for PR-3."""
        if mode == self._layout_document.tool_buttons:
            return
        try:
            document = replace(self._layout_document, tool_buttons=mode)
        except ValueError:
            return
        self._layout_document = document
        self._rebuild_layout()
        self._sync_layout_menu_selection()

    def _on_multiview_button(self) -> None:
        """«Сравнить»: toggle the Multiview session mode (spec §4.1)."""
        self._multiview_mode = not self._multiview_mode
        self._rebuild_layout()
        self._system_bar.set_multiview_checked(self._multiview_mode)
        if not self._multiview_mode:
            self._show_status(tr("multiview.status.exited"))

    # ── Multiview session (N-08: the comparison lives in
    # `presentation/comparison_coordinator.py`; these names stay on the window
    # because the rest of the window, the shortcuts and the tests use them) ──

    @property
    def _multiview(self) -> MultiViewController:
        return self._comparison.session

    @property
    def _pane_left(self) -> MultiViewPaneWidget | None:
        return self._comparison.pane_left

    @property
    def _pane_right(self) -> MultiViewPaneWidget | None:
        return self._comparison.pane_right

    @property
    def _multiview_transport(self) -> MultiViewTransportBar | None:
        return self._comparison.transport

    @property
    def _active_viewer(self) -> ViewerWidget | None:
        return self._comparison.active_viewer

    @_active_viewer.setter
    def _active_viewer(self, value: ViewerWidget | None) -> None:
        self._comparison.active_viewer = value

    def _set_multiview_mode(self, enabled: bool) -> None:
        """Flip the session flag, rebuild and keep the «Сравнить» button in sync."""
        self._multiview_mode = enabled
        self._rebuild_layout()
        self._system_bar.set_multiview_checked(enabled)

    def _enable_multiview_mode(self) -> None:
        """Enter Multiview from a gesture (Ctrl+click, «Открыть справа»)."""
        self._set_multiview_mode(True)

    def _multiview_enabled(self) -> bool:
        return self._comparison.enabled()

    def _ensure_multiview_transport(self) -> None:
        self._comparison.ensure_transport()

    def _teardown_multiview(self) -> None:
        self._comparison.teardown()

    def _ensure_multiview_panes(self) -> None:
        self._comparison.ensure_panes()

    def _sync_left_pane_from_controller(self) -> None:
        self._comparison.sync_left_pane_from_controller()

    def _multiview_pane_badge(
        self,
        instance: InstanceMetadata,
        study_uid: str | None,
        *,
        view_override: str = "",
    ) -> str:
        """«вкладка N · дата · модальность/вид» for one pane (Э10 §6.3, no PHI)."""
        return self._comparison.pane_badge(instance, study_uid, view_override=view_override)

    def _multiview_pane_badge_texts(self) -> tuple[str, str]:
        """Current pane badges for the Presenter mirror (Э10 §6.3)."""
        return self._comparison.pane_badge_texts()

    def _on_pane_view_label_changed(self, pane_id: PaneId, label: str) -> None:
        self._comparison.on_view_label_changed(pane_id, label)

    def _forward_pane_badges(self, left: str, right: str) -> None:
        """Mirror the Multiview pane badges onto the Presenter window (Э10 §6.3)."""
        self._presenter.forward_pane_badges(left, right)

    def _on_main_play_pause_requested(self) -> None:
        self._comparison.on_main_play_pause_requested()

    def _multiview_tool_blocked(self, tool_name: str) -> bool:
        return self._comparison.tool_blocked(tool_name)

    def _on_open_in_pane_requested(self, instance: object, side: str) -> None:
        self._comparison.open_in_pane(instance, side)

    def _on_pane_activated(self, pane_id: PaneId) -> None:
        self._comparison.on_pane_activated(pane_id)

    def _on_pane_cleared(self, pane_id: PaneId) -> None:
        self._comparison.on_pane_cleared(pane_id)

    def _on_pane_frame_selected(self, pane_id: PaneId, index: int) -> None:
        self._comparison.on_pane_frame_selected(pane_id, index)

    def _on_multiview_replace_requested(self, pane_id: PaneId) -> None:
        self._comparison.on_replace_requested(pane_id)

    def _on_multiview_warning(self, title: str, body: str) -> None:
        self._comparison.on_warning(title, body)

    def _on_multiview_left_released(self, frame_index: int) -> None:
        self._comparison.on_left_released(frame_index)

    def _refresh_multiview_transport(self) -> None:
        self._comparison.refresh_transport()

    def _multiview_route_gallery_click(self, selected: InstanceMetadata) -> bool:
        return self._comparison.route_gallery_click(selected)

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
        document: LayoutConfigV2,
        *,
        multiview: bool,
        plan: SlotPlan,
        use_splitter: bool,
        left: QWidget | None,
        right: QWidget | None,
    ) -> None:
        if self._viewer_stack.indexOf(self._viewer) < 0:
            self._viewer.show()
        if multiview and self._has_loaded_study:
            if self._pane_left is not None:
                self._pane_left.show()
            if self._pane_right is not None:
                self._pane_right.show()
        elif multiview:
            # Persisted pane wrappers can remain parented to the content widget
            # while an empty workspace displays the welcome stack.
            for pane in (self._pane_left, self._pane_right):
                if pane is not None and self._content_splitter.indexOf(pane) < 0:
                    pane.hide()

        if plan.bottom is not None:
            if self._bottom_container is not None:
                self._bottom_container.show()
            self._gallery.show()
        elif left is self._gallery or right is self._gallery:
            self._gallery.show()
        else:
            # UI-6: the focus view gives the whole row to the image.  A gallery
            # left out of every slot is detached, not deleted — hiding it here
            # keeps it from floating over the snapshot at its old geometry.
            self._gallery.hide()

        rail = SLOT_RAIL in (plan.left, plan.right)
        if self._tool_rail is not None:
            self._tool_rail.setVisible(rail)
            # §4.8: focus has no study panels, so the rail hides the toggle that
            # would bring them back; the normal view returns it.
            self._tool_rail.set_panels_button_visible(not self._focus_layout_active)
        if self._tool_row is not None:
            # The row is the head of the snapshot column, so the column decides
            # whether it is on screen; the plan only says whether it exists.
            self._tool_row.setVisible(plan.top == SLOT_TOOL_ROW)
        placed = use_splitter or SLOT_TOOL_PANEL in (plan.left, plan.right)
        if placed:
            self._tool_panel.show()
        elif rail and self._rail_panels_pinned and not self._focus_layout_active:
            # The rail's bottom button can bring the wide panel back even where the
            # preset gives it no slot of its own (§4.2); the pin survives a rebuild.
            self._tool_panel.show()
            self._attach_pinned_tool_panel()
        else:
            # §4.2: the rail takes the place of the wide panel only where the
            # preset gives that panel no slot of its own.  Under a filmstrip both
            # sides are free, so the rail sits left of the image and the panel
            # keeps the right slot.
            self._tool_panel.hide()
        self._refresh_tool_buttons()

    def _slot_widget(self, slot: str | None) -> QWidget | None:
        """The widget that fills a side slot of the table (the rail is ensured before)."""
        if slot == SLOT_GALLERY:
            return self._gallery
        if slot == SLOT_TOOL_PANEL:
            return self._tool_panel
        if slot == SLOT_RAIL:
            return self._tool_rail
        return None

    def _sync_gallery_mode(self, plan: SlotPlan | None = None) -> None:
        """Apply the responsive filmstrip policy for the current slot plan."""
        gallery = getattr(self, "_gallery", None)
        document = getattr(self, "_layout_document", None)
        if gallery is None or document is None:
            return
        if plan is None:
            plan = slot_plan(document, multiview=bool(getattr(self, "_multiview_mode", False)))
        dpr = max(0.001, float(self.devicePixelRatioF()))
        physical_width = float(self.width()) * dpr
        horizontal, compact_side_panel = gallery_mode_for_plan(
            plan,
            physical_window_width=physical_width,
        )
        if gallery._horizontal_mode != horizontal or gallery._compact_horizontal_mode != compact_side_panel:
            gallery.set_horizontal_mode(horizontal, compact_side_panel=compact_side_panel)

    def _rebuild_layout(self) -> None:
        """Assemble the content row from the slot table (spec §8.1: no flag branches)."""
        document = self._layout_document
        multiview = self._multiview_mode
        # UI-6: the focus view is a tab-scoped overlay over the chosen preset,
        # not a preset of its own, so it contributes a plan and nothing else.
        # Leaving it reassembles the same document untouched.
        if self._focus_layout_active and not multiview:
            plan = focus_plan()
        else:
            plan = slot_plan(document, multiview=multiview)
        self._gallery.set_multiview_enabled(multiview)
        self._comparison.set_start_hint(None)
        self._content_widget.setUpdatesEnabled(False)
        try:
            self._teardown_multiview()
            self._release_content_layout()
            self._teardown_bottom_gallery()
            self._clear_splitter(self._content_splitter)
            self._sync_gallery_mode(plan)

            if SLOT_RAIL in (plan.left, plan.right):
                self._ensure_tool_rail()

            use_splitter = plan.center == SLOT_SPLIT
            column = self._ensure_viewer_column()
            core = self._viewer_stack

            if multiview and not self._has_loaded_study:
                # A persisted Multiview preference must not hide the empty-tab
                # welcome page on startup. Panes are created when data arrive.
                self._viewer_stack.setCurrentWidget(self._start_page)
                column.set_center(core)
                column.set_top(self._column_top_widget(plan))
                column.set_bottom(self._ensure_protocol_step_bar())
                self._sync_protocol_step_bar()
                center: QWidget = column
            elif plan.center == SLOT_PANES:
                self._ensure_multiview_panes()
                assert self._pane_left is not None and self._pane_right is not None
                self._content_splitter.addWidget(self._pane_left)
                self._content_splitter.addWidget(self._pane_right)
                self._content_splitter.setHandleWidth(2)
                self._content_splitter.setChildrenCollapsible(False)
                self._content_splitter.setStretchFactor(0, 1)
                self._content_splitter.setStretchFactor(1, 1)
                self._content_splitter.blockSignals(True)
                self._content_splitter.setSizes([800, 800])
                self._content_splitter.blockSignals(False)
                self._ensure_multiview_transport()
                # The two panes are the column's payload already split, and the
                # row is never assembled in Multiview (§10.2 of the comparison
                # spec: the tools are refused there), so the splitter goes into
                # the content row on its own.
                column.set_center(None)
                column.set_top(None)
                center = self._content_splitter
            else:
                if use_splitter and self._mmode_active and self._mmode_widget is not None:
                    # M-mode: viewer + trace in a vertical splitter, the tool row
                    # above both of them (§4.1 — one strip per snapshot column).
                    if self._mmode_vertical_splitter is None:
                        self._mmode_vertical_splitter = QSplitter(Qt.Orientation.Vertical)
                        self._mmode_vertical_splitter.setHandleWidth(4)
                    if self._mmode_vertical_splitter.indexOf(self._viewer_stack) < 0:
                        self._mmode_vertical_splitter.addWidget(self._viewer_stack)
                    if self._mmode_vertical_splitter.indexOf(self._mmode_widget) < 0:
                        self._mmode_vertical_splitter.addWidget(self._mmode_widget)
                    self._mmode_vertical_splitter.setSizes([400, 600])
                    self._mmode_vertical_splitter.setStretchFactor(0, 1)
                    self._mmode_vertical_splitter.setStretchFactor(1, 1)
                    core = self._mmode_vertical_splitter
                column.set_center(core)
                column.set_top(self._column_top_widget(plan))
                # UI-3: the step bar lives in the column's bottom slot, between
                # the image and (later) the cine loop; it hides itself when no
                # protocol runs.
                column.set_bottom(self._ensure_protocol_step_bar())
                self._sync_protocol_step_bar()
                if use_splitter:
                    self._content_splitter.setChildrenCollapsible(True)
                    self._content_splitter.blockSignals(True)
                    self._content_splitter.addWidget(column)
                    self._content_splitter.addWidget(self._tool_panel)
                    self._content_splitter.setStretchFactor(0, 1)
                    self._content_splitter.setStretchFactor(1, 0)
                    self._content_splitter.setSizes([800, self._tool_panel_preferred_width()])
                    self._content_splitter.blockSignals(False)
                    center = self._content_splitter
                else:
                    center = column

            if not multiview:
                self._detach_viewer2()

            left = self._slot_widget(plan.left)
            right = self._slot_widget(plan.right)

            if left is not None:
                left.show()
                self._content_layout.addWidget(left)
            if center is not None:
                center.show()
                self._content_layout.addWidget(center, stretch=1)
            if right is not None:
                right.show()
                self._content_layout.addWidget(right)

            if plan.bottom is not None:
                self._bottom_container = QWidget()
                bottom_layout = QHBoxLayout(self._bottom_container)
                bottom_layout.setContentsMargins(0, 0, 0, 0)
                bottom_layout.addWidget(self._gallery)
                if self.statusBar() is not None:
                    status_index = self._root_layout.indexOf(self.statusBar())
                    self._root_layout.insertWidget(status_index, self._bottom_container)
                else:
                    self._root_layout.addWidget(self._bottom_container)

            self.statusBar().setVisible(document.status_bar_visible)
            self._apply_layout_visibility(
                document, multiview=multiview, plan=plan, use_splitter=use_splitter, left=left, right=right
            )
            if SLOT_RAIL in (plan.left, plan.right):
                self._attach_pinned_tool_panel()
            self._apply_tool_panel_frame(self._user_preferences)
            self._save_layout_state()
        finally:
            self._content_widget.setUpdatesEnabled(True)
        if multiview:
            # Rebalance only after the splitter has a real on-screen width.
            # Calling setSizes while it is still hidden can preserve the old
            # viewer/tool-panel ratio on Windows (especially at high DPI).
            QTimer.singleShot(0, self._balance_multiview_splitter)

    def _balance_multiview_splitter(self) -> None:
        if not self._multiview_enabled() or self._content_splitter.count() != 2:
            return
        self._content_layout.activate()
        width = self._content_splitter.contentsRect().width()
        if width <= 0:
            return
        self._content_splitter.setSizes([width, width])

    def _clear_content_layout(self) -> None:
        """Backward-compatible alias for tests."""
        self._release_content_layout()

    def _ensure_viewer2(self) -> None:
        """Create the right pane of the Multiview layout (idempotent)."""
        if self._viewer2 is not None:
            try:
                _ = self._viewer2.width()
                return
            except RuntimeError:
                self._viewer2 = None
        viewer = ViewerWidget()
        viewer.set_scroll_debounce_ms(self._controller.playback_config.scroll_debounce_ms)
        viewer.installEventFilter(self)
        viewer._graphics.installEventFilter(self)
        viewer._view.installEventFilter(self)
        # Stage 1 of Multiview is view-only: annotations stay pane-local and are
        # never forwarded to the main controller (spec 10.2).
        self._viewer2 = viewer
        self._comparison.attach_right_viewer(viewer)

    def _detach_viewer2(self) -> None:
        if self._viewer2 is None:
            return
        try:
            self._viewer2.hide()
        except RuntimeError:
            self._viewer2 = None

    # ── tool buttons of the snapshot column (UI-2 PR-3, D-08) ────────

    def _ensure_viewer_column(self) -> ViewerColumn:
        """The column that carries the row, the image and the bars below it.

        §4.1 measures it 42 + image + 58 + 66 pixels; UI-3 and UI-4 add the step
        bar and the cine loop through the same two setters, so the assembly of the
        window does not change again.
        """
        if self._viewer_column is None:
            self._viewer_column = ViewerColumn(self._content_widget)
        return self._viewer_column

    def _ensure_tool_row(self) -> ToolButtonRow:
        """The 42 px strip above the image (created once, then reused)."""
        if self._tool_row is None:
            self._tool_row = ToolButtonRow(self._content_widget)
            self._tool_row.action_requested.connect(self._on_tool_button_requested)
        self._tool_row.set_labels_mode(self._layout_document.tool_labels)
        return self._tool_row

    def _ensure_tool_rail(self) -> ToolButtonRail:
        """The 70 px rail beside the image: the same tools, taller (§4.1)."""
        if self._tool_rail is None:
            self._tool_rail = ToolButtonRail(self._content_widget)
            self._tool_rail.action_requested.connect(self._on_tool_button_requested)
            self._tool_rail.side_panels_toggled.connect(self._on_rail_panels_toggled)
        self._tool_rail.set_labels_mode(self._layout_document.tool_labels)
        return self._tool_rail

    # ── focus view of a single file (UI-6, spec §4.8) ───────────────

    def _column_top_widget(self, plan: SlotPlan) -> QWidget | None:
        """The head of the snapshot column: the tool row, or the focus strip.

        §4.8 puts a thin strip above the image instead of the 42 px tool row.
        Both live in the same column slot, so a preset switch and the focus
        toggle use one path; outside focus the row is exactly what the plan
        asked for.
        """
        if plan.top == SLOT_TOOL_ROW:
            return self._ensure_tool_row()
        if self._focus_layout_active and not self._multiview_mode:
            return self._ensure_focus_header()
        return None

    def _ensure_focus_header(self) -> FocusHeader:
        """The strip over the snapshot (created on the first focus entry)."""
        if self._focus_header is None:
            self._focus_header = FocusHeader(self._content_widget)
            self._focus_header.exit_requested.connect(self.toggle_focus_mode)
            self._focus_header.update_geometry()
        return self._focus_header

    def _ensure_focus_layer(self) -> FocusLayer:
        """The floating card and cine plate, parented to the viewer."""
        if self._focus_layer is None:
            layer = FocusLayer(self._viewer)
            layer.card.copy_requested.connect(self._copy_focus_measurements)
            layer.cine.play_pause_requested.connect(self._toggle_playback_shortcut)
            layer.cine.frame_selected.connect(self._on_focus_frame_selected)
            self._focus_layer = layer
        return self._focus_layer

    def _focus_allowed(self) -> bool:
        """Whether the view may be shown at all.

        Focus is a view of one image: Multiview shows two clips by definition,
        so the mode is refused there instead of tearing the comparison apart.
        """
        return not self._multiview_mode

    def _focus_tab_state(self):
        """The active tab that carries the mode (S-02), like the report switch.

        Not gated on «Закладки»: with tabs switched off the single tab still
        holds the state, so an explicit exit with F survives a reload there too
        (``_report_mode_active`` reads the same tab the same way).
        """
        try:
            return self._tabs.active
        except Exception:  # noqa: BLE001 - a missing tab means "no state to keep"
            return None

    def focus_mode_active(self) -> bool:
        """True while the tab shows the focus view (S-02: the state is the tab's)."""
        tab = self._focus_tab_state()
        if tab is not None:
            return bool(tab.focus_mode)
        return self._focus_layout_active

    def toggle_focus_mode(self) -> None:
        """F — the way in and out of the single-file focus view (§4.8).

        Entering needs a loaded clip and a single-file workspace; the refusal
        explains itself in the status bar instead of silently doing nothing.
        """
        if self.focus_mode_active() or self._focus_layout_active:
            self._set_focus_mode(False, decided=True)
            return
        if not self._focus_allowed() or not self._has_loaded_study:
            self._show_status(tr("focus.load_first") if not self._has_loaded_study else tr("focus.unavailable"))
            return
        studies = self._active_studies()
        if not should_enter_focus(enabled=True, studies=studies):
            self._show_status(tr("focus.unavailable"))
            return
        self._set_focus_mode(True, decided=True)

    def _active_studies(self) -> list:
        """Clips of the active tab, or of the controller when tabs are off."""
        tab = self._focus_tab_state()
        if tab is not None and tab.studies:
            return list(tab.studies)
        return list(getattr(self._controller, "studies", ()) or ())

    def _set_focus_mode(self, enabled: bool, *, decided: bool, announce: bool = True) -> None:
        """Apply the mode to the window and remember it on the tab.

        The layout document is never touched: focus is an overlay over the
        chosen preset, and a restart must not resume in it (the tab owns the
        flag, the preference file does not).
        """
        enabled = bool(enabled)
        changed = enabled != self._focus_layout_active
        self._focus_layout_active = enabled
        tab = self._focus_tab_state()
        if tab is not None:
            self._tabs.set_focus_mode(tab.tab_id, enabled, decided=decided)
        if changed:
            self._rebuild_layout()
        self._apply_focus_surfaces()
        if changed and announce:
            self._show_status(tr("focus.entered") if enabled else tr("focus.left"))

    def _sync_focus_from_tab(self) -> None:
        """Show the focus view the active tab remembers (S-02, called on tab switches).

        The coordinator asks this hook next to ``_report_mode_page``: that is
        the moment the surface changes, and the moment a tab's own mode could
        go stale.  A Multiview session always wins — two clips are not «one
        file», so the mode is dropped rather than shown around a comparison.
        """
        tab = self._focus_tab_state()
        if tab is None:
            return
        desired = bool(tab.focus_mode) and not self._multiview_mode
        if desired == self._focus_layout_active:
            return
        self._set_focus_mode(desired, decided=False, announce=False)

    def _maybe_enter_focus(self, studies: list) -> None:
        """§4.8: a fresh single-file load opens focus by itself (UQ-02).

        Runs once per source (``focus_decided``): an explicit exit with F is
        not undone by reloading the same tab, while a new source — a different
        file or a replaced folder — gets its own decision.
        """
        tab = self._focus_tab_state()
        if tab is not None and tab.focus_decided:
            self._sync_focus_from_tab()
            return
        enter = (
            should_enter_focus(
                enabled=bool(self._layout_document.single_file_focus),
                studies=studies,
            )
            and not self._multiview_mode
        )
        self._set_focus_mode(enter, decided=True, announce=False)

    def _apply_focus_surfaces(self) -> None:
        """Side effects that do not need a rebuild: the strip, plates and overlay."""
        active = self._focus_layout_active
        if not active and self._focus_header is None and self._focus_layer is None:
            # The mode was never entered in this window: nothing to hide and
            # nothing to re-sync, so a plain load pays only for this check.
            return
        header = self._focus_header
        if header is not None:
            header.setVisible(active)
            if active:
                header.set_info(self._focus_header_info())
        if active:
            layer = self._ensure_focus_layer()
            layer.set_visible(True)
            layer.reload_text()
            layer.set_cine_state(**self._focus_cine_state())
            self._sync_focus_measurements()
        elif self._focus_layer is not None:
            self._focus_layer.set_visible(False)
        # The viewer keeps the built-in cine strip for the normal view; inside
        # focus the floating plate is the transport, so the strip steps aside.
        self._viewer.set_transport_visible(not active)
        # The card shows the same values as the on-image box; two copies of the
        # same numbers over one snapshot are noise, so the box steps aside too.
        self._viewer.set_results_overlay_suppressed(active)
        if not active:
            # Re-sync (not just un-suppress): a measurement made inside focus has
            # to appear on the image as soon as the box comes back.
            self._sync_results_overlay(self._controller.state_manager.snapshot)

    def _focus_cine_state(self) -> dict[str, object]:
        """Current transport facts of the main viewer, in the plate's own names."""
        state = self._controller.state_manager.snapshot
        return {
            "playing": bool(state.is_playing),
            "current_frame": int(state.current_frame_index),
            "total_frames": int(state.total_frames),
            "fps": float(state.fps or 0.0),
        }

    def _focus_header_info(self) -> FocusHeaderInfo:
        """File facts for the strip: name, projection, patient, study date."""
        state = self._controller.state_manager.snapshot
        instance = state.instance
        if instance is None:
            return FocusHeaderInfo()
        demographics = self._focus_demographics(instance)
        return FocusHeaderInfo(
            file_label=_loaded_file_label(instance),
            projection=(instance.series_description or "").strip(),
            patient=getattr(demographics, "name", "") or "",
            date=getattr(demographics, "study_date", "") or "",
        )

    def _focus_demographics(self, instance: InstanceMetadata):
        """Demographics of ``instance``, read from the header once per file.

        The report path re-opens the container on every call; the strip is
        refreshed on every played frame, so the result is cached per instance.
        A non-DICOM clip and an unreadable header both degrade to ``None`` and
        the strip simply leaves the field out.
        """
        key = instance.sop_instance_uid
        if key in self._focus_demographics_cache:
            return self._focus_demographics_cache[key]
        demographics = None
        if instance.path is not None and instance.media_format == "dicom":
            try:
                from echo_personal_tool.application.dicom_io import (
                    read_patient_demographics,
                )

                demographics = read_patient_demographics(instance.path)
            except Exception as exc:  # noqa: BLE001 - a broken header is not fatal
                log_boundary_failure(logger, "patient.demographics", exc, code="io", level=logging.WARNING)
                demographics = None
        if len(self._focus_demographics_cache) > 64:
            self._focus_demographics_cache.clear()
        self._focus_demographics_cache[key] = demographics
        return demographics

    def _focus_measurement_text(self) -> str:
        """Plain-text summary of this file's values (same formatter as the overlay)."""
        state = self._controller.state_manager.snapshot
        snapshot = self._controller.compute_overlay_snapshot(state)
        return format_results_overlay(
            snapshot,
            time_calibrated=self._viewer.is_doppler_time_calibrated(),
            length_display_unit=self._user_preferences.length_display_unit,
        )

    def _sync_focus_measurements(self) -> None:
        """Refresh the card from the current clip (cheap: no rebuild, no re-read)."""
        if self._focus_layer is None or not self._focus_layout_active:
            return
        self._focus_layer.set_measurements(measurement_lines(self._focus_measurement_text()))

    def _copy_focus_measurements(self) -> None:
        """«Копировать»: the file facts and its values, as one plain-text block."""
        lines = measurement_lines(self._focus_measurement_text())
        if not lines:
            return
        from echo_personal_tool.presentation.focus_mode import copy_text

        info = self._focus_header_info()
        text = copy_text(info, lines, title=tr("focus.card.title"))
        QApplication.clipboard().setText(text)
        self._show_status(tr("focus.copied", count=len(lines)))

    def _on_focus_frame_selected(self, index: int) -> None:
        """The floating plate seeks the same controller the built-in slider drives."""
        state = self._controller.state_manager.snapshot
        if state.total_frames <= 1:
            return
        self._slider_navigating = True
        self._controller.state_manager.set_frame(max(0, min(int(index), state.total_frames - 1)))

    def _sync_focus_view(self) -> None:
        """Push the current state into the strip and the plate (called on each frame)."""
        if not self._focus_layout_active:
            return
        if self._focus_header is not None:
            self._focus_header.set_info(self._focus_header_info())
        if self._focus_layer is not None:
            self._focus_layer.set_cine_state(**self._focus_cine_state())
        self._sync_focus_measurements()

    def _tool_button_state(self) -> tool_buttons.ToolButtonState:
        """What the row and the rail dim themselves against (D-08)."""
        from echo_personal_tool.domain.tool_panel_view import PANEL_CONTEXT_2D, PANEL_CONTEXT_DOPPLER

        context = PANEL_CONTEXT_DOPPLER if self._tool_doppler_mode else PANEL_CONTEXT_2D
        return tool_buttons.ToolButtonState(
            has_clip=self._has_loaded_study,
            multiview=self._multiview_mode,
            context=context,
            doppler_mode=self._tool_doppler_mode,
        )

    def _refresh_tool_buttons(self) -> None:
        """Push the context facts into the views that are currently assembled."""
        state = self._tool_button_state()
        for widget in (self._tool_row, self._tool_rail):
            if widget is not None:
                widget.set_state(state)
        # Availability and the armed tool are separate questions: a repaint must
        # not drop the pressed look of the tool the clinician is using.
        armed = self._armed_tool_button()
        self._tool_button_active = armed
        latched = self._latched_tool_buttons()
        for widget in (self._tool_row, self._tool_rail):
            if widget is not None:
                widget.set_latched(latched)
                widget.set_active(armed)

    def _on_tool_doppler_mode_changed(self, mode: str | None) -> None:
        """The panel's context chip (D-03 TP): a Doppler tool needs a Doppler mode."""
        self._tool_doppler_mode = (mode or "").strip().lower() or None
        self._refresh_tool_buttons()

    def _on_tool_button_requested(self, button_id: str) -> None:
        """The one entry of both views (D-09 TP).

        A measurement button carries the payload of its catalog entry and ends in
        :meth:`_on_measure_action` — the same sink the Measures menu and the panel
        use; a mode button calls the handler its own shortcut is bound to, so a
        click and the key cannot drift apart.
        """
        spec = tool_buttons.tool_button_spec(button_id)
        if spec is None:
            logger.warning("unknown tool button: %s", button_id)
            return
        payload = tool_buttons.payload(spec)
        if payload is not None:
            if spec.id in {"freehand_area", "freehand_volume"}:
                # The freehand pair arms the General tool in stroke mode for
                # this drawing; the preference itself stays untouched.
                self._viewer.set_area_tool_mode("freehand")
            elif spec.id in {"spline_area", "spline_volume"}:
                # Plain pair: back to the stored preference after a freehand use.
                self._viewer.set_area_tool_mode(getattr(self._user_preferences, "area_tool_mode", "click"))
            self._last_contour_button = (
                spec.id if spec.id in {"spline_area", "spline_volume", "freehand_area", "freehand_volume"} else None
            )
            self._on_measure_action(payload.action, payload.view, payload.phase, payload.extra)
            self._sync_tool_button_active()
            return
        handler = self._tool_button_handlers().get(spec.ref)
        if handler is None:
            logger.warning("tool button %s has no handler", button_id)
            return
        handler()
        self._sync_tool_button_active()

    def _tool_button_handlers(self) -> dict[str, Callable[[], None]]:
        """Handlers of the mode buttons of the row and the rail.

        The registry handlers first, then the viewer-level ones.  A mode button
        whose key lives in the *viewer* context («K», «T», «V», the loupe) is
        routed to the very method the key calls — the previous table answered
        «tool button … has no handler» and the button did nothing (item 3 of the
        2026-10-23 acceptance list).
        """
        handlers = dict(getattr(self, "_shortcut_handlers", {}))
        handlers.setdefault("calibration_toggle", self._toggle_calibration_tool)
        handlers.setdefault("calibration_clear", self._controller.clear_manual_calibration)
        handlers.setdefault("doppler_interval", self._start_doppler_interval_tool)
        handlers.setdefault("vti_trace", lambda: self._on_doppler_trace_tool("VTI"))
        handlers.setdefault("refine_contour", self._refine_active_contour)
        handlers.setdefault("zoom_fit", lambda: self._set_zoom_mode("fit"))
        handlers.setdefault("zoom_loupe", self._toggle_zoom_loupe)
        handlers.setdefault("cine_phase_markers", self._toggle_phase_markers)
        return handlers

    # ── tool modes shared by the hotkeys, the row and the rail ──────────

    def _active_tool_viewer(self):  # noqa: ANN201 - ViewerWidget, imported lazily
        """The viewer the tools act on (the active Multiview pane, else the main one)."""
        return self._active_viewer or self._viewer

    def _toggle_calibration_tool(self) -> None:
        """«K» / the calibration button: arm the two-click distance calibration."""
        viewer = self._active_tool_viewer()
        viewer.toggle_calibration_caliper()
        if viewer.is_calibration_active:  # a Qt property of the viewer
            self._show_hint(tr("status.calibration_click", cancel_key=shortcut_label("cancel_tool")))
        self._sync_tool_button_active()

    def _toggle_phase_markers(self) -> None:
        """«D/S маркеры»: force ED/ES detection for the current echo clip.

        Automatic detection is deliberately conservative: it waits for a
        positive cardiac label in the DICOM header, which many exported cine
        clips (and every MP4) do not carry.  This is the physician's explicit
        per-clip override — it never changes the metadata gate globally and it
        still refuses a spectral Doppler / M-mode time axis.
        """
        state = self._controller.state_manager.snapshot
        instance = getattr(state, "instance", None)
        uid = getattr(instance, "sop_instance_uid", "") or ""
        if instance is None or getattr(instance, "clip_mode", "2d") != "2d":
            self._show_hint(tr("status.ds_markers_unavailable"))
            return
        forced = self._phase_markers_forced()
        if uid in forced:
            forced.discard(uid)
            enabled = False
        else:
            forced.add(uid)
            enabled = True
        self._show_hint(tr("status.ds_markers_on") if enabled else tr("status.ds_markers_off"))
        # Invalidate the cache key so the same clip is re-detected (or cleared)
        # with the override; the worker's generation guard discards late runs.
        self._phase_timeline_key = None
        self._sync_phase_timeline(state, uid or None)
        self._sync_tool_button_active()

    def _phase_markers_forced(self) -> set[str]:
        """Lazy per-instance latch (MainWindow.__init__ must not grow)."""
        if not hasattr(self, "_phase_markers_forced_uids"):
            self._phase_markers_forced_uids: set[str] = set()
        return self._phase_markers_forced_uids

    def _latched_tool_buttons(self) -> tuple[str, ...]:
        try:
            instance = self._controller.state_manager.snapshot.instance
        except AttributeError:  # pragma: no cover - during a partial construction
            return ()
        uid = getattr(instance, "sop_instance_uid", "") or ""
        return ("ds_markers",) if uid and uid in self._phase_markers_forced() else ()

    def _start_doppler_interval_tool(self) -> None:
        """«T» / the interval button: measure a time between two Doppler levels."""
        viewer = self._active_tool_viewer()
        if not self._ensure_doppler_ready(require_time=True):
            return
        viewer.set_doppler_tool_mode("interval")
        self._show_hint(tr("toolbtn.doppler_interval_tooltip"))
        self._sync_tool_button_active()

    def _refine_active_contour(self) -> None:
        """«R» / the refine action: snap and smooth the contour being edited."""
        viewer = self._active_tool_viewer()
        refined, mode = viewer.refine_active_open_contour()
        if refined:
            self._controller.on_contours_changed(viewer.contours())
            self._show_hint(f"Refine {mode}")
        else:
            self._show_hint(tr("status.no_lv_open_arc"))

    def _set_zoom_mode(self, mode: str) -> None:
        self._active_tool_viewer().set_zoom_mode(mode)

    def _toggle_zoom_loupe(self) -> None:
        """The «Лупа» button of the row: click-to-zoom on the frame (item 4)."""
        viewer = self._active_tool_viewer()
        if not viewer.zoom_loupe_active() and viewer._current_frame is None:
            self._show_status(tr("status.load_frame_or_finish_contour"))
            return
        active = not viewer.zoom_loupe_active()
        viewer.set_zoom_loupe_active(active)
        self._show_hint(tr("toolbtn.zoom_active") if active else "")
        self._sync_tool_button_active()

    def _armed_tool_button(self) -> str | None:
        """Which mode button is armed right now, read from the viewer itself.

        One authority (the viewer's own state) for both the pressed look of the
        row/rail and the hotkeys, so «the button does not light up when I press
        its key» cannot happen (item 3 of the 2026-10-23 list).
        """
        viewer = self._active_tool_viewer()
        if viewer is None:
            return None
        if viewer.zoom_loupe_active():
            return "zoom"
        if getattr(viewer, "is_calibration_active", False):
            return "calibration"
        if getattr(viewer, "_doppler_calibration_active", False) or getattr(viewer, "_doppler_cal_step", None):
            return "calibration"
        doppler_mode = viewer.get_doppler_tool_mode() if hasattr(viewer, "get_doppler_tool_mode") else "none"
        if doppler_mode == "trace":
            return "vti_trace"
        if doppler_mode == "interval":
            return "doppler_interval"
        if doppler_mode == "peak":
            return "model_contour"
        # Both are Qt properties of the viewer, not methods.
        if getattr(viewer, "is_linear_caliper_active", False):
            return "caliper"
        if getattr(viewer, "is_contour_mode_active", False):
            # Three contour tools share one flag on the viewer; its kind says
            # which button was pressed.  A closed contour (area / volume) has no
            # kind of its own, so the button that started it is remembered.
            kind = getattr(viewer, "_contour_mode_kind", None)
            if kind == "model":
                return "model_contour"
            if kind == "closed":
                return self._last_contour_button
            return "manual_contour"
        return None

    def _sync_tool_button_active(self) -> None:
        """Light the button of the armed tool in whichever view is assembled.

        Always pushed, never skipped on an unchanged value: the widgets also
        clear a button that toggled itself on click and ended up arming nothing
        (item 3 of the 2026-10-23 list).
        """
        armed = self._armed_tool_button()
        self._tool_button_active = armed
        latched = self._latched_tool_buttons()
        for widget in (self._tool_row, self._tool_rail):
            if widget is not None:
                widget.set_latched(latched)
                widget.set_active(armed)

    def _on_rail_panels_toggled(self) -> None:
        """The bottom button of the rail: show / hide the side panels (§4.2)."""
        show = not self._tool_panel.isVisible()
        self._rail_panels_pinned = show
        if show:
            self._attach_pinned_tool_panel()
            self._tool_panel.show()
            self._gallery.show()
        else:
            self._tool_panel.hide()
            self._gallery.hide()

    def _attach_pinned_tool_panel(self) -> None:
        """Place the wide panel after the rail, the way the old bar did it."""
        if self._tool_rail is None or not self._rail_panels_pinned:
            return
        if self._content_layout.indexOf(self._tool_rail) >= 0:
            self._attach_tool_panel_after(self._tool_rail)
        elif self._content_layout.indexOf(self._tool_panel) < 0:
            self._content_layout.addWidget(self._tool_panel)

    def _attach_tool_panel_after(self, anchor: QWidget) -> None:
        bar_idx = self._content_layout.indexOf(anchor)
        if bar_idx < 0:
            return
        self._remove_tool_panel_from_content_layout()
        self._content_layout.insertWidget(bar_idx + 1, self._tool_panel)

    def _remove_tool_panel_from_content_layout(self) -> None:
        idx = self._content_layout.indexOf(self._tool_panel)
        if idx >= 0:
            self._content_layout.takeAt(idx)

    @_prof
    def _show_references(self) -> None:
        self._open_reference_dialog()

    def _open_user_reference_document(self) -> None:
        """Open the user's own Markdown/PDF from the reference document viewer."""
        self._open_reference_dialog(open_document=True)

    def _open_user_guide(self) -> None:
        """Show the bundled guide in the in-app reader; never prompt for a file."""
        self._show_help()

    def _show_support_feedback(self) -> None:
        from echo_personal_tool.presentation.feedback_dialog import show_support_feedback_dialog

        show_support_feedback_dialog(self)

    def _show_help(self) -> None:
        from echo_personal_tool.presentation.help_dialog import show_help_dialog

        show_help_dialog(self)

    def _on_welcome_theme_changed(self, theme: str) -> None:
        self._apply_welcome_preference("theme_mode", theme)

    def _on_welcome_language_changed(self, language: str) -> None:
        self._apply_welcome_preference("language", language)

    def _apply_welcome_preference(self, field: str, value: str) -> None:
        """Theme/language picked on the welcome screen: persist and re-apply."""
        from dataclasses import replace

        if getattr(self._user_preferences, field) == value:
            return
        preferences = replace(self._user_preferences, **{field: value})
        self._user_preferences = preferences
        save_user_preferences(preferences)
        self._apply_user_preferences(preferences)

    def _open_reference_dialog(
        self,
        param_id: str | None = None,
        *,
        open_document: bool = False,
    ) -> None:
        """«Справочник»: the S1 window (UI-5 PR-2), or the document viewer.

        ``open_document`` is reserved for adding a user-selected document from
        the start page or the S1 «Sources» action; that viewer still lives in
        :mod:`presentation.ase_reference_dialog`. The bundled User Guide uses
        :meth:`_open_user_guide` and never opens a file picker. Everything that
        asks for a *parameter* — the results overlay, the card S2, the command
        palette — opens the handbook window on that row instead.
        """
        # Lazy import: the reference dialog pulls in QtWebEngine/PyMuPDF,
        # which are excluded from the Presenter (lite) build.
        if not get_profile_capabilities().reference_ui:
            self._show_status(tr("app.reference_unavailable"))
            return
        if open_document:
            try:
                from echo_personal_tool.presentation.ase_reference_dialog import (
                    show_ase_reference_dialog,
                )
            except ImportError:
                self._show_status(tr("app.reference_unavailable"))
                return
            show_ase_reference_dialog(self, param_id=param_id, open_document=True)
            return
        self._open_reference_window(param_id=param_id)

    def _reset_reference_window(self) -> None:
        if getattr(self, "_reference_window", None) is None:
            return
        from echo_personal_tool.presentation.reference_window import reset_reference_window

        reset_reference_window()
        self._reference_window = None

    def _refresh_reference_window_theme(self) -> None:
        """Repaint the open handbook window when the theme or the font changes."""
        if getattr(self, "_reference_window", None) is None:
            return
        self._reference_window.apply_theme()

    def _open_reference_window(self, param_id: str | None = None) -> None:
        """Open (or raise) the handbook window on ``param_id`` (spec §4.7).

        The window is bound to the open study: the sex and the age of the
        patient choose the norm column, and the values of the study projection
        fill the «Пациента» column.  Nothing is recomputed here — the window
        reads the same projection and the same card model as the report.
        """
        if not get_profile_capabilities().reference_ui:
            self._show_status(tr("app.reference_unavailable"))
            return
        try:
            from echo_personal_tool.presentation.reference_window import show_reference_window
        except ImportError:
            self._show_status(tr("app.reference_unavailable"))
            return
        sex, age, values = self._reference_patient_binding()
        window = show_reference_window(self, param_id=param_id, sex=sex, age=age, values=values)
        if window is not self._reference_window:
            # Connect once per window: the cached window outlives every opening.
            self._reference_window = window
            window.constructor_requested.connect(self._open_reference_constructor)
            window.sources_requested.connect(self._open_reference_sources)

    def _reference_patient_binding(self) -> tuple[str, int | None, dict[str, float]]:
        """Sex, age and the values of the study for the handbook window."""
        from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
        from echo_personal_tool.domain.services.reference_topics import reference_values
        from echo_personal_tool.domain.services.study_projection import build_study_projection

        snapshot = None
        patient = None
        try:
            snapshot = self._controller.compute_study_snapshot()
            # One aggregate for both answers: the report header and the values.
            patient = self._report_patient_info(snapshot)
        except Exception as exc:  # noqa: BLE001 — an unreadable header must not block the handbook
            log_boundary_failure(logger, "patient.demographics", exc, code="io", level=logging.WARNING)
        sex = ""
        age: int | None = None
        if patient is not None:
            sex = _normalize_patient_sex(patient.sex)
            age = _age_of(patient.age)
        if snapshot is not None:
            projection = build_study_projection(snapshot or MeasurementSnapshot())
        else:  # the snapshot failed above — still open the handbook, just without values
            projection = build_study_projection(MeasurementSnapshot())
        values = reference_values({key: value.value for key, value in projection.values.items()})
        return sex, age, values

    def _on_norms_toggled(self, visible: bool) -> None:
        """UI-5 UQ-03: the position of the «Нормы» switch is remembered."""
        self._user_preferences.reference_norm_dots = bool(visible)
        save_user_preferences(self._user_preferences)

    def _row_reference_sex(self) -> str:
        """Sex of the patient for the S2 cards of the panel rows (UI-5).

        Cached per open study: the hover card appears after 400 ms and must
        not re-read the DICOM header on every row.
        """
        instance = self._controller.state_manager.snapshot.instance
        token = (getattr(instance, "path", None), getattr(instance, "media_format", None))
        if token != self._row_sex_token:
            self._row_sex_token = token
            self._row_sex_value = ""
            try:
                patient = self._report_patient_info(self._controller.compute_study_snapshot())
                self._row_sex_value = _normalize_patient_sex(patient.sex)
            except Exception as exc:  # noqa: BLE001 — a corrupt header must not block the card
                log_boundary_failure(logger, "patient.demographics", exc, code="io", level=logging.WARNING)
        return self._row_sex_value

    def _open_reference_constructor(self) -> None:
        """«Конструктор…» of the S1 footer: edit the handbook, then reload the window."""
        from echo_personal_tool.constructor.constructor_dialog import show_constructor_dialog

        show_constructor_dialog(self._reference_window or self)
        if self._reference_window is not None:
            self._reference_window.reload_data()

    def _open_reference_sources(self) -> None:
        """«Источники» of the S1 footer: the document viewer of the handbook."""
        self._open_reference_dialog(open_document=True)

    @_prof
    def _show_user_preferences(self, *_args: object, initial_tab: str | None = None) -> None:
        show_user_preferences_dialog(
            self,
            on_apply=self._apply_user_preferences,
            orthanc_cache=self._orthanc_cache,
            protected_cache_sessions=self._active_orthanc_cache_sessions,
            measurement_storage_action=self._show_measurement_storage,
            initial_tab=initial_tab,
        )

    def _show_tools_settings(self, _tool_id: str = "") -> None:
        self._show_user_preferences(initial_tab="tools")

    def _on_tool_layout_changed(self, encoded: str) -> None:
        self._user_preferences.tool_layout_v3_json = encoded
        save_user_preferences(self._user_preferences)

    def _show_measurement_storage(self) -> bool:
        """Open the saved-measurements manager; returns True when it rewrote the
        stored autosave preference (delete-all disables it «now and next launch»)."""
        from echo_personal_tool.presentation.measurement_storage_dialog import MeasurementStorageDialog

        dialog = MeasurementStorageDialog(self._controller, self)
        dialog.exec()
        # The manager may have deleted or imported records: re-read the disk
        # instead of reusing the summaries cached before it opened.
        self._invalidate_saved_records()
        self._refresh_start_page_recents()
        return dialog.preferences_changed

    def _on_persistence_status(self, code: str) -> None:
        states = {"ready", "dirty", "loading", "saving", "saved", "restored", "partial", "disabled", "saved_drafts"}
        if code in states:
            text = tr("persistence." + code)
        else:
            # Keep the status bar readable in Russian: translate well-known codes,
            # fall back to the raw code for anything unmapped.
            code_key = "persistence.code." + code
            code_text = tr(code_key)
            text = tr("persistence.error", code=code if code_text == code_key else code_text)
        if hasattr(self, "_persistence_label"):
            self._persistence_label.setText(text)
            self._persistence_label.setToolTip(tr("persistence.privacy"))
        # A failed write only reports itself; it never locks the viewer, the
        # gallery or the tools — the save/don't-save prompt owns the decision
        # when the user leaves the study (office-style flow).
        if code not in {"dirty", "saving", "saved"}:
            for widget in (self._viewer, self._gallery, self._tool_panel):
                widget.setEnabled(code != "loading")
        if code in {"saved", "saved_drafts", "restored", "partial", "disabled"}:
            # The stored records changed: the next render reads them again.
            self._invalidate_saved_records()
        if code not in states:
            self._show_status(text)

    def _on_persistence_blocked(self) -> None:
        # A second flush inside the controller can refuse a tab load after
        # the UI has entered its busy state. Do not leave the input veil up.
        if self._tab_loading_id is not None:
            self._abort_tab_load()
        QMessageBox.warning(self, tr("persistence.title"), tr("persistence.blocked_navigation"))

    def _on_persistence_conflict(self, study_uids: list) -> None:
        """Runtime enable: an open study has a saved record this session never loaded."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(tr("persistence.conflict_title"))
        box.setText(tr("persistence.conflict_text"))
        load_button = box.addButton(tr("persistence.conflict_load"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(tr("persistence.conflict_keep"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        self._controller.resolve_persistence_conflict(box.clickedButton() is load_button)

    def _sync_measurement_persistence(self, stored: UserPreferences, effective: UserPreferences) -> None:
        """Apply the autosave toggle immediately (no restart).

        Enabling starts saving in this session (records of already open studies
        are adopted first, with a RAM-vs-disk resolution when they have one).
        Disabling settles unsaved edits first: save / discard / cancel.
        ``stored`` is the object the dialog persisted; ``effective`` is the
        presenter-intercepted copy the window runs with.
        """
        persistence = self._controller.measurement_persistence
        enabled = effective.measurement_persistence_enabled
        if persistence.enabled == enabled:
            return
        self._invalidate_saved_records()
        if enabled:
            self._controller.set_measurement_persistence_enabled(True)
            return
        if not persistence.has_pending_edits:
            self._controller.set_measurement_persistence_enabled(False)
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(tr("persistence.disable_title"))
        box.setText(tr("persistence.disable_dirty_text"))
        save_button = box.addButton(tr("persistence.disable_save"), QMessageBox.ButtonRole.AcceptRole)
        discard_button = box.addButton(tr("persistence.disable_discard"), QMessageBox.ButtonRole.DestructiveRole)
        cancel_button = box.addButton(tr("button.cancel"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is discard_button:
            if persistence.discard_pending():
                return
        elif clicked is save_button:
            if persistence.flush():
                self._controller.set_measurement_persistence_enabled(False)
                return
        # Cancel, or a write/discard that could not be confirmed: keep autosave
        # on and put the stored preference back so the next launch agrees with it.
        if clicked is not None and clicked is not cancel_button:
            self._show_status(tr("persistence.disable_blocked"))
        self._revert_measurement_persistence_preference(stored, effective)

    def _revert_measurement_persistence_preference(self, stored: UserPreferences, effective: UserPreferences) -> None:
        from echo_personal_tool.infrastructure.user_preferences import save_user_preferences

        stored.measurement_persistence_enabled = True
        effective.measurement_persistence_enabled = True
        save_user_preferences(stored)

    def _active_orthanc_cache_sessions(self) -> set[str]:
        """Cache sessions backing what is on screen (kept as the window's name)."""
        return self._download_coordinator.active_cache_sessions()

    def _show_properties_tab(self) -> None:
        self._tool_panel.show_properties_tab()

    def _enforce_profile_preferences(self, preferences: UserPreferences) -> UserPreferences:
        """Clamp runtime toggles for capabilities absent from the active product.

        Last-session values are separately gated at every read, display, resume,
        and persistence boundary. Keeping an in-memory value intact matters for
        Presenter-mode preference overlays, without making it persistent or
        allowing it to resume a path.
        """
        if not self._profile_capabilities.tabs:
            preferences.tabs_enabled = False
        if not self._profile_capabilities.measurement_storage:
            preferences.measurement_persistence_enabled = False
        return preferences

    def _apply_user_preferences(self, preferences: UserPreferences) -> None:
        # Re-entrancy guard: a stylesheet/flag change can re-enter through a
        # resize or show event (X11 ghost windows, crashed the app on theme
        # switch — 2026-10-25). The nested call must not start a second pass.
        if getattr(self, "_applying_preferences", False):
            return
        self._applying_preferences = True
        try:
            self._apply_user_preferences_inner(preferences)
        finally:
            self._applying_preferences = False

    def _apply_user_preferences_inner(self, preferences: UserPreferences) -> None:
        # Presenter mode may overlay the projector preset: the caller's
        # object is kept as the base, the effective copy is applied.
        stored = preferences  # the object the settings dialog already persisted
        preferences = self._presenter.intercept_preferences(preferences)
        self._enforce_profile_preferences(preferences)
        if not preferences.tabs_enabled and not self._close_extra_tabs_for_single_mode():
            # The dialog persists before on_apply. Cancel/failure must restore
            # both the runtime flag and QSettings, without undoing other settings.
            stored.tabs_enabled = preferences.tabs_enabled = True
            save_user_preferences(stored)
        self._user_preferences = preferences
        configure_shortcuts(preferences.shortcut_overrides_json)
        self._apply_layout_preferences(preferences)
        self._title_bar.set_tabs_visible(
            self._profile_capabilities.tabs
            and preferences.tabs_enabled
            and (not self.isFullScreen() or not self._title_bar.isHidden())
        )
        start_page = getattr(self, "_start_page", None)
        if start_page is not None:
            start_page.set_measurement_persistence_enabled(preferences.measurement_persistence_enabled)
            start_page.set_show_patient_data(preferences.start_page_show_patient_data)
            start_page.set_continue_target(
                preferences.last_session_source,
                preferences.last_opened_folder,
                date=preferences.last_session_date,
                clip_count=preferences.last_session_clip_count,
            )
            start_page.set_ui_font_size(preferences.ui_font_size)
        if not preferences.results_overlay_custom_position:
            self._instance_overlay_positions.clear()
            self._study_overlay_positions.clear()
            self._last_overlay_position = None
            self._current_overlay_study_uid = None
        from echo_personal_tool.infrastructure.i18n import set_language

        set_language(preferences.language)
        self._reload_ui_language()
        app = QApplication.instance()
        if app is not None:
            app.setFont(ui_font(pixel_size=preferences.ui_font_size))
        apply_clinical_theme(
            font_size=preferences.ui_font_size,
            theme=preferences.theme_mode,
            accent_palette=preferences.accent_palette,
        )
        if start_page is not None:
            start_page.set_theme(preferences.theme_mode)
            start_page.set_language(preferences.language)
            start_page.refresh_theme()
        self._gallery.reload_text()
        # Chrome sizes are font-derived (Э4): re-measure after a font change.
        self._tool_panel.update_font_metrics()
        for widget in (getattr(self, "_tool_row", None), getattr(self, "_tool_rail", None)):
            if widget is not None:  # built on demand, may be off (UI-2 PR-3)
                widget.update_font_metrics()
        report_page = getattr(self, "_report_page", None)
        if report_page is not None:  # built on first entry into «Отчёт» (UI-4 PR-1)
            report_page.set_font_size(preferences.pdf_font_size)
            report_page.apply_theme()
            # Language and the length unit change the document itself.
            report_page.request_refresh()
        focus_header = getattr(self, "_focus_header", None)
        if focus_header is not None:  # built on first entry into the focus view
            focus_header.apply_theme()
        focus_layer = getattr(self, "_focus_layer", None)
        if focus_layer is not None:
            focus_layer.apply_theme()
        # Update window icon to match theme
        from PySide6.QtGui import QIcon

        from echo_personal_tool.presentation.dark_theme import get_logo_path

        self.setWindowIcon(QIcon(str(get_logo_path())))
        # Frame flags: only touch the native window when the preference actually
        # changed. Calling setWindowFlags/show on every theme/font pass leaves
        # ghost windows on X11/KDE (the multi-window cascade of 2026-10-25).
        native_frame = bool(getattr(preferences, "native_window_frame", False))
        last_native = getattr(self, "_last_native_frame_applied", None)
        if last_native is None or last_native != native_frame:
            self.apply_window_frame_mode(native_frame)
            self._last_native_frame_applied = native_frame
        if not self.is_native_window_frame():
            self._install_win32_chrome()
        self._system_bar.reload_icons()
        # The caption is font-derived (Э4): its height, the tabs inside it and
        # the window controls are re-measured after every font/scale change.
        self._title_bar.reload_icons()
        self._title_bar.update_control_height()
        # The tool buttons tint their glyphs and rebuild their stylesheet from the
        # active theme (UI-2 PR-3, UA-14: a reload must not need a restart).
        for widget in (self._tool_row, self._tool_rail):
            if widget is not None:
                widget.reload_icons()
        self.apply_status_bar_tokens()
        self._refresh_reference_window_theme()
        self._viewer.refresh_hint_theme()
        with QSignalBlocker(self._tool_panel.controls._magnetic_snap_check):
            self._tool_panel.controls._magnetic_snap_check.setChecked(preferences.magnetic_snap_enabled)
        self._tool_panel.set_auto_play(preferences.auto_play)
        self._viewer.set_magnetic_snap_enabled(preferences.magnetic_snap_enabled)
        self._viewer.set_area_tool_mode(preferences.area_tool_mode)
        self._viewer.set_lv_contour_input(preferences.lv_contour_input)
        self._viewer.set_atrial_contour_input(preferences.atrial_contour_input)
        self._viewer.apply_user_preferences(preferences)
        self._gallery.apply_scale(preferences.thumbnail_scale)
        self._gallery.set_sort_mode(preferences.thumbnail_sort_mode)
        self._controller.set_playback_speed_multiplier(preferences.playback_speed_multiplier)
        self._tool_panel.set_dicom_inspector_visible(preferences.show_dicom_tag_inspector)
        self._refresh_dicom_inspector()
        self._tool_panel.rebuild_menu_with_preferences(preferences)
        # UI-5: the rebuild may have swapped the Measures tab in place — the
        # card hooks and the remembered «Нормы» switch go to the new instance.
        self._tool_panel.set_reference_sex_provider(self._row_reference_sex)
        self._tool_panel.set_norms_visible(bool(getattr(preferences, "reference_norm_dots", False)))
        self._apply_tool_panel_frame(preferences)
        self._sync_results_overlay(self._controller.state_manager.snapshot)
        self._sync_measurement_persistence(stored, preferences)
        self._refresh_start_page_recents()

    def _apply_layout_preferences(self, preferences: UserPreferences) -> None:
        """Rebuild when the settings changed the layout document (no restart, G-2).

        The settings dialog is the only writer besides this window, so an equal
        document means «nothing changed» — including the apply pass of ``__init__``,
        which runs before the first rebuild.
        """
        document = resolve_document(
            preferences.layout_state_v2_json,
            preferences.layout_state_json,
        )
        if document == self._layout_document:
            return
        self._layout_document = document
        self._rebuild_layout()
        self._sync_layout_menu_selection()

    def _reload_status_labels(self) -> None:
        """Refresh the permanent status-bar labels, which no widget reloads.

        They are plain ``QLabel``s added directly to the bar, so a live
        language switch would otherwise leave the old wording on screen.
        """
        label = getattr(self, "_persistence_label", None)
        if label is not None:
            label.setText(
                tr("persistence.ready")
                if self._user_preferences.measurement_persistence_enabled
                else tr("persistence.disabled")
            )
            label.setToolTip(tr("persistence.privacy"))
        warning = getattr(self, "_research_warning", None)
        if warning is not None:
            warning.setText(tr("layout.research_use_only"))

    def _reload_ui_language(self) -> None:
        self._system_bar.reload_text()
        self._title_bar.reload_text()
        self._title_bar.set_app_menu(self._build_app_menu())
        self._sync_command_choices()
        for widget in (self._tool_row, self._tool_rail):
            if widget is not None:
                widget.set_language(get_language())
                widget.reload_text()
        self._viewer.reload_text()
        self._tool_panel.reload_text()
        self._apply_protocol_step_bar_labels()
        self._gallery.reload_text()
        if getattr(self, "_report_page", None) is not None:
            self._report_page.reload_text()
        start_page = getattr(self, "_start_page", None)
        if start_page is not None:
            start_page.reload_text()
        # UI-6: the focus strip, the card and the cine plate are shell strings too.
        if self._focus_header is not None:
            self._focus_header.reload_text()
            self._focus_header.update_geometry()
            self._focus_header.set_info(self._focus_header_info())
        if self._focus_layer is not None:
            self._focus_layer.reload_text()
        self._reload_status_labels()
        self._show_status(tr("status.startup"))
        self._sync_results_overlay(self._controller.state_manager.snapshot)
        # UI-5 PR-2: the handbook window is built in the language it was opened in;
        # a language switch rebuilds it (the cached one is dropped, not patched).
        self._reset_reference_window()
        # The strain window names every panel it builds, so it follows the same
        # rule: dropping it is cheaper and safer than patching a screenful of
        # captions, and the next open speaks the new language.
        self._reset_strain_window()

    def _on_magnetic_snap_changed(self, enabled: bool) -> None:
        self._viewer.set_magnetic_snap_enabled(enabled)
        self._user_preferences.magnetic_snap_enabled = enabled
        save_user_preferences(self._user_preferences)

    def _on_despeckle_changed(self, enabled: bool) -> None:
        self._viewer.set_despeckle_enabled(enabled)
        self._user_preferences.despeckle_enabled = enabled
        save_user_preferences(self._user_preferences)

    def _on_results_overlay_position_changed(self, x_ratio: float, y_ratio: float) -> None:
        self._last_overlay_position = (x_ratio, y_ratio)
        instance = self._controller.state_manager.snapshot.instance
        if instance is not None:
            self._instance_overlay_positions[instance.sop_instance_uid] = (x_ratio, y_ratio)
        if self._viewer.is_results_overlay_pinned():
            study_uid = self._controller.resolve_study_uid(instance)
            self._study_overlay_positions[study_uid] = (x_ratio, y_ratio)

    def _on_results_overlay_parameter_clicked(self, param_id: str) -> None:
        """Open Structured Reference browser at the given parameter."""
        self._open_reference_dialog(param_id=param_id)

    def _restore_results_overlay_position(self, instance_uid: str | None) -> None:
        instance = self._controller.state_manager.snapshot.instance
        study_uid = self._controller.resolve_study_uid(instance)
        if study_uid != self._current_overlay_study_uid:
            self._current_overlay_study_uid = study_uid
            if study_uid in self._study_overlay_positions:
                x_ratio, y_ratio = self._study_overlay_positions[study_uid]
                self._viewer.set_results_overlay_position(x_ratio, y_ratio, custom=True)
                return
            if self._last_overlay_position is not None:
                x_ratio, y_ratio = self._last_overlay_position
                self._viewer.set_results_overlay_position(x_ratio, y_ratio, custom=True)
                return
            self._viewer.reset_results_overlay_to_default()
            return
        if instance_uid and instance_uid in self._instance_overlay_positions:
            x_ratio, y_ratio = self._instance_overlay_positions[instance_uid]
            self._viewer.set_results_overlay_position(x_ratio, y_ratio, custom=True)
            return
        if self._last_overlay_position is not None:
            x_ratio, y_ratio = self._last_overlay_position
            self._viewer.set_results_overlay_position(x_ratio, y_ratio, custom=True)
            return
        self._viewer.reset_results_overlay_to_default()

    def _on_gold_export_requested(self, phase: str, frame_index: int, chamber: str) -> None:
        self._controller.save_gold_annotation(phase=phase, frame_index=frame_index, chamber=chamber)

    def _on_mmode_column_ready(self, column: object, frame_index: object) -> None:
        if self._mmode_widget is not None and self._mmode_active:
            import numpy as np

            if isinstance(column, np.ndarray):
                self._mmode_widget.on_new_column(column)

    def _on_mmode_line_completed(self, start: object, end: object) -> None:
        if self._mmode_widget is not None and isinstance(start, tuple) and isinstance(end, tuple):
            cached_frames = (
                self._controller.get_cached_frames() if hasattr(self._controller, "get_cached_frames") else []
            )
            if cached_frames:
                self._mmode_widget.recalculate_from_frames(cached_frames, start, end, mask=self._viewer.mask_phi)
            # Apply calibration to M-mode depth axis
            # Priority: M-mode specific calibration > B-mode pixel spacing > fallback
            depth_mm = 0.0
            mmode_cal = (
                self._viewer.get_mmode_calibration_state()
                if hasattr(self._viewer, "get_mmode_calibration_state")
                else None
            )
            if mmode_cal is not None and mmode_cal.is_complete():
                depth_mm = self._mmode_widget._num_samples * mmode_cal.vertical_mm_per_pixel
            else:
                state = self._controller.state_manager.snapshot
                spacing = state.effective_pixel_spacing
                if spacing is None:
                    spacing = (0.1, 0.1)
                row_spacing_mm, col_spacing_mm = spacing[0], spacing[1]
                # Use Euclidean distance along scan line with proper pixel spacing
                dx = abs(float(end[0]) - float(start[0]))
                dy = abs(float(end[1]) - float(start[1]))
                depth_mm = ((dx * col_spacing_mm) ** 2 + (dy * row_spacing_mm) ** 2) ** 0.5
            if depth_mm > 0:
                self._mmode_widget.set_depth_range_mm(depth_mm)
            state = self._controller.state_manager.snapshot
            if (
                state.instance is not None
                and state.instance.frame_time_ms is not None
                and state.instance.frame_time_ms > 0
            ):
                self._mmode_widget.set_time_calibration_ms_per_pixel(state.instance.frame_time_ms)
            self._show_status(tr("status.mmode_line_placed"))

    def _on_teichholz_ed_complete(self, measurements) -> None:
        """Handle completion of 3 Teichholz ED calipers (МЖП, КДР, ЗСЛЖ)."""
        if len(measurements) < 3:
            return
        ivsd = measurements[0].value_mm
        lvidd = measurements[1].value_mm
        lvpwd = measurements[2].value_mm
        if ivsd is None or lvidd is None or lvpwd is None:
            return
        from echo_personal_tool.domain.calculations.teichholz_mmode import compute_teichholz_from_mmode

        study_uid = self._controller._current_study_uid
        session = self._controller._measurement_session.get(study_uid) if study_uid else None
        height_cm = session.height_cm if session else None
        weight_kg = session.weight_kg if session else None
        result = compute_teichholz_from_mmode(
            ivsd_mm=ivsd,
            lvidd_mm=lvidd,
            lvpwd_mm=lvpwd,
            height_cm=height_cm,
            weight_kg=weight_kg,
        )
        self._show_status(
            f"{tr('mmode.teich_ed_labels.0')}={ivsd:.1f} {tr('mmode.teich_ed_labels.1')}={lvidd:.1f} {tr('mmode.teich_ed_labels.2')}={lvpwd:.1f} "
            f"{tr('domain.report.kdo')}={result.edv_ml:.1f} {tr('strain.unit_ml')}  "
            f"{tr('domain.report.rwt')}={result.rwt:.2f}  {tr('domain.report.lvm')}={result.lvm_g:.1f} g"
        )

    def _on_teichholz_es_complete(self, measurement) -> None:
        """Handle completion of Teichholz ESV caliper (КСР)."""
        if measurement.value_mm is None:
            return
        from echo_personal_tool.domain.calculations.teichholz_mmode import compute_teichholz_from_mmode
        from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement

        if self._mmode_widget is None:
            return
        ed_values = self._mmode_widget._measurement_tool.get_teichholz_ed_values()
        if ed_values is None:
            return
        ivsd, lvidd, lvpwd = ed_values
        lvesd = measurement.value_mm
        study_uid = self._controller._current_study_uid
        session = self._controller._measurement_session.get(study_uid) if study_uid else None
        height_cm = session.height_cm if session else None
        weight_kg = session.weight_kg if session else None
        result = compute_teichholz_from_mmode(
            ivsd_mm=ivsd,
            lvidd_mm=lvidd,
            lvpwd_mm=lvpwd,
            lvesd_mm=lvesd,
            height_cm=height_cm,
            weight_kg=weight_kg,
        )
        # Store as linear measurements for overlay integration
        instance = self._controller.state_manager.snapshot.instance
        instance_uid = instance.sop_instance_uid if instance else ""
        linear = (
            LinearMeasurement(label="IVSd", pixel_length=0, millimeter_length=ivsd, sop_instance_uid=instance_uid),
            LinearMeasurement(label="LVEDD", pixel_length=0, millimeter_length=lvidd, sop_instance_uid=instance_uid),
            LinearMeasurement(label="LVPWd", pixel_length=0, millimeter_length=lvpwd, sop_instance_uid=instance_uid),
            LinearMeasurement(label="LVESD", pixel_length=0, millimeter_length=lvesd, sop_instance_uid=instance_uid),
        )
        # Enter through the viewer: it owns the clip's caliper list, and its
        # report is what the study session treats as authoritative.
        self._viewer.add_linear_measurements(linear)
        self._sync_results_overlay(self._controller.state_manager.snapshot)
        lvmi_str = f"  {tr('domain.report.lvmi')}={result.lvmi_g_m2:.1f} g/m²" if result.lvmi_g_m2 else ""
        self._show_status(
            f"{tr('mmode.teichholz')}: {tr('mmode.teich_ed_labels.0')}={result.ivsd_mm:.1f} {tr('mmode.teich_ed_labels.2')}={result.lvpwd_mm:.1f} "
            f"{tr('mmode.teich_ed_labels.1')}={result.lvidd_mm:.1f} {tr('mmode.label_es')}={lvesd:.1f} "
            f"{tr('domain.report.kdo')}={result.edv_ml:.1f} {tr('domain.report.kso')}={result.esv_ml:.1f} "
            f"{tr('domain.report.fv')}={result.lvef_percent:.1f}%  "
            f"{tr('domain.report.rwt')}={result.rwt:.2f}  {tr('domain.report.lvm')}={result.lvm_g:.1f} g"
            f"{lvmi_str}"
        )

    def _wire_wl_persistence(self) -> None:
        for slider_widget in (
            self._tool_panel.controls.window_slider,
            self._tool_panel.controls.level_slider,
            self._tool_panel.controls.dr_slider,
        ):
            slider_widget.slider().valueChanged.connect(self._persist_window_level_preferences)

    def _persist_window_level_preferences(self) -> None:
        self._user_preferences.wl_window = self._tool_panel.controls.window_slider.slider().value()
        self._user_preferences.wl_level = self._tool_panel.controls.level_slider.slider().value()
        self._user_preferences.wl_dr = self._tool_panel.controls.dr_slider.slider().value()
        save_user_preferences(self._user_preferences)

    def _refresh_dicom_inspector(self) -> None:
        instance = self._controller.state_manager.snapshot.instance
        path = instance.path if instance is not None else None
        self._tool_panel.load_dicom_inspector(path)

    def _save_diagnostics(self) -> None:
        from datetime import datetime

        from echo_personal_tool.infrastructure.diagnostics import create_diagnostic_bundle
        from echo_personal_tool.presentation.styled_dialogs import styled_save_file

        default_name = f"SonoForge-diagnostics-{datetime.now().astimezone():%Y%m%d-%H%M%S}.zip"
        destination, _ = styled_save_file(
            self,
            tr("diagnostics.save_dialog_title"),
            str(Path.home() / default_name),
            tr("diagnostics.file_filter"),
        )
        if not destination:
            return
        try:
            saved_path = create_diagnostic_bundle(Path(destination), app=QApplication.instance())
        except Exception as exc:  # noqa: BLE001 - report a failed support export to the user
            log_boundary_failure(logger, "diagnostics.bundle", exc, code="io", level=logging.WARNING)
            QMessageBox.warning(
                self,
                tr("diagnostics.save_dialog_title"),
                tr("diagnostics.error", error=safe_error_category(exc)),
            )
            return
        QMessageBox.information(
            self,
            tr("diagnostics.save_dialog_title"),
            tr("diagnostics.saved", path=str(saved_path)) + "\n\n" + tr("diagnostics.privacy"),
        )

    def open_folder_path(
        self,
        directory: Path,
        *,
        origin: str = TAB_ORIGIN_FOLDER,
        cache_session_id: str = "",
    ) -> None:
        from echo_personal_tool.application.saved_records import (
            default_logs_dir,
            migrate_legacy_scan_errors,
        )

        # The folder opens in a tab of its own (D-29); a server-backed session
        # keeps its PACS cache id and has no local root.
        root = "" if origin == TAB_ORIGIN_SERVER else str(directory)
        if not self._acquire_tab_for_load(origin, root, cache_session_id):
            return
        try:
            migrate_legacy_scan_errors(directory)
        except OSError as exc:
            log_boundary_failure(logger, "scanner.legacy_log_migration", exc, code="io", level=logging.WARNING)
        self._reset_doppler_mode_override()
        self._controller.open_folder(directory, error_log_path=default_logs_dir() / "scan_errors.log")

    def open_server_dialog(self, *, preselect_study_uid: str | None = None) -> None:
        """Open the "load from server" dialog (also used at startup, D-27)."""
        if not self._profile_capabilities.server_dialog:
            return
        self._open_orthanc_dialog(preselect_study_uid=preselect_study_uid)

    def _remember_session_source(
        self,
        source: str,
        folder: str | None = None,
        *,
        clip_count: int | None = None,
    ) -> None:
        """Record what "Last session" has to reopen next time (Q-05/D-27).

        ``folder`` keeps ``last_opened_folder`` in sync for the disk case; the
        server case records only the source, because the PACS cache is cleared
        on exit and there is no path worth remembering.  The date and clip
        count feed the «Продолжить» label (Э5 §7.1); ``clip_count=None`` keeps
        the previously recorded count (the load may not be finished yet).
        Presenter builds only remember the picker path in RAM — last-session
        paths are never persisted or resumed from the portable drive.
        """
        from datetime import date as _date

        if folder is not None:
            self._last_folder_for_picker = folder
        if not self._profile_capabilities.continue_last_session:
            return
        self._user_preferences.last_session_source = source
        self._user_preferences.last_session_date = _date.today().isoformat()
        if clip_count is not None:
            self._user_preferences.last_session_clip_count = int(clip_count)
        if folder is not None:
            self._user_preferences.last_opened_folder = folder
        save_user_preferences(self._user_preferences)
        if hasattr(self, "_start_page"):
            self._start_page.set_continue_target(
                source,
                self._user_preferences.last_opened_folder,
                date=self._user_preferences.last_session_date,
                clip_count=self._user_preferences.last_session_clip_count,
            )

    def _update_last_session_clip_count(self, clip_count: int) -> None:
        """Fill in «число клипов» once the load finished (Э5 §7.1)."""
        self._user_preferences.last_session_clip_count = int(clip_count)
        save_user_preferences(self._user_preferences)
        if hasattr(self, "_start_page"):
            self._start_page.set_continue_target(
                self._user_preferences.last_session_source,
                self._user_preferences.last_opened_folder,
                date=self._user_preferences.last_session_date,
                clip_count=self._user_preferences.last_session_clip_count,
            )

    def _reset_doppler_mode_override(self) -> None:
        """Drop the explicit Doppler mode back to Auto on study open (Э2).

        The override is a per-study assumption (typically for MP4/JPEG clips
        without DICOM metadata); a new study starts from the DICOM mode.
        """
        self._tool_panel.reset_doppler_mode()
        self._viewer.reset_doppler_mode_override()
        self._sync_tool_panel_context()

    @_prof
    def _open_folder(self) -> None:
        from echo_personal_tool.infrastructure.i18n import tr
        from echo_personal_tool.presentation.styled_dialogs import styled_select_directory

        # Э3: external dialog/store instances may have written since startup.
        self._recent_store.reload()
        self._start_page.refresh_recent_places()
        start = (
            self._recent_store.last_folder()
            or self._last_folder_for_picker
            or (self._user_preferences.last_opened_folder if self._profile_capabilities.continue_last_session else "")
        )
        directory = styled_select_directory(self, tr("dialog.select_folder"), start)
        if not directory:
            return
        folder = Path(directory)
        # Record immediately for the next picker; `open_folder_path` also covers
        # non-dialog entry points such as the Continue action.
        self._recent_store.record(folder)
        self._start_page.refresh_recent_places()
        self._remember_session_source(SESSION_SOURCE_FOLDER, str(folder))
        self.open_folder_path(folder)

    def _open_recent_folder(self, path_text: str) -> None:
        if not self._profile_capabilities.recent_folders:
            return
        folder = Path(path_text)
        if not folder.is_dir():
            self._start_page.refresh_recent_places()
            self._show_status(tr("start_page.missing_folder"))
            return
        self._remember_session_source(SESSION_SOURCE_FOLDER, str(folder))
        self.open_folder_path(folder)

    def _continue_last_session(self) -> None:
        if not self._profile_capabilities.continue_last_session:
            return
        source = self._user_preferences.last_session_source
        if source == SESSION_SOURCE_SERVER:
            self.open_server_dialog()
            return
        folder = Path(self._user_preferences.last_opened_folder) if self._user_preferences.last_opened_folder else None
        if folder is None or not folder.is_dir():
            self._start_page.set_continue_target(
                SESSION_SOURCE_FOLDER,
                str(folder or ""),
                date=self._user_preferences.last_session_date,
                clip_count=self._user_preferences.last_session_clip_count,
            )
            self._show_status(tr("start_page.missing_folder"))
            return
        self._remember_session_source(SESSION_SOURCE_FOLDER, str(folder))
        self.open_folder_path(folder)

    def _focus_start_page_search(self) -> None:
        """Ctrl+F: focus the study-browser search while the start page shows.

        Registered window-wide like the other «main-window» actions, so the
        handler first checks that the empty-tab page is the visible surface;
        with a study open the key does nothing here (UI-7).
        """
        start_page = getattr(self, "_start_page", None)
        if start_page is None:
            return
        stack = getattr(self, "_viewer_stack", None)
        if stack is not None and stack.currentWidget() is not start_page:
            return
        start_page.focus_search()

    def _on_start_page_recent_study(self, summary: object) -> None:
        """Open the folder or the server loader for a «Недавние исследования» row (Э5 §7.3)."""
        if not isinstance(summary, RecentStudySummary) or not summary.available:
            return
        if summary.origin == "server":
            self._open_orthanc_dialog(preselect_study_uid=summary.study_uid or None)
            return
        if summary.folder:
            self._open_recent_folder(summary.folder)
            return
        self._show_status(tr("start_page.recent_study_missing"))

    def _request_saved_records(self, *, force: bool = False) -> object | None:
        """Return the cached stored-record listing and refresh it once per change.

        The window never walks the measurements directory on the GUI thread and
        never treats "could not read" as "nothing stored": the summaries come
        from the persistence worker through
        :meth:`MeasurementPersistence.list_saved_records` (QH-1a, S-07). The
        returned listing is the last known state — ``None`` while the first read
        is still in flight — and the start page is re-rendered when it lands.
        """
        enabled = bool(getattr(self._user_preferences, "measurement_persistence_enabled", False))
        persistence = getattr(self._controller, "measurement_persistence", None)
        if not enabled or persistence is None:
            # Presenter/off-policy must not list records at all (S-10).
            self._saved_records_listing = None
            self._saved_records_pending = False
            return None
        listing = getattr(self, "_saved_records_listing", None)
        pending = bool(getattr(self, "_saved_records_pending", False))
        stale = force or listing is None or getattr(listing, "failed", False)
        if stale and not pending:
            self._saved_records_pending = True
            persistence.list_saved_records(self._on_saved_records_listed)
        return listing

    def _on_saved_records_listed(self, listing: object) -> None:
        """Worker result: cache it and re-render the start page block."""
        self._saved_records_pending = False
        self._saved_records_listing = listing
        if not getattr(self._user_preferences, "measurement_persistence_enabled", False):
            return
        self._refresh_start_page_recents()

    def _invalidate_saved_records(self) -> None:
        """Drop the cached summaries after a save, delete or toggle change."""
        self._saved_records_listing = None

    def _stored_record_summaries(self, seen_keys: set[str]) -> list[RecentStudySummary]:
        """Rows for the stored records, including honest unreadable/failed states."""
        from echo_personal_tool.infrastructure.i18n import tr_plural

        listing = self._request_saved_records()
        if listing is None:
            return []
        rows: list[RecentStudySummary] = []
        for record in getattr(listing, "records", ()):
            if not record.readable:
                continue  # aggregated below; the manager shows them one by one
            if record.key in seen_keys:
                continue
            seen_keys.add(record.key)
            date = record.saved_at[:10] if record.saved_at else ""
            title = " · ".join(part for part in (date, tr("start_page.recent_studies_saved")) if part)
            details = (
                f"{tr_plural('start_page.recent_studies_measurements', record.measurement_count)} · "
                f"{tr('start_page.recent_studies_saved')}"
            )
            rows.append(
                RecentStudySummary(
                    key=record.key,
                    title=title,
                    details=details,
                    origin="stored",
                    folder="",
                    study_uid="",
                    available=False,
                    study_date=date,
                    measurement_count=int(record.measurement_count or 0),
                )
            )
        if getattr(listing, "failed", False):
            rows.append(
                RecentStudySummary(
                    key="stored-unavailable",
                    title=tr("start_page.recent_studies_failed"),
                    details=tr("start_page.recent_studies_failed_tip"),
                    origin="stored",
                    available=False,
                )
            )
        elif listing.unreadable:
            rows.append(
                RecentStudySummary(
                    key="stored-unreadable",
                    title=tr_plural("start_page.recent_studies_unreadable", listing.unreadable),
                    details=tr("start_page.recent_studies_unreadable_tip"),
                    origin="stored",
                    available=False,
                )
            )
        return rows

    def _refresh_start_page_recents(self) -> None:
        """Fill «Недавние исследования» from folder/server history and Z2-M (Э5 §7.3)."""
        start_page = getattr(self, "_start_page", None)
        if start_page is None:
            return
        from datetime import datetime

        from echo_personal_tool.infrastructure.i18n import tr_plural

        run_records = sorted(
            [
                (record, "folder", self._folder_study_roots.get(record.study_uid, ""))
                for record in self._folder_study_history.records()
            ]
            + [(record, "server", "") for record in self._download_history.records()],
            key=lambda entry: entry[0].downloaded_at,
            reverse=True,
        )
        summaries: list[RecentStudySummary] = []
        seen: set[str] = set()
        for record, origin, folder in run_records:
            if record.study_uid in seen:
                continue
            seen.add(record.study_uid)
            date = record.study_datetime.strftime("%Y-%m-%d") if isinstance(record.study_datetime, datetime) else ""
            title = " · ".join(part for part in (date, str(record.description or "")) if part)
            origin_label = tr(
                "start_page.recent_studies_local" if origin == "folder" else "start_page.recent_studies_server"
            )
            clip_count = int(record.clip_count or 0)
            details = f"{tr_plural('start_page.recent_studies_clips', clip_count)} · {origin_label}"
            summaries.append(
                RecentStudySummary(
                    key=str(record.study_uid or title),
                    title=title or origin_label,
                    details=details,
                    origin=origin,
                    folder=folder,
                    study_uid=str(record.study_uid or ""),
                    available=bool(folder) if origin == "folder" else True,
                    study_date=date,
                    clip_count=clip_count,
                    patient_surname=(
                        (self._folder_study_history if origin == "folder" else self._download_history).patient_surname(
                            record.study_uid
                        )
                        if self._user_preferences.start_page_show_patient_data
                        else ""
                    ),
                )
            )
        if self._user_preferences.measurement_persistence_enabled:
            # Stored rows are matched to this run's studies through the same
            # opaque key the repository writes, so no patient/study UID has to
            # be exposed to the start page (N-01, S-09).
            from echo_personal_tool.application.saved_records import (
                MeasurementStorageError,
                study_key_for_uid,
            )

            seen_keys: set[str] = set()
            for study_uid in seen:
                try:
                    seen_keys.add(study_key_for_uid(study_uid))
                except MeasurementStorageError:
                    continue
            # UI-7: a stored record matched to a row of this run turns the row
            # into a draft («N изм. · черновик») — the count rides on the
            # reopenable row instead of vanishing with the skipped stored row.
            listing = self._request_saved_records()
            if listing is not None:
                counts_by_key = {
                    record.key: int(record.measurement_count or 0)
                    for record in getattr(listing, "records", ())
                    if record.readable
                }
                if counts_by_key:
                    from dataclasses import replace as _replace_summary

                    merged: list[RecentStudySummary] = []
                    for summary in summaries:
                        count = 0
                        if summary.study_uid:
                            try:
                                count = counts_by_key.get(study_key_for_uid(summary.study_uid), 0)
                            except MeasurementStorageError:
                                count = 0
                        merged.append(_replace_summary(summary, measurement_count=count) if count > 0 else summary)
                    summaries = merged
            summaries.extend(self._stored_record_summaries(seen_keys))
        start_page.set_recent_studies(summaries[:8])

    def _on_export_mp4_requested(self, instance: object) -> None:
        if not isinstance(instance, InstanceMetadata) or instance.path is None:
            return
        from echo_personal_tool.presentation.styled_dialogs import styled_save_file

        dest, _ = styled_save_file(
            self,
            tr("dialog.export_mp4.title"),
            "",
            "MP4 (*.mp4)",
        )
        if not dest:
            return
        # The mask resolves the profile from the exported file's own header, not
        # from whatever the viewer happens to show, so exporting a clip from the
        # gallery anonymizes it like the preview of that clip does.
        mask = frame_masker(instance.path, enabled=self._viewer.phi_masking_enabled)
        if instance.media_format == "mp4" and mask is None:
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
            mask=mask,
            parent=self,
        )
        worker.signals.progress.connect(self._on_mp4_export_progress, Qt.ConnectionType.QueuedConnection)

        worker.signals.finished.connect(self._on_mp4_export_finished, Qt.ConnectionType.QueuedConnection)

        worker.signals.failed.connect(self._on_mp4_export_failed, Qt.ConnectionType.QueuedConnection)

        QThreadPool.globalInstance().start(worker)

    def _on_mp4_export_progress(self, current: int, total: int) -> None:
        self._show_status(tr("status.mp4_export_progress", current=current, total=total))

    def _on_mp4_export_finished(self, path: str) -> None:
        self._show_status(tr("status.mp4_exported", path=path))

    def _on_mp4_export_failed(self, error_code: str) -> None:
        # The worker sends only a stable code; exception text can contain paths
        # and codec details that are not safe to surface in a dialog.
        del error_code
        message = tr("dialog.export_error.body", message=tr("status.mp4_export_failed"))
        QMessageBox.warning(self, tr("dialog.export_error.title"), message)
        self._show_status(tr("status.mp4_export_failed"))

    @_prof
    def _open_orthanc_dialog(self, *, preselect_study_uid: str | None = None) -> None:
        self._download_coordinator.open_dialog(preselect_study_uid=preselect_study_uid)

    def _send_to_server(self) -> None:
        self._download_coordinator.send_to_server()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._download_coordinator.has_active_download():
            self._download_coordinator.show_active_dialog()
            self._show_status(tr("orthanc.finish_download_before_exit"))
            event.ignore()
            return
        # If M-mode is active, close it instead of closing the app
        if self._mmode_active:
            self._toggle_mmode()
            event.ignore()
            self.setFocus()
            self.activateWindow()
            return
        self._download_coordinator.close_idle_dialog()
        persistence = getattr(self._controller, "measurement_persistence", None)
        if persistence is not None and not self._settle_unsaved_measurements():
            event.ignore()
            return
        if persistence is not None and not persistence.close():
            # The data decision is already settled above; only a repository
            # shutdown failure lands here. Do not delete the cache behind it.
            event.ignore()
            self._on_persistence_blocked()
            return
        if self._presenter.active:
            self._presenter.stop()
        if self.isFullScreen():
            self._remove_fullscreen_chrome_filter()
        if self._multiview_mode:
            # Closing from Multiview: hand the interface back to the initial
            # single-view layout first (the window may stay visible for up to
            # 2 s while pending workers drain below).
            self._on_multiview_button()
        self._multiview.shutdown()
        self._viewer.disconnect_display_controls()
        # Wait briefly for pending workers to finish so signals don't fire
        # on destroyed C++ objects.  2s cap avoids hanging on stuck tasks.
        pool = QThreadPool.globalInstance()
        if pool.activeThreadCount() > 0:
            pool.waitForDone(2000)
        if getattr(self._user_preferences, "orthanc_cache_clear_on_exit", True):
            self._download_coordinator.clear_all()
        app = QApplication.instance()
        if app is not None:
            try:
                app.focusChanged.disconnect(self._on_application_focus_changed)
            except RuntimeError:
                pass
        self._on_application_focus_changed(self._alt_focus_widget, None)
        super().closeEvent(event)

    @_prof
    def _on_studies_loaded(self, studies: object) -> None:
        try:
            with self._batch_study_surface_updates():
                self._apply_loaded_studies(studies)
        except Exception:
            self._abort_tab_load()
            raise

    def _apply_loaded_studies(self, studies: object) -> None:
        # A new study/patient invalidates every Multiview pane: never mix clips
        # of two studies in the same pair (spec 4.3).
        self._multiview.reset_session()
        study_list = list(studies)  # type: ignore[arg-type]
        # Tab-managed loads (acquire/switch/batch) own their selection via
        # _restore_target; only a direct load may autoload the first clip.
        tab_managed_load = self._tab_loading_id is not None
        loaded_tab_id = self._finish_tab_load(study_list)
        n_inst = sum(len(s.instances) for st in study_list for s in st.series)
        logger.info("[MW] _on_studies_loaded: %d studies, %d instances", len(study_list), n_inst)
        self._has_loaded_study = n_inst > 0
        self._set_start_page_visible(not self._has_loaded_study)
        self._refresh_tool_buttons()
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
        if self._multiview_mode:
            panes_attached = self._pane_left is not None and self._content_splitter.indexOf(self._pane_left) >= 0
            if not self._has_loaded_study or not panes_attached:
                # Empty loads reveal the welcome page; the next study restores
                # existing panes before main-viewer state starts syncing again.
                self._rebuild_layout()
        restored = self._after_tab_loaded(loaded_tab_id, study_list)
        if self._has_loaded_study and not restored and not tab_managed_load:
            self._autoload_first_instance(study_list)
        # UI-6 (§4.8): the automatic entry runs after the first clip is on
        # screen, so the strip and the card have file facts to show at once.
        if self._has_loaded_study:
            self._maybe_enter_focus(study_list)

    def _autoload_first_instance(self, study_list: list) -> None:
        """Show the new study at once: load its first clip without a click.

        Otherwise the viewer keeps the previous study's frame until the user
        picks a thumbnail by hand. Skipped when a tab switch just restored
        the tab's own instance (the caller reports it via ``_after_tab_loaded``).
        """
        for study in study_list:
            for series in study.series:
                for instance in series.instances:
                    self._gallery.select_instance(instance)
                    self._on_instance_selected(instance)
                    return

    def _set_start_page_visible(self, visible: bool) -> None:
        """Select the welcome page only while the main viewer surface owns a slot."""
        if self._viewer_stack.indexOf(self._start_page) < 0 or self._viewer_stack.indexOf(self._viewer) < 0:
            return
        target = self._start_page if visible else self._viewer
        self._viewer_stack.setCurrentWidget(target)

    def show_empty_start_page(self) -> None:
        """Show the empty-workspace page (also used by future empty tabs)."""
        self._has_loaded_study = False
        if self._multiview_mode:
            self._rebuild_layout()
        else:
            self._set_start_page_visible(True)

    # ── tabs (Э9, PR-B) ─────────────────────────────────────────────
    # N-08: the sequence lives in `presentation/tab_coordinator.py`; the methods
    # below are the window's own names kept as thin delegations (the rest of the
    # window, the shortcuts and the tests drive the tabs through them).

    @property
    def _tabs(self) -> TabSessionManager:
        return self._tab_coordinator.tabs

    @property
    def _tab_loading_id(self) -> str | None:
        return self._tab_coordinator.loading_tab_id

    @_tab_loading_id.setter
    def _tab_loading_id(self, value: str | None) -> None:
        self._tab_coordinator.loading_tab_id = value

    @property
    def _restore_target(self) -> tuple[str, str, int] | None:
        return self._tab_coordinator.restore_target

    @_restore_target.setter
    def _restore_target(self, value: tuple[str, str, int] | None) -> None:
        self._tab_coordinator.restore_target = value

    @property
    def _pending_tab_view(self) -> tuple[str, str, int, dict] | None:
        """View state of a tab being restored (Э9 §3/§5), owned by the coordinator."""
        return self._tab_coordinator.pending_view

    @_pending_tab_view.setter
    def _pending_tab_view(self, value: tuple[str, str, int, dict] | None) -> None:
        self._tab_coordinator.pending_view = value

    @property
    def _folder_study_history(self) -> DownloadHistory:
        """Folder studies of this run, for «Недавние исследования» (Э5 §7.3)."""
        return self._tab_coordinator.folder_history

    @property
    def _folder_study_roots(self) -> dict[str, str]:
        return self._tab_coordinator.folder_roots

    def _settle_unsaved_measurements(self) -> bool:
        """Office-style prompt when leaving a study with unsaved measurements.

        Returns True when the caller may proceed: the pending measurements
        were saved, or the user chose «Don't save».  Cancel (or a failed
        save) returns False and the current study stays put.  Replaces the
        old hard block that trapped the user when a write kept failing.
        """
        persistence = self._controller.measurement_persistence
        if persistence.flush():
            return True
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(tr("persistence.unsaved_title"))
        box.setText(tr("persistence.unsaved_text"))
        save_button = box.addButton(tr("button.save"), QMessageBox.ButtonRole.AcceptRole)
        discard_button = box.addButton(tr("button.discard"), QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(tr("button.cancel"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is save_button:
            if persistence.flush():
                return True
            self._show_status(tr("persistence.unsaved_save_failed"))
            return False
        if clicked is discard_button:
            return persistence.discard_unsaved()
        return False

    def _tab_flush_or_block(self) -> bool:
        """Measurements settle (save / don't save) before leaving the study.

        Window policy (persistence + prompt), so it stays here and is
        handed to the coordinator as a hook; tests replace it to simulate a
        refused flush.
        """
        return self._settle_unsaved_measurements()

    def _tabs_feature_enabled(self) -> bool:
        """Whether both the product profile and user preference allow tabs."""
        return self._profile_capabilities.tabs and self._user_preferences.tabs_enabled

    def _tab_busy(self) -> bool:
        return self._tab_coordinator.busy()

    def _acquire_tab_for_load(self, origin: str, root: str, cache_session_id: str) -> bool:
        return self._tab_coordinator.acquire_for_load(origin, root, cache_session_id)

    def _ensure_tab_capacity(self) -> bool:
        return self._tab_coordinator.ensure_capacity()

    def _make_room(self, count: int) -> bool:
        return self._tab_coordinator.make_room(count)

    def _open_server_batch(self, studies: list[StudyMetadata], session_id: str) -> bool:
        return self._tab_coordinator.open_batch(studies, session_id)

    def _park_active_tab(self) -> None:
        self._tab_coordinator.park_active()

    def _special_layout_active(self) -> bool:
        """True while Multiview or M-mode shows clips of the study being left."""
        return self._multiview_mode or self._mmode_active

    def _leave_special_layouts(self) -> None:
        """Multiview and M-mode show the previous study's clips; they end with the tab."""
        if self._multiview_mode:
            self._on_multiview_button()
        if self._mmode_active:
            self._toggle_mmode()

    @contextmanager
    def _batch_study_surface_updates(self):
        """Coalesce synchronous surface changes, never freeze the whole window.

        Restore the previous flags (also on exceptions/nested calls); updates
        are enabled again before control returns to the async event loop.
        """
        widgets = (self._viewer_stack, self._gallery)
        enabled = [widget.updatesEnabled() for widget in widgets]
        try:
            for widget, was_enabled in zip(widgets, enabled):
                if was_enabled:
                    widget.setUpdatesEnabled(False)
            yield
        finally:
            for widget, was_enabled in zip(widgets, enabled):
                if was_enabled:
                    widget.setUpdatesEnabled(True)

    def _load_tab_content(self, tab) -> None:  # noqa: ANN001 - TabSession
        self._tab_coordinator.load_content(tab)

    def _switch_to_tab(self, tab_id: str) -> bool:
        return self._tab_coordinator.switch_to(tab_id)

    def _tab_has_live_measurements(self, tab) -> bool:  # noqa: ANN001 - TabSession
        return self._tab_coordinator.has_live_measurements(tab)

    def _close_extra_tabs_for_single_mode(self) -> bool:
        return self._tab_coordinator.close_extra_tabs_for_single_mode()

    def _on_tab_selected(self, tab_id: str) -> None:
        self._tab_coordinator.on_selected(tab_id)

    def _on_tab_close_requested(self, tab_id: str) -> None:
        self._tab_coordinator.on_close_requested(tab_id)

    def _close_inactive_tab(self, tab_id: str) -> None:
        self._tab_coordinator.close_inactive(tab_id)

    def _open_empty_tab_shortcut(self) -> None:
        """Create and activate a blank tab when the tab workspace is enabled."""
        if not self._user_preferences.tabs_enabled:
            return
        if self._tab_busy() or not self._tab_flush_or_block() or not self._ensure_tab_capacity():
            return
        tab = self._tabs.open_tab(origin=TAB_ORIGIN_EMPTY, activate=False)
        if not self._switch_to_tab(tab.tab_id):
            # A persistence refusal must not leave a hidden empty tab behind.
            self._tabs.close_tab(tab.tab_id)

    def _on_tab_close_others_requested(self, keep_tab_id: str) -> None:
        """«Закрыть другие» (Э9 §4); the guards live in the tab coordinator."""
        self._tab_coordinator.close_others(keep_tab_id)

    def _on_tab_moved(self, from_index: int, to_index: int) -> None:
        """Drag-reorder the tab strip (Э9 §4)."""
        self._tab_coordinator.move_tab(from_index, to_index)

    def _cycle_tab(self, step: int) -> None:
        self._tab_coordinator.cycle(step)

    def _close_active_tab_shortcut(self) -> None:
        self._tab_coordinator.close_active()

    # ── downloads (Э9, PR-C): the cache, the history and the queue live in
    # `presentation/download_coordinator.py`; these are the window's own names ──

    @property
    def _orthanc_cache(self) -> OrthancCache:
        return self._download_coordinator.cache

    @property
    def _download_history(self) -> DownloadHistory:
        return self._download_coordinator.history

    def _queue_cache_purge(self, session_id: str) -> None:
        self._download_coordinator.queue_purge(session_id)

    def _process_pending_cache_purges(self) -> None:
        self._download_coordinator.process_pending_purges()

    def _tab_caption(self, tab) -> str:  # noqa: ANN001 - TabSession
        return self._tab_coordinator.caption(tab)

    def _refresh_tab_strip(self) -> None:
        self._tab_coordinator.refresh_strip()

    def _update_main_stack(self) -> None:
        self._tab_coordinator.update_main_stack()

    def _finish_tab_load(self, studies: list) -> str | None:
        return self._tab_coordinator.finish_load(studies)

    def _abort_tab_load(self) -> None:
        self._tab_coordinator.abort_load()

    def _on_studies_loaded_background(self, studies: object) -> None:
        """A superseded download lands in ITS tab and never into the view."""
        self._tab_coordinator.finish_background_load(list(studies))  # type: ignore[arg-type]

    def _on_scan_failed_background(self, _message: str) -> None:
        """Only the waiting tab's «loading» mark goes — the visible one is untouched."""
        self._tab_coordinator.fail_background_load()

    def _after_tab_loaded(self, loaded_tab_id: str | None, studies: list) -> bool:
        return self._tab_coordinator.after_loaded(loaded_tab_id, studies)

    def _restore_tab_view(
        self, studies: list, instance_uid: str, frame_index: int = 0, viewer_state: dict | None = None
    ) -> None:
        self._tab_coordinator.restore_view(studies, instance_uid, frame_index, viewer_state)

    def _multiview_study_uid(self, instance: InstanceMetadata) -> str | None:
        return self._comparison.study_uid(instance)

    def _set_multiview_start_hint(self, uid: str | None) -> None:
        self._comparison.set_start_hint(uid)

    def _route_multiview_start(self, selected: InstanceMetadata, ctrl: bool) -> bool:
        return self._comparison.route_start(selected, ctrl)

    def _multiview_load_into_pane(self, pane_id: PaneId, instance: InstanceMetadata) -> bool:
        """Load a clip into one pane (the guards live in the comparison coordinator)."""
        return self._comparison.load_into_pane(pane_id, instance)

    def _on_scan_failed(self, message: str) -> None:
        from echo_personal_tool.infrastructure.i18n import tr

        self._abort_tab_load()
        QMessageBox.warning(self, tr("error.scan_failed"), message)

    def _on_instance_selected(self, selected: object) -> None:
        if not isinstance(selected, InstanceMetadata):
            return
        if self._multiview_route_gallery_click(selected):
            return
        self._click_to_frame_started_at = perf_counter()
        previous = self._controller.state_manager.snapshot.instance
        if previous is not None:
            self._instance_overlay_cache[previous.sop_instance_uid] = self._viewer.results_overlay_text()
            if self._viewer.results_overlay_custom_position():
                x_ratio, y_ratio = self._viewer.results_overlay_position()
                self._instance_overlay_positions[previous.sop_instance_uid] = (x_ratio, y_ratio)
                if self._viewer.is_results_overlay_pinned():
                    study_uid = self._controller.resolve_study_uid(previous)
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

        # Reset M-mode when switching files
        if self._mmode_active:
            self._controller.set_playing(False)
            self._viewer.cancel_mmode_line()
            if self._mmode_widget is not None:
                self._mmode_widget.clear_buffer()
                self._mmode_widget.clear_calibration()
            # Restart M-mode line placement for new file
            self._viewer.start_mmode_line()

        # Hide properties tab when switching files
        self._tool_panel.hide_properties_tab()

        label = _loaded_file_label(selected)
        self._system_bar.set_study_context(label)
        # Hold the old frame AND its overlays until the new file's first frame
        # is decoded: clearing here, on click, popped graphics off the still
        # visible old anatomy (a flicker before the actual swap). The results
        # text is re-synced by _on_state_changed at swap time; the STE reset
        # below is armed and runs once in _on_frame_loaded, atomically with
        # the new pixels. Re-selecting the same instance keeps its results.
        self._pending_swap_uid = (
            selected.sop_instance_uid
            if previous is None or previous.sop_instance_uid != selected.sop_instance_uid
            else None
        )
        self._controller.load_instance(selected)
        # UI-0: clicking a thumbnail in the gallery must move focus to the main
        # window at once, so Space immediately plays/pauses and Up/Down arrows
        # switch files without an extra click on the viewer.
        self.setFocus()
        self.activateWindow()

    @_prof
    def _sync_phase_timeline(self, state: ViewerState, instance_uid: str | None) -> None:
        """(Re)start phase detection when the active cine instance changes.

        Phase state is initialised lazily here: ``MainWindow.__init__`` is
        grandfathered by the function-length ratchet and must not grow.
        """
        if not hasattr(self, "_phase_timeline_generation"):
            self._phase_timeline_uid = None
            self._phase_timeline_key: tuple[object, ...] | None = None
            self._phase_timeline_generation = 0
            self._phase_timelines: dict[tuple[object, ...], object] = {}
            self._phase_workers: dict[int, object] = {}
        if not hasattr(self, "_phase_markers_forced_uids"):
            self._phase_markers_forced_uids: set[str] = set()
        # ``total_frames`` is often 0 on the first state emission and filled in
        # after decoding, so the key includes it: the worker must start then.
        from echo_personal_tool.domain.services.cardiac_study import is_cardiac_cine

        instance = state.instance
        forced = bool(instance_uid and instance_uid in self._phase_markers_forced_uids)
        eligible = instance is not None and is_cardiac_cine(
            clip_mode=instance.clip_mode,
            body_part=instance.body_part,
            series_description=instance.series_description,
            study_description=instance.study_description,
            allow_unlabeled=forced,
        )
        key = (instance_uid, int(state.total_frames), eligible, forced, state.frame_time_ms)
        if key == self._phase_timeline_key:
            return
        self._phase_timeline_key = key
        self._phase_timeline_uid = instance_uid
        self._phase_timeline_generation += 1
        # Old workers are kept alive until their queued signals arrive; the
        # generation check discards their results, not their Python objects.
        self._viewer.set_phase_timeline(None)
        if not eligible or instance is None or instance.path is None or state.total_frames < 4:
            return
        cache_key = (instance_uid, state.total_frames, state.frame_time_ms)
        cached = self._phase_timelines.get(cache_key)
        if cached is not None:
            self._viewer.set_phase_timeline(cached)
            return

        from echo_personal_tool.application.workers.cine_phase_worker import CinePhaseWorker

        generation = self._phase_timeline_generation
        worker = CinePhaseWorker(
            source_path=Path(instance.path),
            media_format=instance.media_format,
            frame_time_ms=state.frame_time_ms,
            n_frames=state.total_frames,
            instance_uid=instance_uid or "",
            generation=generation,
        )
        worker.signals.finished.connect(self._on_phase_timeline_ready, Qt.ConnectionType.QueuedConnection)
        worker.signals.failed.connect(self._on_phase_timeline_failed, Qt.ConnectionType.QueuedConnection)
        # Keep the QRunnable alive until its queued signals arrive.
        self._phase_workers[generation] = worker
        QThreadPool.globalInstance().start(worker)

    def _on_phase_timeline_ready(self, timeline: object, instance_uid: str, generation: int) -> None:
        self._phase_workers.pop(generation, None)
        if generation != self._phase_timeline_generation or instance_uid != self._phase_timeline_uid:
            return
        cache_key = (instance_uid, getattr(timeline, "n_frames", 0), getattr(timeline, "frame_time_ms", None))
        self._phase_timelines[cache_key] = timeline
        self._viewer.set_phase_timeline(timeline)

    def _on_phase_timeline_failed(self, code: str, instance_uid: str, generation: int) -> None:
        self._phase_workers.pop(generation, None)
        if generation != self._phase_timeline_generation or instance_uid != self._phase_timeline_uid:
            return
        # Honest placeholder: the strip stays muted instead of painting a guess.
        logger.debug("cine phase detection unavailable: %s", code)

    def _on_frame_loaded(self, pixels: object) -> None:
        _ft0 = perf_counter() if _FREEZE_DIAG else 0
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
            # Atomic swap, single render: the old fast + deferred-full double
            # render moved viewRange twice per switch (measured 167-1974 px
            # jumps on cross-vendor cuts). The old frame stays until now.
            if self._pending_swap_uid is not None:
                # STE/strain state belongs to the previous clip (same reset
                # as before, just deferred from click time to swap time).
                if self._strain_window is not None:
                    self._strain_window.close()
                    self._strain_window = None
                self._manual_ed_frame = None
                self._manual_es_frame = None
                self._pending_swap_uid = None
            self._viewer.show_frame(image)
            self._viewer.reposition_overlays()
            if self._pending_report_frame is not None:
                # «Открыть кадры» of the report card: the clip just swapped,
                # so the saved frame can be applied to the new instance.
                pending_frame = self._pending_report_frame
                self._pending_report_frame = None
                self._jump_to_report_frame(pending_frame)
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
                    self._show_status(tr("status.calibration_click", cancel_key=shortcut_label("cancel_tool")))
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
                    self._show_status(tr("status.calibration_click", cancel_key=shortcut_label("cancel_tool")))
        self._presenter.forward_frame(image)
        if _FREEZE_DIAG:
            _diag_log.warning(
                "[frame_display] playing=%s scroll=%s render_ms=%.2f",
                is_playing,
                scroll_active,
                (perf_counter() - _ft0) * 1000,
            )

    def _on_slider_frame_selected(self, index: int) -> None:
        if (
            self._multiview_enabled()
            and self._multiview.session.playback_mode is not PlaybackMode.INDEPENDENT
            and self._multiview.session.is_playing
        ):
            # Manual positioning in a synchronised mode moves the shared playhead.
            self._multiview.seek_marker(PaneId.LEFT, index)
            return
        self._slider_navigating = True
        self._controller.state_manager.set_frame(index)

    @_prof
    def _on_scroll_settled(self) -> None:
        _t0 = perf_counter() if _FREEZE_DIAG else 0
        if self._controller.state_manager.snapshot.is_playing:
            return
        self._viewer.refresh_after_scroll()
        self._viewer.reposition_overlays()
        self._viewer.refresh_dicom_tags_overlay()
        self._restore_doppler_for_current_instance()
        self._restore_mmode_for_current_instance()
        self._sync_doppler_tool_availability()
        if _FREEZE_DIAG:
            _diag_log.warning(
                "[scroll_settled] total_ms=%.2f",
                (perf_counter() - _t0) * 1000,
            )

    @_prof
    def _on_frame_load_failed(self, message: str) -> None:
        from echo_personal_tool.infrastructure.i18n import tr

        self._click_to_frame_started_at = None
        QMessageBox.warning(self, tr("error.load_failed"), message)

    def _on_contour_landmark_rejected(self, _code: str) -> None:
        """Show a localized, static rejection; never forward geometry exceptions to UI."""
        self._show_status(tr("status.contour_landmark_rejected"))

    def _show_status(self, message: str) -> None:
        """Load/function status — bottom status bar only.

        The top system bar keeps just the study/file name; tool prompts go to
        the viewer's black hint strip via :meth:`_show_hint`.
        """
        if self.statusBar():
            self.statusBar().showMessage(message)

    def apply_status_bar_tokens(self) -> None:
        """Paint the permanent status-bar labels with the theme tokens (UI-0, PR-3).

        The «Только для исследований» warning takes ``state.warn`` and the
        version label ``text.3``; both used to be raw colour literals inside
        this window, so they ignored the theme. Called on creation and after
        every theme change, next to ``SystemBar.reload_icons()``. The window
        applies the stored preferences once before its status bar exists (the
        labels are built further down in ``__init__``), so the call is a no-op
        until then.
        """
        research_warning = getattr(self, "_research_warning", None)
        version_label = getattr(self, "_version_label", None)
        if research_warning is None or version_label is None:
            return
        from echo_personal_tool.presentation.dark_theme import get_theme_tokens

        tokens = get_theme_tokens()
        research_warning.setStyleSheet(f"color: {tokens['state.warn']}; font-weight: bold; padding-right: 10px;")
        version_label.setStyleSheet(f"color: {tokens['text.3']}; padding-right: 10px;")

    def _show_hint(self, message: str) -> None:
        """Tool prompt shown in the viewer's black hint strip."""
        self._viewer.set_hint(message)

    @_prof
    def _on_state_changed(self, state: object) -> None:
        if not isinstance(state, ViewerState):
            return
        self._tab_coordinator.apply_pending_view(state)
        self._presenter.forward_state(state)
        instance_uid = state.instance.sop_instance_uid if state.instance else None
        instance_changed = instance_uid != self._overlay_sync_instance_uid
        self._sync_phase_timeline(state, instance_uid)
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
            self._viewer._results_overlay_cleared = False
            self._restore_results_overlay_position(instance_uid)
            self._sync_results_overlay(state)
        elif content_changed:
            self._sync_results_overlay(state)
        if instance_changed or content_changed:
            # UI-4 PR-1: a measurement change rebuilds the sheet (debounced
            # 300 ms in the preview; a no-op while the tab shows the images).
            self._request_report_refresh()
        self._last_overlay_state = state
        if instance_changed:
            self._refresh_dicom_inspector()
        self._update_properties_panel(state)
        # UI-6: the strip and the floating plate mirror the same state the
        # built-in transport does; on a frame tick that is two labels and one
        # slider, not a rebuild.
        if self._focus_layout_active:
            self._sync_focus_view()
        snapshot = state.measurement_snapshot
        self._tool_panel.set_calculations(
            snapshot.calculations if snapshot is not None else None,
            has_study=state.instance is not None,
        )
        if self._multiview_enabled():
            self._comparison.sync_left_pane_from_controller()
            self._multiview.on_main_frame_changed(state.current_frame_index)

    def _update_properties_panel(self, state: ViewerState) -> None:
        """Update the properties panel with current instance info.

        The DICOM header read inside ``extract_properties_snapshot`` is cached
        per instance path so that rapid state changes (frame scrubbing, mode
        switches 2D/doppler/M) do not re-read the file from disk on every tick
        — that was freezing the UI on Windows 10.
        """
        from dataclasses import replace as _replace

        panel = self._tool_panel.properties_panel
        if state.instance is None or state.instance.path is None:
            panel.clear_all()
            self._viewer.set_dicom_doppler_mode(None)
            self._sync_tool_panel_context()
            return

        from echo_personal_tool.application.dicom_io import (
            extract_properties_snapshot,
            spectral_doppler_mode,
        )

        mmode = self._viewer.get_mmode_calibration_state()
        doppler = self._viewer.get_doppler_calibration_state()

        try:
            path = state.instance.path
            cached = self._properties_cache.get(path)
            if cached is None:
                snap = extract_properties_snapshot(
                    path,
                    depth_ok=state.effective_pixel_spacing is not None,
                    mmode_calibrated=mmode.is_complete() if mmode else False,
                    mmode_has_time_scale=mmode.has_time_scale() if mmode else False,
                    mmode_vertical_mm_per_pixel=mmode.vertical_mm_per_pixel if mmode else None,
                    mmode_horizontal_ms_per_pixel=mmode.horizontal_ms_per_pixel if mmode else None,
                    mmode_has_depth_from_dicom=mmode.has_depth_from_dicom() if mmode else False,
                    mmode_has_time_from_dicom=mmode.has_time_from_dicom() if mmode else False,
                    doppler_calibrated=doppler.is_complete() if doppler else False,
                    doppler_has_time_from_dicom=doppler.has_time_scale_from_dicom() if doppler else False,
                    doppler_has_velocity_from_dicom=doppler.has_velocity_scale_from_dicom() if doppler else False,
                    doppler_partial=doppler is not None and not doppler.is_complete(),
                )
                self._properties_cache[path] = snap
            else:
                snap = _replace(
                    cached,
                    depth_calibrated=state.effective_pixel_spacing is not None,
                    mmode_calibrated=mmode.is_complete() if mmode else False,
                    mmode_has_time_scale=mmode.has_time_scale() if mmode else False,
                    mmode_vertical_mm_per_pixel=mmode.vertical_mm_per_pixel if mmode else None,
                    mmode_horizontal_ms_per_pixel=mmode.horizontal_ms_per_pixel if mmode else None,
                    mmode_has_depth_from_dicom=mmode.has_depth_from_dicom() if mmode else False,
                    mmode_has_time_from_dicom=mmode.has_time_from_dicom() if mmode else False,
                    doppler_calibrated=doppler.is_complete() if doppler else False,
                    doppler_has_time_from_dicom=doppler.has_time_scale_from_dicom() if doppler else False,
                    doppler_has_velocity_from_dicom=doppler.has_velocity_scale_from_dicom() if doppler else False,
                    doppler_partial=doppler is not None and not doppler.is_complete(),
                )
            panel.update_from_snapshot(snap)
            # DICOM acquisition mode for Doppler display units (Э2); the
            # manual override in the Measures menu wins over it.
            self._viewer.set_dicom_doppler_mode(spectral_doppler_mode(snap))
        except (FileNotFoundError, PermissionError, OSError):
            panel.update_instance_info(
                modality=state.instance.modality,
                series_desc=state.instance.series_description,
                frame_time_ms=state.instance.frame_time_ms,
                number_of_frames=state.instance.number_of_frames,
                media_format=state.instance.media_format,
            )
            self._viewer.set_dicom_doppler_mode(None)

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
        self._sync_tool_panel_context()

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
            calibration = self._controller.get_doppler_calibration_for_instance(instance.sop_instance_uid)
            if calibration is not None and instance.number_of_frames > 1:
                calibration = None
        dto = self._controller.get_doppler_dto_for_instance_frame(
            instance.sop_instance_uid,
            frame_index,
        )
        with QSignalBlocker(self._viewer):
            self._viewer.restore_doppler_state(calibration, dto)
        self._doppler_frame_context = (instance.sop_instance_uid, frame_index)
        self._restore_vessel_for_current_frame()

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

    def _on_vessel_accept_requested(self, measurement: object) -> None:
        from echo_personal_tool.domain.models.vessel_measurement import VesselMeasurement

        if not isinstance(measurement, VesselMeasurement):
            return
        if self._controller.accept_vessel_measurement(measurement):
            self._show_status(tr("status.vessel_accepted"))

    def _restore_vessel_for_current_frame(self) -> None:
        from echo_personal_tool.application.study_measurement_session import (
            vessel_measurements_for_instance,
        )

        instance = self._controller.state_manager.snapshot.instance
        if instance is None:
            return
        frame = self._controller.state_manager.snapshot.current_frame_index
        study_uid = self._controller._current_study_uid
        session = self._controller._measurement_session.get(study_uid) if study_uid else None
        if session is None:
            return
        measurements = vessel_measurements_for_instance(
            session.vessel_measurements,
            instance.sop_instance_uid,
        )
        for m in measurements:
            if m.frame_index == frame:
                self._viewer._doppler.show_vessel_measurement(m)
                break

    def _restore_mmode_for_current_instance(self) -> None:
        instance = self._controller.state_manager.snapshot.instance
        if instance is None:
            return
        calibration = self._controller.get_mmode_calibration_for_instance(instance.sop_instance_uid)
        self._viewer.restore_mmode_state(calibration)

    def _ensure_mmode_ready_for_tapse(self) -> bool:
        if self._viewer.is_mmode_calibrated():
            return True
        instance = self._controller.state_manager.snapshot.instance
        if instance is not None:
            saved = self._controller.get_mmode_calibration_for_instance(instance.sop_instance_uid)
            if saved is not None:
                self._viewer.apply_mmode_calibration_state(saved)
                return True
        if self._viewer.try_apply_mmode_from_dicom_or_heuristic():
            state = self._viewer.get_mmode_calibration_state()
            if state is not None:
                self._controller.on_mmode_calibration_changed(state)
            return True
        if self._viewer.start_mmode_panel_calibration():
            self._show_status(tr("status.mmode_tapse_click"))
        else:
            self._show_status(tr("status.load_first_frame_mmode"))
        return False

    @_prof
    def _sync_results_overlay(self, state: ViewerState) -> None:
        time_calibrated = self._viewer.is_doppler_time_calibrated()
        instance = state.instance
        instance_uid = instance.sop_instance_uid if instance is not None else None

        overlay_snapshot = self._controller.compute_overlay_snapshot(state)
        fresh_html = format_results_overlay_html(
            overlay_snapshot,
            time_calibrated=time_calibrated,
            length_display_unit=self._user_preferences.length_display_unit,
        )
        logger.debug(
            "_sync_overlay: uid=%s html_len=%d linear=%d",
            instance_uid,
            len(fresh_html),
            len(overlay_snapshot.linear_measurements) if overlay_snapshot else 0,
        )

        if instance_uid is not None:
            if fresh_html.strip():
                self._instance_overlay_cache[instance_uid] = fresh_html
                # Cap cache size to prevent unbounded growth
                if len(self._instance_overlay_cache) > 500:
                    oldest = next(iter(self._instance_overlay_cache))
                    del self._instance_overlay_cache[oldest]
                display_text = fresh_html
            else:
                self._instance_overlay_cache.pop(instance_uid, None)
                display_text = ""
        else:
            display_text = fresh_html

        self._viewer.set_results_overlay(display_text)
        self._presenter.forward_results_overlay(display_text)

        snapshot = state.measurement_snapshot
        if snapshot is not None:
            indexed = snapshot.indexed
            self._tool_panel.set_patient_metrics(
                snapshot.height_cm,
                snapshot.weight_kg,
                indexed.bsa_basis if indexed is not None else None,
            )
        self._sync_doppler_tool_availability()

    def _apply_current_theme(self) -> None:
        apply_clinical_theme(
            font_size=self._user_preferences.ui_font_size,
            theme=self._user_preferences.theme_mode,
            accent_palette=self._user_preferences.accent_palette,
        )

    def _build_tool_panel(self) -> None:
        """Create the tools and mount their patient editors in the top bar."""
        self._tool_panel = ToolPanel(self._user_preferences)
        self._tool_panel.edit_requested.connect(self._show_tools_settings)
        self._tool_panel.layout_changed.connect(self._on_tool_layout_changed)
        self._mount_patient_metrics_toolbar()

    def _mount_patient_metrics_toolbar(self) -> None:
        """Place the patient editors in the patient line (one chrome row).

        The editors used to live in a strip of their own under the system bar:
        a third chrome row before the image, mostly empty, with its own hairline
        and its own gutter.  They now mount into the patient line itself, right
        after the study label — the composition of the approved mockup, where
        «Рост · Вес · ППТ» sit between the patient and the actions.
        """
        # The host lives in the patient line (:class:`SystemBar`); its layout is
        # the one the tool panel fills, so the editors keep their single
        # instance and the window shows one chrome row, not three.
        self._tool_panel.set_patient_metrics_host(self._system_bar.patient_metrics_host())

    def _report_patient_info(self, measurement_snapshot) -> PatientInfo:
        """Report header pre-filled from the DICOM header and the session.

        A video file has no patient block, and a corrupt header must not stop
        the report from opening, so every failure degrades to an empty header
        the physician can fill in by hand.
        """
        from echo_personal_tool.application.dicom_io import (
            read_patient_demographics,
        )

        instance = self._controller.state_manager.snapshot.instance
        demographics = None
        if instance is not None and instance.path is not None and instance.media_format == "dicom":
            try:
                demographics = read_patient_demographics(instance.path)
            except Exception as exc:  # noqa: BLE001 - an unreadable header is not fatal
                log_boundary_failure(logger, "patient.demographics", exc, code="io", level=logging.WARNING)

        indexed = measurement_snapshot.indexed if measurement_snapshot is not None else None
        height_cm = measurement_snapshot.height_cm if measurement_snapshot is not None else None
        weight_kg = measurement_snapshot.weight_kg if measurement_snapshot is not None else None
        height_source, weight_source = (
            self._controller.patient_metric_sources()
            if hasattr(self._controller, "patient_metric_sources")
            else ("unset", "unset")
        )
        if demographics is not None:
            # Explicit clearing wins too; a report must not resurrect DICOM values.
            # The session values win: they are the ones the user can correct in
            # the tool panel, the header is only the fallback.
            if height_cm is None and height_source == "unset" and demographics.height_m:
                height_cm = demographics.height_m * 100.0
            if weight_kg is None and weight_source == "unset":
                weight_kg = demographics.weight_kg
        patient = PatientInfo(
            name=demographics.name if demographics else "",
            patient_id=demographics.patient_id if demographics else "",
            birth_date=demographics.birth_date if demographics else "",
            age=demographics.age if demographics else "",
            sex=demographics.sex if demographics else "",
            study_date=demographics.study_date if demographics else "",
            height_cm=height_cm,
            weight_kg=weight_kg,
            bsa_m2=indexed.bsa_m2 if indexed is not None else None,
            institution=demographics.institution if demographics else "",
            equipment=demographics.equipment if demographics else "",
            physician=demographics.referring_physician if demographics else "",
        )

        tab = getattr(getattr(self, "_tabs", None), "active", None)
        overrides = getattr(tab, "report_patient_fields", {}) if tab is not None else {}
        return replace(patient, **overrides)

    def _default_report_name(self) -> str:
        """Suggested file name of an exported report (same as the dialog's)."""
        instance = self._controller.state_manager.snapshot.instance
        if instance is not None and instance.path is not None:
            return f"{instance.path.stem}_report.pdf"
        return "echo_report.pdf"

    def _show_results_dialog(self) -> None:
        """Compatibility entry point: one report editor, preview and export."""
        self._set_report_mode(True)

    # ── Report mode (UI-4 PR-1…PR-5, spec §4.6) ────────────────────
    # The mode is a surface of the main stack next to the images content;
    # which tab shows it lives in TabSession.report_mode (S-02), and the tab
    # coordinator asks _report_mode_page() whenever it picks the surface.
    # Toggling never touches the viewer, so the clip, the frame and an armed
    # protocol step survive the round trip (UA-09). The phrases column and the
    # conclusion draft arrived with PR-3 (TabSession.report_conclusion); PR-4
    # added the «откуда значение» card and its «Открыть кадры» jump, PR-5 the
    # export block (PDF, print) and the per-tab finished version (UQ-07). The
    # Patient header editing, conclusion and export now share this surface.

    def _report_phrase_store(self) -> ReportPhraseStore:
        """The local phrase library (UI-4 PR-3); one file per user profile."""
        return make_report_phrase_store()

    def _ensure_report_page(self) -> ReportModePage:
        """The one report page of the window, created on first entry."""
        if self._report_page is None:
            self._report_page = ReportModePage(
                self._current_report_document,
                projection_provider=self._controller.study_projection,
                phrase_store=self._report_phrase_store(),
                conclusion_autofill_provider=self._provide_report_conclusion,
                font_size=self._user_preferences.pdf_font_size,
                translate=tr,
                parent=self._main_stack,
            )
            self._report_page.patient_field_changed.connect(self._on_report_patient_field_changed)
            self._report_page.measure_requested.connect(self._on_report_measure_requested)
            self._report_page.conclusion_changed.connect(self._on_report_conclusion_changed)
            self._report_page.generated_conclusion_changed.connect(self._on_report_generated_conclusion_changed)
            self._report_page.open_frames_requested.connect(self._on_report_open_frames)
            self._report_page.export_requested.connect(self._export_report_pdf)
            self._report_page.print_requested.connect(self._print_report)
            self._report_page.finish_requested.connect(lambda: self._set_report_finished(True))
            self._report_page.draft_requested.connect(lambda: self._set_report_finished(False))
            self._report_page.sections.not_evaluated_changed.connect(self._on_report_not_evaluated_changed)
            self._report_page.set_clip_label_provider(self._report_clip_label)
            self._main_stack.addWidget(self._report_page)
        return self._report_page

    def _on_report_patient_field_changed(self, name: str, value: str) -> None:
        from echo_personal_tool.presentation.report_mode.patient import FIELDS

        tab = self._tabs.active
        if tab is None or tab.report_finished or name not in {key for key, _ in FIELDS} | {"sex"}:
            return
        tab.report_patient_fields[name] = value
        if self._report_page is not None:
            self._report_page.preview.request_refresh()

    def _on_report_conclusion_changed(self, text: str) -> None:
        """Keep the conclusion draft in the tab and refresh the sheet."""
        tab = self._tabs.active
        if tab is None:
            return
        if getattr(tab, "report_finished", False):
            # A finished version is read-only (UQ-07): a stray echo of the
            # editor must not become an edit of the fixed draft.
            self._report_page.set_conclusion(tab.report_conclusion)
            return
        tab.report_conclusion = str(text)
        # Only the sheet depends on the conclusion: the sections column and the
        # measurement projections are untouched by typing.
        page = self._report_page
        if page is not None and self._report_mode_active():
            page.preview.request_refresh()

    def _provide_report_conclusion(self) -> ConclusionAutofillResult:
        """Fresh study snapshot + patient context for the conclusion button."""
        from echo_personal_tool.application.report_conclusion import age_years_from_text

        tab = self._tabs.active
        page = self._ensure_report_page()
        if tab is None or getattr(tab, "report_finished", False):
            return ConclusionAutofillResult(
                text=page.conclusion,
                generated_block=getattr(tab, "report_generated_conclusion", "") if tab is not None else "",
                status_key="report.conclusion.status.readonly",
                changed=False,
                finding_count=0,
            )
        snapshot = self._controller.compute_study_snapshot()
        patient = self._report_patient_info(snapshot)
        return autofill_conclusion(
            snapshot,
            sex=patient.sex,
            age_years=age_years_from_text(patient.age),
            language=get_language(),
            existing=page.conclusion,
            previous_generated=getattr(tab, "report_generated_conclusion", ""),
        )

    def _on_report_generated_conclusion_changed(self, block: str) -> None:
        """Remember the exact managed block in the active tab only."""
        tab = self._tabs.active
        if tab is None or getattr(tab, "report_finished", False):
            return
        tab.report_generated_conclusion = str(block)

    def _on_report_measure_requested(self, protocol_id: str, step_index: int) -> None:
        """«измерить» in the report sections: back to images, arm the step (UA-12)."""
        if not protocol_id:
            return
        self._set_report_mode(False)
        session = self._ensure_protocol_session()
        if session.active_protocol_id != protocol_id:
            session.start(protocol_id)
        session.arm(step_index)

    def _current_report_document(self) -> ReportDocument:
        """The report of the active study, built like the dialog builds it.

        Same inputs as :meth:`_show_results_dialog` (study-wide snapshot,
        DICOM header, the patient's sex, the length unit), so the sheet of
        the mode and the dialog's document cannot drift apart (S-11).
        """
        snapshot = self._controller.compute_study_snapshot()
        patient = self._report_patient_info(snapshot)
        tab = self._tabs.active
        conclusion = getattr(tab, "report_conclusion", "") if tab is not None else ""
        if conclusion:
            # The draft lives in the tab (UI-4 PR-3); like the dialog's text it
            # is part of the document, so the sheet and the PDF share it (S-11).
            patient = replace(patient, conclusion=conclusion)
        document = build_report_document(
            snapshot,
            patient,
            sex=patient.sex,
            length_display_unit=self._user_preferences.length_display_unit,
        )
        page = self._report_page
        marks = page.marked_not_evaluated() if page is not None else frozenset()
        if not marks:
            return document
        # «не оценивалось» prints as an explicit mark instead of the
        # screen-only «измерить» link (spec §4.6, PR-5).
        return with_extra_values(
            document,
            not_evaluated_values(
                page.sections.sections,
                marks,
                value_text=tr("report.not_evaluated"),
            ),
        )

    def _report_mode_active(self) -> bool:
        tab = self._tabs.active
        return bool(getattr(tab, "report_mode", False)) if tab is not None else False

    def _report_mode_page(self) -> ReportModePage | None:
        """Coordinator hook: the report page when the active tab is in «Отчёт».

        Also the one place the patient-line switch is synced to the tab: the
        coordinator asks on every surface change (tab switch, load, abort),
        which is exactly when the mirror could go stale.
        """
        report = self._report_mode_active()
        system_bar = getattr(self, "_system_bar", None)
        if system_bar is not None:
            system_bar.set_report_mode(report)
        if not report:
            return None
        page = self._ensure_report_page()
        tab = self._tabs.active
        # The draft is per tab (S-02): restore it before the surface is shown.
        page.patient_editor.set_patient(self._report_patient_info(self._controller.compute_study_snapshot()))
        page.set_conclusion(getattr(tab, "report_conclusion", "") if tab is not None else "")
        self._sync_report_finished(tab)
        return page

    def _set_report_mode(self, enabled: bool) -> None:
        """Put the active tab into «Отчёт» (True) or back to «Изображения»."""
        tab = self._tabs.active
        if tab is None:
            return
        tab.report_mode = bool(enabled)
        if enabled:
            # The first paint of QPdfView is asynchronous (spike §4.3); the
            # render itself is synchronous and well inside the 500 ms budget.
            # The draft is set first: the provider reads it from the tab.
            page = self._ensure_report_page()
            page.patient_editor.set_patient(self._report_patient_info(self._controller.compute_study_snapshot()))
            page.set_conclusion(tab.report_conclusion)
            self._sync_report_finished(tab)
            if not tab.report_finished:
                page.refresh_now()
        self._update_main_stack()
        if not enabled and self._viewer_stack.currentWidget() is self._viewer:
            # Back on the images the keys belong to the viewer again, not to
            # the switch button the pointer just left.
            self._viewer.setFocus()

    def _toggle_report_mode_shortcut(self) -> None:
        """Ctrl+R: «Изображения» ↔ «Отчёт» of the active tab (spec §4.6)."""
        self._set_report_mode(not self._report_mode_active())

    def _request_report_refresh(self) -> None:
        """Schedule a sheet rebuild when the active tab shows the report."""
        if self._report_page is not None and self._report_mode_active():
            tab = self._tabs.active
            if tab is not None and getattr(tab, "report_finished", False):
                return
            self._report_page.request_refresh()

    # ── Report mode: «откуда значение», export, print, finish (PR-4/PR-5) ──

    def _report_clip_label(self, sop_instance_uid: str) -> str:
        """Name a clip the way the gallery does (hover card, PR-4)."""
        instance = self._report_instance(sop_instance_uid)
        if instance is None:
            return ""
        return _loaded_file_label(instance)

    def _report_instance(self, sop_instance_uid: str):
        """Find an instance of the open studies by its SOP Instance UID."""
        if not sop_instance_uid:
            return None
        for study in self._controller.studies:
            for series in study.series:
                for instance in series.instances:
                    if instance.sop_instance_uid == sop_instance_uid:
                        return instance
        return None

    def _on_report_open_frames(self, sop_instance_uid: str, frame_index: int) -> None:
        """«Открыть кадры»: back to «Изображения» on the source clip and frame."""
        self._set_report_mode(False)
        instance = self._report_instance(sop_instance_uid)
        if instance is None:
            self._show_status(tr("report.origin.clip_missing"))
            return
        current = self._controller.state_manager.snapshot.instance
        if current is None or current.sop_instance_uid != instance.sop_instance_uid:
            self._gallery.select_instance(instance)
            self._on_instance_selected(instance)
            self._pending_report_frame = int(frame_index)
        else:
            self._jump_to_report_frame(int(frame_index))
        self._viewer.setFocus()

    def _jump_to_report_frame(self, frame_index: int) -> None:
        """Move the cine to a recorded frame; an out-of-range index is ignored."""
        snapshot = self._controller.state_manager.snapshot
        total = int(getattr(snapshot, "total_frames", 0) or 0)
        if total < 1 or frame_index < 0 or frame_index >= total:
            return
        self._controller.set_playing(False)
        self._controller.state_manager.set_frame(frame_index)

    def _on_report_not_evaluated_changed(self) -> None:
        """A new «не оценивалось» mark changes the printed sheet (PR-5)."""
        page = self._report_page
        tab = self._tabs.active
        if page is None or tab is None or getattr(tab, "report_finished", False):
            return
        page.request_refresh()

    def _export_report_pdf(self) -> None:
        """«PDF…» of the export block: the bytes on screen, written atomically."""
        page = self._report_page
        if page is None:
            return
        document = page.document
        if document is None:
            page.set_status(tr("report.export_empty"))
            return
        from echo_personal_tool.presentation.styled_dialogs import styled_save_file

        default_name = self._default_report_name()
        path, _ = styled_save_file(
            self,
            tr("report.export_pdf_title"),
            str(Path(default_name)),
            tr("report.pdf_filter"),
        )
        if not path:
            return
        try:
            export_report_document_pdf(
                document,
                Path(path),
                font_size=self._user_preferences.pdf_font_size,
            )
        except ReportExportError as exc:
            log_boundary_failure(logger, "report.export", exc, code="io", level=logging.WARNING)
            page.set_status(tr("report.export_failed"))
            return
        page.set_status(tr("report.export_done", name=Path(path).name))

    def _print_report(self) -> None:
        """«Печать…» of the export block (UQ-06)."""
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter

        page = self._report_page
        if page is None or not page.pdf_bytes:
            if page is not None:
                page.set_status(tr("report.print_empty"))
            return
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        dialog = QPrintDialog(printer, self)
        dialog.setWindowTitle(tr("report.print_title"))
        if dialog.exec() != QPrintDialog.DialogCode.Accepted:
            return
        self._print_report_to(printer)

    def _print_report_to(self, printer) -> bool:
        """Print the sheet bytes on *printer*; the status line reports the outcome."""
        page = self._report_page
        if page is None:
            return False
        ok = print_report_pdf(page.pdf_bytes, printer)
        page.set_status(tr("report.print_done") if ok else tr("report.print_failed"))
        return ok

    def _set_report_finished(self, finished: bool) -> None:
        """«Завершить» / «Новый черновик» of the active tab (UQ-07).

        Finishing fixes *the bytes currently on the sheet* — that is the
        version the physician signed off, not a later recomputation.  Editing
        starts a new draft, and the fixed version is dropped then: storing
        versions is a separate decision together with QH.
        """
        tab = self._tabs.active
        page = self._ensure_report_page()
        if tab is None:
            return
        if finished:
            version = page.preview.version()
            if version is None:
                page.set_status(tr("report.finish_empty"))
                return
            tab.report_finished = True
            tab.report_frozen_sheet = version
            page.set_finished(True)
            page.set_status(tr("report.finish_done"))
            return
        tab.report_finished = False
        tab.report_frozen_sheet = None
        page.set_finished(False)
        page.set_status(tr("report.draft_done"))
        page.refresh_now()

    def _sync_report_finished(self, tab) -> None:
        """Show the tab's own finished version or its live draft (S-02)."""
        page = self._report_page
        if page is None or tab is None:
            return
        finished = bool(getattr(tab, "report_finished", False))
        frozen_sheet = getattr(tab, "report_frozen_sheet", None)
        if finished and frozen_sheet is not None:
            page.set_finished(True)
            page.preview.set_version(frozen_sheet)
            return
        page.set_finished(False)

    def _sync_doppler_tool_availability(self) -> None:
        self._tool_panel.set_doppler_tool_availability(
            time_ok=self._viewer.is_doppler_time_calibrated(),
            vessel_ok=self._viewer.is_vessel_available(),
        )

    # ── Measurement panel 2.0 (TP-2 PR-1, experimental) ────────────

    def _tool_panel_preferred_width(self) -> int:
        """Width of the panel in the content splitter (280 legacy, 320 v2)."""
        if getattr(self._tool_panel, "is_v2", False):
            return int(self._tool_panel.preferred_width)
        return _TOOL_PANEL_WIDTH

    def _apply_tool_panel_frame(self, preferences) -> None:
        """Splitter-sized inside the splitter, pinned outside it (TP-2 §4.2).

        The 2.0 panel is resizable only where the splitter can move its edge.
        In a table slot (Multiview, side presets, the pinned rail panel) the
        width is the saved one: the panel must not stretch to its tab size
        hint and steal the space of the viewer and the Multiview panes.
        """
        panel = self._tool_panel
        v2 = bool(getattr(preferences, "tool_panel_v2", False))
        target = _TOOL_PANEL_WIDTH if not v2 else int(panel.preferred_width)
        in_splitter = self._content_splitter.indexOf(panel) >= 0
        if v2:
            panel.set_splitter_resizable(in_splitter)
        else:
            panel.set_splitter_resizable(False)
            panel.setFixedWidth(_TOOL_PANEL_WIDTH)
        if in_splitter:
            sizes = self._content_splitter.sizes()
            total = sum(sizes) if sum(sizes) > target else 800 + target
            self._content_splitter.blockSignals(True)
            self._content_splitter.setSizes([max(1, total - target), target])
            self._content_splitter.blockSignals(False)
        else:
            panel.resize(target, panel.height())

    def _on_content_splitter_moved(self, _position: int, _index: int) -> None:
        panel = getattr(self, "_tool_panel", None)
        if panel is None or not getattr(panel, "is_v2", False):
            return
        if self._content_splitter.indexOf(panel) < 0:
            return
        self._panel_width_timer.start()

    def _save_tool_panel_width(self) -> None:
        """Persist the splitter width of the 2.0 panel (280–420 px)."""
        panel = getattr(self, "_tool_panel", None)
        if panel is None or not getattr(panel, "is_v2", False):
            return
        if self._content_splitter.indexOf(panel) < 0:
            return
        width = int(panel.width())
        if width <= 0 or self._user_preferences.panel_width == width:
            return
        self._user_preferences.panel_width = width
        save_user_preferences(self._user_preferences)

    def _on_tool_measurement_context_changed(self, context: str) -> None:
        self._viewer.set_vessel_measurement_mode(context == "vessels")

    def _sync_tool_panel_context(self) -> None:
        """Tell the 2.0 panel which viewer context it is in (§4.2)."""
        panel = getattr(self, "_tool_panel", None)
        if panel is None or not getattr(panel, "is_v2", False):
            return
        if self._mmode_active:
            panel.set_view_context("m", defer=True)
            return
        context = "doppler" if self._viewer.is_doppler_context() else "2d"
        mode = ""
        if context == "doppler":
            resolved = getattr(self._viewer, "resolved_doppler_mode", None)
            if callable(resolved):
                mode = resolved()
        panel.set_view_context(context, mode, defer=True)

    # ── Radial menu (TP-6, spec §4.4) ──────────────────────────────

    def _radial_context(self) -> str:
        """The explicit vessel override, otherwise the acquisition context."""
        if self._tool_panel.is_v2 and self._tool_panel.measure.context() == "vessels":
            return "vessels"
        if self._mmode_active:
            return "m"
        return "doppler" if self._viewer.is_doppler_context() else "2d"

    def _radial_sector_labels(self) -> tuple[tuple[str, str], ...]:
        """``(tool_id, caption)`` for the wheel, in profile/fallback order."""
        from echo_personal_tool.domain.measurement_catalog import CATALOG
        from echo_personal_tool.infrastructure.i18n import get_language

        language = get_language()
        labels: list[tuple[str, str]] = []
        for tool_id in self._tool_panel.radial_sectors(self._radial_context())[:7]:
            tool = CATALOG.get(tool_id)
            labels.append((tool_id, tool.label(language).short if tool else tool_id))
        return tuple(labels)

    def _on_radial_tool(self, tool_id: str) -> None:
        """A wheel sector starts the tool — the same path as a protocol step."""
        if not getattr(self._tool_panel, "is_v2", False):
            return
        self._tool_panel.activate_tool(tool_id)
        measure = getattr(self._tool_panel, "measure", None)
        if measure is not None and hasattr(measure, "highlight_tool"):
            measure.highlight_tool(tool_id)

    def _on_radial_more(self) -> None:
        """«Ещё…», a jerk to a free sector, or a quick click: the legacy menu."""
        self._viewer._show_save_context_menu(None)

    @_prof
    def _focus_panel_search(self) -> None:
        """``/``: the search field of the 2.0 panel (free in ``main-window``)."""
        if not getattr(self._tool_panel, "is_v2", False):
            return
        if self._tool_rail is not None and self._layout_document.rail:
            self._rail_panels_pinned = True
            self._attach_pinned_tool_panel()
            self._tool_panel.show()
        else:
            self._tool_panel.show_measures_tab()
            self._tool_panel.show()
        self._tool_panel.focus_search()

    def _ensure_doppler_ready(self, *, require_time: bool = False) -> bool:
        if self._viewer._current_frame is None:
            self._show_status(tr("status.load_first_frame_doppler"))
            return False
        if require_time:
            if self._viewer.is_doppler_time_calibrated():
                return True
            self._show_status(tr("status.doppler_no_time"))
            return False
        return True

    def _wire_ui(self) -> None:
        self._system_bar.open_folder_requested.connect(self._open_folder)
        self._system_bar.load_from_server_requested.connect(self._open_orthanc_dialog)
        self._system_bar.send_to_server_requested.connect(self._send_to_server)
        self._system_bar.reset_session_requested.connect(self._on_reset_measurements_requested)
        self._system_bar.calibration_requested.connect(self._on_calibration_requested)
        self._system_bar.doppler_calibration_requested.connect(self._on_doppler_calibration_requested)
        self._system_bar.heart_rate_requested.connect(self._on_heart_rate_requested)
        self._system_bar.references_requested.connect(self._show_references)
        self._system_bar.report_mode_changed.connect(self._set_report_mode)
        if self._system_bar._btn_presenter is not None:
            self._system_bar.presenter_toggle_requested.connect(self._presenter.toggle)
            self._install_presenter_menu()
        self._tool_panel.action_requested.connect(self._on_measure_action)
        self._tool_panel.measurement_context_changed.connect(self._on_tool_measurement_context_changed)
        self._tool_panel.doppler_mode_changed.connect(self._viewer.set_doppler_mode_override)
        # UI-5 PR-4: the S2 card of the rows (hover 400 ms / the registry key)
        # and the «Нормы» dots switch (UD-14/UQ-03 — the position is remembered).
        self._tool_panel.open_reference_requested.connect(self._open_reference_dialog)
        self._tool_panel.norms_toggled.connect(self._on_norms_toggled)
        self._tool_panel.set_reference_sex_provider(self._row_reference_sex)
        self._tool_panel.set_norms_visible(bool(getattr(self._user_preferences, "reference_norm_dots", False)))
        # UI-2 PR-3: the same chip tells the row and the rail which context to
        # dim against (D-03 TP); the window keeps no second copy of the mode.
        self._tool_panel.doppler_mode_changed.connect(self._on_tool_doppler_mode_changed)
        self._tool_panel.patient_metrics_changed.connect(self._controller.on_patient_metrics_changed)
        self._tool_panel.calculator_input_changed.connect(self._controller.set_calculator_input)
        self._tool_panel.results_requested.connect(self._show_results_dialog)
        self._tool_panel.magnetic_snap_changed.connect(self._on_magnetic_snap_changed)
        self._tool_panel.despeckle_changed.connect(self._on_despeckle_changed)
        self._tool_panel.auto_play_changed.connect(self._on_auto_play_changed)
        # TP-3 PR-3: the protocol card of the 2.0 panel drives one session per
        # tab; the legacy Measures tab simply has no card.
        if self._tool_panel.is_v2:
            self._tool_panel.protocol_selected.connect(self._on_protocol_selected)
            self._tool_panel.protocol_step_activated.connect(self._on_protocol_step_activated)
            self._tool_panel.protocol_stop_requested.connect(self._on_protocol_stop_requested)
            self._tool_panel.protocol_skip_requested.connect(self._on_protocol_skip_requested)
            self._tool_panel.protocol_auto_advance_toggled.connect(self._on_protocol_auto_advance_toggled)
            self._tool_panel.set_protocols(PROTOCOLS)
        self._controller.study_projection_changed.connect(self._on_study_projection_changed)
        self._controller.speckle_result_ready.connect(self._on_speckle_result_ready)
        self._apply_magnetic_snap_from_preferences()
        self._apply_despeckle_from_preferences()

    def _apply_magnetic_snap_from_preferences(self) -> None:
        enabled = self._user_preferences.magnetic_snap_enabled
        with QSignalBlocker(self._tool_panel.controls._magnetic_snap_check):
            self._tool_panel.controls._magnetic_snap_check.setChecked(enabled)
        self._viewer.set_magnetic_snap_enabled(enabled)

    def _apply_despeckle_from_preferences(self) -> None:
        enabled = self._user_preferences.despeckle_enabled
        with QSignalBlocker(self._tool_panel.controls._despeckle_check):
            self._tool_panel.controls._despeckle_check.setChecked(enabled)
        self._viewer.set_despeckle_enabled(enabled)

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
            # The tool row and the rail hand over the catalog payload as it is
            # written in the catalog — a plain string («caliper»), not the enum
            # member.  ``MeasurementAction`` *is* a string enum, so nothing
            # downstream ever noticed, but the ``isinstance`` gate above turned
            # every click of the first three buttons into a silent no-op while
            # the hotkeys (which call the handlers directly) kept working
            # (item 3 of the 2026-10-23 acceptance list).
            try:
                action = MeasurementAction(action)
            except ValueError:
                return
        if self._multiview_tool_blocked(f"measure:{action}"):
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
            MeasurementAction.MANUAL_SIMPSON: (lambda: self._on_manual_simpson_requested(view, phase)),
            MeasurementAction.MBS_SIMPSON: (lambda: self._on_mbs_simpson_requested(view, phase)),
            MeasurementAction.LV2D_ALL_DIASTOLE: self._on_lv2d_all_diastole,
            MeasurementAction.LV2D_ES: self._on_lv2d_es,
            MeasurementAction.LA_DIAMETER: self._on_la_diameter,
            MeasurementAction.LAV_4C: self._on_lav_4c,
            MeasurementAction.LAV_4C_AUTO: self._on_lav_4c_auto,
            MeasurementAction.LAV_4C_AI_PLUS: self._on_lav_4c_ai_plus,
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
            MeasurementAction.STRAIN_CURVES: self._on_strain_curves_requested,
            MeasurementAction.STE_VIEW_A4C: lambda: self._on_ste_view_selected("A4C"),
            MeasurementAction.STE_VIEW_A2C: lambda: self._on_ste_view_selected("A2C"),
            MeasurementAction.STE_VIEW_A3C: lambda: self._on_ste_view_selected("A3C"),
            MeasurementAction.MMODE: self._toggle_mmode,
            MeasurementAction.MMODE_CALIPER: self._on_mmode_caliper_requested,
            MeasurementAction.MMODE_TIME_HR: self._on_mmode_time_hr_from_menu,
            MeasurementAction.TEICHHOLZ_ED: self._on_teichholz_ed_from_menu,
            MeasurementAction.TEICHHOLZ_ES: self._on_teichholz_es_from_menu,
            MeasurementAction.AREA_COMPARE: self._on_area_compare_requested,
            MeasurementAction.HEART_RATE: self._on_heart_rate_requested,
        }
        if action == MeasurementAction.CALIPER:
            self._on_caliper_requested(extra or None)
            return
        if action == MeasurementAction.DIAMETER_COMPARE:
            self._on_diameter_compare_requested()
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
        if action == MeasurementAction.DOPPLER_TRACE_AUTO:
            self._on_doppler_trace_auto()
            return
        if action == MeasurementAction.DOPPLER_TRACE_AUTO_REGION:
            self._on_doppler_trace_auto_region(extra or "VTI")
            return
        if action == MeasurementAction.VESSEL_PSV_EDV:
            if self._viewer.start_vessel_psv():
                self._show_status(tr("status.vessel_psv"))
            return
        if action == MeasurementAction.VESSEL_AUTO_TRACE_UP:
            preset = self._tool_panel.measure.vessel_preset()
            if self._viewer.start_vessel_auto_trace(preset, direction="up"):
                self._show_status(tr("status.vessel_auto_trace"))
            return
        if action == MeasurementAction.VESSEL_AUTO_TRACE_DOWN:
            preset = self._tool_panel.measure.vessel_preset()
            if self._viewer.start_vessel_auto_trace(preset, direction="down"):
                self._show_status(tr("status.vessel_auto_trace"))
            return
        if action == MeasurementAction.VESSEL_AVERAGE:
            if self._viewer.average_vessel_cycles():
                self._show_status(tr("status.vessel_average"))
            return
        if action == MeasurementAction.VESSEL_CLEAR:
            self._viewer.clear_vessel_measurement()
            return
        if action == MeasurementAction.VESSEL_ACCEPT:
            self._viewer.accept_vessel_measurement()
            return
        if action == MeasurementAction.VESSEL_STENOSIS_DIAMETER:
            if self._viewer.start_vessel_stenosis_diameter():
                self._show_status(tr("status.vessel_stenosis_diameter"))
            return
        if action == MeasurementAction.VESSEL_STENOSIS_AREA:
            if self._viewer.start_vessel_stenosis_area():
                self._show_status(tr("status.vessel_stenosis_area"))
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
        self._show_status(tr("status.doppler_peak_tool", label=label or "E"))

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
        if label == HEART_RATE_INTERVAL_LABEL:
            self._show_status(tr("status.doppler_heart_rate_tool"))
        else:
            self._show_status(tr("status.doppler_interval_tool", label=label or "DT"))

    def _on_doppler_trace_tool(self, trace_label: str = "VTI") -> None:
        if not self._ensure_doppler_ready(require_time=True):
            return
        self._viewer.set_doppler_tool_mode("trace", trace_label=trace_label)
        self._show_status(tr("status.doppler_trace_tool", trace_label=trace_label))

    def _on_doppler_trace_auto(self) -> None:
        if not self._ensure_doppler_ready(require_time=True):
            return
        if self._viewer.start_vti_auto_trace():
            self._show_status(tr("status.vti_auto_trace"))
        else:
            self._show_status(tr("status.load_first_frame_doppler"))

    def _on_doppler_trace_auto_region(self, trace_label: str) -> None:
        if not self._ensure_doppler_ready(require_time=True):
            return
        self._viewer.set_doppler_tool_mode("autovti_region", trace_label=trace_label)
        self._show_status(tr("status.autovti_region_tool", trace_label=trace_label))

    def _on_rv_s_prime(self) -> None:
        if not self._ensure_doppler_ready():
            return
        self._viewer.set_doppler_tool_mode("peak", peak_label="s_prime_rv")
        self._show_status(tr("status.rv_s_prime_tool"))

    def _on_rv_fac(self) -> None:
        phase = "ES" if self._rv_fac_awaiting_es else "ED"
        if not self._start_chamber_contour(
            "RV",
            phase,
            "A4C",
            overlay=f"RV FAC {phase}: TV lateral → septal → free wall",
            status=(
                f"RV FAC {phase}: 1) TV lateral  2) TV septal  3) free wall · Enter — {tr('status.ready_done', line='confirm')}"  # noqa: E501
            ),
        ):
            self._show_status(f"Load a frame first or cancel the active tool ({shortcut_label('cancel_tool')})")

    def _wire_measurement_tools(self) -> None:
        """Backward-compatible alias for tests."""
        self._wire_ui()

    def _on_caliper_requested(self, label: str | None = None) -> None:
        if self._multiview_tool_blocked("caliper"):
            return
        if label:
            if self._viewer.start_linear_caliper_for(label):
                self._show_status(tr("status.linear_caliper_tool", label=label))
            else:
                self._show_status("Load a frame first")
            return
        if self._viewer.is_caliper_repeat_mode:
            # Scanner-like toggle: while the generic caliper is armed, the
            # button (like the L hotkey) switches it off. Every click pair
            # commits one measurement and immediately arms the next DistN.
            self._viewer.toggle_linear_caliper()
            self._show_status(tr("status.linear_caliper_off"))
            return
        if activated := self._viewer.activate_generic_dist_caliper():
            self._show_status(tr("status.linear_caliper_tool", label=activated))
        else:
            self._show_status("Load a frame first")

    def _on_mmode_caliper_requested(self) -> None:
        if self._viewer.start_mmode_vertical_caliper():
            self._show_status(tr("status.mmode_caliper_tool"))
        else:
            self._show_status("M-mode calibration required")

    def _on_mmode_time_hr_from_menu(self) -> None:
        """Start horizontal time/HR caliper in the current viewer window (no anatomical M-mode panel)."""
        self._viewer.try_apply_mmode_from_dicom_or_heuristic()

        if not self._viewer.is_mmode_calibrated():
            self._viewer.start_mmode_panel_calibration()
            self._show_status(tr("status.mmode_calibration_start"))
            return

        if self._viewer.start_linear_caliper_for("Time"):
            self._show_status(tr("status.mmode_time_ready"))
        else:
            self._show_status("M-mode calibration required")

    def _start_mmode_frame_sequence_or_calibrate(self, labels: tuple[str, ...], *, ed: bool) -> None:
        """Apply Teichholz labels to the current M-mode frame instead of launching anatomic M-mode."""
        self._viewer.try_apply_mmode_from_dicom_or_heuristic()
        if not self._viewer.is_mmode_calibrated():
            if self._viewer.start_mmode_panel_calibration():
                self._show_status(tr("status.mmode_calibration_start"))
            else:
                self._show_status(tr("status.load_frame"))
            return
        if not self._viewer.start_mmode_frame_caliper_sequence(labels):
            self._show_status(tr("status.load_frame"))
            return
        if ed:
            self._tool_panel.measure.clear_action_highlight()
            self._viewer.clear_frame_overlay()
            self._viewer.append_frame_overlay(tr("status.lv_diastole_overlay"))
            self._show_status(tr("status.lv_diastole_sequence"))
        else:
            self._show_status(tr("status.lv_systole_place"))

    def _on_teichholz_ed_from_menu(self) -> None:
        """Start IVSd-LVIDd-LVPWd calipers on the current M-mode frame (no anatomic M-mode panel)."""
        self._start_mmode_frame_sequence_or_calibrate(("IVSd", "LVEDD", "LVPWd"), ed=True)

    def _on_teichholz_es_from_menu(self) -> None:
        """Start LVIDs caliper on the current M-mode frame (no anatomic M-mode panel)."""
        self._start_mmode_frame_sequence_or_calibrate(("LVESD",), ed=False)

    def _on_diameter_compare_requested(self) -> None:
        if self._viewer.start_diameter_compare():
            self._show_status(tr("viewer.dcmp_click_start"))
        else:
            self._show_status("Load a frame first")

    def _on_area_compare_requested(self) -> None:
        self._viewer.start_area_compare()

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
        # TP-3: a reset is a new study for the protocol (S-02).
        if self._protocol_session is not None:
            self._protocol_session.on_study_changed()
        self._instance_overlay_cache.clear()
        self._viewer.cancel_active_tool()
        self._viewer.set_results_overlay("")
        self._viewer.clear_doppler_calibration_display(keep_time_scale=True)
        self._viewer.clear_doppler_measurements()
        self._viewer.clear_speckle_overlay()
        if self._strain_window is not None:
            self._strain_window.close()
            self._strain_window = None
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
        if self._multiview_tool_blocked("calibration"):
            return
        if self._viewer._current_frame is None:
            self._show_status("Load a frame first")
            return
        self._viewer.toggle_calibration_caliper()
        if self._viewer.is_calibration_active:
            self._show_status(tr("status.calibration_bmode_click", cancel_key=shortcut_label("cancel_tool")))
        else:
            self._show_status(tr("status.calibration_cancelled"))

    def _on_heart_rate_requested(self) -> None:
        if self._multiview_tool_blocked("heart_rate"):
            return
        snapshot = self._controller.state_manager.snapshot
        if snapshot.instance is None:
            self._show_status("Load a cine first")
            return
        from PySide6.QtCore import QThreadPool

        from echo_personal_tool.application.workers.heart_rate_worker import (
            HeartRateWorker,
        )

        # Collect contour areas for area-time method
        contour_areas: list[float] | None = None
        contour_frame_indices: list[int] | None = None
        contours = self._viewer.contours()
        if contours:
            from echo_personal_tool.domain.services.contour_geometry import (
                polygon_area_mm2,
            )

            pixel_spacing = snapshot.instance.pixel_spacing or (1.0, 1.0)
            areas: list[float] = []
            indices: list[int] = []
            for c in contours:
                if c.chamber == "LV" and len(c.points) >= 3:
                    area = polygon_area_mm2(c.points, pixel_spacing)
                    areas.append(area)
                    indices.append(c.frame_index)
            if len(areas) >= 4:
                contour_areas = areas
                contour_frame_indices = indices

        worker = HeartRateWorker(
            source_path=snapshot.instance.path,
            media_format=snapshot.instance.media_format,
            frame_time_ms=snapshot.instance.frame_time_ms,
            contour_areas=contour_areas,
            contour_frame_indices=contour_frame_indices,
        )
        worker.signals.finished.connect(self._on_heart_rate_result, Qt.ConnectionType.QueuedConnection)
        worker.signals.failed.connect(self._on_heart_rate_failed, Qt.ConnectionType.QueuedConnection)
        self._show_status("Estimating heart rate…")
        QThreadPool.globalInstance().start(worker)

    def _on_heart_rate_result(self, bpm: float, confidence: float, method: str) -> None:
        method_label = {"optical_flow": "Optical Flow", "area_time": "Area-Time", "combined": "Combined"}.get(
            method, method
        )
        msg = f"HR: {bpm:.0f} BPM ({method_label}, conf {confidence:.0%})"
        self._show_status(msg)
        # Calculator source for cardiac output when the clip has no DICOM HR (Э11).
        self._controller.record_heart_rate_estimate(bpm, method)
        overlay = self._viewer.results_overlay_text()
        hr_line = f"HR: {bpm:.0f} BPM"
        if overlay:
            self._viewer.set_results_overlay(f"{overlay}\n{hr_line}")
        else:
            self._viewer.set_results_overlay(hr_line)

    def _on_heart_rate_failed(self, error: str) -> None:
        self._show_status(f"HR estimation failed: {error}")

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
        # Respect the position chosen with the Стрейн toolbar buttons: the ED
        # contour of that view is used when present (the A4C preference here is
        # only a fallback for the historical default).
        ste_view = (self._ste_position or "A4C").upper()
        contour = (
            self._viewer.get_lv_contour(phase="ED", view=ste_view)
            or self._viewer.get_lv_contour(phase="ED", view="A4C")
            or self._viewer.get_lv_contour()
        )
        if contour is None:
            self._show_status(tr("status.speckle_no_contour"))
            return
        created_epi = self._viewer.ensure_lv_epicardial_contours(
            view=contour.view,
            thickness_mm=self._ste_wall_thickness_mm,
        )
        if created_epi:
            self._controller.on_contours_changed(self._viewer.contours())
            self._show_status("Epicardial contours created — edit nodes if needed, then press STE again")
            return

        phase_contours = {
            item.phase.upper(): item
            for item in self._viewer.contours()
            if item.chamber == "LV" and item.view.upper() == contour.view.upper() and item.frame_index is not None
        }
        ed_from_contour = self._manual_ed_frame is None and phase_contours.get("ED") is not None
        es_from_contour = self._manual_es_frame is None and phase_contours.get("ES") is not None
        if ed_from_contour:
            self._manual_ed_frame = phase_contours["ED"].frame_index
        if es_from_contour:
            self._manual_es_frame = phase_contours["ES"].frame_index
        ed_pinned = self._manual_ed_frame is not None
        es_pinned = self._manual_es_frame is not None
        if ed_from_contour and es_from_contour:
            ed_es_hint = "Manual — from EDV/ESV contours"
        elif ed_from_contour:
            ed_es_hint = "ED pinned from EDV contour; ES auto-detected"
        elif es_from_contour:
            ed_es_hint = "ES pinned from ESV contour; ED auto-detected"
        elif ed_pinned and es_pinned:
            ed_es_hint = "Manual frames (auto-detect disabled)"
        else:
            ed_es_hint = "Auto-detect: ECG → Simpson area → image"
        current_idx = self._get_current_frame_index() or 0
        cache = self._controller._frame_cache
        n_frames = cache._total_frames if cache else 0
        settings = SpeckleSettingsDialog(
            self,
            current_frame=current_idx,
            manual_ed=self._manual_ed_frame,
            manual_es=self._manual_es_frame,
            n_frames=n_frames,
            ed_es_hint=ed_es_hint,
            initial_view=contour.view,
        )
        from echo_personal_tool.presentation.ui_animations import exec_animated

        if exec_animated(settings) != QDialog.DialogCode.Accepted:
            self._show_status(tr("status.speckle_cancelled"))
            return
        config = settings.get_config()
        config_preset = settings.selected_preset_name()
        self._ste_wall_thickness_mm = float(config.wall_thickness_mm)
        self._ste_position = settings.selected_view()
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
            view=self._ste_position,
        )

    def _reset_strain_window(self) -> None:
        """Drop the strain window; it is built in the language it opened in."""
        window = self._strain_window
        if window is not None:
            self._strain_window = None
            window.close()

    def _ensure_strain_window(self) -> StrainWindow:
        if self._strain_window is None:
            # Top-level window (no parent) so it is raised above a maximized or
            # fullscreen main window instead of only becoming visible after the
            # main window is closed.
            self._strain_window = StrainWindow()
            self._strain_window.closed.connect(self._on_strain_window_closed)
        return self._strain_window

    def _on_strain_window_closed(self) -> None:
        self._strain_window = None
        # The smoothing slider is a child of the viewer; without this it stays
        # visible after the strain window closes (issue #1).
        try:
            self._viewer._ste_sensitivity.hide()
        except Exception as exc:  # noqa: BLE001
            log_boundary_failure(logger, "ui.cleanup", exc, code="cleanup", level=logging.DEBUG)

    def _on_speckle_result_ready(self, result: object) -> None:
        from echo_personal_tool.domain.models.speckle import StrainResult

        if not isinstance(result, StrainResult):
            return
        gls = result.gls
        ncc_pct = result.tracking_quality_mean * 100.0
        qc_pct = result.qc_score * 100.0
        drift = "ON" if result.drift_compensation_applied else "OFF"
        preset_name = self._format_speckle_preset_name(result.config_preset)

        # Quality gate info
        total = result.kernels_total_count
        accepted = result.kernels_accepted_count
        rejected = result.kernels_rejected_count
        if total > 0:
            accepted_pct = (accepted / total) * 100.0
            quality_info = f"Kernels: {accepted}/{total} ({accepted_pct:.0f}%)"
            if rejected > 0:
                quality_info += f" [{rejected} rejected]"
        else:
            quality_info = ""

        # Honest QC: NCC alone can read >90% while the deformation is
        # implausible; the combined QC score and physiology check are shown
        # alongside it so users are not misled (issue #3).
        qc_info = f"QC: {qc_pct:.0f}%"
        if not result.qc_physiology_ok and result.qc_physiology_reasons:
            qc_info += f" [⚠ {result.qc_physiology_reasons[0]}]"

        status_parts = [
            f"GLS: {gls:.1f}%",
            qc_info,
            f"NCC: {ncc_pct:.0f}%",
            quality_info,
            f"ED/ES: {result.ed_es_source}",
            f"Drift: {drift}",
            f"Preset: {preset_name}",
        ]
        self._show_status(" | ".join(filter(None, status_parts)))
        self._viewer.show_speckle_result(result)

        # The cine frames the worker actually tracked on travel with the
        # result, so the results window can always animate kernels over the
        # ultrasound even when the main viewer's cache dropped frames. Falls
        # back to the cache for older result objects.
        frames: np.ndarray | None = getattr(result, "cine_frames", None)
        if frames is None:
            try:
                frames = self._controller._frame_cache.require_full_cine()
            except Exception:  # noqa: BLE001
                frames = None
        # Keep the last result so the "Strain curves" button can reopen it
        self._strain_result_for_window = result
        self._strain_frames_for_window = frames
        window = self._ensure_strain_window()
        window.set_position(self._ste_position)
        # One accumulation of analysed views for the window and the protocol:
        # the controller owns it, the window adopts it (plan §5.3 п.6).
        window.set_study(self._controller.strain_study())
        # DICOM provenance so the strain window can save a gold-contour JSON
        # with the correct study UID and pixel spacing (§11.2 п.1).
        snapshot = self._controller.state_manager.snapshot
        spacing = snapshot.effective_pixel_spacing or (1.0, 1.0)
        study_uid = ""
        sop_uid = ""
        instance = getattr(snapshot, "instance", None)
        if instance is not None:
            study_uid = str(getattr(instance, "study_instance_uid", "") or "")
            sop_uid = str(getattr(instance, "sop_instance_uid", "") or "")
        window.show_result(
            result,
            frames=frames,
            study_uid=study_uid,
            sop_instance_uid=sop_uid,
            pixel_spacing_mm=(float(spacing[0]), float(spacing[1])),
        )

    def _on_ste_view_selected(self, view: str) -> None:
        """Record which apical view (A4C/A2C/A3C) the current clip represents.

        The choice is remembered on the main window and forwarded to the STE
        settings dialog (which the contours were drawn on), the results-window
        position label and the JSON export.
        """
        self._ste_position = view.upper()
        self._show_status(tr("status.strain_pos_selected", view=self._ste_position))

    def _on_strain_curves_requested(self) -> None:
        """Reopen the strain window on the curves page (issue #6)."""
        result = self._strain_result_for_window
        if result is None:
            self._show_status(tr("status.strain_curves_need_data"))
            return
        window = self._ensure_strain_window()
        window.set_position(self._ste_position)
        window.set_study(self._controller.strain_study())
        # Reuse metadata captured at the last run — show_result stores it on
        # the window, and the curves page reopens the same result.
        snapshot = self._controller.state_manager.snapshot
        spacing = snapshot.effective_pixel_spacing or (1.0, 1.0)
        instance = getattr(snapshot, "instance", None)
        window.show_result(
            result,
            frames=self._strain_frames_for_window,
            study_uid="" if instance is None else str(getattr(instance, "study_instance_uid", "") or ""),
            sop_instance_uid="" if instance is None else str(getattr(instance, "sop_instance_uid", "") or ""),
            pixel_spacing_mm=(float(spacing[0]), float(spacing[1])),
        )
        window.show_curves()

    @staticmethod
    def _format_speckle_preset_name(preset_name: str) -> str:
        mapping = {
            "standard": "Standard",
            "research": "Research",
            "debug": "Debug",
        }
        return mapping.get(preset_name, preset_name)

    def _on_doppler_calibration_requested(self) -> None:
        if self._multiview_tool_blocked("doppler_calibration"):
            return
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
            self._viewer.append_frame_overlay(f"Manual LV {view} {phase}: annulus septal → lateral → apex")
            self._show_status(f"Manual Simpson {view} {phase}: click annulus septal, lateral, apex")
        else:
            self._show_status(f"Load a frame first or cancel the active tool ({shortcut_label('cancel_tool')})")

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
            status += tr("status.lv_no_pixel_spacing", calibration_key=shortcut_label("calibration_toggle"))
        self._show_status(status)
        self._viewer.append_frame_overlay(status)

    def _on_es_button_pressed(self, view: str, phase: str) -> None:
        del view, phase

    def _on_lv2d_all_diastole(self) -> None:
        if self._multiview_tool_blocked("lv2d"):
            return
        self._tool_panel.measure.clear_action_highlight()
        if self._viewer.start_linear_caliper_sequence(("IVSd", "LVEDD", "LVPWd")):
            self._viewer.clear_frame_overlay()
            self._viewer.append_frame_overlay(tr("status.lv_diastole_overlay"))
            self._show_status(tr("status.lv_diastole_sequence"))
        else:
            self._show_status(tr("status.load_frame"))

    def _on_linear_caliper_sequence_completed(self) -> None:
        self._tool_panel.measure.highlight_action(MeasurementAction.LV2D_ES)
        # The diastole sequence is the first half of one measurement pair: the
        # operator scrolls the cine to the systolic frame and that click is
        # already LVIDs (ТЗ 2026-10-23, п. 2) — the panel shortcut is worth
        # using only when the second half continues by itself.  The chain is
        # resolved on the click, because scrolling cancels a running tool.
        if not self._viewer.is_protocol_active():
            self._viewer.arm_next_caliper("LVESD")
        self._show_status(tr("status.lv_diastole_done"))

    def _on_lv2d_es(self) -> None:
        if self._multiview_tool_blocked("lv2d_es"):
            return
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
        force_landmarks: bool = False,
        overlay: str,
        status: str,
    ) -> bool:
        if model:
            started = self._viewer.start_model_contour(chamber=chamber, phase=phase, view=view)
        else:
            started = self._viewer.start_contour(
                chamber=chamber,
                phase=phase,
                view=view,
                force_landmarks=force_landmarks,
            )
        if not started:
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
            self._show_status(f"Load a frame first or cancel the active tool ({shortcut_label('cancel_tool')})")

    def _on_lav_4c_auto(self) -> None:
        """Trigger LA auto-segmentation on current A4C ES frame."""
        self._viewer.clear_frame_overlay()
        self._viewer.append_frame_overlay(tr("status.lav4c_auto_overlay"))
        self._controller.request_la_auto_segment()

    def _on_lav_4c_ai_plus(self) -> None:
        """Start AI-assisted manual LA contour: 3 clicks → AI refinement."""
        self._start_chamber_contour(
            "LA",
            "ES",
            "A4C",
            force_landmarks=True,
            overlay=tr("status.lav4c_ai_plus_overlay"),
            status=tr("status.lav4c_ai_plus_status"),
        )

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
                self._show_status(f"Load a frame first or cancel the active tool ({shortcut_label('cancel_tool')})")
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
            self._show_status(f"Load a frame first or cancel the active tool ({shortcut_label('cancel_tool')})")

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
            self._show_status(f"Load a frame first or cancel the active tool ({shortcut_label('cancel_tool')})")

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
            self._show_status(f"Load a frame first or cancel the active tool ({shortcut_label('cancel_tool')})")

    def _on_contour_completed(self, contour: object) -> None:
        if not isinstance(contour, Contour):
            return
        chamber = contour.chamber.upper()
        if chamber not in {"LV", "LA", "RA", "RV", "AREA", "VOL"}:
            return
        extra_lines: tuple[str, ...] = ()
        if chamber in {"AREA", "VOL"}:
            if self._viewer._comparison_state.kind == "area":
                self._viewer._handle_area_compare_contour(contour)
                self._sync_results_overlay(self._controller.state_manager.snapshot)
                return
            if self._viewer._comparison_state.kind == "stenosis_area":
                self._viewer._handle_stenosis_area_contour(contour)
                self._sync_results_overlay(self._controller.state_manager.snapshot)
                return
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
            es_action = MeasurementAction.MBS_SIMPSON if mode == "mbs" else MeasurementAction.MANUAL_SIMPSON
            self._tool_panel.measure.highlight_action(es_action, view=view, phase="ES")
            view_label = "4C" if view == "A4C" else "2C"
            es_name = "ESV Auto" if mode == "mbs" else "LVEF Simpson ESV"
            extra_lines = (tr("status.press_es", es_name=es_name, view_label=view_label),)
            status = tr("status.press_es", es_name=es_name, view_label=view_label)
            # Same chain for the volumes: after the ED contour the next click on
            # the systolic frame starts the ES contour, so «КДО · 4-кам.» and
            # «КСО · 4-кам.» live next to each other in Quick/Favorites (ТЗ п. 2).
            if not self._viewer.is_protocol_active():
                self._viewer.arm_next_contour(
                    chamber="LV",
                    view=view,
                    phase="ES",
                    model=mode == "mbs",
                )
                status = tr(
                    "status.next_click_es",
                    es_name=es_name,
                    view_label=view_label,
                )
                extra_lines = (status,)
            if self._controller.state_manager.snapshot.effective_pixel_spacing is None:
                status += tr("status.lv_no_pixel_spacing", calibration_key=shortcut_label("calibration_toggle"))
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
                finish_key=shortcut_label("finish_tool"),
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
                finish_key=shortcut_label("finish_tool"),
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
                overlay_snap = self._controller.compute_overlay_snapshot(
                    self._controller.state_manager.snapshot,
                )
                if overlay_snap is not None and overlay_snap.rv_fac_percent is not None:
                    extra_lines = (
                        *extra_lines,
                        f"FAC: {overlay_snap.rv_fac_percent:.1f} %",
                    )

        self._viewer._refresh_frame_overlays(extra_lines=extra_lines)
        self._sync_results_overlay(self._controller.state_manager.snapshot)

    def _on_rv_basal(self) -> None:
        if self._viewer.start_linear_caliper_for("RV basal"):
            self._show_hint("RV: place basal diameter caliper")
        else:
            self._show_status("Load a frame first")

    def _on_rv_tapse(self) -> None:
        if not self._ensure_mmode_ready_for_tapse():
            return
        if self._viewer.start_linear_caliper_for("TAPSE"):
            self._show_hint(tr("status.rv_tapse_tool"))
        else:
            self._show_status("Load a frame first")

    def _on_application_focus_changed(self, _old: QWidget | None, focused: QWidget | None) -> None:
        """Filter only the current focus widget; avoid an app-wide event-filter cost."""
        previous = self._alt_focus_widget
        if previous is not None:
            try:
                previous.removeEventFilter(self)
            except RuntimeError:
                # The focus widget can be deleted before the next focus change.
                pass
        self._alt_focus_widget = None
        if focused is not None and (focused is self or self.isAncestorOf(focused)):
            focused.installEventFilter(self)
            self._alt_focus_widget = focused
        else:
            self._set_alt_key_hints(False)

    def _set_alt_key_hints(self, visible: bool) -> None:
        """Show/hide tool key badges while Alt (Option on macOS) is held."""
        for widget in (self._tool_row, self._tool_rail):
            if widget is not None:
                widget.set_key_hints_visible(visible)

    def eventFilter(self, watched: object, event: QEvent) -> bool:  # type: ignore[override]
        if event.type() in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease) and isinstance(event, QKeyEvent):
            if event.key() == Qt.Key.Key_Alt and self.isActiveWindow():
                self._set_alt_key_hints(event.type() == QEvent.Type.KeyPress)
        if event.type() == QEvent.Type.MouseButtonPress:
            if watched in (self._viewer, self._viewer._graphics, self._viewer._view):
                self._active_viewer = self._viewer
            elif self._viewer2 is not None and watched in (
                self._viewer2,
                self._viewer2._graphics,
                self._viewer2._view,
            ):
                self._active_viewer = self._viewer2
        # Fullscreen kiosk: reveal the system bar when the pointer touches
        # the top edge of the window; auto-hide again once it moves away.
        # Installed on the viewer viewport and chrome bars only while F11-kiosk is active.
        if self.isFullScreen() and event.type() == QEvent.Type.MouseMove:
            self._fullscreen_handle_hover(event)
        if event.type() == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
            if watched in (self._viewer, self._viewer._graphics, self._viewer._view):
                if self._handle_key_press(event):
                    return True
            if self._viewer2 is not None and watched in (
                self._viewer2,
                self._viewer2._graphics,
                self._viewer2._view,
            ):
                if self._handle_key_press(event):
                    return True
        return super().eventFilter(watched, event)

    @_prof
    def event(self, event) -> bool:  # type: ignore[override]
        if event.type() == QEvent.Type.HoverMove:
            try:
                self._update_resize_cursor(event.position().toPoint())
            except AttributeError:
                pass
        elif event.type() == QEvent.Type.HoverLeave and self._resize_cursor_active:
            self.unsetCursor()
            self._resize_cursor_active = False
        if event.type() == QEvent.Type.KeyPress and event_matches_shortcut(event, "cycle_caliper_label"):
            v = self._active_viewer or self._viewer
            v.cycle_caliper_label()
            event.accept()
            return True
        return super().event(event)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if (
            event.button() == Qt.MouseButton.LeftButton
            and not self.is_native_window_frame()
            and not self.isFullScreen()
        ):
            local_pos = event.position().toPoint()
            zone = self.chrome_hit_test(local_pos)
            if zone in RESIZE_ZONES:
                start_system_resize(self, zone_to_qt_edges(zone))
                event.accept()
                return
            if zone == Zone.CAPTION:
                global_pos = event.globalPosition().toPoint()
                start_system_move(self, global_pos=global_pos, drag_offset=global_pos - self.pos())
                event.accept()
                return
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if self._handle_key_press(event):
            return
        super().keyPressEvent(event)

    #: Registry IDs which Multiview stage 1 refuses instead of silently
    #: drawing on the hidden main viewer (spec 10.2).
    _MULTIVIEW_BLOCKED_SHORTCUTS = (
        "caliper",
        "manual_contour",
        "model_contour",
        "calibration_toggle",
        "calibration_clear",
        "doppler_interval",
        "vti_trace",
        "refine_contour",
        "auto_segment",
        "ghost_toggle",
        "ghost_neighbor",
        "ghost_previous",
        "ghost_next",
        "delete_selection",
    )

    def _handle_key_press(self, event: QKeyEvent) -> bool:
        v = self._active_viewer or self._viewer
        if v.is_label_picker_visible() and v.handle_label_picker_key(event):
            return True
        if self._multiview_enabled():
            active_shortcut_ids = {shortcut.id for shortcut in shortcuts_for_profile(active_profile_name())}
            if any(
                shortcut_id in active_shortcut_ids and event_matches_shortcut(event, shortcut_id)
                for shortcut_id in self._MULTIVIEW_BLOCKED_SHORTCUTS
            ):
                self._multiview_tool_blocked("hotkey")
                event.accept()
                return True
        elif (
            self._tool_panel.is_v2
            and not event.isAutoRepeat()
            and (favorite_index := favorite_shortcut_index(event)) is not None
            and self._tool_panel.activate_favorite(favorite_index)
        ):
            # The favourites' visible 1–9 badges must work while the user is
            # focused on the image, not only after tabbing into the panel.
            event.accept()
            return True
        if event_matches_shortcut(event, "panel_search") and not event.isAutoRepeat():
            if getattr(self._tool_panel, "is_v2", False):
                self._focus_panel_search()
                event.accept()
                return True
        if event_matches_shortcut(event, "play_pause", exact_modifiers=False):
            if self._controller.state_manager.snapshot.decode_in_progress:
                event.accept()
                return True
            if self._multiview_enabled():
                # Space drives shared playback in sync modes and the active
                # pane's own playback in independent mode (spec §5.3).
                self._multiview.toggle_play(self._multiview.session.active_pane)
            else:
                self._controller.toggle_playback()
            event.accept()
            return True
        if event_matches_shortcut(event, "caliper"):
            v.toggle_linear_caliper()
            self._sync_tool_button_active()
            event.accept()
            return True
        if event_matches_shortcut(event, "calibration_toggle"):
            # One implementation for the key and the button (D-09 TP).
            self._toggle_calibration_tool()
            event.accept()
            return True
        if event_matches_shortcut(event, "calibration_clear"):
            self._controller.clear_manual_calibration()
            event.accept()
            return True
        if event_matches_shortcut(event, "cycle_caliper_label"):
            v.cycle_caliper_label()
            event.accept()
            return True
        if event_matches_shortcut(event, "manual_contour"):
            if v.start_contour():
                self._show_hint("Manual contour: click MA septal, lateral, then arc")
            else:
                self._show_status("Load a frame first (or finish the active contour)")
            self._sync_tool_button_active()
            event.accept()
            return True
        if event_matches_shortcut(event, "model_contour"):
            if v.get_doppler_tool_mode() != "none":
                v.set_doppler_tool_mode("peak")
                self._show_hint(f"Doppler peak ({shortcut_label('model_contour')})")
            elif v.start_model_contour():
                self._show_hint("MBS-lite: click MA septal, lateral, then apex")
            else:
                self._show_status("Load a frame first (or finish the active contour)")
            self._sync_tool_button_active()
            event.accept()
            return True
        if event_matches_shortcut(event, "doppler_interval"):
            self._start_doppler_interval_tool()
            event.accept()
            return True
        if event_matches_shortcut(event, "vti_trace"):
            if self._ensure_doppler_ready(require_time=True):
                self._on_doppler_trace_tool("VTI")
            self._sync_tool_button_active()
            event.accept()
            return True
        if event_matches_shortcut(event, "refine_contour"):
            self._refine_active_contour()
            event.accept()
            return True
        if active_profile_name() == "full" and event_matches_shortcut(event, "auto_segment"):
            self._request_auto_segment_shortcut()
            event.accept()
            return True
        if event_matches_shortcut(event, "finish_tool", exact_modifiers=False):
            trace_active = v.get_doppler_tool_mode() == "trace"
            if trace_active and v.finish_doppler_trace():
                self._sync_tool_button_active()
                event.accept()
                return True
            if v.finish_contour():
                self._sync_tool_button_active()
                event.accept()
                return True
        if (
            event_matches_shortcut(event, "delete_selection", exact_modifiers=False)
            and event.key() == Qt.Key.Key_Backspace
            and v.rollback_freehand_segment()
        ):
            event.accept()
            return True
        if event_matches_shortcut(event, "delete_selection", exact_modifiers=False):
            if v._delete_selected_caliper():
                self._show_status(tr("status.caliper_deleted"))
                event.accept()
                return True
            if v.delete_contour_for_current_phase():
                self._controller.on_contours_changed(v.contours())
                self._show_status(tr("status.contour_deleted"))
            event.accept()
            return True
        if event_matches_shortcut(event, "cancel_tool", exact_modifiers=False):
            self._cancel_active_tool()
            self._sync_tool_button_active()
            event.accept()
            return True
        # Ghost overlay keys (temporal fusion).
        if event_matches_shortcut(event, "ghost_toggle"):
            mode = v.toggle_ghost_mode()
            self._show_hint(f"Ghost: {mode}")
            event.accept()
            return True
        if event_matches_shortcut(event, "ghost_neighbor"):
            v.set_ghost_mode("neighbor")
            self._show_hint("Ghost: neighbor")
            event.accept()
            return True
        if event_matches_shortcut(event, "ghost_previous", exact_modifiers=False):
            v.cycle_neighbor_ghost(-1)
            self._show_hint(f"Ghost: neighbor {v.ghost_mode}")
            event.accept()
            return True
        if event_matches_shortcut(event, "ghost_next", exact_modifiers=False):
            v.cycle_neighbor_ghost(1)
            self._show_hint(f"Ghost: neighbor {v.ghost_mode}")
            event.accept()
            return True
        return False
