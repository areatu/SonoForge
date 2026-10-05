"""Dialog for browsing Orthanc studies and downloading selected series.

Layout (по мотивам PACS-ворк листов: Sectra IDS7, GE Synapse, RadiAnt):

    ┌ toolbar: поиск │ источник │ период │ сортировка │ миниатюры ┐
    ├───────────────────────────┬──────────────────────────────────┤
    │ ИССЛЕДОВАНИЯ (N)          │ пациент + исследование           │
    │  ☑ ▣ Иванов Иван Иванович │  ☑ ▣ 2D PLAX     96 инст.        │
    │      М · 67 лет · 28.09…  │  ☐ ▣ Doppler mitral              │
    ├───────────────────────────┴──────────────────────────────────┤
    │ Выбрано: 2 иссл. · 7 сер. · ≈ 84 МБ   [прогресс]  [кнопки]   │
    └──────────────────────────────────────────────────────────────┘

The left list is the study list, the right pane shows the series of the
highlighted study; a study checkbox selects the whole study at once, and the
series checkboxes let the user trim the selection.  See
``docs/superpowers/specs/2026-10-04-orthanc-dialog-ux-ru.md`` for the rationale.
"""

from __future__ import annotations

import logging
import shutil
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import shiboken6
from PySide6.QtCore import QObject, QRunnable, QSettings, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.application.workers.orthanc_download_worker import OrthancDownloadWorker
from echo_personal_tool.domain.models import StudyMetadata
from echo_personal_tool.domain.models.orthanc import SeriesInfo, StudyInfo, StudyStatistics
from echo_personal_tool.domain.ports import DicomWebClient, QuerySource
from echo_personal_tool.domain.services.patient_display import (
    format_patient_age,
    format_person_name,
    format_relative_day,
    format_size_mb,
)
from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.infrastructure.orthanc_cache import OrthancSessionCache
from echo_personal_tool.infrastructure.orthanc_client import OrthancDicomWebClient
from echo_personal_tool.infrastructure.profile import qsettings_for
from echo_personal_tool.infrastructure.server_client_factory import (
    make_dicom_retrieve_service,
)
from echo_personal_tool.infrastructure.server_settings import (
    ServerSettings,
    load_server_settings,
    save_server_settings,
)
from echo_personal_tool.presentation.orthanc_preview_loader import OrthancPreviewLoader
from echo_personal_tool.presentation.orthanc_study_delegate import (
    ROLE_CHECKED,
    ROLE_PARTIAL,
    ROLE_PIXMAP,
    ROLE_ROW,
    ROLE_SORT_KEY,
    ROLE_UID,
    SERIES_ROW_HEIGHT,
    STUDY_ROW_HEIGHT,
    Badge,
    OrthancRowDelegate,
    SeriesRow,
    StudyRow,
    checkbox_rect,
)

_SORT_ROLE = ROLE_SORT_KEY
_CANCEL_FORCE_CLOSE_MS = 30_000
# The status line must never widen the dialog: long failure chains go to the
# log in full, while the label and the error box get a bounded slice.
_STATUS_TEXT_LIMIT = 240
_DIALOG_TEXT_LIMIT = 400
#: How many prior studies of the same patient the strip shows at most.
_HISTORY_LIMIT = 6
#: Per-patient cache of prior studies fetched in this dialog session.
_HISTORY_CACHE_LIMIT = 12
_STATUS_LABEL_MAX_WIDTH = 720
_SEARCH_DEBOUNCE_MS = 400
_PREVIEW_TARGET = QSize(160, 120)
_MAX_PREFETCHED_STUDIES = 24
_UI_SETTINGS_APP = "loader_dialog"
_THUMBNAILS_KEY = "show_thumbnails"
_UNKNOWN_PATIENT_KEY = "orthanc.unknown_patient"
_NO_DESCRIPTION_KEY = "orthanc.no_description"
_TODAY_KEY = "orthanc.date_today"
_YESTERDAY_KEY = "orthanc.date_yesterday"

log = logging.getLogger(__name__)


def build_loader_dialog_stylesheet(p: dict[str, str]) -> str:
    """Dialog-scoped QSS: period chips, primary button, panel headers.

    Scoped to the loader dialog on purpose — the global theme styles
    ``QTreeWidget`` check indicators as small circular markers for the clinical
    browsers, which is exactly the affordance the loader must not reuse.  Row
    checkboxes there are painted by the delegate instead.
    """
    return f"""
            QPushButton#periodChip {{
                background: {p["bg_control"]};
                border: 1px solid {p["border"]};
                border-radius: 12px;
                padding: 4px 12px;
            }}
            QPushButton#periodChip:hover {{ border-color: {p["accent"]}; }}
            QPushButton#periodChip:checked {{
                background: {p["accent"]};
                color: #062026;
                border-color: {p["accent"]};
                font-weight: bold;
            }}
            QPushButton#primaryButton {{
                background: {p["accent"]};
                color: #062026;
                font-weight: bold;
                border: none;
                border-radius: 4px;
                padding: 7px 18px;
            }}
            QPushButton#primaryButton:hover {{ background: {p["accent_bright"]}; }}
            QPushButton#primaryButton:disabled {{
                background: {p["bg_button"]};
                color: {p["text_dim"]};
            }}
            QLabel#patientBanner {{
                background: {p["bg_control"]};
                border: 1px solid {p["border"]};
                border-radius: 5px;
                padding: 7px 10px;
                color: {p["text"]};
                font-weight: bold;
            }}
            QLabel#selectionSummary {{ color: {p["text"]}; }}
            QLabel#emptyState {{ color: {p["text_dim"]}; }}
            QLabel#panelHeader {{ color: {p["text_dim"]}; font-weight: bold; }}
            QPushButton#historyChip {{
                background: {p["bg_control"]};
                border: 1px solid {p["border"]};
                border-radius: 11px;
                padding: 3px 10px;
                color: {p["text"]};
            }}
            QPushButton#historyChip:hover {{
                border-color: {p["accent"]};
                color: {p["accent"]};
            }}
            QTreeWidget#studyList, QTreeWidget#seriesList {{
                background: {p["bg_dark"]};
                border: 1px solid {p["border"]};
                border-radius: 5px;
            }}
            QTreeWidget#studyList::item, QTreeWidget#seriesList::item {{
                border: none;
                padding: 0px;
            }}
            """


class _StudyItem(QTreeWidgetItem):
    """Sort by the key stored in ``_SORT_ROLE``, not by the painted text."""

    def __lt__(self, other: QTreeWidgetItem) -> bool:
        col = self.treeWidget().sortColumn() if self.treeWidget() else 0
        a = self.data(col, _SORT_ROLE)
        b = other.data(col, _SORT_ROLE)
        return str(a or "") < str(b or "")


class CheckableTreeWidget(QTreeWidget):
    """Flat list with delegate-painted rows and a mouse/keyboard checkbox.

    Qt draws tree indicators inside the item rect and offers no hit-test API,
    so the checkbox is painted by the delegate and hit-tested here.  ``Space``
    toggles the current row, matching every list UI users already know.
    """

    checkToggled = Signal(object)  # QTreeWidgetItem

    def __init__(self, parent: QWidget | None = None, *, row_height: int) -> None:
        super().__init__(parent)
        self._row_height = row_height
        self.setColumnCount(1)
        self.setHeaderHidden(True)
        self.setRootIsDecorated(False)
        self.setIndentation(0)
        self.setUniformRowHeights(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setMouseTracking(True)
        self.setExpandsOnDoubleClick(False)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

    def item_for_pos(self, pos) -> QTreeWidgetItem | None:  # noqa: ANN001 - QPoint
        item = self.itemAt(pos)
        if item is None:
            return None
        return item

    def checkbox_hit(self, item: QTreeWidgetItem, pos) -> bool:  # noqa: ANN001 - QPoint
        rect = self.visualItemRect(item)
        return checkbox_rect(rect).contains(pos)

    def mousePressEvent(self, event) -> None:  # noqa: ANN001 - QMouseEvent
        item = self.item_for_pos(event.position().toPoint())
        if item is not None and self.checkbox_hit(item, event.position().toPoint()):
            self.checkToggled.emit(item)
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: ANN001 - QKeyEvent
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Select):
            item = self.currentItem()
            if item is not None:
                self.checkToggled.emit(item)
                event.accept()
                return
        super().keyPressEvent(event)


class _StudyQuerySignals(QObject):
    finished = Signal(object, object)  # (list[StudyInfo] | None, error_message | None)


class _PingSignals(QObject):
    finished = Signal(bool)  # server answered


class _PingWorker(QRunnable):
    """Check server availability off the GUI thread."""

    def __init__(self, client: object, signals: _PingSignals) -> None:
        super().__init__()
        self._client = client
        self._signals = signals
        self.setAutoDelete(True)

    def run(self) -> None:
        ok = False
        try:
            ping = getattr(self._client, "ping", None)
            ok = bool(ping()) if callable(ping) else False
        except Exception as exc:  # noqa: BLE001
            log.debug("[DLG] ping failed: %s", exc)
        try:
            self._signals.finished.emit(ok)
        except RuntimeError:
            log.debug("[DLG] ping worker: signal already deleted, skipping emit")


class _StudyQueryWorker(QRunnable):
    """Fetch studies from Orthanc in a background thread."""

    def __init__(self, query_fn: Callable[[], list], signals: _StudyQuerySignals) -> None:
        super().__init__()
        self._query_fn = query_fn
        self._signals = signals
        self.setAutoDelete(True)

    def run(self) -> None:
        error = None
        try:
            studies = self._query_fn()
        except Exception as exc:  # noqa: BLE001
            log.warning("[DLG] study query failed: %s", exc)
            studies = []
            error = str(exc)
        try:
            self._signals.finished.emit(studies, error)
        except RuntimeError:
            log.debug("[DLG] study query worker: signal already deleted, skipping emit")


class _SeriesQuerySignals(QObject):
    finished = Signal(object)  # (study_uid, series_list, error_message)


class _SeriesQueryWorker(QRunnable):
    """Fetch series for a single study in a background thread."""

    def __init__(self, study_uid: str, query_fn: Callable[[str], list], signals: _SeriesQuerySignals) -> None:
        super().__init__()
        self._study_uid = study_uid
        self._query_fn = query_fn
        self._signals = signals
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            series = self._query_fn(self._study_uid)
            error = None
        except Exception as exc:  # noqa: BLE001
            log.warning("[DLG] series query failed for %s: %s", self._study_uid[:16], exc)
            series = []
            error = str(exc)
        try:
            self._signals.finished.emit((self._study_uid, series, error))
        except RuntimeError:
            log.debug("[DLG] series query worker: signal already deleted, skipping emit")


class _StudyDetailSignals(QObject):
    finished = Signal(str, object)  # study_uid, StudyStatistics


