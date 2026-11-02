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

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt, Signal
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
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.application.calculator_inputs import evaluate_standalone
from echo_personal_tool.application.localization import get_language, tr
from echo_personal_tool.domain.calculators import (
    CALCULATORS,
    CalculationsSnapshot,
    CalculatorSpec,
    InputValue,
    all_input_ids,
    input_spec,
    is_out_of_range,
    primary_input_ids,
    primary_output_ids,
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
from echo_personal_tool.presentation.dark_theme import get_theme_tokens
from echo_personal_tool.presentation.ui_animations import _reduce_motion_enabled
from echo_personal_tool.presentation.ui_metrics import font_pixel_size, text_width

_SECTION_ANIM_MS = 180

MODE_STUDY = "study"
MODE_STANDALONE = "standalone"

_SOURCE_TOKENS = {
    SOURCE_MANUAL: "provenance.manual",
    SOURCE_MISSING: "provenance.missing",
}
_DEFAULT_SOURCE_TOKEN = "provenance.default"
_WARNING_TOKEN = "provenance.warning"


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
        self.unit.setMinimumWidth(text_width(self.unit, "mmHg", padding=4))
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


class _SectionHeading(QToolButton):
    """Collapsible section heading of the Inputs group.

    A ``QToolButton`` takes the width of its text as its minimum, and the
    longest section name («Правые отделы и лёгочная гемодинамика  (0/5)»)
    claimed ~373 px inside a 280 px panel: the group grew past the viewport and
    its accent border was cut (item 2 of the 2026-10-23 list).  The painted text
    is elided to the real width while :meth:`text` keeps the full string for the
    tooltip and for the callers that read it.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_text = ""
        self._title = ""
        self._count = ""
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

    def text(self) -> str:  # noqa: D401 - Qt-compatible reader
        """The full heading, count included."""
        return self._full_text

    def set_heading(self, title: str, count: str) -> None:
        self._title = title
        self._count = count
        self._full_text = f"{title}{count}"
        self._apply()

    def minimumSizeHint(self) -> QSize:  # type: ignore[override]  # mypy does not check this file (outside tool.mypy.files)
        return QSize(0, super().minimumSizeHint().height())

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._apply()

    def _apply(self) -> None:
        if not self._full_text:
            QToolButton.setText(self, "")
            return
        available = self.width() - 26
        metrics = self.fontMetrics()
        if available <= 0:
            shown = self._full_text
        else:
            room = max(0, available - metrics.horizontalAdvance(self._count) - 6)
            shown = f"{metrics.elidedText(self._title, Qt.TextElideMode.ElideRight, room)}{self._count}"
        if shown != QToolButton.text(self):
            QToolButton.setText(self, shown)
        self.setToolTip(self._full_text if shown != self._full_text else "")


class _CardBox(QGroupBox):
    """A calculator card whose title never decides the width of the panel.

    ``QGroupBox.minimumSizeHint`` adds the width of its title.  A registry title
    such as «Площадь аортального клапана (уравнение непрерывности)» therefore
    made the card ~411 px wide, whatever the panel asked for: at the 280 px and
    even the widened 420 px width the card was clipped and its accent border —
    the «синяя обводка» of the acceptance list — fell outside the viewport
    (item 2 of 2026-10-23).  The title is elided to the real width instead, with
    the full text kept in :meth:`title` and in the tooltip.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_title = ""

    def title(self) -> str:  # noqa: D401 - Qt override
        """The full registry title (the painted one may be elided)."""
        return self._full_title

    def setTitle(self, text: str) -> None:  # noqa: N802 - Qt override
        self._full_title = text
        self._apply_title()

    def minimumSizeHint(self) -> QSize:  # type: ignore[override]  # mypy does not check this file (outside tool.mypy.files)
        """The layout's minimum width: the long title is not part of it."""
        hint = super().minimumSizeHint()
        layout = self.layout()
        width = layout.minimumSize().width() if layout is not None else 0
        return QSize(width or hint.width(), hint.height())

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._apply_title()

    def _apply_title(self) -> None:
        full = self._full_title
        if not full:
            QGroupBox.setTitle(self, "")
            return
        self.setToolTip(full)
        available = self.width() - 16
        shown = full if available <= 0 else self.fontMetrics().elidedText(full, Qt.TextElideMode.ElideRight, available)
        if shown != QGroupBox.title(self):
            QGroupBox.setTitle(self, shown)


class _CalculatorCard:
    def __init__(self, spec: CalculatorSpec, layout: QVBoxLayout) -> None:
        self.spec = spec
        self.box = _CardBox()
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
            name.setWordWrap(True)
            name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
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
        self.warnings.setStyleSheet(f"color: {get_theme_tokens()[_WARNING_TOKEN]};")
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
            for reference_id in output.reference_ids:
                if reference_id in seen:
                    continue
                seen.add(reference_id)
                hint = reference_hint(reference_id, get_language())
                if hint is not None:
                    line = html.escape(hint.text())
                    if hint.note:
                        line += f"<br><i>* {html.escape(hint.note)}</i>"
                    hints.append(line)
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

    def update(
        self,
        calculations: CalculationsSnapshot | None,
        inputs: dict[str, InputValue] | None = None,
    ) -> None:
        result = calculations.result(self.spec.id) if calculations is not None else None
        # A section of results appears as soon as one of *its own* inputs has a
        # value — before that every row reads «—», the missing line and the whole
        # literature block only make the panel longer with nothing to say
        # (item 1 of the 2026-10-23 acceptance list).  The Inputs section and
        # the mode hint above stay visible all the time.
        self.box.setVisible(self._has_own_results(inputs or {}, result))
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

    def _has_own_results(self, inputs: dict[str, InputValue], result: object | None) -> bool:
        """Whether the card has anything of its own to say yet.

        Two ways in: one of its *own* inputs has a value (the card then shows
        what it still needs), or one of its *own* outputs is computed.  Inputs
        and outputs borrowed from another card — LVOTd / LVOT area in the PISA,
        Qp/Qs and orifice formulas — are not evidence that this section was
        filled in; they used to unfold five empty cards at once (item 1 of the
        2026-10-23 acceptance list).
        """
        for input_id in primary_input_ids(self.spec):
            item = inputs.get(input_id)
            if item is not None and item.available:
                return True
        if result is not None:
            for output_id in primary_output_ids(self.spec):
                item = result.output(output_id)  # type: ignore[attr-defined]  # mypy does not check this file (outside tool.mypy.files)
                if item is not None and item.computed:
                    return True
        return False


class CalculatorsPanel(QWidget):
    """Registry-driven calculators with study and standalone modes."""

    #: ``(input_id, value | None)`` — study-mode override; ``None`` clears it.
    study_input_changed = Signal(str, object)

    def __init__(self, parent: QWidget | None = None, *, lazy: bool = False) -> None:
        super().__init__(parent)
        self.setObjectName("calculatorsPanel")
        self._mode = MODE_STUDY
        self._has_study = False
        self._study_calculations: CalculationsSnapshot | None = None
        self._standalone_values: dict[str, float] = {}
        # ~350 child widgets: inside the tool panel they are built on first show.
        # Every main window carries this hidden tab, and an app-wide stylesheet
        # change repolishes all live widgets, so building them up front made
        # window creation and theme changes noticeably slower.
        self._built = False
        self._surface: QWidget | None = None
        self._pinned_width: int | None = None
        self._section_anims: dict[str, QPropertyAnimation] = {}
        self._section_hide_slots: dict[str, object] = {}
        if not lazy:
            self._ensure_built()

    @property
    def is_built(self) -> bool:
        return self._built

    def showEvent(self, event) -> None:  # noqa: N802
        self._ensure_built()
        super().showEvent(event)

    def _ensure_built(self) -> None:
        if self._built:
            return
        self._built = True
        self._build()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._place_surface()
        if self._built:
            # Section headings and card titles are elided to the real width;
            # the panel glides between 280 and its widened width on tab switch.
            self._update_section_headings(self._inputs())
            for card in self._cards:
                card.box._apply_title()

    def set_clip_width(self, width: int | None) -> None:
        """Pin the built surface so a parent width glide does not reflow it."""
        self._pinned_width = None if width is None else int(width)
        self._place_surface()

    def clip_width(self) -> int | None:
        return self._pinned_width

    def _place_surface(self) -> None:
        surface = self._surface
        if surface is None:
            return
        width = self._pinned_width if self._pinned_width is not None else self.width()
        surface.setGeometry(0, 0, max(1, width), max(1, self.height()))

    def _build(self) -> None:
        self._surface = QWidget(self)
        self._surface.setObjectName("calcSurface")
        root = QVBoxLayout(self._surface)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        top = QHBoxLayout()
        self._mode_combo = QComboBox()
        self._mode_combo.setObjectName("calcModeCombo")
        self._mode_combo.addItem("", MODE_STUDY)
        self._mode_combo.addItem("", MODE_STANDALONE)
        self._mode_combo.setCurrentIndex(max(0, self._mode_combo.findData(self._mode)))
        self._mode_combo.currentIndexChanged.connect(self._on_mode_combo)
        # «Из исследования» is the longest item; let the combo shrink instead of
        # pushing the Copy / Clear buttons past the right edge of the panel.
        self._mode_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._mode_combo.setMinimumContentsLength(4)
        self._mode_combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
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
        # The panel is a column, not a canvas: a long title or a formula must wrap
        # or elide, never produce a horizontal scrollbar that pushes the cards'
        # right border out of the viewport (item 2 of the 2026-10-23 list).
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll = scroll
        content = QWidget()
        content.setObjectName("calcContent")
        content.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(6)

        self._inputs_box = QGroupBox()
        self._inputs_box.setObjectName("calcInputsBox")
        inputs_layout = QVBoxLayout(self._inputs_box)
        inputs_layout.setContentsMargins(4, 4, 4, 4)
        inputs_layout.setSpacing(2)
        self._rows: dict[str, _InputRow] = {}
        #: Collapsible section headings (continuity, PISA MR/AR, MS, right heart,
        #: LV, orifice, patient) and the input ids of each section.
        self._section_labels: dict[str, QToolButton] = {}
        self._section_bodies: dict[str, QWidget] = {}
        self._section_inputs: dict[str, list[str]] = {}
        grids: dict[str, QGridLayout] = {}
        for input_id in all_input_ids():
            spec = input_spec(input_id)
            section = spec.section if spec is not None else ""
            if section not in self._section_labels:
                heading = _SectionHeading()
                heading.setObjectName(f"calcSection_{section}")
                heading.setCheckable(True)
                heading.setChecked(False)
                heading.setAutoRaise(True)
                heading.setArrowType(Qt.ArrowType.RightArrow)
                heading.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
                font = heading.font()
                font.setBold(True)
                heading.setFont(font)
                body = QWidget()
                body.setObjectName(f"calcSectionBody_{section}")
                grid = QGridLayout(body)
                grid.setContentsMargins(12, 0, 0, 4)
                grid.setHorizontalSpacing(6)
                grid.setVerticalSpacing(1)
                grid.setColumnStretch(0, 1)
                grids[section] = grid
                body.setVisible(False)
                body.setMaximumHeight(0)
                heading.toggled.connect(lambda expanded, key=section: self._on_section_toggled(key, expanded))
                anim = QPropertyAnimation(body, b"maximumHeight", self)
                anim.setEasingCurve(QEasingCurve.Type.OutCubic)
                anim.setDuration(_SECTION_ANIM_MS)
                self._section_anims[section] = anim
                inputs_layout.addWidget(heading)
                inputs_layout.addWidget(body)
                self._section_labels[section] = heading
                self._section_bodies[section] = body
                self._section_inputs[section] = []
            self._rows[input_id] = _InputRow(self, input_id, grids[section], 2 * len(self._section_inputs[section]))
            self._section_inputs[section].append(input_id)
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
        self._refresh(force_text=True)
        self._place_surface()
        # PR2: surface built while the panel is hidden inherits hidden state
        # (QTabWidget had not shown the tab yet) — nobody showed it, so the
        # glide animation ran over an empty panel. Explicit show persists
        # once the parent tab becomes visible.
        self._surface.setVisible(True)

    # ── public API ───────────────────────────────────────────────────────
    @property
    def mode(self) -> str:
        return self._mode

    def set_section_expanded(self, section: str, expanded: bool) -> None:
        self._ensure_built()
        heading = self._section_labels.get(section)
        if heading is not None:
            heading.setChecked(expanded)

    def is_section_expanded(self, section: str) -> bool:
        self._ensure_built()
        heading = self._section_labels.get(section)
        return heading is not None and heading.isChecked()

    def set_mode(self, mode: str) -> None:
        if mode not in (MODE_STUDY, MODE_STANDALONE):
            return
        if not self._built:
            self._mode = mode
            return
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
        if not self._built:
            return  # _build() applies the current language
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
    def _on_section_toggled(self, section: str, expanded: bool) -> None:
        body = self._section_bodies[section]
        heading = self._section_labels[section]
        # Arrow changes at the start of the motion, not when it finishes.
        heading.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        anim = self._section_anims[section]
        previous = self._section_hide_slots.pop(section, None)
        if previous is not None:
            anim.finished.disconnect(previous)
        anim.stop()
        if _reduce_motion_enabled():
            if expanded:
                body.setVisible(True)
                body.setMaximumHeight(16777215)
            else:
                body.setMaximumHeight(0)
                body.setVisible(False)
            return
        if expanded:
            was_closed = (not body.isVisible()) or body.maximumHeight() == 0
            body.setVisible(True)
            body.setMaximumHeight(16777215)
            target = max(1, body.sizeHint().height())
            start = 0 if was_closed else min(body.height(), target)
            body.setMaximumHeight(start)
            anim.setStartValue(start)
            anim.setEndValue(target)
        else:
            start = body.height() if body.isVisible() and body.height() > 0 else max(1, body.sizeHint().height())
            anim.setStartValue(start)
            anim.setEndValue(0)

            def _hide(key: str = section) -> None:
                self._hide_section_body(key)

            self._section_hide_slots[section] = _hide
            anim.finished.connect(_hide)
        anim.start()

    def _hide_section_body(self, section: str) -> None:
        heading = self._section_labels.get(section)
        body = self._section_bodies.get(section)
        if heading is None or body is None or heading.isChecked():
            return
        body.setMaximumHeight(0)
        body.setVisible(False)

    def _update_section_headings(self, inputs: dict[str, InputValue]) -> None:
        """Heading text with the number of inputs that have a value (useful when collapsed).

        The heading is a full-width row of a 280 px column, so a long section
        name («Правые отделы и лёгочная гемодинамика») must be elided: as a plain
        ``QToolButton`` it claimed ~373 px and widened the whole Inputs group,
        clipping its right border (item 2).  The count and the full name stay in
        the tooltip.
        """
        for section, heading in self._section_labels.items():
            ids = self._section_inputs[section]
            filled = sum(1 for input_id in ids if (item := inputs.get(input_id)) is not None and item.available)
            title = tr(f"calc.section.{section}")
            count = f"  ({filled}/{len(ids)})"
            if isinstance(heading, _SectionHeading):
                heading.set_heading(title, count)
            else:  # pragma: no cover - defensive, the build always makes one
                heading.setText(f"{title}{count}")

    def _on_mode_combo(self, _index: int) -> None:
        self._mode = self._mode_combo.currentData() or MODE_STUDY
        self._refresh(force_text=True)

    def _inputs(self) -> dict[str, InputValue]:
        calculations = self.current_calculations()
        if calculations is None:
            return {}
        return {item.id: item for item in calculations.inputs}

    def _refresh(self, *, force_text: bool = False) -> None:
        if not self._built:
            return  # state is kept; _build() renders it
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
        theme_tokens = get_theme_tokens()
        for input_id, row in self._rows.items():
            item = inputs.get(input_id, InputValue(input_id, None))
            row.edit.setEnabled(editable)
            text = format_input_value(item)
            if force_text or not row.edit.hasFocus():
                row.edit.setText(text)
                row.shown_text = text
            row.source.setText(self._source_line(item, standalone))
            color_token = _SOURCE_TOKENS.get(item.source, _DEFAULT_SOURCE_TOKEN)
            color = theme_tokens[color_token]
            small = font_pixel_size(row.source, 0.85, minimum=9)
            row.source.setStyleSheet(f"color: {color}; font-size: {small}px;")
            if standalone:
                row.reset.setVisible(input_id in self._standalone_values)
            else:
                row.reset.setVisible(editable and item.overridden)
            out_of_range = item.available and is_out_of_range(input_id, item.value)
            row.edit.setStyleSheet(f"border: 1px solid {theme_tokens[_WARNING_TOKEN]};" if out_of_range else "")
        self._update_section_headings(inputs)
        calculations = self.current_calculations()
        for card in self._cards:
            card.update(calculations, inputs)
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
