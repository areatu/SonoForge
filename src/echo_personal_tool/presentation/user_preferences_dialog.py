"""Dialog for interface and viewer preferences."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.infrastructure.orthanc_cache import OrthancSessionCache
from echo_personal_tool.infrastructure.server_settings import save_server_settings
from echo_personal_tool.infrastructure.ui_scale import (
    UI_SCALE_AUTO,
    UI_SCALE_CHOICES,
    normalize_ui_scale,
)
from echo_personal_tool.infrastructure.user_preferences import (
    MAX_LINE_WIDTH,
    MAX_MAGNETIC_RADIUS,
    MAX_MAGNETIC_RELEASE,
    MAX_MAGNETIC_WEIGHT,
    MAX_MAGNIFIER_RADIUS_PX,
    MAX_MAGNIFIER_ZOOM,
    MAX_OVERLAY_FONT_SIZE,
    MAX_OVERLAY_OPACITY,
    MAX_PDF_FONT_SIZE,
    MAX_PLAYBACK_SPEED,
    MAX_UI_FONT_SIZE,
    MIN_LINE_WIDTH,
    MIN_MAGNETIC_RADIUS,
    MIN_MAGNETIC_RELEASE,
    MIN_MAGNETIC_WEIGHT,
    MIN_MAGNIFIER_RADIUS_PX,
    MIN_MAGNIFIER_ZOOM,
    MIN_OVERLAY_FONT_SIZE,
    MIN_OVERLAY_OPACITY,
    MIN_PDF_FONT_SIZE,
    MIN_PLAYBACK_SPEED,
    MIN_UI_FONT_SIZE,
    UserPreferences,
    default_user_preferences,
    load_user_preferences,
    save_user_preferences,
)
from echo_personal_tool.presentation.server_settings_dialog import ServerSettingsForm
from echo_personal_tool.presentation.styled_dialogs import localize_dialog_button_box, theme_button_box_icons
from echo_personal_tool.presentation.tool_panel_settings import ToolPanelSettingsWidget
from echo_personal_tool.presentation.ui_metrics import icon_button_size, title_bar_height


def show_user_preferences_dialog(
    parent: QWidget | None = None,
    *,
    on_apply: Callable[[UserPreferences], None] | None = None,
    orthanc_cache: OrthancSessionCache | None = None,
    protected_cache_sessions: Callable[[], set[str]] | None = None,
    measurement_storage_action: Callable[[], None] | None = None,
) -> bool:
    from echo_personal_tool.presentation.ui_animations import exec_animated

    dialog = UserPreferencesDialog(
        parent,
        on_apply=on_apply,
        orthanc_cache=orthanc_cache,
        protected_cache_sessions=protected_cache_sessions,
        measurement_storage_action=measurement_storage_action,
    )
    return exec_animated(dialog) == QDialog.DialogCode.Accepted


def _scrollable_tab(form: QFormLayout) -> QWidget:
    host = QWidget()
    host.setLayout(form)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(host)
    return scroll


def _group_box(title: str, form: QFormLayout) -> QGroupBox:
    box = QGroupBox(title)
    box.setLayout(form)
    return box


def _scrollable_grouped(*groups: tuple[str, QFormLayout]) -> QWidget:
    host = QWidget()
    layout = QVBoxLayout(host)
    layout.setContentsMargins(4, 8, 4, 8)
    for title, form in groups:
        layout.addWidget(_group_box(title, form))
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(host)
    return scroll


class UserPreferencesDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        on_apply: Callable[[UserPreferences], None] | None = None,
        orthanc_cache: OrthancSessionCache | None = None,
        protected_cache_sessions: Callable[[], set[str]] | None = None,
        measurement_storage_action: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_apply = on_apply
        if orthanc_cache is None:
            from echo_personal_tool.infrastructure.profile import orthanc_cache_root

            orthanc_cache = OrthancSessionCache(orthanc_cache_root())
        self._orthanc_cache = orthanc_cache
        self._protected_cache_sessions = protected_cache_sessions
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self._drag_pos = None
        current = load_user_preferences()

        # Adaptive sizing: cap at 80% of screen, minimum 500x400
        from PySide6.QtGui import QGuiApplication

        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            max_w = int(geo.width() * 0.80)
            max_h = int(geo.height() * 0.85)
        else:
            max_w, max_h = 780, 560
        self.setMinimumSize(500, 400)
        self.resize(min(780, max_w), min(560, max_h))

        # Custom title bar
        title_bar = QWidget()
        title_bar.setObjectName("preferencesTitleBar")
        title_bar.setFixedHeight(title_bar_height(self))
        title_bar_layout = QHBoxLayout(title_bar)
        title_bar_layout.setContentsMargins(6, 0, 0, 0)
        title_bar_layout.setSpacing(8)
        title_label = QLabel(tr("preferences.title"))
        title_label.setStyleSheet("font-weight: 500;")
        title_bar_layout.addWidget(title_label)
        title_bar_layout.addStretch(1)

        btn_close = QPushButton()
        from echo_personal_tool.presentation.system_bar import _load_icon

        btn_close.setIcon(_load_icon("close"))
        btn_close.setObjectName("closeButton")
        btn_close.setFixedSize(*icon_button_size(btn_close, "×"))
        btn_close.clicked.connect(self.reject)
        title_bar_layout.addWidget(btn_close)

        tabs = QTabWidget()
        self._tabs = tabs

        interface_form = QFormLayout()
        self._theme_combo = QComboBox()
        self._theme_combo.addItem(tr("preferences.theme_dark"), "dark")
        self._theme_combo.addItem(tr("preferences.theme_light"), "light")
        self._theme_combo.addItem("VS Code Dark", "vscode_dark")
        self._theme_combo.addItem("VS Code Light", "vscode_light")
        self._theme_combo.addItem(tr("preferences.theme_system"), "system")
        theme_index = self._theme_combo.findData(current.theme_mode)
        self._theme_combo.setCurrentIndex(max(theme_index, 0))
        self._language_combo = QComboBox()
        self._language_combo.addItem(tr("preferences.lang_ru"), "ru")
        self._language_combo.addItem(tr("preferences.lang_en"), "en")
        lang_index = self._language_combo.findData(current.language)
        self._language_combo.setCurrentIndex(max(lang_index, 0))
        self._font_spin = QSpinBox()
        self._font_spin.setRange(MIN_UI_FONT_SIZE, MAX_UI_FONT_SIZE)
        self._font_spin.setSuffix(" px")
        self._font_spin.setValue(current.ui_font_size)
        self._overlay_font_spin = QSpinBox()
        self._overlay_font_spin.setRange(MIN_OVERLAY_FONT_SIZE, MAX_OVERLAY_FONT_SIZE)
        self._overlay_font_spin.setSuffix(" px")
        self._overlay_font_spin.setValue(current.results_overlay_font_size)
        self._overlay_opacity_spin = QDoubleSpinBox()
        self._overlay_opacity_spin.setRange(MIN_OVERLAY_OPACITY, MAX_OVERLAY_OPACITY)
        self._overlay_opacity_spin.setSingleStep(0.05)
        self._overlay_opacity_spin.setDecimals(2)
        self._overlay_opacity_spin.setValue(current.results_overlay_opacity)
        self._caliper_spin = QDoubleSpinBox()
        self._caliper_spin.setRange(MIN_LINE_WIDTH, MAX_LINE_WIDTH)
        self._caliper_spin.setSingleStep(0.5)
        self._caliper_spin.setDecimals(1)
        self._caliper_spin.setSuffix(" px")
        self._caliper_spin.setValue(current.caliper_line_width)
        self._ui_scale = QComboBox()
        for percent in UI_SCALE_CHOICES:
            if percent == UI_SCALE_AUTO:
                self._ui_scale.addItem(tr("preferences.ui_scale_auto"), UI_SCALE_AUTO)
            else:
                self._ui_scale.addItem(f"{percent} %", percent)
        scale_index = self._ui_scale.findData(normalize_ui_scale(current.ui_scale_percent))
        self._ui_scale.setCurrentIndex(max(scale_index, 0))
        self._ui_scale.setToolTip(tr("preferences.ui_scale_tip"))
        interface_form.addRow(tr("preferences.color_theme"), self._theme_combo)
        interface_form.addRow(tr("preferences.ui_scale"), self._ui_scale)
        interface_form.addRow(tr("preferences.language"), self._language_combo)
        interface_form.addRow(tr("preferences.ui_font_size"), self._font_spin)
        interface_form.addRow(tr("preferences.results_overlay_font_size"), self._overlay_font_spin)
        interface_form.addRow(tr("preferences.results_overlay_opacity"), self._overlay_opacity_spin)
        interface_form.addRow(tr("preferences.caliper_width"), self._caliper_spin)

        display_form = QFormLayout()
        self._playback_spin = QDoubleSpinBox()
        self._playback_spin.setRange(MIN_PLAYBACK_SPEED, MAX_PLAYBACK_SPEED)
        self._playback_spin.setSingleStep(0.25)
        self._playback_spin.setDecimals(2)
        self._playback_spin.setSuffix("×")
        self._playback_spin.setValue(current.playback_speed_multiplier)
        self._wl_preset = QComboBox()
        self._wl_preset.addItem(tr("preferences.wl_last_used"), "last_used")
        self._wl_preset.addItem(tr("preferences.wl_soft"), "soft")
        self._wl_preset.addItem(tr("preferences.wl_contrast"), "contrast")
        preset_index = self._wl_preset.findData(current.wl_preset)
        self._wl_preset.setCurrentIndex(max(preset_index, 0))
        self._thumbnail_scale = QComboBox()
        self._thumbnail_scale.addItem(tr("tool_panel.small"), "small")
        self._thumbnail_scale.addItem(tr("tool_panel.medium"), "medium")
        self._thumbnail_scale.addItem(tr("tool_panel.large"), "large")
        thumb_index = self._thumbnail_scale.findData(current.thumbnail_scale)
        self._thumbnail_scale.setCurrentIndex(max(thumb_index, 0))
        self._thumbnail_sort = QComboBox()
        self._thumbnail_sort.addItem(tr("tool_panel.thumbnail_sort_created"), "created")
        self._thumbnail_sort.addItem(tr("tool_panel.thumbnail_sort_filename"), "filename")
        sort_index = self._thumbnail_sort.findData(current.thumbnail_sort_mode)
        self._thumbnail_sort.setCurrentIndex(max(sort_index, 0))
        self._show_crosshair = QCheckBox()
        self._show_crosshair.setChecked(current.show_crosshair)
        self._show_panel_frames = QCheckBox()
        self._show_panel_frames.setChecked(current.show_panel_frames)
        self._show_caliper_labels = QCheckBox()
        self._show_caliper_labels.setChecked(current.show_caliper_labels_on_frame)
        self._show_caliper_inline_labels = QCheckBox()
        self._show_caliper_inline_labels.setChecked(current.show_caliper_inline_labels)
        self._show_doppler_cal_roi = QCheckBox(tr("preferences.show_doppler_cal_roi"))
        self._show_doppler_cal_roi.setChecked(current.show_doppler_calibration_roi)
        self._anonymize_frames = QCheckBox()
        self._anonymize_frames.setChecked(current.anonymize_frames)
        self._anonymize_frames.setToolTip(tr("preferences.anonymize_frames_hint"))
        self._phi_text_detector = QCheckBox()
        self._phi_text_detector.setChecked(current.phi_text_detector)
        self._phi_text_detector.setToolTip(tr("preferences.phi_text_detector_hint"))
        self._reduce_motion = QCheckBox(tr("preferences.reduce_motion"))
        self._reduce_motion.setChecked(current.reduce_motion)
        self._magnifier_check = QCheckBox(tr("preferences.magnifier"))
        self._magnifier_check.setChecked(current.magnifier_enabled)
        self._magnifier_check.setToolTip(tr("preferences.magnifier_hint"))
        self._magnifier_zoom_spin = QDoubleSpinBox()
        self._magnifier_zoom_spin.setRange(MIN_MAGNIFIER_ZOOM, MAX_MAGNIFIER_ZOOM)
        self._magnifier_zoom_spin.setSingleStep(0.5)
        self._magnifier_zoom_spin.setDecimals(1)
        self._magnifier_zoom_spin.setSuffix(" x")
        self._magnifier_zoom_spin.setValue(current.magnifier_zoom)
        self._magnifier_radius_spin = QSpinBox()
        self._magnifier_radius_spin.setRange(MIN_MAGNIFIER_RADIUS_PX, MAX_MAGNIFIER_RADIUS_PX)
        self._magnifier_radius_spin.setSingleStep(5)
        self._magnifier_radius_spin.setSuffix(" px")
        self._magnifier_radius_spin.setValue(current.magnifier_radius_px)
        display_form.addRow(tr("tool_panel.cine_speed"), self._playback_spin)
        display_form.addRow(tr("tool_panel.wl_preset"), self._wl_preset)
        display_form.addRow(tr("tool_panel.thumbnail_size"), self._thumbnail_scale)
        display_form.addRow(tr("tool_panel.thumbnail_sort"), self._thumbnail_sort)
        display_form.addRow(tr("tool_panel.crosshair"), self._show_crosshair)
        display_form.addRow(tr("tool_panel.panel_frames"), self._show_panel_frames)
        display_form.addRow(tr("tool_panel.caliper_labels"), self._show_caliper_labels)
        display_form.addRow(tr("tool_panel.caliper_inline_labels"), self._show_caliper_inline_labels)
        display_form.addRow(self._show_doppler_cal_roi)
        display_form.addRow(tr("preferences.anonymize_frames"), self._anonymize_frames)
        display_form.addRow(tr("preferences.phi_text_detector"), self._phi_text_detector)
        display_form.addRow(self._magnifier_check)
        display_form.addRow(tr("preferences.magnifier_zoom"), self._magnifier_zoom_spin)
        display_form.addRow(tr("preferences.magnifier_radius"), self._magnifier_radius_spin)
        display_form.addRow(tr("preferences.reduce_motion"), self._reduce_motion)

        tabs.addTab(
            _scrollable_grouped(
                ("", interface_form),
                (tr("preferences.block_display"), display_form),
            ),
            tr("preferences.tab_interface"),
        )

        measure_form = QFormLayout()
        self._manual_contour_spin = QDoubleSpinBox()
        self._manual_contour_spin.setRange(MIN_LINE_WIDTH, MAX_LINE_WIDTH)
        self._manual_contour_spin.setSingleStep(0.5)
        self._manual_contour_spin.setDecimals(1)
        self._manual_contour_spin.setSuffix(" px")
        self._manual_contour_spin.setValue(current.contour_pen_manual_width)
        self._ai_contour_spin = QDoubleSpinBox()
        self._ai_contour_spin.setRange(MIN_LINE_WIDTH, MAX_LINE_WIDTH)
        self._ai_contour_spin.setSingleStep(0.5)
        self._ai_contour_spin.setDecimals(1)
        self._ai_contour_spin.setSuffix(" px")
        self._ai_contour_spin.setValue(current.contour_pen_ai_width)
        self._simpson_contour_spin = QDoubleSpinBox()
        self._simpson_contour_spin.setRange(MIN_LINE_WIDTH, MAX_LINE_WIDTH)
        self._simpson_contour_spin.setSingleStep(0.5)
        self._simpson_contour_spin.setDecimals(1)
        self._simpson_contour_spin.setSuffix(" px")
        self._simpson_contour_spin.setValue(current.contour_pen_simpson_width)
        self._magnetic_snap_check = QCheckBox(tr("preferences.magnetic_snap"))
        self._magnetic_snap_check.setChecked(current.magnetic_snap_enabled)
        self._magnetic_weight_spin = QDoubleSpinBox()
        self._magnetic_weight_spin.setRange(MIN_MAGNETIC_WEIGHT, MAX_MAGNETIC_WEIGHT)
        self._magnetic_weight_spin.setSingleStep(0.05)
        self._magnetic_weight_spin.setDecimals(2)
        self._magnetic_weight_spin.setValue(current.magnetic_snap_weight_threshold)
        self._magnetic_release_spin = QDoubleSpinBox()
        self._magnetic_release_spin.setRange(MIN_MAGNETIC_RELEASE, MAX_MAGNETIC_RELEASE)
        self._magnetic_release_spin.setSingleStep(0.05)
        self._magnetic_release_spin.setDecimals(2)
        self._magnetic_release_spin.setValue(current.magnetic_snap_release_strength)
        self._magnetic_radius_spin = QDoubleSpinBox()
        self._magnetic_radius_spin.setRange(MIN_MAGNETIC_RADIUS, MAX_MAGNETIC_RADIUS)
        self._magnetic_radius_spin.setSingleStep(1.0)
        self._magnetic_radius_spin.setDecimals(1)
        self._magnetic_radius_spin.setSuffix(" px")
        self._magnetic_radius_spin.setValue(current.magnetic_snap_release_max_radial_px)
        self._doppler_auto_cal = QCheckBox()
        self._doppler_auto_cal.setChecked(current.doppler_auto_calibration_enabled)
        self._calibration_tick_snap = QCheckBox(tr("preferences.calibration_tick_snap"))
        self._calibration_tick_snap.setChecked(current.calibration_tick_snap_enabled)
        self._auto_depth_cal = QCheckBox(tr("preferences.auto_depth_cal"))
        self._auto_depth_cal.setChecked(current.auto_depth_calibration_enabled)
        self._auto_depth_cal.setToolTip(tr("preferences.auto_depth_cal_tooltip"))
        self._length_unit = QComboBox()
        self._length_unit.addItem(tr("preferences.unit_mm"), "mm")
        self._length_unit.addItem(tr("preferences.unit_cm"), "cm")
        unit_index = self._length_unit.findData(current.length_display_unit)
        self._length_unit.setCurrentIndex(max(unit_index, 0))
        self._area_tool_mode_combo = QComboBox()
        self._area_tool_mode_combo.addItem(tr("preferences.area_mode_click"), "click")
        self._area_tool_mode_combo.addItem(tr("preferences.area_mode_freehand"), "freehand")
        area_mode_index = self._area_tool_mode_combo.findData(current.area_tool_mode)
        self._area_tool_mode_combo.setCurrentIndex(max(area_mode_index, 0))
        self._lv_contour_input_combo = QComboBox()
        self._lv_contour_input_combo.addItem(tr("preferences.lv_input_landmarks"), "landmarks")
        self._lv_contour_input_combo.addItem(tr("preferences.lv_input_trace"), "trace")
        lv_input_index = self._lv_contour_input_combo.findData(current.lv_contour_input)
        self._lv_contour_input_combo.setCurrentIndex(max(lv_input_index, 0))
        self._atrial_contour_input_combo = QComboBox()
        self._atrial_contour_input_combo.addItem(tr("preferences.atrial_input_landmarks"), "landmarks")
        self._atrial_contour_input_combo.addItem(tr("preferences.atrial_input_trace"), "trace")
        atrial_input_index = self._atrial_contour_input_combo.findData(current.atrial_contour_input)
        self._atrial_contour_input_combo.setCurrentIndex(max(atrial_input_index, 0))
        measure_form.addRow(tr("preferences.contour_manual"), self._manual_contour_spin)
        measure_form.addRow(tr("preferences.contour_ai"), self._ai_contour_spin)
        measure_form.addRow(tr("preferences.contour_simpson"), self._simpson_contour_spin)
        measure_form.addRow(self._magnetic_snap_check)
        measure_form.addRow(tr("preferences.magnetic_weight"), self._magnetic_weight_spin)
        measure_form.addRow(tr("preferences.magnetic_release"), self._magnetic_release_spin)
        measure_form.addRow(tr("preferences.magnetic_radius"), self._magnetic_radius_spin)
        measure_form.addRow(tr("preferences.doppler_from_dicom"), self._doppler_auto_cal)
        measure_form.addRow(self._calibration_tick_snap)
        measure_form.addRow(self._auto_depth_cal)
        measure_form.addRow(tr("preferences.length_display_unit"), self._length_unit)
        measure_form.addRow(tr("preferences.area_tool_mode"), self._area_tool_mode_combo)
        measure_form.addRow(tr("preferences.lv_contour_input"), self._lv_contour_input_combo)
        measure_form.addRow(tr("preferences.atrial_contour_input"), self._atrial_contour_input_combo)
        tabs.addTab(_scrollable_tab(measure_form), tr("preferences.tab_measurement"))

        self._tool_panel_settings = ToolPanelSettingsWidget(current.tool_panel_layout_json)
        tabs.addTab(self._tool_panel_settings, tr("preferences.tab_tools"))

        # --- Gold annotation ---
        gold_form = QFormLayout()
        self._gold_enabled = QCheckBox()
        self._gold_enabled.setChecked(current.gold_annotation_enabled)
        self._gold_path = QLineEdit(current.gold_dataset_path)
        self._gold_path.setPlaceholderText(str(Path.home() / "SonoForge-gold"))
        self._gold_path_browse = QPushButton(tr("preferences.gold_browse"))
        self._gold_path_browse.clicked.connect(self._browse_gold_path)
        gold_path_row = QHBoxLayout()
        gold_path_row.addWidget(self._gold_path)
        gold_path_row.addWidget(self._gold_path_browse)
        gold_form.addRow(tr("preferences.gold_enabled"), self._gold_enabled)
        gold_form.addRow(tr("preferences.gold_path"), gold_path_row)

        # --- DICOM ---
        dicom_form = QFormLayout()
        self._show_dicom_inspector = QCheckBox()
        self._show_dicom_inspector.setChecked(current.show_dicom_tag_inspector)
        self._interesting_tags = QLineEdit(current.interesting_dicom_tags)
        self._interesting_tags.setPlaceholderText("PatientName,StudyDate,HeartRate")
        self._interesting_tags.setToolTip(tr("preferences.tags_tooltip"))
        dicom_form.addRow(tr("preferences.inspector_tags"), self._show_dicom_inspector)
        dicom_form.addRow(tr("preferences.tags_overlay"), self._interesting_tags)

        # --- References ---
        refs_form = QFormLayout()
        self._refs_dir = QLineEdit(current.references_dir)
        self._refs_dir.setPlaceholderText(str(Path.home() / "SonoForge-references"))
        self._refs_dir_browse = QPushButton(tr("references_dir_browse"))
        self._refs_dir_browse.clicked.connect(self._browse_references_dir)
        refs_dir_row = QHBoxLayout()
        refs_dir_row.addWidget(self._refs_dir)
        refs_dir_row.addWidget(self._refs_dir_browse)
        refs_form.addRow(tr("preferences.references_dir"), refs_dir_row)

        # --- Other tab (consolidated with blocks) ---
        other_form = QFormLayout()
        self._confirm_reset = QCheckBox()
        self._confirm_reset.setChecked(current.confirm_reset)
        self._pdf_font_spin = QSpinBox()
        self._pdf_font_spin.setRange(MIN_PDF_FONT_SIZE, MAX_PDF_FONT_SIZE)
        self._pdf_font_spin.setSuffix(" pt")
        self._pdf_font_spin.setValue(current.pdf_font_size)
        self._startup_mode = QComboBox()
        self._startup_mode.addItem(tr("preferences.startup_empty_window"), "empty")
        self._startup_mode.addItem(tr("preferences.startup_last_folder"), "last_folder")
        startup_index = self._startup_mode.findData(current.startup_mode)
        self._startup_mode.setCurrentIndex(max(startup_index, 0))
        other_form.addRow(tr("preferences.confirm_reset"), self._confirm_reset)
        other_form.addRow(tr("preferences.pdf_font"), self._pdf_font_spin)
        other_form.addRow(tr("preferences.startup_at"), self._startup_mode)

        persistence_form = QFormLayout()
        self._persist_measurements = QCheckBox(tr("persistence.enable"))
        self._persist_measurements.setChecked(current.measurement_persistence_enabled)
        persistence_form.addRow(self._persist_measurements)
        persistence_hint = QLabel(tr("persistence.privacy") + "\n" + tr("persistence.restart"))
        persistence_hint.setWordWrap(True)
        persistence_form.addRow(persistence_hint)
        self._measurement_manage = QPushButton(tr("persistence.manage"))
        self._measurement_manage.setEnabled(measurement_storage_action is not None)
        if measurement_storage_action is not None:

            def manage_measurements():
                measurement_storage_action()
                self._persist_measurements.setChecked(load_user_preferences().measurement_persistence_enabled)

            self._measurement_manage.clicked.connect(manage_measurements)
        persistence_form.addRow(self._measurement_manage)

        # --- Managed DICOM download cache ---
        cache_form = QFormLayout()
        self._cache_location_label = QLabel(str(self._orthanc_cache.root))
        self._cache_location_label.setWordWrap(True)
        self._cache_location_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._cache_size_label = QLabel(self._format_cache_size(self._orthanc_cache.size_bytes()))
        self._cache_quota_label = QLabel(self._format_cache_size(self._orthanc_cache.max_size_bytes))
        self._cache_clear_button = QPushButton(tr("preferences.cache_clear"))
        self._cache_clear_button.clicked.connect(self._clear_cache)
        self._cache_clear_on_exit = QCheckBox(tr("preferences.cache_clear_on_exit"))
        self._cache_clear_on_exit.setChecked(current.orthanc_cache_clear_on_exit)
        self._cache_hint = QLabel(tr("preferences.cache_retention_hint"))
        self._cache_hint.setWordWrap(True)
        cache_form.addRow(tr("preferences.cache_location"), self._cache_location_label)
        cache_form.addRow(tr("preferences.cache_size"), self._cache_size_label)
        cache_form.addRow(tr("preferences.cache_quota"), self._cache_quota_label)
        cache_form.addRow("", self._cache_clear_button)
        cache_form.addRow("", self._cache_clear_on_exit)
        cache_form.addRow(self._cache_hint)

        # --- Other tab: confirm/pfd/startup + Gold + DICOM + Cache + References ---
        from echo_personal_tool.infrastructure.profile import (
            has_ai_segmentation,
            has_reference_ui,
        )

        other_blocks: list[tuple[str, object]] = [
            ("", other_form),
            (tr("preferences.block_gold"), gold_form),
            (tr("preferences.block_dicom"), dicom_form),
            (tr("preferences.block_cache"), cache_form),
            (tr("persistence.title"), persistence_form),
        ]
        if has_reference_ui():
            other_blocks.append((tr("preferences.block_references"), refs_form))
        tabs.addTab(
            _scrollable_grouped(*other_blocks),
            tr("preferences.tab_other"),
        )

        # Experimental features tab
        exp_form = QFormLayout()
        self._show_strain = QCheckBox()
        self._show_strain.setChecked(current.show_strain)
        exp_form.addRow(tr("prefs.show_strain"), self._show_strain)
        self._show_la_auto = QCheckBox()
        self._show_la_auto.setChecked(current.show_la_auto)
        if has_ai_segmentation():
            # LA auto-segmentation (ONNX) is not part of the Presenter build.
            exp_form.addRow(tr("prefs.show_la_auto"), self._show_la_auto)
        tabs.addTab(_scrollable_tab(exp_form), tr("prefs.tab_experimental"))

        self._server_form = ServerSettingsForm()
        server_scroll = QScrollArea()
        server_scroll.setWidgetResizable(True)
        server_scroll.setWidget(self._server_form)
        tabs.addTab(server_scroll, tr("preferences.tab_server"))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        self._recolor_buttonbox_icons(buttons)
        localize_dialog_button_box(buttons)
        theme_button_box_icons(buttons)

        reset_row = QHBoxLayout()
        reset_defaults_btn = QPushButton(tr("preferences.reset_defaults"))
        reset_defaults_btn.clicked.connect(self._reset_to_defaults)
        reset_row.addWidget(reset_defaults_btn)
        reset_row.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(title_bar)
        layout.addWidget(tabs)
        layout.addLayout(reset_row)
        layout.addWidget(buttons)

    @staticmethod
    def _format_cache_size(size_bytes: int) -> str:
        size = float(max(0, size_bytes))
        for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
            if size < 1024.0 or unit == "TiB":
                return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
            size /= 1024.0
        return "0 B"

    def _clear_cache(self) -> None:
        answer = QMessageBox.question(
            self,
            tr("preferences.cache_clear_title"),
            tr("preferences.cache_clear_confirm"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            preserve = set(self._protected_cache_sessions() if self._protected_cache_sessions else ())
        except Exception:  # noqa: BLE001
            QMessageBox.warning(
                self,
                tr("preferences.cache_clear_title"),
                tr("preferences.cache_clear_failed"),
            )
            return

        before = self._orthanc_cache.size_bytes()
        try:
            removed = self._orthanc_cache.clear_all(preserve_session_ids=preserve)
        except OSError:
            QMessageBox.warning(
                self,
                tr("preferences.cache_clear_title"),
                tr("preferences.cache_clear_failed"),
            )
            self._cache_size_label.setText(self._format_cache_size(self._orthanc_cache.size_bytes()))
            return
        after = self._orthanc_cache.size_bytes()
        freed = max(0, before - after)
        self._cache_size_label.setText(self._format_cache_size(after))
        active_cache_remains = any(self._orthanc_cache.session_path(session_id).exists() for session_id in preserve)

        if removed == 0 and after == 0:
            message = tr("preferences.cache_clear_empty")
        elif removed == 0 and after > 0 and not active_cache_remains:
            message = tr("preferences.cache_clear_failed")
        elif active_cache_remains:
            message = tr(
                "preferences.cache_clear_done_preserved",
                sessions=str(removed),
                size=self._format_cache_size(freed),
            )
        else:
            message = tr(
                "preferences.cache_clear_done",
                sessions=str(removed),
                size=self._format_cache_size(freed),
            )
        QMessageBox.information(self, tr("preferences.cache_clear_title"), message)

    def _reset_to_defaults(self) -> None:
        answer = QMessageBox.question(
            self,
            tr("preferences.reset_title"),
            tr("preferences.reset_confirm"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        defaults = default_user_preferences()
        stored = load_user_preferences()
        defaults.last_opened_folder = stored.last_opened_folder
        save_user_preferences(defaults)
        if self._on_apply is not None:
            self._on_apply(defaults)
        self.accept()

    def _browse_gold_path(self) -> None:
        from echo_personal_tool.presentation.styled_dialogs import styled_select_directory

        path = styled_select_directory(
            self,
            tr("preferences.gold_browse_title"),
            self._gold_path.text() or str(Path.home()),
            remember=False,  # a dataset folder is not one of the "recent patient folders"
        )
        if path:
            self._gold_path.setText(path)

    def _browse_references_dir(self) -> None:
        from echo_personal_tool.presentation.styled_dialogs import styled_select_directory

        path = styled_select_directory(
            self,
            tr("references_dir_browse_title"),
            self._refs_dir.text() or str(Path.home()),
            remember=False,
        )
        if path:
            self._refs_dir.setText(path)

    def _on_accept(self) -> None:
        stored = load_user_preferences()
        preferences = UserPreferences(
            ui_scale_percent=normalize_ui_scale(self._ui_scale.currentData()),
            ui_font_size=self._font_spin.value(),
            results_overlay_x_ratio=stored.results_overlay_x_ratio,
            results_overlay_y_ratio=stored.results_overlay_y_ratio,
            results_overlay_custom_position=stored.results_overlay_custom_position,
            results_overlay_font_size=self._overlay_font_spin.value(),
            results_overlay_opacity=float(self._overlay_opacity_spin.value()),
            caliper_line_width=float(self._caliper_spin.value()),
            contour_pen_manual_width=float(self._manual_contour_spin.value()),
            contour_pen_ai_width=float(self._ai_contour_spin.value()),
            contour_pen_simpson_width=float(self._simpson_contour_spin.value()),
            magnetic_snap_enabled=self._magnetic_snap_check.isChecked(),
            playback_speed_multiplier=float(self._playback_spin.value()),
            wl_preset=str(self._wl_preset.currentData()),
            wl_window=stored.wl_window,
            wl_level=stored.wl_level,
            wl_dr=stored.wl_dr,
            show_crosshair=self._show_crosshair.isChecked(),
            magnifier_enabled=self._magnifier_check.isChecked(),
            magnifier_zoom=float(self._magnifier_zoom_spin.value()),
            magnifier_radius_px=int(self._magnifier_radius_spin.value()),
            show_panel_frames=self._show_panel_frames.isChecked(),
            show_caliper_labels_on_frame=self._show_caliper_labels.isChecked(),
            show_caliper_inline_labels=self._show_caliper_inline_labels.isChecked(),
            show_doppler_calibration_roi=self._show_doppler_cal_roi.isChecked(),
            anonymize_frames=self._anonymize_frames.isChecked(),
            phi_text_detector=self._phi_text_detector.isChecked(),
            thumbnail_scale=str(self._thumbnail_scale.currentData()),
            thumbnail_sort_mode=str(self._thumbnail_sort.currentData()),
            magnetic_snap_weight_threshold=float(self._magnetic_weight_spin.value()),
            magnetic_snap_release_strength=float(self._magnetic_release_spin.value()),
            magnetic_snap_release_max_radial_px=float(self._magnetic_radius_spin.value()),
            doppler_auto_calibration_enabled=self._doppler_auto_cal.isChecked(),
            calibration_tick_snap_enabled=self._calibration_tick_snap.isChecked(),
            auto_depth_calibration_enabled=self._auto_depth_cal.isChecked(),
            length_display_unit=str(self._length_unit.currentData()),
            area_tool_mode=str(self._area_tool_mode_combo.currentData()),
            lv_contour_input=str(self._lv_contour_input_combo.currentData()),
            atrial_contour_input=str(self._atrial_contour_input_combo.currentData()),
            show_dicom_tag_inspector=self._show_dicom_inspector.isChecked(),
            interesting_dicom_tags=self._interesting_tags.text().strip(),
            confirm_reset=self._confirm_reset.isChecked(),
            pdf_font_size=self._pdf_font_spin.value(),
            startup_mode=str(self._startup_mode.currentData()),
            last_opened_folder=stored.last_opened_folder,
            orthanc_cache_clear_on_exit=self._cache_clear_on_exit.isChecked(),
            measurement_persistence_enabled=self._persist_measurements.isChecked(),
            theme_mode=str(self._theme_combo.currentData()),
            language=str(self._language_combo.currentData()),
            reduce_motion=self._reduce_motion.isChecked(),
            gold_annotation_enabled=self._gold_enabled.isChecked(),
            gold_dataset_path=self._gold_path.text().strip(),
            references_dir=self._refs_dir.text().strip(),
            show_strain=self._show_strain.isChecked(),
            show_la_auto=self._show_la_auto.isChecked(),
            despeckle_enabled=stored.despeckle_enabled,
            tool_panel_layout_json=self._tool_panel_settings.encoded_layout(),
            auto_play=stored.auto_play,
            playback_max_cache_mb=stored.playback_max_cache_mb,
            layout_state_json=stored.layout_state_json,
            presenter_screen=stored.presenter_screen,
            presenter_visual_preset=stored.presenter_visual_preset,
            presenter_pointer=stored.presenter_pointer,
        )
        scale_changed = normalize_ui_scale(stored.ui_scale_percent) != preferences.ui_scale_percent
        save_user_preferences(preferences)
        save_server_settings(self._server_form.settings())
        if self._on_apply is not None:
            self._on_apply(preferences)
        self.accept()
        if scale_changed:
            # Show the prompt after the dialog is gone, and only once the nested
            # event loop of exec() has unwound.
            QTimer.singleShot(0, self._prompt_ui_scale_restart)

    def _prompt_ui_scale_restart(self) -> None:
        """The multiplier is read before QApplication, so it needs a restart."""
        from echo_personal_tool.infrastructure.ui_scale import restart_application

        box = QMessageBox(self.parentWidget())
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle(tr("ui_scale.restart_title"))
        box.setText(tr("ui_scale.restart_text"))
        restart_button = box.addButton(tr("ui_scale.restart_now"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(tr("ui_scale.restart_later"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is not restart_button:
            return
        if restart_application():
            app = QApplication.instance()
            if app is not None:
                app.quit()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        self._drag_pos = None

    def showEvent(self, event) -> None:  # noqa: ANN001
        super().showEvent(event)
        QTimer.singleShot(0, self._setup_tab_scroll_arrows)

    def _setup_tab_scroll_arrows(self) -> None:
        tab_bar = self._tabs.tabBar()
        for btn in tab_bar.findChildren(QToolButton):
            # Scroll buttons are children of the tab bar with no text
            if not btn.text():
                btn.setMinimumWidth(28)
                if btn.x() < tab_bar.width() // 2:
                    btn.setText("<")
                else:
                    btn.setText(">")

    def _recolor_buttonbox_icons(self, box: QDialogButtonBox) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap

        from echo_personal_tool.presentation.dark_theme import get_theme_palette

        p = get_theme_palette()
        color = QColor(p["text"])
        for btn in box.findChildren(QPushButton):
            old_icon = btn.icon()
            if old_icon.isNull():
                continue
            pixmap = old_icon.pixmap(16, 16)
            if pixmap.isNull():
                continue
            image = QImage(16, 16, QImage.Format.Format_ARGB32)
            image.fill(Qt.GlobalColor.transparent)
            painter = QPainter(image)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            painter.drawPixmap(0, 0, pixmap)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            painter.fillRect(image.rect(), color)
            painter.end()
            btn.setIcon(QIcon(QPixmap.fromImage(image)))