class _StudyDetailWorker(QRunnable):
    """Fetch study size/status from Orthanc REST (optional, best effort)."""

    def __init__(
        self, study_uid: str, fetch_fn: Callable[[str], StudyStatistics], signals: _StudyDetailSignals
    ) -> None:
        super().__init__()
        self._study_uid = study_uid
        self._fetch_fn = fetch_fn
        self._signals = signals
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            stats = self._fetch_fn(self._study_uid)
        except Exception as exc:  # noqa: BLE001
            log.debug("[DLG] study details failed for %s: %s", self._study_uid[:16], exc)
            stats = StudyStatistics()
        if not isinstance(stats, StudyStatistics):
            stats = StudyStatistics()
        try:
            self._signals.finished.emit(self._study_uid, stats)
        except RuntimeError:
            log.debug("[DLG] study detail worker: signal already deleted, skipping emit")


class OrthancStudyDialog(QDialog):
    """Browse studies with a master–detail layout and download the selection."""

    def __init__(
        self,
        client: DicomWebClient,
        cache: OrthancSessionCache,
        parent: QWidget | None = None,
        *,
        server_settings: ServerSettings | None = None,
        base_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
        query_service=None,  # DicomQueryService | None
        retrieve_service=None,  # DicomRetrieveService | None
    ) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self._client = client
        self._cache = cache
        self._server_settings = server_settings
        self._base_url = base_url
        self._username = username
        self._password = password
        self._query_service = query_service
        # The caller may inject a retrieve service sharing the same HTTP/DIMSE
        # clients (L4). Fall back to building one from settings for callers
        # that do not provide it (kept for backwards compatibility).
        self._retrieve_service = retrieve_service
        if self._retrieve_service is None and server_settings is not None:
            self._retrieve_service = make_dicom_retrieve_service(server_settings)
        # When services are injected (L4), the caller owns the shared client
        # and is responsible for closing it.  The dialog only closes a client
        # it created itself via the fallback retrieve-service path.
        self._owns_client = query_service is None and retrieve_service is None
        self._result: tuple[str, str] | None = None
        self._downloading = False
        self._worker: OrthancDownloadWorker | None = None
        self._session_id: str | None = None
        self._client_closed = False
        self._close_pending = False
        self._pending_downloads: list[tuple[str, list[str]]] = []
        self._completed_downloads = 0
        self._failed_downloads = 0
        self._total_studies = 0
        self._partial_download_warnings: list[str] = []
        self._downloaded_studies: list[StudyMetadata] = []
        self._force_close_timer = QTimer(self)
        self._force_close_timer.setSingleShot(True)
        self._force_close_timer.timeout.connect(self._force_close_if_still_downloading)
        self._series_loading: set[str] = set()
        self._closed = False
        self._active_workers: list[tuple[QRunnable, QObject]] = []
        self._save_to_disk_path: str = ""
        self._init_timer = QTimer(self)
        self._init_timer.setSingleShot(True)
        self._init_timer.timeout.connect(self._init_network)
        self._reject_timer = QTimer(self)
        self._reject_timer.setSingleShot(True)
        self._reject_timer.timeout.connect(self.reject)

        # ── model state ─────────────────────────────────────────────
        self._studies: list[StudyInfo] = []
        #: Prior studies per patient id (one query per patient per dialog).
        self._history_cache: dict[str, list[StudyInfo]] = {}
        self._history_in_flight: set[str] = set()
        #: Incremented per study query so a slow answer cannot replace a list
        #: the user is already working with.
        self._study_query_generation = 0
        #: Patient whose history the strip currently shows.
        self._history_patient = ""
        self._series_cache: dict[str, list[SeriesInfo]] = {}
        self._series_errors: dict[str, str] = {}
        self._series_loaded: set[str] = set()
        self._selected_all: set[str] = set()  # study marked as "whole study"
        self._selected_series: dict[str, set[str]] = {}
        self._study_thumbnails: dict[str, tuple[str, str]] = {}  # study -> (study, series)
        self._study_stats: dict[str, StudyStatistics] = {}
        self._study_states: dict[str, tuple[str, str]] = {}
        self._prefetch_queue: list[str] = []
        self._prefetching: set[str] = set()
        self._pending_action: str | None = None
        self._current_study_uid = ""
        self._sort_mode = "date_desc"

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(_SEARCH_DEBOUNCE_MS)
        self._search_timer.timeout.connect(self._load_studies_async)

        self._preview_loader = OrthancPreviewLoader(client, target_size=_PREVIEW_TARGET, parent=self)
        self._preview_loader.preview_ready.connect(self._on_preview_ready)

        self.setWindowTitle(tr("dialog.orthanc.title"))
        self.resize(1120, 660)
        self.setMinimumSize(760, 480)

        self._build_ui()
        self._restore_ui_preferences()
        self._init_timer.start(0)

    # ── UI construction ─────────────────────────────────────────────
    def _build_ui(self) -> None:
        from echo_personal_tool.presentation.dark_theme import get_theme_palette

        p = get_theme_palette()

        # Title bar (frameless window)
        self._drag_pos = None
        title_bar = QWidget()
        title_bar.setFixedHeight(34)
        title_bar.setStyleSheet(f"background: {p['bg_dark']};")
        tb_layout = QHBoxLayout(title_bar)
        tb_layout.setContentsMargins(10, 0, 4, 0)
        tb_layout.setSpacing(8)
        title_label = QLabel(tr("dialog.orthanc.title"))
        title_label.setStyleSheet(f"color: {p['text']}; font-weight: bold; border: none;")
        tb_layout.addWidget(title_label)
        self._server_pill = QLabel(tr("orthanc.checking_server"))
        self._server_pill.setStyleSheet(f"color: {p['text_dim']}; border: none; padding-left: 6px;")
        tb_layout.addWidget(self._server_pill)
        tb_layout.addStretch(1)
        from echo_personal_tool.presentation.system_bar import _load_icon

        btn_close = QPushButton()
        btn_close.setIcon(_load_icon("close"))
        btn_close.setObjectName("closeButton")
        btn_close.setFixedSize(28, 23)
        btn_close.clicked.connect(self.reject)
        tb_layout.addWidget(btn_close)

        # Search / controls row
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText(tr("orthanc.patient_name_placeholder"))
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.returnPressed.connect(self._on_find)
        self._search_edit.textChanged.connect(self._on_search_text_changed)

        self._find_btn = QPushButton(tr("orthanc.find"))
        self._find_btn.setDefault(True)
        self._find_btn.clicked.connect(self._on_find)

        self._source_combo = QComboBox()
        self._source_combo.addItem(tr("server_settings.query_source_dicomweb"), "dicomweb")
        self._source_combo.addItem(tr("server_settings.query_source_dimse"), "dimse")
        self._source_combo.addItem(tr("server_settings.query_source_auto"), "auto")
        if self._query_service is not None:
            source_idx = self._source_combo.findData(self._query_service.source.value)
            self._source_combo.setCurrentIndex(max(source_idx, 0))
        self._source_combo.currentIndexChanged.connect(self._on_source_changed)
        self._source_combo.setToolTip(tr("orthanc.source_tooltip"))

        self._sort_combo = QComboBox()
        for key, label_key in (
            ("date_desc", "orthanc.sort_date_desc"),
            ("date_asc", "orthanc.sort_date_asc"),
            ("name", "orthanc.sort_name"),
            ("size", "orthanc.sort_size"),
        ):
            self._sort_combo.addItem(tr(label_key), key)
        self._sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        self._sort_combo.setToolTip(tr("orthanc.sort_tooltip"))

        self._thumbs_check = QCheckBox(tr("orthanc.thumbnails"))
        self._thumbs_check.setChecked(True)
        self._thumbs_check.toggled.connect(self._on_thumbnails_toggled)
        self._thumbs_check.setToolTip(tr("orthanc.thumbnails_tooltip"))

        search_row = QHBoxLayout()
        search_row.setContentsMargins(10, 8, 10, 0)
        search_row.setSpacing(8)
        search_row.addWidget(self._search_edit, stretch=1)
        search_row.addWidget(self._find_btn)
        search_row.addSpacing(12)
        search_row.addWidget(QLabel(tr("orthanc.source_label")))
        search_row.addWidget(self._source_combo)
        search_row.addWidget(QLabel(tr("orthanc.sort_label")))
        search_row.addWidget(self._sort_combo)
        search_row.addWidget(self._thumbs_check)

        # Period filter as a segmented control (faster than a combo box)
        self._date_filter_group = QButtonGroup(self)
        self._date_filter_group.setExclusive(True)
        period_row = QHBoxLayout()
        period_row.setContentsMargins(10, 8, 10, 0)
        period_row.setSpacing(6)
        period_row.addWidget(QLabel(tr("orthanc.period_label")))
        self._period_buttons: dict[int, QPushButton] = {}
        for days, label_key in (
            (0, "orthanc.date_filter_all"),
            (1, "orthanc.date_filter_1d"),
            (7, "orthanc.date_filter_7d"),
            (30, "orthanc.date_filter_30d"),
            (90, "orthanc.date_filter_90d"),
        ):
            button = QPushButton(tr(label_key))
            button.setCheckable(True)
            button.setObjectName("periodChip")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setChecked(days == 0)
            self._date_filter_group.addButton(button)
            self._period_buttons[days] = button
            period_row.addWidget(button)
        self._date_filter_group.buttonClicked.connect(self._on_date_filter_changed)
        period_row.addStretch(1)
        self._select_all_btn = QPushButton(tr("orthanc.select_all"))
        self._select_all_btn.clicked.connect(self._on_select_all_studies)
        self._clear_selection_btn = QPushButton(tr("orthanc.clear_selection"))
        self._clear_selection_btn.clicked.connect(self._on_clear_selection)
        period_row.addWidget(self._select_all_btn)
        period_row.addWidget(self._clear_selection_btn)

        # Master–detail splitter
        self._studies_list = CheckableTreeWidget(row_height=STUDY_ROW_HEIGHT)
        self._studies_list.setItemDelegate(OrthancRowDelegate(self._studies_list, kind="study"))
        self._studies_list.setObjectName("studyList")
        self._studies_list.checkToggled.connect(self._on_study_check_toggled)
        self._studies_list.currentItemChanged.connect(self._on_study_current_changed)
        self._studies_list.itemDoubleClicked.connect(self._on_study_double_clicked)
        self._studies_list.verticalScrollBar().valueChanged.connect(self._on_list_scrolled)
        self._studies_list.setToolTip(tr("orthanc.help_hint"))

        self._studies_header = QLabel()
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(10, 8, 6, 8)
        left_layout.setSpacing(6)
        left_layout.addWidget(self._studies_header)
        self._studies_stack = QStackedWidget()
        self._studies_stack.addWidget(self._studies_list)
        self._empty_studies, self._empty_studies_label = self._make_empty_page(tr("orthanc.empty_studies"))
        self._studies_stack.addWidget(self._empty_studies)
        left_layout.addWidget(self._studies_stack, stretch=1)

        self._series_list = CheckableTreeWidget(row_height=SERIES_ROW_HEIGHT)
        self._series_list.setItemDelegate(OrthancRowDelegate(self._series_list, kind="series"))
        self._series_list.setObjectName("seriesList")
        self._series_list.checkToggled.connect(self._on_series_check_toggled)
        self._series_list.verticalScrollBar().valueChanged.connect(self._on_list_scrolled)
        self._series_list.setToolTip(tr("orthanc.help_hint"))

        self._patient_label = QLabel()
        self._patient_label.setObjectName("patientBanner")
        self._patient_label.setWordWrap(True)
        self._series_header = QLabel()
        self._series_actions = QWidget()
        series_actions_row = QHBoxLayout(self._series_actions)
        series_actions_row.setContentsMargins(0, 0, 0, 0)
        series_actions_row.setSpacing(6)
        self._series_all_btn = QPushButton(tr("orthanc.select_all_series"))
        self._series_all_btn.clicked.connect(lambda: self._set_all_series_checked(True))
        self._series_none_btn = QPushButton(tr("orthanc.clear_series"))
        self._series_none_btn.clicked.connect(lambda: self._set_all_series_checked(False))
        series_actions_row.addWidget(self._series_all_btn)
        series_actions_row.addWidget(self._series_none_btn)
        series_actions_row.addStretch(1)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(6, 8, 10, 8)
        right_layout.setSpacing(6)
        right_layout.addWidget(self._patient_label)
        self._history_panel = QWidget()
        history_row = QHBoxLayout(self._history_panel)
        history_row.setContentsMargins(0, 0, 0, 0)
        history_row.setSpacing(6)
        self._history_label = QLabel()
        self._history_label.setObjectName("panelHeader")
        history_row.addWidget(self._history_label)
        self._history_chips = QWidget()
        self._history_chips_layout = QHBoxLayout(self._history_chips)
        self._history_chips_layout.setContentsMargins(0, 0, 0, 0)
        self._history_chips_layout.setSpacing(6)
        history_row.addWidget(self._history_chips)
        history_row.addStretch(1)
        self._history_panel.hide()
        right_layout.addWidget(self._history_panel)
        header_row = QHBoxLayout()
        header_row.setSpacing(8)
        header_row.addWidget(self._series_header)
        header_row.addWidget(self._series_actions)
        header_row.addStretch(1)
        right_layout.addLayout(header_row)
        self._series_stack = QStackedWidget()
        self._series_stack.addWidget(self._series_list)
        self._empty_series, self._empty_series_label = self._make_empty_page(tr("orthanc.empty_series"))
        self._series_stack.addWidget(self._empty_series)
        right_layout.addWidget(self._series_stack, stretch=1)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 4)
        splitter.setChildrenCollapsible(False)

        # Footer: selection summary, progress, actions
        self._summary_label = QLabel()
        self._summary_label.setObjectName("selectionSummary")
        self._summary_label.setWordWrap(True)
        self._status_label = QLabel()
        self._status_label.setWordWrap(True)
        self._status_label.setMinimumWidth(0)
        self._status_label.setMaximumWidth(_STATUS_LABEL_MAX_WIDTH)
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignLeading | Qt.AlignmentFlag.AlignTop)
        self._progress = QProgressBar()
        self._progress.hide()

        self._load_btn = QPushButton(tr("orthanc.open"))
        self._load_btn.setObjectName("primaryButton")
        self._load_btn.setEnabled(False)
        self._load_btn.setToolTip(tr("orthanc.open_tooltip"))
        self._load_btn.clicked.connect(self._on_load)

        self._save_disk_btn = QPushButton(tr("orthanc.save_to_disk"))
        self._save_disk_btn.setEnabled(False)
        self._save_disk_btn.clicked.connect(self._on_save_to_disk)

        self._cancel_btn = QPushButton(tr("orthanc.cancel"))
        self._cancel_btn.clicked.connect(self._on_cancel)

        actions_row = QHBoxLayout()
        actions_row.setContentsMargins(10, 0, 10, 10)
        actions_row.setSpacing(8)
        actions_row.addWidget(self._summary_label, stretch=1)
        actions_row.addWidget(self._cancel_btn)
        actions_row.addWidget(self._save_disk_btn)
        actions_row.addWidget(self._load_btn)

        status_row = QHBoxLayout()
        status_row.setContentsMargins(10, 0, 10, 0)
        status_row.setSpacing(10)
        # Explicit alignment: without it Qt centres the (width-capped) label in
        # its cell as soon as the progress bar is hidden.
        status_row.addWidget(
            self._status_label,
            0,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )
        status_row.addWidget(self._progress, stretch=1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(title_bar)
        layout.addLayout(search_row)
        layout.addLayout(period_row)
        layout.addWidget(splitter, stretch=1)
        layout.addLayout(status_row)
        layout.addLayout(actions_row)

        self._apply_local_style(p)
        self._install_shortcuts()
        self._update_selection_summary()
        self._update_empty_states()

    def _make_empty_page(self, text: str) -> tuple[QWidget, QLabel]:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(24, 24, 24, 24)
        page_layout.addStretch(1)
        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        label.setObjectName("emptyState")
        page_layout.addWidget(label)
        page_layout.addStretch(1)
        return page, label

    def _apply_local_style(self, p: dict[str, str]) -> None:
        """Dialog-scoped QSS (see :func:`build_loader_dialog_stylesheet`)."""
        self.setStyleSheet(build_loader_dialog_stylesheet(p))
        header_font = QFont(self.font())
        header_font.setBold(True)
        for label in (self._studies_header, self._series_header):
            label.setObjectName("panelHeader")
            label.setFont(header_font)

    def _install_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self._search_edit.setFocus)
        QShortcut(QKeySequence("F5"), self, activated=self._load_studies_async)
        QShortcut(QKeySequence("Ctrl+R"), self, activated=self._load_studies_async)
        QShortcut(QKeySequence("Ctrl+A"), self, activated=self._on_select_all_studies)

    # ── settings ────────────────────────────────────────────────────
    def _ui_settings(self) -> QSettings:
        return qsettings_for("sonoforge", _UI_SETTINGS_APP)

    def _restore_ui_preferences(self) -> None:
        try:
            store = self._ui_settings()
            value = store.value(_THUMBNAILS_KEY, True)
            enabled = value if isinstance(value, bool) else str(value).lower() not in {"false", "0", "no"}
        except Exception:  # noqa: BLE001 - preferences must never block the dialog
            enabled = True
        self._thumbs_check.setChecked(enabled)
        self._preview_loader.set_enabled(enabled)

    def _persist_ui_preferences(self) -> None:
        try:
            store = self._ui_settings()
            store.setValue(_THUMBNAILS_KEY, bool(self._thumbs_check.isChecked()))
            store.sync()
        except Exception:  # noqa: BLE001
            log.debug("[DLG] cannot persist loader dialog preferences", exc_info=True)

    def _on_thumbnails_toggled(self, checked: bool) -> None:
        self._preview_loader.set_enabled(checked)
        self._persist_ui_preferences()
        if checked:
            self._request_visible_previews()
        self._studies_list.viewport().update()
        self._series_list.viewport().update()

    # ── network / queries ───────────────────────────────────────────
    def _init_network(self) -> None:
        if not self._is_alive():
            return
        log.info("[DLG] _init_network called")
        self._set_status(tr("orthanc.searching"))
        self._ping_async()
        self._load_studies_async()

    def _ping_async(self) -> None:
        """Show whether the server answers at all (non-blocking)."""
        signals = _PingSignals()
        signals.finished.connect(self._on_ping_done)
        worker = _PingWorker(self._client, signals)
        self._active_workers.append((worker, signals))
        QThreadPool.globalInstance().start(worker)

    def _on_ping_done(self, ok: bool) -> None:
        if not self._is_alive():
            return
        from echo_personal_tool.presentation.dark_theme import get_theme_palette

        p = get_theme_palette()
        color = p["success"] if ok else p["error"]
        text = tr("orthanc.server_available") if ok else tr("orthanc.server_unavailable")
        self._server_pill.setText(f"● {text}")
        self._server_pill.setStyleSheet(f"color: {color}; border: none; padding-left: 6px;")

    def _load_studies_async(self) -> None:
        """Query studies in a background thread to avoid blocking the UI."""
        if not self._is_alive():
            return
        if not self._query_source_available():
            self._set_status(tr("orthanc.dimse_disabled"))
            return
        if self._downloading:
            return
        text = self._search_edit.text().strip()
        patient_name = text or None
        self._set_status(tr("orthanc.searching"))
        self._empty_studies_label.setText(tr("orthanc.searching"))

        def _query() -> list:
            if self._query_service is not None:
                return self._query_service.query_studies(patient_name=patient_name)
            return self._client.query_studies(patient_name=patient_name)

        self._study_query_generation += 1
        generation = self._study_query_generation
        signals = _StudyQuerySignals()
        signals.finished.connect(
            lambda studies, error, gen=generation: self._on_studies_loaded_for(gen, studies, error)
        )
        worker = _StudyQueryWorker(_query, signals)
        self._active_workers.append((worker, signals))
        QThreadPool.globalInstance().start(worker)

    def _on_studies_loaded_for(self, generation: int, studies: object, error: str | None) -> None:
        """Drop answers of superseded searches (the user may have moved on)."""
        if generation != self._study_query_generation:
            log.debug("[DLG] ignoring stale study result #%d", generation)
            return
        self._on_studies_loaded(studies, error)

    def _on_search_text_changed(self, _text: str) -> None:
        if self._downloading:
            return
        self._search_timer.start()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() < 34:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def result_data(self) -> tuple[str, str] | None:
        """Return (session_id, study_uid) after successful download, else None."""
        return self._result

    def downloaded_studies(self) -> list[StudyMetadata]:
        """Return pre-scanned StudyMetadata from download worker (P4)."""
        return self._downloaded_studies

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        log.info("[DLG] closeEvent: downloading=%s", self._downloading)
        if self._downloading:
            self._close_pending = True
            self._on_cancel()
            event.ignore()
            return
        self._shutdown()
        super().closeEvent(event)

    def reject(self) -> None:
        log.info("[DLG] reject: downloading=%s result=%s", self._downloading, self._result)
        if self._downloading:
            self._close_pending = True
            self._on_cancel()
            return
        self._shutdown()
        super().reject()

    def accept(self) -> None:
        from echo_personal_tool.presentation.ui_animations import hide_dialog_animated

        log.info("[DLG] accept: result=%s downloaded=%d", self._result, len(self._downloaded_studies))
        try:
            self._release_client()
        except Exception:  # noqa: BLE001
            pass
        self._shutdown()
        hide_dialog_animated(self, on_done=super().accept)

    def _shutdown(self) -> None:
        """Stop pending callbacks so background workers can never touch a closed dialog."""
        if not self._is_alive():
            return
        self._closed = True
        self._init_timer.stop()
        self._reject_timer.stop()
        self._force_close_timer.stop()
        self._search_timer.stop()
        self._series_loading.clear()
        self._prefetch_queue.clear()
        self._prefetching.clear()
        self._preview_loader.shutdown()
        for _worker, signals in self._active_workers:
            try:
                signals.finished.disconnect()
            except (RuntimeError, TypeError):
                pass
        self._active_workers.clear()
        self._persist_ui_preferences()
        self._release_client()

    def _is_alive(self) -> bool:
        """True while the dialog can still safely handle callbacks."""
        return not self._closed and shiboken6.isValid(self)

    def _release_client(self) -> None:
        if self._client_closed:
            return
        if not self._owns_client:
            self._client_closed = True
            return
        if isinstance(self._client, OrthancDicomWebClient):
            self._client.close()
            self._client_closed = True

    def _on_source_changed(self) -> None:
        source_val = self._source_combo.currentData()
        if self._query_service is not None and source_val:
            self._query_service.source = QuerySource(source_val)
        if source_val:
            self._persist_query_source(str(source_val))
        self._show_source_hint(str(source_val))

    @staticmethod
    def _retrieval_source_label(value: str) -> str:
        """Human-readable label of the *actual* download source in settings."""
        return {
            "wado": "WADO-RS",
            "dimse": "C-GET",
            "cmove": "C-MOVE",
            "auto": "Auto",
        }.get(value, value)

    def _show_source_hint(self, source_val: str) -> None:
        """Show an honest status hint about what the current source means.

        The combo only switches the *query* protocol; the download protocol
        is controlled separately by settings.retrieval_source, so the hint
        reports both instead of claiming "download via C-GET" unconditionally.
        """
        if self._downloading:
            return  # never clobber the download progress status
        if source_val != "dimse":
            return
        if not self._query_source_available():
            self._set_status(tr("orthanc.dimse_disabled"))
            return
        retrieval = self._retrieval_source_label(
            self._server_settings.retrieval_source if self._server_settings is not None else "auto"
        )
        self._set_status(tr("orthanc.dimse_info_banner", retrieval=retrieval))

    def _query_source_available(self) -> bool:
        """True when the currently selected query source can actually run.

        DIMSE requires either mock mode or DIMSE enabled in server settings;
        otherwise a search would silently return an empty list.
        """
        source_val = self._source_combo.currentData()
        if source_val != "dimse":
            return True
        if self._server_settings is None:
            return True
        return self._server_settings.use_mock or self._server_settings.dimse_enabled

    def _persist_query_source(self, source_val: str) -> None:
        if source_val not in {s.value for s in QuerySource}:
            return
        current = load_server_settings()
        if current.query_source == source_val:
            return
        updated = replace(current, query_source=source_val)
        save_server_settings(updated)
        if self._server_settings is not None:
            self._server_settings = replace(self._server_settings, query_source=source_val)

    # ── study list ──────────────────────────────────────────────────
    def _on_studies_loaded(self, studies: list, error: str | None = None) -> None:
        if not self._is_alive():
            return
        log.info("[DLG] _on_studies_loaded: count=%d error=%s", len(studies), error)
        self._studies = list(studies or [])
        self._series_cache.clear()
        self._series_errors.clear()
        self._series_loaded.clear()
        self._study_stats.clear()
        self._study_thumbnails.clear()
        self._selected_all.clear()
        self._selected_series.clear()
        self._study_states.clear()
        self._prefetch_queue = [s.study_uid for s in self._studies if s.study_uid]
        self._prefetching.clear()
        self._current_study_uid = ""
        self._history_patient = ""
        self._render_patient_history("", [])
        self._build_study_rows(self._studies)
        if error and not studies:
            # Server unreachable / auth failure / DIMSE refused — surface the
            # reason instead of showing an empty "Ready" list.
            self._set_status(tr("orthanc.find_error", message=error[:200]))
        elif error:
            self._set_status(tr("orthanc.find_error", message=error[:200]))
        elif not studies:
            self._set_status(tr("orthanc.ready"))
        else:
            self._set_status(tr("orthanc.studies_found", count=len(self._studies)))
        self._update_load_button()
        self._update_empty_states()
        self._update_selection_summary()
        QTimer.singleShot(0, self._prefetch_visible_studies)

    def _build_study_rows(self, studies: list) -> None:
        self._studies_list.blockSignals(True)
        self._studies_list.clear()
        for study in self._sorted_studies(studies):
            item = _StudyItem()
            item.setData(0, ROLE_ROW, self._make_study_row(study))
            item.setData(0, ROLE_UID, study.study_uid)
            item.setData(0, ROLE_CHECKED, study.study_uid in self._selected_all)
            item.setSizeHint(0, QSize(0, STUDY_ROW_HEIGHT))
            item.setData(0, _SORT_ROLE, self._study_sort_key(study))
            self._studies_list.addTopLevelItem(item)
        self._studies_list.blockSignals(False)
        self._update_studies_header()

    def _sorted_studies(self, studies: list) -> list[StudyInfo]:
        if self._sort_mode == "date_asc":
            return sorted(studies, key=lambda s: (s.study_date or "", s.study_time or ""))
        if self._sort_mode == "name":
            return sorted(studies, key=lambda s: (s.patient_name or "", s.study_date or ""))
        if self._sort_mode == "size":
            return sorted(studies, key=lambda s: (s.instances_count or 0, s.study_date or ""), reverse=True)
        return sorted(studies, key=lambda s: (s.study_date or "", s.study_time or ""), reverse=True)

    @staticmethod
    def _study_sort_key(study: StudyInfo) -> str:
        return f"{study.study_date or ''}{study.study_time or ''}"

    def _make_study_row(self, study: StudyInfo) -> StudyRow:
        badges: list[Badge] = []
        modalities = (study.modalities_in_study or "").strip()
        if modalities:
            badges.append(Badge(modalities.replace(", ", "/"), "accent"))
        if study.series_count:
            badges.append(Badge(tr("orthanc.badge_series", count=study.series_count)))
        if study.instances_count:
            badges.append(Badge(tr("orthanc.badge_instances", count=study.instances_count)))
        stats = self._study_stats.get(study.study_uid)
        if stats is not None:
            size = format_size_mb(stats.size_mb)
            if size:
                badges.append(Badge(f"≈ {size}"))
            if stats.is_stable is True:
                badges.append(Badge(tr("orthanc.badge_complete"), "success"))
            elif stats.is_stable is False:
                badges.append(Badge(tr("orthanc.badge_receiving"), "warning"))
        accession = (study.accession_number or "").strip()
        if accession:
            badges.append(Badge(f"№ {accession}"))
        state = self._study_states.get(study.study_uid)
        return StudyRow(
            study=study,
            title=format_person_name(study.patient_name, fallback=tr(_UNKNOWN_PATIENT_KEY)),
            demographics=self._demographics(study),
            description=(study.study_description or "").strip() or tr(_NO_DESCRIPTION_KEY),
            date_text=self._format_study_date_label(study),
            badges=tuple(badges),
            thumb_badge=self._study_thumb_badge(study),
            state_text=state[0] if state else "",
            state_kind=state[1] if state else "warning",
        )

    def _demographics(self, study: StudyInfo) -> str:
        parts: list[str] = []
        sex = {"M": tr("orthanc.sex_male"), "F": tr("orthanc.sex_female"), "O": tr("orthanc.sex_other")}.get(
            (study.patient_sex or "").strip().upper()[:1],
            "",
        )
        if sex:
            parts.append(sex)
        age = format_patient_age(
            study.patient_birth_date or "",
            study.study_date or "",
            year_forms=(
                tr("orthanc.age_year_one"),
                tr("orthanc.age_year_few"),
                tr("orthanc.age_year_many"),
            ),
        )
        if age:
            parts.append(age)
        patient_id = (study.patient_id or "").strip()
        if patient_id:
            parts.append(f"ID {patient_id}")
        return " · ".join(parts)

    def _format_study_date_label(self, study: StudyInfo) -> str:
        return format_relative_day(
            study.study_date or "",
            today_label=tr(_TODAY_KEY),
            yesterday_label=tr(_YESTERDAY_KEY),
        )

    def _study_thumb_badge(self, study: StudyInfo) -> str:
        """Modality label for the study thumbnail (from the first series)."""
        series = self._series_cache.get(study.study_uid) or []
        for entry in series:
            if entry.modality:
                return entry.modality
        modalities = (study.modalities_in_study or "").split(",")
        return modalities[0].strip() if modalities else ""

    def _format_study_date(self, raw_date: str) -> str:
        """Convert DICOM date 'YYYYMMDD' to 'DD.MM.YYYY' (kept for callers/tests)."""
        from echo_personal_tool.domain.services.patient_display import format_dicom_date

        return format_dicom_date(raw_date)

    def _visible_item_uids(self, tree: QTreeWidget, role: int) -> list[str]:
        """UIDs of the rows currently inside the viewport (plus one screen)."""
        viewport = tree.viewport().rect()
        padded = viewport.adjusted(0, -viewport.height(), 0, viewport.height())
        uids: list[str] = []
        for index in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(index)
            if not tree.visualItemRect(item).intersects(padded):
                continue
            uid = item.data(0, role)
            if uid:
                uids.append(str(uid))
        return uids

    def _on_list_scrolled(self, _value: int) -> None:
        self._request_visible_previews()

    def _request_visible_previews(self) -> None:
        if not self._is_alive() or not self._preview_loader.is_enabled():
            return
        for study_uid in self._visible_item_uids(self._studies_list, ROLE_UID):
            self._request_study_preview(study_uid)
        visible_series = self._visible_item_uids(self._series_list, ROLE_UID)
        for series_uid in visible_series:
            if self._current_study_uid:
                self._request_series_preview(self._current_study_uid, series_uid)

    def _request_study_preview(self, study_uid: str) -> None:
        series = self._series_cache.get(study_uid)
        if not series:
            self._prefetch_series(study_uid)
            return
        entry = series[0]
        if not entry.series_uid:
            return
        self._study_thumbnails[study_uid] = (study_uid, entry.series_uid)
        if self._preview_loader.cached(study_uid, entry.series_uid) is None:
            self._preview_loader.request(study_uid, entry.series_uid)

    def _request_series_preview(self, study_uid: str, series_uid: str) -> None:
        if self._preview_loader.cached(study_uid, series_uid) is None:
            self._preview_loader.request(study_uid, series_uid)

    def _on_preview_ready(self, study_uid: str, series_uid: str) -> None:
        if not self._is_alive():
            return
        pixmap = self._preview_loader.cached(study_uid, series_uid)
        if pixmap is None:
            return
        for index in range(self._studies_list.topLevelItemCount()):
            item = self._studies_list.topLevelItem(index)
            if item.data(0, ROLE_UID) != study_uid:
                continue
            target = self._study_thumbnails.get(study_uid)
            if target is not None and target[1] == series_uid:
                item.setData(0, ROLE_PIXMAP, pixmap)
            break
        if study_uid == self._current_study_uid:
            for index in range(self._series_list.topLevelItemCount()):
                item = self._series_list.topLevelItem(index)
                if item.data(0, ROLE_UID) == series_uid:
                    item.setData(0, ROLE_PIXMAP, pixmap)
                    break

    def _prefetch_visible_studies(self) -> None:
        for study_uid in self._visible_item_uids(self._studies_list, ROLE_UID):
            self._prefetch_series(study_uid)

    def _prefetch_series(self, study_uid: str, *, force: bool = False) -> None:
        """Load the series list of a study in the background (thumbnails, check-all).

        *force* is set for studies the user explicitly selected or opened: the
        background prefetch budget must never block an explicit request.
        """
        if not study_uid or study_uid in self._series_loaded or study_uid in self._series_loading:
            return
        if not force and len(self._series_loaded) >= _MAX_PREFETCHED_STUDIES:
            return
        self._series_loading.add(study_uid)

        def _query(uid: str) -> list:
            if self._query_service is not None:
                return self._query_service.query_series(uid)
            return self._client.query_series(uid)

        signals = _SeriesQuerySignals()
        signals.finished.connect(self._on_series_loaded)
        worker = _SeriesQueryWorker(study_uid, _query, signals)
        self._active_workers.append((worker, signals))
        QThreadPool.globalInstance().start(worker)

    def _on_series_loaded(self, result: object) -> None:
        if not self._is_alive():
            return
        study_uid, series_list, error = result  # type: ignore[misc]
        log.info(
            "[DLG] _on_series_loaded: study_uid=%s count=%d error=%s",
            study_uid[:16],
            len(series_list),
            error,
        )
        self._series_loading.discard(study_uid)
        self._series_loaded.add(study_uid)
        self._series_cache[study_uid] = list(series_list)
        if error:
            self._series_errors[study_uid] = str(error)
        if study_uid in self._selected_all:
            self._selected_series[study_uid] = {s.series_uid for s in series_list if s.series_uid}

        self._refresh_study_row(study_uid)
        if study_uid == self._current_study_uid:
            self._populate_series(study_uid)
        else:
            # The study thumbnail needs the first series UID.
            self._request_study_preview(study_uid)
        self._update_load_button()
        self._update_selection_summary()
        self._maybe_run_pending_action()

    def _refresh_study_row(self, study_uid: str) -> None:
        for index in range(self._studies_list.topLevelItemCount()):
            item = self._studies_list.topLevelItem(index)
            if item.data(0, ROLE_UID) != study_uid:
                continue
            study = self._study_by_uid(study_uid)
            if study is not None:
                item.setData(0, ROLE_ROW, self._make_study_row(study))
            self._sync_study_item_state(item)
            return

    def _study_by_uid(self, study_uid: str) -> StudyInfo | None:
        for study in self._studies:
            if study.study_uid == study_uid:
                return study
        return None

    def _series_label(self, series: SeriesInfo) -> str:
        parts = [series.modality, series.description]
        if series.instance_count is not None:
            parts.append(f"{series.instance_count} {tr('orthanc.instances_suffix')}")
        return " — ".join(part for part in parts if part)

    def _on_find(self) -> None:
        from echo_personal_tool.presentation.ui_animations import loading_button

        self._search_timer.stop()
        with loading_button(self._find_btn, tr("orthanc.searching")):
            self._load_studies_async()

    # ── selection ───────────────────────────────────────────────────
    def _on_study_current_changed(self, current: QTreeWidgetItem | None, _previous) -> None:
        if not self._is_alive() or current is None:
            return
        study_uid = current.data(0, ROLE_UID)
        if not study_uid:
            return
        self._current_study_uid = str(study_uid)
        self._show_study_details(self._current_study_uid)
        self._populate_series(self._current_study_uid)

    def _on_study_double_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        """Double-click = "download and open this study" (PACS habit)."""
        study_uid = item.data(0, ROLE_UID)
        if not study_uid or self._downloading:
            return
        self._on_clear_selection()
        self._set_study_selected(str(study_uid), True)
        self._on_load()

    def _show_study_details(self, study_uid: str) -> None:
        study = self._study_by_uid(study_uid)
        if study is None:
            return
        self._patient_label.setText(self._format_patient_header(study))
        self._patient_label.show()
        if study_uid not in self._study_stats:
            self._fetch_study_stats(study_uid)
        self._request_patient_history(study)

    def _format_patient_header(self, study: StudyInfo) -> str:
        from echo_personal_tool.domain.services.patient_display import format_patient_header

        return format_patient_header(
            study,
            age_year_forms=(
                tr("orthanc.age_year_one"),
                tr("orthanc.age_year_few"),
                tr("orthanc.age_year_many"),
            ),
        )

    def _fetch_study_stats(self, study_uid: str) -> None:
        fetch = getattr(self._client, "study_statistics", None)
        if not callable(fetch):
            return

        def _query(uid: str) -> StudyStatistics:
            result = fetch(uid)
            return result if isinstance(result, StudyStatistics) else StudyStatistics()

        signals = _StudyDetailSignals()
        signals.finished.connect(self._on_study_stats)
        worker = _StudyDetailWorker(study_uid, _query, signals)
        self._active_workers.append((worker, signals))
        QThreadPool.globalInstance().start(worker)

    def _on_study_stats(self, study_uid: str, stats: StudyStatistics) -> None:
        if not self._is_alive():
            return
        if stats.instances is None and stats.series is None and not stats.size_mb and stats.is_stable is None:
            return
        self._study_stats[study_uid] = stats
        self._refresh_study_row(study_uid)
        if study_uid == self._current_study_uid:
            study = self._study_by_uid(study_uid)
            if study is not None:
                self._patient_label.setText(self._format_patient_header(study))
        self._update_selection_summary()

    def _populate_series(self, study_uid: str) -> None:
        """Fill the right pane with the series of *study_uid*."""
        series = self._series_cache.get(study_uid)
        if series is None:
            self._prefetch_series(study_uid, force=True)
            self._series_list.clear()
            self._series_header.setText(tr("orthanc.series_loading"))
            self._series_actions.setVisible(False)
            self._update_empty_states()
            return
        selected = self._selected_series.get(study_uid, set())
        self._series_list.blockSignals(True)
        self._series_list.clear()
        for entry in series:
            item = _StudyItem()
            item.setData(0, ROLE_ROW, self._make_series_row(entry))
            item.setData(0, ROLE_UID, entry.series_uid)
            item.setData(0, ROLE_CHECKED, entry.series_uid in selected)
            item.setSizeHint(0, QSize(0, SERIES_ROW_HEIGHT))
            pixmap = self._preview_loader.cached(study_uid, entry.series_uid)
            if pixmap is not None:
                item.setData(0, ROLE_PIXMAP, pixmap)
            self._series_list.addTopLevelItem(item)
        self._series_list.blockSignals(False)
        error = self._series_errors.get(study_uid)
        if error and not series:
            self._series_header.setText(tr("orthanc.series_query_error", message=error[:120]))
        else:
            self._series_header.setText(tr("orthanc.series_header", count=len(series)))
        self._series_actions.setVisible(bool(series))
        self._update_empty_states()
        self._request_visible_previews()

    def _make_series_row(self, series: SeriesInfo) -> SeriesRow:
        title = (series.description or "").strip() or tr("orthanc.series_no_description")
        if series.series_number:
            title = f"{series.series_number}. {title}"
        subtitle_parts = [part for part in (series.modality, series.body_part) if part]
        if series.instance_count:
            subtitle_parts.append(tr("orthanc.badge_instances", count=series.instance_count))
        return SeriesRow(
            series=series,
            title=title,
            subtitle=" · ".join(subtitle_parts),
            thumb_badge=series.modality,
        )

    def _on_study_check_toggled(self, item: QTreeWidgetItem) -> None:
        study_uid = item.data(0, ROLE_UID)
        if not study_uid:
            return
        study_uid = str(study_uid)
        currently_checked = bool(item.data(0, ROLE_CHECKED))
        self._set_study_selected(study_uid, not currently_checked)

    def _set_study_selected(self, study_uid: str, selected: bool) -> None:
        series = self._series_cache.get(study_uid)
        if selected:
            self._selected_all.add(study_uid)
            if series is not None:
                self._selected_series[study_uid] = {s.series_uid for s in series if s.series_uid}
            elif study_uid not in self._series_loaded:
                self._prefetch_series(study_uid, force=True)
        else:
            self._selected_all.discard(study_uid)
            self._selected_series.pop(study_uid, None)
        self._sync_study_item_state_by_uid(study_uid)
        if study_uid == self._current_study_uid:
            self._sync_series_items()
        self._update_load_button()
        self._update_selection_summary()
        self._update_studies_header()

    def _on_series_check_toggled(self, item: QTreeWidgetItem) -> None:
        if not self._current_study_uid:
            return
        series_uid = item.data(0, ROLE_UID)
        if not series_uid:
            return
        selected = set(self._selected_series.get(self._current_study_uid, set()))
        if bool(item.data(0, ROLE_CHECKED)):
            selected.discard(str(series_uid))
        else:
            selected.add(str(series_uid))
        self._selected_series[self._current_study_uid] = selected
        known = {s.series_uid for s in self._series_cache.get(self._current_study_uid, [])}
        if known and selected >= known:
            self._selected_all.add(self._current_study_uid)
        else:
            self._selected_all.discard(self._current_study_uid)
        item.setData(0, ROLE_CHECKED, str(series_uid) in selected)
        self._sync_study_item_state_by_uid(self._current_study_uid)
        self._update_load_button()
        self._update_selection_summary()

    def _set_all_series_checked(self, checked: bool) -> None:
        if not self._current_study_uid:
            return
        self._set_study_selected(self._current_study_uid, checked)

    def _sync_series_items(self) -> None:
        selected = self._selected_series.get(self._current_study_uid, set())
        self._series_list.blockSignals(True)
        for index in range(self._series_list.topLevelItemCount()):
            item = self._series_list.topLevelItem(index)
            series_uid = str(item.data(0, ROLE_UID) or "")
            item.setData(0, ROLE_CHECKED, series_uid in selected)
        self._series_list.blockSignals(False)

    def _sync_study_item_state_by_uid(self, study_uid: str) -> None:
        for index in range(self._studies_list.topLevelItemCount()):
            item = self._studies_list.topLevelItem(index)
            if item.data(0, ROLE_UID) == study_uid:
                self._sync_study_item_state(item)
                return

    def _sync_study_item_state(self, item: QTreeWidgetItem) -> None:
        study_uid = str(item.data(0, ROLE_UID) or "")
        checked, partial = self._study_check_state(study_uid)
        item.setData(0, ROLE_CHECKED, checked)
        item.setData(0, ROLE_PARTIAL, partial)

    def _study_check_state(self, study_uid: str) -> tuple[bool, bool]:
        selected = self._selected_series.get(study_uid)
        known = {s.series_uid for s in self._series_cache.get(study_uid, [])}
        if known:
            selected = selected or set()
            if selected >= known:
                return True, False
            if selected:
                return False, True
            return False, False
        if study_uid in self._selected_all:
            return True, False
        return False, False

    def _on_select_all_studies(self) -> None:
        for index in range(self._studies_list.topLevelItemCount()):
            item = self._studies_list.topLevelItem(index)
            study_uid = str(item.data(0, ROLE_UID) or "")
            if study_uid and not item.isHidden():
                self._set_study_selected(study_uid, True)

    def _on_clear_selection(self) -> None:
        self._selected_all.clear()
        self._selected_series.clear()
        for index in range(self._studies_list.topLevelItemCount()):
            self._sync_study_item_state(self._studies_list.topLevelItem(index))
        self._sync_series_items()
        self._update_load_button()
        self._update_selection_summary()

    def _update_load_button(self) -> None:
        if self._downloading:
            return
        has_checked = len(self._collect_all_checked_series()) > 0
        self._load_btn.setEnabled(has_checked)
        self._save_disk_btn.setEnabled(has_checked)

    def _collect_all_checked_series(self) -> list[tuple[str, list[str]]]:
        """Collect all (study_uid, series_uids) pairs across visible studies.

        Studies hidden by the date filter are skipped: their checked series
        are invisible to the user and must not be silently downloaded.
        """
        hidden = self._hidden_study_uids()
        result: list[tuple[str, list[str]]] = []
        ordered = list(dict.fromkeys([*self._selected_all, *self._selected_series]))
        for study_uid in ordered:
            if not study_uid or study_uid in hidden:
                continue
            known = [entry.series_uid for entry in self._series_cache.get(study_uid, []) if entry.series_uid]
            if study_uid in self._selected_all:
                # "Whole study": every series we know about.  While the series
                # list is still loading the entry carries an empty list — the
                # selection is real, and ``_ensure_selection_ready`` fetches the
                # list before anything is downloaded.
                uids = known or sorted(self._selected_series.get(study_uid, set()))
            else:
                selected = self._selected_series.get(study_uid, set())
                uids = [uid for uid in known if uid in selected] if known else sorted(selected)
            result.append((study_uid, uids))
        return result

    def _hidden_study_uids(self) -> set[str]:
        hidden: set[str] = set()
        for index in range(self._studies_list.topLevelItemCount()):
            item = self._studies_list.topLevelItem(index)
            if item.isHidden():
                uid = str(item.data(0, ROLE_UID) or "")
                if uid:
                    hidden.add(uid)
        return hidden

    def _selected_study_uids(self) -> list[str]:
        return [uid for uid, _series in self._collect_all_checked_series()]

    def _update_selection_summary(self) -> None:
        pairs = self._collect_all_checked_series()
        studies = len(pairs)
        series = sum(len(uids) for _uid, uids in pairs)
        size_mb = 0.0
        size_known = False
        for study_uid, uids in pairs:
            stats = self._study_stats.get(study_uid)
            known = {s.series_uid for s in self._series_cache.get(study_uid, [])}
            if stats is not None and stats.size_mb and known:
                share = len(uids) / max(1, len(known))
                size_mb += float(stats.size_mb) * share
                size_known = True
        if not studies:
            self._summary_label.setText(tr("orthanc.selection_empty"))
            return
        parts = [
            tr("orthanc.summary_studies", count=studies),
            tr("orthanc.summary_series", count=series),
        ]
        if size_known and size_mb > 0:
            parts.append(f"≈ {format_size_mb(size_mb)}")
        self._summary_label.setText(tr("orthanc.selection_summary", summary=" · ".join(parts)))

    def _update_studies_header(self) -> None:
        total = self._studies_list.topLevelItemCount()
        visible = sum(1 for i in range(total) if not self._studies_list.topLevelItem(i).isHidden())
        if total and visible != total:
            text = tr("orthanc.studies_header_filtered", visible=visible, total=total)
        else:
            text = tr("orthanc.studies_header", count=total)
        extra = self._studies_selected_off_list()
        if extra:
            # Studies ticked from the patient history are real downloads but
            # have no row here — say so instead of showing a wrong count.
            text = tr("orthanc.studies_header_extra", base=text, count=extra)
        self._studies_header.setText(text)

    def _studies_selected_off_list(self) -> int:
        """How many ticked studies are outside the current result set."""
        listed = {
            str(self._studies_list.topLevelItem(i).data(0, ROLE_UID))
            for i in range(self._studies_list.topLevelItemCount())
        }
        return sum(1 for uid in self._selected_all if uid and uid not in listed)

    def _update_empty_states(self) -> None:
        self._studies_stack.setCurrentIndex(0 if self._studies_list.topLevelItemCount() else 1)
        self._series_stack.setCurrentIndex(0 if self._series_list.topLevelItemCount() else 1)
        if not self._series_list.topLevelItemCount() and self._current_study_uid:
            self._empty_series_label.setText(tr("orthanc.series_loading"))
        else:
            self._empty_series_label.setText(tr("orthanc.empty_series"))
        self._patient_label.setVisible(bool(self._current_study_uid))

    # ── filters / sorting ───────────────────────────────────────────
    def _date_filter_days(self) -> int:
        for days, button in self._period_buttons.items():
            if button.isChecked():
                return days
        return 0

    def _filter_studies_by_date(self, days: int) -> None:
        """Hide/show study rows based on the selected date filter."""
        if days <= 0:
            for index in range(self._studies_list.topLevelItemCount()):
                self._studies_list.topLevelItem(index).setHidden(False)
        else:
            cutoff = datetime.now() - timedelta(days=days)
            for index in range(self._studies_list.topLevelItemCount()):
                item = self._studies_list.topLevelItem(index)
                raw_date = item.data(0, _SORT_ROLE) or ""
                try:
                    item_date = datetime.strptime(str(raw_date)[:8], "%Y%m%d")
                except ValueError:
                    item.setHidden(False)
                    continue
                item.setHidden(item_date < cutoff)
        self._update_studies_header()
        self._update_load_button()
        self._update_selection_summary()

    def _on_date_filter_changed(self, _button) -> None:
        self._filter_studies_by_date(self._date_filter_days())
        self._prefetch_visible_studies()

    def _on_sort_changed(self) -> None:
        mode = self._sort_combo.currentData()
        if not mode:
            return
        self._sort_mode = str(mode)
        if not self._studies:
            return
        current = self._current_study_uid
        self._build_study_rows(self._studies)
        self._filter_studies_by_date(self._date_filter_days())
        if current:
            self._select_study_row(current)
        self._request_visible_previews()

    def _select_study_row(self, study_uid: str) -> None:
        for index in range(self._studies_list.topLevelItemCount()):
            item = self._studies_list.topLevelItem(index)
            if item.data(0, ROLE_UID) == study_uid:
                self._studies_list.setCurrentItem(item)
                return

    # ── patient history (prior studies of the same patient) ─────────
    def _request_patient_history(self, study: StudyInfo) -> None:
        """Fetch the other studies of this patient (one query per patient)."""
        patient_id = (study.patient_id or "").strip()
        self._history_patient = patient_id
        if not patient_id:
            self._render_patient_history("", [])
            return
        cached = self._history_cache.get(patient_id)
        if cached is not None:
            self._render_patient_history(patient_id, cached)
            return
        if patient_id in self._history_in_flight:
            return
        self._history_in_flight.add(patient_id)

        def _query() -> list:
            if self._query_service is not None:
                return self._query_service.query_studies(patient_id=patient_id)
            return self._client.query_studies(patient_id=patient_id)

        signals = _StudyQuerySignals()
        signals.finished.connect(
            lambda studies, error, pid=patient_id: self._on_patient_history_loaded(pid, studies, error)
        )
        worker = _StudyQueryWorker(_query, signals)
        self._active_workers.append((worker, signals))
        QThreadPool.globalInstance().start(worker)

    def _on_patient_history_loaded(self, patient_id: str, studies: object, error: str | None) -> None:
        self._history_in_flight.discard(patient_id)
        if not self._is_alive():
            return
        if error:
            log.debug("[DLG] patient history query failed: %s", error)
        # A server that ignores the PatientID filter must not leak other
        # patients into the strip.
        others = [
            study
            for study in (studies or [])
            if isinstance(study, StudyInfo) and study.study_uid and (study.patient_id or "") == patient_id
        ]
        others.sort(key=lambda s: (s.study_date or "", s.study_time or ""), reverse=True)
        self._history_cache[patient_id] = others[:_HISTORY_CACHE_LIMIT]
        if patient_id == self._history_patient:
            self._render_patient_history(patient_id, self._history_cache[patient_id])

    def _render_patient_history(self, patient_id: str, studies: list[StudyInfo]) -> None:
        self._clear_history_chips()
        if not patient_id:
            self._history_panel.hide()
            return
        others = [s for s in studies if s.study_uid != self._current_study_uid]
        if not others:
            self._history_panel.hide()
            return
        self._history_label.setText(tr("orthanc.history_label", count=str(len(others))))
        for study in others[:_HISTORY_LIMIT]:
            self._history_chips_layout.addWidget(self._make_history_chip(study))
        self._history_panel.show()

    def _make_history_chip(self, study: StudyInfo) -> QPushButton:
        from echo_personal_tool.domain.services.patient_display import format_dicom_date

        date_text = format_dicom_date(study.study_date) or study.study_date or "—"
        description = (study.study_description or "").strip()
        label = f"{date_text} · {description[:18]}" if description else date_text
        chip = QPushButton(label)
        chip.setObjectName("historyChip")
        chip.setCursor(Qt.CursorShape.PointingHandCursor)
        chip.setToolTip(tr("orthanc.history_chip_tooltip"))
        chip.clicked.connect(lambda _checked=False, uid=study.study_uid: self._on_history_chip_clicked(uid))
        return chip

    def _clear_history_chips(self) -> None:
        while self._history_chips_layout.count():
            item = self._history_chips_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _on_history_chip_clicked(self, study_uid: str) -> None:
        """Tick a prior study for download and reveal it when it is listed."""
        study = next(
            (s for s in self._history_cache.get(self._history_patient, []) if s.study_uid == study_uid),
            None,
        )
        item = self._find_study_item(study_uid)
        if study is None and item is None:
            return  # never invent a selection out of a stale chip
        if item is not None:
            self._studies_list.setCurrentItem(item)
            self._studies_list.scrollToItem(item)
        self._set_study_selected(study_uid, True)
        if study is not None:
            from echo_personal_tool.domain.services.patient_display import format_dicom_date

            date_text = format_dicom_date(study.study_date) or study.study_date or "—"
            self._set_status(tr("orthanc.history_marked", date=date_text))

    def _find_study_item(self, study_uid: str) -> QTreeWidgetItem | None:
        for index in range(self._studies_list.topLevelItemCount()):
            item = self._studies_list.topLevelItem(index)
            if item.data(0, ROLE_UID) == study_uid:
                return item
        return None

    # ── download orchestration (unchanged semantics) ────────────────
    def _ensure_selection_ready(self, action: str) -> bool:
        """Fetch the series lists still missing for the current selection.

        Returns True when the caller may proceed immediately; otherwise the
        action is queued and resumed from ``_on_series_loaded``.
        """
        hidden = self._hidden_study_uids()
        candidates = dict.fromkeys([*self._selected_all, *self._selected_series])
        # A study whose series list is *in flight* is not ready either: without
        # its UIDs the download would silently fetch nothing.
        missing = [
            study_uid
            for study_uid in candidates
            if study_uid and study_uid not in hidden and study_uid not in self._series_cache
        ]
        if not missing:
            self._pending_action = None
            return True
        self._pending_action = action
        self._set_status(tr("orthanc.preparing_selection"))
        for study_uid in missing:
            self._prefetch_series(study_uid, force=True)
        return False

    def _maybe_run_pending_action(self) -> None:
        action = self._pending_action
        if action is None or self._downloading or not self._is_alive():
            return
        pending = dict.fromkeys([*self._selected_all, *self._selected_series])
        if any(uid in self._series_loading for uid in pending if uid not in self._series_cache):
            return
        self._pending_action = None
        if action == "disk":
            self._on_save_to_disk()
        else:
            self._on_load()

    def _on_load(self) -> None:
        from echo_personal_tool.presentation.ui_animations import set_button_loading

        if not self._ensure_selection_ready("load"):
            return
        all_series = self._collect_all_checked_series()
        log.info("[DLG] _on_load: checked_series=%d", len(all_series))
        if not all_series:
            return

        session_id = self._cache.create_session()
        self._session_id = session_id
        self._downloading = True
        self._close_pending = False
        # A fresh download batch must not inherit StudyMetadata from a previous
        # (possibly partially failed) batch whose session files were removed.
        self._downloaded_studies = []
        self._result = None
        set_button_loading(self._load_btn, True, "…")
        self._cancel_btn.setText(tr("orthanc.cancel_download"))
        self._cancel_btn.setEnabled(True)
        self._find_btn.setEnabled(False)
        self._studies_list.setEnabled(False)
        self._series_list.setEnabled(False)
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.show()
        self._set_status(tr("orthanc.preparing"))

        self._partial_download_warnings = []
        self._pending_downloads = list(all_series)
        self._completed_downloads = 0
        self._failed_downloads = 0
        self._total_studies = len(all_series)
        self._study_states.clear()
        self._start_next_download()

    def _on_save_to_disk(self) -> None:
        """Download selected series to a user-chosen directory on disk."""
        from echo_personal_tool.presentation.ui_animations import set_button_loading

        if not self._ensure_selection_ready("disk"):
            return
        all_series = self._collect_all_checked_series()
        log.info("[DLG] _on_save_to_disk: checked_series=%d", len(all_series))
        if not all_series:
            return

        # Ask user for directory
        directory = QFileDialog.getExistingDirectory(
            self,
            tr("orthanc.select_directory"),
            "",
            QFileDialog.Option.ShowDirsOnly,
        )
        if not directory:
            return

        # Start download to disk
        session_id = self._cache.create_session()
        self._session_id = session_id
        self._downloading = True
        self._close_pending = False
        self._downloaded_studies = []
        self._result = None
        self._save_to_disk_path = directory
        set_button_loading(self._save_disk_btn, True, "…")
        self._cancel_btn.setText(tr("orthanc.cancel_download"))
        self._cancel_btn.setEnabled(True)
        self._find_btn.setEnabled(False)
        self._studies_list.setEnabled(False)
        self._series_list.setEnabled(False)
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.show()
        self._set_status(tr("orthanc.saving_to_disk", path=directory))

        self._partial_download_warnings = []
        self._pending_downloads = list(all_series)
        self._completed_downloads = 0
        self._failed_downloads = 0
        self._total_studies = len(all_series)
        self._study_states.clear()
        self._start_next_download_to_disk()

    def _make_download_worker(self, study_uid: str, series_uids: list[str]) -> OrthancDownloadWorker:
        return OrthancDownloadWorker(
            self._client,
            self._cache,
            self._session_id,  # type: ignore[arg-type]
            study_uid,
            series_uids,
            self,
            server_settings=self._server_settings,
            base_url=self._base_url,
            username=self._username,
            password=self._password,
            retrieve_service=self._retrieve_service,
        )

    def _start_next_download(self) -> None:
        log.info(
            "[DLG] _start_next_download: pending=%d completed=%d total=%d",
            len(self._pending_downloads),
            self._completed_downloads,
            self._total_studies,
        )
        if not self._pending_downloads:
            if self._session_id is None:
                return
            if self._failed_downloads > 0:
                if self._completed_downloads > self._failed_downloads:
                    # Some studies succeeded: keep them (do not wipe the whole
                    # session) and let the user open the successful ones.
                    self._on_partial_done()
                else:
                    # Nothing succeeded — discard the session and report.
                    self._on_failed("", tr("orthanc.partial_failed"))
            else:
                first_study = self._downloaded_studies[0].study_uid if self._downloaded_studies else ""
                self._on_done(self._session_id, first_study)
            return

        study_uid, series_uids = self._pending_downloads.pop(0)
        self._set_status(
            tr("orthanc.loading_progress", current=self._completed_downloads + 1, total=self._total_studies)
        )
        self._set_study_state(study_uid, tr("orthanc.state_downloading"), "accent")
        worker = self._make_download_worker(study_uid, series_uids)
        self._worker = worker
        worker.signals.progress.connect(self._on_progress)
        worker.signals.status.connect(self._on_status)
        worker.signals.done.connect(self._on_single_study_done)
        worker.signals.failed.connect(self._on_single_study_failed)
        worker.signals.partial_failed.connect(self._on_partial_instance_failure)
        worker.signals.cancelled.connect(self._on_cancelled)
        worker.signals.series_done.connect(self._on_series_done)
        worker.signals.studies_ready.connect(self._on_studies_ready)
        QThreadPool.globalInstance().start(worker)

    def _start_next_download_to_disk(self) -> None:
        """Download next study to disk directory."""
        log.info(
            "[DLG] _start_next_download_to_disk: pending=%d completed=%d total=%d",
            len(self._pending_downloads),
            self._completed_downloads,
            self._total_studies,
        )
        if not self._pending_downloads:
            if self._session_id is None:
                return
            if self._completed_downloads > self._failed_downloads:
                # Copy whatever was downloaded successfully — a partial batch
                # must not silently discard the studies that did succeed.
                self._on_disk_download_done(partial=self._failed_downloads > 0)
            else:
                self._on_failed("", tr("orthanc.partial_failed"))
            return

        study_uid, series_uids = self._pending_downloads.pop(0)
        self._set_status(
            tr("orthanc.disk_download_progress", current=self._completed_downloads + 1, total=self._total_studies)
        )
        self._set_study_state(study_uid, tr("orthanc.state_downloading"), "accent")
        worker = self._make_download_worker(study_uid, series_uids)
        self._worker = worker
        worker.signals.progress.connect(self._on_progress)
        worker.signals.status.connect(self._on_status)
        worker.signals.done.connect(self._on_single_study_done_to_disk)
        worker.signals.failed.connect(self._on_single_study_failed)
        worker.signals.partial_failed.connect(self._on_partial_instance_failure)
        worker.signals.cancelled.connect(self._on_cancelled)
        worker.signals.series_done.connect(self._on_series_done)
        worker.signals.studies_ready.connect(self._on_studies_ready)
        QThreadPool.globalInstance().start(worker)

    def _set_study_state(self, study_uid: str, text: str, kind: str = "warning") -> None:
        """Show a transient state chip on a study row (загрузка / готово / ошибка)."""
        if not study_uid:
            return
        self._study_states[study_uid] = (text, kind)
        self._refresh_study_row(study_uid)

    def _on_cancel(self) -> None:
        if self._downloading and self._worker is not None:
            self._set_status(tr("orthanc.download_cancelled"))
            self._cancel_btn.setEnabled(False)
            self._worker.cancel()
            self._force_close_timer.start(_CANCEL_FORCE_CLOSE_MS)
            return
        if self._downloading:
            # Nothing is running anymore — drop the stuck flag and close now
            # instead of waiting for the force-close timer.
            log.info("[DLG] cancel with no active worker, force closing")
            self._force_close_if_still_downloading()
            return
        self.reject()

    def _force_close_if_still_downloading(self) -> None:
        if not self._is_alive():
            return
        if not self._downloading:
            return
        self._downloading = False
        self._worker = None
        if self._session_id is not None:
            self._cache.clear_session(self._session_id)
            self._session_id = None
        self._progress.hide()
        self._shutdown()
        super().reject()

    def _short_uid(self, series_uid: str) -> str:
        return series_uid[:12] + "…" if len(series_uid) > 12 else series_uid

    def _on_progress(self, current: int, total: int, series_uid: str) -> None:
        if not self._is_alive():
            return
        if total > 0:
            self._progress.setRange(0, total)
            self._progress.setValue(min(current, total))
        short_uid = self._short_uid(series_uid)
        self._set_status(tr("orthanc.loading_detail", current=current, total=total, uid=short_uid))

    def _on_status(self, message: str) -> None:
        if not self._is_alive():
            return
        self._set_status(message)

    def _on_series_done(self, series_uid: str, status: str) -> None:
        if not self._is_alive():
            return
        if status == "failed":
            self._set_status(tr("orthanc.series_error_status", uid=self._short_uid(series_uid)))

    def _on_studies_ready(self, studies: list[StudyMetadata]) -> None:
        if not self._is_alive():
            return
        log.info("[DLG] _on_studies_ready: %d studies", len(studies))
        for s in studies:
            total_inst = sum(len(sr.instances) for sr in s.series)
            log.info("[DLG]   study_uid=%s series=%d instances=%d", s.study_uid[:16], len(s.series), total_inst)
        self._downloaded_studies.extend(studies)

    def _reset_after_download(self) -> None:
        from echo_personal_tool.presentation.ui_animations import set_button_loading

        self._downloading = False
        self._worker = None
        self._force_close_timer.stop()
        set_button_loading(self._load_btn, False)
        set_button_loading(self._save_disk_btn, False)

    def _on_single_study_done(self, session_id: str, study_uid: str) -> None:
        if not self._is_alive():
            return
        log.info("[DLG] _on_single_study_done: uid=%s", study_uid[:16])
        self._completed_downloads += 1
        self._set_study_state(study_uid, tr("orthanc.state_done"), "success")
        self._set_status(tr("orthanc.series_done", current=self._completed_downloads, total=self._total_studies))
        self._start_next_download()

    def _on_single_study_done_to_disk(self, session_id: str, study_uid: str) -> None:
        """Handle single study download completion when saving to disk."""
        if not self._is_alive():
            return
        log.info("[DLG] _on_single_study_done_to_disk: uid=%s", study_uid[:16])
        self._completed_downloads += 1
        self._set_study_state(study_uid, tr("orthanc.state_done"), "success")
        self._set_status(
            tr("orthanc.disk_download_progress", current=self._completed_downloads, total=self._total_studies)
        )
        self._start_next_download_to_disk()

    def _on_disk_download_done(self, *, partial: bool = False) -> None:
        """Handle completion of all downloads to disk — copy files from cache to target."""
        if not self._is_alive():
            return
        log.info(
            "[DLG] _on_disk_download_done: path=%s partial=%s",
            self._save_to_disk_path,
            partial,
        )
        # Worker already finished: no cancel handshake is pending anymore.
        self._worker = None

        # Copy files from cache to user-selected directory (whatever succeeded)
        copied_count = 0
        copy_error: str | None = None
        if self._session_id is not None:
            session_dir = self._cache.session_path(self._session_id)
            if session_dir.is_dir():
                target_dir = Path(self._save_to_disk_path)
                try:
                    copied_count = self._copy_session_files(session_dir, target_dir)
                    log.info("[DLG] Copied %d files to %s", copied_count, self._save_to_disk_path)
                except OSError as exc:
                    # The reset below must run even here: skipping it leaves
                    # ``_downloading`` stuck and locks the dialog forever.
                    copy_error = str(exc)
                    log.warning("[DLG] copy to %s failed: %s", self._save_to_disk_path, exc)

        self._reset_after_download()
        self._session_id = None
        self._progress.setValue(self._progress.maximum())
        if copy_error is not None:
            message = tr("orthanc.download_error.body", message=self._clip(copy_error, _DIALOG_TEXT_LIMIT))
            self._set_status(message)
            self._progress.hide()
            self._set_lists_enabled(True)
            self._cancel_btn.setText(tr("orthanc.cancel"))
            self._cancel_btn.setEnabled(True)
            self._update_load_button()
            QMessageBox.warning(
                self,
                tr("orthanc.download_error.title"),
                message,
            )
            return
        partial_warning = self._partial_instance_warning_text()
        if partial or partial_warning:
            messages: list[str] = []
            if partial:
                saved = self._completed_downloads - self._failed_downloads
                messages.append(
                    tr(
                        "orthanc.disk_download_partial",
                        path=self._save_to_disk_path,
                        saved=str(saved),
                        total=str(self._total_studies),
                    )
                )
            if partial_warning:
                messages.append(partial_warning)
            message = self._clip("\n".join(messages), _DIALOG_TEXT_LIMIT)
            self._set_status(message)
            QMessageBox.warning(
                self,
                tr("orthanc.download_error.title"),
                message,
            )
        else:
            message = tr("orthanc.disk_download_complete", path=self._save_to_disk_path)
            self._set_status(message)
            QMessageBox.information(
                self,
                tr("orthanc.download_complete"),
                message,
            )
        self.accept()

    def _set_lists_enabled(self, enabled: bool) -> None:
        self._studies_list.setEnabled(enabled)
        self._series_list.setEnabled(enabled)
        self._find_btn.setEnabled(enabled)

    @staticmethod
    def _copy_session_files(session_dir: Path, target_dir: Path) -> int:
        """Export a download session, preserving <study>/<series>/<file>.dcm."""
        copied_count = 0
        for study_dir in session_dir.iterdir():
            if not study_dir.is_dir():
                continue
            study_target = target_dir / study_dir.name
            study_target.mkdir(parents=True, exist_ok=True)
            for entry in sorted(study_dir.iterdir()):
                if entry.is_dir():
                    # Legacy layout: <study>/<series>/<sop>.dcm
                    files = [(f, entry.name) for f in sorted(entry.glob("*.dcm"))]
                elif entry.suffix.lower() == ".dcm":
                    # Current layout: <study>/<sop>.dcm
                    files = [(entry, None)]
                else:
                    continue
                for dcm_file, legacy_series in files:
                    series_name = OrthancStudyDialog._series_name_for(dcm_file, legacy_series)
                    series_target = study_target / series_name if series_name else study_target
                    series_target.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(dcm_file, series_target / dcm_file.name)
                    copied_count += 1
        return copied_count

    @staticmethod
    def _series_name_for(dcm_file: Path, legacy_series_name: str | None) -> str:
        """Series folder name for an exported instance ("" = study folder).

        Legacy cache sessions keep the series directory name on disk; the
        current flat layout has to read it back from the DICOM header so the
        exported structure stays the same.
        """
        if legacy_series_name:
            return legacy_series_name
        try:
            import pydicom

            ds = pydicom.dcmread(str(dcm_file), stop_before_pixels=True, force=True)
            uid = str(getattr(ds, "SeriesInstanceUID", "") or "").strip()
            if uid:
                return uid
        except Exception:  # noqa: BLE001
            log.warning("[DLG] cannot read SeriesInstanceUID from %s", dcm_file, exc_info=True)
        return ""

    @staticmethod
    def _clip(text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        return text[: limit - 1].rstrip() + "…"

    def _set_status(self, text: str) -> None:
        """Show ``text`` in the status line without resizing the dialog.

        The full text goes to the log; the label gets at most
        ``_STATUS_TEXT_LIMIT`` characters so a long error chain cannot stretch
        the window past its ``resize(1120, 660)``.
        """
        log.debug("[DLG] status: %s", text)
        self._status_label.setText(self._clip(text, _STATUS_TEXT_LIMIT))

    def _on_partial_instance_failure(self, study_uid: str, message: str) -> None:
        """Remember per-instance failures while preserving successfully fetched files."""
        if not self._is_alive():
            return
        log.warning("[DLG] partial instance download: study=%s message=%s", study_uid[:16], message)
        self._partial_download_warnings.append(self._clip(message, _DIALOG_TEXT_LIMIT))

    def _partial_instance_warning_text(self) -> str:
        return self._clip("\n".join(self._partial_download_warnings), _DIALOG_TEXT_LIMIT)

    def _on_single_study_failed(self, _uid: str, message: str) -> None:
        if not self._is_alive():
            return
        log.warning("[DLG] _on_single_study_failed: uid=%s msg=%s", _uid[:16] if _uid else "?", message)
        self._completed_downloads += 1
        self._failed_downloads += 1
        self._set_study_state(_uid, tr("orthanc.state_failed"), "error")
        self._set_status(
            tr(
                "orthanc.series_error",
                current=self._completed_downloads,
                total=self._total_studies,
                message=message,
            )
        )
        self._start_next_download()

    def _on_partial_done(self) -> None:
        """Some queued studies failed but at least one succeeded.

        Keep the session (and the parsed StudyMetadata) so the successfully
        downloaded studies can be opened, and clearly warn about the rest.
        """
        if not self._is_alive():
            return
        saved = self._completed_downloads - self._failed_downloads
        log.warning(
            "[DLG] _on_partial_done: saved=%d failed=%d total=%d",
            saved,
            self._failed_downloads,
            self._total_studies,
        )
        self._reset_after_download()
        if self._session_id is None:
            return
        session_id = self._session_id
        self._session_id = None
        first_study = self._downloaded_studies[0].study_uid if self._downloaded_studies else ""
        self._result = (session_id, first_study)
        self._progress.setValue(self._progress.maximum())
        message = tr(
            "orthanc.partial_done",
            saved=str(saved),
            total=str(self._total_studies),
        )
        details = self._partial_instance_warning_text()
        if details:
            message = f"{message}\n{details}"
        message = self._clip(message, _DIALOG_TEXT_LIMIT)
        self._set_status(message)
        QMessageBox.warning(
            self,
            tr("orthanc.download_error.title"),
            message,
        )
        self.accept()

    def _on_done(self, session_id: str, study_uid: str) -> None:
        if not self._is_alive():
            return
        log.info(
            "[DLG] _on_done: session=%s studies_downloaded=%d",
            session_id[:8] if session_id else "?",
            len(self._downloaded_studies),
        )
        self._reset_after_download()
        self._session_id = None
        self._result = (session_id, study_uid)
        self._progress.setValue(self._progress.maximum())
        partial_warning = self._partial_instance_warning_text()
        if partial_warning:
            self._set_status(partial_warning)
            QMessageBox.warning(
                self,
                tr("orthanc.download_error.title"),
                partial_warning,
            )
        else:
            self._set_status(tr("orthanc.download_complete"))
        self.accept()

    def _on_failed(self, _uid: str, message: str) -> None:
        if not self._is_alive():
            return
        log.warning("[DLG] _on_failed: uid=%s msg=%s", _uid[:16] if _uid else "?", message)
        self._reset_after_download()
        if self._pending_downloads and self._session_id is not None:
            self._start_next_download()
            return
        if self._session_id is not None:
            self._cache.clear_session(self._session_id)
            self._session_id = None
        self._downloaded_studies = []
        self._progress.hide()
        self._set_lists_enabled(True)
        self._cancel_btn.setText(tr("orthanc.cancel"))
        self._cancel_btn.setEnabled(True)
        self._update_load_button()
        QMessageBox.warning(
            self,
            tr("orthanc.download_error.title"),
            tr("orthanc.download_error.body", message=self._clip(message, _DIALOG_TEXT_LIMIT)),
        )

    def _on_cancelled(self, _session_id: str) -> None:
        if not self._is_alive():
            return
        self._reset_after_download()
        self._session_id = None
        self._progress.hide()
        self._set_lists_enabled(True)
        self._cancel_btn.setText(tr("orthanc.cancel"))
        self._cancel_btn.setEnabled(True)
        self._update_load_button()
        self._shutdown()
        self._reject_timer.start(0)
