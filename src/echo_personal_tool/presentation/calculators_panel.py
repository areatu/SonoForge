"""Calculators tab of the tool panel (Э11).

Built entirely from the calculator registry: an inputs table (value, unit,
provenance, "back to measured") and one card per calculator (outputs with
formulas, missing inputs, warnings, reference gradations, assumptions and
literature).

Two modes:

* **Study** — inputs come from the open study's measurements; any field can be
  overridden by typing, the override is applied by the controller and the
  results reach the study report.
* **Standalone** — numbers typed from the scanner screen, no image needed;
  results stay in the panel (copy button) and never enter a study report.
"""

from __future__ import annotations

import html

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.application.calculator_inputs import evaluate_standalone
from echo_personal_tool.domain.calculators import (
    CALCULATORS,
    CalculationsSnapshot,
    CalculatorSpec,
    InputValue,
    all_input_ids,
    input_spec,
    is_out_of_range,
)
from echo_personal_tool.domain.calculators.models import SOURCE_MANUAL, SOURCE_MISSING
from echo_personal_tool.domain.calculators.reference_hints import reference_hint
from echo_personal_tool.domain.calculators.text import (
    format_input_value,
    input_label,
    inputs_summary,
    missing_text,
    source_text,
    warning_text,
)
from echo_personal_tool.infrastructure.i18n import get_language, tr
from echo_personal_tool.presentation.ui_metrics import font_pixel_size, text_width

MODE_STUDY = "study"
MODE_STANDALONE = "standalone"

_SOURCE_COLORS = {
    SOURCE_MANUAL: "#3b82f6",
    SOURCE_MISSING: "#9ca3af",
}
_DEFAULT_SOURCE_COLOR = "#22a35a"
_WARNING_COLOR = "#f59e0b"


def parse_number(text: str) -> float | None:
    """Parse ``2,1`` / ``2.1``; empty → ``None``; garbage → ``ValueError``."""
    cleaned = text.strip().replace(",", ".").replace(" ", "")
    if not cleaned:
        return None
    return float(cleaned)


class _InputRow:
    def __init__(self, panel: CalculatorsPanel, input_id: str, grid: QGridLayout, row: int) -> None:
        self.input_id = input_id
        self.spec = input_spec(input_id)
        assert self.spec is not None
        self.label = QLabel()
        self.edit = QLineEdit()
        self.edit.setObjectName(f"calcInput_{input_id}")
        self.edit.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.edit.setPlaceholderText("—")
        self.edit.setMinimumWidth(text_width(self.edit, "0000.00", padding=18))
        self.edit.editingFinished.connect(lambda: panel._on_edit(input_id))
        self.unit = QLabel(self.spec.unit)
        self.source = QLabel()
        self.source.setObjectName(f"calcSource_{input_id}")
        self.source.setWordWrap(True)
        self.reset = QToolButton()
        self.reset.setObjectName(f"calcReset_{input_id}")
        self.reset.setText("↺")
        self.reset.setAutoRaise(True)
        self.reset.clicked.connect(lambda: panel._on_reset(input_id))
        self.reset.setVisible(False)
        grid.addWidget(self.label, row, 0)
        grid.addWidget(self.edit, row, 1)
        grid.addWidget(self.unit, row, 2)
        grid.addWidget(self.reset, row, 3)
        grid.addWidget(self.source, row + 1, 0, 1, 4)
        #: Text last written by the panel: unchanged text on focus-out is not an edit.
        self.shown_text = ""

    def reload_text(self) -> None:
        self.label.setText(input_label(self.input_id))
        self.label.setToolTip(tr(self.spec.name_key))
        self.edit.setToolTip(tr(self.spec.name_key))
        self.reset.setToolTip(tr("calc.reset_tooltip"))


