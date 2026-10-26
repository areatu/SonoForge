"""The handbook window S1 (UI-5 PR-2, spec §4.7, §8.5, §9; UD-06, UD-15).

«Справочник — окно S1 и карточка S2»: the card answers «это значение в норме?»
at the row of a measurement, the window answers «а как это вообще измеряют и
что значит градация?» — with the picture, so the card itself can stay free of
images (UD-06).

Shape of the window (mockup `S1-reference-window.png`):

* a caption row in the style of Windows 11 — the app glyph, the title, the
  search field and the window controls.  Like :class:`AseReferenceDialog` the
  window is frameless and maximizable; the caption is the drag handle;
* themes on the left with the number of parameters, grouped «Сердце» /
  «Сосуды и органы»;
* in the centre — breadcrumb, topic title, the pathology chips, the sex switch
  («Мужчины | Женщины | Оба»), the toggle «Значения пациента» and the table:
  parameter, unit, norm for the sex, one column per gradation and the value of
  the open study;
* on the right — «Иллюстрация» with a counter, the numbered «Как измерять»
  (the ``how_to`` field of UI-5 PR-3), the source and the method of the norm.

The window never computes a norm or a grade itself: :mod:`domain.services.
reference_topics` builds the rows from the same :func:`build_reference_card`
the card S2 uses, so the two surfaces cannot disagree.  Colours of the
gradations come from :mod:`presentation.reference_grades`; every other colour
is a token of the active theme.

Opening: :func:`show_reference_window` keeps one window per session (the
document tabs, the search field and the geometry survive between openings, and
a live QWebEngineView is never torn down mid-session).  «Открыть в справочнике»
of the card S2 calls :meth:`ReferenceWindow.open_at` with the parameter id;
the command palette adds «Справочник: КДР» through the same entry point.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.application.profile_settings import SettingsStore, settings_store_for
from echo_personal_tool.domain.services.reference_data_store import ReferenceDataStore
from echo_personal_tool.domain.services.reference_topics import (
    SEX_BOTH,
    SEX_FEMALE,
    SEX_MALE,
    ReferenceRow,
    TopicView,
    build_topic_view,
    chip_label,
    reference_values,
    search_view,
    topic_entries,
)
from echo_personal_tool.infrastructure.i18n import get_language, tr
from echo_personal_tool.presentation.dark_theme import get_theme_tokens
from echo_personal_tool.presentation.reference_grades import grade_colors
from echo_personal_tool.presentation.ui_metrics import (
    control_height,
    icon_button_size,
    title_bar_height,
)
from echo_personal_tool.presentation.window_chrome.hit_test import start_system_move
from echo_personal_tool.presentation.window_chrome.title_bar import load_icon

_IMAGES_DIR = Path(__file__).resolve().parents[1] / "resources" / "references" / "images"
_GEOMETRY_KEY = "reference_window/geometry"
#: Own settings file of the window (like the document viewer's «ase-reference»).
_SETTINGS_ORG = "sonoforge"
_SETTINGS_APP = "reference-window"
#: The group boundary of the mockup: heart above, vessels and organs below.
_VESSELS_FIRST_SLUG = "carotid_arteries"
#: One cached window per session (see :func:`show_reference_window`).
_CACHED_WINDOW: ReferenceWindow | None = None


def _images_dir() -> Path:
    """Directory of the handbook pictures, frozen-build aware."""
    import sys

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass is not None:
        return Path(meipass) / "echo_personal_tool" / "resources" / "references" / "images"
    return _IMAGES_DIR


def _language() -> str:
    return (get_language() or "en").strip().lower()[:2] or "en"


class _CaptionButton(QPushButton):
    """One window control of the caption (object names drive the theme QSS)."""

    def __init__(self, icon_name: str, tooltip: str, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName(f"{icon_name}Button")
        self.setIcon(load_icon(icon_name))
        self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIconSize(QSize(14, 14))
        self.setFixedSize(QSize(46, title_bar_height(self)))
        self.setFlat(True)


class _ReferenceCaption(QWidget):
    """The drag handle of the frameless window: glyph, title, search, controls."""

    def __init__(self, window: ReferenceWindow) -> None:
        super().__init__(window)
        self.setObjectName("referenceCaption")
        self._window = window
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 0, 0)
        layout.setSpacing(8)
        self._glyph = QLabel(self)
        self._glyph.setPixmap(
            QPixmap(str(self._window.logo_path())).scaled(
                18, 18, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
        )
        self._glyph.setFixedSize(QSize(20, 20))
        layout.addWidget(self._glyph)
        self._title = QLabel(tr("ref_window.title"), self)
        self._title.setObjectName("referenceCaptionTitle")
        layout.addWidget(self._title)
        layout.addStretch(1)
        self.search = QLineEdit(self)
        self.search.setObjectName("referenceSearch")
        self.search.setPlaceholderText(tr("ref_window.search_placeholder"))
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(420)
        self.search.setMinimumWidth(260)
        self.search.addAction(load_icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        layout.addWidget(self.search)
        layout.addStretch(1)
        self._btn_minimize = _CaptionButton("minimize", tr("system_bar.minimize"), self)
        self._btn_minimize.clicked.connect(window.showMinimized)
        self._btn_maximize = _CaptionButton("maximize", tr("system_bar.maximize"), self)
        self._btn_maximize.clicked.connect(window.toggle_maximized)
        self._btn_close = _CaptionButton("close", tr("system_bar.close"), self)
        self._btn_close.clicked.connect(window.close)
        for button in (self._btn_minimize, self._btn_maximize, self._btn_close):
            layout.addWidget(button)
        self.setFixedHeight(title_bar_height(self, padding=16, minimum=34))

    # -- drag: the window manager moves the window (UD-13) -------------------
    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt
        if event.button() == Qt.MouseButton.LeftButton:
            start_system_move(self._window, event.globalPosition().toPoint())
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 - Qt
        if event.button() == Qt.MouseButton.LeftButton:
            self._window.toggle_maximized()
            return
        super().mouseDoubleClickEvent(event)

    def apply_tokens(self) -> None:
        tokens = get_theme_tokens()
        self.setStyleSheet(f"QWidget#referenceCaption {{ background: {tokens['surface.1']}; }}")
        self._title.setStyleSheet(f"color: {tokens['text.1']}; font-weight: 600; border: none;")
        self._btn_maximize.setIcon(load_icon("restore" if self._window.isMaximizedNow() else "maximize"))
        for button in (self._btn_minimize, self._btn_maximize):
            button.setStyleSheet(
                f"QPushButton {{ background: transparent; border: none; }}"
                f"QPushButton:hover {{ background: {tokens['surface.3']}; }}"
            )
        self._btn_close.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; }}"
            f"QPushButton:hover {{ background: {tokens['state.danger.solid']}; }}"
        )


class _TopicRow(QWidget):
    """One topic of the left navigation: name on the left, count on the right."""

    def __init__(self, name: str, count: int, parent: QWidget) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 0, 6, 0)
        layout.setSpacing(6)
        self.name_label = QLabel(name, self)
        self.name_label.setObjectName("referenceTopicName")
        self.count_label = QLabel(str(count), self)
        self.count_label.setObjectName("referenceTopicCount")
        self.count_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.name_label, stretch=1)
        layout.addWidget(self.count_label)


class ReferenceWindow(QDialog):
    """Non-modal window S1: topics, the table of a topic and the illustration."""

    #: «Конструктор…» of the footer — the host opens the constructor of UI-5 PR-3.
    constructor_requested = Signal()
    #: «Источники» of the footer — the host opens the document viewer.
    sources_requested = Signal()

    def __init__(
        self,
        store: ReferenceDataStore | None = None,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = store if store is not None else ReferenceDataStore(language=_language()).load()
        self._language = _language()
        self._sex = SEX_BOTH
        self._values: dict[str, float] = {}
        self._age: int | None = None
        self._view: TopicView | None = None
        self._topic_slug = ""
        self._pathology_name = ""
        self._search_needle = ""
        self._image_paths: tuple[str, ...] = ()
        self._image_index = 0
        self._original_pixmap: QPixmap | None = None
        self._normal_geometry = None
        self._rescale_timer = QTimer(self)
        self._rescale_timer.setSingleShot(True)
        self._rescale_timer.setInterval(0)
        self._rescale_timer.timeout.connect(self._rescale_image)
        self._settings: SettingsStore = settings_store_for(_SETTINGS_ORG, _SETTINGS_APP)
        self._selection_restored = False
        self.setObjectName("referenceWindow")
        self.setWindowTitle(tr("ref_window.title"))
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setModal(False)
        self.setMinimumSize(960, 600)
        self.resize(1360, 860)
        self._build_ui()
        self._sex_buttons[SEX_BOTH].setChecked(True)
        self.apply_theme()
        self._reload_topics()
        if self._store.get_topics():
            self.set_topic(self._store.get_topics()[0].slug)

    # ── construction ─────────────────────────────────────────────────────
    def logo_path(self) -> Path:
        from echo_personal_tool.presentation.dark_theme import get_logo_path

        return get_logo_path()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._caption = _ReferenceCaption(self)
        self._caption.search.textChanged.connect(self._on_search_changed)
        root.addWidget(self._caption)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self._topic_list = QListWidget(self)
        self._topic_list.setObjectName("referenceTopicList")
        self._topic_list.setFrameShape(QFrame.Shape.NoFrame)
        self._topic_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._topic_list.setFixedWidth(236)
        self._topic_list.currentItemChanged.connect(self._on_topic_item_changed)
        body.addWidget(self._topic_list)

        body.addWidget(self._build_center(), stretch=1)
        body.addWidget(self._build_right())

        root.addLayout(body, stretch=1)
        root.addWidget(self._build_footer())

    def _build_center(self) -> QWidget:
        panel = QWidget(self)
        panel.setObjectName("referenceCenter")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 12, 16, 8)
        layout.setSpacing(8)

        self._crumb = QLabel(panel)
        self._crumb.setObjectName("referenceCrumb")
        layout.addWidget(self._crumb)

        self._title_label = QLabel(panel)
        self._title_label.setObjectName("referenceTopicTitle")
        layout.addWidget(self._title_label)

        chips_host = QWidget(panel)
        self._chips_layout = QHBoxLayout(chips_host)
        self._chips_layout.setContentsMargins(0, 0, 0, 0)
        self._chips_layout.setSpacing(4)
        self._chips_layout.addStretch(1)
        self._chip_group = QButtonGroup(self)
        self._chip_group.setExclusive(True)
        layout.addWidget(chips_host)

        controls = QHBoxLayout()
        controls.setSpacing(6)
        self._sex_group = QButtonGroup(self)
        self._sex_group.setExclusive(True)
        self._sex_buttons: dict[str, QPushButton] = {}
        for sex, key in (
            (SEX_MALE, "ref_window.sex_male"),
            (SEX_FEMALE, "ref_window.sex_female"),
            (SEX_BOTH, "ref_window.sex_both"),
        ):
            button = QPushButton(tr(key), panel)
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked, value=sex: self.set_sex(value))
            self._sex_group.addButton(button)
            self._sex_buttons[sex] = button
            controls.addWidget(button)
        self._patient_label = QLabel(panel)
        self._patient_label.setObjectName("referencePatientHint")
        controls.addSpacing(10)
        controls.addWidget(self._patient_label)
        controls.addStretch(1)
        self._values_toggle = QCheckBox(tr("ref_window.values_toggle"), panel)
        self._values_toggle.setChecked(True)
        self._values_toggle.toggled.connect(self._on_values_toggled)
        controls.addWidget(self._values_toggle)
        layout.addLayout(controls)

        self._table = QTableWidget(0, 0, panel)
        self._table.setObjectName("referenceTable")
        self._table.verticalHeader().hide()
        self._table.setShowGrid(False)
        self._table.setWordWrap(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectItems)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._table.currentCellChanged.connect(self._on_current_cell_changed)
        layout.addWidget(self._table, stretch=1)

        self._empty_label = QLabel(tr("ref_window.empty_search"), panel)
        self._empty_label.setObjectName("referenceEmpty")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.hide()
        layout.addWidget(self._empty_label)
        return panel

    def _build_right(self) -> QWidget:
        panel = QWidget(self)
        panel.setObjectName("referenceSide")
        panel.setFixedWidth(340)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(6)
        self._image_title = QLabel(tr("ref_window.illustration"), panel)
        self._image_title.setObjectName("referenceSectionTitle")
        header.addWidget(self._image_title)
        header.addStretch(1)
        self._image_counter = QLabel("", panel)
        self._image_counter.setObjectName("referenceImageCounter")
        self._btn_prev = QPushButton("‹", panel)
        self._btn_prev.setObjectName("referenceImageNav")
        self._btn_prev.setFixedSize(*icon_button_size(self._btn_prev, "‹", minimum=22))
        self._btn_prev.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_prev.clicked.connect(self._previous_image)
        self._btn_next = QPushButton("›", panel)
        self._btn_next.setObjectName("referenceImageNav")
        self._btn_next.setFixedSize(*icon_button_size(self._btn_next, "›", minimum=22))
        self._btn_next.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_next.clicked.connect(self._next_image)
        header.addWidget(self._image_counter)
        header.addWidget(self._btn_prev)
        header.addWidget(self._btn_next)
        layout.addLayout(header)

        self._image_label = QLabel(panel)
        self._image_label.setObjectName("referenceImage")
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setMinimumHeight(220)
        self._image_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._image_label.installEventFilter(self)
        layout.addWidget(self._image_label, stretch=3)

        scroll = QScrollArea(panel)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setObjectName("referenceSideScroll")
        inner = QWidget(scroll)
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.setSpacing(6)

        self._caption_label = QLabel("", inner)
        self._caption_label.setObjectName("referenceImageCaption")
        self._caption_label.setWordWrap(True)
        inner_layout.addWidget(self._caption_label)

        self._how_to_title = QLabel(tr("ref_window.how_to"), inner)
        self._how_to_title.setObjectName("referenceSectionTitle")
        inner_layout.addWidget(self._how_to_title)

        self._how_to_host = QWidget(inner)
        self._how_to_layout = QVBoxLayout(self._how_to_host)
        self._how_to_layout.setContentsMargins(0, 0, 0, 0)
        self._how_to_layout.setSpacing(4)
        inner_layout.addWidget(self._how_to_host)

        self._source_title = QLabel(tr("ref_window.source"), inner)
        self._source_title.setObjectName("referenceSectionTitle")
        inner_layout.addWidget(self._source_title)

        self._source_label = QLabel("", inner)
        self._source_label.setObjectName("referenceSource")
        self._source_label.setWordWrap(True)
        inner_layout.addWidget(self._source_label)
        inner_layout.addStretch(1)

        scroll.setWidget(inner)
        layout.addWidget(scroll, stretch=2)
        return panel

    def _build_footer(self) -> QWidget:
        footer = QWidget(self)
        footer.setObjectName("referenceFooter")
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(8)
        self._btn_constructor = QPushButton(tr("ref_window.constructor"), footer)
        self._btn_constructor.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_constructor.clicked.connect(self.constructor_requested.emit)
        self._btn_sources = QPushButton(tr("ref_window.sources"), footer)
        self._btn_sources.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_sources.clicked.connect(self.sources_requested.emit)
        layout.addWidget(self._btn_constructor)
        layout.addWidget(self._btn_sources)
        layout.addStretch(1)
        return footer

    # ── theme ────────────────────────────────────────────────────────────
    def apply_theme(self) -> None:
        """Re-read the tokens: every colour of the window is a role of the theme."""
        tokens = get_theme_tokens()
        self._caption.apply_tokens()
        self.setStyleSheet(
            f"QWidget#referenceWindow {{ background: {tokens['surface.0']}; }}"
            f"QWidget#referenceCenter {{ background: {tokens['surface.0']}; }}"
            f"QWidget#referenceSide {{ background: {tokens['surface.1']}; "
            f"border-left: 1px solid {tokens['line.1']}; }}"
            f"QWidget#referenceFooter {{ background: {tokens['surface.1']}; "
            f"border-top: 1px solid {tokens['line.1']}; }}"
            f"QListWidget#referenceTopicList {{ background: {tokens['surface.0']}; border: none; "
            f"border-right: 1px solid {tokens['line.1']}; padding: 4px; }}"
            f"QListWidget#referenceTopicList::item {{ padding: 2px 0; border-radius: 4px; }}"
            f"QListWidget#referenceTopicList::item:selected {{ background: {tokens['accent.tab']}; }}"
            f"QListWidget#referenceTopicList::item:hover:!selected {{ background: {tokens['surface.hover']}; }}"
            f"QLabel#referenceTopicName {{ color: {tokens['text.1']}; }}"
            f"QLabel#referenceTopicCount {{ color: {tokens['text.3']}; }}"
            f"QLabel#referenceCrumb {{ color: {tokens['text.3']}; }}"
            f"QLabel#referenceTopicTitle {{ color: {tokens['text.1']}; font-size: 20px; font-weight: 600; }}"
            f"QLabel#referenceSectionTitle {{ color: {tokens['text.1']}; font-weight: 600; }}"
            f"QLabel#referenceImageCaption, QLabel#referenceSource {{ color: {tokens['text.2']}; }}"
            f"QLabel#referenceImageCounter {{ color: {tokens['text.3']}; }}"
            f"QLabel#referenceImage {{ background: {tokens['surface.2']}; "
            f"border: 1px solid {tokens['line.1']}; color: {tokens['text.3']}; }}"
            f"QLabel#referencePatientHint {{ color: {tokens['text.2']}; }}"
            f"QLabel#referenceEmpty {{ color: {tokens['text.3']}; }}"
            f"QLineEdit#referenceSearch {{ background: {tokens['surface.2']}; color: {tokens['text.1']}; "
            f"border: 1px solid {tokens['line.1']}; border-radius: 4px; padding: 4px 8px; }}"
            f"QPushButton {{ background: {tokens['surface.2']}; color: {tokens['text.1']}; "
            f"border: 1px solid {tokens['line.1']}; border-radius: 4px; padding: 4px 10px; }}"
            f"QPushButton:hover {{ background: {tokens['surface.hover']}; }}"
            f"QPushButton:checked {{ background: {tokens['accent.tab']}; border-color: {tokens['accent.tab']}; }}"
            f"QCheckBox {{ color: {tokens['text.2']}; }}"
            f"QPushButton#referenceImageNav {{ padding: 0; font-size: 15px; }}"
        )
        self._table.setStyleSheet(
            f"QTableWidget#referenceTable {{ background: {tokens['surface.1']}; "
            f"alternate-background-color: {tokens['surface.0']}; color: {tokens['text.1']}; "
            f"border: 1px solid {tokens['line.1']}; gridline-color: {tokens['line.1']}; }}"
            f"QTableWidget#referenceTable::item {{ padding: 4px 6px; }}"
            f"QTableWidget#referenceTable::item:selected {{ background: {tokens['surface.2']}; "
            f"color: {tokens['text.1']}; }}"
            f"QHeaderView::section {{ background: {tokens['surface.2']}; color: {tokens['text.2']}; "
            f"border: none; border-bottom: 1px solid {tokens['line.1']}; padding: 4px 6px; }}"
        )
        self._image_title.setStyleSheet(f"color: {tokens['text.1']}; font-weight: 600;")
        self._how_to_title.setStyleSheet(f"color: {tokens['text.1']}; font-weight: 600;")
        self._source_title.setStyleSheet(f"color: {tokens['text.1']}; font-weight: 600;")
        if self._view is not None:
            self._fill_table()
        self._show_current_image()

    def reload_data(self) -> None:
        """Pick up the YAML edited in the constructor, keeping the selection."""
        self._language = _language()
        self._store = ReferenceDataStore(language=self._language).load()
        keep_topic, keep_param = self._topic_slug, self.selected_param_id()
        self._reload_topics()
        if keep_param and self.open_at(keep_param):
            return
        if keep_topic:
            self.set_topic(keep_topic)

    # ── public API ───────────────────────────────────────────────────────
    @property
    def sex(self) -> str:
        return self._sex

    @property
    def selected_topic_slug(self) -> str:
        return self._topic_slug

    def topic_slugs(self) -> tuple[str, ...]:
        return tuple(entry.slug for entry in topic_entries(self._store))

    def set_sex(self, sex: str) -> None:
        """«Мужчины | Женщины | Оба» — the norm column follows the choice."""
        sex = sex if sex in (SEX_MALE, SEX_FEMALE, SEX_BOTH) else SEX_BOTH
        if sex == self._sex and self._view is not None:
            return
        self._sex = sex
        button = self._sex_buttons.get(sex)
        if button is not None and not button.isChecked():
            button.setChecked(True)
        self._refresh()

    def set_patient(
        self,
        *,
        sex: str = SEX_BOTH,
        age: int | None = None,
        values: Mapping[str, float] | None = None,
    ) -> None:
        """Bind the window to the open study: sex, age and the values of the report."""
        self._sex = sex if sex in (SEX_MALE, SEX_FEMALE, SEX_BOTH) else SEX_BOTH
        button = self._sex_buttons.get(self._sex)
        if button is not None:
            button.setChecked(True)
        self._age = age
        self._values = dict(values or {})
        self._refresh()

    def set_values(self, values: Mapping[str, float] | None) -> None:
        self._values = dict(values or {})
        self._refresh()

    def set_projection(self, projection_values: Mapping[str, float] | None) -> None:
        """Patient values straight from the study projection (catalogue ids)."""
        self.set_values(reference_values(projection_values))

    def set_topic(self, topic_slug: str) -> bool:
        topic = self._store.get_topic(topic_slug)
        if topic is None:
            return False
        self._topic_slug = topic.slug
        self._pathology_name = topic.pathologies[0].name if topic.pathologies else ""
        self._search_needle = ""
        if self._caption.search.text():
            self._caption.search.blockSignals(True)
            self._caption.search.clear()
            self._caption.search.blockSignals(False)
        self._sync_topic_selection()
        self._refresh()
        return True

    def open_at(self, param_id: str, *, sex: str | None = None, age: int | None = None) -> bool:
        """Open the window on a parameter — «Открыть в справочнике» of the card S2."""
        found = self._store.lookup(param_id)
        if found is None:
            return False
        topic, pathology, _gradation = found
        if sex is not None:
            self._sex = sex if sex in (SEX_MALE, SEX_FEMALE) else SEX_BOTH
            button = self._sex_buttons.get(self._sex)
            if button is not None:
                button.setChecked(True)
        if age is not None:
            self._age = age
        self._topic_slug = topic.slug
        self._pathology_name = pathology.name
        self._search_needle = ""
        if self._caption.search.text():
            self._caption.search.blockSignals(True)
            self._caption.search.clear()
            self._caption.search.blockSignals(False)
        self._sync_topic_selection()
        self._refresh(select_param=param_id)
        return True

    def selected_param_id(self) -> str:
        row = self._table.currentRow()
        item = self._table.item(row, 0) if row >= 0 else None
        if item is None:
            return ""
        return str(item.data(Qt.ItemDataRole.UserRole) or "")

    def selected_row(self) -> ReferenceRow | None:
        param_id = self.selected_param_id()
        if not param_id or self._view is None:
            return None
        return next((row for row in self._view.rows if row.param_id == param_id), None)

    def rows_on_screen(self) -> tuple[ReferenceRow, ...]:
        """Rows currently in the table (after the pathology filter)."""
        return tuple(self._filtered_rows())

    def headers(self) -> tuple[str, ...]:
        return tuple(self._table.horizontalHeaderItem(c).text() for c in range(self._table.columnCount()))

    def set_search(self, needle: str) -> None:
        self._caption.search.setText(needle)

    def values_visible(self) -> bool:
        return self._values_toggle.isChecked() and bool(self._values)

    def patient_values(self) -> dict[str, float]:
        """The values bound to the window (handbook ids → number)."""
        return dict(self._values)

    def isMaximizedNow(self) -> bool:  # noqa: N802 - kept close to Qt spelling
        return self.isMaximized()

    # ── topics and chips ─────────────────────────────────────────────────
    def _reload_topics(self) -> None:
        self._topic_list.blockSignals(True)
        self._topic_list.clear()
        self._topic_items: dict[str, QListWidgetItem] = {}
        entries = topic_entries(self._store)
        for entry in entries:
            if entry.slug == _VESSELS_FIRST_SLUG:
                self._add_group_header(tr("ref_window.group_vessels"))
            item = QListWidgetItem(self._topic_list)
            item.setData(Qt.ItemDataRole.UserRole, entry.slug)
            item.setSizeHint(QSize(200, control_height(self, padding=14, minimum=26)))
            widget = _TopicRow(entry.name, entry.parameter_count, self._topic_list)
            item.setData(Qt.ItemDataRole.UserRole + 1, widget)
            self._topic_list.setItemWidget(item, widget)
            self._topic_items[entry.slug] = item
        self._topic_list.blockSignals(False)

    def _add_group_header(self, text: str) -> None:
        item = QListWidgetItem(text, self._topic_list)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        item.setData(Qt.ItemDataRole.UserRole, "")
        item.setSizeHint(QSize(200, control_height(self, padding=10, minimum=22)))

    def _sync_topic_selection(self) -> None:
        item = getattr(self, "_topic_items", {}).get(self._topic_slug)
        if item is None:
            return
        self._topic_list.blockSignals(True)
        self._topic_list.setCurrentItem(item)
        self._topic_list.blockSignals(False)

    def _on_topic_item_changed(self, current: QListWidgetItem | None, _previous) -> None:
        if current is None:
            return
        slug = str(current.data(Qt.ItemDataRole.UserRole) or "")
        if slug and slug != self._topic_slug:
            topic = self._store.get_topic(slug)
            if topic is not None:
                self._topic_slug = slug
                self._pathology_name = topic.pathologies[0].name if topic.pathologies else ""
                self._search_needle = ""
                if self._caption.search.text():
                    self._caption.search.blockSignals(True)
                    self._caption.search.clear()
                    self._caption.search.blockSignals(False)
                self._refresh()

    def _rebuild_chips(self, names: tuple[str, ...]) -> None:
        for button in self._chip_group.buttons():
            self._chip_group.removeButton(button)
            button.setParent(None)
            button.deleteLater()
        topic_name = self._store.get_topic(self._topic_slug)
        for name in names:
            button = QPushButton(chip_label(name, topic_name.name if topic_name else ""), self)
            button.setToolTip(name)
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setChecked(name == self._pathology_name)
            button.clicked.connect(lambda _checked, value=name: self.set_pathology(value))
            self._chip_group.addButton(button)
            self._chips_layout.insertWidget(self._chips_layout.count() - 1, button)

    def set_pathology(self, name: str) -> None:
        if name == self._pathology_name:
            return
        self._pathology_name = name
        self._refresh()

    # ── model → table ────────────────────────────────────────────────────
    def _on_search_changed(self, text: str) -> None:
        needle = text.strip()
        if needle == self._search_needle:
            return
        self._search_needle = needle
        self._refresh()

    def _on_values_toggled(self, _checked: bool) -> None:
        self._fill_table()
        self._show_selected_row()

    def _refresh(self, *, select_param: str = "") -> None:
        keep = select_param or self.selected_param_id()
        if self._search_needle:
            self._view = search_view(
                self._store,
                self._search_needle,
                sex=self._sex,
                values=self._values,
                language=self._language,
            )
        else:
            self._view = build_topic_view(
                self._store,
                self._topic_slug,
                sex=self._sex,
                values=self._values,
                language=self._language,
            )
        self._update_header()
        self._fill_table(select_param=keep)
        self._show_selected_row()

    def _update_header(self) -> None:
        view = self._view
        if view is None:
            return
        topic = self._store.get_topic(self._topic_slug)
        if self._search_needle:
            self._crumb.setText(tr("ref_window.search_crumb"))
            self._title_label.setText(tr("ref_window.search_title", query=self._search_needle))
            self._rebuild_chips(())
        else:
            slugs = [entry.slug for entry in topic_entries(self._store)]
            group = tr("ref_window.group_heart")
            if _VESSELS_FIRST_SLUG in slugs and self._topic_slug in slugs:
                if slugs.index(self._topic_slug) >= slugs.index(_VESSELS_FIRST_SLUG):
                    group = tr("ref_window.group_vessels")
            self._crumb.setText(f"{group}  ›  {topic.name if topic else ''}")
            self._title_label.setText(topic.name if topic else "")
            self._rebuild_chips(view.pathology_names)
        if self._age is not None:
            self._patient_label.setText(tr("ref_window.patient_age", age=self._age))
        elif self._sex in (SEX_MALE, SEX_FEMALE):
            self._patient_label.setText(tr("ref_window.patient_selected"))
        else:
            self._patient_label.setText(tr("ref_window.patient_no_sex"))
        self._values_toggle.setEnabled(bool(self._values))
        self._values_toggle.setText(tr("ref_window.values_toggle") if self._values else tr("ref_window.values_none"))

    def _filtered_rows(self) -> list[ReferenceRow]:
        if self._view is None:
            return []
        if self._search_needle or not self._pathology_name:
            return list(self._view.rows)
        return [row for row in self._view.rows if row.pathology_name == self._pathology_name]

    def _fill_table(self, *, select_param: str = "") -> None:
        rows = self._filtered_rows()
        columns = list(self._view.columns) if self._view is not None else []
        show_values = self.values_visible()
        show_topic = bool(self._search_needle)
        headers = [tr("ref_window.col_param")]
        if show_topic:
            headers.append(tr("ref_window.col_topic"))
        headers.append(tr("ref_window.col_unit"))
        headers.append(tr("ref_window.col_norm_both") if self._sex == SEX_BOTH else tr("ref_window.col_norm"))
        headers.extend(columns)
        if show_values:
            headers.append(tr("ref_window.col_value"))
        self._table.clear()
        self._table.setColumnCount(len(headers))
        self._table.setRowCount(len(rows))
        self._table.setHorizontalHeaderLabels(headers)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        tokens = get_theme_tokens()
        for r, row in enumerate(rows):
            name = QTableWidgetItem(row.name)
            name.setData(Qt.ItemDataRole.UserRole, row.param_id)
            name.setToolTip(row.tooltip)
            font = name.font()
            font.setBold(True)
            name.setFont(font)
            name.setForeground(QColor(tokens["text.1"]))
            self._table.setItem(r, 0, name)
            column = 1
            if show_topic:
                topic_item = QTableWidgetItem(row.topic_name)
                topic_item.setForeground(QColor(tokens["text.3"]))
                self._table.setItem(r, column, topic_item)
                column += 1
            unit_item = QTableWidgetItem(row.unit)
            unit_item.setForeground(QColor(tokens["text.3"]))
            self._table.setItem(r, column, unit_item)
            column += 1
            norm_text = row.norm_text or tr("ref_window.no_norm")
            norm_item = QTableWidgetItem(norm_text)
            norm_item.setForeground(QColor(tokens["accent.text"] if row.norm_text else tokens["text.3"]))
            self._table.setItem(r, column, norm_item)
            column += 1
            for name_text, cell in zip(columns, row.gradation_texts):
                item = QTableWidgetItem(cell or "—")
                colors = grade_colors(name_text) if cell else None
                if colors is not None:
                    item.setBackground(QColor(colors[0]))
                    item.setForeground(QColor(colors[1]))
                else:
                    item.setForeground(QColor(tokens["text.3"]))
                self._table.setItem(r, column, item)
                column += 1
            if show_values:
                value_item = QTableWidgetItem(row.value_text or "—")
                colors = grade_colors(row.grade) if row.grade else None
                if colors is not None:
                    value_item.setBackground(QColor(colors[0]))
                    value_item.setForeground(QColor(colors[1]))
                    value_item.setToolTip(row.grade)
                else:
                    value_item.setForeground(QColor(tokens["text.2"]))
                self._table.setItem(r, column, value_item)
        self._empty_label.setVisible(not rows)
        self._table.setVisible(bool(rows))
        if rows:
            target = 0
            if select_param:
                target = next((i for i, row in enumerate(rows) if row.param_id == select_param), 0)
            self._table.setCurrentCell(target, 0)

    def _on_current_cell_changed(self, _row: int, _column: int, _prev_row: int, _prev_column: int) -> None:
        self._show_selected_row()

    def _show_selected_row(self) -> None:
        row = self.selected_row()
        if row is None:
            self._image_paths = ()
            self._image_index = 0
            self._image_label.clear()
            self._caption_label.clear()
            self._clear_how_to()
            self._source_label.clear()
            self._image_counter.setText("")
            return
        if tuple(row.image_paths) != self._image_paths:
            self._image_paths = tuple(row.image_paths)
            self._image_index = 0
        self._caption_label.setText(row.description or row.pathology_name)
        self._show_current_image()
        self._render_how_to(row.how_to)
        source = " · ".join(part for part in (row.source, row.method) if part)
        self._source_label.setText(source)
        self._source_label.setVisible(bool(source))
        self._source_title.setVisible(bool(source))

    # ── illustration ─────────────────────────────────────────────────────
    def _show_current_image(self) -> None:
        total = len(self._image_paths)
        self._image_counter.setText(f"{self._image_index + 1} / {total}" if total else "")
        self._btn_prev.setEnabled(total > 1)
        self._btn_next.setEnabled(total > 1)
        if not total:
            self._image_label.clear()
            self._image_label.setText(tr("ref_window.no_image"))
            self._original_pixmap = None
            return
        name = self._image_paths[self._image_index]
        path = _images_dir() / name
        if not path.is_file():
            self._image_label.clear()
            self._image_label.setText(tr("ref_window.no_image"))
            return
        # The handbook ships raster schemes only (png/jpg): no recolouring of
        # asset colours, and no colour literal of our own (the ratchet of UI-0).
        pixmap = QPixmap(str(path))
        self._original_pixmap = None if pixmap.isNull() else pixmap
        self._rescale_image()
        self._rescale_timer.start()

    def _rescale_image(self) -> None:
        if self._original_pixmap is None:
            return
        width = max(self._image_label.width() - 8, 40)
        height = max(self._image_label.height() - 8, 40)
        self._image_label.setPixmap(
            self._original_pixmap.scaled(
                width,
                height,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt
        super().resizeEvent(event)
        self._rescale_image()

    def eventFilter(self, watched, event) -> bool:  # noqa: ANN001 - Qt
        if watched is self._image_label and event.type() == QEvent.Type.Resize:
            self._rescale_image()
        return super().eventFilter(watched, event)

    def _previous_image(self) -> None:
        if len(self._image_paths) > 1:
            self._image_index = (self._image_index - 1) % len(self._image_paths)
            self._show_current_image()

    def _next_image(self) -> None:
        if len(self._image_paths) > 1:
            self._image_index = (self._image_index + 1) % len(self._image_paths)
            self._show_current_image()

    # ── «как измерять» ───────────────────────────────────────────────────
    def _clear_how_to(self) -> None:
        while self._how_to_layout.count():
            item = self._how_to_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _render_how_to(self, steps: tuple[str, ...]) -> None:
        self._clear_how_to()
        if not steps:
            placeholder = QLabel(tr("ref_window.no_how_to"), self._how_to_host)
            placeholder.setObjectName("referenceHowTo")
            placeholder.setWordWrap(True)
            self._how_to_layout.addWidget(placeholder)
            return
        for index, step in enumerate(steps, start=1):
            label = QLabel(f"{index}. {step}", self._how_to_host)
            label.setObjectName("referenceHowTo")
            label.setWordWrap(True)
            self._how_to_layout.addWidget(label)

    # ── window chrome ────────────────────────────────────────────────────
    def toggle_maximized(self) -> None:
        if self.isMaximized():
            self.showNormal()
            if self._normal_geometry is not None:
                self.setGeometry(self._normal_geometry)
                self._normal_geometry = None
        else:
            self._normal_geometry = self.geometry()
            self.showMaximized()
        self._caption.apply_tokens()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt
        super().showEvent(event)
        if not self._selection_restored:
            self._selection_restored = True
            geometry = self._settings.read(_GEOMETRY_KEY)
            if geometry is not None:
                self.restoreGeometry(geometry)
        if self.selected_param_id():
            self._table.setFocus(Qt.FocusReason.OtherFocusReason)
        else:
            self._caption.search.setFocus(Qt.FocusReason.OtherFocusReason)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt
        self._settings.write(_GEOMETRY_KEY, self.saveGeometry())
        super().closeEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        if event.key() == Qt.Key.Key_F and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._caption.search.setFocus(Qt.FocusReason.ShortcutFocusReason)
            self._caption.search.selectAll()
            return
        super().keyPressEvent(event)


def show_reference_window(
    parent: QWidget | None = None,
    *,
    param_id: str | None = None,
    sex: str = SEX_BOTH,
    age: int | None = None,
    values: Mapping[str, float] | None = None,
) -> ReferenceWindow:
    """Open (or raise) the one reference window of the session.

    The window is deliberately cached: the search field, the last topic and the
    geometry survive between openings, and a live web view of the documents is
    never destroyed mid-session (the same reason :func:`show_ase_reference_dialog`
    caches its dialog).
    """
    global _CACHED_WINDOW
    if _CACHED_WINDOW is None:
        _CACHED_WINDOW = ReferenceWindow(parent=parent)
    window = _CACHED_WINDOW
    if window.parent() is None and parent is not None:
        window.setParent(parent, window.windowFlags())
    if values is not None or sex != SEX_BOTH or age is not None:
        window.set_patient(
            sex=sex,
            age=age,
            values=values if values is not None else window.patient_values(),
        )
    if param_id:
        window.open_at(param_id, sex=sex)
    window.apply_theme()
    window.show()
    window.raise_()
    window.activateWindow()
    return window


def reset_reference_window() -> None:
    """Drop the cached window (tests and a language switch rebuild the data)."""
    global _CACHED_WINDOW
    if _CACHED_WINDOW is not None:
        _CACHED_WINDOW.close()
        _CACHED_WINDOW.deleteLater()
        _CACHED_WINDOW = None


__all__ = [
    "ReferenceWindow",
    "reset_reference_window",
    "show_reference_window",
]
