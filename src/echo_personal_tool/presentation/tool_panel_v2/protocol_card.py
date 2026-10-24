"""Protocol card of the measurement panel 2.0 (TP-3 PR-3, spec TP §4.2, §6).

The card replaces the old blinking of the next button (§4.2: «Заменяет
мигание»): the header chooses the protocol, the body lists its steps with their
state glyph and value-free label, and the derived results of the card.  It is
collapsed to just the chooser while no protocol is running.

The card is presentation only.  It is handed a :class:`ProtocolProgress` (a pure
domain value) and emits ``protocol_selected`` / ``step_activated``; the window
owns ``ProtocolRunner`` and decides what a selection means.
"""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.domain.protocols import (
    LOCK_MODE,
    LOCK_REQUIREMENT,
    LOCK_VIEW,
    ProtocolProgress,
    ProtocolSpec,
    StepState,
)
from echo_personal_tool.presentation.dark_theme import get_theme_tokens
from echo_personal_tool.presentation.theme.token_restyle import TokenRestyleMixin

#: State glyphs of a step; never the only signal — the label carries the same.
_STEP_GLYPH: dict[StepState, str] = {
    StepState.TODO: "○",
    StepState.CURRENT: "◉",
    StepState.DONE: "✓",
    StepState.STALE: "⟳",
    StepState.SKIPPED: "—",
    StepState.SHARED: "↗",
    StepState.LOCKED: "🔒",
}


