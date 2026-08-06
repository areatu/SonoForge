"""Bottom bar: sex/age filter, source, description for selected parameter."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.constructor.editors.base_editor import BaseEditor
from echo_personal_tool.constructor.models import ParameterModel
from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.presentation.dark_theme import get_theme_palette


class MetadataEditor(BaseEditor):
    """Bottom bar: metadata for the selected parameter."""

    metadata_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._parameter: ParameterModel | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        p = get_theme_palette()
        self.setFixedHeight(80)
        self.setStyleSheet(f"background: {p['bg_control']}; border-top: 1px solid {p['border']};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(4)

        # Row 1: Sex + Age + Source
        row1 = QHBoxLayout()
        row1.setSpacing(12)

        # Sex
        sex_label = QLabel(tr("constructor.meta.sex_label"))
        sex_label.setStyleSheet(f"color: {p['text']};")
        row1.addWidget(sex_label)

        self._sex_male = QRadioButton(tr("constructor.meta.sex_male"))
        self._sex_male.setStyleSheet(f"color: {p['text']};")
        self._sex_male.toggled.connect(self._on_changed)
        row1.addWidget(self._sex_male)

        self._sex_female = QRadioButton(tr("constructor.meta.sex_female"))
        self._sex_female.setStyleSheet(f"color: {p['text']};")
        self._sex_female.toggled.connect(self._on_changed)
        row1.addWidget(self._sex_female)

        self._sex_both = QRadioButton(tr("constructor.meta.sex_both"))
        self._sex_both.setChecked(True)
        self._sex_both.setStyleSheet(f"color: {p['text']};")
        self._sex_both.toggled.connect(self._on_changed)
        row1.addWidget(self._sex_both)

        row1.addSpacing(12)

        # Age
        age_label = QLabel(tr("constructor.meta.age_label"))
        age_label.setStyleSheet(f"color: {p['text']};")
        row1.addWidget(age_label)

        self._age_spin = QSpinBox()
        self._age_spin.setRange(0, 120)
        self._age_spin.setValue(0)
        self._age_spin.setSpecialValueText("—")
        self._age_spin.setFixedWidth(60)
        self._age_spin.setStyleSheet(
            f"QSpinBox {{ color: {p['text']}; background: {p['bg_panel']}; border: 1px solid {p['border']}; padding: 2px; }}"  # noqa: E501
        )
        self._age_spin.valueChanged.connect(self._on_changed)
        row1.addWidget(self._age_spin)

        row1.addSpacing(12)

        # Source
        source_label = QLabel(tr("constructor.meta.source_label"))
        source_label.setStyleSheet(f"color: {p['text']};")
        row1.addWidget(source_label)

        self._source_edit = QLineEdit()
        self._source_edit.setPlaceholderText("ASE 2017, Guidelines...")
        self._source_edit.setStyleSheet(
            f"QLineEdit {{ color: {p['text']}; background: {p['bg_panel']}; border: 1px solid {p['border']}; padding: 2px 6px; }}"  # noqa: E501
        )
        self._source_edit.textChanged.connect(self._on_changed)
        row1.addWidget(self._source_edit, 1)

        layout.addLayout(row1)

        # Row 2: Description
        row2 = QHBoxLayout()
        row2.setSpacing(12)

        desc_label = QLabel(tr("constructor.meta.desc_label"))
        desc_label.setStyleSheet(f"color: {p['text']};")
        row2.addWidget(desc_label)

        self._desc_edit = QLineEdit()
        self._desc_edit.setPlaceholderText(tr("constructor.meta.desc_placeholder"))
        self._desc_edit.setStyleSheet(
            f"QLineEdit {{ color: {p['text']}; background: {p['bg_panel']}; border: 1px solid {p['border']}; padding: 2px 6px; }}"  # noqa: E501
        )
        self._desc_edit.textChanged.connect(self._on_changed)
        row2.addWidget(self._desc_edit, 1)

        layout.addLayout(row2)

    # ── Public API ──

    def set_parameter(self, param: ParameterModel) -> None:
        self._parameter = param
        self._block_signals(True)

        # Sex radio
        if param.norm_male and param.norm_female:
            self._sex_both.setChecked(True)
        elif param.norm_male:
            self._sex_male.setChecked(True)
        elif param.norm_female:
            self._sex_female.setChecked(True)
        else:
            self._sex_both.setChecked(True)

        self._source_edit.setText(param.source or "")
        self._desc_edit.setText(param.pathology_desc or "")

        self._block_signals(False)

    def _block_signals(self, block: bool) -> None:
        self._sex_male.blockSignals(block)
        self._sex_female.blockSignals(block)
        self._sex_both.blockSignals(block)
        self._age_spin.blockSignals(block)
        self._source_edit.blockSignals(block)
        self._desc_edit.blockSignals(block)

    def _on_changed(self, _: Any = None) -> None:
        if self._parameter is None:
            return

        self._parameter.source = self._source_edit.text() or None
        self._parameter.pathology_desc = self._desc_edit.text() or None

        self.metadata_changed.emit()
