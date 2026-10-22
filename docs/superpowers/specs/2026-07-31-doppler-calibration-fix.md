# Спек: Auto + Manual Doppler Spectrogram Calibration

**Файл:** `docs/superpowers/plans/doppler-calibration-overhaul.md`
**Статус:** `[~]` в реализации
**Дата:** 2026-07-31
**Связанные файлы:**
- `src/echo_personal_tool/infrastructure/dicom_doppler_calibration.py`
- `src/echo_personal_tool/domain/services/ultrasound_region_physics.py`
- `src/echo_personal_tool/domain/services/doppler_calibration.py`
- `src/echo_personal_tool/presentation/viewer_widget.py`
- `src/echo_personal_tool/application/app_controller.py`

---

## 1. Контекст

Doppler-измерения (пики E/A, VTI, интервалы DT/IVRT, градиенты давления) требуют привязки пикселей спектрограммы к физическим осям:
- **Ось X** — время (мс), определяется `RegionPhysicalDeltaX` × `PhysicalUnitsXDirection`
- **Ось Y** — скорость (см/с), определяется `RegionPhysicalDeltaY` × `PhysicalUnitsYDirection`
- **Baseline** — нулевая линия скорости, от которой считается знак

Текущая реализация имеет **три критических бага**, из-за которых авто-калибровка не работает ни на одном вендоре, а ручная калибровка проходит только частично.

---

## 2. Диагностика (аудит 2026-07-31)

### 2.1 Критический баг: опечатки в ключах DICOM

**Файл:** `ultrasound_region_physics.py::region_physical_deltas()`

```python
# ❌ ТЕКУЩЕЕ — пробелы в конце строк ломают ВСЕ вендоры
dx = region.get("PhysicalDeltaX ")       # ← trailing space!
dy = region.get("PhysicalDeltaY ")       # ← trailing space!
ux = region.get("PhysicalUnitsXDirection ")
uy = region.get("PhysicalUnitsYDirection ")
```

**Влияние:** `get()` с пробелом не находит тег → возвращает `None` → `time_span_ms_from_region()` и `velocity_span_cm_s_from_region()` падают → авто-калибровка невозможна даже для вендоров, корректно записывающих теги (GE, Philips, Siemens).

### 2.2 Samsung RS85-RUS: отсутствие дельт

Вывод `debug_doppler_tags.py` на файлах Samsung Medison RS85-RUS:

```
[Region 2] (спектральный)
  RegionSpatialFormat: 3  ✓
  RegionDataType:    3  ✓
  Bounds: X[4..1143], Y[394..873]  ✓
  RegionPhysicalDeltaX:   None  ← ОТСУТСТВУЕТ
  RegionPhysicalDeltaY:   None  ← ОТСУТСТВУЕТ
  PhysicalUnitsXDirection: 4  (ms)
  PhysicalUnitsYDirection: 7  (cm/s — vendor quirk)
  ReferencePixelY0:  239 / 419  ← ЭТО ГОТОВАЯ BASELINE!
```

**Вывод:** Samsung не записывает `PhysicalDeltaX/Y`, но записывает:
- Единицы измерения (`PhysicalUnitsX/YDirection`)
- Позицию baseline (`ReferencePixelY0`) — **vendor-specific тег**, не описанный в DICOM PS3.3
- VelocityScale/VelocityRange на уровне dataset тоже отсутствуют

### 2.3 Отсутствие `time_origin_ms` в конструкторе

**Файл:** `doppler_calibration.py::calibration_from_roi_and_baseline()`

```python
return DopplerCalibrationState(
    roi=roi,
    baseline_y_px=baseline_y_px,
    time_span_ms=time_span_ms,
    velocity_span_cm_s=span,
    kind=kind,
    # ❌ time_origin_ms отсутствует — ломается при default=None
)
```

Хотя `DopplerCalibrationState` имеет `time_origin_ms: float = 0.0`, отсутствие явной передачи затрудняет читаемость и может привести к ошибкам в будущих версиях.

### 2.4 Ручная калибровка Doppler — неполная

**Файл:** `viewer_widget.py::_prompt_spectral_velocity_span()`

Визард собирает 3 из 4 параметров:
- ✅ ROI (2 клика)
- ✅ Baseline (1 клик)
- ✅ Velocity span (prompt + клики по шкале)
- ❌ Time span — всегда дефолт 1000мс, без возможности задать вручную

Для спектрального допплера время развёртки (обычно 2–5 сек) критично для корректного расчёта VTI и интервалов.

---

## 3. План исправлений

### 3.1 Фикс #1: убрать пробелы в ключах DICOM

**Файл:** `ultrasound_region_physics.py`
**Приоритет:** P0 (блокирует авто-калибровку для всех вендоров)

