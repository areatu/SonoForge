"""Collapsible presentation-only controls embedded in the Controls tab."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.application.localization import tr
from echo_personal_tool.application.prepared_anatomy import POSITIONS, STRUCTURES, VIEWS, Annotation
from echo_personal_tool.presentation.prepared_anatomy_layer import DEFAULT_COLORS


class PreparedAnatomyControls(QWidget):
    """Appearance only; not connected to measurement or export actions."""

    load_requested = Signal()
    clear_requested = Signal()
    changed = Signal()
    create_requested = Signal()
    draw_requested = Signal()
    erase_requested = Signal()
    save_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 8, 0, 0)
        self.disclosure = QToolButton(self)
        self.disclosure.setObjectName("teachingAnatomyDisclosure")
        self.disclosure.setCheckable(True)
        self.disclosure.setText(tr("teaching_anatomy.title"))
        self.disclosure.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.disclosure.setArrowType(Qt.ArrowType.RightArrow)
        root.addWidget(self.disclosure)
        self.body = QWidget(self)
        column = QVBoxLayout(self.body)
        column.setContentsMargins(6, 4, 0, 4)
        self._notice = QLabel(tr("teaching_anatomy.not_measurement"))
        self._notice.setWordWrap(True)
        column.addWidget(self._notice)
        row = QHBoxLayout()
        self.load_button = QPushButton(tr("teaching_anatomy.load"))
        self.load_button.clicked.connect(self.load_requested.emit)
        self.clear_button = QPushButton(tr("teaching_anatomy.clear"))
        self.clear_button.clicked.connect(self.clear_requested.emit)
        row.addWidget(self.load_button)
        row.addWidget(self.clear_button)
        column.addLayout(row)
        self.source_label = QLabel(tr("teaching_anatomy.empty"))
        self.source_label.setWordWrap(True)
        column.addWidget(self.source_label)
        self.view_label = QLabel(tr("teaching_anatomy.view_label"))
        column.addWidget(self.view_label)
        self.view_combo = QComboBox()
        for view in VIEWS:
            self.view_combo.addItem(tr(f"teaching_anatomy.view.{view.lower()}"), view)
        column.addWidget(self.view_combo)
        self.position_label = QLabel(tr("teaching_anatomy.position_label"))
        column.addWidget(self.position_label)
        self.position_combo = QComboBox()
        for position in POSITIONS:
            self.position_combo.addItem(tr(f"teaching_anatomy.position.{position}"), position)
        column.addWidget(self.position_combo)
        self.create_button = QPushButton(tr("teaching_anatomy.create"))
        self.create_button.clicked.connect(self.create_requested.emit)
        column.addWidget(self.create_button)
        self.structure_label = QLabel(tr("teaching_anatomy.structure_label"))
        column.addWidget(self.structure_label)
        self.draw_structure = QComboBox()
        for structure in STRUCTURES:
            self.draw_structure.addItem(tr(f"teaching_anatomy.structure.{structure}"), structure)
        column.addWidget(self.draw_structure)
        draw_row = QHBoxLayout()
        self.draw_button = QPushButton(tr("teaching_anatomy.draw"))
        self.draw_button.clicked.connect(self.draw_requested.emit)
        self.erase_button = QPushButton(tr("teaching_anatomy.erase"))
        self.erase_button.clicked.connect(self.erase_requested.emit)
        draw_row.addWidget(self.draw_button)
        draw_row.addWidget(self.erase_button)
        column.addLayout(draw_row)
        self.save_button = QPushButton(tr("teaching_anatomy.save"))
        self.save_button.clicked.connect(self.save_requested.emit)
        column.addWidget(self.save_button)
        self.show_checkbox = QCheckBox(tr("teaching_anatomy.show"))
        self.show_checkbox.setChecked(True)
        self.show_checkbox.toggled.connect(lambda _checked: self.changed.emit())
        column.addWidget(self.show_checkbox)
        self.structure_rows: dict[str, tuple[QWidget, QCheckBox, QPushButton]] = {}
        for key in STRUCTURES:
            holder = QWidget(self.body)
            line = QHBoxLayout(holder)
            line.setContentsMargins(0, 0, 0, 0)
            check = QCheckBox(tr(f"teaching_anatomy.structure.{key}"))
            check.setChecked(True)
            check.toggled.connect(lambda _checked: self.changed.emit())
            color = QPushButton(tr("teaching_anatomy.color"))
            color.setToolTip(tr("teaching_anatomy.color_tip", structure=tr(f"teaching_anatomy.structure.{key}")))
            color.clicked.connect(lambda _, name=key: self._choose_color(name))
            line.addWidget(check, 1)
            line.addWidget(color)
            column.addWidget(holder)
            self.structure_rows[key] = (holder, check, color)
        self.labels_checkbox = QCheckBox(tr("teaching_anatomy.labels"))
        self.labels_checkbox.setChecked(True)
        self.labels_checkbox.toggled.connect(lambda _checked: self.changed.emit())
        column.addWidget(self.labels_checkbox)
        column.addWidget(QLabel(tr("teaching_anatomy.width")))
        self.width_combo = QComboBox()
        for width in (2, 3, 5, 8):
            self.width_combo.addItem(f"{width} px", width)
        self.width_combo.setCurrentIndex(1)
        self.width_combo.currentIndexChanged.connect(lambda _index: self.changed.emit())
        column.addWidget(self.width_combo)
        column.addWidget(QLabel(tr("teaching_anatomy.fill")))
        self.fill_combo = QComboBox()
        for alpha, label in ((0, "0%"), (35, "14%"), (65, "25%"), (105, "41%")):
            self.fill_combo.addItem(label, alpha)
        self.fill_combo.setCurrentIndex(2)
        self.fill_combo.currentIndexChanged.connect(lambda _index: self.changed.emit())
        column.addWidget(self.fill_combo)
        root.addWidget(self.body)
        self.body.hide()
        self.disclosure.toggled.connect(self._toggle_body)
        self.set_annotation(None)
        self.colors = dict(DEFAULT_COLORS)

    def _toggle_body(self, expanded: bool) -> None:
        self.body.setVisible(expanded)
        self.disclosure.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)

    def _choose_color(self, name: str) -> None:
        chosen = QColorDialog.getColor(QColor(self.colors[name]), self, tr("teaching_anatomy.color"))
        if chosen.isValid():
            self.colors[name] = chosen.name()
            self.changed.emit()

    def set_annotation(self, annotation: Annotation | None) -> None:
        self.source_label.setText(
            f"{annotation.view} / {tr(f'teaching_anatomy.position.{annotation.position}')}"
            if annotation is not None
            else tr("teaching_anatomy.empty")
        )
        enabled = annotation is not None
        self.clear_button.setEnabled(enabled)
        self.view_combo.setEnabled(not enabled)
        self.position_combo.setEnabled(not enabled)
        self.draw_button.setEnabled(enabled)
        self.erase_button.setEnabled(enabled)
        self.save_button.setEnabled(enabled)
        if annotation is not None:
            self.view_combo.setCurrentIndex(self.view_combo.findData(annotation.view))
            self.position_combo.setCurrentIndex(self.position_combo.findData(annotation.position))
        self.show_checkbox.setEnabled(enabled)
        self.labels_checkbox.setEnabled(enabled)
        self.width_combo.setEnabled(enabled)
        self.fill_combo.setEnabled(enabled)
        found = {shape.structure for frame in annotation.frames.values() for shape in frame} if annotation else set()
        for key, (holder, _check, _color) in self.structure_rows.items():
            holder.setVisible(key in found)

    def reload_text(self) -> None:
        self.disclosure.setText(tr("teaching_anatomy.title"))
        self._notice.setText(tr("teaching_anatomy.not_measurement"))
        self.load_button.setText(tr("teaching_anatomy.load"))
        self.clear_button.setText(tr("teaching_anatomy.clear"))
        self.create_button.setText(tr("teaching_anatomy.create"))
        self.draw_button.setText(tr("teaching_anatomy.draw"))
        self.erase_button.setText(tr("teaching_anatomy.erase"))
        self.save_button.setText(tr("teaching_anatomy.save"))
        self.view_label.setText(tr("teaching_anatomy.view_label"))
        self.position_label.setText(tr("teaching_anatomy.position_label"))
        self.structure_label.setText(tr("teaching_anatomy.structure_label"))
        for index in range(self.view_combo.count()):
            self.view_combo.setItemText(index, tr(f"teaching_anatomy.view.{self.view_combo.itemData(index).lower()}"))
        for index in range(self.position_combo.count()):
            self.position_combo.setItemText(
                index, tr(f"teaching_anatomy.position.{self.position_combo.itemData(index)}")
            )
        for index in range(self.draw_structure.count()):
            self.draw_structure.setItemText(
                index, tr(f"teaching_anatomy.structure.{self.draw_structure.itemData(index)}")
            )
        self.show_checkbox.setText(tr("teaching_anatomy.show"))
        self.labels_checkbox.setText(tr("teaching_anatomy.labels"))
        for key, (_holder, check, button) in self.structure_rows.items():
            check.setText(tr(f"teaching_anatomy.structure.{key}"))
            button.setText(tr("teaching_anatomy.color"))
            button.setToolTip(tr("teaching_anatomy.color_tip", structure=check.text()))
        if not self.clear_button.isEnabled():
            self.source_label.setText(tr("teaching_anatomy.empty"))