class _CalculatorCard:
    def __init__(self, spec: CalculatorSpec, layout: QVBoxLayout) -> None:
        self.spec = spec
        self.box = QGroupBox()
        self.box.setObjectName(f"calcCard_{spec.id}")
        outer = QVBoxLayout(self.box)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(4)
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(2)
        outer.addLayout(grid)
        self.rows: dict[str, tuple[QLabel, QLabel, QLabel]] = {}
        for row, output in enumerate(spec.outputs):
            name = QLabel()
            name.setTextFormat(Qt.TextFormat.RichText)
            value = QLabel("—")
            value.setObjectName(f"calcOutput_{spec.id}_{output.id}")
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            font = value.font()
            font.setBold(True)
            value.setFont(font)
            unit = QLabel(output.unit)
            grid.addWidget(name, row, 0)
            grid.addWidget(value, row, 1)
            grid.addWidget(unit, row, 2)
            self.rows[output.id] = (name, value, unit)
        grid.setColumnStretch(0, 1)
        self.missing = QLabel()
        self.missing.setObjectName(f"calcMissing_{spec.id}")
        self.missing.setWordWrap(True)
        outer.addWidget(self.missing)
        self.warnings = QLabel()
        self.warnings.setObjectName(f"calcWarnings_{spec.id}")
        self.warnings.setWordWrap(True)
        self.warnings.setStyleSheet(f"color: {_WARNING_COLOR};")
        outer.addWidget(self.warnings)
        self.hints = QLabel()
        self.hints.setObjectName(f"calcHints_{spec.id}")
        self.hints.setWordWrap(True)
        self.hints.setTextFormat(Qt.TextFormat.RichText)
        outer.addWidget(self.hints)
        self.notes = QLabel()
        self.notes.setObjectName(f"calcNotes_{spec.id}")
        self.notes.setWordWrap(True)
        self.notes.setTextFormat(Qt.TextFormat.RichText)
        outer.addWidget(self.notes)
        layout.addWidget(self.box)

    def reload_text(self) -> None:
        self.box.setTitle(tr(self.spec.title_key))
        small = font_pixel_size(self.box, 0.85, minimum=9)
        for output in self.spec.outputs:
            name, value, _unit = self.rows[output.id]
            name.setText(
                f"<b>{html.escape(output.label)}</b><br>"
                f"<span style='color: gray; font-size: {small}px;'>{html.escape(output.formula)}</span>"
            )
            name.setToolTip(tr(output.name_key))
            value.setToolTip(tr(output.name_key))
        hints: list[str] = []
        seen: set[str] = set()
        for output in self.spec.outputs:
            if not output.reference_id or output.reference_id in seen:
                continue
            seen.add(output.reference_id)
            hint = reference_hint(output.reference_id, get_language())
            if hint is not None:
                hints.append(html.escape(hint.text()))
        if hints:
            title = html.escape(tr("calc.reference_title"))
            self.hints.setText(f"<span style='font-size: {small}px;'><b>{title}</b><br>{'<br>'.join(hints)}</span>")
        else:
            self.hints.clear()
        self.hints.setVisible(bool(hints))
        refs = "<br>".join(html.escape(item) for item in self.spec.references)
        self.notes.setText(
            f"<span style='color: gray; font-size: {small}px;'>"
            f"<b>{html.escape(tr('calc.assumptions_title'))}</b> {html.escape(tr(self.spec.assumptions_key))}<br>"
            f"<b>{html.escape(tr('calc.references_title'))}</b><br>{refs}</span>"
        )

    def update(self, calculations: CalculationsSnapshot | None) -> None:
        result = calculations.result(self.spec.id) if calculations is not None else None
        missing: list[str] = []
        for output in self.spec.outputs:
            _name, value, _unit = self.rows[output.id]
            item = result.output(output.id) if result is not None else None
            value.setText(item.formatted() if item is not None else "—")
            if item is None:
                missing.extend(i for i in self.spec.input_closure(output.id) if i not in missing)
            else:
                missing.extend(i for i in item.missing if i not in missing)
        self.missing.setText(missing_text(tuple(missing)) if missing else "")
        self.missing.setVisible(bool(missing))
        warnings = [warning_text(w) for w in result.warnings] if result is not None else []
        warnings = [f"⚠ {text}" for text in warnings if text]
        self.warnings.setText("\n".join(warnings))
        self.warnings.setVisible(bool(warnings))


