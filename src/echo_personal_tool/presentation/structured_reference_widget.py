"""Interactive structured reference browser widget."""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

from PySide6.QtCore import QEvent, QObject, QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.domain.services.reference_data_store import (
    GradationRef,
    PathologyRef,
    ReferenceDataStore,
    TopicRef,
)
from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.presentation.dark_theme import get_theme_palette

_IMAGES_DIR = Path(__file__).resolve().parents[1] / "resources" / "references" / "images"
_ICONS_DIR = Path(__file__).resolve().parents[1] / "resources" / "icons"

_TOPIC_ICONS: dict[str, str] = {
    "left_ventricle": "LV01",
    "left_atrium": "LA01",
    "right_ventricle": "RV01",
    "right_atrium": "RA01",
    "mitral_valve": "MV01",
    "aortic_valve": "AV01",
    "tricuspid_valve": "TV01",
    "pulmonary_valve": "PV01",
    "aorta": "AV01",
    "prosthetic_valves": "MV01",
    "other": "LV01",
}

_TOPIC_LABELS: dict[str, str] = {
    "left_ventricle": tr("ref_topic.left_ventricle"),
    "left_atrium": tr("ref_topic.left_atrium"),
    "right_ventricle": tr("ref_topic.right_ventricle"),
    "right_atrium": tr("ref_topic.right_atrium"),
    "mitral_valve": tr("ref_topic.mitral_valve"),
    "aortic_valve": tr("ref_topic.aortic_valve"),
    "tricuspid_valve": tr("ref_topic.tricuspid_valve"),
    "pulmonary_valve": tr("ref_topic.pulmonary_valve"),
    "aorta": tr("ref_topic.aorta"),
    "prosthetic_valves": tr("ref_topic.prosthetic_valves"),
    "other": tr("ref_topic.other"),
}

_TOPIC_FULL_NAMES: dict[str, str] = {
    "left_ventricle": tr("ref_topic.full_left_ventricle"),
    "left_atrium": tr("ref_topic.full_left_atrium"),
    "right_ventricle": tr("ref_topic.full_right_ventricle"),
    "right_atrium": tr("ref_topic.full_right_atrium"),
    "mitral_valve": tr("ref_topic.full_mitral_valve"),
    "aortic_valve": tr("ref_topic.full_aortic_valve"),
    "tricuspid_valve": tr("ref_topic.full_tricuspid_valve"),
    "pulmonary_valve": tr("ref_topic.full_pulmonary_valve"),
    "aorta": tr("ref_topic.full_aorta"),
    "prosthetic_valves": tr("ref_topic.full_prosthetic_valves"),
    "other": tr("ref_topic.full_other"),
}


_GRADATION_COLORS: dict[str, tuple[str, str]] = {
    "норм": ("rgba(34, 197, 94, 0.12)", "#22c55e"),
    "лёгк": ("rgba(234, 179, 8, 0.12)", "#eab308"),
    "умерен": ("rgba(249, 115, 22, 0.12)", "#f97316"),
    "тяжёл": ("rgba(239, 68, 68, 0.12)", "#ef4444"),
}


def _gradation_color(name: str) -> tuple[str, str] | None:
    """Return (bg, text) colors for a gradation name, or None."""
    lower = name.lower()
    for keyword, colors in _GRADATION_COLORS.items():
        if keyword in lower:
            return colors
    return None


