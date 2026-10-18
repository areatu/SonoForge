"""Протоколы измерений: модель шагов и прогресс по проекции (TP-3 PR-1).

Протокол (спека TP §6) — упорядоченный список шагов; каждый шаг ссылается на
инструмент каталога и требуемый контекст клипа (режим, проекция).  Шаг может
быть необязательным или агрегировать несколько окон («максимум из N», Q-05).

**Прогресс = функция от проекции исследования** (D-08, S-11): шаг выполнен,
если нужный результат есть в той же проекции, по которой строится отчёт.
Поэтому значения, полученные другим протоколом или без протокола,
засчитываются автоматически (``shared``, ↗), переключение протоколов не
теряет прогресс, нового персистентного состояния нет (S-04/S-05 не
затрагиваются); «пропущено» живёт только в памяти вкладки.

Состояния шага (§4.3, §6.1): ``todo → current → done``; из ``done`` в
``stale`` (S-03); ``skipped``; ``shared``; ``locked(reason)``.

Модуль чистый (без Qt) и не видит UI: синтетическая проекция в тестах
устраивает его так же, как настоящая, собранная из ``MeasurementSnapshot``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum

from echo_personal_tool.domain.measurement_catalog import CATALOG

#: Коды причин блокировки (§4.3 «Заблокировано») — устойчивые идентификаторы
#: для слоёв выше: текст для пользователя берётся из локализации по коду.
LOCK_MODE = "mode"
LOCK_VIEW = "view"
LOCK_REQUIREMENT = "req"

#: Агрегация нескольких измерений одного шага (Q-05).
AGGREGATE_MAX = "max"


class StepState(str, Enum):
    """Состояние шага в прогрессе протокола."""

    TODO = "todo"
    CURRENT = "current"
    DONE = "done"
    STALE = "stale"
    SKIPPED = "skipped"
    SHARED = "shared"
    LOCKED = "locked"


@dataclass(frozen=True)
class StepSpec:
    """Шаг протокола (спека TP §8.4, с уточнениями §6.1).

    ``satisfied_by`` — ключи проекции, засчитывающие шаг; по умолчанию берутся
    ``result_keys`` инструмента, а если их нет — сам id инструмента (у
    большинства инструментов id совпадает с id измерения каталога).

    ``view`` — требуемая проекция клипа («A4C» / «A2C»); пусто — любая.
    ``frame_hint`` («ed» / «es») — подсказка кадра, не автоматика.

    ``tool_id`` пуст для шагов-входов без инструмента (чипы ДПП, П6.2) и для
    шагов-ссылок на другой протокол (иОЛП, П4.7) — у таких шагов заполняют
    ``satisfied_by``.
    """

    tool_id: str
    labels: Mapping[str, str]
    contexts: frozenset[str]
    satisfied_by: tuple[str, ...] = ()
    alt_tool_ids: tuple[str, ...] = ()
    view: str = ""
    frame_hint: str | None = None
    optional: bool = False
    aggregate: str | None = None
    open_protocol: str = ""

    @property
    def tool_ids(self) -> tuple[str, ...]:
        return tuple(tool_id for tool_id in (self.tool_id, *self.alt_tool_ids) if tool_id)

    @property
    def satisfied_keys(self) -> tuple[str, ...]:
        if self.satisfied_by:
            return self.satisfied_by
        tool = CATALOG.get(self.tool_id) if self.tool_id else None
        if tool is not None and tool.result_keys:
            return tuple(tool.result_keys)
        return (self.tool_id,)

    def label(self, language: str) -> str:
        return self.labels.get(language) or self.labels.get("ru") or self.labels.get("en") or ""

    def requirements(self) -> frozenset[str]:
        """Требования инструментов шага (калибровки, ППТ) из каталога."""
        needed: set[str] = set()
        for tool_id in self.tool_ids:
            tool = CATALOG.get(tool_id)
            if tool is not None:
                needed |= set(tool.requires)
        return frozenset(needed)


@dataclass(frozen=True)
class ProtocolSpec:
    """Протокол: упорядоченные шаги и производные результаты карточки."""

    id: str
    labels: Mapping[str, str]
    steps: tuple[StepSpec, ...]
    derived: tuple[str, ...] = ()
    notes: Mapping[str, str] = field(default_factory=dict)

    def label(self, language: str) -> str:
        return self.labels.get(language) or self.labels.get("ru") or self.labels.get("en") or ""

    def step(self, index: int) -> StepSpec:
        return self.steps[index]


@dataclass(frozen=True)
class ProjectionValue:
    """Одно значение проекции исследования (S-11)."""

    value: float | None = None
    #: Происхождение: id протокола, который его получил, либо "" — вне протокола.
    origin: str = ""
    #: S-03: значимый вход изменился, результат устарел (оценщики QH-1b.2).
    stale: bool = False


@dataclass(frozen=True)
class StudyProjection:
    """Проекция исследования и контекст вкладки для прогресса протокола.

    ``values`` — ключи результатов, те же, что видит сборщик отчёта (S-11):
    значение есть ⇔ шаг может быть засчитан.  Остальные поля описывают
    открытую вкладку: какие режимы клипа доступны (``clip_modes`` из
    ``ToolSpec.contexts``), метка проекции клипа (``clip_view``) и
    известные незакрытые требования (``unmet`` из ``ToolSpec.requires``) —
    по ним шаг получает ``locked`` с причиной.  Пустые контекст, метка и
    ``unmet`` ничего не блокируют: блокировка требует знания о проблеме.
    """

    values: Mapping[str, ProjectionValue] = field(default_factory=dict)
    clip_modes: frozenset[str] = frozenset()
    clip_view: str = ""
    unmet: frozenset[str] = frozenset()

    def has(self, key: str) -> bool:
        return key in self.values

    def get(self, key: str) -> ProjectionValue | None:
        return self.values.get(key)

    def with_value(self, key: str, value: ProjectionValue) -> StudyProjection:
        merged = dict(self.values)
        merged[key] = value
        return StudyProjection(
            values=merged,
            clip_modes=self.clip_modes,
            clip_view=self.clip_view,
            unmet=self.unmet,
        )


@dataclass(frozen=True)
class StepProgress:
    """Состояние одного шага в прогрессе протокола."""

    index: int
    state: StepState
    keys: tuple[str, ...] = ()
    reason: str = ""
    optional: bool = False
    aggregate: str | None = None


@dataclass(frozen=True)
class DerivedProgress:
    """Производный результат карточки (присутствует / устарел)."""

    key: str
    present: bool
    stale: bool = False


@dataclass(frozen=True)
class ProtocolProgress:
    """Прогресс протокола: шаги, производные, счётчики и текущий шаг."""

    protocol_id: str
    steps: tuple[StepProgress, ...]
    derived: tuple[DerivedProgress, ...] = ()
    done_count: int = 0
    skipped_count: int = 0
    total: int = 0
    current_index: int | None = None
    finished: bool = False

    def step(self, index: int) -> StepProgress:
        return self.steps[index]


def step_lock_reason(step: StepSpec, projection: StudyProjection) -> str:
    """Причина блокировки шага ("" — шаг разрешён).

    Случаи §4.3 «Заблокировано» / §6.2 «Не тот контекст»: не тот режим клипа
    («нужен CW-клип»), не та проекция («нужен клип A4C»), известная
    незакрытая калибровка или ППТ.  Пустые контекст, метка и ``unmet`` ничего
    не блокируют.
    """
    if step.contexts and projection.clip_modes and not (step.contexts & projection.clip_modes):
        return f"{LOCK_MODE}:{'/'.join(sorted(step.contexts))}"
    if step.view and projection.clip_view and step.view != projection.clip_view:
        return f"{LOCK_VIEW}:{step.view}"
    missing = sorted(step.requirements() & projection.unmet)
    if missing:
        return f"{LOCK_REQUIREMENT}:{'/'.join(missing)}"
    return ""


def pick_aggregate(aggregate: str | None, values: Iterable[float | None]) -> float | None:
    """Выбор значения из нескольких измерений шага.

    ``"max"`` — «максимум из N» (Q-05: Vmax АК / Vmax ТР из нескольких окон);
    без правила последнее измерение заменяет прежнее (Q-08).
    """
    numbers = [v for v in values if v is not None]
    if not numbers:
        return None
    if aggregate == AGGREGATE_MAX:
        return max(numbers)
    return numbers[-1]


def _step_state(
    step: StepSpec,
    index: int,
    projection: StudyProjection,
    skipped: frozenset[int],
    protocol_id: str,
) -> tuple[StepState, str]:
    keys = step.satisfied_keys
    present = [projection.get(key) for key in keys]
    if all(item is not None for item in present):
        if any(bool(item and item.stale) for item in present):
            return StepState.STALE, ""
        origins = {item.origin for item in present if item is not None}
        # Значение этого протокола — «выполнено»; любое другое происхождение
        # (другой протокол, свободное измерение) засчитывается автоматически
        # и помечается «из другого протокола» (↗).
        return (StepState.DONE, "") if origins == {protocol_id} else (StepState.SHARED, "")
    if index in skipped:
        return StepState.SKIPPED, ""
    reason = step_lock_reason(step, projection)
    return (StepState.LOCKED, reason) if reason else (StepState.TODO, "")


def progress(
    spec: ProtocolSpec,
    projection: StudyProjection,
    skipped: frozenset[int] = frozenset(),
    armed: int | None = None,
) -> ProtocolProgress:
    """Прогресс протокола по проекции исследования (чистая функция).

    ``skipped`` — индексы шагов, пропущенных пользователем (только в памяти
    вкладки).  ``armed`` — индекс взведённого шага (повтор клика по
    выполненному тоже взводит); без него текущим становится первый
    невыполненный.  ``current`` ставится на взведённый и на следующий
    невыполненный шаг с состоянием ``todo``; ``locked``, ``skipped`` и
    ``stale`` сохраняют своё состояние как более информативное.
    """
    steps: list[StepProgress] = []
    done_count = 0
    skipped_count = 0
    total = 0
    first_unmet: int | None = None
    for index, step in enumerate(spec.steps):
        state, reason = _step_state(step, index, projection, skipped, spec.id)
        if state in (StepState.DONE, StepState.SHARED):
            done_count += 1
        if state is StepState.SKIPPED:
            skipped_count += 1
        if not step.optional:
            total += 1
        if first_unmet is None and state not in (StepState.DONE, StepState.SHARED, StepState.SKIPPED):
            first_unmet = index
        steps.append(
            StepProgress(
                index=index,
                state=state,
                keys=step.satisfied_keys,
                reason=reason,
                optional=step.optional,
                aggregate=step.aggregate,
            )
        )

    current_index = armed if armed is not None else first_unmet
    if current_index is not None and 0 <= current_index < len(steps):
        current = steps[current_index]
        show_current = (
            current.state is StepState.TODO
            if armed is None
            else current.state not in (StepState.LOCKED, StepState.SKIPPED)
        )
        if show_current:
            steps[current_index] = StepProgress(
                index=current.index,
                state=StepState.CURRENT,
                keys=current.keys,
                reason=current.reason,
                optional=current.optional,
                aggregate=current.aggregate,
            )

    derived = tuple(
        DerivedProgress(
            key=key,
            present=projection.has(key),
            stale=bool(projection.get(key) and projection.get(key).stale),
        )
        for key in spec.derived
    )
    finished = total > 0 and all(
        step.state in (StepState.DONE, StepState.SHARED, StepState.SKIPPED) for step in steps if not step.optional
    )
    return ProtocolProgress(
        protocol_id=spec.id,
        steps=tuple(steps),
        derived=derived,
        done_count=done_count,
        skipped_count=skipped_count,
        total=total,
        current_index=current_index,
        finished=finished,
    )
