# План: обогащение trace-результатов спектрального допплера метриками Vpeak / Vmean / PGpeak / PGmean

Дата: 2026-08-06

---

## 0. Что уже есть

| Компонент | Файл | Статус |
|-----------|------|--------|
| `DopplerTrace` с точками `(time_ms, velocity_cm_s)` | `domain/models/doppler.py` | Готово |
| VTI из trace (`_find_vti_cm`) | `domain/calculations/doppler_metrics.py` | Готово |
| Vpeak из маркера (`_find_peak_velocity`) | `domain/calculations/doppler_metrics.py` | Готово |
| Vmean = VTI / ET | `domain/calculations/doppler_metrics.py` | Готово |
| PGpeak / PGmean через Bernoulli | `domain/calculations/bernoulli.py` | Готово |
| Авто-трейс огибающей (`apply_auto_vti_trace`) | `presentation/doppler_overlay.py` | Готово |
| Ручной трейс (`finish_trace`) | `presentation/doppler_widget.py` | Готово |
| Отображение VTI/Vpeak/Vmean/PGpeak/PGmean в панели | `presentation/measurement_panel.py` | Готово |
| Отображение VTI в статусной строке после finish | `presentation/viewer_widget.py` | Готово |

**Что отсутствует:**
- Vpeak вычисляется из trace автоматически (сейчас только из маркера Vmax)
- Vmean вычисляется из trace duration автоматически (сейчас только из ET-интервала)
- После завершения трейса в статусной строке показываются только VTI, но не Vpeak/Vmean/PGpeak/PGmean

---

## 1. Задачи

### Задача 1. Добавить `_find_peak_velocity_from_trace` в `doppler_metrics.py`

**Файл:** `src/echo_personal_tool/domain/calculations/doppler_metrics.py`

**Что делать:**
- Добавить функцию `_find_peak_velocity_from_trace(dto, *labels)`, которая ищет trace с меткой, начинающейся с `vti`, и возвращает `max(|v|)` по точкам trace
- Для отрицательных скоростей (регургитация) использовать `max(abs(v))`

**Приоритет:** Высокий

### Задача 2. Добавить `_find_mean_velocity_from_trace` в `doppler_metrics.py`

**Файл:** `src/echo_personal_tool/domain/calculations/doppler_metrics.py`

**Что делать:**
- Добавить функцию `_find_mean_velocity_from_trace(dto)`, которая берёт первую VTI-трассу, вычисляет duration = (max_time - min_time) / 1000, возвращает `VTI / duration_s`

**Приоритет:** Высокий

### Задача 3. Обновить `compute()` с приоритетом маркер > trace

**Файл:** `src/echo_personal_tool/domain/calculations/doppler_metrics.py`

**Что делать:**
- Vpeak: сначала ищется маркер `Vmax`/`v_peak`; если не найден — берётся из trace
- Vmean: сначала ищется ET-интервал; если не найден — берётся из trace duration
- PGpeak / PGmean пересчитываются автоматически

**Приоритет:** Высокий

### Задача 4. Обновить `finish_doppler_trace()` в `viewer_widget.py`

**Файл:** `src/echo_personal_tool/presentation/viewer_widget.py` (строка ~2954)

**Что делать:**
- После завершения трейса показать в статусной строке VTI + Vpeak + Vmean + PGpeak + PGmean (если вычислимы)
- Формат: `"VTI AV: 22.4 cm | Vpeak: 178 cm/s | Vmean: 95 cm/s | PGpeak: 51 mmHg | PGmean: 36 mmHg"`

**Приоритет:** Средний

### Задача 5. Обновить `apply_auto_vti_trace()` в `doppler_overlay.py`

**Файл:** `src/echo_personal_tool/presentation/doppler_overlay.py` (строка ~509)

**Что делать:**
- После коммита trace вызвать `compute()` и показать результат в measurement_label
- Формат аналогичен задаче 4

**Приоритет:** Средний

### Задача 6. Добавить unit-тесты

**Файл:** `tests/unit/test_doppler_metrics.py` (или обновить существующий)

**Что тестировать:**
1. Trace с точками → Vpeak = max velocity
2. Trace + Vmax маркер → Vpeak берётся из маркера (приоритет)
3. Trace + ET интервал → Vmean = VTI / ET
4. Нет trace, нет маркеров → все `None`
5. Отрицательные скорости (регургитация) → Vpeak = max(|v|)
6. PGpeak / PGmean соответствуют Bernoulli от Vpeak / Vmean
7. Существующие тесты не регрессируют

**Приоритет:** Средний

---

## 2. Порядок реализации

1. Задачи 1–3 (ядро вычислений, `doppler_metrics.py`)
2. Задачи 4–5 (UI-отображение)
3. Задача 6 (тесты)

---

## 3. Зависимости

- Задачи 1–3 не зависят от других задач
- Задачи 4–5 зависят от 1–3
- Задача 6 зависит от 1–5

---

## 4. Риски

| Риск | Вероятность | Влияние | Смягчение |
|------|-------------|---------|-----------|
| Отрицательные скорости для регургитации дают отрицательный Vmean | Средняя | Низкое | Использовать `abs(VTI) / duration` для Vmean |
| Trace с одной точкой → duration = 0 | Низкая | Низкое | Проверка `duration_s > 0` |
| Регрессия существующих вычислений | Низкая | Высокое | Сохранить существующую логику как fallback, добавить приоритет маркер > trace |

---

## 5. Приёмочные критерии

1. При ручном трейсинге trace AV в статусной строке отображаются VTI + Vpeak + Vmean + PGpeak + PGmean
2. При авто-трейсинге VTI MV аналогично
3. Vpeak берётся из маркера, если он есть; иначе из trace
4. Vmean берётся из ET-интервала, если он есть; иначе из trace duration
5. PGpeak = 4 × (Vpeak/100)², PGmean = 4 × (Vmean/100)²
6. Все существующие тесты проходят
7. Новые unit-тесты покрывают все граничные случаи
