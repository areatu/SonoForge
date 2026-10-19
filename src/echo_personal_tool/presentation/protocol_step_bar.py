"""Step bar under the snapshot (UI-3, spec TP §4.4 / §6.2, UD-04).

The active step of a protocol used to be a banner painted over the image; the
approved design moves it into a strip below the snapshot, between the image and
the cine loop (UI-redesign §4.4).  The bar owns only presentation: it shows the
protocol name, «шаг N из M», what to measure and on which frame, and the three
actions of a step — «Отменить точку» (cancel drawing), «Пропустить» (S) and
«Готово» (Enter).  For the RAP step (П6.2, Q-04) it shows the chips
3 / 8 / 15 / «другое…» instead of an instruction.

After a step is fixed the same strip shows the auto-advance notification
«✓ … → далее: …» with the «Esc — остановить автопереход» hint (Q-07); the bar
keeps it for at least ``minimum_ms`` so it is never a flash.  Everything is
static — no animation — so the ``reduce_motion`` setting needs no branching.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.presentation.dark_theme import get_theme_tokens
from echo_personal_tool.presentation.ui_metrics import control_height

#: The RAP chips of Q-04 (mmHg); «другое…» opens a free input.
RAP_CHIPS: tuple[int, ...] = (3, 8, 15)

#: Q-07: the notification of an auto-advance stays visible at least this long.
NOTIFICATION_MIN_MS = 2000


class ProtocolStepBar(QFrame):
    """Strip under the snapshot that carries the current step of a protocol."""

    skip_requested = Signal()
    done_requested = Signal()
    cancel_point_requested = Signal()
    rap_chosen = Signal(object)  # float mmHg from a chip
    rap_other_requested = Signal()  # «другое…» — the window opens a free input

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("protocolStepBar")
        self._active = False
        self._rap_active = False
        self.setVisible(False)

        self._title = QLabel()
        self._title.setObjectName("protocolStepTitle")
        self._counter = QLabel()
        self._counter.setObjectName("protocolStepCounter")
        self._instruction = QLabel()
        self._instruction.setObjectName("protocolStepInstruction")
        self._instruction.setWordWrap(True)

        self._cancel_button = self._make_button("protocolStepCancel", self.cancel_point_requested)
        self._skip_button = self._make_button("protocolStepSkip", self.skip_requested)
        self._done_button = self._make_button("protocolStepDone", self.done_requested)
        self._done_button.setProperty("primary", True)

        self._rap_values = self._make_rap_values()

        self._notification = QLabel()
        self._notification.setObjectName("protocolStepNotification")
        self._notification.setWordWrap(True)
        self._notification.setVisible(False)
        self._notification_hint = QLabel()
        self._notification_hint.setObjectName("protocolStepNotificationHint")
        self._notification_hint.setVisible(False)

        top = QHBoxLayout()
        top.setContentsMargins(8, 4, 8, 0)
        top.setSpacing(8)
        top.addWidget(self._title)
        top.addWidget(self._counter)
        top.addStretch(1)
        top.addWidget(self._cancel_button)
        top.addWidget(self._skip_button)
        top.addWidget(self._done_button)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(8, 0, 8, 4)
        bottom.setSpacing(8)
        bottom.addWidget(self._instruction, 1)
        bottom.addWidget(self._rap_values)
        bottom.addWidget(self._notification, 1)
        bottom.addWidget(self._notification_hint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(top)
        layout.addLayout(bottom)

        self._notify_timer = QTimer(self)
        self._notify_timer.setSingleShot(True)
        self._notify_timer.timeout.connect(self._clear_notification)
        self._apply_style()

    # ── Construction helpers ───────────────────────────────────────

    def _make_button(self, name: str, signal) -> QPushButton:
        button = QPushButton()
        button.setObjectName(name)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(signal.emit)
        button.setMinimumHeight(control_height(self, padding=6, minimum=24))
        return button

    def _make_rap_values(self) -> QWidget:
        box = QWidget()
        box.setObjectName("protocolStepRapValues")
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        for value in (*RAP_CHIPS, None):
            label = f"{value}" if value is not None else "…"
            button = QPushButton(label)
            button.setObjectName("protocolStepRapChip")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            if value is None:
                button.clicked.connect(self.rap_other_requested.emit)
            else:
                button.clicked.connect(lambda _checked=False, v=value: self.rap_chosen.emit(float(v)))
            row.addWidget(button)
        box.setVisible(False)
        return box

    # ── State ──────────────────────────────────────────────────────

    def is_active(self) -> bool:
        """Whether the bar currently carries a step (protocol is running)."""
        return self._active

    def notification_active(self) -> bool:
        return self._notification.isVisible()

    def set_step(
        self,
        *,
        protocol_label: str,
        index: int,
        total: int,
        step_label: str,
        frame_hint: str = "",
        can_cancel: bool = False,
        rap: bool = False,
    ) -> None:
        """Show the current step; a live auto-advance notification survives (Q-07)."""
        self._active = True
        self._rap_active = bool(rap)
        self._title.setText(protocol_label)
        self._counter.setText(f"{index + 1} / {total}")
        self._instruction.setText(step_label + (f" · {frame_hint}" if frame_hint else ""))
        self._instruction.setVisible(not rap)
        self._rap_values.setVisible(rap)
        self._cancel_button.setVisible(can_cancel)
        # Q-07: уведомление автоперехода держится ≥ 2 с в полосе. Любой прогресс
        # (например, правка контура) шлёт set_step и не должен его обрывать —
        # до истечения minimum_ms его сотрут только таймер, clear() или новое
        # уведомление.
        if not self._notify_timer.isActive():
            self._clear_notification()
        self.setVisible(True)

    def set_labels(
        self,
        *,
        cancel: str,
        skip: str,
        done: str,
        rap_hint: str = "",
        notification_hint: str = "",
    ) -> None:
        """Localized button texts and the RAP/notification hints."""
        self._cancel_button.setText(cancel)
        self._skip_button.setText(skip)
        self._done_button.setText(done)
        if rap_hint:
            self._instruction.setToolTip(rap_hint)
            self._rap_values.setToolTip(rap_hint)
        self._notification_hint.setText(notification_hint)

    def show_notification(self, text: str, *, hint: str = "", minimum_ms: int = NOTIFICATION_MIN_MS) -> None:
        """Show «✓ … → далее …»; kept for at least ``minimum_ms`` (Q-07)."""
        if not text:
            self._clear_notification()
            return
        self._notification.setText(text)
        self._notification.setVisible(True)
        if hint:
            self._notification_hint.setText(hint)
        self._notification_hint.setVisible(bool(self._notification_hint.text()))
        self._notify_timer.start(max(0, int(minimum_ms)))

    def clear(self) -> None:
        """No protocol — hide the bar entirely; the image grows by its height."""
        self._active = False
        self._rap_active = False
        self._clear_notification()
        self.setVisible(False)

    @property
    def rap_active(self) -> bool:
        return self._rap_active

    def _clear_notification(self) -> None:
        self._notify_timer.stop()
        self._notification.setVisible(False)
        self._notification_hint.setVisible(False)

    # ── Styling ────────────────────────────────────────────────────

    def _apply_style(self) -> None:
        tokens = get_theme_tokens()
        self.setStyleSheet(
            f"""
            #protocolStepBar {{
                background: {tokens["surface.1"]};
                border-top: 1px solid {tokens["line.1"]};
                border-bottom: 1px solid {tokens["line.1"]};
            }}
            #protocolStepTitle {{
                color: {tokens["text.1"]};
                font-weight: 600;
            }}
            #protocolStepCounter {{
                color: {tokens["text.3"]};
            }}
            #protocolStepInstruction {{
                color: {tokens["text.2"]};
            }}
            #protocolStepCancel, #protocolStepSkip {{
                color: {tokens["text.1"]};
                background: {tokens["surface.2"]};
                border: 1px solid {tokens["line.2"]};
                border-radius: 4px;
                padding: 2px 8px;
            }}
            #protocolStepCancel:hover, #protocolStepSkip:hover {{
                background: {tokens["surface.3"]};
            }}
            #protocolStepDone {{
                color: {tokens["accent.on"]};
                background: {tokens["accent"]};
                border: none;
                border-radius: 4px;
                padding: 2px 10px;
            }}
            #protocolStepRapChip {{
                color: {tokens["text.1"]};
                background: {tokens["surface.2"]};
                border: 1px solid {tokens["line.2"]};
                border-radius: 4px;
                padding: 2px 10px;
            }}
            #protocolStepRapChip:hover {{
                background: {tokens["surface.3"]};
            }}
            #protocolStepNotification {{
                color: {tokens["state.ok"]};
            }}
            #protocolStepNotificationHint {{
                color: {tokens["text.3"]};
            }}
            """
        )
