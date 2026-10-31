"""«Откуда значение» — the hover card of the report sheet (UI-4 PR-4, §4.6).

Hovering a value on the A4 sheet opens a card with what the document actually
records: the method, the clip and frame a caliper was drawn on, the inputs of a
calculator output and the freshness status.  Where the lineage was never
recorded the card says «происхождение не записано» — it never reconstructs a
source from the current study (QH §5.3, items 3 and 6).

The card draws only tokens of the active theme (no hex literals) and offers one
action: «Открыть кадры» jumps back to «Изображения» on the source clip.  The
window owns that jump; the card only emits :attr:`open_frames_requested`.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
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
    METHOD_DOPPLER_CALIPER,
    METHOD_LINEAR_CALIPER,
    METHOD_NOT_EVALUATED,
    METHOD_PLANIMETER,
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
    METHOD_NOT_EVALUATED: "report.origin.method_not_evaluated",
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

#: Clip label lookup: DICOM SOP Instance UID → the name the gallery shows.
ClipLabelProvider = Callable[[str], str]


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
    hover_entered = Signal()
    hover_left = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("reportValueCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(CARD_WIDTH)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._value: ReportValue | None = None
        self._clip_label_provider: ClipLabelProvider | None = None

        self._title = QLabel()
        self._title.setObjectName("reportValueCardTitle")
        self._title.setWordWrap(True)

        self._method = QLabel()
        self._method.setObjectName("reportValueCardMethod")
        self._method.setWordWrap(True)

        self._identity = QLabel()
        self._identity.setObjectName("reportValueCardIdentity")
        self._identity.setWordWrap(True)
        self._identity.setVisible(False)

        self._sources_title = QLabel()
        self._sources_title.setObjectName("reportValueCardSection")
        self._sources_title.setVisible(False)
        self._sources = QVBoxLayout()
        self._sources.setContentsMargins(0, 0, 0, 0)
        self._sources.setSpacing(0)

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

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(0)
        actions.addStretch(1)
        actions.addWidget(self._open)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)
        layout.addWidget(self._title)
        layout.addWidget(self._method)
        layout.addWidget(self._identity)
        layout.addWidget(self._sources_title)
        layout.addLayout(self._sources)
        layout.addWidget(self._inputs_title)
        layout.addLayout(self._inputs)
        layout.addWidget(self._status)
        layout.addLayout(actions)

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

    def set_clip_label_provider(self, provider: ClipLabelProvider | None) -> None:
        """Look up the gallery name of a clip; the UID tail is the fallback."""
        self._clip_label_provider = provider

    def show_value(self, value: ReportValue, *, origin: ValueOrigin | None = None) -> None:
        """Fill the card from *value* (its own origin by default) and show it."""
        self._value = value
        resolved = origin if origin is not None else value.origin
        self._title.setText(_title_text(value))
        self._method.setText(tr("report.origin.method") + ": " + method_text(resolved) if resolved else "")
        self._method.setVisible(resolved is not None)
        self._fill_identity(resolved)
        self._fill_sources(resolved)
        self._fill_inputs(resolved)
        text, recorded = freshness_text(resolved)
        self._status.setText(text)
        self._status.setProperty("recorded", recorded)
        _repolish(self._status)
        self._open.setVisible(bool(resolved is not None and resolved.clips))
        self.adjustSize()
        self.setVisible(True)
        self.raise_()

    def hide_card(self) -> None:
        self._value = None
        self.setVisible(False)

    # ── content ──────────────────────────────────────────────────────

    def _fill_identity(self, origin: ValueOrigin | None) -> None:
        text = ""
        if origin is not None and origin.measurement_id:
            short = origin.measurement_id[-8:]
            text = tr("report.origin.measurement_id", id=short, revision=origin.revision)
        self._identity.setText(text)
        self._identity.setVisible(bool(text))

    def _fill_sources(self, origin: ValueOrigin | None) -> None:
        _clear_boxes(self._sources)
        clips = origin.clips if origin is not None else ()
        for index, clip in enumerate(clips):
            name = self._clip_name(clip.sop_instance_uid)
            if clip.frame_index is None:
                text = tr("report.origin.clip", name=name)
            else:
                text = tr("report.origin.clip_frame", name=name, frame=int(clip.frame_index) + 1)
            label = QLabel(text)
            label.setObjectName("reportValueCardSource")
            label.setWordWrap(True)
            label.setProperty("clipIndex", index)
            label.setToolTip(clip.sop_instance_uid)
            self._sources.addWidget(label)
        self._sources_title.setText(tr("report.origin.sources"))
        self._sources_title.setVisible(bool(clips))

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

    def _clip_name(self, sop_instance_uid: str) -> str:
        if self._clip_label_provider is not None and sop_instance_uid:
            try:
                name = self._clip_label_provider(sop_instance_uid)
            except Exception:  # noqa: BLE001 - a label must never break the card
                name = ""
            if name:
                return name
        tail = sop_instance_uid[-8:] if sop_instance_uid else ""
        return tr("report.origin.clip_fallback", id=tail) if tail else tr("report.origin.clip_unnamed")

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
            """
        )


def _title_text(value: ReportValue) -> str:
    """«КДР ЛЖ · 48 мм» — label and value with its unit, never a second format."""
    unit = f" {value.unit}" if value.unit else ""
    return f"{value.label} · {value.display_value}{unit}"


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
