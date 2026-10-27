"""Dialog for interface and viewer preferences.

Redesigned layout (mock `docs/images/ui-redesign/07-settings-layout.png`):

* a left sidebar: header with search field «Найти параметр», then the
  settings sections as an icon list (Общее, Внешний вид и компоновка,
  Инструменты, …, О программе).  The selected section is highlighted.
* a right content area: the settings of the selected section, each in its
  own scrollable page.  Section title + subtitle at the top of the page.
* a bottom action bar: save-on-Done hint, section reset, support actions
  and «Готово». Actions wrap at narrow widths and large fonts.

Edits stay local until Done. The appearance page owns panel/accent colours,
Hotkeys edits the shared binding registry, and Privacy controls whether the
start page may render/search RAM-only DICOM family names.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.application.server_io import OrthancCache, make_orthanc_session_cache, save_server_settings
from echo_personal_tool.infrastructure.i18n import tr
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
    default_measurement_persistence_enabled,
    default_user_preferences,
    load_user_preferences,
    save_user_preferences,
)
from echo_personal_tool.keyboard_shortcuts import shortcut_label
from echo_personal_tool.presentation.layout.layout_settings import LayoutSettingsWidget
from echo_personal_tool.presentation.layout.presets import resolve_document
from echo_personal_tool.presentation.measures_menu import tool_layout_v3_from_v2
from echo_personal_tool.presentation.server_settings_dialog import ServerSettingsForm
from echo_personal_tool.presentation.shortcut_settings import ShortcutSettingsWidget
from echo_personal_tool.presentation.tool_settings_2 import ToolSettings2Widget
from echo_personal_tool.presentation.ui_metrics import icon_button_size, title_bar_height
from echo_personal_tool.presentation.wrapping_action_layout import WrappingActionLayout

__all__ = ["show_user_preferences_dialog"]


#: Sidebar sections: (object name, translation key, icon name).
#: ``(page object name, locale key, icon name)`` of the sidebar, top to bottom
#: (mock ``07-settings-layout.png``).
_SECTIONS: tuple[tuple[str, str, str], ...] = (
    ("settings_section_general", "settings.section.general", "settings"),
    ("settings_section_appearance", "settings.section.appearance", "layout"),
    ("settings_section_tools", "settings.section.tools", "wrench"),
    ("settings_section_protocols", "settings.section.protocols", "clipboard_list"),
    ("settings_section_measurements", "settings.section.measurements", "ruler"),
    ("settings_section_report", "settings.section.report", "file_report"),
    ("settings_section_server", "settings.section.server", "server"),
    ("settings_section_hotkeys", "settings.section.hotkeys", "keyboard"),
    ("settings_section_privacy", "settings.section.privacy", "shield"),
    ("settings_section_about", "settings.section.about", "info"),
)


#: Which ``UserPreferences`` fields each page owns. «Сбросить раздел» needs the
#: map to reset one section without touching the edits of the others; a field
#: that belongs to no page is reset by «Сбросить всё» only.
_SECTION_FIELDS: dict[str, tuple[str, ...]] = {
    "settings_section_general": (
        "language",
        "ui_scale_percent",
        "ui_font_size",
        "reduce_motion",
        "native_window_frame",
        "tabs_enabled",
        "startup_mode",
    ),
    "settings_section_appearance": (
        "theme_mode",
        "accent_palette",
        "layout_state_json",
        "layout_state_v2_json",
        "panel_width",
        "show_panel_frames",
        "thumbnail_scale",
        "thumbnail_sort_mode",
    ),
    "settings_section_tools": (
        "tool_layout_v3_json",
        "tool_panel_layout_json",
        "show_strain",
        "show_la_auto",
        "label_picker_enabled",
    ),
    "settings_section_protocols": (
        "tool_panel_v2",
        "show_strain",
        "show_la_auto",
        "despeckle_enabled",
        "gold_annotation_enabled",
    ),
    "settings_section_measurements": (
        "caliper_line_width",
        "contour_pen_manual_width",
        "contour_pen_ai_width",
        "contour_pen_simpson_width",
        "magnetic_snap_enabled",
        "magnetic_snap_weight_threshold",
        "magnetic_snap_release_strength",
        "magnetic_snap_release_max_radial_px",
        "length_display_unit",
        "area_tool_mode",
        "lv_contour_input",
        "atrial_contour_input",
        "show_caliper_labels_on_frame",
        "show_caliper_inline_labels",
        "doppler_auto_calibration_enabled",
        "calibration_tick_snap_enabled",
        "auto_depth_calibration_enabled",
        "show_doppler_calibration_roi",
        "results_overlay_font_size",
        "results_overlay_opacity",
        "results_overlay_custom_position",
        "measurement_persistence_enabled",
    ),
    "settings_section_report": (
        "show_dicom_tag_inspector",
        "interesting_dicom_tags",
        "confirm_reset",
        "pdf_font_size",
    ),
    "settings_section_server": ("orthanc_cache_clear_on_exit",),
    "settings_section_hotkeys": (
        "shortcut_overrides_json",
        "magnifier_enabled",
        "magnifier_zoom",
        "magnifier_radius_px",
        "magnifier_linear_persistent",
        "show_crosshair",
    ),
    "settings_section_privacy": (
        "start_page_show_patient_data",
        "anonymize_frames",
        "phi_mask_top_percent",
        "phi_text_detector",
    ),
    "settings_section_about": (
        "gold_dataset_path",
        "references_dir",
    ),
}


class _SettingsRowCaption(QWidget):
    """A name and a wrapped explanation reserve their real height at the current width."""

    def __init__(self, title: str, hint: str) -> None:
        super().__init__()
        self.setObjectName("settingsRowCaption")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        name = QLabel(title)
        name.setObjectName("settingsRowTitle")
        name.setWordWrap(True)
        layout.addWidget(name)
        if hint.strip():
            note = QLabel(hint.strip())
            note.setObjectName("settingsRowHint")
            note.setWordWrap(True)
            layout.addWidget(note)
        self._fit_height()

    def _fit_height(self) -> None:
        layout = self.layout()
        heights = []
        for label in self.findChildren(QLabel):
            height = max(label.fontMetrics().height(), label.heightForWidth(max(1, self.width())))
            label.setMinimumHeight(height)
            heights.append(height)
        height = sum(heights) + layout.spacing() * (layout.count() - 1)
        if height != self.minimumHeight():
            self.setMinimumHeight(height)
            self.updateGeometry()
        # A nested resize during setMinimumHeight can leave the inner layout
        # with its old rectangle even though the form allocated the taller row.
        layout.setGeometry(self.rect())

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit_height()


def _row_caption(title: str, hint: str) -> QWidget:
    return _SettingsRowCaption(title, hint)


def _dress_form(form: QFormLayout) -> None:
    """Turn a plain form into the mock's rows: name over hint, control right.

    ``QFormLayout`` right-aligns its labels by default, so the setting names
    sat against the controls in a ragged column of their own. Left-aligned,
    with the control aligned to the right edge, is the arrangement the mock
    shows — and it survives the 900 px minimum width the dialog allows.
    """
    form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    # Fields keep their own width; the caption column takes the slack, so a
    # combo sits at the right edge of the card without a wrapper widget per
    # row (sixty of them cost more than the look is worth).
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
    form.setHorizontalSpacing(24)
    form.setVerticalSpacing(14)
    for row in range(form.rowCount()):
        label_item = form.itemAt(row, QFormLayout.ItemRole.LabelRole)
        field_item = form.itemAt(row, QFormLayout.ItemRole.FieldRole)
        label = label_item.widget() if label_item is not None else None
        field = field_item.widget() if field_item is not None else None
        if not isinstance(label, QLabel) or field is None:
            continue
        title = label.text().strip()
        if not title:
            continue
        caption = _row_caption(title, field.toolTip())
        # Take the old label out of the cell first: ``setWidget`` on an occupied
        # cell is a no-op with a warning, and the caption would never appear.
        form.removeWidget(label)
        label.setParent(None)
        label.deleteLater()
        form.setWidget(row, QFormLayout.ItemRole.LabelRole, caption)
        caption.setMinimumWidth(240)
        caption.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)


def _wrap_in_card(content: QWidget) -> QWidget:
    """Put a page's own layout on the same rounded card as the form pages.

    The Server page is a bespoke widget (a form plus the cache block), not a
    ``QFormLayout``; without this it would be the one section that does not
    look like the others.
    """
    card = QFrame()
    card.setObjectName("settingsCard")
    card_layout = QVBoxLayout(card)
    card_layout.setContentsMargins(18, 14, 18, 14)
    card_layout.setSpacing(8)
    card_layout.addWidget(content, 1)

    host = QWidget()
    host.setObjectName("settingsFormHost")
    host_layout = QVBoxLayout(host)
    host_layout.setContentsMargins(16, 4, 16, 16)
    host_layout.setSpacing(12)
    host_layout.addWidget(card)
    host_layout.addStretch(1)
    return host


def _scrollable_tab(form: QFormLayout) -> QWidget:
    """One settings page's form, scrolling inside the content column.

    The page must paint the dialog's surface, not the platform's default
    window colour: a bare ``QScrollArea`` over the dark theme came out light
    grey, with the labels of the form barely readable on it. The form itself
    sits on a rounded card, as in the mock, so a page of settings reads as one
    block instead of a floating list of rows.
    """
    _dress_form(form)
    card = QFrame()
    card.setObjectName("settingsCard")
    card_layout = QVBoxLayout(card)
    card_layout.setContentsMargins(18, 14, 18, 14)
    card_layout.setSpacing(0)
    form.setContentsMargins(0, 0, 0, 0)
    card_layout.addLayout(form)
    card_layout.addStretch(1)

    host = QWidget()
    host.setObjectName("settingsFormHost")
    host_layout = QVBoxLayout(host)
    host_layout.setContentsMargins(16, 4, 16, 16)
    host_layout.setSpacing(12)
    host_layout.addWidget(card)
    host_layout.addStretch(1)
    scroll = QScrollArea()
    scroll.setObjectName("settingsFormScroll")
    scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
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


def show_user_preferences_dialog(
    parent: QWidget | None = None,
    *,
    on_apply: Callable[[UserPreferences], None] | None = None,
    orthanc_cache: OrthancCache | None = None,
    protected_cache_sessions: Callable[[], set[str]] | None = None,
    measurement_storage_action: Callable[[], bool | None] | None = None,
    initial_tab: str | None = None,
) -> bool:
    from echo_personal_tool.presentation.ui_animations import exec_animated

    dialog = UserPreferencesDialog(
        parent,
        on_apply=on_apply,
        orthanc_cache=orthanc_cache,
        protected_cache_sessions=protected_cache_sessions,
        measurement_storage_action=measurement_storage_action,
        initial_tab=initial_tab,
    )
    return exec_animated(dialog) == QDialog.DialogCode.Accepted


class _SectionPage(QWidget):
    """One settings section page: title, subtitle, scrollable form."""

    def __init__(self, title: str, subtitle: str, content: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget()
        header.setObjectName("settingsSectionHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(16, 12, 16, 8)
        header_layout.setSpacing(2)
        title_label = QLabel(title)
        title_label.setObjectName("settingsSectionTitle")
        header_layout.addWidget(title_label)
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("settingsSectionSubtitle")
        subtitle_label.setWordWrap(True)
        header_layout.addWidget(subtitle_label)
        layout.addWidget(header)

        layout.addWidget(content, stretch=1)


class UserPreferencesDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        on_apply: Callable[[UserPreferences], None] | None = None,
        orthanc_cache: OrthancCache | None = None,
        protected_cache_sessions: Callable[[], set[str]] | None = None,
        measurement_storage_action: Callable[[], bool | None] | None = None,
        initial_tab: str | None = None,
    ) -> None:
        super().__init__(parent)
        from echo_personal_tool.application.profile_settings import get_profile_capabilities

        self._profile_capabilities = get_profile_capabilities()
        self._on_apply = on_apply
        self._measurement_storage_action = measurement_storage_action
        if orthanc_cache is None:
            orthanc_cache = make_orthanc_session_cache()
        self._orthanc_cache = orthanc_cache
        self._protected_cache_sessions = protected_cache_sessions
        self.setObjectName("UserPreferencesDialog")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self._drag_pos = None
        current = load_user_preferences()

        # Adaptive sizing: cap at 80% of screen, minimum 900x620
        from PySide6.QtGui import QGuiApplication

        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            max_w = int(geo.width() * 0.80)
            max_h = int(geo.height() * 0.85)
        else:
            max_w, max_h = 900, 620
        self.setMinimumSize(900, 620)
        self.resize(min(1100, max_w), min(700, max_h))

        # Custom title bar — kept as a member so the frameless window may only
        # be dragged by this bar, not by arbitrary empty spots of the pages.
        title_bar = self._build_title_bar()
        self._title_bar = title_bar

        # Sidebar + content
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        sidebar = QWidget()
        sidebar.setObjectName("settingsSidebar")
        sidebar.setFixedWidth(250)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)

        # Search sits at the top of the sidebar, above the sections — the mock
        # puts it there, and it narrows the *section* list, not one form.
        search_host = QWidget()
        search_host.setObjectName("settingsSearchHost")
        search_layout = QHBoxLayout(search_host)
        search_layout.setContentsMargins(12, 12, 12, 8)
        search_layout.setSpacing(0)
        self._search = QLineEdit()
        self._search.setObjectName("preferencesSearch")
        self._search.setPlaceholderText(tr("settings.find_section"))
        self._search.setToolTip(tr("settings.find_section_hint"))
        self._search.setClearButtonEnabled(True)
        self._search.setReadOnly(False)
        search_layout.addWidget(self._search)
        sidebar_layout.addWidget(search_host)
        self._search.textChanged.connect(self._on_search_changed)

        self._section_list = QListWidget()
        self._section_list.setObjectName("settingsSectionList")
        self._section_list.setFrameShape(QListWidget.Shape.NoFrame)
        self._section_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._section_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        from echo_personal_tool.presentation.icon_loader import load_svg_icon

        self._section_list.setIconSize(QSize(18, 18))
        for object_name, key, icon_name in _SECTIONS:
            item = QListWidgetItem(load_svg_icon(icon_name), tr(key))
            item.setData(Qt.ItemDataRole.UserRole, object_name)
            row_height = max(38, self._section_list.sizeHintForRow(0))
            item.setSizeHint(QSize(0, row_height))
            self._section_list.addItem(item)
        self._section_list.setCurrentRow(0)
        self._section_list.currentItemChanged.connect(self._on_section_changed)
        sidebar_layout.addWidget(self._section_list, stretch=1)

        body.addWidget(sidebar)

        self._stack = QStackedWidget()
        body.addWidget(self._stack, stretch=1)

        root = QVBoxLayout(self)
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)
        root.addWidget(title_bar)
        root.addLayout(body, stretch=1)

        # Build all section pages (lazily-ish, all up front for simplicity).
        self._pages: dict[str, _SectionPage] = {}
        self._page_widgets: dict[str, QWidget] = {}
        self._build_pages(current)

        self._apply_profile_visibility()
        if initial_tab == "tools":
            for index in range(self._section_list.count()):
                item = self._section_list.item(index)
                if item is not None and str(item.data(Qt.ItemDataRole.UserRole) or "") == "settings_section_tools":
                    self._section_list.setCurrentItem(item)
                    break
        else:
            self._on_section_changed(self._section_list.currentItem(), None)

        # Keep complete captions at large fonts / narrow widths instead of
        # squeezing every action into one cropped line.
        action_bar = QWidget()
        action_bar.setObjectName("settingsActionBar")
        action_row = WrappingActionLayout(action_bar)
        action_row.setContentsMargins(16, 8, 16, 10)
        action_row.setSpacing(8)

        hint = QLabel(tr("settings.applies_on_done"))
        hint.setObjectName("settingsAppliesHint")
        action_row.addWidget(hint)

        self._section_reset_btn = QPushButton(tr("settings.reset_section"))
        self._section_reset_btn.setObjectName("settingsResetSection")
        self._section_reset_btn.setFlat(True)
        self._section_reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._section_reset_btn.clicked.connect(self._reset_current_section)
        action_row.addWidget(self._section_reset_btn)

        # Q-13: the way out when something is broken lives in Settings, next to
        # the destructive action, so it is reachable from every section.
        feedback_btn = QPushButton(tr("feedback.button"))
        feedback_btn.setObjectName("feedbackButton")
        feedback_btn.setToolTip(tr("feedback.intro"))
        feedback_btn.clicked.connect(self._report_problem)
        action_row.addWidget(feedback_btn)
        diagnostics_btn = QPushButton(tr("system_bar.save_diagnostics"))
        diagnostics_btn.setObjectName("saveDiagnosticsButton")
        diagnostics_btn.setToolTip(tr("system_bar.save_diagnostics_tooltip"))
        diagnostics_btn.clicked.connect(self._save_diagnostics)
        action_row.addWidget(diagnostics_btn)
        reset_defaults_btn = QPushButton(tr("preferences.reset_defaults"))
        reset_defaults_btn.setObjectName("settingsResetAll")
        reset_defaults_btn.clicked.connect(self._reset_to_defaults)
        action_row.addWidget(reset_defaults_btn)
        help_btn = QPushButton(tr("start_page.help"))
        help_btn.setObjectName("settingsHelp")
        help_btn.setToolTip(tr("preferences.help_hint"))

        def _open_help() -> None:
            from echo_personal_tool.presentation.help_dialog import show_help_dialog

            show_help_dialog(self)

        help_btn.clicked.connect(_open_help)
        action_row.addWidget(help_btn)

        # This is a standalone button: reparenting an OK button out of a
        # QDialogButtonBox disconnects its accepted role. Esc remains QDialog's
        # native reject, while a real click must save and accept exactly once.
        ok_button = QPushButton(tr("settings.ok"))
        self._ok_button = ok_button
        ok_button.clicked.connect(self._on_accept)
        ok_button.setObjectName("settingsOkButton")
        ok_button.setText(tr("settings.ok"))
        ok_button.setDefault(True)
        ok_button.setMinimumWidth(120)
        # The ✓ of the standard box is tinted with the *dim text* role, which
        # is unreadable on the accent fill of the primary button: the mock's
        # single «Готово» is a plain filled button with no glyph.
        ok_button.setIcon(QIcon())
        action_row.addWidget(ok_button)

        root.addWidget(action_bar)
        # Set the default only after parenting the complete action bar into
        # QDialog. Otherwise the first auto-default child (the close ×) steals
        # Return on show, so Enter silently rejects the settings.
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
        ok_button.setDefault(True)

        # Apply dialog-level stylesheet
        self._apply_dialog_stylesheet()
        from echo_personal_tool.presentation.theme.dialog_outline import ensure_dialog_outline

        ensure_dialog_outline(self)

    # ── construction helpers ─────────────────────────────────────────

    def _build_title_bar(self) -> QWidget:
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
        return title_bar

    def _apply_dialog_stylesheet(self) -> None:
        from echo_personal_tool.presentation.dark_theme import get_theme_tokens
        from echo_personal_tool.presentation.theme.button_feedback import ButtonFeedback
        from echo_personal_tool.presentation.theme.controls import button_qss

        tokens = get_theme_tokens()
        # One QSS recipe for every button of the dialog: the primary «Готово»
        # and the secondary actions differ only in their resting fill.  The
        # primary also gets animated hover/press feedback (item 1 of the
        # 2026-10-27 UI list) — its old :hover rule repeated the resting
        # colour, so pointing at it changed nothing at all.
        button_styles = button_qss(
            "QPushButton#settingsOkButton",
            tokens,
            variant="primary",
            padding_x=18,
            padding_y=7,
        )
        button_styles += button_qss(
            (
                "QPushButton#feedbackButton",
                "QPushButton#saveDiagnosticsButton",
                "QPushButton#settingsHelp",
            ),
            tokens,
            padding_x=12,
            padding_y=6,
        )
        self.setStyleSheet(
            f"QDialog#UserPreferencesDialog {{ background: {tokens['surface.0']}; }}\n"
            f"QWidget#preferencesTitleBar {{ background: {tokens['surface.1']}; border-bottom: 1px solid {tokens['line.1']}; }}\n"
            f"QLineEdit#preferencesSearch {{ background: {tokens['surface.2']}; color: {tokens['text.1']}; "
            f"border: 1px solid {tokens['line.1']}; border-radius: 4px; padding: 4px 8px; }}\n"
            f"QWidget#settingsSidebar {{ background: {tokens['surface.1']}; border-right: 1px solid {tokens['line.1']}; }}\n"
            f"QLabel#settingsSectionsTitle {{ color: {tokens['text.3']}; font-weight: 600; }}\n"
            f"QListWidget#settingsSectionList {{ background: transparent; border: none; outline: none; color: {tokens['text.1']}; }}\n"
            f"QListWidget#settingsSectionList::item {{ border-radius: 6px; padding: 6px 12px; }}\n"
            f"QListWidget#settingsSectionList::item:selected {{ background: {tokens['surface.hover']}; "
            f"color: {tokens['accent']}; border-left: 2px solid {tokens['accent']}; }}\n"
            f"QListWidget#settingsSectionList::item:hover:!selected {{ background: {tokens['surface.hover']}; }}\n"
            f"QWidget#settingsSectionHeader {{ background: {tokens['surface.0']}; }}\n"
            f"QFrame#settingsCard {{ background: {tokens['surface.1']}; "
            f"border: 1px solid {tokens['line.1']}; border-radius: 10px; }}\n"
            f"QLabel#settingsSectionTitle {{ color: {tokens['text.1']}; font-size: 21px; font-weight: 600; }}\n"
            f"QLabel#settingsSectionSubtitle {{ color: {tokens['text.2']}; }}\n"
            f"QWidget#settingsActionBar {{ background: {tokens['surface.0']}; "
            f"border-top: 1px solid {tokens['line.1']}; }}\n"
            f"QScrollArea#settingsFormScroll, QWidget#settingsFormHost {{ "
            f"background: {tokens['surface.0']}; }}\n"
            f"QWidget#settingsFormHost QLabel {{ color: {tokens['text.1']}; "
            f"background: transparent; }}\n"
            f"QLabel#settingsRowTitle {{ color: {tokens['text.1']}; font-weight: 600; }}\n"
            f"QLabel#settingsRowHint {{ color: {tokens['text.3']}; }}\n"
            f"QWidget#settingsFormHost QLineEdit {{ background: {tokens['surface.2']}; "
            f"border: 1px solid {tokens['line.1']}; border-radius: 4px; padding: 4px 8px; }}\n"
            f"QWidget#settingsFormHost QCheckBox, QWidget#settingsFormHost QRadioButton {{ "
            f"color: {tokens['text.1']}; background: transparent; }}\n"
            f"QWidget#settingsFormHost QGroupBox {{ color: {tokens['text.1']}; "
            f"border: 1px solid {tokens['line.1']}; border-radius: 6px; margin-top: 12px; "
            f"padding: 10px 8px 8px 8px; }}\n"
            f"QWidget#settingsFormHost QGroupBox::title {{ subcontrol-origin: margin; "
            f"left: 10px; padding: 0 4px; color: {tokens['text.2']}; }}\n"
            f"QPushButton#closeButton {{ background: transparent; border: none; "
            f"border-radius: 4px; }}\n"
            f"QPushButton#closeButton:hover {{ background: {tokens['surface.hover']}; }}\n"
            f"QLabel#settingsAppliesHint {{ color: {tokens['text.3']}; }}\n"
            f"QPushButton#settingsResetSection, QPushButton#settingsResetAll {{ color: {tokens['accent.text']}; "
            f"background: transparent; border: none; padding: 4px 6px; text-align: left; }}\n"
            f"QPushButton#settingsResetSection:hover, QPushButton#settingsResetAll:hover {{ "
            f"color: {tokens['accent']}; text-decoration: underline; }}\n"
            f"QPushButton#settingsOkButton {{ font-weight: 600; }}\n"
            f"QPushButton#settingsResetSection, QPushButton#settingsResetAll {{ border-radius: 6px; }}\n"
            + button_styles
        )
        ButtonFeedback.install_all(
            (
                getattr(self, "_ok_button", None),
                self.findChild(QPushButton, "feedbackButton"),
                self.findChild(QPushButton, "saveDiagnosticsButton"),
                self.findChild(QPushButton, "settingsHelp"),
            )
        )

    def _build_theme_choice(self, current) -> None:
        self._theme_combo = QComboBox()
        self._theme_combo.addItem(tr("preferences.theme_dark"), "dark")
        self._theme_combo.addItem(tr("preferences.theme_light"), "light")
        self._theme_combo.addItem("VS Code Dark", "vscode_dark")
        self._theme_combo.addItem("VS Code Light", "vscode_light")
        self._theme_combo.addItem(tr("preferences.theme_graphite"), "graphite")
        self._theme_combo.addItem(tr("preferences.theme_system"), "system")
        theme_index = self._theme_combo.findData(current.theme_mode)
        self._theme_combo.setCurrentIndex(max(theme_index, 0))

    def _add_accent_palette_setting(self, form, current) -> None:
        from echo_personal_tool.presentation.theme.palette_picker import InterfacePalettePicker

        self._accent_palette_combo = QComboBox()
        self._accent_palette_combo.setObjectName("accentPaletteCombo")
        for value in ("theme", "blue", "teal", "violet", "amber"):
            self._accent_palette_combo.addItem(tr(f"preferences.accent_{value}"), value)
        self._accent_palette_combo.setCurrentIndex(max(0, self._accent_palette_combo.findData(current.accent_palette)))
        form.addRow(tr("preferences.accent_palette"), self._accent_palette_combo)
        # The missing «interface palette» control of the 2026-10-27 UI list:
        # a visible choice of the colours of panels, fields, buttons and the
        # active accent.  The cards drive the two comboboxes above, so no
        # third preference is introduced and a hand-picked combination still
        # works (no card is checked then).
        # The dialog is a reviewed i18n source; inject ``tr`` so the picker
        # itself stays free of a new presentation -> infrastructure edge.
        self._palette_picker = InterfacePalettePicker(self, translate=tr)
        self._palette_picker.palette_selected.connect(self._on_palette_preset_selected)
        form.addRow(tr("preferences.interface_palette"), self._palette_picker)
        self._theme_combo.currentIndexChanged.connect(self._sync_palette_picker)
        self._accent_palette_combo.currentIndexChanged.connect(self._sync_palette_picker)
        self._sync_palette_picker()

    def _on_palette_preset_selected(self, theme: str, accent: str) -> None:
        theme_index = self._theme_combo.findData(theme)
        accent_index = self._accent_palette_combo.findData(accent)
        if theme_index < 0 or accent_index < 0:
            return
        self._theme_combo.setCurrentIndex(theme_index)
        self._accent_palette_combo.setCurrentIndex(accent_index)

    def _sync_palette_picker(self) -> None:
        picker = getattr(self, "_palette_picker", None)
        if picker is None:
            return
        picker.set_current(str(self._theme_combo.currentData()), str(self._accent_palette_combo.currentData()))

    def _build_pages(self, current: UserPreferences) -> None:
        from echo_personal_tool.application.profile_settings import get_profile_capabilities

        capabilities = get_profile_capabilities()

        # ── General ──────────────────────────────────────────────
        general_form = QFormLayout()
        self._tabs_enabled = QCheckBox(tr("preferences.tabs_enabled"))
        self._tabs_enabled.setChecked(current.tabs_enabled)
        self._tabs_enabled.setToolTip(
            tr(
                "preferences.tabs_enabled_hint",
                new_tab=shortcut_label("new_tab"),
                next_tab=shortcut_label("next_tab"),
                previous_tab=shortcut_label("previous_tab"),
                close_tab=shortcut_label("close_tab"),
            )
        )
        self._tabs_enabled.setEnabled(capabilities.tabs)
        general_form.addRow(self._tabs_enabled)
        self._native_window_frame = QCheckBox(tr("preferences.native_window_frame"))
        self._native_window_frame.setChecked(current.native_window_frame)
        self._native_window_frame.setToolTip(tr("preferences.native_window_frame_hint"))
        general_form.addRow(self._native_window_frame)
        self._build_theme_choice(current)
        self._language_combo = QComboBox()
        self._language_combo.addItem(tr("preferences.lang_ru"), "ru")
        self._language_combo.addItem(tr("preferences.lang_en"), "en")
        lang_index = self._language_combo.findData(current.language)
        self._language_combo.setCurrentIndex(max(lang_index, 0))
        self._font_spin = QSpinBox()
        self._font_spin.setRange(MIN_UI_FONT_SIZE, MAX_UI_FONT_SIZE)
        self._font_spin.setSuffix(" px")
        self._font_spin.setValue(current.ui_font_size)
        self._ui_scale = QComboBox()
        for percent in UI_SCALE_CHOICES:
            if percent == UI_SCALE_AUTO:
                self._ui_scale.addItem(tr("preferences.ui_scale_auto"), UI_SCALE_AUTO)
            else:
                self._ui_scale.addItem(f"{percent} %", percent)
        scale_index = self._ui_scale.findData(normalize_ui_scale(current.ui_scale_percent))
        self._ui_scale.setCurrentIndex(max(scale_index, 0))
        self._ui_scale.setToolTip(tr("preferences.ui_scale_tip"))
        general_form.addRow(tr("preferences.ui_scale"), self._ui_scale)
        general_form.addRow(tr("preferences.language"), self._language_combo)
        general_form.addRow(tr("preferences.ui_font_size"), self._font_spin)
        # Startup behaviour is a general-app preference (the mock has no
        # «Прочее» row, so it lives here rather than on a page of its own).
        self._startup_mode = QComboBox()
        self._startup_mode.addItem(tr("preferences.startup_empty_window"), "empty")
        if self._profile_capabilities.continue_last_session:
            self._startup_mode.addItem(tr("preferences.startup_last_folder"), "last_folder")
        startup_index = self._startup_mode.findData(current.startup_mode)
        self._startup_mode.setCurrentIndex(max(startup_index, 0))
        general_form.addRow(tr("preferences.startup_at"), self._startup_mode)
        startup_hint = QLabel(tr("preferences.startup_last_folder_hint"))
        startup_hint.setWordWrap(True)
        general_form.addRow("", startup_hint)
        general_page = _SectionPage(
            tr("settings.section.general"),
            tr("settings.section.general_hint"),
            _scrollable_tab(general_form),
        )
        self._register_page("settings_section_general", general_page)

        # ── Appearance & layout ──────────────────────────────────
        appearance_form = QFormLayout()
        appearance_form.addRow(tr("preferences.color_theme"), self._theme_combo)
        self._theme_combo.setToolTip(tr("preferences.color_theme_hint"))
        self._add_accent_palette_setting(appearance_form, current)
        self._accent_palette_combo.setToolTip(tr("preferences.accent_palette_hint"))
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
        self._show_doppler_cal_roi = QCheckBox()
        self._show_doppler_cal_roi.setChecked(current.show_doppler_calibration_roi)
        self._anonymize_frames = QCheckBox()
        self._anonymize_frames.setChecked(current.anonymize_frames)
        self._anonymize_frames.setToolTip(tr("preferences.anonymize_frames_hint"))
        self._phi_text_detector = QCheckBox()
        self._phi_text_detector.setChecked(current.phi_text_detector)
        self._phi_text_detector.setToolTip(tr("preferences.phi_text_detector_hint"))
        self._phi_mask_top = QComboBox()
        for _label, _value in (
            (tr("preferences.phi_mask_top_auto"), 0.0),
            ("4 %", 0.04),
            ("6 %", 0.06),
            ("8 %", 0.08),
            ("10 %", 0.10),
            ("12 %", 0.12),
            ("14 %", 0.14),
        ):
            self._phi_mask_top.addItem(_label, _value)
        _mask_index = self._phi_mask_top.findData(round(current.phi_mask_top_percent, 2))
        self._phi_mask_top.setCurrentIndex(_mask_index if _mask_index >= 0 else 0)
        self._phi_mask_top.setToolTip(tr("preferences.phi_mask_top_hint"))
        self._reduce_motion = QCheckBox()
        self._reduce_motion.setChecked(current.reduce_motion)
        self._playback_spin = QDoubleSpinBox()
        self._playback_spin.setRange(MIN_PLAYBACK_SPEED, MAX_PLAYBACK_SPEED)
        self._playback_spin.setSingleStep(0.25)
        self._playback_spin.setDecimals(2)
        self._playback_spin.setSuffix("×")
        self._playback_spin.setValue(current.playback_speed_multiplier)
        appearance_form.addRow(tr("preferences.results_overlay_font_size"), self._overlay_font_spin)
        appearance_form.addRow(tr("preferences.results_overlay_opacity"), self._overlay_opacity_spin)
        appearance_form.addRow(tr("preferences.caliper_width"), self._caliper_spin)
        appearance_form.addRow(tr("tool_panel.cine_speed"), self._playback_spin)
        appearance_form.addRow(tr("tool_panel.thumbnail_size"), self._thumbnail_scale)
        appearance_form.addRow(tr("tool_panel.thumbnail_sort"), self._thumbnail_sort)
        appearance_form.addRow(tr("tool_panel.crosshair"), self._show_crosshair)
        appearance_form.addRow(tr("tool_panel.panel_frames"), self._show_panel_frames)
        appearance_form.addRow(tr("tool_panel.caliper_labels"), self._show_caliper_labels)
        appearance_form.addRow(tr("tool_panel.caliper_inline_labels"), self._show_caliper_inline_labels)
        appearance_form.addRow(tr("preferences.show_doppler_cal_roi"), self._show_doppler_cal_roi)
        appearance_form.addRow(tr("preferences.anonymize_frames"), self._anonymize_frames)
        appearance_form.addRow(tr("preferences.phi_mask_top"), self._phi_mask_top)
        appearance_form.addRow(tr("preferences.phi_text_detector"), self._phi_text_detector)
        appearance_form.addRow(tr("preferences.reduce_motion"), self._reduce_motion)

        self._layout_section = LayoutSettingsWidget(
            resolve_document(current.layout_state_v2_json, current.layout_state_json)
        )
        appearance_form.addRow(self._layout_section)

        appearance_page = _SectionPage(
            tr("settings.section.appearance"),
            tr("settings.section.appearance_hint"),
            _scrollable_tab(appearance_form),
        )
        self._register_page("settings_section_appearance", appearance_page)

        # ── Tools ────────────────────────────────────────────────
        self._build_tools_page(current)

        # ── Protocols & norms ────────────────────────────────────
        protocols_form = QFormLayout()
        self._show_strain = QCheckBox()
        self._show_strain.setChecked(current.show_strain)
        protocols_form.addRow(tr("prefs.show_strain"), self._show_strain)
        self._show_la_auto = QCheckBox()
        self._show_la_auto.setChecked(current.show_la_auto)
        if capabilities.ai_segmentation:
            protocols_form.addRow(tr("prefs.show_la_auto"), self._show_la_auto)
        self._tool_panel_v2 = QCheckBox()
        self._tool_panel_v2.setChecked(current.tool_panel_v2)
        self._tool_panel_v2.setToolTip(tr("prefs.tool_panel_v2_hint"))
        protocols_form.addRow(tr("prefs.tool_panel_v2"), self._tool_panel_v2)
        protocols_page = _SectionPage(
            tr("settings.section.protocols"),
            tr("settings.section.protocols_hint"),
            _scrollable_tab(protocols_form),
        )
        self._register_page("settings_section_protocols", protocols_page)

        # ── Measurements & units ─────────────────────────────────
        measurements_form = QFormLayout()
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
        self._magnetic_snap_check = QCheckBox()
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
        self._calibration_tick_snap = QCheckBox()
        self._calibration_tick_snap.setChecked(current.calibration_tick_snap_enabled)
        self._auto_depth_cal = QCheckBox()
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
        self._label_picker_enabled = QCheckBox()
        self._label_picker_enabled.setChecked(current.label_picker_enabled)
        measurements_form.addRow(tr("preferences.contour_manual"), self._manual_contour_spin)
        measurements_form.addRow(tr("preferences.contour_ai"), self._ai_contour_spin)
        measurements_form.addRow(tr("preferences.contour_simpson"), self._simpson_contour_spin)
        measurements_form.addRow(tr("preferences.magnetic_snap"), self._magnetic_snap_check)
        measurements_form.addRow(tr("preferences.magnetic_weight"), self._magnetic_weight_spin)
        measurements_form.addRow(tr("preferences.magnetic_release"), self._magnetic_release_spin)
        measurements_form.addRow(tr("preferences.magnetic_radius"), self._magnetic_radius_spin)
        measurements_form.addRow(tr("preferences.doppler_from_dicom"), self._doppler_auto_cal)
        measurements_form.addRow(tr("preferences.calibration_tick_snap"), self._calibration_tick_snap)
        measurements_form.addRow(tr("preferences.auto_depth_cal"), self._auto_depth_cal)
        measurements_form.addRow(tr("preferences.length_display_unit"), self._length_unit)
        measurements_form.addRow(tr("preferences.area_tool_mode"), self._area_tool_mode_combo)
        measurements_form.addRow(tr("preferences.lv_contour_input"), self._lv_contour_input_combo)
        measurements_form.addRow(tr("preferences.atrial_contour_input"), self._atrial_contour_input_combo)
        measurements_form.addRow(tr("preferences.label_picker_enabled"), self._label_picker_enabled)
        # Measurement persistence is a property of measurements, not a section
        # of its own (the mock has no «Прочее» row).
        self._persist_measurements = QCheckBox()
        self._persist_measurements.setChecked(current.measurement_persistence_enabled)
        self._persist_measurements.setEnabled(self._profile_capabilities.measurement_storage)
        measurements_form.addRow(tr("persistence.enable"), self._persist_measurements)
        persistence_hint = QLabel(tr("persistence.privacy") + "\n" + tr("persistence.toggle_hint"))
        persistence_hint.setWordWrap(True)
        measurements_form.addRow("", persistence_hint)
        self._measurement_manage = QPushButton(tr("persistence.manage"))
        self._measurement_manage.setEnabled(
            self._profile_capabilities.measurement_storage and self._measurement_storage_action is not None
        )
        if self._measurement_storage_action is not None:

            def manage_measurements():
                action = self._measurement_storage_action
                if action is not None and action():
                    self._persist_measurements.setChecked(load_user_preferences().measurement_persistence_enabled)

            self._measurement_manage.clicked.connect(manage_measurements)
        measurements_form.addRow(self._measurement_manage)
        measurements_page = _SectionPage(
            tr("settings.section.measurements"),
            tr("settings.section.measurements_hint"),
            _scrollable_tab(measurements_form),
        )
        self._register_page("settings_section_measurements", measurements_page)

        # ── Report ───────────────────────────────────────────────
        report_form = QFormLayout()
        self._show_dicom_inspector = QCheckBox()
        self._show_dicom_inspector.setChecked(current.show_dicom_tag_inspector)
        self._interesting_tags = QLineEdit(current.interesting_dicom_tags)
        self._interesting_tags.setPlaceholderText("PatientName,StudyDate,HeartRate")
        self._interesting_tags.setToolTip(tr("preferences.tags_tooltip"))
        self._confirm_reset = QCheckBox()
        self._confirm_reset.setChecked(current.confirm_reset)
        self._pdf_font_spin = QSpinBox()
        self._pdf_font_spin.setRange(MIN_PDF_FONT_SIZE, MAX_PDF_FONT_SIZE)
        self._pdf_font_spin.setSuffix(" pt")
        self._pdf_font_spin.setValue(current.pdf_font_size)
        report_form.addRow(tr("preferences.inspector_tags"), self._show_dicom_inspector)
        report_form.addRow(tr("preferences.tags_overlay"), self._interesting_tags)
        report_form.addRow(tr("preferences.confirm_reset"), self._confirm_reset)
        report_form.addRow(tr("preferences.pdf_font"), self._pdf_font_spin)
        report_page = _SectionPage(
            tr("settings.section.report"),
            tr("settings.section.report_hint"),
            _scrollable_tab(report_form),
        )
        self._register_page("settings_section_report", report_page)

        # ── Server (PACS / Orthanc) ──────────────────────────────
        self._build_server_page(current)

        self._build_hotkeys_page(current)
        self._build_privacy_page(current)

        # ── About ────────────────────────────────────────────────
        about_form = QFormLayout()
        self._gold_enabled = QCheckBox()
        self._gold_enabled.setChecked(current.gold_annotation_enabled)
        self._gold_path = QLineEdit(current.gold_dataset_path)
        self._gold_path.setPlaceholderText(str(Path.home() / "SonoForge-gold"))
        self._gold_path_browse = QPushButton(tr("preferences.gold_browse"))
        self._gold_path_browse.clicked.connect(self._browse_gold_path)
        gold_path_row = QHBoxLayout()
        gold_path_row.addWidget(self._gold_path)
        gold_path_row.addWidget(self._gold_path_browse)
        about_form.addRow(tr("preferences.gold_enabled"), self._gold_enabled)
        about_form.addRow(tr("preferences.gold_path"), gold_path_row)
        self._refs_dir = QLineEdit(current.references_dir)
        self._refs_dir.setPlaceholderText(str(Path.home() / "SonoForge-references"))
        self._refs_dir_browse = QPushButton(tr("references_dir_browse"))
        self._refs_dir_browse.clicked.connect(self._browse_references_dir)
        refs_dir_row = QHBoxLayout()
        refs_dir_row.addWidget(self._refs_dir)
        refs_dir_row.addWidget(self._refs_dir_browse)
        about_form.addRow(tr("preferences.references_dir"), refs_dir_row)
        about_page = _SectionPage(
            tr("settings.section.about"),
            tr("settings.section.about_hint"),
            _scrollable_tab(about_form),
        )
        self._register_page("settings_section_about", about_page)

        # Show only tabs that have capabilities
        self._stack.setCurrentIndex(0)

    def _build_hotkeys_page(self, current: UserPreferences) -> None:
        hotkeys_form = QFormLayout()
        self._shortcut_settings = ShortcutSettingsWidget(current.shortcut_overrides_json)
        hotkeys_form.addRow(self._shortcut_settings)
        self._magnifier_check = QCheckBox()
        magnifier_key = shortcut_label("magnifier_hold")
        self._magnifier_check.setChecked(current.magnifier_enabled)
        self._magnifier_check.setToolTip(tr("preferences.magnifier_hint", shortcut=magnifier_key))
        self._magnifier_linear_persistent = QCheckBox()
        self._magnifier_linear_persistent.setChecked(current.magnifier_linear_persistent)
        self._magnifier_linear_persistent.setToolTip(tr("preferences.magnifier_linear_persistent_hint"))
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
        hotkeys_form.addRow(tr("preferences.magnifier", shortcut=magnifier_key), self._magnifier_check)
        hotkeys_form.addRow(tr("preferences.magnifier_linear_persistent"), self._magnifier_linear_persistent)
        hotkeys_form.addRow(tr("preferences.magnifier_zoom"), self._magnifier_zoom_spin)
        hotkeys_form.addRow(tr("preferences.magnifier_radius"), self._magnifier_radius_spin)
        hotkeys_page = _SectionPage(
            tr("settings.section.hotkeys"),
            tr("settings.section.hotkeys_hint"),
            _scrollable_tab(hotkeys_form),
        )
        self._register_page("settings_section_hotkeys", hotkeys_page)

    def _build_privacy_page(self, current: UserPreferences) -> None:
        privacy_form = QFormLayout()
        self._start_page_patient_data = QCheckBox()
        self._start_page_patient_data.setObjectName("startPagePatientData")
        self._start_page_patient_data.setChecked(current.start_page_show_patient_data)
        self._start_page_patient_data.setEnabled(self._profile_capabilities.recent_studies)
        self._start_page_patient_data.setToolTip(tr("preferences.start_page_patient_data_hint"))
        privacy_form.addRow(tr("preferences.start_page_patient_data"), self._start_page_patient_data)
        privacy_form.addRow(tr("preferences.anonymize_frames"), self._anonymize_frames)
        privacy_form.addRow(tr("preferences.phi_mask_top"), self._phi_mask_top)
        privacy_form.addRow(tr("preferences.phi_text_detector"), self._phi_text_detector)
        privacy_page = _SectionPage(
            tr("settings.section.privacy"),
            tr("settings.section.privacy_hint"),
            _scrollable_tab(privacy_form),
        )
        self._register_page("settings_section_privacy", privacy_page)

    def _build_tools_page(self, current: UserPreferences) -> None:
        # The editor fits the viewport width; only vertical scrolling is needed.
        self._tool_panel_settings = ToolSettings2Widget(
            current.tool_layout_v3_json or tool_layout_v3_from_v2(current.tool_panel_layout_json)
        )
        self._tool_panel_settings.ensure_editable_profile()
        tools_scroll = QScrollArea()
        tools_scroll.setObjectName("settingsFormScroll")
        tools_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        tools_scroll.setWidgetResizable(True)
        tools_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        tools_scroll.setWidget(_wrap_in_card(self._tool_panel_settings))
        tools_page = _SectionPage(
            tr("settings.section.tools"),
            tr("settings.section.tools_hint"),
            tools_scroll,
        )
        self._register_page("settings_section_tools", tools_page)

    def _build_server_page(self, current: UserPreferences) -> None:
        # The Orthanc session cache belongs here, next to the server it caches;
        # it used to live on a separate «Прочее» tab that the mock does not
        # have — every section of that tab moved to the page it belongs to.
        self._server_form = ServerSettingsForm()
        # The shared form keeps its own dense layout for the server dialogs;
        # inside Settings it is dressed like every other row so the page does
        # not switch style halfway down.
        for _form in self._server_form.findChildren(QFormLayout):
            _dress_form(_form)
        # The connection block is the top section of the page: its captions took
        # the whole 240 px column and squeezed the value fields to ~140 px, so
        # the server name and the URL could not be read.  Narrower captions plus
        # growing fields give the values the room (2026-10-25).  The DIMSE group
        # below keeps the shared dressing.
        top_form = self._server_form.layout()
        if isinstance(top_form, QFormLayout):
            top_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            for _row in range(top_form.rowCount()):
                _label_item = top_form.itemAt(_row, QFormLayout.ItemRole.LabelRole)
                _field_item = top_form.itemAt(_row, QFormLayout.ItemRole.FieldRole)
                _caption = _label_item.widget() if _label_item is not None else None
                _field = _field_item.widget() if _field_item is not None else None
                if isinstance(_caption, QWidget):
                    _caption.setMinimumWidth(150)
                    _caption.setMaximumWidth(220)
                    _caption.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
                if isinstance(_field, QLineEdit):
                    _field.setMinimumWidth(320)
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
        self._cache_hint.setObjectName("settingsCacheHint")
        self._cache_hint.setWordWrap(True)

        server_host = QWidget()
        server_host.setObjectName("settingsFormHost")
        server_host_layout = QVBoxLayout(server_host)
        server_host_layout.setContentsMargins(0, 0, 0, 0)
        server_host_layout.setSpacing(8)
        server_host_layout.addWidget(self._server_form, 1)
        cache_form = QFormLayout()
        cache_form.setContentsMargins(0, 8, 0, 0)
        cache_form.addRow(tr("preferences.cache_location"), self._cache_location_label)
        cache_form.addRow(tr("preferences.cache_size"), self._cache_size_label)
        cache_form.addRow(tr("preferences.cache_quota"), self._cache_quota_label)
        cache_form.addRow("", self._cache_clear_button)
        cache_form.addRow("", self._cache_clear_on_exit)
        cache_form.addRow(self._cache_hint)
        _dress_form(cache_form)
        server_host_layout.addLayout(cache_form)
        server_scroll = QScrollArea()
        server_scroll.setObjectName("settingsFormScroll")
        server_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        server_scroll.setWidgetResizable(True)
        server_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        server_scroll.setWidget(_wrap_in_card(server_host))
        server_page = _SectionPage(
            tr("settings.section.server"),
            tr("settings.section.server_hint"),
            server_scroll,
        )
        self._register_page("settings_section_server", server_page)

    def _register_page(self, section_name: str, page: _SectionPage) -> None:
        self._pages[section_name] = page
        self._stack.addWidget(page)

    def _apply_profile_visibility(self) -> None:
        """Show the mock's ten sections; capability gating is per-control.

        Every section stays in the sidebar of every profile: a settings page
        that disappears is a question («где оно?»), not an answer. What a
        profile cannot do is disabled *inside* the page, with the hint that
        says why.
        """

    def _on_section_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is None:
            return
        section = str(current.data(Qt.ItemDataRole.UserRole) or "")
        page = self._pages.get(section)
        if page is None:
            return
        self._stack.setCurrentWidget(page)
        self._current_section = section

    def _on_search_changed(self, text: str) -> None:
        """Jump to the first section whose title or subtitle matches *text*.

        Filtering the rows away would hide settings the physician may still
        need; the mock's field is «Найти параметр», so it navigates. The first
        match is opened, the rest stays visible, and an empty query restores
        the row the dialog was on.
        """
        query = text.strip().casefold()
        if not query:
            return
        for index in range(self._section_list.count()):
            item = self._section_list.item(index)
            if item is None:
                continue
            section = str(item.data(Qt.ItemDataRole.UserRole) or "")
            page = self._pages.get(section)
            haystack = item.text().casefold()
            if page is not None:
                for label in page.findChildren(QLabel):
                    haystack += " " + label.text().casefold()
            if query in haystack:
                self._section_list.setCurrentItem(item)
                return

    def _reset_current_section(self) -> None:
        """Put the visible section back to its defaults, leaving the rest as is.

        «Сбросить раздел» is per-section in the mock; a no-op button would be a
        lie, and resetting *all* sections would be worse. The fields owned by
        each page are listed in :data:`_SECTION_FIELDS`, so the reset rebuilds
        every page from «defaults for this section, the screen for the rest».
        Nothing is saved until «Готово»: the reset is an edit of the form.
        """
        section = self._current_section
        fields = _SECTION_FIELDS.get(section, ())
        if not fields:
            return
        confirm = QMessageBox.question(
            self,
            tr("settings.reset_section"),
            tr("settings.reset_section_confirm"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        defaults = default_user_preferences()
        current = self._collect_preferences(load_user_preferences())
        merged = replace(current, **{name: getattr(defaults, name) for name in fields})
        self._rebuild_pages(merged)

    def _rebuild_pages(self, current: UserPreferences) -> None:
        """Tear the stack down and build every page again from *current*."""
        for page in self._pages.values():
            self._stack.removeWidget(page)
            page.setParent(None)
            page.deleteLater()
        self._pages.clear()
        self._page_widgets.clear()
        self._build_pages(current)
        target = self._current_section
        for index in range(self._section_list.count()):
            item = self._section_list.item(index)
            if item is not None and str(item.data(Qt.ItemDataRole.UserRole) or "") == target:
                self._section_list.setCurrentItem(item)
                self._on_section_changed(item, None)
                break

    # ── format / cache / persistence helpers ───────────────────────

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
        defaults.last_session_source = stored.last_session_source
        defaults.measurement_persistence_enabled = default_measurement_persistence_enabled()
        save_user_preferences(defaults)
        if self._on_apply is not None:
            self._on_apply(defaults)
        self.accept()

    def _report_problem(self) -> None:
        """Open the "report a problem" dialog (Q-13) without touching settings."""
        from echo_personal_tool.presentation.feedback_dialog import show_support_feedback_dialog

        show_support_feedback_dialog(self)

    def _save_diagnostics(self) -> None:
        """Write a privacy-filtered diagnostic archive (moved from the top bar)."""
        import logging
        from datetime import datetime

        from echo_personal_tool.infrastructure.diagnostics import create_diagnostic_bundle
        from echo_personal_tool.infrastructure.safe_diagnostics import (
            log_boundary_failure,
            safe_error_category,
        )
        from echo_personal_tool.presentation.styled_dialogs import styled_save_file

        logger = logging.getLogger(__name__)
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

    def _browse_gold_path(self) -> None:
        from echo_personal_tool.presentation.styled_dialogs import styled_select_directory

        path = styled_select_directory(
            self,
            tr("preferences.gold_browse_title"),
            self._gold_path.text() or str(Path.home()),
            remember=False,
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
        error = self._shortcut_settings.validation_error()
        if error:
            self._section_list.setCurrentRow(7)
            QMessageBox.warning(self, tr("settings.shortcut_conflict"), error)
            return
        stored = load_user_preferences()
        preferences = self._collect_preferences(stored)
        scale_changed = normalize_ui_scale(stored.ui_scale_percent) != preferences.ui_scale_percent
        save_user_preferences(preferences)
        save_server_settings(self._server_form.settings())
        if self._on_apply is not None:
            # Strip QGraphicsOpacityEffect overlays (ButtonFeedback) before
            # the app-wide stylesheet swap.  A live effect + setStyleSheet is
            # a documented SIGSEGV path on native platforms (dark_theme.py).
            # The dialog is about to close; the overlays are not needed after.
            for w in self.findChildren(QWidget):
                if w.graphicsEffect() is not None:
                    w.setGraphicsEffect(None)
            self._on_apply(preferences)
        if scale_changed:
            QTimer.singleShot(0, self._prompt_ui_scale_restart)
        self.accept()

    def _collect_preferences(self, stored: UserPreferences) -> UserPreferences:
        """Read every control of every page into one :class:`UserPreferences`.

        Split out of :meth:`_on_accept` so «Сбросить раздел» can rebuild the
        form from the values the physician has *not* touched yet.
        """
        return replace(
            stored,
            tabs_enabled=self._tabs_enabled.isChecked(),
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
            wl_window=stored.wl_window,
            wl_level=stored.wl_level,
            wl_dr=stored.wl_dr,
            show_crosshair=self._show_crosshair.isChecked(),
            magnifier_enabled=self._magnifier_check.isChecked(),
            magnifier_zoom=float(self._magnifier_zoom_spin.value()),
            magnifier_radius_px=int(self._magnifier_radius_spin.value()),
            magnifier_linear_persistent=self._magnifier_linear_persistent.isChecked(),
            show_panel_frames=self._show_panel_frames.isChecked(),
            show_caliper_labels_on_frame=self._show_caliper_labels.isChecked(),
            show_caliper_inline_labels=self._show_caliper_inline_labels.isChecked(),
            show_doppler_calibration_roi=self._show_doppler_cal_roi.isChecked(),
            anonymize_frames=self._anonymize_frames.isChecked(),
            start_page_show_patient_data=self._start_page_patient_data.isChecked(),
            shortcut_overrides_json=self._shortcut_settings.encoded_overrides(),
            phi_mask_top_percent=float(self._phi_mask_top.currentData()),
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
            accent_palette=str(self._accent_palette_combo.currentData()),
            language=str(self._language_combo.currentData()),
            reduce_motion=self._reduce_motion.isChecked(),
            native_window_frame=self._native_window_frame.isChecked(),
            gold_annotation_enabled=self._gold_enabled.isChecked(),
            gold_dataset_path=self._gold_path.text().strip(),
            references_dir=self._refs_dir.text().strip(),
            show_strain=self._show_strain.isChecked(),
            show_la_auto=self._show_la_auto.isChecked(),
            tool_panel_v2=self._tool_panel_v2.isChecked(),
            panel_width=stored.panel_width,
            label_picker_enabled=self._label_picker_enabled.isChecked(),
            despeckle_enabled=stored.despeckle_enabled,
            tool_panel_layout_json=stored.tool_panel_layout_json,
            tool_layout_v3_json=self._tool_panel_settings.encoded_layout(),
            auto_play=stored.auto_play,
            playback_max_cache_mb=stored.playback_max_cache_mb,
            layout_state_json=stored.layout_state_json,
            layout_state_v2_json=self._layout_section.document().to_json(),
            presenter_screen=stored.presenter_screen,
            presenter_visual_preset=stored.presenter_visual_preset,
            presenter_pointer=stored.presenter_pointer,
        )

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
            # Only the custom title bar moves the frameless dialog.  Presses on
            # a page (labels, empty gaps, group boxes) reach this handler too,
            # which used to drag the window from anywhere but the sidebar.
            title_bar = getattr(self, "_title_bar", None)
            if title_bar is not None and title_bar.geometry().contains(event.position().toPoint()):
                self._drag_pos = event.globalPosition().toPoint() - self.pos()
                return
        self._drag_pos = None

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        self._drag_pos = None

    def showEvent(self, event) -> None:  # noqa: ANN001
        super().showEvent(event)

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
