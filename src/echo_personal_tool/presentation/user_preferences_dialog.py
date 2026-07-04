"""Dialog for interface and viewer preferences."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.infrastructure.server_settings import save_server_settings
from echo_personal_tool.infrastructure.user_preferences import (
    MAX_LINE_WIDTH,
    MAX_MAGNETIC_RADIUS,
    MAX_MAGNETIC_RELEASE,
    MAX_MAGNETIC_WEIGHT,
    MAX_OVERLAY_FONT_SIZE,
    MAX_OVERLAY_OPACITY,
    MAX_PDF_FONT_SIZE,
    MAX_PLAYBACK_SPEED,
    MAX_UI_FONT_SIZE,
    MIN_LINE_WIDTH,
    MIN_MAGNETIC_RADIUS,
    MIN_MAGNETIC_RELEASE,
    MIN_MAGNETIC_WEIGHT,
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


def show_user_preferences_dialog(
    parent: QWidget | None = None,
    *,
    on_apply: Callable[[UserPreferences], None] | None = None,
) -> bool:
    from echo_personal_tool.presentation.ui_animations import exec_animated
    dialog = UserPreferencesDialog(parent, on_apply=on_apply)
    return exec_animated(dialog) == QDialog.DialogCode.Accepted


def _scrollable_tab(form: QFormLayout) -> QWidget:
    host = QWidget()
    host.setLayout(form)
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
    ) -> None:
        super().__init__(parent)
        self._on_apply = on_apply
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Dialog
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.resize(780, 560)
        self._drag_pos = None
        current = load_user_preferences()

        # Custom title bar
        title_bar = QWidget()
        title_bar.setObjectName("systemBar")
        title_bar.setFixedHeight(34)
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
        btn_close.setFixedSize(28, 23)
        btn_close.clicked.connect(self.reject)
        title_bar_layout.addWidget(btn_close)

        tabs = QTabWidget()

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
        self._font_spin.setSuffix(" pt")
        self._font_spin.setValue(current.ui_font_size)
        self._overlay_font_spin = QSpinBox()
        self._overlay_font_spin.setRange(MIN_OVERLAY_FONT_SIZE, MAX_OVERLAY_FONT_SIZE)
        self._overlay_font_spin.setSuffix(" pt")
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
        interface_form.addRow(tr("preferences.color_theme"), self._theme_combo)
        interface_form.addRow(tr("preferences.language"), self._language_combo)
        interface_form.addRow(tr("preferences.ui_font_size"), self._font_spin)
        interface_form.addRow(tr("preferences.results_overlay_font_size"), self._overlay_font_spin)
        interface_form.addRow(tr("preferences.results_overlay_opacity"), self._overlay_opacity_spin)
        interface_form.addRow(tr("preferences.caliper_width"), self._caliper_spin)
        tabs.addTab(_scrollable_tab(interface_form), tr("preferences.tab_interface"))

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
        self._show_crosshair = QCheckBox()
        self._show_crosshair.setChecked(current.show_crosshair)
        self._show_panel_frames = QCheckBox()
        self._show_panel_frames.setChecked(current.show_panel_frames)
        self._show_caliper_labels = QCheckBox()
        self._show_caliper_labels.setChecked(current.show_caliper_labels_on_frame)
        self._show_caliper_inline_labels = QCheckBox()
        self._show_caliper_inline_labels.setChecked(current.show_caliper_inline_labels)
        self._reduce_motion = QCheckBox(tr("preferences.reduce_motion"))
        self._reduce_motion.setChecked(current.reduce_motion)
        display_form.addRow(tr("tool_panel.cine_speed"), self._playback_spin)
        display_form.addRow(tr("tool_panel.wl_preset"), self._wl_preset)
        display_form.addRow(tr("tool_panel.thumbnail_size"), self._thumbnail_scale)
        display_form.addRow(tr("tool_panel.crosshair"), self._show_crosshair)
        display_form.addRow(tr("tool_panel.panel_frames"), self._show_panel_frames)
        display_form.addRow(tr("tool_panel.caliper_labels"), self._show_caliper_labels)
        display_form.addRow(tr("tool_panel.caliper_inline_labels"), self._show_caliper_inline_labels)
        display_form.addRow(tr("preferences.reduce_motion"), self._reduce_motion)
        tabs.addTab(_scrollable_tab(display_form), tr("preferences.tab_display"))

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
        self._auto_depth_cal.setToolTip(
            tr("preferences.auto_depth_cal_tooltip")
        )
        self._length_unit = QComboBox()
        self._length_unit.addItem(tr("preferences.unit_mm"), "mm")
        self._length_unit.addItem(tr("preferences.unit_cm"), "cm")
        unit_index = self._length_unit.findData(current.length_display_unit)
        self._length_unit.setCurrentIndex(max(unit_index, 0))
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
        tabs.addTab(_scrollable_tab(measure_form), tr("preferences.tab_measurement"))

        dicom_form = QFormLayout()
        self._show_dicom_inspector = QCheckBox()
        self._show_dicom_inspector.setChecked(current.show_dicom_tag_inspector)
        self._interesting_tags = QLineEdit(current.interesting_dicom_tags)
        self._interesting_tags.setPlaceholderText("PatientName,StudyDate,HeartRate")
        self._interesting_tags.setToolTip(
            tr("preferences.tags_tooltip")
        )
        dicom_form.addRow(tr("preferences.inspector_tags"), self._show_dicom_inspector)
        dicom_form.addRow(tr("preferences.tags_overlay"), self._interesting_tags)
        tabs.addTab(_scrollable_tab(dicom_form), "DICOM")

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
        tabs.addTab(_scrollable_tab(other_form), tr("preferences.tab_other"))

        self._server_form = ServerSettingsForm()
        tabs.addTab(self._server_form, tr("preferences.tab_server"))

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

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

    def _on_accept(self) -> None:
        stored = load_user_preferences()
        preferences = UserPreferences(
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
            show_panel_frames=self._show_panel_frames.isChecked(),
            show_caliper_labels_on_frame=self._show_caliper_labels.isChecked(),
            show_caliper_inline_labels=self._show_caliper_inline_labels.isChecked(),
            thumbnail_scale=str(self._thumbnail_scale.currentData()),
            magnetic_snap_weight_threshold=float(self._magnetic_weight_spin.value()),
            magnetic_snap_release_strength=float(self._magnetic_release_spin.value()),
            magnetic_snap_release_max_radial_px=float(self._magnetic_radius_spin.value()),
            doppler_auto_calibration_enabled=self._doppler_auto_cal.isChecked(),
            calibration_tick_snap_enabled=self._calibration_tick_snap.isChecked(),
            auto_depth_calibration_enabled=self._auto_depth_cal.isChecked(),
            length_display_unit=str(self._length_unit.currentData()),
            show_dicom_tag_inspector=self._show_dicom_inspector.isChecked(),
            interesting_dicom_tags=self._interesting_tags.text().strip(),
            confirm_reset=self._confirm_reset.isChecked(),
            pdf_font_size=self._pdf_font_spin.value(),
            startup_mode=str(self._startup_mode.currentData()),
            last_opened_folder=stored.last_opened_folder,
            theme_mode=str(self._theme_combo.currentData()),
            language=str(self._language_combo.currentData()),
            reduce_motion=self._reduce_motion.isChecked(),
        )
        save_user_preferences(preferences)
        save_server_settings(self._server_form.settings())
        if self._on_apply is not None:
            self._on_apply(preferences)
        self.accept()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        self._drag_pos = None
