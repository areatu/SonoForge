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
    QScrollArea,
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


class _ParameterCard(QWidget):
    """Single parameter card showing name, unit, norm, and pathology description."""

    def __init__(self, param, norm_text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._param = param
        self._selected = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        p = get_theme_palette()
        self.setStyleSheet(
            f"_ParameterCard {{ border: 1px solid {p['border']}; border-radius: 4px; "
            f"background: {p['bg_panel']}; }}"
            f"_ParameterCard:hover {{ background: {p['bg_button_hover']}; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        # Top row: parameter name + unit + norm
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        name_label = QLabel(f"<b>{param.name}</b>")
        name_label.setStyleSheet(f"font-size: 13px; color: {p['text']}; border: none;")
        name_label.setWordWrap(True)
        top_row.addWidget(name_label, stretch=1)

        if param.unit:
            unit_label = QLabel(param.unit)
            unit_label.setStyleSheet(f"font-size: 12px; color: {p['text_dim']}; border: none;")
            top_row.addWidget(unit_label)

        if norm_text:
            norm_label = QLabel(f"Норма: {norm_text}")
            norm_label.setStyleSheet(f"font-size: 12px; color: {p['accent_tab']}; border: none; font-weight: bold;")
            top_row.addWidget(norm_label)

        layout.addLayout(top_row)

        # Bottom row: pathology description
        desc = param.pathology_desc or ""
        if desc:
            desc_label = QLabel(desc)
            desc_label.setStyleSheet(
                f"font-size: 13px; color: {p['text']}; border: none; "
                f"background: {p['bg_control']}; border-radius: 3px; padding: 4px 8px;"
            )
            desc_label.setWordWrap(True)
            layout.addWidget(desc_label)

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
    """Topic → pathology → gradation → parameter cards with sex toggle and images."""

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

        # Middle: cards (left) + image (right)
        content_row = QHBoxLayout()
        content_row.setSpacing(8)

        # Parameter cards (left half) in a scroll area
        self._cards_scroll = QScrollArea()
        self._cards_scroll.setWidgetResizable(True)
        self._cards_scroll.setStyleSheet(
            f"QScrollArea {{ border: none; background: transparent; }}"
        )
        self._cards_container = QWidget()
        self._cards_layout = QVBoxLayout(self._cards_container)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(6)
        self._cards_layout.addStretch(1)
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

        # Open default section
        self._open_default_section()

    def _show_placeholder(self) -> None:
        self._pathology_list.clear()
        self._clear_cards()
        self._image_label.clear()
        self._image_label.setText("Нет изображения")
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
        self._pathology_list.setCurrentRow(patho_idx)

    def _clear_cards(self) -> None:
        """Remove all parameter cards from the container."""
        for card in self._param_cards:
            self._cards_layout.removeWidget(card)
            card.deleteLater()
        self._param_cards.clear()

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
        """Scale pixmap to fill the container along the dominant axis.

        Wide images fill the container width; tall images fill the height.
        Uses KeepAspectRatioByExpanding so images are never smaller than the
        container in their dominant dimension — avoids the "small image in a
        big box" problem with pure KeepAspectRatio.
        """
        return pixmap.scaled(
            cw, ch,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )

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
        self._clear_cards()
        for topic, patho, grad, param in results:
            norm = self._format_norm(param)
            card = _ParameterCard(param, norm)
            card.setToolTip(f"{patho.name}" + (f" ({grad.name})" if grad else ""))
            self._cards_layout.insertWidget(self._cards_layout.count() - 1, card)
            self._param_cards.append(card)
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
        self._clear_cards()
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

    def _on_card_selected(self, card: _ParameterCard) -> None:
        """Handle card selection — update source label and highlight."""
        for c in self._param_cards:
            c.set_selected(c is card)
        if card._param.source:
            self._source_label.setText(card._param.source)
        else:
            self._source_label.clear()

    def _refresh_table(self) -> None:
        params = self._get_current_parameters()
        self._clear_cards()
        for param in params:
            norm = self._format_norm(param)
            card = _ParameterCard(param, norm)
            self._cards_layout.insertWidget(self._cards_layout.count() - 1, card)
            self._param_cards.append(card)

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
