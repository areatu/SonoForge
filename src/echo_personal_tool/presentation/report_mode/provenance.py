"""«Откуда значение» — the hover card of the report sheet (UI-4 PR-4, §4.6).

Hovering a value on the A4 sheet opens a card with what the document actually
records: the method, the clips a caliper was drawn on, the inputs of a
calculator output and the freshness status.  Where the lineage was never
recorded the card says «происхождение не записано» — it never reconstructs a
source from the current study (QH §5.3, items 3 and 6).

The card draws only tokens of the active theme (no hex literals).  Its actions:
«Открыть кадры» jumps back to «Изображения» on the source clip, and when the
row was measured more than once the card lists the readings of every
acquisition (2026-11-18 list, item 1) — just the values, coloured by their
norms, no file names or frame numbers — and one click pins the reading for the
report.  The window owns the jumps and the pins; the card only emits
:attr:`open_frames_requested` and :attr:`choice_selected`.
"""

from __future__ import annotations

from PySide6.QtCore import QPropertyAnimation, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.application.localization import tr
from echo_personal_tool.domain.models.result_provenance import Freshness
from echo_personal_tool.domain.models.value_origin import (
    KIND_CALCULATOR,
    METHOD_CALCULATOR,
    METHOD_DOPPLER_AGGREGATE,
    METHOD_DOPPLER_CALIPER,
    METHOD_LINEAR_CALIPER,
    METHOD_LINEAR_DERIVED,
    METHOD_NOT_EVALUATED,
    METHOD_PLANIMETER,
    METHOD_SIMPSON,
    METHOD_SIMPSON_BIPLANE,
    METHOD_SIMPSON_MEAN_MONOPLANE,
    METHOD_SIMPSON_MONOPLANE,
    METHOD_STRAIN,
    METHOD_TEICHHOLZ,
    METHOD_VESSEL,
    REASON_NOT_RECORDED,
    ValueOrigin,
)
from echo_personal_tool.domain.services.report_builder import ReportValue
from echo_personal_tool.presentation.dark_theme import get_theme_tokens

#: Fixed width of the card; the sheet sits next to it, never under it.
CARD_WIDTH = 320

#: Method id → i18n key.  An unknown method shows its stable id, never prose.
_METHOD_KEYS: dict[str, str] = {
    METHOD_LINEAR_CALIPER: "report.origin.method_linear_caliper",
    METHOD_DOPPLER_CALIPER: "report.origin.method_doppler_caliper",
    METHOD_VESSEL: "report.origin.method_vessel",
    METHOD_PLANIMETER: "report.origin.method_planimeter",
    METHOD_CALCULATOR: "report.origin.method_calculator",
    METHOD_DOPPLER_AGGREGATE: "report.origin.method_doppler_aggregate",
    METHOD_STRAIN: "report.origin.method_strain",
    METHOD_NOT_EVALUATED: "report.origin.method_not_evaluated",
    METHOD_SIMPSON_BIPLANE: "report.origin.method_simpson_biplane",
    METHOD_SIMPSON_MONOPLANE: "report.origin.method_simpson_monoplane",
    METHOD_SIMPSON_MEAN_MONOPLANE: "report.origin.method_simpson_mean_monoplane",
    METHOD_SIMPSON: "report.origin.method_simpson",
    METHOD_TEICHHOLZ: "report.origin.method_teichholz",
    METHOD_LINEAR_DERIVED: "report.origin.method_linear_derived",
}

#: Input source code → i18n key of the calculator engine (Э11).
_SOURCE_KEYS: dict[str, str] = {
    "measured": "report.origin.source_measured",
    "dicom": "report.origin.source_dicom",
    "estimate": "report.origin.source_estimate",
    "patient": "report.origin.source_patient",
    "derived": "report.origin.source_derived",
    "manual": "report.origin.source_manual",
}


def method_text(origin: ValueOrigin) -> str:
    """Localized method line of one origin (stable id when unknown)."""
    key = _METHOD_KEYS.get(origin.method_id)
    return tr(key) if key else origin.method_id


