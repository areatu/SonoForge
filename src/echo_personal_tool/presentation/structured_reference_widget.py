"""Interactive structured reference browser widget."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from PySide6.QtCore import QEvent, QObject, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
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


class _ImageContainer(QWidget):
    """QWidget that ignores child pixmap size hints so the layout stays stable."""

    def sizeHint(self):
        return QSize(200, 200)

    def minimumSizeHint(self):
        return QSize(100, 100)


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
        self._image_paths: list[str] = []
        self._current_image_index: int = 0

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

        # Image (right half) — container overrides sizeHint() to prevent
        # the pixmap from inflating the layout via Qt's size negotiation.
        self._image_container = _ImageContainer()
        image_layout = QVBoxLayout(self._image_container)
        image_layout.setContentsMargins(0, 0, 0, 0)
        self._image_label = QLabel()
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setStyleSheet(
            f"border: 1px solid {p['border']}; background: {p['bg_panel']}; font-size: 12px; color: {p['text_dim']};"
        )
        self._image_label.setText("Нет изображения")
        image_layout.addWidget(self._image_label, stretch=1)

        # Image navigation bar (< counter >)
        nav_bar = QWidget()
        nav_bar.setStyleSheet(f"background: {p['bg_panel']}; border-top: 1px solid {p['border']};")
        nav_layout = QHBoxLayout(nav_bar)
        nav_layout.setContentsMargins(4, 2, 4, 2)
        nav_layout.setSpacing(4)
        self._btn_img_prev = QPushButton("\u25C0")
        self._btn_img_prev.setFixedSize(28, 22)
        self._btn_img_prev.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_img_prev.clicked.connect(self._prev_image)
        self._btn_img_prev.setEnabled(False)
        self._image_counter_label = QLabel("0 / 0")
        self._image_counter_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._btn_img_next = QPushButton("\u25B6")
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

        # Placeholder
        self._show_placeholder()

    def _show_placeholder(self) -> None:
        self._pathology_list.clear()
        self._table.setRowCount(0)
        self._image_label.clear()
        self._image_label.setText("Нет изображения")
        self._image_paths = []
        self._current_image_index = 0
        self._update_nav_buttons()

    def _scale_image(self) -> None:
        # Guard against recursive calls from resizeEvent
        if getattr(self, '_scaling', False):
            return
        self._scaling = True
        try:
            cw = self._image_container.width()
            ch = self._image_container.height()
            if cw < 10 or ch < 10:
                return

            # Skip if container size hasn't changed
            cache_key = (cw, ch)
            if getattr(self, '_last_scale_size', None) == cache_key:
                return
            self._last_scale_size = cache_key

            if getattr(self, '_is_svg', False) and self._svg_text:
                # Render SVG at actual display resolution using QSvgRenderer
                try:
                    from PySide6.QtSvg import QSvgRenderer
                    from PySide6.QtGui import QImage, QPainter
                    renderer = QSvgRenderer()
                    renderer.load(self._svg_text.encode("utf-8"))
                    if renderer.isValid():
                        vb = renderer.viewBoxF()
                        if vb.width() > 0 and vb.height() > 0:
                            aspect = vb.height() / vb.width()
                        else:
                            aspect = 1.0
                        device_ratio = self.devicePixelRatioF()
                        # Fit within container keeping aspect ratio
                        w = int(cw * device_ratio)
                        h = int(w * aspect)
                        if h > int(ch * device_ratio):
                            h = int(ch * device_ratio)
                            w = int(h / aspect)
                        image = QImage(w, h, QImage.Format.Format_ARGB32)
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
                    scaled = pixmap.scaled(cw, ch, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                    self._image_label.setPixmap(scaled)
            elif self._original_pixmap is not None and not self._original_pixmap.isNull():
                scaled = self._original_pixmap.scaled(cw, ch, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                self._image_label.setPixmap(scaled)
        finally:
            self._scaling = False

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._last_scale_size = None
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
                            (existing.pathology_desc or "")
                            + " / " + f"{grad.name}: {param.pathology_desc}"
                        ).lstrip(" /")
                else:
                    dup = copy.copy(param)
                    if dup.pathology_desc:
                        dup.pathology_desc = f"{grad.name}: {dup.pathology_desc}"
                    seen[param.id] = dup
        return list(seen.values())

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
        if self._current_pathology.gradations:
            return self._flatten_gradation_parameters(self._current_pathology)
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
        if self._current_pathology is None or not self._current_pathology.image_paths:
            self._image_label.clear()
            self._image_label.setText("Нет изображения")
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
            self._image_label.setText("Нет изображения")
            return

        path_str = self._image_paths[self._current_image_index]
        img_path = _IMAGES_DIR / path_str
        if not img_path.is_file():
            self._image_label.clear()
            self._image_label.setText(f"Изображение: {path_str}")
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
            self._image_label.setText("Нет изображения")
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
