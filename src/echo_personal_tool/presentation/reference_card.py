"""Compact S2 reference card for a measurement row.

The card deliberately contains no image: illustrations remain in the S1
reference dialog.  It accepts a catalog/reference id and patient value so it
can be attached to measurement rows without coupling it to a particular panel.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout, QWidget

from echo_personal_tool.domain.services.reference_data_store import ParameterRef, ReferenceDataStore
from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.presentation.dark_theme import get_theme_tokens


class ReferenceCard(QWidget):
    """Image-free reference summary for a single parameter."""

    open_reference_requested = Signal(str)

    def __init__(
        self,
        data_store: ReferenceDataStore,
        param_id: str,
        value: float | None = None,
        *,
        sex: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.param_id = param_id
        self.value = value
        self.sex = sex
        self.parameter: ParameterRef | None = self._get_parameter(data_store, param_id)
        self._build_ui()

    @staticmethod
    def _get_parameter(store: ReferenceDataStore, param_id: str) -> ParameterRef | None:
        result = store.lookup(param_id)
        if result is None:
            return None
        _topic, _pathology, _gradation = result
        # Look up the concrete object in the pathology hierarchy. lookup()
        # intentionally returns location, while the parameter is in a child.
        for gradation in (_gradation,) if _gradation is not None else ():
            for parameter in gradation.parameters:
                if parameter.id == param_id:
                    return parameter
        if _pathology.parameters:
            return next((p for p in _pathology.parameters if p.id == param_id), None)
        for gradation in _pathology.gradations or []:
            for parameter in gradation.parameters:
                if parameter.id == param_id:
                    return parameter
        return None

    @staticmethod
    def _format_range(norm: object | None) -> str:
        if norm is None:
            return ""
        low, high = getattr(norm, "low", None), getattr(norm, "high", None)
        if low is not None and high is not None:
            return f"{low:g}–{high:g}"
        if low is not None:
            return f"≥{low:g}"
        if high is not None:
            return f"≤{high:g}"
        return ""

    def _build_ui(self) -> None:
        tokens = get_theme_tokens()
        self.setObjectName("referenceCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#referenceCard {{ background: {tokens['surface.1']}; border: 1px solid "
            f"{tokens['line.1']}; border-radius: 8px; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        if self.parameter is None:
            title = QLabel(self.param_id)
            layout.addWidget(title)
            missing = QLabel(tr("reference.card_missing"))
            missing.setWordWrap(True)
            layout.addWidget(missing)
            return

        param = self.parameter
        title = QLabel(param.full_name or param.name)
        title.setObjectName("referenceCardTitle")
        title.setStyleSheet(f"font-weight: 600; color: {tokens['text.1']};")
        layout.addWidget(title)
        if param.full_name and param.name != param.full_name:
            abbreviation = QLabel(param.name)
            abbreviation.setStyleSheet(f"color: {tokens['text.2']};")
            layout.addWidget(abbreviation)

        norm = param.norm_female if self.sex and self.sex.casefold() in {"f", "female", "ж", "жен", "женский"} else param.norm_male
        sex_label = tr("reference.card_female") if self.sex and self.sex.casefold() in {"f", "female", "ж", "жен", "женский"} else tr("reference.card_male")
        norm_text = self._format_range(norm)
        if norm_text:
            norm_line = QLabel(f"{sex_label} · {norm_text} {param.unit}".rstrip())
            layout.addWidget(norm_line)
        else:
            layout.addWidget(QLabel(tr("reference.card_no_norm")))

        if self.value is not None:
            value_text = f"{self.value:g} {param.unit}".rstrip()
            value_label = QLabel(value_text)
            value_label.setObjectName("referenceCardValue")
            layout.addWidget(value_label)
            if norm is not None:
                low, high = norm.low, norm.high
                in_range = (low is None or self.value >= low) and (high is None or self.value <= high)
                state = tr("reference.card_normal") if in_range else tr("reference.card_outside")
                chip = QLabel(state)
                chip.setFrameShape(QFrame.Shape.StyledPanel)
                chip.setStyleSheet(
                    f"QLabel {{ color: {tokens['text.1']}; background: "
                    f"{tokens['state.ok'] if in_range else tokens['state.warn']}; "
                    "padding: 3px 8px; border-radius: 10px; }}"
                )
                layout.addWidget(chip, 0, Qt.AlignmentFlag.AlignLeft)

        if param.method:
            layout.addWidget(QLabel(param.method))
        if param.note:
            note = QLabel(param.note)
            note.setWordWrap(True)
            layout.addWidget(note)
        if param.source:
            source = QLabel(param.source)
            source.setWordWrap(True)
            source.setStyleSheet(f"color: {tokens['text.2']};")
            layout.addWidget(source)

        open_button = QPushButton(tr("reference.card_open"))
        open_button.clicked.connect(self._open_reference)
        layout.addWidget(open_button, 0, Qt.AlignmentFlag.AlignRight)

    def _open_reference(self) -> None:
        self.open_reference_requested.emit(self.param_id)
        from echo_personal_tool.presentation.ase_reference_dialog import show_ase_reference_dialog

        show_ase_reference_dialog(self.window(), param_id=self.param_id)


def show_reference_card(
    data_store: ReferenceDataStore,
    param_id: str,
    value: float | None = None,
    *,
    sex: str | None = None,
    parent: QWidget | None = None,
) -> ReferenceCard:
    """Create and return a card; callers position it as a row tooltip/popover."""
    return ReferenceCard(data_store, param_id, value, sex=sex, parent=parent)