def freshness_text(origin: ValueOrigin | None) -> tuple[str, bool]:
    """``(text, recorded)`` of the status line of the card.

    A value without an origin is *unverified*, and so is an origin whose inputs
    were never stored: both say «происхождение не записано» instead of
    implying the current study state is the source.
    """
    if origin is None:
        return tr("report.origin.not_recorded"), False
    if origin.freshness == Freshness.FRESH.value:
        return tr("report.origin.recorded"), True
    if origin.freshness == Freshness.STALE.value:
        return tr("report.origin.stale"), False
    if origin.freshness == Freshness.UNAVAILABLE.value:
        return tr("report.origin.unavailable"), False
    if origin.reason == REASON_NOT_RECORDED:
        return tr("report.origin.not_recorded"), False
    return tr("report.origin.unverified"), False


class ReportValueCard(QFrame):
    """The «откуда значение» card of one report value."""

    open_frames_requested = Signal(str, int)  # sop_instance_uid, frame_index
    #: Item 10 of the 2026-11-06 list: the physician renamed a planimeter row
    #: of the sheet.  ``(measurement_id, new_label)`` — the window writes it
    #: through the contour path, so the overlay and the report agree.
    rename_requested = Signal(str, str)
    #: The physician pinned one source candidate of a repeat row (2026-11-18
    #: list, item 1): ``(repeat_key, candidate_id)``; empty id = «Авто».
    choice_selected = Signal(str, str)
    hover_entered = Signal()
    hover_left = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("reportValueCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(CARD_WIDTH)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._value: ReportValue | None = None
        self._repeat_key: str = ""
        self._chosen: str = ""
        self._variant_buttons: list[tuple[str, QPushButton]] = []

        self._title = QLabel()
        self._title.setObjectName("reportValueCardTitle")
        self._title.setWordWrap(True)

        self._method = QLabel()
        self._method.setObjectName("reportValueCardMethod")
        self._method.setWordWrap(True)

        #: Norm line of the row (issue 277, §4.7): the range plus its gradation dot,
        #: the same scale the sheet's value dot and the panel rows show.
        self._norm_dot = QLabel()
        self._norm_dot.setObjectName("reportValueCardNormDot")
        self._norm_dot.setFixedSize(8, 8)
        self._norm = QLabel()
        self._norm.setObjectName("reportValueCardNorm")
        self._norm.setWordWrap(True)
        self._norm_host = QWidget()
        norm_row = QHBoxLayout(self._norm_host)
        norm_row.setContentsMargins(0, 0, 0, 0)
        norm_row.setSpacing(6)
        norm_row.addWidget(self._norm_dot)
        norm_row.addWidget(self._norm)
        norm_row.addStretch(1)

        self._identity = QLabel()
        self._identity.setObjectName("reportValueCardIdentity")
        self._identity.setWordWrap(True)
        self._identity.setVisible(False)

        #: «Варианты измерений» (2026-11-18 list, item 1): the readings of every
        #: acquisition of this row, values only — one click pins one for the
        #: report, «Авто» returns to following the latest acquisition.
        self._variants_title = QLabel()
        self._variants_title.setObjectName("reportValueCardVariants")
        self._variants_title.setVisible(False)
        self._variants_auto = QPushButton(tr("report.value_card.variants_auto"))
        self._variants_auto.setObjectName("reportValueCardAuto")
        self._variants_auto.setCursor(Qt.CursorShape.PointingHandCursor)
        self._variants_auto.setVisible(False)
        self._variants_auto.clicked.connect(lambda: self._choose_candidate(""))
        self._variants = QVBoxLayout()
        self._variants.setContentsMargins(0, 0, 0, 0)
        self._variants.setSpacing(0)

        self._inputs_title = QLabel()
        self._inputs_title.setObjectName("reportValueCardSection")
        self._inputs_title.setVisible(False)
        self._inputs = QVBoxLayout()
        self._inputs.setContentsMargins(0, 0, 0, 0)
        self._inputs.setSpacing(0)

        self._status = QLabel()
        self._status.setObjectName("reportValueCardStatus")
        self._status.setWordWrap(True)

        self._open = QPushButton()
        self._open.setObjectName("reportValueCardOpen")
        self._open.setCursor(Qt.CursorShape.PointingHandCursor)
        self._open.clicked.connect(self._open_frames)

        #: Item 10: a planimeter row is named here as well as at creation —
        #: the report is where the physician notices that two polygons read
        #: «Площадь1», and the round trip back to the images must not be needed.
        self._rename = QPushButton()
        self._rename.setObjectName("reportValueCardRename")
        self._rename.setCursor(Qt.CursorShape.PointingHandCursor)
        self._rename.clicked.connect(self._request_rename)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(0)
        actions.addStretch(1)
        actions.addWidget(self._rename)
        actions.addWidget(self._open)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)
        layout.addWidget(self._title)
        layout.addWidget(self._method)
        layout.addWidget(self._identity)
        variant_head = QHBoxLayout()
        variant_head.setContentsMargins(0, 0, 0, 0)
        variant_head.setSpacing(0)
        variant_head.addWidget(self._variants_title)
        variant_head.addStretch(1)
        variant_head.addWidget(self._variants_auto)
        layout.addLayout(variant_head)
        layout.addLayout(self._variants)
        layout.addWidget(self._inputs_title)
        layout.addLayout(self._inputs)
        layout.addWidget(self._status)
        layout.addLayout(actions)

        # The card fades in (2026-11-18 list, item 2): a hover card that pops
        # at full strength is easy to miss and feels abrupt next to the sheet.
        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity)
        self._fade = QPropertyAnimation(self._opacity, b"opacity", self)
        self._fade.setDuration(120)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)

        self.setVisible(False)
        self.apply_theme()
        self.reload_text()

    # ── state ────────────────────────────────────────────────────────

    @property
    def value(self) -> ReportValue | None:
        """The value the card currently shows (``None`` when hidden)."""
        return self._value

    @property
    def open_button(self) -> QPushButton:
        return self._open

    def show_value(self, value: ReportValue, *, origin: ValueOrigin | None = None) -> None:
        """Fill the card from *value* (its own origin by default) and show it."""
        self._value = value
        resolved = origin if origin is not None else value.origin
        self._title.setText(_title_text(value))
        self._method.setText(tr("report.origin.method") + ": " + method_text(resolved) if resolved else "")
        self._method.setVisible(resolved is not None)
        self._fill_identity(resolved)
        self._fill_variants(value)
        self._fill_inputs(resolved)
        text, recorded = freshness_text(resolved)
        self._status.setText(text)
        self._status.setProperty("recorded", recorded)
        _repolish(self._status)
        self._open.setVisible(bool(resolved is not None and resolved.clips))
        self._rename.setVisible(self._rename_target() is not None)
        self.adjustSize()
        self.setVisible(True)
        self.raise_()
        self._fade.stop()
        self._opacity.setOpacity(0.0)
        self._fade.start()

    def _rename_target(self) -> str | None:
        """``measurement_id`` of the row when it may be renamed, else ``None``.

        Only a planimeter value of a traced contour has a renameable name: a
        caliper is named by its catalog code, a calculator output by its
        formula, and neither is a free text.
        """
        origin = self._value.origin if self._value is not None else None
        if origin is None or not origin.measurement_id:
            return None
        if origin.method_id != METHOD_PLANIMETER:
            return None
        return origin.measurement_id

    def _request_rename(self) -> None:
        measurement_id = self._rename_target()
        if measurement_id is None or self._value is None:
            return
        from PySide6.QtWidgets import QInputDialog

        text, accepted = QInputDialog.getText(
            self,
            tr("report.rename.title"),
            tr("report.rename.prompt"),
            text=self._value.label,
        )
        label = str(text or "").strip()
        if not accepted or not label or label == self._value.label:
            return
        self.rename_requested.emit(measurement_id, label)

    def hide_card(self) -> None:
        self._value = None
        self._fade.stop()
        self._opacity.setOpacity(1.0)
        self.setVisible(False)

    # ── content ──────────────────────────────────────────────────────

    def _fill_norm(self, value: ReportValue) -> None:
        """Norm range plus the gradation dot of the row (issue 277, §4.7).

        A row without a handbook norm hides the line instead of showing an
        empty one — the same honest answer the S2 card gives.
        """
        from echo_personal_tool.presentation.reference_grades import grade_colors

        if not value.norm:
            self._norm_host.setVisible(False)
            return
        colors = grade_colors(value.norm_grade) if value.norm_grade else None
        if colors is None:
            self._norm_dot.hide()
        else:
            # The solid half of the pair: a dot has no room for a tinted fill.
            self._norm_dot.setStyleSheet(f"background: {colors[1]}; border-radius: 4px;")
            self._norm_dot.show()
        self._norm.setText(f"{tr('report.col_norm')}: {value.norm}")
        self._norm_host.setVisible(True)

    def _fill_identity(self, origin: ValueOrigin | None) -> None:
        text = ""
        if origin is not None and origin.measurement_id:
            short = origin.measurement_id[-8:]
            text = tr("report.origin.measurement_id", id=short, revision=origin.revision)
        self._identity.setText(text)
        self._identity.setVisible(bool(text))

    def _fill_variants(self, value: ReportValue) -> None:
        """One line per acquisition, values only (2026-11-18 list, item 1).

        File names and frame numbers stay out of the card: they do not fit the
        server's names and the physician chooses by the reading itself.  The
        colour of a line is the norm verdict the builder recorded for the
        candidate's readings — green in norm, red outside, plain text when no
        norm is known.
        """
        _clear_boxes(self._variants)
        repeat = value.repeat
        self._repeat_key = repeat.key if repeat is not None else ""
        self._chosen = repeat.override if repeat is not None else ""
        candidates = repeat.candidates if repeat is not None else ()
        active = self._chosen or (repeat.default_id if repeat is not None else "")
        self._variant_buttons = []
        for candidate in candidates:
            texts = [description for description, _source in candidate.parts]
            button = QPushButton("\n".join(texts))
            button.setObjectName("reportValueCardVariant")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setCheckable(True)
            button.setProperty("pathology", _pathology_property(candidate.pathological))
            button.setProperty("baseText", button.text())
            button.clicked.connect(lambda _checked=False, cid=candidate.id: self._choose_candidate(cid))
            self._variants.addWidget(button)
            self._variant_buttons.append((candidate.id, button))
        self._mark_active(active)
        self._variants_title.setText(tr("report.origin.variants"))
        self._variants_title.setVisible(bool(candidates))
        self._variants_auto.setText(tr("report.origin.variants_auto"))
        self._variants_auto.setToolTip(tr("report.origin.variants_auto_hint"))
        self._variants_auto.setVisible(bool(candidates))
        _repolish(self._variants_auto)

    def _mark_active(self, active: str) -> None:
        for candidate_id, button in self._variant_buttons:
            now = candidate_id == active
            button.setChecked(now)
            base = str(button.property("baseText") or "")
            button.setText(("✓ " if now else "") + base)

    def _choose_candidate(self, candidate_id: str) -> None:
        self._chosen = candidate_id
        self._mark_active(candidate_id or self._repeat_active_id())
        if self._repeat_key:
            self.choice_selected.emit(self._repeat_key, candidate_id)

    def _repeat_active_id(self) -> str:
        repeat = self._value.repeat if self._value is not None else None
        return repeat.default_id if repeat is not None else ""

    def _fill_inputs(self, origin: ValueOrigin | None) -> None:
        _clear_boxes(self._inputs)
        inputs = origin.inputs if origin is not None else ()
        for item in inputs:
            source_key = _SOURCE_KEYS.get(item.source)
            source = tr(source_key) if source_key else item.source
            text = f"{item.id} — {item.value}" if item.value else item.id
            if source:
                text = f"{text} · {source}"
            label = QLabel(text)
            label.setObjectName("reportValueCardInput")
            label.setWordWrap(True)
            label.setProperty("inputId", item.id)
            self._inputs.addWidget(label)
        title = tr("report.origin.inputs")
        if origin is not None and origin.kind == KIND_CALCULATOR:
            title = tr("report.origin.calculator_inputs")
        self._inputs_title.setText(title)
        self._inputs_title.setVisible(bool(inputs))

    def _open_frames(self) -> None:
        origin = self._value.origin if self._value is not None else None
        if origin is None or not origin.clips:
            return
        clip = origin.clips[0]
        self.open_frames_requested.emit(clip.sop_instance_uid, int(clip.frame_index or 0))

    # ── events ───────────────────────────────────────────────────────

    def enterEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.hover_entered.emit()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.hover_left.emit()
        super().leaveEvent(event)

    # ── language and theme ───────────────────────────────────────────

    def reload_text(self) -> None:
        self._open.setText(tr("report.origin.open_frames"))
        self._open.setToolTip(tr("report.origin.open_frames_hint"))
        self._rename.setText(tr("report.rename.action"))
        self._rename.setToolTip(tr("report.rename.hint"))
        if self._value is not None:
            self.show_value(self._value)

    def apply_theme(self) -> None:
        tokens = get_theme_tokens()
        self.setStyleSheet(
            f"""
            #reportValueCard {{
                background: {tokens["surface.1"]};
                border: 1px solid {tokens["line.1"]};
                border-radius: 6px;
            }}
            #reportValueCardTitle {{
                color: {tokens["text.1"]};
                font-weight: 600;
            }}
            #reportValueCardMethod {{
                color: {tokens["text.2"]};
            }}
            #reportValueCardIdentity, #reportValueCardSource,
            #reportValueCardInput {{
                color: {tokens["text.2"]};
            }}
            #reportValueCardSection {{
                color: {tokens["text.3"]};
                font-weight: 600;
                padding-top: 2px;
            }}
            #reportValueCardStatus {{
                color: {tokens["text.3"]};
                font-style: italic;
            }}
            #reportValueCardStatus[recorded="true"] {{
                color: {tokens["state.ok"]};
                font-style: normal;
            }}
            #reportValueCardOpen {{
                color: {tokens["accent.text"]};
                border: none;
                padding: 2px 0;
            }}
            #reportValueCardOpen:hover {{
                text-decoration: underline;
            }}
            #reportValueCardVariant {{
                color: {tokens["text.2"]};
                background: transparent;
                border: none;
                padding: 2px 4px;
                text-align: left;
            }}
            #reportValueCardVariant[pathology="false"] {{
                color: {tokens["state.ok"]};
            }}
            #reportValueCardVariant[pathology="true"] {{
                color: {tokens["state.err"]};
            }}
            #reportValueCardVariant:checked {{
                font-weight: 600;
            }}
            #reportValueCardAuto {{
                color: {tokens["accent.text"]};
                border: none;
                padding: 2px 0;
            }}
            #reportValueCardAuto:hover {{
                text-decoration: underline;
            }}
            #reportValueCardNorm {{
                color: {tokens["text.2"]};
            }}
            """
        )
        if self._value is not None:
            # The gradation dot has its own colour pair per theme surface.
            self._fill_norm(self._value)


def _title_text(value: ReportValue) -> str:
    """«КДР ЛЖ · 48 мм» — label and value with its unit, never a second format."""
    unit = f" {value.unit}" if value.unit else ""
    return f"{value.label} · {value.display_value}{unit}"


def _pathology_property(pathological: bool | None) -> str:
    """Stylesheet hook: ``\"true\"`` red, ``\"false\"`` green, ``\"\"`` unjudged."""
    if pathological is None:
        return ""
    return "true" if pathological else "false"


def _clear_boxes(layout: QVBoxLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()


def _repolish(widget: QWidget) -> None:
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()
