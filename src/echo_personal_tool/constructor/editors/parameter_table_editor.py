"""Center panel: editable parameter table with drag-drop rows/columns."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.constructor.editors.base_editor import BaseEditor
from echo_personal_tool.constructor.models import (
    NormRangeModel,
    ParameterModel,
    PathologyModel,
)
from echo_personal_tool.presentation.echopac_theme import get_theme_palette


class ParameterTableEditor(BaseEditor):
    """Center panel: editable QTableWidget with drag-drop."""

    parameters_changed = Signal()
    parameter_selected = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._pathology: PathologyModel | None = None
        self._parameters: list[ParameterModel] = []
        self._all_params: list[ParameterModel] = []
        self._font_family = "sans-serif"
        self._font_size = 13
        self._columns = list(_FLAT_COLUMNS)
        self._selected_col = -1
        self._drag_from_col = -1
        self._build_ui()

    def _build_ui(self) -> None:
        p = get_theme_palette()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header_widget = QWidget()
        header_widget.setStyleSheet(
            f"background: {p['bg_control']}; border-bottom: 1px solid {p['border']};"
        )
        header_layout = QVBoxLayout(header_widget)
        header_layout.setContentsMargins(8, 4, 8, 4)

        title_row = QHBoxLayout()
        title = QLabel("Параметры")
        title.setStyleSheet(f"color: {p['text']}; font-weight: bold;")
        title_row.addWidget(title)
        title_row.addStretch()

        # Font controls
        fl = QLabel("Шрифт:")
        fl.setStyleSheet(f"color: {p['text']}; font-size: 11px;")
        title_row.addWidget(fl)

        self._font_combo = QComboBox()
        self._font_combo.addItems(["sans-serif", "serif", "monospace", "Arial", "Times New Roman"])
        self._font_combo.setFixedWidth(120)
        self._font_combo.setStyleSheet(
            f"QComboBox {{ color: {p['text']}; background: {p['bg_panel']}; "
            f"border: 1px solid {p['border']}; padding: 2px 4px; font-size: 11px; }}"
        )
        self._font_combo.currentTextChanged.connect(self._on_font_changed)
        title_row.addWidget(self._font_combo)

        sl = QLabel("Размер:")
        sl.setStyleSheet(f"color: {p['text']}; font-size: 11px;")
        title_row.addWidget(sl)

        self._size_spin = QSpinBox()
        self._size_spin.setRange(8, 24)
        self._size_spin.setValue(self._font_size)
        self._size_spin.setFixedWidth(50)
        self._size_spin.setStyleSheet(
            f"QSpinBox {{ color: {p['text']}; background: {p['bg_panel']}; "
            f"border: 1px solid {p['border']}; padding: 2px; font-size: 11px; }}"
        )
        self._size_spin.valueChanged.connect(self._on_size_changed)
        title_row.addWidget(self._size_spin)

        header_layout.addLayout(title_row)

        # Buttons
        btn_row = QHBoxLayout()
        for text, slot in [
            ("+ Параметр", self._add_parameter),
            ("+ Столбец", self._add_column),
            ("Удалить столбец", self._delete_column),
        ]:
            btn = QPushButton(text)
            btn.setFixedHeight(26)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                f"QPushButton {{ border: 1px solid {p['border']}; border-radius: 3px; "
                f"padding: 2px 8px; color: {p['text']}; background: {p['bg_panel']}; font-size: 11px; }}"
                f"QPushButton:hover {{ background: {p['bg_button_hover']}; }}"
            )
            btn.clicked.connect(slot)
            btn_row.addWidget(btn)
        btn_row.addStretch()
        header_layout.addLayout(btn_row)

        # Column visibility toggles
        vis_row = QHBoxLayout()
        vis_label = QLabel("Показать:")
        vis_label.setStyleSheet(f"color: {p['text']}; font-size: 11px;")
        vis_row.addWidget(vis_label)

        self._col_visibility: dict[str, bool] = {c[0]: True for c in self._columns}
        self._col_checkboxes: dict[str, QCheckBox] = {}
        from PySide6.QtWidgets import QCheckBox
        for field, label in self._columns:
            cb = QCheckBox(label)
            cb.setChecked(True)
            cb.setStyleSheet(f"color: {p['text']}; font-size: 11px;")
            cb.stateChanged.connect(lambda state, f=field: self._toggle_column(f, state))
            self._col_checkboxes[field] = cb
            vis_row.addWidget(cb)
        vis_row.addStretch()
        header_layout.addLayout(vis_row)

        # Column indicator
        self._col_indicator = QLabel("Столбец: — | Перетащите заголовок для перемещения")
        self._col_indicator.setStyleSheet(f"color: {p['text_dim']}; font-size: 11px;")
        header_layout.addWidget(self._col_indicator)

        layout.addWidget(header_widget)

        # Table
        self._table = QTableWidget()
        self._table.setColumnCount(len(self._columns))
        self._table.setHorizontalHeaderLabels([c[1] for c in self._columns])
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.setAlternatingRowColors(True)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.horizontalHeader().setSectionsMovable(True)
        self._table.horizontalHeader().sectionMoved.connect(self._on_column_moved)
        self._table.verticalHeader().setVisible(True)
        self._table.verticalHeader().setDefaultSectionSize(28)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.setStyleSheet(self._table_style())
        self._table.cellChanged.connect(self._on_cell_changed)
        self._table.cellClicked.connect(self._on_cell_clicked)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        self._table.customContextMenuRequested.connect(self._context_menu)
        layout.addWidget(self._table, 1)

    def _table_style(self) -> str:
        p = get_theme_palette()
        return (
            f"QTableWidget {{ border: none; color: {p['text']}; background: {p['bg_panel']}; "
            f"gridline-color: {p['border']}; font-size: {self._font_size}px; "
            f"font-family: {self._font_family}; selection-background-color: {p['accent']}; }}"
            f"QTableWidget::item {{ padding: 4px; }}"
            f"QTableWidget::item:selected {{ background: {p['accent']}; color: white; }}"
            f"QHeaderView::section {{ background: {p['bg_control']}; color: {p['text']}; "
            f"border: 1px solid {p['border']}; padding: 4px; font-weight: bold; "
            f"border-bottom: 2px solid {p['accent']}; }}"
            f"QHeaderView::section:hover {{ background: {p['bg_button_hover']}; }}"
            f"QHeaderView::section:pressed {{ background: {p['accent_tab']}; color: white; }}"
        )

    # ── Public API ──

    def set_pathology(self, pathology: PathologyModel) -> None:
        self._pathology = pathology
        if pathology.has_gradations:
            self._columns = list(_GRADATION_COLUMNS)
        else:
            self._columns = list(_FLAT_COLUMNS)
        self._parameters = pathology.all_parameters()
        self._all_params = list(self._parameters)
        self._refresh_table()

    def set_parameters(self, parameters: list[ParameterModel]) -> None:
        self._pathology = None
        self._parameters = parameters
        self._all_params = list(parameters)
        self._columns = list(_FLAT_COLUMNS)
        self._refresh_table()

    def filter(self, query: str) -> None:
        self._parameters = [
            p for p in self._all_params
            if query in p.id.lower() or query in p.name.lower()
        ]
        self._refresh_table()

    def clear_filter(self) -> None:
        self._parameters = list(self._all_params)
        self._refresh_table()

    # ── Table refresh ──

    def _refresh_table(self) -> None:
        self._table.blockSignals(True)
        self._table.setColumnCount(len(self._columns))
        self._table.setHorizontalHeaderLabels([c[1] for c in self._columns])
        self._table.setRowCount(len(self._parameters))

        for row, param in enumerate(self._parameters):
            for col, (field, _) in enumerate(self._columns):
                value = self._get_field(param, field)
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, param.id)
                self._table.setItem(row, col, item)

        self._table.blockSignals(False)
        self._table.setStyleSheet(self._table_style())

    def _get_field(self, param: ParameterModel, field: str) -> str:
        if field == "id":
            return param.id
        elif field == "name":
            return param.name
        elif field == "unit":
            return param.unit
        elif field == "norm_male_low":
            return str(param.norm_male.low) if param.norm_male and param.norm_male.low is not None else ""
        elif field == "norm_male_high":
            return str(param.norm_male.high) if param.norm_male and param.norm_male.high is not None else ""
        elif field == "norm_female_low":
            return str(param.norm_female.low) if param.norm_female and param.norm_female.low is not None else ""
        elif field == "norm_female_high":
            return str(param.norm_female.high) if param.norm_female and param.norm_female.high is not None else ""
        elif field == "pathology_desc":
            return param.pathology_desc or ""
        elif field == "source":
            return param.source or ""
        return ""

    def _set_field(self, param: ParameterModel, field: str, value: str) -> None:
        if field == "id":
            param.id = value
        elif field == "name":
            param.name = value
        elif field == "unit":
            param.unit = value
        elif field == "norm_male_low":
            if not param.norm_male:
                param.norm_male = NormRangeModel()
            param.norm_male.low = _parse_float(value)
        elif field == "norm_male_high":
            if not param.norm_male:
                param.norm_male = NormRangeModel()
            param.norm_male.high = _parse_float(value)
        elif field == "norm_female_low":
            if not param.norm_female:
                param.norm_female = NormRangeModel()
            param.norm_female.low = _parse_float(value)
        elif field == "norm_female_high":
            if not param.norm_female:
                param.norm_female = NormRangeModel()
            param.norm_female.high = _parse_float(value)
        elif field == "pathology_desc":
            param.pathology_desc = value or None
        elif field == "source":
            param.source = value or None

    # ── Cell editing ──

    def _on_cell_changed(self, row: int, col: int) -> None:
        if row < 0 or row >= len(self._parameters) or col >= len(self._columns):
            return
        param = self._parameters[row]
        item = self._table.item(row, col)
        if not item:
            return
        field = self._columns[col][0]
        self._set_field(param, field, item.text())
        self.parameters_changed.emit()

    def _on_cell_clicked(self, row: int, col: int) -> None:
        self._selected_col = col
        col_name = self._columns[col][1] if col < len(self._columns) else ""
        self._col_indicator.setText(f"Столбец: {col_name} (номер {col + 1}) | Перетащите заголовок для перемещения")
        if row < len(self._parameters):
            self.parameter_selected.emit(self._parameters[row].id)

    def _on_selection_changed(self) -> None:
        items = self._table.selectedItems()
        if items:
            param_id = items[0].data(Qt.ItemDataRole.UserRole)
            if param_id:
                self.parameter_selected.emit(param_id)

    # ── Column drag-drop reorder ──

    def _on_column_moved(self, logical_index: int, old_visual: int, new_visual: int) -> None:
        if old_visual == new_visual:
            return
        # Reorder _columns to match visual order
        col = self._columns.pop(old_visual)
        self._columns.insert(new_visual, col)
        self.parameters_changed.emit()

    # ── Column visibility ──

    def _toggle_column(self, field: str, state: int) -> None:
        visible = state == Qt.CheckState.Checked.value
        self._col_visibility[field] = visible
        # Find column index and hide/show
        for col, (f, _) in enumerate(self._columns):
            if f == field:
                self._table.setColumnHidden(col, not visible)
                break

    # ── Add / Delete ──

    def _add_parameter(self) -> None:
        new_param = ParameterModel(id=f"param_{len(self._parameters) + 1}", name="Новый параметр")
        self._parameters.append(new_param)
        self._all_params.append(new_param)
        self._refresh_table()
        self.parameters_changed.emit()

    def _add_column(self) -> None:
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Новый столбец", "Имя столбца:")
        if ok and name:
            slug = name.lower().replace(" ", "_")
            self._columns.append((slug, name))
            self._refresh_table()
            self.parameters_changed.emit()

    def _delete_column(self) -> None:
        col = self._selected_col
        if col < 0 or col >= len(self._columns):
            QMessageBox.warning(self, "Ошибка", "Кликните на столбец для удаления")
            return
        field, label = self._columns[col]
        if field in ("id", "name"):
            QMessageBox.warning(self, "Ошибка", "Нельзя удалить обязательные столбцы")
            return
        reply = QMessageBox.question(
            self, "Удалить столбец", f"Удалить столбец «{label}»?"
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._columns.pop(col)
            self._selected_col = -1
            self._col_indicator.setText("Столбец: —")
            self._refresh_table()
            self.parameters_changed.emit()

    def delete_selected(self) -> None:
        rows = sorted(set(idx.row() for idx in self._table.selectedIndexes()), reverse=True)
        if not rows:
            return
        reply = QMessageBox.question(
            self, "Удалить параметры",
            f"Удалить {len(rows)} параметров?"
        )
        if reply == QMessageBox.StandardButton.Yes:
            for row in rows:
                if row < len(self._parameters):
                    param = self._parameters[row]
                    self._parameters.pop(row)
                    if param in self._all_params:
                        self._all_params.remove(param)
            self._refresh_table()
            self.parameters_changed.emit()

    # ── Font ──

    def _on_font_changed(self, family: str) -> None:
        self._font_family = family
        self._table.setStyleSheet(self._table_style())

    def _on_size_changed(self, size: int) -> None:
        self._font_size = size
        self._table.setStyleSheet(self._table_style())

    # ── Context menu ──

    def _context_menu(self, pos: Any) -> None:
        p = get_theme_palette()
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ color: {p['text']}; background: {p['bg_control']}; border: 1px solid {p['border']}; }}"
            f"QMenu::item:selected {{ background: {p['accent']}; }}"
        )
        menu.addAction("Добавить параметр", self._add_parameter)
        menu.addAction("Добавить столбец", self._add_column)
        menu.addAction("Удалить столбец", self._delete_column)
        menu.addSeparator()
        menu.addAction("Удалить выбранные", self.delete_selected)
        menu.exec(self._table.mapToGlobal(pos))


_FLAT_COLUMNS = [
    ("id", "ID"),
    ("name", "Название"),
    ("unit", "Ед."),
    ("norm_male_low", "Норм М (от)"),
    ("norm_male_high", "Норм М (до)"),
    ("norm_female_low", "Норм Ж (от)"),
    ("norm_female_high", "Норм Ж (до)"),
    ("pathology_desc", "Описание"),
    ("source", "Источник"),
]

_GRADATION_COLUMNS = [
    ("id", "ID"),
    ("name", "Название"),
    ("unit", "Ед."),
    ("norm_male_low", "Норм М (от)"),
    ("norm_male_high", "Норм М (до)"),
    ("norm_female_low", "Норм Ж (от)"),
    ("norm_female_high", "Норм Ж (до)"),
    ("pathology_desc", "Описание патологии"),
    ("source", "Источник"),
]


def _parse_float(s: str) -> float | None:
    try:
        return float(s)
    except (ValueError, TypeError):
        return None
