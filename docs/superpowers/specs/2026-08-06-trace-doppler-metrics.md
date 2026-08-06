# Спецификация: обогащение trace-результатов спектрального допплера метриками Vpeak / Vmean / PGpeak / PGmean

Дата: 2026-08-06

---

## 1. Проблема

При использовании инструментов трейсинга в полосе спектрального допплера (trace AV, trace MV, trace AR, trace MR, trace TR, trace PR) результатом является только VTI. Для получения Vpeak, Vmean, PGpeak, PGmean пользователь должен отдельно размещать пиковые маркеры (Vmax) и интервалы (ET), что увеличивает количество шагов и снижает скорость рабочего процесса.

При этом сам trace уже содержит всю необходимую информацию — огибающая скорости по времени. Vpeak = max(velocity) на trace, Vmean = VTI / duration, PGpeak/PGmean — из Bernoulli.

## 2. Цель

Оптимизировать trace-инструменты так, чтобы по результату трейсинга (ручного или авто-) автоматически вычислялись и отображались:

| Метрика | Формула | Источник |
|---------|---------|----------|
| VTI | `∫ v dt / 1000` | уже есть |
| Vpeak | `max(v)` по точкам trace | новый |
| Vmean | `VTI / duration_s` | новый |
| PGpeak | `4 × (Vpeak / 100)²` | новый |
| PGmean | `4 × (Vmean / 100)²` | новый |

## 3. Область применения

- Все trace-метки, начинающиеся с `VTI` (VTI, VTI AV, VTI MV, VTI AR, VTI MR, VTI TR, VTI PR и т.д.)
- Ручной трейсинг (`finish_trace` в `doppler_widget.py`)
- Авто-трейсинг (`apply_auto_vti_trace` в `doppler_overlay.py`)
- Отображение в панели Measurements (`measurement_panel.py`)
- Форматирование отчёта (`measurement_report_formatter.py`)

## 4. Детали реализации

### 4.1. Вычисление Vpeak из trace

В `doppler_metrics.py` добавить функцию:

```python
def _find_peak_velocity_from_trace(dto: DopplerMeasurementDTO, *labels: str) -> float | None:
    """Vpeak = максимальная скорость по точкам trace, чья метка начинается с 'vti'."""
    wanted = {_normalize_label(label) for label in labels}
    candidates: list[float] = []
    for trace in dto.traces:
        if not _normalize_label(trace.label).startswith("vti"):
            continue
        if not trace.points:
            continue
        max_v = max(point[1] for point in trace.points)
        candidates.append(max_v)
    return max(candidates) if candidates else None
```

### 4.2. Вычисление Vmean из trace

```python
def _find_mean_velocity_from_trace(dto: DopplerMeasurementDTO) -> float | None:
    """Vmean = VTI / duration (сек). Использует первую VTI-трассу."""
    vti = _find_vti_cm(dto)
    if vti is None or vti <= 0:
        return None
    for trace in dto.traces:
        if not _normalize_label(trace.label).startswith("vti"):
            continue
        if len(trace.points) < 2:
            continue
        times = [point[0] for point in trace.points]
        duration_s = (max(times) - min(times)) / 1000.0
        if duration_s > 0:
            return vti / duration_s
    return None
```

### 4.3. PGpeak и PGmean

Уже вычисляются в `doppler_metrics.py` через `pressure_gradient_mmhg()`. Нужно только убедиться, что `vpeak_cm_s` и `vmean_cm_s` теперь берутся из trace, а не только из пиковых маркеров.

### 4.4. Приоритет источников Vpeak

1. Если есть пиковый маркер `Vmax` / `v_peak` — использовать его (ручная коррекция пользователя имеет приоритет).
2. Иначе — вычислить Vpeak из trace (максимальная скорость по точкам).
3. Если нет ни маркера, ни trace — `None`.

Аналогично для Vmean:
1. Если есть интервал ET и VTI — использовать `VTI / ET_s` (текущая логика).
2. Иначе если есть trace с точками — использовать `VTI / duration_s` trace.
3. Иначе — `None`.

### 4.5. Изменения в `doppler_metrics.py`