class CalculatorsPanel(QWidget):
    """Registry-driven calculators with study and standalone modes."""

    #: ``(input_id, value | None)`` — study-mode override; ``None`` clears it.
    study_input_changed = Signal(str, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("calculatorsPanel")
        self._mode = MODE_STUDY
        self._has_study = False
        self._study_calculations: CalculationsSnapshot | None = None
        self._standalone_values: dict[str, float] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        top = QHBoxLayout()
        self._mode_combo = QComboBox()
        self._mode_combo.setObjectName("calcModeCombo")
        self._mode_combo.addItem("", MODE_STUDY)
        self._mode_combo.addItem("", MODE_STANDALONE)
        self._mode_combo.currentIndexChanged.connect(self._on_mode_combo)
        top.addWidget(self._mode_combo, 1)
        self._copy_button = QPushButton()
        self._copy_button.setObjectName("calcCopyButton")
        self._copy_button.clicked.connect(self.copy_results)
        top.addWidget(self._copy_button)
        self._clear_button = QPushButton()
        self._clear_button.setObjectName("calcClearButton")
        self._clear_button.clicked.connect(self.clear_standalone)
        top.addWidget(self._clear_button)
        root.addLayout(top)

        self._hint = QLabel()
        self._hint.setObjectName("calcModeHint")
        self._hint.setWordWrap(True)
        root.addWidget(self._hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(6)

        self._inputs_box = QGroupBox()
        self._inputs_box.setObjectName("calcInputsBox")
        grid = QGridLayout(self._inputs_box)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(1)
        grid.setColumnStretch(0, 1)
        self._rows: dict[str, _InputRow] = {}
        for index, input_id in enumerate(all_input_ids()):
            self._rows[input_id] = _InputRow(self, input_id, grid, index * 2)
        content_layout.addWidget(self._inputs_box)

        self._cards = [_CalculatorCard(spec, content_layout) for spec in CALCULATORS]

        self._ruo = QLabel()
        self._ruo.setObjectName("calcRuo")
        self._ruo.setWordWrap(True)
        content_layout.addWidget(self._ruo)
        content_layout.addStretch(1)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        self.reload_text()
        self._refresh()

    # ── public API ───────────────────────────────────────────────────────
    @property
    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> None:
        index = self._mode_combo.findData(mode)
        if index >= 0:
            self._mode_combo.setCurrentIndex(index)

    def set_study_calculations(self, calculations: CalculationsSnapshot | None, *, has_study: bool) -> None:
        if calculations == self._study_calculations and has_study == self._has_study:
            return
        self._study_calculations = calculations
        self._has_study = has_study
        if self._mode == MODE_STUDY:
            self._refresh()

    def current_calculations(self) -> CalculationsSnapshot | None:
        if self._mode == MODE_STANDALONE:
            return evaluate_standalone(self._standalone_values)
        return self._study_calculations

    def standalone_values(self) -> dict[str, float]:
        return dict(self._standalone_values)

    def clear_standalone(self) -> None:
        self._standalone_values.clear()
        if self._mode == MODE_STANDALONE:
            self._refresh(force_text=True)

    def results_text(self) -> str:
        """Plain-text summary for the clipboard (formulas and provenance included)."""
        calculations = self.current_calculations()
        if calculations is None or not calculations.has_values:
            return ""
        lines: list[str] = []
        seen: set[str] = set()
        for spec in CALCULATORS:
            result = calculations.result(spec.id)
            if result is None or not result.has_values:
                continue
            lines.append(tr(spec.title_key))
            for output in result.outputs:
                if not output.computed or output.id in seen:
                    continue
                seen.add(output.id)
                unit = f" {output.unit}" if output.unit else ""
                lines.append(f"  {output.label}: {output.formatted()}{unit}  [{output.formula}]")
            for warning in result.warnings:
                text = warning_text(warning)
                if text:
                    lines.append(f"  ! {text}")
        summary = inputs_summary(calculations)
        if summary:
            lines.append(tr("calc.report.inputs", inputs=summary))
        lines.append(tr("calc.ruo"))
        return "\n".join(lines)

    def copy_results(self) -> None:
        text = self.results_text()
        if text:
            QGuiApplication.clipboard().setText(text)

    def reload_text(self) -> None:
        self._mode_combo.setItemText(0, tr("calc.mode.study"))
        self._mode_combo.setItemText(1, tr("calc.mode.standalone"))
        self._copy_button.setText(tr("calc.copy"))
        self._copy_button.setToolTip(tr("calc.copy_tooltip"))
        self._clear_button.setText(tr("calc.clear"))
        self._clear_button.setToolTip(tr("calc.clear_tooltip"))
        self._inputs_box.setTitle(tr("calc.inputs_title"))
        self._ruo.setText(tr("calc.ruo"))
        for row in self._rows.values():
            row.reload_text()
        for card in self._cards:
            card.reload_text()
        self._refresh()

    # ── internals ────────────────────────────────────────────────────────
    def _on_mode_combo(self, _index: int) -> None:
        self._mode = self._mode_combo.currentData() or MODE_STUDY
        self._refresh(force_text=True)

    def _inputs(self) -> dict[str, InputValue]:
        calculations = self.current_calculations()
        if calculations is None:
            return {}
        return {item.id: item for item in calculations.inputs}

    def _refresh(self, *, force_text: bool = False) -> None:
        standalone = self._mode == MODE_STANDALONE
        editable = standalone or self._has_study
        if standalone:
            self._hint.setText(tr("calc.hint.standalone"))
        elif self._has_study:
            self._hint.setText(tr("calc.hint.study"))
        else:
            self._hint.setText(tr("calc.hint.no_study"))
        self._clear_button.setVisible(standalone)
        inputs = self._inputs()
        for input_id, row in self._rows.items():
            item = inputs.get(input_id, InputValue(input_id, None))
            row.edit.setEnabled(editable)
            text = format_input_value(item)
            if force_text or not row.edit.hasFocus():
                row.edit.setText(text)
                row.shown_text = text
            row.source.setText(self._source_line(item, standalone))
            color = _SOURCE_COLORS.get(item.source, _DEFAULT_SOURCE_COLOR)
            small = font_pixel_size(row.source, 0.85, minimum=9)
            row.source.setStyleSheet(f"color: {color}; font-size: {small}px;")
            if standalone:
                row.reset.setVisible(input_id in self._standalone_values)
            else:
                row.reset.setVisible(editable and item.overridden)
            out_of_range = item.available and is_out_of_range(input_id, item.value)
            row.edit.setStyleSheet(f"border: 1px solid {_WARNING_COLOR};" if out_of_range else "")
        calculations = self.current_calculations()
        for card in self._cards:
            card.update(calculations)
        self._copy_button.setEnabled(bool(calculations is not None and calculations.has_values))

    def _source_line(self, item: InputValue, standalone: bool) -> str:
        if standalone and item.source == SOURCE_MANUAL:
            return ""
        text = source_text(item)
        if item.overridden:
            spec = input_spec(item.id)
            auto = InputValue(item.id, item.auto_value, source=item.auto_source)
            unit = f" {spec.unit}" if spec is not None and spec.unit else ""
            text = tr("calc.source.overridden", value=f"{format_input_value(auto)}{unit}")
        return text

    def _on_edit(self, input_id: str) -> None:
        row = self._rows[input_id]
        text = row.edit.text()
        if text.strip() == row.shown_text.strip():
            return
        try:
            value = parse_number(text)
        except ValueError:
            row.edit.setText(row.shown_text)
            row.edit.setToolTip(tr("calc.invalid_number"))
            return
        spec = row.spec
        if value is not None and not (spec.editor_range[0] <= value <= spec.editor_range[1]):
            row.edit.setText(row.shown_text)
            row.edit.setToolTip(
                tr(
                    "calc.invalid_range",
                    low=f"{spec.editor_range[0]:g}",
                    high=f"{spec.editor_range[1]:g}",
                    unit=spec.unit,
                )
            )
            return
        row.edit.setToolTip(tr(spec.name_key))
        if self._mode == MODE_STANDALONE:
            if value is None:
                self._standalone_values.pop(input_id, None)
            else:
                self._standalone_values[input_id] = value
            self._refresh(force_text=True)
            return
        if not self._has_study:
            return
        row.shown_text = text
        self.study_input_changed.emit(input_id, value)
        # The controller recomputes synchronously; re-sync the text even when the
        # snapshot did not change (e.g. a cleared field without an override).
        self._refresh(force_text=True)

    def _on_reset(self, input_id: str) -> None:
        if self._mode == MODE_STANDALONE:
            self._standalone_values.pop(input_id, None)
            self._refresh(force_text=True)
            return
        self.study_input_changed.emit(input_id, None)
        self._refresh(force_text=True)