```python
def region_physical_deltas(region: Dataset) -> tuple[float | None, ...]:
    # FIX: убраны trailing spaces
    dx = region.get("PhysicalDeltaX")
    dy = region.get("PhysicalDeltaY")
    ux = region.get("PhysicalUnitsXDirection")
    uy = region.get("PhysicalUnitsYDirection")
    ...
```

**Проверка:** запустить `debug_doppler_tags.py` на файлах GE/Philips/Siemens — должны появиться числовые значения для дельт.

### 3.2 Фикс #2: Samsung fallback — baseline из ReferencePixelY0

**Файл:** `dicom_doppler_calibration.py`
**Приоритет:** P1

Добавить извлечение baseline из Samsung-специфичного тега:

```python
def _extract_samsung_baseline(region: Dataset) -> float | None:
    ref_y = region.get("ReferencePixelY0")
    if ref_y is not None:
        return float(ref_y)
    return None
```

В `try_parse_from_dataset()` — приоритет baseline:
1. `ReferencePixelY0` (Samsung)
2. Auto-detect по яркости (`detect_baseline_y`)
3. Fallback: середина ROI (только если ничего не сработало)

### 3.3 Фикс #3: явная передача `time_origin_ms`

**Файл:** `doppler_calibration.py`
**Приоритет:** P2

```python
def calibration_from_roi_and_baseline(
    roi: DopplerSpectrogramRoi,
    baseline_y_px: float,
    *,
    velocity_span_cm_s: float | None = None,
    time_span_ms: float = 1000.0,
    time_origin_ms: float = 0.0,  # ← явный параметр
    kind: DopplerKind = DopplerKind.SPECTRAL,
) -> DopplerCalibrationState:
    ...
    return DopplerCalibrationState(
        ...
        time_origin_ms=time_origin_ms,
        ...
    )
```

### 3.4 Фикс #4: частичная авто-калибровка (partial calibration)

**Файл:** `viewer_widget.py::_try_auto_detect_doppler_calibration()`
**Приоритет:** P1

Если авто-калибровка извлечёт только часть параметров (например, ROI + baseline, но без velocity/time span), всё равно применить её и предложить пользователю задать недостающее вручную:

```python
def _try_auto_detect_doppler_calibration(self) -> bool:
    ...
    if parsed is not None:
        if parsed.has_time_scale_from_dicom() or parsed.has_velocity_scale_from_dicom():
            self.apply_doppler_calibration_state(parsed, persist=True)
            return True
        elif parsed.is_complete():
            # Partial: ROI+baseline from DICOM, scales need manual input
            self.apply_doppler_calibration_state(parsed, persist=True)
            self.status_message.emit(tr("viewer.doppler_partial_calibration"))
            return True
    return False
```

### 3.5 Фикс #5: ручной ввод time span в UI-визарде

**Файл:** `viewer_widget.py`
**Приоритет:** P2

Добавить 4-й шаг в визард `start_doppler_calibration()`:

| Шаг | Действие | Параметр |
|-----|----------|----------|
| 1 | 2 клика по углам ROI | `roi` |
| 2 | Клик по baseline | `baseline_y_px` |
| 3 | Клик + prompt | `velocity_span_cm_s` |
| **4** | **Prompt** | **`time_span_ms`** |

```python
def _prompt_spectral_time_span(self) -> None:
    span_ms, accepted = QInputDialog.getDouble(
        self,
        tr("viewer.calibration_spectral_time_title"),
        tr("viewer.calibration_spectral_time_prompt"),
        2000.0,  # дефолт 2 сек
        100.0,
        10000.0,
        0,
    )
    if accepted:
        # Rebuild calibration with time_span_ms
        state = calibration_from_roi_and_baseline(
            self._doppler_pending_roi,
            self._doppler_pending_baseline_y,
            velocity_span_cm_s=self._doppler_pending_velocity_span,
            time_span_ms=span_ms,
            kind=self._doppler_cal_kind,
        )
        self.apply_doppler_calibration_state(state)
```

---

## 4. UI-визард: ручной режим Doppler

### 4.1 Последовательность шагов

```
start_doppler_calibration()
    ↓
[ROI step] ← 2 клика (углы спектрограммы)
    ↓
[baseline step] ← 1 клик (нулевая линия)
    ↓
[velocity step] ← клик + prompt (диапазон см/с)
    ↓
[time step] ← prompt (длительность развёртки мс)
    ↓
apply_doppler_calibration_state()
```

### 4.2 Промпты (i18n keys)