```python
def compute(dto: DopplerMeasurementDTO) -> DopplerResults:
    # ... существующий код ...

    vti_cm = _find_vti_cm(dto)

    # Vpeak: marker > trace
    vpeak_cm_s = _find_peak_velocity(dto, "vmax", "v_peak", "vmax")
    if vpeak_cm_s is None:
        vpeak_cm_s = _find_peak_velocity_from_trace(dto)

    # Vmean: ET-interval > trace-duration
    vmean_cm_s = None
    if vti_cm is not None:
        et_ms = _find_interval_duration_ms(dto, "et")
        if et_ms is not None and et_ms > 0:
            vmean_cm_s = vti_cm / (et_ms / 1000.0)
        else:
            vmean_cm_s = _find_mean_velocity_from_trace(dto)

    pgpeak_mmhg = pressure_gradient_mmhg(vpeak_cm_s) if vpeak_cm_s is not None else None
    pgmean_mmhg = pressure_gradient_mmhg(vmean_cm_s) if vmean_cm_s is not None else None

    return DopplerResults(
        # ... существующие поля ...
        vti_cm=vti_cm,
        vpeak_cm_s=vpeak_cm_s,
        vmean_cm_s=vmean_cm_s,
        pgpeak_mmhg=pgpeak_mmhg,
        pgmean_mmhg=pgmean_mmhg,
    )
```

### 4.6. Отображение в панели Measurements

В `measurement_panel.py` строки 210–214 уже отображают VTI, Vpeak, Vmean, PGpeak, PGmean. Никаких изменений не требуется — они уже есть.

### 4.7. Отображение после завершения трейса

В `viewer_widget.py` `finish_doppler_trace()` (строка 2954) показывает только VTI:

```python
label = self._doppler.last_committed_trace_label()
vti_cm = self._last_committed_vti_cm()
if vti_cm is not None:
    self._measurement_label.setText(f"{label}: {vti_cm:.1f} cm")
```

Оптимизировать показ: после завершения трейса отображать VTI + Vpeak + Vmean + PGpeak + PGmean (если вычислимы).

## 5. Выходной объект

После завершения trace (ручного или авто-) в `DopplerResults` будут заполнены:

```json
{
  "vti_cm": 22.4,
  "vpeak_cm_s": 178.4,
  "vmean_cm_s": 95.2,
  "pgpeak_mmhg": 50.8,
  "pgmean_mmhg": 36.3
}
```

## 6. Рекомендуемые значения по умолчанию

- Vpeak: `max(velocity)` по точкам trace (без порога)
- Vmean: `VTI / duration` (duration = время от первой до последней точки trace)
- PGpeak: `4 × (Vpeak / 100)²`
- PGmean: `4 × (Vmean / 100)²`

## 7. Граничные случаи

| Ситуация | Vpeak | Vmean | PGpeak | PGmean |
|----------|-------|-------|--------|--------|
| Trace с 1 точкой | `None` | `None` | `None` | `None` |
| Trace с одинаковыми точками (flat) | значение | `VTI / duration` | вычислен | вычислен |
| Нет trace, есть только Vmax маркер | из маркера | из ET | вычислен | вычислен |
| Нет trace, нет маркеров | `None` | `None` | `None` | `None` |
| Trace ниже baseline (отрицательные скорости) | `max(abs(v))` | `VTI / duration` | вычислен | вычислен |

Для отрицательных скоростей (регургитация): Vpeak = `max(|v|)` по абсолютным значениям, Vmean = `|VTI| / duration`.

## 8. Тестирование

### Unit-тесты (`tests/unit/test_doppler_metrics.py` или аналогичный):

1. Trace с точками → Vpeak = max velocity, Vmean = VTI / duration
2. Trace + Vmax маркер → Vpeak берётся из маркера (приоритет)
3. Trace + ET интервал → Vmean = VTI / ET
4. Нет trace, нет маркеров → все `None`
5. Отрицательные скорости (регургитация) → Vpeak = max(|v|)
6. PGpeak / PGmean соответствуют Bernoulli от Vpeak / Vmean
7. Существующие тесты для `compute()` не регрессируют

### Интеграционные тесты:

8. Ручной трейс AV → в Measurements появляются VTI + Vpeak + Vmean + PGpeak + PGmean
9. Авто-трейс VTI MV → аналогично
10. После `finish_doppler_trace()` в статусной строке отображаются все метрики

## 9. Приоритеты реализации

| # | Задача | Приоритет |
|---|--------|-----------|
| 1 | Добавить `_find_peak_velocity_from_trace` в `doppler_metrics.py` | Высокий |
| 2 | Добавить `_find_mean_velocity_from_trace` в `doppler_metrics.py` | Высокий |
| 3 | Обновить `compute()` с приоритетом маркер > trace | Высокий |
| 4 | Обновить `finish_doppler_trace()` показ в viewer_widget.py | Средний |
| 5 | Обновить `apply_auto_vti_trace()` для предварительного вычисления | Средний |
| 6 | Добавить unit-тесты | Средний |
| 7 | Обновить `measurement_report_formatter.py` (если нужно) | Низкий |
