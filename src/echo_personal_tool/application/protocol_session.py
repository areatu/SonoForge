"""Сессия протокола одной вкладки (TP-3 PR-3, спека TP §6.2, §8.6, §9).

Владелец связки «раннер + проекция исследования + статусы строк».  Раннер
(:class:`ProtocolRunner`) хранит активный протокол и шаг; сессия строит по нему
проекцию (``AppController.study_projection``) и рассылает статусы строк
(:class:`ToolStatusProvider`).  Контекст вкладки (режимы клипа и проекция)
приходит снаружи замыканием — так вьюер не растёт вторым, протокольным
состоянием (QH-3, спека TP §9).

Сессия не знает ни Qt-компоновки, ни вьюера: presentation подписывается на её
сигналы и решает, что показать в карточке и полосе шага.  Это делает срез
тестируемым без окна: замыкание контекста и контроллер подставляются заглушкой.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QObject, Signal

from .protocol_runner import EscapeResult, ProtocolRunner

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..domain.protocols import ProtocolProgress, StudyProjection
from .tool_status import ToolStatusProvider

#: Замыкание контекста вкладки: возвращает ``(clip_modes, clip_view)``.
ClipContextProvider = Callable[[], tuple[frozenset[str], str]]


class ProtocolSession(QObject):
    """Активный протокол вкладки поверх проекции исследования."""

    progress_changed = Signal(object)  # ProtocolProgress | None
    action_requested = Signal(object)  # StepAction
    notification = Signal(str)  # код уведомления полосы шага
    finished = Signal(str)  # protocol_id
    stopped = Signal(str)  # причина остановки
    statuses_changed = Signal(object)  # tuple[ToolStatus, ...]
    drawing_cancel_requested = Signal()

    def __init__(
        self,
        controller: Any,
        *,
        clip_context: ClipContextProvider,
        language: str = "ru",
        # Manual by default: Enter / the next tile confirms; the window raises
        # this only when the footer toggle switches auto-advance on.
        auto_advance_ms: int = 0,
        tab_id: str = "",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._clip_context = clip_context
        self._provider = ToolStatusProvider(language=language)
        self._runner = ProtocolRunner(auto_advance_ms=auto_advance_ms, tab_id=tab_id, parent=self)
        self._runner.progress_changed.connect(self.progress_changed.emit)
        self._runner.action_requested.connect(self.action_requested.emit)
        self._runner.notification.connect(self.notification.emit)
        self._runner.finished.connect(self.finished.emit)
        self._runner.stopped.connect(self._on_stopped)
        self._runner.drawing_cancel_requested.connect(self.drawing_cancel_requested.emit)

    # ── Состояние ──────────────────────────────────────────────────

    @property
    def runner(self) -> ProtocolRunner:
        return self._runner

    @property
    def active(self) -> bool:
        return self._runner.active

    @property
    def active_protocol_id(self) -> str:
        return self._runner.active_protocol_id

    @property
    def progress(self) -> ProtocolProgress | None:
        return self._runner.progress

    def projection(self) -> StudyProjection:
        """Проекция исследования с контекстом вкладки и вкладом протокола."""
        return self._projection_for(self._runner.active_protocol_id, self._runner.authored_keys)

    def _projection_for(self, protocol_id: str, authored: frozenset[str]) -> StudyProjection:
        clip_modes, clip_view = self._clip_context()
        return self._controller.study_projection(
            clip_modes=clip_modes,
            clip_view=clip_view,
            protocol_id=protocol_id,
            authored=authored,
        )

    # ── Жизненный цикл ─────────────────────────────────────────────

    def start(self, protocol_id: str) -> None:
        """Запускает протокол; пустой id останавливает текущий."""
        if not protocol_id:
            self.stop("")
            return
        # Проекция собирается уже с новым id, иначе первый прогресс увидел бы
        # вклад пустого протокола.
        self._runner.start(protocol_id, self._projection_for(protocol_id, frozenset()))
        self._refresh()

    def stop(self, reason: str = "") -> None:
        self._runner.stop(reason)

    def skip(self, index: int | None = None) -> None:
        self._runner.skip(index)

    def arm(self, index: int) -> None:
        """Взводит шаг; раннер сам шлёт ``action_requested``."""
        self._runner.arm(index)

    def arm_current(self) -> None:
        self._runner.arm_current()

    def on_escape(self) -> EscapeResult:
        return self._runner.on_escape()

    def on_study_changed(self) -> None:
        self._runner.on_study_changed()

    def refresh(self) -> None:
        """Пересчитывает проекцию и статусы (сигнал события измерения)."""
        self._refresh()

    # ── Внутреннее ─────────────────────────────────────────────────

    def _refresh(self) -> None:
        projection = self.projection()
        if self._runner.active:
            self._runner.set_projection(projection)
            # set_projection мог засчитать шаг и пополнить authored — вторая
            # сборка нужна, чтобы происхождение значения попало в статусы.
            projection = self.projection()
        self.statuses_changed.emit(self._provider.statuses(projection))

    def _on_stopped(self, reason: str) -> None:
        self.stopped.emit(reason)
        self._refresh()
