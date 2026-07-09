"""Interactive structured reference browser widget."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QEvent, QObject, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QRadioButton,
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
from echo_personal_tool.presentation.echopac_theme import get_theme_palette

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
    "left_ventricle": "ЛЖ",
    "left_atrium": "ЛП",
    "right_ventricle": "ПЖ",
    "right_atrium": "ПП",
    "mitral_valve": "МК",
    "aortic_valve": "АК",
    "tricuspid_valve": "ТК",
    "pulmonary_valve": "ЛК",
    "aorta": "Аорта",
    "prosthetic_valves": "Протезы",
    "other": "Прочее",
}

_TOPIC_FULL_NAMES: dict[str, str] = {
    "left_ventricle": "Левый\nжелудочек",
    "left_atrium": "Левое\nпредсердие",
    "right_ventricle": "Правый\nжелудочек",
    "right_atrium": "Правое\nпредсердие",
    "mitral_valve": "Митральный\nклапан",
    "aortic_valve": "Аортальный\nклапан",
    "tricuspid_valve": "Трикуспидальный\nклапан",
    "pulmonary_valve": "Лёгочный\nклапан",
    "aorta": "Аорта",
    "prosthetic_valves": "Протезы\nклапанов",
    "other": "Прочее",
}


class StructuredReferenceWidget(QWidget):
    """Topic → pathology → gradation → parameter table with sex toggle and images."""

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
        self._sex_male: bool = True
        self._age: int | None = None
        self._original_pixmap: QPixmap | None = None

        self._build_ui()

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
        self._search_input.setPlaceholderText("Поиск параметра...")
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
        left_layout = QVBoxLayout(left_panel)
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

        # Sex toggle
        sex_widget = QWidget()
        sex_layout = QHBoxLayout(sex_widget)
        sex_layout.setContentsMargins(4, 4, 4, 4)
        sex_layout.setSpacing(4)

        sex_group = QButtonGroup(self)
        self._male_radio = QRadioButton("Муж")
        self._female_radio = QRadioButton("Жен")
        self._male_radio.setChecked(True)
        sex_group.addButton(self._male_radio, 0)
        sex_group.addButton(self._female_radio, 1)
        sex_group.idClicked.connect(self._on_sex_changed)

        sex_label = QLabel("Пол:")
        sex_label.setStyleSheet(f"font-size: 12px; color: {p['text']};")
        sex_layout.addWidget(sex_label)
        sex_layout.addWidget(self._male_radio)
        sex_layout.addWidget(self._female_radio)
        left_layout.addWidget(sex_widget)

        # Age field
        age_widget = QWidget()
        age_layout = QHBoxLayout(age_widget)
        age_layout.setContentsMargins(4, 2, 4, 4)
        age_layout.setSpacing(4)

        age_label = QLabel("Возраст:")
        age_label.setStyleSheet(f"font-size: 12px; color: {p['text']};")
        self._age_input = QLineEdit()
        self._age_input.setPlaceholderText("л")
        self._age_input.setMaximumWidth(50)
        self._age_input.setStyleSheet(f"font-size: 12px; padding: 2px;")
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

        # Pathology list (~6 rows)
        self._pathology_list = QListWidget()
        self._pathology_list.setFixedHeight(150)
        self._pathology_list.setStyleSheet(
            f"QListWidget {{ border: 1px solid {p['border']}; background: {p['bg_panel']}; font-size: 13px; }}"
            f"QListWidget::item {{ padding: 4px 8px; }}"
            f"QListWidget::item:selected {{ background: {p['accent_tab']}; }}"
        )
        self._pathology_list.currentRowChanged.connect(self._on_pathology_row_changed)
        right_layout.addWidget(self._pathology_list)

        # Gradation radio group — shown only when pathology has gradations
        self._gradation_group = QGroupBox("Градация")
        self._gradation_group.setStyleSheet(
            f"QGroupBox {{ border: 1px solid {p['border']}; margin-top: 6px; padding-top: 14px; font-size: 13px; }}"
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; }}"
        )
        gradation_layout = QHBoxLayout(self._gradation_group)
        gradation_layout.setContentsMargins(8, 4, 8, 4)
        self._gradation_radio_group = QButtonGroup(self)
        self._gradation_radio_group.idClicked.connect(self._on_gradation_changed)
        self._gradation_group.hide()
        right_layout.addWidget(self._gradation_group)

        # Middle: table (left) + image (right)
        content_row = QHBoxLayout()
        content_row.setSpacing(8)

        # Table (left half)
        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["Параметр", "Ед. изм.", "Норма", "Патология"])
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.verticalHeader().hide()
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setColumnWidth(0, 220)
        self._table.setStyleSheet(
            f"QTableWidget {{ border: 1px solid {p['border']}; gridline-color: {p['border']}; font-size: 13px; }}"
            f"QTableWidget::item {{ padding: 4px; }}"
            f"QHeaderView::section {{ background: {p['bg_control']}; padding: 4px; border: 1px solid {p['border']}; font-size: 13px; font-weight: bold; }}"
        )
        self._table.itemSelectionChanged.connect(self._on_table_selection_changed)
        content_row.addWidget(self._table, stretch=1)

        # Image (right half) — always visible
        self._image_label = QLabel()
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setStyleSheet(
            f"border: 1px solid {p['border']}; background: {p['bg_panel']}; font-size: 12px; color: {p['text_dim']};"
        )
        self._image_label.setText("Нет изображения")
        content_row.addWidget(self._image_label, stretch=1)

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

        # Placeholder
        self._show_placeholder()

    def _show_placeholder(self) -> None:
        self._pathology_list.clear()
        self._table.setRowCount(0)
        self._gradation_group.hide()
        self._image_label.clear()
        self._image_label.setText("Нет изображения")

    def _scale_image(self) -> None:
        if self._original_pixmap is None or self._original_pixmap.isNull():
            return
        label_size = self._image_label.size()
        if label_size.width() < 10 or label_size.height() < 10:
            return
        scaled = self._original_pixmap.scaled(
            label_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._image_label.setPixmap(scaled)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._scale_image()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._scale_image()

    def _on_sex_changed(self, button_id: int) -> None:
        self._sex_male = button_id == 0
        self._refresh_table()

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
        self._table.setRowCount(len(results))
        for row, (topic, patho, grad, param) in enumerate(results):
            self._table.setItem(row, 0, QTableWidgetItem(param.name))
            self._table.setItem(row, 1, QTableWidgetItem(param.unit))
            norm = self._format_norm(param)
            self._table.setItem(row, 2, QTableWidgetItem(norm))
            self._table.setItem(row, 3, QTableWidgetItem(patho.name + (f" ({grad.name})" if grad else "")))
        self._image_label.clear()
        self._image_label.setText("Нет изображения")

    def _on_topic_clicked(self, topic: TopicRef) -> None:
        self._current_topic = topic
        self._current_pathology = None
        self._current_gradation = None
        self._pathology_list.blockSignals(True)
        self._pathology_list.clear()
        for patho in topic.pathologies:
            self._pathology_list.addItem(patho.name)
        self._pathology_list.blockSignals(False)
        self._table.setRowCount(0)
        self._image_label.clear()
        self._image_label.setText("Нет изображения")
        self._source_label.clear()

    def _on_pathology_row_changed(self, row: int) -> None:
        if row < 0 or self._current_topic is None:
            return
        self._current_pathology = self._current_topic.pathologies[row]

        if self._current_pathology.gradations:
            self._rebuild_gradation_buttons(self._current_pathology.gradations)
            self._current_gradation = self._current_pathology.gradations[0]
            self._gradation_group.show()
        else:
            self._current_gradation = None
            self._gradation_group.hide()

        self._refresh_table()
        self._load_image()
        self._update_source()

    def _rebuild_gradation_buttons(self, gradations: list[GradationRef]) -> None:
        """Replace radio buttons in the gradation group for the given gradations."""
        layout = self._gradation_group.layout()
        # Remove existing buttons
        for btn in self._gradation_radio_group.buttons():
            self._gradation_radio_group.removeButton(btn)
            layout.removeWidget(btn)
            btn.deleteLater()
        # Add new buttons
        for i, grad in enumerate(gradations):
            radio = QRadioButton(grad.name)
            self._gradation_radio_group.addButton(radio, i)
            layout.addWidget(radio)
        # Auto-select first
        if self._gradation_radio_group.buttons():
            self._gradation_radio_group.buttons()[0].setChecked(True)

    def _on_gradation_changed(self, button_id: int) -> None:
        if self._current_pathology is None or not self._current_pathology.gradations:
            return
        if button_id < len(self._current_pathology.gradations):
            self._current_gradation = self._current_pathology.gradations[button_id]
            self._refresh_table()
            self._update_source()

    def _on_table_selection_changed(self) -> None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return
        row = rows[0].row()
        params = self._get_current_parameters()
        if row < len(params):
            param = params[row]
            if param.source:
                self._source_label.setText(param.source)
            else:
                self._source_label.clear()

    def _refresh_table(self) -> None:
        params = self._get_current_parameters()
        self._table.setRowCount(len(params))
        for row, param in enumerate(params):
            self._table.setItem(row, 0, QTableWidgetItem(param.name))
            self._table.setItem(row, 1, QTableWidgetItem(param.unit))
            norm = self._format_norm(param)
            self._table.setItem(row, 2, QTableWidgetItem(norm))
            desc = param.pathology_desc or ""
            self._table.setItem(row, 3, QTableWidgetItem(desc))

    def _get_current_parameters(self) -> list:
        if self._current_pathology is None:
            return []
        if self._current_gradation is not None:
            return self._current_gradation.parameters
        if self._current_pathology.parameters is not None:
            return self._current_pathology.parameters
        return []

    def _format_norm(self, param) -> str:
        norm = param.norm_female if not self._sex_male else param.norm_male
        if norm is None:
            norm = param.norm_male or param.norm_female
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
        if self._current_pathology is None or not self._current_pathology.image_path:
            self._image_label.clear()
            self._image_label.setText("Нет изображения")
            return
        img_path = _IMAGES_DIR / self._current_pathology.image_path
        if not img_path.is_file():
            self._image_label.clear()
            self._image_label.setText(f"Изображение: {self._current_pathology.image_path}")
            return

        pixmap = QPixmap()
        if img_path.suffix.lower() == ".svg":
            # SVG: replace colors with theme-adaptive colors
            p = get_theme_palette()
            svg_text = img_path.read_text(encoding="utf-8")
            svg_text = svg_text.replace("currentColor", p.get("text", "#f1f5f9"))
            svg_text = svg_text.replace("#000000", p.get("text", "#f1f5f9"))
            svg_text = svg_text.replace("#706f6f", p.get("text_dim", "#94a3b8"))
            pixmap.loadFromData(svg_text.encode("utf-8"))
        else:
            pixmap = QPixmap(str(img_path))

        if pixmap.isNull():
            self._image_label.clear()
            self._image_label.setText("Нет изображения")
            return

        # Store original pixmap for re-scaling on resize
        self._original_pixmap = pixmap
        self._scale_image()

    def _update_source(self) -> None:
        params = self._get_current_parameters()
        sources = sorted({p.source for p in params if p.source})
        if sources:
            self._source_label.setText("Источники: " + "; ".join(sources))
        else:
            self._source_label.clear()
        # Clear row selection highlight when source changes
        self._table.clearSelection()

    def navigate_to_param(self, param_id: str) -> None:
        result = self._store.lookup(param_id)
        if result is None:
            return
        topic, patho, grad = result
        topic_idx = next((i for i, t in enumerate(self._topics) if t.slug == topic.slug), -1)
        if topic_idx < 0:
            return
        self._topic_buttons[topic_idx].click()
        patho_idx = next((i for i, p in enumerate(topic.pathologies) if p.slug == patho.slug), -1)
        if patho_idx < 0:
            return
        self._pathology_list.setCurrentRow(patho_idx)
        # Select the specific gradation if applicable
        if grad is not None and self._current_pathology and self._current_pathology.gradations:
            grad_idx = next(
                (i for i, g in enumerate(self._current_pathology.gradations) if g.name == grad.name),
                -1,
            )
            if grad_idx >= 0 and grad_idx < len(self._gradation_radio_group.buttons()):
                self._gradation_radio_group.buttons()[grad_idx].setChecked(True)
                self._current_gradation = self._current_pathology.gradations[grad_idx]
                self._refresh_table()
                self._update_source()

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
