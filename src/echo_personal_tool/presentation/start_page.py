"""Native welcome page shown in the viewer area before a study is loaded.

The page deliberately uses regular Qt widgets rather than a web view. Recent
study rows accept summaries from the current-run/PACS history integration; the
section stays useful and privacy-safe when that optional history is empty.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.infrastructure.recent_store import RecentFolder, RecentStore
from echo_personal_tool.presentation.dark_theme import get_theme_palette

MAX_START_PAGE_RECENT_PLACES = 8


@dataclass(frozen=True)
class RecentStudySummary:
    """Safe display data for a recent study; patient identifiers are omitted."""

    key: str
    title: str
    details: str = ""


class RecentStudyDelegate(QStyledItemDelegate):
    """Paint a lightweight, image-free placeholder beside each study summary."""

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:  # type: ignore[override]
        del index
        line_height = QFontMetrics(option.font).lineSpacing()
        return QSize(240, max(64, line_height * 3 + 18))

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:  # type: ignore[override]
        painter.save()
        palette = get_theme_palette()
        rect = option.rect
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(rect, QColor(palette["accent_selected"]))

        thumb_height = max(40, rect.height() - 16)
        thumb_width = min(76, max(52, rect.width() // 6))
        thumb = QRect(rect.left() + 8, rect.top() + 8, thumb_width, thumb_height)
        painter.setPen(QPen(QColor(palette["border"]), 1))
        painter.setBrush(QColor(palette["bg_control"]))
        painter.drawRoundedRect(thumb, 5, 5)

        # A small neutral echo trace stands in for a thumbnail until one is
        # available from the cache; no patient pixels are read by this widget.
        trace = QPainterPath()
        baseline = thumb.center().y()
        left = thumb.left() + 8
        trace.moveTo(left, baseline)
        trace.lineTo(left + 8, baseline)
        trace.lineTo(left + 13, baseline - 8)
        trace.lineTo(left + 18, baseline + 8)
        trace.lineTo(left + 24, baseline - 13)
        trace.lineTo(left + 30, baseline + 4)
        trace.lineTo(thumb.right() - 7, baseline + 4)
        painter.setPen(QPen(QColor(palette["accent"]), 2))
        painter.drawPath(trace)

        title = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        details = str(index.data(Qt.ItemDataRole.UserRole + 1) or "")
        text_left = thumb.right() + 12
        title_rect = QRect(text_left, rect.top() + 7, max(0, rect.right() - text_left - 8), rect.height() // 2)
        title_font = QFont(option.font)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QColor(palette["text"]))
        painter.drawText(
            title_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            title,
        )

        detail_rect = QRect(
            text_left,
            title_rect.bottom(),
            max(0, rect.right() - text_left - 8),
            max(0, rect.bottom() - title_rect.bottom() - 5),
        )
        detail_font = QFont(option.font)
        detail_font.setPointSizeF(max(8.0, detail_font.pointSizeF() - 1.0))
        painter.setFont(detail_font)
        painter.setPen(QColor(palette["text_dim"]))
        painter.drawText(
            detail_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            details,
        )
        painter.restore()


class StartPage(QWidget):
    """Welcome content for an empty viewer/tab."""

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

    def __init__(
        self,
        *,
        recent_store: RecentStore | None = None,
        version: str = "",
        profile_name: str = "full",
        measurement_persistence_enabled: bool = False,
        ui_font_size: int = 13,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("startPage")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._recent_store = recent_store or RecentStore()
        self._version = version
        self._profile_name = profile_name
        self._measurement_persistence_enabled = bool(measurement_persistence_enabled)
        self._ui_font_size = max(10, int(ui_font_size))
        self._recent_studies: list[RecentStudySummary] = []
        self._continue_source = ""
        self._continue_folder = ""
        self._show_private_sections = profile_name != "presenter"

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self._scroll = QScrollArea(self)
        self._scroll.setObjectName("startPageScroll")
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root.addWidget(self._scroll)

        scroll_host = QWidget()
        scroll_host.setObjectName("startPageScrollHost")
        scroll_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        host_layout = QHBoxLayout(scroll_host)
        host_layout.setContentsMargins(20, 20, 20, 20)
        host_layout.addStretch(1)

        self._content = QWidget()
        self._content.setObjectName("startPageContent")
        self._content.setMaximumWidth(1040)
        self._content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(14)
        host_layout.addWidget(self._content, 12)
        host_layout.addStretch(1)
        self._scroll.setWidget(scroll_host)

        self._title = QLabel()
        self._title.setObjectName("startPageTitle")
        content_layout.addWidget(self._title)

        self._subtitle = QLabel()
        self._subtitle.setObjectName("startPageSubtitle")
        self._subtitle.setWordWrap(True)
        content_layout.addWidget(self._subtitle)

        self._actions_card = QFrame()
        self._actions_card.setObjectName("startPageCard")
        actions_layout = QGridLayout(self._actions_card)
        actions_layout.setContentsMargins(14, 14, 14, 14)
        actions_layout.setHorizontalSpacing(10)
        actions_layout.setVerticalSpacing(10)

        self.open_folder_button = self._button("startPageOpenFolder", primary=True)
        self.load_server_button = self._button("startPageLoadServer")
        self.continue_button = self._button("startPageContinue")
        actions_layout.addWidget(self.open_folder_button, 0, 0)
        actions_layout.addWidget(self.load_server_button, 0, 1)
        actions_layout.addWidget(self.continue_button, 0, 2)
        for column in range(3):
            actions_layout.setColumnStretch(column, 1)
        content_layout.addWidget(self._actions_card)

        self._places_card, self._places_title, places_body = self._section("startPageRecentPlaces")
        places_layout = QVBoxLayout(places_body)
        places_layout.setContentsMargins(0, 0, 0, 0)
        self._places_empty = QLabel()
        self._places_empty.setObjectName("startPageRecentPlacesEmpty")
        self._places_list = QListWidget()
        self._places_list.setObjectName("startPageRecentPlacesList")
        self._places_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._places_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._places_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._places_list.itemClicked.connect(self._on_recent_place_clicked)
        places_layout.addWidget(self._places_empty)
        places_layout.addWidget(self._places_list)
        content_layout.addWidget(self._places_card)

        self._studies_card, self._studies_title, studies_body = self._section("startPageRecentStudies")
        studies_layout = QVBoxLayout(studies_body)
        studies_layout.setContentsMargins(0, 0, 0, 0)
        self._studies_empty = QLabel()
        self._studies_empty.setObjectName("startPageRecentStudiesEmpty")
        self._studies_empty.setWordWrap(True)
        self._studies_list = QListWidget()
        self._studies_list.setObjectName("startPageRecentStudiesList")
        self._studies_list.setItemDelegate(RecentStudyDelegate(self._studies_list))
        self._studies_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._studies_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._studies_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._studies_list.itemClicked.connect(self._on_recent_study_clicked)
        studies_layout.addWidget(self._studies_empty)
        studies_layout.addWidget(self._studies_list)
        content_layout.addWidget(self._studies_card)

        self._links_card, self._links_title, links_body = self._section("startPageLinks")
        links_layout = QGridLayout(links_body)
        links_layout.setContentsMargins(0, 0, 0, 0)
        links_layout.setHorizontalSpacing(8)
        links_layout.setVerticalSpacing(8)
        self.references_button = self._button("startPageReferences", link=True)
        self.documents_button = self._button("startPageDocuments", link=True)
        self.feedback_button = self._button("startPageFeedback", link=True)
        self.settings_button = self._button("startPageSettings", link=True)
        self.help_button = self._button("startPageHelp", link=True)
        link_buttons = (
            self.references_button,
            self.documents_button,
            self.feedback_button,
            self.settings_button,
            self.help_button,
        )
        for index, button in enumerate(link_buttons):
            links_layout.addWidget(button, index // 3, index % 3)
            links_layout.setColumnStretch(index % 3, 1)
        content_layout.addWidget(self._links_card)

        self._footer = QLabel()
        self._footer.setObjectName("startPageStatus")
        self._footer.setWordWrap(True)
        content_layout.addWidget(self._footer)
        content_layout.addStretch(1)

        self.open_folder_button.clicked.connect(lambda: self.open_folder_requested.emit())
        self.load_server_button.clicked.connect(lambda: self.load_from_server_requested.emit())
        self.continue_button.clicked.connect(lambda: self.continue_requested.emit())
        self.references_button.clicked.connect(lambda: self.references_requested.emit())
        self.documents_button.clicked.connect(lambda: self.documents_requested.emit())
        self.feedback_button.clicked.connect(lambda: self.feedback_requested.emit())
        self.settings_button.clicked.connect(lambda: self.settings_requested.emit())
        self.help_button.clicked.connect(lambda: self.help_requested.emit())

        self._apply_profile_visibility()
        self.reload_text()
        self.refresh_recent_places()
        self.set_recent_studies(())
        self.set_continue_target("", "")
        self.set_measurement_persistence_enabled(self._measurement_persistence_enabled)

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

    def _section(self, object_name: str) -> tuple[QFrame, QLabel, QWidget]:
        card = QFrame()
        card.setObjectName("startPageCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(8)
        title = QLabel()
        title.setObjectName("startPageSectionTitle")
        body = QWidget(card)
        body.setObjectName(f"{object_name}Body")
        layout.addWidget(title)
        layout.addWidget(body)
        card.setProperty("startPageSection", object_name)
        return card, title, body

    def _apply_profile_visibility(self) -> None:
        self._places_card.setVisible(self._show_private_sections)
        self._studies_card.setVisible(self._show_private_sections)
        self.references_button.setVisible(self._show_private_sections)
        self.documents_button.setVisible(self._show_private_sections)
        self.feedback_button.setVisible(self._show_private_sections)
        self.settings_button.setVisible(self._show_private_sections)
        self.continue_button.setVisible(self._show_private_sections)

    def reload_text(self) -> None:
        """Refresh visible strings after the active UI language changes."""
        self._title.setText(tr("start_page.title"))
        self._subtitle.setText(tr("start_page.subtitle"))
        self.open_folder_button.setText(tr("start_page.open_folder"))
        self.open_folder_button.setToolTip(tr("start_page.open_folder_tip"))
        self.load_server_button.setText(tr("start_page.load_server"))
        self.load_server_button.setToolTip(tr("start_page.load_server_tip"))
        self._places_title.setText(tr("start_page.recent_places"))
        self._places_empty.setText(tr("start_page.recent_places_empty"))
        self._studies_title.setText(tr("start_page.recent_studies"))
        self._studies_empty.setText(tr("start_page.recent_studies_empty"))
        self._links_title.setText(tr("start_page.links"))
        self.references_button.setText(tr("start_page.references"))
        self.documents_button.setText(tr("start_page.documents"))
        self.feedback_button.setText(tr("start_page.feedback"))
        self.settings_button.setText(tr("start_page.settings"))
        self.help_button.setText(tr("start_page.help"))
        self.refresh_recent_places()
        self.set_recent_studies(self._recent_studies)
        self._refresh_continue_button()
        self._refresh_footer()
        self._apply_theme()

    def refresh_recent_places(self, entries: Iterable[RecentFolder] | None = None) -> None:
        """Re-read and display up to eight places, with missing folders greyed out."""
        folders = list(entries if entries is not None else self._recent_store.entries())
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
                item.setForeground(QColor(get_theme_palette()["text_dim"]))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self._places_list.addItem(item)
        self._places_list.setMaximumHeight(max(row_height + 4, row_height * len(folders) + 4))

    def set_recent_studies(self, studies: Iterable[RecentStudySummary]) -> None:
        """Show current-run study summaries; callers must omit patient identifiers."""
        self._recent_studies = list(studies)
        self._studies_list.clear()
        visible = bool(self._recent_studies) and self._show_private_sections
        self._studies_empty.setVisible(not visible)
        self._studies_list.setVisible(visible)
        for study in self._recent_studies:
            item = QListWidgetItem(study.title)
            item.setData(Qt.ItemDataRole.UserRole, study)
            item.setData(Qt.ItemDataRole.UserRole + 1, study.details)
            item.setToolTip(study.details)
            item.setSizeHint(QSize(0, self._studies_list.fontMetrics().lineSpacing() * 3 + 18))
            self._studies_list.addItem(item)
        if visible:
            row_height = self._studies_list.fontMetrics().lineSpacing() * 3 + 18
            self._studies_list.setMaximumHeight(min(len(self._recent_studies), 6) * row_height + 4)
        else:
            self._studies_list.setMaximumHeight(0)

    def set_continue_target(self, source: str, folder: str = "") -> None:
        """Update the Continue action from the persisted last-session source."""
        self._continue_source = source if source in {"folder", "server"} else ""
        self._continue_folder = folder
        self._refresh_continue_button()

    def set_measurement_persistence_enabled(self, enabled: bool) -> None:
        self._measurement_persistence_enabled = bool(enabled)
        self._refresh_footer()

    def set_ui_font_size(self, font_size: int) -> None:
        self._ui_font_size = max(10, int(font_size))

    def _refresh_continue_button(self) -> None:
        if self._continue_source == "server":
            target = tr("start_page.session_server")
            self.continue_button.setText(tr("start_page.continue", target=target))
            self.continue_button.setToolTip(tr("start_page.continue_server_tip"))
            self.continue_button.setEnabled(True)
        elif self._continue_source == "folder" and self._continue_folder:
            folder = Path(self._continue_folder)
            target = folder.name or self._continue_folder
            exists = folder.is_dir()
            key = "start_page.continue" if exists else "start_page.continue_missing"
            self.continue_button.setText(tr(key, target=target))
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

    def _on_recent_place_clicked(self, item: QListWidgetItem) -> None:
        if item.flags() & Qt.ItemFlag.ItemIsEnabled:
            path = item.data(Qt.ItemDataRole.UserRole)
            if path:
                self.recent_folder_requested.emit(str(path))

    def _on_recent_study_clicked(self, item: QListWidgetItem) -> None:
        study = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(study, RecentStudySummary):
            self.recent_study_requested.emit(study)

    def refresh_theme(self) -> None:
        """Apply the active clinical palette without rebuilding the page."""
        self._apply_theme()
        for button in (
            self.open_folder_button,
            self.load_server_button,
            self.continue_button,
            self.references_button,
            self.documents_button,
            self.feedback_button,
            self.settings_button,
            self.help_button,
        ):
            button.setMinimumHeight(max(40, button.fontMetrics().lineSpacing() + 20))
        self.refresh_recent_places()
        self.set_recent_studies(self._recent_studies)

    def _apply_theme(self) -> None:
        palette = get_theme_palette()
        accent = QColor(palette["accent"])
        luminance = (0.299 * accent.red()) + (0.587 * accent.green()) + (0.114 * accent.blue())
        accent_text = "#15202b" if luminance > 160 else "#ffffff"
        title_font_size = max(22, round(self._ui_font_size * 1.75))
        self.setStyleSheet(
            "QWidget#startPage { background-color: " + palette["bg_dark"] + "; color: " + palette["text"] + "; }"
            "QFrame#startPageCard { background-color: "
            + palette["bg_panel"]
            + "; border: 1px solid "
            + palette["border"]
            + "; border-radius: 9px; }"
            "QLabel#startPageTitle { color: "
            + palette["text"]
            + f"; font-size: {title_font_size}px; font-weight: 600; }}"
            "QLabel#startPageSubtitle, QLabel#startPageRecentPlacesEmpty, "
            "QLabel#startPageRecentStudiesEmpty { color: " + palette["text_dim"] + "; }"
            "QLabel#startPageSectionTitle { color: " + palette["text"] + "; font-weight: 600; }"
            "QLabel#startPageStatus { color: "
            + palette["text_dim"]
            + "; border-top: 1px solid "
            + palette["border"]
            + "; padding-top: 10px; }"
            "QPushButton[startPageRole='primary'] { background-color: "
            + palette["accent"]
            + "; color: "
            + accent_text
            + "; border: 1px solid "
            + palette["accent"]
            + "; border-radius: 6px; padding: 8px 12px; font-weight: 600; }"
            "QPushButton[startPageRole='primary']:hover { background-color: " + palette["accent_bright"] + "; }"
            "QPushButton[startPageRole='secondary'] { background-color: "
            + palette["bg_button"]
            + "; color: "
            + palette["text"]
            + "; border: 1px solid "
            + palette["border"]
            + "; border-radius: 6px; padding: 8px 12px; }"
            "QPushButton[startPageRole='secondary']:hover, "
            "QPushButton[startPageRole='link']:hover { background-color: " + palette["bg_button_hover"] + "; }"
            "QPushButton[startPageRole='link'] { background-color: transparent; color: "
            + palette["accent_bright"]
            + "; border: 1px solid "
            + palette["border"]
            + "; border-radius: 6px; padding: 8px 12px; text-align: left; }"
            "QPushButton:disabled { color: " + palette["text_dim"] + "; }"
            "QListWidget#startPageRecentPlacesList, QListWidget#startPageRecentStudiesList { "
            "background: transparent; border: none; outline: none; color: " + palette["text"] + "; }"
            "QListWidget#startPageRecentPlacesList::item { border-radius: 4px; padding-left: 6px; }"
            "QListWidget#startPageRecentPlacesList::item:selected { background-color: "
            + palette["accent_selected"]
            + "; }"
        )