class ProtocolCard(TokenRestyleMixin, QFrame):
    """Header chooser plus the step list and derived results of a protocol."""

    protocol_selected = Signal(str)  # protocol_id, "" — none
    step_activated = Signal(int)
    stop_requested = Signal()

    def __init__(self, language: str = "ru", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("protocolCard")
        self._language = language
        self._protocols: tuple[ProtocolSpec, ...] = ()
        self._labels: dict[str, str] = {}
        self._syncing = False

        self._title = QLabel()
        self._title.setObjectName("protocolCardTitle")
        self._combo = QComboBox()
        self._combo.setObjectName("protocolCardCombo")
        self._combo.currentIndexChanged.connect(self._on_combo_changed)
        self._combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._progress = QLabel()
        self._progress.setObjectName("protocolCardProgress")
        self._stop = QPushButton()
        self._stop.setObjectName("protocolCardStop")
        self._stop.setFlat(True)
        self._stop.setCursor(Qt.CursorShape.PointingHandCursor)
        self._stop.clicked.connect(self.stop_requested.emit)

        header = QHBoxLayout()
        header.setContentsMargins(6, 4, 6, 2)
        header.setSpacing(6)
        header.addWidget(self._title)
        header.addWidget(self._progress)
        header.addStretch(1)
        header.addWidget(self._stop)

        self._steps_host = QWidget()
        self._steps_layout = QVBoxLayout(self._steps_host)
        self._steps_layout.setContentsMargins(6, 0, 6, 2)
        self._steps_layout.setSpacing(1)
        self._derived = QLabel()
        self._derived.setObjectName("protocolCardDerived")
        self._derived.setWordWrap(True)
        self._derived.setVisible(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(1)
        layout.addLayout(header)
        layout.addWidget(self._combo)
        layout.addWidget(self._steps_host)
        layout.addWidget(self._derived)

        self._stop.setVisible(False)
        self._steps_host.setVisible(False)
        self._apply_style()

    # ── Content ────────────────────────────────────────────────────

    def set_protocols(self, protocols: Iterable[ProtocolSpec]) -> None:
        """Fill the chooser with the six protocols (order preserved)."""
        self._protocols = tuple(protocols)
        self._syncing = True
        self._combo.clear()
        self._combo.addItem(self._labels.get("none", "—"), "")
        for spec in self._protocols:
            self._combo.addItem(spec.label(self._language), spec.id)
        self._syncing = False

    def set_labels(self, labels: dict[str, str]) -> None:
        """Localized strings of the card (title, stop, derived, reason words)."""
        self._labels.update(labels)
        self._title.setText(labels.get("title", ""))
        self._stop.setText(labels.get("stop", ""))
        self._stop.setToolTip(labels.get("stop", ""))
        if self._combo.count():
            self._combo.setItemText(0, labels.get("none", "—"))
        for index in range(1, self._combo.count()):
            spec = self._protocols[index - 1]
            self._combo.setItemText(index, spec.label(self._language))

    def set_progress(self, progress: ProtocolProgress | None) -> None:
        """Show the progress of ``progress``; ``None`` collapses to the chooser."""
        if progress is None:
            self._progress.setText("")
            self._stop.setVisible(False)
            self._steps_host.setVisible(False)
            self._derived.setVisible(False)
            self._set_combo_id("")
            return
        spec = self._spec(progress.protocol_id)
        self._progress.setText(f"{progress.done_count} / {progress.total}")
        self._stop.setVisible(True)
        self._steps_host.setVisible(True)
        self._set_combo_id(progress.protocol_id)
        self._fill_steps(progress)
        self._fill_derived(progress, spec)

    def selected_protocol_id(self) -> str:
        data = self._combo.currentData()
        return data if isinstance(data, str) else ""

    def _spec(self, protocol_id: str) -> ProtocolSpec | None:
        for spec in self._protocols:
            if spec.id == protocol_id:
                return spec
        return None

    def _set_combo_id(self, protocol_id: str) -> None:
        index = self._combo.findData(protocol_id)
        if index < 0 or index == self._combo.currentIndex():
            return
        self._syncing = True
        self._combo.setCurrentIndex(index)
        self._syncing = False

    def _fill_steps(self, progress: ProtocolProgress) -> None:
        while self._steps_layout.count():
            item = self._steps_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        spec = self._spec(progress.protocol_id)
        if spec is None:
            return
        for step in progress.steps:
            row = QPushButton()
            row.setObjectName("protocolCardStep")
            row.setFlat(True)
            row.setCursor(Qt.CursorShape.PointingHandCursor)
            row.setProperty("state", step.state.value)
            label = spec.steps[step.index].label(self._language)
            glyph = _STEP_GLYPH.get(step.state, "○")
            text = f"{glyph}  {label}"
            if step.state is StepState.SKIPPED:
                text = f"{text} · {self._labels.get('skipped', '')}"
            elif step.state is StepState.LOCKED and step.reason:
                text = f"{text} · {self._reason_text(step.reason)}"
            row.setText(text)
            row.setEnabled(step.state is not StepState.LOCKED)
            row.clicked.connect(lambda _checked=False, i=step.index: self.step_activated.emit(i))
            self._steps_layout.addWidget(row)

    def _fill_derived(self, progress: ProtocolProgress, spec: ProtocolSpec | None) -> None:
        if spec is None or not progress.derived:
            self._derived.setVisible(False)
            return
        names: list[str] = []
        for entry in progress.derived:
            text = self._derived_label(entry.key)
            if entry.stale:
                text = f"{text} · {self._labels.get('stale', '')}"
            names.append(text)
        self._derived.setText(f"{self._labels.get('derived', '')}: {', '.join(names)}")
        self._derived.setVisible(True)

    def _derived_label(self, key: str) -> str:
        from echo_personal_tool.domain.measurement_catalog import MEASUREMENTS

        spec = MEASUREMENTS.get(key)
        if spec is None:
            return key
        return spec.label(self._language).short

    def _reason_text(self, reason: str) -> str:
        kind, _, detail = reason.partition(":")
        if kind == LOCK_MODE:
            return self._labels.get("lock_mode", "mode").format(modes=detail)
        if kind == LOCK_VIEW:
            return self._labels.get("lock_view", "view").format(view=detail)
        if kind == LOCK_REQUIREMENT:
            return self._labels.get("lock_req", "req").format(req=detail)
        return detail

    def _on_combo_changed(self, _index: int) -> None:
        if self._syncing:
            return
        self.protocol_selected.emit(self.selected_protocol_id())

    # ── Styling ────────────────────────────────────────────────────

    def _apply_style(self) -> None:
        tokens = get_theme_tokens()
        self.setStyleSheet(
            f"""
            #protocolCard {{
                background: {tokens["surface.2"]};
                border-bottom: 1px solid {tokens["line.1"]};
            }}
            #protocolCardTitle {{
                color: {tokens["text.3"]};
                font-weight: 600;
            }}
            #protocolCardProgress {{
                color: {tokens["accent.text"]};
            }}
            #protocolCardStop {{
                color: {tokens["text.3"]};
                border: none;
                padding: 0 2px;
            }}
            #protocolCardCombo {{
                margin: 0 6px;
                min-height: 24px;
                border: 1px solid {tokens["line.2"]};
                border-radius: 4px;
                background: {tokens["surface.1"]};
                color: {tokens["text.1"]};
                padding: 1px 4px;
            }}
            #protocolCardStep {{
                text-align: left;
                padding: 3px 4px;
                border: 1px solid transparent;
                border-radius: 4px;
                color: {tokens["text.2"]};
            }}
            #protocolCardStep:hover {{
                background: {tokens["surface.3"]};
                color: {tokens["text.1"]};
            }}
            #protocolCardStep[state="current"] {{
                border-color: {tokens["accent"]};
                color: {tokens["text.1"]};
            }}
            #protocolCardStep:disabled {{
                color: {tokens["text.disabled"]};
            }}
            #protocolCardDerived {{
                color: {tokens["text.3"]};
                padding: 0 6px 2px 6px;
            }}
            """
        )
