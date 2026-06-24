"""Dialog for interface and viewer preferences."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

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
    dialog = UserPreferencesDialog(parent, on_apply=on_apply)
    return dialog.exec() == QDialog.DialogCode.Accepted


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
        self.setWindowTitle("Настройки")
        self.resize(780, 560)
        current = load_user_preferences()

        tabs = QTabWidget()

        interface_form = QFormLayout()
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
        interface_form.addRow("Размер шрифта UI:", self._font_spin)
        interface_form.addRow("Шрифт оверлея результатов:", self._overlay_font_spin)
        interface_form.addRow("Прозрачность оверлея:", self._overlay_opacity_spin)
        interface_form.addRow("Толщина калиперов:", self._caliper_spin)
        tabs.addTab(_scrollable_tab(interface_form), "Интерфейс")

        display_form = QFormLayout()
        self._playback_spin = QDoubleSpinBox()
        self._playback_spin.setRange(MIN_PLAYBACK_SPEED, MAX_PLAYBACK_SPEED)
        self._playback_spin.setSingleStep(0.25)
        self._playback_spin.setDecimals(2)
        self._playback_spin.setSuffix("×")
        self._playback_spin.setValue(current.playback_speed_multiplier)
        self._wl_preset = QComboBox()
        self._wl_preset.addItem("Последний использованный", "last_used")
        self._wl_preset.addItem("Мягкий", "soft")
        self._wl_preset.addItem("Контрастный", "contrast")
        preset_index = self._wl_preset.findData(current.wl_preset)
        self._wl_preset.setCurrentIndex(max(preset_index, 0))
        self._thumbnail_scale = QComboBox()
        self._thumbnail_scale.addItem("Маленькие", "small")
        self._thumbnail_scale.addItem("Средние", "medium")
        self._thumbnail_scale.addItem("Крупные", "large")
        thumb_index = self._thumbnail_scale.findData(current.thumbnail_scale)
        self._thumbnail_scale.setCurrentIndex(max(thumb_index, 0))
        self._show_crosshair = QCheckBox()
        self._show_crosshair.setChecked(current.show_crosshair)
        self._show_panel_frames = QCheckBox()
        self._show_panel_frames.setChecked(current.show_panel_frames)
        self._show_caliper_labels = QCheckBox()
        self._show_caliper_labels.setChecked(current.show_caliper_labels_on_frame)
        display_form.addRow("Скорость cine:", self._playback_spin)
        display_form.addRow("Пресет W/L:", self._wl_preset)
        display_form.addRow("Размер миниатюр:", self._thumbnail_scale)
        display_form.addRow("Перекрестие:", self._show_crosshair)
        display_form.addRow("Рамки панелей:", self._show_panel_frames)
        display_form.addRow("Подписи калиперов:", self._show_caliper_labels)
        tabs.addTab(_scrollable_tab(display_form), "Отображение")

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
        self._magnetic_snap_check = QCheckBox("Магнит к стенке")
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
        self._length_unit = QComboBox()
        self._length_unit.addItem("мм", "mm")
        self._length_unit.addItem("см", "cm")
        unit_index = self._length_unit.findData(current.length_display_unit)
        self._length_unit.setCurrentIndex(max(unit_index, 0))
        measure_form.addRow("Контур (ручной):", self._manual_contour_spin)
        measure_form.addRow("Контур (AI):", self._ai_contour_spin)
        measure_form.addRow("Контур (Simpson):", self._simpson_contour_spin)
        measure_form.addRow(self._magnetic_snap_check)
        measure_form.addRow("Магнит: порог:", self._magnetic_weight_spin)
        measure_form.addRow("Магнит: отпускание:", self._magnetic_release_spin)
        measure_form.addRow("Магнит: радиус:", self._magnetic_radius_spin)
        measure_form.addRow("Doppler из DICOM:", self._doppler_auto_cal)
        measure_form.addRow("Единицы длины:", self._length_unit)
        tabs.addTab(_scrollable_tab(measure_form), "Измерения")

        dicom_form = QFormLayout()
        self._show_dicom_inspector = QCheckBox()
        self._show_dicom_inspector.setChecked(current.show_dicom_tag_inspector)
        self._interesting_tags = QLineEdit(current.interesting_dicom_tags)
        self._interesting_tags.setPlaceholderText("PatientName,StudyDate,HeartRate")
        self._interesting_tags.setToolTip(
            "Список тегов через запятую (имя или (0010,0010)). "
            "Показываются внизу слева на просмотрщике для DICOM-файлов."
        )
        dicom_form.addRow("Инспектор тегов:", self._show_dicom_inspector)
        dicom_form.addRow("Теги в оверлее:", self._interesting_tags)
        tabs.addTab(_scrollable_tab(dicom_form), "DICOM")

        other_form = QFormLayout()
        self._confirm_reset = QCheckBox()
        self._confirm_reset.setChecked(current.confirm_reset)
        self._pdf_font_spin = QSpinBox()
        self._pdf_font_spin.setRange(MIN_PDF_FONT_SIZE, MAX_PDF_FONT_SIZE)
        self._pdf_font_spin.setSuffix(" pt")
        self._pdf_font_spin.setValue(current.pdf_font_size)
        self._startup_mode = QComboBox()
        self._startup_mode.addItem("Пустое окно", "empty")
        self._startup_mode.addItem("Последняя папка", "last_folder")
        startup_index = self._startup_mode.findData(current.startup_mode)
        self._startup_mode.setCurrentIndex(max(startup_index, 0))
        other_form.addRow("Подтверждать Reset:", self._confirm_reset)
        other_form.addRow("Шрифт PDF:", self._pdf_font_spin)
        other_form.addRow("При запуске:", self._startup_mode)
        tabs.addTab(_scrollable_tab(other_form), "Прочее")

        self._server_form = ServerSettingsForm()
        tabs.addTab(self._server_form, "Сервер")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        reset_row = QHBoxLayout()
        reset_defaults_btn = QPushButton("По умолчанию")
        reset_defaults_btn.clicked.connect(self._reset_to_defaults)
        reset_row.addWidget(reset_defaults_btn)
        reset_row.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addLayout(reset_row)
        layout.addWidget(buttons)

    def _reset_to_defaults(self) -> None:
        answer = QMessageBox.question(
            self,
            "Сбросить настройки",
            "Вернуть все параметры к значениям по умолчанию?",
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
            thumbnail_scale=str(self._thumbnail_scale.currentData()),
            magnetic_snap_weight_threshold=float(self._magnetic_weight_spin.value()),
            magnetic_snap_release_strength=float(self._magnetic_release_spin.value()),
            magnetic_snap_release_max_radial_px=float(self._magnetic_radius_spin.value()),
            doppler_auto_calibration_enabled=self._doppler_auto_cal.isChecked(),
            length_display_unit=str(self._length_unit.currentData()),
            show_dicom_tag_inspector=self._show_dicom_inspector.isChecked(),
            interesting_dicom_tags=self._interesting_tags.text().strip(),
            confirm_reset=self._confirm_reset.isChecked(),
            pdf_font_size=self._pdf_font_spin.value(),
            startup_mode=str(self._startup_mode.currentData()),
            last_opened_folder=stored.last_opened_folder,
        )
        save_user_preferences(preferences)
        save_server_settings(self._server_form.settings())
        if self._on_apply is not None:
            self._on_apply(preferences)
        self.accept()