```yaml
viewer.doppler.cal_roi1: "Doppler: кликните верхний левый угол спектрограммы"
viewer.doppler.cal_roi2: "Doppler: кликните нижний правый угол спектрограммы"
viewer.doppler.cal_baseline: "Doppler: кликните по нулевой линии скорости"
viewer.doppler.cal_velocity: "Doppler: кликните по верху/низу шкалы скорости"
viewer.calibration_spectral_title: "Калибровка скорости"
viewer.calibration_spectral_prompt: "Полный диапазон скорости (см/с)"
viewer.calibration_spectral_time_title: "Калибровка времени"
viewer.calibration_spectral_time_prompt: "Длительность развёртки (мс)"
viewer.doppler_calibration_complete: "Doppler калибровка завершена"
viewer.doppler_partial_calibration: "Doppler: ROI и baseline из DICOM. Задайте шкалу вручную."
```

### 4.3 Отмена и сброс

- `Esc` — отмена визарда на любом шаге
- Повторный вызов `start_doppler_calibration()` — сброс предыдущего состояния
- При переключении файла — автоматический сброс `_doppler_cal_step = None`

---

## 5. Тест-план

### 5.1 Авто-калибровка (DICOM tags)

| Вендор | Файл | Ожидаемый результат |
|--------|------|---------------------|
| GE | `test_data/ge_spectral.dcm` | `has_time_scale_from_dicom() == True`, `has_velocity_scale_from_dicom() == True` |
| Philips | `test_data/philips_spectral.dcm` | То же |
| Siemens | `test_data/siemens_spectral.dcm` | То же |
| Samsung | `test_data/samsung_rs85.dcm` | `baseline_y_px` из `ReferencePixelY0`, velocity span — ручной ввод |

### 5.2 Ручная калибровка

| Сценарий | Ожидаемый результат |
|----------|---------------------|
| Полный визард (4 шага) | `is_complete() == True`, VTI рассчитывается корректно |
| Отмена на шаге 2 (Esc) | `_doppler_cal_step == None`, графика очищена |
| Переключение файла | Сброс визарда, загрузка новой калибровки |
| Частичная авто (Samsung) | ROI+baseline применены, prompt на velocity span |

### 5.3 Интеграция с расчётами

| Метрика | Проверка |
|---------|----------|
| VTI (см) | `np.trapz(velocities, times)` — время из `time_span_ms`, скорости из `velocity_span_cm_s` |
| Пик E (см/с) | Корректное преобразование пикселей → см/с относительно `baseline_y_px` |
| Интервал DT (мс) | `end_time_ms - start_time_ms` из `time_span_ms` |
| Градиент (мм рт.ст.) | `pressure_gradient_mmhg(vpeak_cm_s)` — Бернулли |

---

## 6. Критерии готовности (Definition of Done)

- [ ] **Фикс #1** применён: авто-калибровка работает на файлах GE/Philips/Siemens
- [ ] **Фикс #2** применён: Samsung baseline извлекается из `ReferencePixelY0`
- [ ] **Фикс #3** применён: `time_origin_ms` передаётся явно
- [ ] **Фикс #4** применён: partial calibration предлагает ручной ввод
- [ ] **Фикс #5** применён: визард имеет 4 шага (ROI, baseline, velocity, time)
- [ ] Добавлены i18n keys для всех промптов
- [ ] Unit-тесты: `test_dicom_doppler_calibration.py` — coverage ≥ 80%
- [ ] Integration-тест: VTI рассчитывается корректно на реальном DICOM
- [ ] Документация обновлена: `README.md` (раздел Doppler), `ROADMAP.md` (добавить строку)
- [ ] CHANGELOG: запись `[feat(doppler)]: auto + manual spectrogram calibration overhaul`

---

## 7. Связанные задачи (backlog)

| Задача | Приоритет | Статус |
|--------|-----------|--------|
| Doppler auto-trace (контур огибающей) | P2 | `[ ]` |
| Автоматические цепочки производных (E/A → E/e' → диастолическая функция) | P2 | `[ ]` |
| CW Doppler калибровка (отдельный `DopplerKind.CW`) | P3 | `[ ]` |
| Tissue Doppler (TDI) калибровка | P3 | `[~]` (есть `DopplerKind.TISSUE`, но не протестировано) |

---

## 8. Риски и митигация

| Риск | Вероятность | Митигация |
|------|-------------|-----------|
| Samsung `ReferencePixelY0` — не baseline, а что-то другое | Средняя | Визуальная проверка: baseline должна быть горизонтальной линией минимальной дисперсии |
| Philips/GE используют нестандартные `PhysicalUnitsYDirection` | Низкая | Расширить whitelist в `velocity_span_cm_s_from_region()` по мере обнаружения |
| Пользователь вводит некорректный velocity span (например, 0) | Средняя | Валидация в `QInputDialog`: min=1.0, max=1000.0 |
| Частичная калибровка применяется, но user не замечает prompt | Средняя | Визуальный баннер на экране (как `_auto_calibration_ok`) |

---

**Конец спеки.**
