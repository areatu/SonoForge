"""Автомат активного протокола (TP-3 PR-2, спека TP §6.2, §9).

Владелец состояния протокола одной вкладки: активный протокол, текущий шаг,
автопереход после фиксации, двухступенчатый Esc, пропуск и повтор.  Прогресс
считает чистая функция ``domain.protocols.progress()`` — раннер только хранит
``skipped`` и ``armed`` и переводит события в сигналы.

Дребезг проекции и интеграция с вкладками — на стороне ``AppController``
(§8.6).  Задержка автоперехода идёт через ``QTimer``; тесты вызывают
``advance_now()``/``cancel_advance()``, не поднимая цикл событий.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from PySide6.QtCore import QObject, QTimer, Signal

from ..domain.protocol_definitions import PROTOCOLS_BY_ID
from ..domain.protocols import (
    ProtocolProgress,
    StepSpec,
    StepState,
    StudyProjection,
    progress,
)

#: Задержка автоперехода после фиксации шага (Q-07: уведомление ≥ 2 с).
DEFAULT_AUTO_ADVANCE_MS = 2000

_DONE_STATES = (StepState.DONE, StepState.SHARED)


class EscapeResult(str, Enum):
    """Что сделал Esc (A-09: первый отменяет рисование, второй останавливает)."""

    NONE = "none"
    DRAWING_CANCELLED = "drawing_cancelled"
    ADVANCE_CANCELLED = "advance_cancelled"
    STOPPED = "stopped"


@dataclass(frozen=True)
class StepAction:
    """Payload взведённого шага: что вьюер должен включить (D-09)."""

    index: int
    tool_id: str
    contexts: frozenset[str]
    frame_hint: str | None = None
    aggregate: str | None = None
    open_protocol: str = ""


class ProtocolRunner(QObject):
    """Активный протокол вкладки: шаг, автопереход, Esc, пропуск и повтор."""

    progress_changed = Signal(object)  # ProtocolProgress
    action_requested = Signal(object)  # StepAction
    notification = Signal(str)  # код уведомления полосы шага
    finished = Signal(str)  # protocol_id
    stopped = Signal(str)  # причина остановки
    drawing_cancel_requested = Signal()

    def __init__(
        self,
        *,
        auto_advance_ms: int = DEFAULT_AUTO_ADVANCE_MS,
        tab_id: str = "",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._auto_advance_ms = auto_advance_ms
        self._tab_id = tab_id
        self._protocol_id = ""
        self._projection = StudyProjection()
        self._skipped: set[int] = set()
        self._armed: int | None = None
        self._pending_advance: int | None = None
        self._drawing = False
        self._finish_emitted = False
        self._authored: set[str] = set()
        self._advance_timer = QTimer(self)
        self._advance_timer.setSingleShot(True)
        self._advance_timer.timeout.connect(self.advance_now)

    # -- состояние -------------------------------------------------------

    @property
    def tab_id(self) -> str:
        return self._tab_id

    @property
    def auto_advance_ms(self) -> int:
        return self._auto_advance_ms

    @property
    def active(self) -> bool:
        return bool(self._protocol_id)

    @property
    def active_protocol_id(self) -> str:
        return self._protocol_id

    @property
    def armed_index(self) -> int | None:
        return self._armed

    @property
    def pending_advance(self) -> int | None:
        return self._pending_advance

    @property
    def drawing_active(self) -> bool:
        return self._drawing

    @property
    def authored_keys(self) -> frozenset[str]:
        """Ключи проекции, заработанные активным протоколом (origin = протокол)."""
        return frozenset(self._authored)

    @property
    def progress(self) -> ProtocolProgress | None:
        spec = self._spec()
        if spec is None:
            return None
        return progress(spec, self._projection, frozenset(self._skipped), armed=self._armed)

    def _spec(self):
        return PROTOCOLS_BY_ID.get(self._protocol_id) if self._protocol_id else None

    # -- жизненный цикл --------------------------------------------------

    def start(
        self,
        protocol_id: str,
        projection: StudyProjection | None = None,
        *,
        tab_id: str | None = None,
    ) -> None:
        """Запускает протокол; первым становится первый невыполненный шаг."""
        if protocol_id not in PROTOCOLS_BY_ID:
            raise KeyError(f"unknown protocol: {protocol_id!r}")
        if tab_id is not None:
            self._tab_id = tab_id
        self._protocol_id = protocol_id
        self._projection = projection if projection is not None else StudyProjection()
        self._skipped.clear()
        self._armed = None
        self._finish_emitted = False
        self._authored.clear()
        self.cancel_advance()
        self._drawing = False
        self._emit_progress()

    def stop(self, reason: str = "") -> None:
        """Останавливает протокол (Esc, смена исследования)."""
        if not self._protocol_id:
            return
        protocol_id = self._protocol_id
        self.cancel_advance()
        self._protocol_id = ""
        self._armed = None
        self._drawing = False
        self._authored.clear()
        self.stopped.emit(reason or protocol_id)

    def on_study_changed(self) -> None:
        """Смена исследования останавливает протокол (S-02)."""
        self.stop("study_changed")

    def set_tab(self, tab_id: str) -> None:
        self._tab_id = tab_id

    # -- проекция --------------------------------------------------------

    def set_projection(self, projection: StudyProjection) -> None:
        """Новая проекция: пересчёт и, если шаг закрыт, автопереход."""
        if not self._protocol_id:
            return
        self._projection = projection
        previous = self._armed
        if previous is not None:
            spec = self._spec()
            base = progress(spec, self._projection, frozenset(self._skipped))
            if base.step(previous).state in _DONE_STATES:
                self._authored.update(spec.steps[previous].satisfied_keys)
                self._armed = None
                self._schedule_advance()
        self._emit_progress()

    # -- шаги ------------------------------------------------------------

    def arm(self, index: int) -> None:
        """Взводит шаг: повтор клика по выполненному тоже взводит (Q-08)."""
        spec = self._spec()
        if spec is None or not (0 <= index < len(spec.steps)):
            return
        self.cancel_advance()
        self._armed = index
        self._skipped.discard(index)
        self._drawing = False
        self.action_requested.emit(self._payload(index, spec.steps[index]))
        self._emit_progress()

    def arm_current(self) -> None:
        current = self.progress
        if current is not None and current.current_index is not None:
            self.arm(current.current_index)

    def repeat(self, index: int) -> None:
        """Повтор выполненного шага: новое значение заменит старое (Q-08)."""
        self.arm(index)

    def skip(self, index: int | None = None) -> None:
        """Пропускает шаг (S / «Пропустить»); пропуск — только в памяти вкладки."""
        spec = self._spec()
        if spec is None:
            return
        target = index if index is not None else self._current_index()
        if target is None or not (0 <= target < len(spec.steps)):
            return
        self.cancel_advance()
        self._skipped.add(target)
        if self._armed == target:
            self._armed = None
        self._emit_progress()

    def set_drawing_active(self, active: bool) -> None:
        self._drawing = active

    # -- Esc -------------------------------------------------------------

    def on_escape(self) -> EscapeResult:
        """Двухступенчатый Esc (A-09)."""
        if self._drawing:
            self._drawing = False
            self.drawing_cancel_requested.emit()
            return EscapeResult.DRAWING_CANCELLED
        if self._pending_advance is not None:
            self.cancel_advance()
            return EscapeResult.ADVANCE_CANCELLED
        if self._protocol_id:
            self.stop("escape")
            return EscapeResult.STOPPED
        return EscapeResult.NONE

    # -- автопереход -----------------------------------------------------

    def _schedule_advance(self) -> None:
        spec = self._spec()
        if spec is None:
            return
        target = self._first_unmet()
        if target is None:
            self._emit_finished()
            return
        self._pending_advance = target
        self.notification.emit("auto_advance")
        if self._auto_advance_ms > 0:
            self._advance_timer.start(self._auto_advance_ms)

    def advance_now(self) -> None:
        """Выполняет отложенный автопереход (таймер либо тест)."""
        target, self._pending_advance = self._pending_advance, None
        if target is None:
            return
        self.arm(target)

    def cancel_advance(self) -> None:
        """Отменяет автопереход (Esc во время уведомления, §6.2)."""
        self._pending_advance = None
        if self._advance_timer.isActive():
            self._advance_timer.stop()

    # -- внутреннее ------------------------------------------------------

    def _current_index(self) -> int | None:
        spec = self._spec()
        if spec is None:
            return None
        return progress(spec, self._projection, frozenset(self._skipped), armed=self._armed).current_index

    def _first_unmet(self) -> int | None:
        spec = self._spec()
        if spec is None:
            return None
        return progress(spec, self._projection, frozenset(self._skipped)).current_index

    def _payload(self, index: int, step: StepSpec) -> StepAction:
        return StepAction(
            index=index,
            tool_id=step.tool_id,
            contexts=step.contexts,
            frame_hint=step.frame_hint,
            aggregate=step.aggregate,
            open_protocol=step.open_protocol,
        )

    def _emit_progress(self) -> None:
        current = self.progress
        if current is None:
            return
        self.progress_changed.emit(current)
        if current.finished:
            self._emit_finished()

    def _emit_finished(self) -> None:
        if self._protocol_id and not self._finish_emitted:
            self._finish_emitted = True
            self.finished.emit(self._protocol_id)
