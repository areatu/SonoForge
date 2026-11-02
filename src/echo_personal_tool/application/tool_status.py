"""Статусы строк инструментов для панели 2.0 (TP-3 PR-2, спека TP §8.5).

Провайдер берёт проекцию исследования — ту же, что строит отчёт (S-11), — и
отдаёт для каждого инструмента каталога: форматированное значение (единица и
знаки из каталога, локаль), состояние (``done / stale / qc / locked``),
происхождение (id протокола либо пусто) и число измерений.

Актуальность (``stale``) приходит уже готовой в ``ProjectionValue.stale`` —
её считают оценщики QH-1b.2 (``domain/services/*_freshness.py``).  Панель
только показывает результат, сама не вычисляет.  Предупреждения QC
(``CalcWarning``) панель передаёт кодами; провайдер не строит локализованный
текст — это делает presentation по коду.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum

from ..domain.measurement_catalog import (
    CATALOG,
    DEFAULT_LINEAR_UNIT,
    MEASUREMENTS,
)
from ..domain.protocols import LOCK_REQUIREMENT, StudyProjection


class ToolState(str, Enum):
    """Состояние строки инструмента (спека TP §4.3)."""

    NONE = "none"
    DONE = "done"
    STALE = "stale"
    QC = "qc"
    LOCKED = "locked"


@dataclass(frozen=True)
class ToolStatus:
    """Статус одной строки инструмента."""

    tool_id: str
    key: str
    value: float | None = None
    text: str = ""
    unit: str = ""
    state: ToolState = ToolState.NONE
    origin: str = ""
    reason: str = ""
    count: int = 0


class ToolStatusProvider:
    """Собирает статусы строк из проекции исследования и каталога.

    ``language`` зарезервирован под локаль подписей; форматирование значения
    локаль не затрагивает (единицы и знаки — из каталога).  ``linear_unit`` и
    ``doppler_mode`` задают единицу и разрядность показанного значения.
    """

    def __init__(
        self,
        *,
        language: str = "ru",
        linear_unit: str = DEFAULT_LINEAR_UNIT,
        doppler_mode: str | None = None,
    ) -> None:
        self._language = language
        self._linear_unit = linear_unit
        self._doppler_mode = doppler_mode

    def result_key(self, tool_id: str) -> str:
        """Ключ проекции, по которому инструмент показывает значение."""
        tool = CATALOG.get(tool_id)
        if tool is not None and tool.result_keys:
            return tool.result_keys[0]
        return tool_id

    def format_value(self, key: str, value: float | None) -> tuple[str, str]:
        """Возвращает ``(текст, единица)`` для значения ключа."""
        spec = MEASUREMENTS.get(key)
        if value is None:
            return "", spec.unit(linear_unit=self._linear_unit, doppler_mode=self._doppler_mode) if spec else ""
        if spec is None:
            return f"{value:g}", ""
        unit = spec.unit(linear_unit=self._linear_unit, doppler_mode=self._doppler_mode)
        decimals = spec.decimals_for(unit)
        return f"{value:.{decimals}f}", unit

    def status(
        self,
        tool_id: str,
        projection: StudyProjection,
        *,
        warnings: Mapping[str, str] | None = None,
        count: int | None = None,
    ) -> ToolStatus:
        """Статус инструмента: значение, состояние, причина блокировки."""
        key = self.result_key(tool_id)
        item = projection.get(key)
        value = item.value if item is not None else None
        text, unit = self.format_value(key, value)
        origin = item.origin if item is not None else ""
        measurements = count if count is not None else (1 if item is not None else 0)

        if item is not None:
            state = ToolState.STALE if item.stale else ToolState.DONE
            reason = ""
            warning = (warnings or {}).get(key) or (warnings or {}).get(tool_id)
            if warning:
                state = ToolState.QC
                reason = warning
        else:
            state, reason = self._unmet_state(tool_id, projection)

        return ToolStatus(
            tool_id=tool_id,
            key=key,
            value=value,
            text=text,
            unit=unit,
            state=state,
            origin=origin,
            reason=reason,
            count=measurements,
        )

    def statuses(
        self,
        projection: StudyProjection,
        tool_ids: Iterable[str] | None = None,
        *,
        warnings: Mapping[str, str] | None = None,
    ) -> tuple[ToolStatus, ...]:
        """Статусы набора инструментов (по умолчанию — весь каталог)."""
        ids = tuple(tool_ids) if tool_ids is not None else tuple(CATALOG)
        return tuple(self.status(tool_id, projection, warnings=warnings) for tool_id in ids)

    @staticmethod
    def _unmet_state(tool_id: str, projection: StudyProjection) -> tuple[ToolState, str]:
        """Состояние строки без значения: блокировка по требованиям или пусто."""
        tool = CATALOG.get(tool_id)
        if tool is not None and projection.unmet:
            missing = sorted(tool.requires & projection.unmet)
            if missing:
                return ToolState.LOCKED, f"{LOCK_REQUIREMENT}:{'/'.join(missing)}"
        return ToolState.NONE, ""