class _PathologyPanel(QWidget):
    """Two-column pathology list: items flow left→right, max 4 rows per column."""

    currentRowChanged = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items: list[str] = []
        self._buttons: list[QPushButton] = []
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._selected_index: int = -1
        self._blocked: bool = False

        self._layout = QGridLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(2)

    def addItems(self, items: list[str]) -> None:
        self.clear()
        self._items = list(items)
        p = get_theme_palette()
        for i, text in enumerate(items):
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                f"QPushButton {{ text-align: left; padding: 4px 8px; border: none; "
                f"background: transparent; color: {p['text']}; font-size: 13px; "
                f"border-radius: 3px; }}"
                f"QPushButton:checked {{ background: {p['accent_tab']}; font-weight: bold; }}"
                f"QPushButton:hover:!checked {{ background: {p['bg_button_hover']}; }}"
            )
            btn.clicked.connect(lambda _checked, idx=i: self._on_clicked(idx))
            self._group.addButton(btn, i)
            self._buttons.append(btn)
            col = i % 2
            row = i // 2
            self._layout.addWidget(btn, row, col)
        # Fill remaining cells in the grid so columns align
        if len(items) % 2 == 1:
            spacer = QWidget()
            spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            self._layout.addWidget(spacer, len(items) // 2, 1)

    def clear(self) -> None:
        for btn in self._buttons:
            self._group.removeButton(btn)
            btn.setParent(None)
            btn.deleteLater()
        self._buttons.clear()
        self._items.clear()
        self._selected_index = -1

    def setCurrentRow(self, row: int) -> None:
        if 0 <= row < len(self._buttons):
            self._buttons[row].setChecked(True)
            self._selected_index = row

    def _on_clicked(self, index: int) -> None:
        if self._blocked:
            return
        self._selected_index = index
        self.currentRowChanged.emit(index)

    def count(self) -> int:
        return len(self._buttons)


class _ImageContainer(QWidget):
    """QWidget that ignores child pixmap size hints so the layout stays stable."""

    def sizeHint(self):
        return QSize(200, 200)

    def minimumSizeHint(self):
        return QSize(100, 100)


class _ParameterCard(QWidget):
    """Single parameter card with mini-tables for norm and pathology."""

    def __init__(self, param, norm_text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._param = param
        self._selected = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        p = get_theme_palette()
        unit = param.unit or ""
        self.setStyleSheet(
            f"_ParameterCard {{ border: 1px solid {p['border']}; border-radius: 4px; "
            f"background: {p['bg_panel']}; }}"
            f"_ParameterCard:hover {{ background: {p['bg_button_hover']}; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        # Parameter name header
        name_label = QLabel(f"<b>{param.name}</b>")
        name_label.setStyleSheet(f"font-size: 13px; color: {p['text']}; border: none;")
        layout.addWidget(name_label)

        # Norm mini-table (2 columns: Показатель | Значение)
        if norm_text:
            norm_value = f"{norm_text} {unit}".strip() if unit else norm_text
            norm_table = self._make_table(
                headers=[tr("ref_table.header_param"), tr("ref_table.header_value")],
                rows=[[param.name, norm_value]],
                header_bg=p["bg_control"],
                value_color=p["accent_tab"],
            )
            layout.addWidget(norm_table)

        # Pathology mini-table (merged header "Патология" + 2 columns)
        desc = param.pathology_desc or ""
        if desc:
            patho_rows = self._parse_pathology_rows(desc, unit)
            patho_table = self._make_pathology_table(patho_rows, p)
            layout.addWidget(patho_table)

    def _make_table(
        self,
        headers: list[str],
        rows: list[list[str]],
        header_bg: str = "",
        value_color: str = "",
    ) -> QTableWidget:
        """Create a small 2-column table."""
        p = get_theme_palette()
        table = QTableWidget(len(rows), len(headers))
        table.verticalHeader().hide()
        table.horizontalHeader().setStretchLastSection(True)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        table.setMaximumHeight(60)

        header_style = f"background: {header_bg or p['bg_control']}; font-weight: bold; font-size: 12px; border: none;"
        table.horizontalHeader().setStyleSheet(f"QHeaderView::section {{ {header_style} }}")
        table.setStyleSheet(
            f"QTableWidget {{ border: 1px solid {p['border']}; gridline-color: {p['border']}; "
            f"font-size: 13px; background: transparent; }}"
            f"QTableWidget::item {{ padding: 2px 6px; border: none; }}"
        )
        table.setHorizontalHeaderLabels(headers)

        for r, row_data in enumerate(rows):
            for c, text in enumerate(row_data):
                item = QTableWidgetItem(text)
                if c == 1 and value_color:
                    item.setForeground(QColor(value_color))
                table.setItem(r, c, item)

        table.resizeColumnsToContents()
        return table

    def _make_pathology_table(self, rows: list[list[str]], p: dict) -> QWidget:
        """Create pathology table with merged 'Патология' header spanning both columns."""
        wrapper = QWidget()
        vbox = QVBoxLayout(wrapper)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        # Merged header label
        header = QLabel("  " + tr("ref_table.pathology_header"))
        header.setStyleSheet(
            f"font-size: 12px; font-weight: bold; color: {p['text']}; "
            f"background: {p['bg_control']}; padding: 3px 6px; border: 1px solid {p['border']};"
        )
        vbox.addWidget(header)

        # Data rows
        table = QTableWidget(len(rows), 2)
        table.verticalHeader().hide()
        table.horizontalHeader().hide()
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        table.setStyleSheet(
            f"QTableWidget {{ border: 1px solid {p['border']}; border-top: none; "
            f"gridline-color: {p['border']}; font-size: 13px; background: transparent; }}"
            f"QTableWidget::item {{ padding: 2px 6px; border: none; }}"
        )

        for r, (grad_name, grad_value) in enumerate(rows):
            name_item = QTableWidgetItem(grad_name)
            name_item.setForeground(QColor(p["text_dim"]))
            val_item = QTableWidgetItem(grad_value)
            table.setItem(r, 0, name_item)
            table.setItem(r, 1, val_item)

        table.resizeColumnsToContents()
        vbox.addWidget(table)
        return wrapper

    @staticmethod
    def _parse_pathology_rows(desc: str, unit: str) -> list[list[str]]:
        """Parse pathology_desc into gradation rows.

        Handles:
          - Gradation format: "Лёгкая: <0.20 / Умеренная: 0.20-0.39 / Тяжёлая: ≥0.40"
          - Simple format: ">115 (м) / >95 (ж) — гипертрофия"
        """
        parts = [p.strip() for p in desc.split("/")]

        # Try gradation format first
        gradations = []
        for part in parts:
            m = re.match(r"^([^:]+):\s*(.+)$", part)
            if m:
                gradations.append((m.group(1).strip(), m.group(2).strip()))

        if len(gradations) >= 2:
            return [[g[0], f"{g[1]} {unit}".strip() if unit else g[1]] for g in gradations]

        # Simple format — single row
        value = f"{desc} {unit}".strip() if unit else desc
        return [[desc, value]]

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._select()
        super().mousePressEvent(event)

    def _select(self) -> None:
        # Find the parent widget and deselect others
        parent = self.parent()
        while parent is not None:
            if isinstance(parent, StructuredReferenceWidget):
                parent._on_card_selected(self)
                break
            parent = parent.parent()

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        p = get_theme_palette()
        if selected:
            self.setStyleSheet(
                f"_ParameterCard {{ border: 2px solid {p['accent_tab']}; border-radius: 4px; "
                f"background: {p['bg_control']}; }}"
            )
        else:
            self.setStyleSheet(
                f"_ParameterCard {{ border: 1px solid {p['border']}; border-radius: 4px; "
                f"background: {p['bg_panel']}; }}"
                f"_ParameterCard:hover {{ background: {p['bg_button_hover']}; }}"
            )


class StructuredReferenceWidget(QWidget):
    """Topic → pathology → gradation → parameter cards with images."""

    param_clicked = Signal(str)  # future: overlay link

    def __init__(
        self,
        data_store: ReferenceDataStore,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = data_store
        self._topics: list[TopicRef] = data_store.get_topics()
        self._current_topic: TopicRef | None = None
        self._current_pathology: PathologyRef | None = None
        self._current_gradation: GradationRef | None = None
        self._age: int | None = None
        self._original_pixmap: QPixmap | None = None
        self._image_paths: list[str] = []
        self._current_image_index: int = 0

        self._build_ui()

    def reload(self) -> None:
        """Reload data from YAML and refresh the entire view."""
        self._store.load()
        self._topics = self._store.get_topics()
        # Rebuild topic buttons
        self._rebuild_topic_buttons()
        # Re-select current pathology if still exists
        if self._current_pathology is not None:
            new_patho = self._store.get_pathology(
                self._current_topic.slug if self._current_topic else "",
                self._current_pathology.slug,
            )
            if new_patho is not None:
                self._current_pathology = new_patho
                self._image_paths = new_patho.image_paths
                self._current_image_index = 0
                self._refresh_table()
                self._load_image()

    def _rebuild_topic_buttons(self) -> None:
        """Remove old topic buttons and recreate from current data."""
        p = get_theme_palette()
        # Remove old buttons
        for btn in self._topic_buttons:
            self._topic_group.removeButton(btn)
            btn.setParent(None)
            btn.deleteLater()
        self._topic_buttons.clear()
        # Create new buttons
        for i, topic in enumerate(self._topics):
            label = _TOPIC_LABELS.get(topic.slug, topic.name[:8])
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(32)

            icon_name = _TOPIC_ICONS.get(topic.slug)
            if icon_name:
                icon_path = _ICONS_DIR / f"{icon_name}.svg"
                if icon_path.is_file():
                    icon = QIcon(str(icon_path))
                    btn.setIcon(icon)
                    btn.setIconSize(QSize(20, 20))

            btn.setStyleSheet(
                f"QPushButton {{ text-align: left; padding: 6px 8px; border: none; "
                f"background: transparent; color: {p['text']}; font-size: 14px; }}"
                f"QPushButton:checked {{ background: {p['accent_tab']}; font-weight: bold; }}"
                f"QPushButton:hover:!checked {{ background: {p['bg_button_hover']}; }}"
            )
            btn.clicked.connect(lambda _checked, t=topic: self._on_topic_clicked(t))
            self._topic_group.addButton(btn, i)
            self._topic_buttons.append(btn)
            self._left_layout.insertWidget(self._left_layout.count() - 2, btn)

    # Default section to open on first show
    _DEFAULT_TOPIC_SLUG = "left_ventricle"
    _DEFAULT_PATHOLOGY_SLUG = "lv_diastolic"

    def _build_ui(self) -> None:
        p = get_theme_palette()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Top bar: search only ──
        top_bar = QWidget()
        top_bar.setStyleSheet(f"background: {p['bg_panel']}; border-bottom: 1px solid {p['border']};")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(8, 4, 8, 4)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText(tr("ref_table.search_placeholder"))
        self._search_input.textChanged.connect(self._on_search_changed)
        self._search_input.returnPressed.connect(self._on_search_enter)
        self._search_input.installEventFilter(self)
        top_layout.addWidget(self._search_input)
        top_layout.addStretch(1)

        root.addWidget(top_bar)

        # ── Main area: left nav (fixed) | right content ──
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Left: topic navigation (fixed width, non-collapsible)
        left_panel = QWidget()
        self._left_layout = left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(4, 4, 4, 4)
        left_layout.setSpacing(2)

        self._topic_buttons: list[QPushButton] = []
        self._topic_group = QButtonGroup(self)
        self._topic_group.setExclusive(True)
        for i, topic in enumerate(self._topics):
            label = _TOPIC_LABELS.get(topic.slug, topic.name[:8])
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(32)

            icon_name = _TOPIC_ICONS.get(topic.slug)
            if icon_name:
                icon_path = _ICONS_DIR / f"{icon_name}.svg"
                if icon_path.is_file():
                    icon = QIcon(str(icon_path))
                    btn.setIcon(icon)
                    btn.setIconSize(QSize(20, 20))

            btn.setStyleSheet(
                f"QPushButton {{ text-align: left; padding: 6px 8px; border: none; "
                f"background: transparent; color: {p['text']}; font-size: 14px; }}"
                f"QPushButton:checked {{ background: {p['accent_tab']}; font-weight: bold; }}"
                f"QPushButton:hover:!checked {{ background: {p['bg_button_hover']}; }}"
            )
            btn.clicked.connect(lambda _checked, t=topic: self._on_topic_clicked(t))
            self._topic_group.addButton(btn, i)
            self._topic_buttons.append(btn)
            left_layout.addWidget(btn)
        left_layout.addStretch(1)

        # Separator
        separator = QLabel()
        separator.setFixedHeight(1)
        separator.setStyleSheet(f"background: {p['border']};")
        left_layout.addWidget(separator)

        # Age field
        age_widget = QWidget()
        age_layout = QHBoxLayout(age_widget)
        age_layout.setContentsMargins(4, 2, 4, 4)
        age_layout.setSpacing(4)

        age_label = QLabel(tr("ref_table.age_label"))
        age_label.setStyleSheet(f"font-size: 12px; color: {p['text']};")
        self._age_input = QLineEdit()
        self._age_input.setPlaceholderText(tr("ref_table.age_placeholder"))
        self._age_input.setMaximumWidth(50)
        self._age_input.setStyleSheet("font-size: 12px; padding: 2px;")
        self._age_input.textChanged.connect(self._on_age_changed)

        age_layout.addWidget(age_label)
        age_layout.addWidget(self._age_input)
        age_layout.addStretch(1)
        left_layout.addWidget(age_widget)

        left_panel.setFixedWidth(180)
        main_layout.addWidget(left_panel)

        # Right: pathology list + table/image split
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(8)

        # Pathology panel (two-column grid)
        self._pathology_panel = _PathologyPanel()
        self._pathology_panel.setFixedHeight(80)
        self._pathology_panel.setStyleSheet(
            f"_PathologyPanel {{ border: 1px solid {p['border']}; background: {p['bg_panel']}; }}"
        )
        self._pathology_panel.currentRowChanged.connect(self._on_pathology_row_changed)
        right_layout.addWidget(self._pathology_panel)

        # Middle: cards (left) + image (right)
        content_row = QHBoxLayout()
        content_row.setSpacing(8)

        # Parameter cards (left half) in a scroll area
        self._cards_scroll = QScrollArea()
        self._cards_scroll.setWidgetResizable(True)
        self._cards_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self._cards_container = QWidget()
        self._cards_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._cards_layout = QVBoxLayout(self._cards_container)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(6)
        self._cards_layout.addStretch(1)  # pushes table to bottom, fills upward
        self._cards_scroll.setWidget(self._cards_container)
        self._param_cards: list[_ParameterCard] = []
        content_row.addWidget(self._cards_scroll, stretch=1)

        # Image (right half) — container overrides sizeHint() to prevent
        # the pixmap from inflating the layout via Qt's size negotiation.
        self._image_container = _ImageContainer()
        image_layout = QVBoxLayout(self._image_container)
        image_layout.setContentsMargins(0, 0, 0, 0)
        self._image_label = QLabel()
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._image_label.setStyleSheet(
            f"border: 1px solid {p['border']}; background: {p['bg_panel']}; font-size: 12px; color: {p['text_dim']};"
        )
        self._image_label.setText(tr("reference.no_image"))
        image_layout.addWidget(self._image_label, stretch=1)

        # Image navigation bar (< counter >)
        nav_bar = QWidget()
        nav_bar.setStyleSheet(f"background: {p['bg_panel']}; border-top: 1px solid {p['border']};")
        nav_layout = QHBoxLayout(nav_bar)
        nav_layout.setContentsMargins(4, 2, 4, 2)
        nav_layout.setSpacing(4)
        self._btn_img_prev = QPushButton("\u25c0")
        self._btn_img_prev.setFixedSize(28, 22)
        self._btn_img_prev.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_img_prev.clicked.connect(self._prev_image)
        self._btn_img_prev.setEnabled(False)
        self._image_counter_label = QLabel("0 / 0")
        self._image_counter_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._btn_img_next = QPushButton("\u25b6")
        self._btn_img_next.setFixedSize(28, 22)
        self._btn_img_next.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_img_next.clicked.connect(self._next_image)
        self._btn_img_next.setEnabled(False)
        nav_layout.addStretch(1)
        nav_layout.addWidget(self._btn_img_prev)
        nav_layout.addWidget(self._image_counter_label)
        nav_layout.addWidget(self._btn_img_next)
        nav_layout.addStretch(1)
        image_layout.addWidget(nav_bar)
        content_row.addWidget(self._image_container, stretch=1)

        right_layout.addLayout(content_row, stretch=1)

        # Source bar at bottom
        self._source_label = QLabel()
        self._source_label.setStyleSheet(
            f"color: {p['text_dim']}; padding: 4px; font-size: 12px; "
            f"border-top: 1px solid {p['border']}; background: {p['bg_panel']};"
        )
        self._source_label.setWordWrap(True)
        self._source_label.setMinimumHeight(24)
        right_layout.addWidget(self._source_label)

        main_layout.addWidget(right_panel, stretch=1)
        root.addLayout(main_layout, stretch=1)

        # Open default section
        self._open_default_section()

    def _show_placeholder(self) -> None:
        self._pathology_panel.clear()
        self._clear_cards()
        self._image_label.clear()
        self._image_label.setText(tr("reference.no_image"))
        self._image_paths = []
        self._current_image_index = 0
        self._update_nav_buttons()

    def _open_default_section(self) -> None:
        """Select the default topic and pathology on startup."""
        topic_idx = next(
            (i for i, t in enumerate(self._topics) if t.slug == self._DEFAULT_TOPIC_SLUG),
            -1,
        )
        if topic_idx < 0:
            self._show_placeholder()
            return
        self._topic_buttons[topic_idx].click()
        topic = self._topics[topic_idx]
        patho_idx = next(
            (i for i, p in enumerate(topic.pathologies) if p.slug == self._DEFAULT_PATHOLOGY_SLUG),
            0,
        )
        self._pathology_panel.setCurrentRow(patho_idx)

    def _clear_cards(self) -> None:
        """Remove all parameter cards and tables from the container."""
        for card in self._param_cards:
            self._cards_layout.removeWidget(card)
            card.deleteLater()
        self._param_cards.clear()
        # Also remove any tables that were added
        while self._cards_layout.count() > 1:  # Keep stretch
            item = self._cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _scale_image(self) -> None:
        # Guard against recursive calls from resizeEvent
        if getattr(self, "_scaling", False):
            return
        self._scaling = True
        try:
            # Use the label's actual size, not the container's — the nav bar
            # below eats ~30 px, so container height overstates available space.
            cw = self._image_label.width()
            ch = self._image_label.height()
            if cw < 10 or ch < 10:
                return

            # Skip if container size hasn't changed
            cache_key = (cw, ch)
            if getattr(self, "_last_scale_size", None) == cache_key:
                return
            self._last_scale_size = cache_key

            if getattr(self, "_is_svg", False) and self._svg_text:
                # Render SVG at actual display resolution using QSvgRenderer
                try:
                    from PySide6.QtGui import QImage, QPainter
                    from PySide6.QtSvg import QSvgRenderer

                    renderer = QSvgRenderer()
                    renderer.load(self._svg_text.encode("utf-8"))
                    if renderer.isValid():
                        vb = renderer.viewBoxF()
                        if vb.width() > 0 and vb.height() > 0:
                            img_aspect = vb.height() / vb.width()
                        else:
                            img_aspect = 1.0
                        device_ratio = self.devicePixelRatioF()
                        # Smart scaling: fit by width or height based on image shape
                        container_aspect = ch / cw if cw > 0 else 1.0
                        if img_aspect >= container_aspect:
                            # Image is tall or square — fit by height
                            h = int(ch * device_ratio)
                            w = int(h / img_aspect)
                        else:
                            # Image is wide — fit by width
                            w = int(cw * device_ratio)
                            h = int(w * img_aspect)
                        image = QImage(max(w, 1), max(h, 1), QImage.Format.Format_ARGB32)
                        image.setDevicePixelRatio(device_ratio)
                        image.fill(0)
                        painter = QPainter(image)
                        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
                        renderer.render(painter)
                        painter.end()
                        pixmap = QPixmap.fromImage(image)
                        self._image_label.setPixmap(pixmap)
                        return
                except ImportError:
                    pass
                # Fallback: load from data
                pixmap = QPixmap()
                pixmap.loadFromData(self._svg_text.encode("utf-8"))
                if not pixmap.isNull():
                    scaled = self._smart_scale_pixmap(pixmap, cw, ch)
                    self._image_label.setPixmap(scaled)
            elif self._original_pixmap is not None and not self._original_pixmap.isNull():
                scaled = self._smart_scale_pixmap(self._original_pixmap, cw, ch)
                self._image_label.setPixmap(scaled)
        finally:
            self._scaling = False

    def _smart_scale_pixmap(self, pixmap: QPixmap, cw: int, ch: int) -> QPixmap:
        """Scale pixmap along the dominant axis so it fills the container."""
        pw, ph = pixmap.width(), pixmap.height()
        if pw <= 0 or ph <= 0:
            return pixmap
        img_aspect = ph / pw
        container_aspect = ch / cw if cw > 0 else 1.0
        if img_aspect >= container_aspect:
            # Tall image — fit by height
            target_h = ch
            target_w = max(int(ch / img_aspect), 1)
        else:
            # Wide image — fit by width
            target_w = cw
            target_h = max(int(cw * img_aspect), 1)
        return pixmap.scaled(
            target_w,
            target_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._last_scale_size = None
        self._scale_image()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._scale_image()

    def _on_age_changed(self, text: str) -> None:
        # Age is stored for future use (e.g., diastolic function norms)
        try:
            self._age = int(text) if text.strip() else None
        except ValueError:
            self._age = None

    def _on_search_changed(self, text: str) -> None:
        if text.strip():
            results = self._store.search(text)
            self._show_search_results(results)
        else:
            self._refresh_table()

    def _on_search_enter(self) -> None:
        # Prevent Enter from propagating to parent dialog
        pass

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self._search_input and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                return True  # Consume the event, prevent dialog from closing
        return super().eventFilter(obj, event)

    def _show_search_results(
        self,
        results: list[tuple[TopicRef, PathologyRef, GradationRef | None, Any]],
    ) -> None:
        self._clear_cards()
        for topic, patho, grad, param in results:
            norm = self._format_norm(param)
            card = _ParameterCard(param, norm)
            card.setToolTip(f"{patho.name}" + (f" ({grad.name})" if grad else ""))
            self._cards_layout.insertWidget(self._cards_layout.count() - 1, card)
            self._param_cards.append(card)
        self._image_label.clear()
        self._image_label.setText(tr("reference.no_image"))

    def _on_topic_clicked(self, topic: TopicRef) -> None:
        self._current_topic = topic
        self._current_pathology = None
        self._current_gradation = None
        self._pathology_panel._blocked = True
        self._pathology_panel.clear()
        self._pathology_panel.addItems([p.name for p in topic.pathologies])
        self._pathology_panel._blocked = False
        self._clear_cards()
        self._image_label.clear()
        self._image_label.setText(tr("reference.no_image"))
        self._source_label.clear()

    def _on_pathology_row_changed(self, row: int) -> None:
        if row < 0 or self._current_topic is None:
            return
        self._current_pathology = self._current_topic.pathologies[row]
        self._current_gradation = None

        self._refresh_table()
        self._load_image()
        self._update_source()

    def _flatten_gradation_parameters(self, pathology) -> list:
        """Combine parameters from all gradations into a single deduplicated list.

        Parameters appearing in multiple gradations get their pathology_desc
        updated with gradation name prefixes (e.g. "Лёгкая: <0.10").
        """
        seen: dict[str, ParameterRef] = {}
        for grad in pathology.gradations:
            for param in grad.parameters:
                if param.id in seen:
                    existing = seen[param.id]
                    if param.pathology_desc:
                        existing.pathology_desc = (
                            (existing.pathology_desc or "") + " / " + f"{grad.name}: {param.pathology_desc}"
                        ).lstrip(" /")
                else:
                    dup = copy.copy(param)
                    if dup.pathology_desc:
                        dup.pathology_desc = f"{grad.name}: {dup.pathology_desc}"
                    seen[param.id] = dup
        return list(seen.values())

    def _on_card_selected(self, card: _ParameterCard) -> None:
        """Handle card selection — update source label and highlight."""
        for c in self._param_cards:
            c.set_selected(c is card)
        if card._param.source:
            self._source_label.setText(card._param.source)
        else:
            self._source_label.clear()

    def _refresh_table(self) -> None:
        self._clear_cards()
        if self._current_pathology is None:
            return
        self._render_parameter_table()

    def _render_parameter_table(self) -> None:
        """Unified table: Показатель | Норм М | Норм Ж | [Градации...]."""
        if self._current_pathology is None:
            return

        params = self._current_pathology.parameters or []
        if not params:
            if self._current_pathology.gradations:
                params = self._flatten_gradation_parameters(self._current_pathology)
            if not params:
                return

        has_gradations = any(p.gradations for p in params)
        grad_names: list[str] = []
        if has_gradations:
            seen: set[str] = set()
            for p in params:
                for g in p.gradations:
                    if g.name not in seen:
                        grad_names.append(g.name)
                        seen.add(g.name)

        pal = get_theme_palette()
        n_cols = 3 + len(grad_names)
        n_rows = len(params)

        table = QTableWidget(n_rows, n_cols)
        table.verticalHeader().hide()
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        table.setAlternatingRowColors(True)

        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in range(1, n_cols):
            header.setSectionResizeMode(c, QHeaderView.ResizeMode.Interactive)
            header.resizeSection(c, 100)

        headers = [tr("ref_table.col_param"), tr("ref_table.col_norm_male"), tr("ref_table.col_norm_female")]
        headers.extend(grad_names)
        table.setHorizontalHeaderLabels(headers)

        header_style = (
            f"background: {pal['bg_control']}; font-weight: bold; font-size: 12px; "
            f"color: {pal['text']}; border-bottom: 2px solid {pal['accent_tab']};"
        )
        header.setStyleSheet(f"QHeaderView::section {{ {header_style} padding: 4px 8px; }}")

        table.setStyleSheet(
            f"QTableWidget {{ border: 1px solid {pal['border']}; gridline-color: {pal['border']}; "
            f"font-size: 13px; background: {pal['bg_panel']}; color: {pal['text']}; "
            f"alternate-background-color: {pal.get('bg_panel_alt', pal['bg_control'])}; }}"
            f"QTableWidget::item {{ padding: 4px 8px; border: none; }}"
        )

        mono_font = table.font()
        mono_font.setStyleHint(QFont.StyleHint.Monospace)

        for r, param in enumerate(params):
            name_text = param.name
            if param.unit:
                name_text += f" ({param.unit})"
            name_item = QTableWidgetItem(name_text)
            name_item.setForeground(QColor(pal["text"]))
            font = name_item.font()
            font.setBold(True)
            name_item.setFont(font)
            table.setItem(r, 0, name_item)

            norm_m = self._format_norm_range(param.norm_male)
            norm_m_item = QTableWidgetItem(norm_m)
            norm_m_item.setFont(mono_font)
            norm_m_item.setForeground(QColor(pal["accent_tab"]))
            table.setItem(r, 1, norm_m_item)

            norm_f = self._format_norm_range(param.norm_female)
            norm_f_item = QTableWidgetItem(norm_f)
            norm_f_item.setFont(mono_font)
            norm_f_item.setForeground(QColor(pal["accent_tab"]))
            table.setItem(r, 2, norm_f_item)

            grad_map = {g.name: g for g in param.gradations}
            for g_idx, g_name in enumerate(grad_names):
                col = 3 + g_idx
                grad = grad_map.get(g_name)
                if grad:
                    parts = []
                    if grad.range_male:
                        parts.append(self._format_norm_range(grad.range_male))
                    if grad.range_female:
                        parts.append(self._format_norm_range(grad.range_female))
                    value = " / ".join(parts) if parts else "—"
                else:
                    value = "—"

                item = QTableWidgetItem(value)
                item.setFont(mono_font)

                colors = _gradation_color(g_name)
                if colors and value != "—":
                    bg, text = colors
                    item.setBackground(QColor(bg))
                    item.setForeground(QColor(text))
                else:
                    item.setForeground(QColor(pal["text_dim"]))

                table.setItem(r, col, item)

        # Insert table into cards layout (inside scroll area)
        self._cards_layout.insertWidget(self._cards_layout.count() - 1, table)
        # Restore saved column widths and connect resize signal
        QTimer.singleShot(0, lambda: self._restore_column_widths(table))
        header.sectionResized.connect(lambda _idx, _old, _new: self._save_column_widths(table))
        QTimer.singleShot(0, lambda: self._adjust_table_row_height(table, n_rows))

    def _adjust_table_row_height(self, table: QTableWidget, n_rows: int) -> None:
        """Set row height to a reasonable size; cap at 32px so rows don't stretch."""
        if n_rows == 0:
            return
        table.verticalHeader().setDefaultSectionSize(32)

    def _save_column_widths(self, table: QTableWidget) -> None:
        """Persist column widths for current pathology via QSettings."""
        if self._current_pathology is None:
            return
        settings = QSettings()
        key = f"reference/col_widths/{self._current_pathology.slug}"
        widths = [table.columnWidth(c) for c in range(table.columnCount())]
        settings.setValue(key, widths)

    def _restore_column_widths(self, table: QTableWidget) -> None:
        """Restore saved column widths for current pathology."""
        if self._current_pathology is None:
            return
        settings = QSettings()
        key = f"reference/col_widths/{self._current_pathology.slug}"
        widths = settings.value(key)
        if widths and isinstance(widths, list):
            for c, w in enumerate(widths):
                if c < table.columnCount():
                    table.setColumnWidth(c, int(w))

    def save_settings(self) -> None:
        """Public API: save all current settings (column widths etc.)."""
        # Find the table widget in cards layout
        for i in range(self._cards_layout.count()):
            item = self._cards_layout.itemAt(i)
            if item and item.widget() and isinstance(item.widget(), QTableWidget):
                self._save_column_widths(item.widget())
                break

    def _get_current_parameters(self) -> list:
        if self._current_pathology is None:
            return []
        params = []
        if self._current_pathology.parameters is not None:
            params.extend(self._current_pathology.parameters)
        if self._current_pathology.gradations:
            params.extend(self._flatten_gradation_parameters(self._current_pathology))
        return params

    def _format_norm(self, param) -> str:
        parts = []
        if param.norm_male:
            parts.append(f"М: {self._format_norm_range(param.norm_male)}")
        if param.norm_female:
            parts.append(f"Ж: {self._format_norm_range(param.norm_female)}")
        return " / ".join(parts) if parts else ""

    def _format_norm_range(self, norm) -> str:
        """Format a NormRange directly (for table view)."""
        if norm is None:
            return ""
        if norm.low is not None and norm.high is not None:
            return f"{norm.low}\u2013{norm.high}"
        if norm.low is not None:
            return f"\u2265{norm.low}"
        if norm.high is not None:
            return f"\u2264{norm.high}"
        return ""

    def _load_image(self) -> None:
        if self._current_pathology is None or not self._current_pathology.image_paths:
            self._image_label.clear()
            self._image_label.setText(tr("reference.no_image"))
            self._image_paths = []
            self._current_image_index = 0
            self._update_nav_buttons()
            return

        self._image_paths = self._current_pathology.image_paths
        self._current_image_index = 0
        self._show_current_image()
        self._update_nav_buttons()

    def _show_current_image(self) -> None:
        """Display the image at _current_image_index."""
        if not self._image_paths:
            self._image_label.clear()
            self._image_label.setText(tr("reference.no_image"))
            return

        path_str = self._image_paths[self._current_image_index]
        img_path = _IMAGES_DIR / path_str
        if not img_path.is_file():
            self._image_label.clear()
            self._image_label.setText(tr("ref_table.image_label", path=path_str))
            return

        if img_path.suffix.lower() == ".svg":
            p = get_theme_palette()
            self._svg_text = img_path.read_text(encoding="utf-8")
            self._svg_text = self._svg_text.replace("currentColor", p.get("text", "#f1f5f9"))
            self._svg_text = self._svg_text.replace("#000000", p.get("text", "#f1f5f9"))
            self._svg_text = self._svg_text.replace("#706f6f", p.get("text_dim", "#94a3b8"))
            self._is_svg = True
            self._original_pixmap = None
        else:
            self._is_svg = False
            self._svg_text = None
            self._original_pixmap = QPixmap(str(img_path))

        if not self._is_svg and self._original_pixmap.isNull():
            self._image_label.clear()
            self._image_label.setText(tr("reference.no_image"))
            return

        self._last_scale_size = None
        self._scale_image()

    def _prev_image(self) -> None:
        if self._current_image_index > 0:
            self._current_image_index -= 1
            self._show_current_image()
            self._update_nav_buttons()

    def _next_image(self) -> None:
        if self._current_image_index < len(self._image_paths) - 1:
            self._current_image_index += 1
            self._show_current_image()
            self._update_nav_buttons()

    def _update_nav_buttons(self) -> None:
        n = len(self._image_paths)
        self._btn_img_prev.setEnabled(self._current_image_index > 0)
        self._btn_img_next.setEnabled(self._current_image_index < n - 1)
        self._image_counter_label.setText(f"{self._current_image_index + 1} / {n}" if n > 0 else "0 / 0")

    def _update_source(self) -> None:
        params = self._get_current_parameters()
        sources = sorted({p.source for p in params if p.source})
        if sources:
            self._source_label.setText(tr("reference.sources") + "; ".join(sources))
        else:
            self._source_label.clear()
        # Clear card selection highlight when source changes
        for card in self._param_cards:
            card.set_selected(False)

    def navigate_to_param(self, param_id: str) -> None:
        result = self._store.lookup(param_id)
        if result is None:
            import logging

            logging.getLogger(__name__).debug("navigate_to_param: param_id=%r not found in YAML", param_id)
            return
        topic, patho, grad = result
        topic_idx = next((i for i, t in enumerate(self._topics) if t.slug == topic.slug), -1)
        if topic_idx < 0:
            return
        self._topic_buttons[topic_idx].click()
        patho_idx = next((i for i, p in enumerate(topic.pathologies) if p.slug == patho.slug), -1)
        if patho_idx < 0:
            return
        self._pathology_panel.setCurrentRow(patho_idx)

    def set_maximized_mode(self, maximized: bool) -> None:
        """Update button labels and sizes for maximized/restored mode."""
        p = get_theme_palette()
        for i, (topic, btn) in enumerate(zip(self._topics, self._topic_buttons)):
            if maximized:
                label = _TOPIC_FULL_NAMES.get(topic.slug, topic.name)
                btn.setText(label)
                btn.setFixedHeight(58)
                icon_size = 32
                btn.setIconSize(QSize(icon_size, icon_size))
                btn.setStyleSheet(
                    f"QPushButton {{ text-align: left; padding: 8px 12px; border: none; "
                    f"background: transparent; color: {p['text']}; font-size: 14px; }}"
                    f"QPushButton:checked {{ background: {p['accent_tab']}; font-weight: bold; }}"
                    f"QPushButton:hover:!checked {{ background: {p['bg_button_hover']}; }}"
                )
            else:
                label = _TOPIC_LABELS.get(topic.slug, topic.name[:8])
                btn.setText(label)
                btn.setFixedHeight(32)
                icon_size = 20
                btn.setIconSize(QSize(icon_size, icon_size))
                btn.setStyleSheet(
                    f"QPushButton {{ text-align: left; padding: 6px 8px; border: none; "
                    f"background: transparent; color: {p['text']}; font-size: 14px; }}"
                    f"QPushButton:checked {{ background: {p['accent_tab']}; font-weight: bold; }}"
                    f"QPushButton:hover:!checked {{ background: {p['bg_button_hover']}; }}"
                )
