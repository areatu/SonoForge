"""Study browser shown in the viewer area before a study is loaded (UI-7).

The empty tab hosts the A2 «Рабочая станция» browser of the redesign spec
(§4.10): a header with search, a period segment and the primary actions; a
sidebar with sources, quick filters, recent places, links and the profile
block; the studies table in the centre; and the selected study's facts on
the right.  Rows come from the same identifier-free summaries the welcome
page (Э5) already had — the current run's history and the saved-measurement
records (N-01/S-09) — so the columns are description, date, clips, saved
measurements, draft status and source.  Clip thumbnails and protocol
progress from the round-1 mockup would need the study loaded, so the detail
panel shows the summary facts instead of inventing them.

Filtering, counters and the status classification live in the Qt-free
:mod:`.study_browser`; this module only renders them.  Single click selects
a row (and fills the detail panel), Enter / double-click / «Открыть
исследование» opens it; recent places keep their click-to-open.  A folder
dropped anywhere on the page opens through ``recent_folder_requested``.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, QSize, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.application.recent_folders import (
    RecentFolderEntry,
    RecentFolderStore,
    make_recent_folder_store,
)
from echo_personal_tool.infrastructure.i18n import tr, tr_plural
from echo_personal_tool.infrastructure.profile import ProfileCapabilities, capabilities_for
from echo_personal_tool.infrastructure.profile import profile as active_profile
from echo_personal_tool.keyboard_shortcuts import append_shortcut_hint
from echo_personal_tool.presentation.dark_theme import get_theme_tokens
from echo_personal_tool.presentation.study_browser import (
    PERIODS,
    STATUS_DRAFT,
    STATUS_NEW,
    STATUS_UNAVAILABLE,
    RecentStudySummary,
    display_title,
    filter_summaries,
    study_status,
)

MAX_START_PAGE_RECENT_PLACES = 8

__all__ = ["MAX_START_PAGE_RECENT_PLACES", "RecentStudySummary", "StartPage"]

#: Table columns, left to right (redesign spec §4.10).
_COL_STUDY, _COL_DATE, _COL_CLIPS, _COL_MEASUREMENTS, _COL_STATUS, _COL_SOURCE = range(6)


class StartPage(QWidget):
    """A2 study browser: the content of an empty viewer/tab."""

    open_folder_requested = Signal()
    load_from_server_requested = Signal()
    continue_requested = Signal()
    recent_folder_requested = Signal(str)
    recent_study_requested = Signal(object)
    references_requested = Signal()
    documents_requested = Signal()
    feedback_requested = Signal()
    settings_requested = Signal()
    help_requested = Signal()
    theme_changed = Signal(str)
    language_changed = Signal(str)

    _THEMES = (
        ("preferences.theme_dark", "dark"),
        ("preferences.theme_light", "light"),
        ("preferences.theme_system", "system"),
        ("preferences.theme_vscode_dark", "vscode_dark"),
        ("preferences.theme_vscode_light", "vscode_light"),
        ("preferences.theme_graphite", "graphite"),
    )
    _LANGUAGES = (
        ("preferences.lang_ru", "ru"),
        ("preferences.lang_en", "en"),
    )
    _PERIOD_KEYS = {
        "all": "start_page.period_all",
        "today": "start_page.period_today",
        "7d": "start_page.period_week",
        "30d": "start_page.period_month",
    }
    _DETAIL_ROWS = ("date", "source", "folder", "clips", "measurements", "status")
    _DETAIL_CAPTIONS = {
        "date": "start_page.detail_date",
        "source": "start_page.detail_source",
        "folder": "start_page.detail_folder",
        "clips": "start_page.detail_clips",
        "measurements": "start_page.detail_measurements",
        "status": "start_page.detail_status",
    }

    def __init__(
        self,
        *,
        recent_store: RecentFolderStore | None = None,
        version: str = "",
        profile_name: str | None = None,
        profile_capabilities: ProfileCapabilities | None = None,
        measurement_persistence_enabled: bool = False,
        ui_font_size: int = 13,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("startPage")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAcceptDrops(True)
        self._profile_name = profile_name or active_profile()
        self._profile_capabilities = profile_capabilities or capabilities_for(self._profile_name)
        self._recent_store = recent_store or make_recent_folder_store(enabled=self._profile_capabilities.recent_folders)
        self._version = version
        self._measurement_persistence_enabled = bool(
            measurement_persistence_enabled and self._profile_capabilities.measurement_storage
        )
        self._ui_font_size = max(10, int(ui_font_size))
        self._recent_studies: list[RecentStudySummary] = []
        self._visible_studies: list[RecentStudySummary] = []
        self._continue_source = ""
        self._continue_folder = ""

        self._show_private_sections = self._profile_capabilities.extended_start_page

        self._continue_date = ""
        self._continue_clip_count = 0
        self._show_private_sections = profile_name != "presenter"

        # The header's date segment is the one narrowing control that stayed:
        # it filters by study date, needs no sidebar column and is part of the
        # A2 header in the mock. Everything else narrowed through the sidebar
        # block that was removed.
        self._browser_period = PERIODS[0]

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())
        body = QSplitter(Qt.Orientation.Horizontal)
        body.setObjectName("startPageBodySplitter")
        body.setChildrenCollapsible(False)
        body.addWidget(self._build_sidebar())
        body.addWidget(self._build_center())
        body.addWidget(self._build_detail_panel())
        body.setStretchFactor(1, 1)
        body.setSizes([240, 940, 300])
        root.addWidget(body, 1)

        self.open_folder_button.clicked.connect(lambda: self.open_folder_requested.emit())
        self.load_server_button.clicked.connect(lambda: self.load_from_server_requested.emit())
        self.continue_button.clicked.connect(lambda: self.continue_requested.emit())
        self.references_button.clicked.connect(lambda: self.references_requested.emit())
        self.documents_button.clicked.connect(lambda: self.documents_requested.emit())
        self.feedback_button.clicked.connect(lambda: self.feedback_requested.emit())
        self.settings_button.clicked.connect(lambda: self.settings_requested.emit())
        self.help_button.clicked.connect(lambda: self.help_requested.emit())
        self.open_study_button.clicked.connect(self._open_selected_study)
        self._search_edit.textChanged.connect(lambda _text: self._refresh_browser())
        self._period_group.idClicked.connect(self._on_period_clicked)
        self._studies_table.itemSelectionChanged.connect(self._update_detail)
        self._studies_table.itemActivated.connect(self._on_study_activated)

        self._apply_profile_visibility()
        self.reload_text()
        self.refresh_recent_places()
        self.set_recent_studies(())
        self.set_continue_target("", "")
        self.set_measurement_persistence_enabled(self._measurement_persistence_enabled)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt override
        """Keep the browser from pinning the main window's minimum width.

        The page shares the centre slot with the gallery and the tool
        panel, and the window must still shrink to a 1366 px physical
        display (911 logical px at 150 % DPI — the UI-2 gallery compacting
        keys off the physical width).  The natural width of header +
        sidebar + detail panel would forbid that, so below it the panes
        squeeze to their explicit floors instead.
        """
        return QSize(430, 340)

    # ── construction ───────────────────────────────────────────────────

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("startPageBrowserHeader")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(10)

        self._title = QLabel()
        self._title.setObjectName("startPageTitle")
        self._title.setMinimumWidth(48)
        layout.addWidget(self._title)

        self._search_edit = QLineEdit()
        self._search_edit.setObjectName("startPageStudySearch")
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.setMinimumWidth(64)
        layout.addWidget(self._search_edit, 1)

        self._period_group = QButtonGroup(self)
        self._period_group.setExclusive(True)
        self._period_buttons: list[QPushButton] = []
        period_host = QWidget()
        period_host.setObjectName("startPagePeriodGroup")
        period_layout = QHBoxLayout(period_host)
        period_layout.setContentsMargins(0, 0, 0, 0)
        period_layout.setSpacing(4)
        for index, period in enumerate(PERIODS):
            button = QPushButton()
            button.setObjectName(f"startPagePeriod{period.capitalize()}")
            button.setProperty("startPageRole", "segment")
            button.setMinimumWidth(30)
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self._period_group.addButton(button, index)
            self._period_buttons.append(button)
            period_layout.addWidget(button)
        self._period_buttons[0].setChecked(True)
        layout.addWidget(period_host)

        # «Продолжить» lives at the top of the sidebar, not here: the A2
        # header holds the two open actions, and the long continue label
        # (Э5 §7.1) would otherwise pin the header's minimum width.
        self.open_folder_button = self._button("startPageOpenFolder", primary=True)
        self.load_server_button = self._button("startPageLoadServer")
        for button in (self.open_folder_button, self.load_server_button):
            button.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            button.setMinimumWidth(72)
            layout.addWidget(button)
        return header

    def _build_sidebar(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName("startPageSidebar")
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(140)

        host = QWidget()
        host.setObjectName("startPageSidebarHost")
        host.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(host)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.continue_button = self._button("startPageContinue")
        layout.addWidget(self.continue_button)

        self._places_card = QWidget()
        self._places_card.setObjectName("startPageRecentPlaces")
        places_layout = QVBoxLayout(self._places_card)
        places_layout.setContentsMargins(0, 0, 0, 0)
        places_layout.setSpacing(6)
        self._places_title = self._section_title()
        self._places_empty = QLabel()
        self._places_empty.setObjectName("startPageRecentPlacesEmpty")
        self._places_empty.setWordWrap(True)
        self._places_list = QListWidget()
        self._places_list.setObjectName("startPageRecentPlacesList")
        self._places_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._places_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._places_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._places_list.itemClicked.connect(self._on_recent_place_clicked)
        places_layout.addWidget(self._places_title)
        places_layout.addWidget(self._places_empty)
        places_layout.addWidget(self._places_list)
        layout.addWidget(self._places_card)

        self._links_card = QWidget()
        self._links_card.setObjectName("startPageLinks")
        links_layout = QVBoxLayout(self._links_card)
        links_layout.setContentsMargins(0, 0, 0, 0)
        links_layout.setSpacing(6)
        self._links_title = self._section_title()
        links_layout.addWidget(self._links_title)
        self.references_button = self._button("startPageReferences", link=True)
        self.documents_button = self._button("startPageDocuments", link=True)
        self.feedback_button = self._button("startPageFeedback", link=True)
        self.settings_button = self._button("startPageSettings", link=True)
        self.help_button = self._button("startPageHelp", link=True)
        for button in (
            self.references_button,
            self.documents_button,
            self.feedback_button,
            self.settings_button,
            self.help_button,
        ):
            links_layout.addWidget(button)
        layout.addWidget(self._links_card)

        self._theme_combo = QComboBox()
        self._theme_combo.setObjectName("startPageThemeCombo")
        for key, value in self._THEMES:
            self._theme_combo.addItem(tr(key), value)
        self._theme_combo.currentIndexChanged.connect(self._emit_theme)
        self._language_combo = QComboBox()
        self._language_combo.setObjectName("startPageLangCombo")
        for key, value in self._LANGUAGES:
            self._language_combo.addItem(tr(key), value)
        self._language_combo.currentIndexChanged.connect(self._emit_language)
        layout.addWidget(self._theme_combo)
        layout.addWidget(self._language_combo)

        self._footer = QLabel()
        self._footer.setObjectName("startPageStatus")
        self._footer.setWordWrap(True)
        layout.addWidget(self._footer)
        layout.addStretch(1)

        scroll.setWidget(host)
        self._sidebar = scroll
        return scroll

    def _build_center(self) -> QWidget:
        center = QWidget()
        center.setObjectName("startPageContent")
        center.setMinimumWidth(180)
        layout = QVBoxLayout(center)
        layout.setContentsMargins(0, 0, 0, 0)
        self._content = center

        self._subtitle = QLabel()
        self._subtitle.setObjectName("startPageSubtitle")
        self._subtitle.setWordWrap(True)
        self._subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._subtitle, 1)

        self._studies_card = QFrame()
        self._studies_card.setObjectName("startPageCard")
        studies_layout = QVBoxLayout(self._studies_card)
        studies_layout.setContentsMargins(12, 10, 12, 10)
        studies_layout.setSpacing(8)

        self._studies_table = QTableWidget(0, 6)
        self._studies_table.setObjectName("startPageStudiesTable")
        self._studies_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._studies_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._studies_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._studies_table.setShowGrid(False)
        self._studies_table.verticalHeader().setVisible(False)
        header = self._studies_table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setSectionResizeMode(_COL_STUDY, QHeaderView.ResizeMode.Stretch)
        for column in (_COL_DATE, _COL_CLIPS, _COL_MEASUREMENTS, _COL_STATUS, _COL_SOURCE):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        studies_layout.addWidget(self._studies_table, 1)

        self._studies_empty = QLabel()
        self._studies_empty.setObjectName("startPageRecentStudiesEmpty")
        self._studies_empty.setWordWrap(True)
        self._studies_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        studies_layout.addWidget(self._studies_empty, 1)

        self._no_results = QWidget()
        self._no_results.setObjectName("startPageNoResults")
        no_results_layout = QVBoxLayout(self._no_results)
        no_results_layout.setContentsMargins(0, 24, 0, 24)
        no_results_layout.setSpacing(10)
        self._no_results_label = QLabel()
        self._no_results_label.setObjectName("startPageNoResultsLabel")
        self._no_results_label.setWordWrap(True)
        self._no_results_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        no_results_layout.addStretch(1)
        no_results_layout.addWidget(self._no_results_label)
        no_results_layout.addStretch(1)
        studies_layout.addWidget(self._no_results, 1)

        self._shown_label = QLabel()
        self._shown_label.setObjectName("startPageStudiesCount")
        studies_layout.addWidget(self._shown_label)
        layout.addWidget(self._studies_card, 1)
        return center

    def _build_detail_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("startPageDetailPanel")
        panel.setMinimumWidth(170)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        self._detail_title = QLabel()
        self._detail_title.setObjectName("startPageDetailTitle")
        self._detail_title.setWordWrap(True)
        layout.addWidget(self._detail_title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)
        self._detail_captions: dict[str, QLabel] = {}
        self._detail_values: dict[str, QLabel] = {}
        for row, field in enumerate(self._DETAIL_ROWS):
            caption = QLabel()
            caption.setProperty("startPageRole", "detailCaption")
            value = QLabel()
            value.setObjectName(f"startPageDetail{field.capitalize()}")
            value.setWordWrap(True)
            self._detail_captions[field] = caption
            self._detail_values[field] = value
            grid.addWidget(caption, row, 0)
            grid.addWidget(value, row, 1)
        layout.addLayout(grid)

        self._detail_note = QLabel()
        self._detail_note.setObjectName("startPageDetailNote")
        self._detail_note.setWordWrap(True)
        layout.addWidget(self._detail_note)
        layout.addStretch(1)

        self.open_study_button = self._button("startPageOpenStudy", primary=True)
        layout.addWidget(self.open_study_button)
        self._detail_hint = QLabel()
        self._detail_hint.setObjectName("startPageDetailHint")
        self._detail_hint.setWordWrap(True)
        layout.addWidget(self._detail_hint)

        self._detail_panel = panel
        return panel

    @staticmethod
    def _section_title() -> QLabel:
        title = QLabel()
        title.setObjectName("startPageSectionTitle")
        title.setProperty("startPageRole", "sectionTitle")
        return title

    @staticmethod
    def _button(object_name: str, *, primary: bool = False, link: bool = False) -> QPushButton:
        button = QPushButton()
        button.setObjectName(object_name)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setMinimumHeight(max(40, button.fontMetrics().lineSpacing() + 20))
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        if primary:
            button.setProperty("startPageRole", "primary")
        elif link:
            button.setProperty("startPageRole", "link")
        else:
            button.setProperty("startPageRole", "secondary")
        return button

    def _apply_profile_visibility(self) -> None:
        caps = self._profile_capabilities
        self._places_card.setVisible(caps.recent_folders)
        self._studies_card.setVisible(caps.recent_studies)
        self._detail_panel.setVisible(caps.recent_studies)
        self._subtitle.setVisible(not caps.recent_studies)
        self._search_edit.setVisible(caps.recent_studies)
        for button in self._period_buttons:
            button.setVisible(caps.recent_studies)
        self.references_button.setVisible(caps.reference_ui)
        self.documents_button.setVisible(self._show_private_sections)
        self.feedback_button.setVisible(self._show_private_sections)
        self.settings_button.setVisible(self._show_private_sections)
        self.continue_button.setVisible(caps.continue_last_session)
        self.load_server_button.setVisible(caps.server_dialog)

    # ── public API (unchanged Э5 contract) ─────────────────────────────

    def _emit_theme(self) -> None:
        self.theme_changed.emit(str(self._theme_combo.currentData()))

    def _emit_language(self) -> None:
        self.language_changed.emit(str(self._language_combo.currentData()))

    def set_theme(self, theme: str) -> None:
        index = self._theme_combo.findData(theme)
        if index >= 0:
            with QSignalBlocker(self._theme_combo):
                self._theme_combo.setCurrentIndex(index)

    def set_language(self, language: str) -> None:
        index = self._language_combo.findData(language)
        if index >= 0:
            with QSignalBlocker(self._language_combo):
                self._language_combo.setCurrentIndex(index)

    def reload_text(self) -> None:
        """Refresh visible strings after the active UI language changes."""
        self._title.setText(tr("start_page.browser_title"))
        self._subtitle.setText(tr("start_page.subtitle"))
        self._search_edit.setPlaceholderText(tr("start_page.search_placeholder"))
        self._search_edit.setToolTip(append_shortcut_hint(tr("start_page.search_tip"), "start_page_search"))
        for index, period in enumerate(PERIODS):
            self._period_buttons[index].setText(tr(self._PERIOD_KEYS[period]))
        self.open_folder_button.setText(tr("start_page.open_folder"))
        self.open_folder_button.setToolTip(append_shortcut_hint(tr("start_page.open_folder_tip"), "open_folder"))
        self.load_server_button.setText(tr("start_page.load_server"))
        self.load_server_button.setToolTip(append_shortcut_hint(tr("start_page.load_server_tip"), "load_server"))
        self._places_title.setText(tr("start_page.recent_places"))
        self._places_empty.setText(tr("start_page.recent_places_empty"))
        self._studies_empty.setText(tr("start_page.recent_studies_empty") + "\n" + tr("start_page.drop_hint"))
        self._no_results_label.setText(tr("start_page.no_results"))
        self._links_title.setText(tr("start_page.links"))
        self.references_button.setText(tr("start_page.references"))
        self.documents_button.setText(tr("start_page.documents"))
        self.feedback_button.setText(tr("start_page.feedback"))
        self.settings_button.setText(tr("start_page.settings"))
        self.help_button.setText(tr("start_page.help"))
        self._studies_table.setHorizontalHeaderLabels(
            [
                tr("start_page.col_study"),
                tr("start_page.col_date"),
                tr("start_page.col_clips"),
                tr("start_page.col_measurements"),
                tr("start_page.col_status"),
                tr("start_page.col_source"),
            ]
        )
        for field, key in self._DETAIL_CAPTIONS.items():
            self._detail_captions[field].setText(tr(key))
        self.open_study_button.setText(tr("start_page.detail_open"))
        self._detail_hint.setText(tr("start_page.detail_hint"))
        for combo, options in (
            (self._theme_combo, self._THEMES),
            (self._language_combo, self._LANGUAGES),
        ):
            for index, (key, _value) in enumerate(options):
                combo.setItemText(index, tr(key))
        self.refresh_recent_places()
        self.set_recent_studies(self._recent_studies)
        self._refresh_continue_button()
        self._refresh_footer()
        self._apply_theme()

    def refresh_recent_places(self, entries: Iterable[RecentFolderEntry] | None = None) -> None:
        """Re-read and display up to eight places, with missing folders greyed out."""
        folders = (
            list(entries if entries is not None else self._recent_store.entries())
            if self._profile_capabilities.recent_folders
            else []
        )
        folders = folders[:MAX_START_PAGE_RECENT_PLACES]
        self._places_list.clear()
        self._places_empty.setVisible(not folders)
        self._places_list.setVisible(bool(folders))
        row_height = max(38, self._places_list.fontMetrics().lineSpacing() + 18)
        for folder in folders:
            path = Path(folder.path)
            label = path.name or folder.path
            prefix = "★  " if folder.pinned else ""
            item = QListWidgetItem(prefix + label)
            item.setData(Qt.ItemDataRole.UserRole, folder.path)
            item.setSizeHint(QSize(0, row_height))
            if not folder.exists:
                item.setForeground(QColor(get_theme_tokens()["text.2"]))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self._places_list.addItem(item)
        self._places_list.setMaximumHeight(max(row_height + 4, row_height * len(folders) + 4))

    def set_recent_studies(self, studies: Iterable[RecentStudySummary]) -> None:
        """Show current-run study summaries; callers must omit patient identifiers."""
        self._recent_studies = list(studies) if self._profile_capabilities.recent_studies else []
        self._refresh_browser()

    def set_continue_target(
        self,
        source: str,
        folder: str = "",
        *,
        date: str = "",
        clip_count: int = 0,
    ) -> None:
        """Update the Continue action from the persisted last-session source.

        The label follows Э5 §7.1 — «Продолжить: <папка или сервер · дата ·
        число клипов>» — with the date and clip count the caller recorded for
        that session; unknown parts are omitted (no patient data, N-01).
        Presenter builds never resume a last session: the target stays empty.
        """
        if self._profile_capabilities.continue_last_session:
            self._continue_source = source if source in {"folder", "server"} else ""
            self._continue_folder = folder
            self._continue_date = date
            self._continue_clip_count = int(clip_count or 0)
        else:
            self._continue_source = ""
            self._continue_folder = ""
            self._continue_date = ""
            self._continue_clip_count = 0
        self._refresh_continue_button()

    def set_measurement_persistence_enabled(self, enabled: bool) -> None:
        self._measurement_persistence_enabled = bool(enabled and self._profile_capabilities.measurement_storage)
        self._refresh_footer()

    def set_ui_font_size(self, font_size: int) -> None:
        self._ui_font_size = max(10, int(font_size))

    def focus_search(self) -> None:
        """Put keyboard focus into the study search field (Ctrl+F target)."""
        if not self._profile_capabilities.recent_studies:
            return
        self._search_edit.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self._search_edit.selectAll()

    def refresh_theme(self) -> None:
        """Apply the active clinical palette without rebuilding the page."""
        self._apply_theme()
        for button in (
            self.open_folder_button,
            self.load_server_button,
            self.continue_button,
            self.open_study_button,
            self.references_button,
            self.documents_button,
            self.feedback_button,
            self.settings_button,
            self.help_button,
        ):
            button.setMinimumHeight(max(40, button.fontMetrics().lineSpacing() + 20))
        self.refresh_recent_places()
        self.set_recent_studies(self._recent_studies)

    # ── browser rendering ──────────────────────────────────────────────

    def _refresh_browser(self) -> None:
        selected_key = ""
        current = self._selected_summary()
        if current is not None:
            selected_key = current.key
        self._visible_studies = filter_summaries(
            self._recent_studies,
            query=self._search_edit.text(),
            period=self._browser_period,
        )
        self._rebuild_table(selected_key)
        has_studies = bool(self._recent_studies)
        has_rows = bool(self._visible_studies)
        self._studies_table.setVisible(has_rows)
        self._studies_empty.setVisible(not has_studies)
        self._no_results.setVisible(has_studies and not has_rows)
        self._shown_label.setText(
            tr("start_page.shown_count", shown=len(self._visible_studies), total=len(self._recent_studies))
        )
        self._update_detail()

    def _rebuild_table(self, selected_key: str) -> None:
        table = self._studies_table
        tokens = get_theme_tokens()
        row_height = max(36, table.fontMetrics().lineSpacing() + 16)
        selected_row = -1
        with QSignalBlocker(table):
            table.setRowCount(len(self._visible_studies))
            for row, summary in enumerate(self._visible_studies):
                if summary.key == selected_key:
                    selected_row = row
                table.setRowHeight(row, row_height)
                for column, item in enumerate(self._row_items(summary, tokens)):
                    table.setItem(row, column, item)
        if self._visible_studies:
            table.setCurrentCell(selected_row if selected_row >= 0 else 0, 0)

    def _row_items(self, summary: RecentStudySummary, tokens: dict[str, str]) -> list[QTableWidgetItem]:
        kind = study_status(summary)
        dim = QColor(tokens["text.3"])
        study = QTableWidgetItem(display_title(summary))
        study.setData(Qt.ItemDataRole.UserRole, summary)
        study.setToolTip(summary.title)
        date_item = QTableWidgetItem(summary.study_date or "—")
        clips = QTableWidgetItem(str(summary.clip_count) if summary.clip_count > 0 else "—")
        clips.setTextAlignment(int(Qt.AlignmentFlag.AlignCenter))
        measurements = QTableWidgetItem(str(summary.measurement_count) if summary.measurement_count > 0 else "—")
        measurements.setTextAlignment(int(Qt.AlignmentFlag.AlignCenter))
        status = QTableWidgetItem(self._status_text(summary, kind))
        status.setForeground(QColor(self._status_token(tokens, kind)))
        source = QTableWidgetItem(self._source_text(summary))
        items = [study, date_item, clips, measurements, status, source]
        for item in items:
            item.setFlags(
                (item.flags() | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable) & ~Qt.ItemFlag.ItemIsEditable
            )
        if kind == STATUS_UNAVAILABLE:
            for item in (study, date_item, clips, measurements, source):
                item.setForeground(dim)
        return items

    @staticmethod
    def _status_token(tokens: dict[str, str], kind: str) -> str:
        if kind == STATUS_DRAFT:
            return tokens["state.warn"]
        if kind == STATUS_NEW:
            return tokens["state.info"]
        return tokens["text.3"]

    @staticmethod
    def _status_text(summary: RecentStudySummary, kind: str) -> str:
        if kind == STATUS_DRAFT:
            count = tr_plural("start_page.recent_studies_measurements", summary.measurement_count)
            return f"● {count} · {tr('start_page.status_draft')}"
        if kind == STATUS_NEW:
            return f"● {tr('start_page.status_new')}"
        return f"● {tr('start_page.status_unavailable')}"

    @staticmethod
    def _source_text(summary: RecentStudySummary) -> str:
        if summary.origin == "folder":
            return Path(summary.folder).name if summary.folder else tr("start_page.origin_folder")
        if summary.origin == "server":
            return tr("start_page.origin_server")
        if summary.origin == "stored":
            return tr("start_page.origin_stored")
        return "—"

    def _selected_summary(self) -> RecentStudySummary | None:
        row = self._studies_table.currentRow()
        if 0 <= row < len(self._visible_studies):
            return self._visible_studies[row]
        return None

    def _update_detail(self) -> None:
        summary = self._selected_summary()
        if summary is None:
            self._detail_title.setText(tr("start_page.detail_empty"))
            for value in self._detail_values.values():
                value.setText("—")
            self._detail_note.setText("")
            self.open_study_button.setEnabled(False)
            return
        kind = study_status(summary)
        self._detail_title.setText(display_title(summary))
        self._detail_values["date"].setText(summary.study_date or "—")
        self._detail_values["source"].setText(self._source_text(summary))
        folder_name = Path(summary.folder).name if summary.folder else "—"
        self._detail_values["folder"].setText(folder_name)
        self._detail_values["clips"].setText(str(summary.clip_count) if summary.clip_count > 0 else "—")
        self._detail_values["measurements"].setText(
            str(summary.measurement_count) if summary.measurement_count > 0 else "—"
        )
        status_value = self._detail_values["status"]
        status_value.setText(self._status_text(summary, kind))
        # A palette colour would lose against the page stylesheet cascade on
        # the next polish; the label carries its token colour itself and this
        # method re-runs on every theme refresh.
        status_value.setStyleSheet(f"color: {self._status_token(get_theme_tokens(), kind)};")
        self._detail_note.setText(self._detail_note_text(summary))
        self.open_study_button.setEnabled(bool(summary.available))

    @staticmethod
    def _detail_note_text(summary: RecentStudySummary) -> str:
        if summary.available:
            return summary.details
        if summary.origin == "stored":
            return summary.details or tr("start_page.recent_study_unavailable_tip")
        if summary.origin == "folder":
            return tr("start_page.recent_study_missing")
        return summary.details

    # ── browser interactions ───────────────────────────────────────────

    def _on_period_clicked(self, index: int) -> None:
        if 0 <= index < len(PERIODS):
            self._browser_period = PERIODS[index]
            self._refresh_browser()

    def _on_study_activated(self, item: QTableWidgetItem) -> None:
        row = self._studies_table.row(item)
        if 0 <= row < len(self._visible_studies):
            self._open_summary(self._visible_studies[row])

    def _open_selected_study(self) -> None:
        summary = self._selected_summary()
        if summary is not None:
            self._open_summary(summary)

    def _open_summary(self, summary: RecentStudySummary) -> None:
        if summary.available:
            self.recent_study_requested.emit(summary)

    def _on_recent_place_clicked(self, item: QListWidgetItem) -> None:
        if item.flags() & Qt.ItemFlag.ItemIsEnabled:
            path = item.data(Qt.ItemDataRole.UserRole)
            if path:
                self.recent_folder_requested.emit(str(path))

    # ── drag and drop (spec §4.10: «перетаскивание папки») ────────────

    @staticmethod
    def _dropped_folder(mime) -> str:  # noqa: ANN001 - QMimeData, kept loose for tests
        """First local folder in a drop; a dropped file opens its parent."""
        if mime is None or not mime.hasUrls():
            return ""
        for url in mime.urls():
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            try:
                if path.is_dir():
                    return str(path)
                if path.is_file():
                    return str(path.parent)
            except OSError:
                continue
        return ""

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._dropped_folder(event.mimeData()):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._dropped_folder(event.mimeData()):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt override
        folder = self._dropped_folder(event.mimeData())
        if folder:
            event.acceptProposedAction()
            self.recent_folder_requested.emit(folder)
        else:
            super().dropEvent(event)

    # ── continue / footer ──────────────────────────────────────────────

    def _continue_target_label(self, name: str) -> str:
        """«<папка или сервер · дата · число клипов>» (Э5 §7.1); unknown parts omitted."""
        parts = [name]
        if self._continue_date:
            parts.append(self._continue_date)
        if self._continue_clip_count > 0:
            parts.append(tr_plural("start_page.recent_studies_clips", self._continue_clip_count))
        return " · ".join(parts)

    def _refresh_continue_button(self) -> None:
        if self._continue_source == "server":
            target = self._continue_target_label(tr("start_page.session_server"))
            self.continue_button.setText(tr("start_page.continue", target=target))
            self.continue_button.setToolTip(tr("start_page.continue_server_tip"))
            self.continue_button.setEnabled(True)
        elif self._continue_source == "folder" and self._continue_folder:
            folder = Path(self._continue_folder)
            name = folder.name or self._continue_folder
            exists = folder.is_dir()
            key = "start_page.continue" if exists else "start_page.continue_missing"
            self.continue_button.setText(tr(key, target=self._continue_target_label(name)))
            self.continue_button.setToolTip(tr("start_page.continue_folder_tip"))
            self.continue_button.setEnabled(exists)
        else:
            self.continue_button.setText(tr("start_page.continue_none"))
            self.continue_button.setToolTip(tr("start_page.continue_none_tip"))
            self.continue_button.setEnabled(False)

    def _refresh_footer(self) -> None:
        profile_text = tr(
            "start_page.profile_presenter" if self._profile_name == "presenter" else "start_page.profile_full"
        )
        saving_key = (
            "start_page.measurements_on" if self._measurement_persistence_enabled else "start_page.measurements_off"
        )
        self._footer.setText(
            "  ·  ".join(
                (
                    tr("start_page.version", version=self._version),
                    tr("start_page.profile", profile=profile_text),
                    tr(saving_key),
                )
            )
        )

    # ── theme ──────────────────────────────────────────────────────────

    def _apply_theme(self) -> None:
        tokens = get_theme_tokens()
        title_font_size = max(22, round(self._ui_font_size * 1.75))
        self.setStyleSheet(
            "QWidget#startPage { background-color: " + tokens["surface.0"] + "; color: " + tokens["text.1"] + "; }"
            "QFrame#startPageBrowserHeader { background-color: "
            + tokens["surface.1"]
            + "; border: none; border-bottom: 1px solid "
            + tokens["line.1"]
            + "; }"
            "QLabel#startPageTitle { color: "
            + tokens["text.1"]
            + f"; font-size: {title_font_size}px; font-weight: 600; }}"
            "QLineEdit#startPageStudySearch { background-color: "
            + tokens["surface.2"]
            + "; color: "
            + tokens["text.1"]
            + "; border: 1px solid "
            + tokens["line.2"]
            + "; border-radius: 6px; padding: 7px 10px; }"
            "QLineEdit#startPageStudySearch:focus { border-color: " + tokens["accent"] + "; }"
            "QPushButton[startPageRole='segment'] { background-color: "
            + tokens["surface.2"]
            + "; color: "
            + tokens["text.2"]
            + "; border: 1px solid "
            + tokens["line.1"]
            + "; border-radius: 6px; padding: 7px 10px; }"
            "QPushButton[startPageRole='segment']:checked { background-color: "
            + tokens["accent.selected"]
            + "; color: "
            + tokens["text.1"]
            + "; }"
            "QPushButton[startPageRole='primary'] { background-color: "
            + tokens["accent"]
            + "; color: "
            + tokens["accent.on"]
            + "; border: 1px solid "
            + tokens["accent"]
            + "; border-radius: 6px; padding: 8px 12px; font-weight: 600; }"
            "QPushButton[startPageRole='primary']:hover { background-color: " + tokens["accent.text"] + "; }"
            "QPushButton[startPageRole='secondary'] { background-color: "
            + tokens["surface.3"]
            + "; color: "
            + tokens["text.1"]
            + "; border: 1px solid "
            + tokens["line.2"]
            + "; border-radius: 6px; padding: 8px 12px; }"
            "QPushButton[startPageRole='secondary']:hover, "
            "QPushButton[startPageRole='link']:hover { background-color: " + tokens["surface.hover"] + "; }"
            # A link is a link: the boxed variant clipped its own border in a
            # narrow sidebar and read as a disabled button next to real ones.
            "QPushButton[startPageRole='link'] { background-color: transparent; color: "
            + tokens["accent.text"]
            + "; border: none; border-radius: 4px; padding: 6px 8px; text-align: left; }"
            "QPushButton:disabled { color: " + tokens["text.disabled"] + "; }"
            "QScrollArea#startPageSidebar { background-color: " + tokens["surface.1"] + "; border: none; }"
            "QWidget#startPageSidebarHost { background-color: " + tokens["surface.1"] + "; }"
            "QLabel[startPageRole='sectionTitle'] { color: " + tokens["text.3"] + "; font-weight: 600; }"
            "QLabel[startPageRole='detailCaption'] { color: " + tokens["text.3"] + "; }"
            "QLabel#startPageSubtitle, QLabel#startPageRecentPlacesEmpty, "
            "QLabel#startPageRecentStudiesEmpty, QLabel#startPageNoResultsLabel, "
            "QLabel#startPageStudiesCount, QLabel#startPageDetailNote, "
            "QLabel#startPageDetailHint { color: " + tokens["text.3"] + "; }"
            "QLabel#startPageDetailTitle { color: " + tokens["text.1"] + "; font-weight: 600; }"
            "QLabel#startPageStatus { color: "
            + tokens["text.3"]
            + "; border-top: 1px solid "
            + tokens["line.1"]
            + "; padding-top: 10px; }"
            "QFrame#startPageCard { background-color: " + tokens["surface.0"] + "; border: none; }"
            "QFrame#startPageDetailPanel { background-color: " + tokens["surface.1"] + "; border: none; }"
            "QListWidget#startPageRecentPlacesList { background: transparent; border: none; outline: none; color: "
            + tokens["text.1"]
            + "; }"
            "QListWidget#startPageSourceNav::item, QListWidget#startPageFilterList::item, "
            "QListWidget#startPageRecentPlacesList::item { border-radius: 4px; padding-left: 6px; }"
            "QListWidget#startPageSourceNav::item:selected, "
            "QListWidget#startPageRecentPlacesList::item:selected { background-color: "
            + tokens["accent.selected"]
            + "; }"
            "QTableWidget#startPageStudiesTable { background-color: transparent; border: none; outline: none; "
            "gridline-color: "
            + tokens["line.1"]
            + "; color: "
            + tokens["text.1"]
            + "; selection-background-color: "
            + tokens["accent.selected"]
            + "; }"
            "QTableWidget#startPageStudiesTable::item { padding: 4px 6px; border-bottom: 1px solid "
            + tokens["line.1"]
            + "; }"
            "QHeaderView::section { background-color: "
            + tokens["surface.1"]
            + "; color: "
            + tokens["text.3"]
            + "; border: none; border-bottom: 1px solid "
            + tokens["line.1"]
            + "; padding: 6px; }"
        )
