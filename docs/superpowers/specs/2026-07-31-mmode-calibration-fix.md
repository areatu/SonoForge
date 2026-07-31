# Спек: Auto + Manual M-Mode Calibration Fix

**Статус:** `[ ]` (не начато)
**Дата:** 2026-07-31
**Связанные файлы:**
- `src/echo_personal_tool/domain/models/frame_panels.py` (`MmodeCalibrationState`)
- `src/echo_personal_tool/domain/services/mmode_calibration.py` (`mmode_state_from_panel`)
- `src/echo_personal_tool/presentation/viewer_widget.py` (`try_apply_mmode_from_dicom_or_heuristic`, `start_mmode_panel_calibration`, manual wizard)

---

## 1. Контекст

M-mode измерения (IVSd, LVIDd, LVPWd, TAPSE, RWT, Teichholz volumes) требуют привязки пикселей к физическим осям:
- **Ось Y** (depth): mm/px — линейные размеры камер
- **Ось X** (time): ms/px — HR, время сокращения, DT-подобные интервалы

Текущая реализация **молча** отбрасывает всю калибровку, если `PhysicalDeltaY` отсутствует в DICOM-регионе, хотя ROI и time scale могут быть доступны. Ручной визард также неполон — нет шага time.

---

## 2. Диагностика (аудит 2026-07-31)

### 2.1 Критический баг: `mmode_state_from_panel` требует depth

**Файл:** `mmode_calibration.py`

```python
def mmode_state_from_panel(panel: UltrasoundPanel) -> MmodeCalibrationState | None:
    vertical_mm = panel.vertical_mm_per_pixel
    if vertical_mm is None or vertical_mm <= 0.0:
        return None   # ← ROI + time scale теряются целиком
```

Если Samsung / часть GE / secondary capture **не пишут `PhysicalDeltaY`**, автокалибровка не применяется, хотя:
- ROI (`RegionLocation*`) есть;
- time scale (`PhysicalDeltaX` + units sec/Hz) часто есть.

### 2.2 `MmodeCalibrationState` требует обязательный depth

**Файл:** `frame_panels.py`

```python
@dataclass(frozen=True)
class MmodeCalibrationState:
    roi: DopplerSpectrogramRoi
    vertical_mm_per_pixel: float          # ← не Optional
    horizontal_ms_per_pixel: float | None = None
```

Тип `float` не позволяет хранить `None` → partial state невозможен.

### 2.3 Ручной визард — только ROI + depth, нет time

**Файл:** `viewer_widget.py`

После 2 кликов ROI → `_calibration_kind = "mmode_depth"` → prompt depth → `MmodeCalibrationState(roi, vertical_mm_per_pixel=...)` → **apply**. Нет перехода к `_calibration_kind = "mmode_time"`.

`_prompt_mmode_time_span` существует, но вызывается только при `calibration_kind == "mmode_time"`, в который визард **никогда не переходит**.

### 2.4 `_prompt_mmode_time_span` не создаёт полный state

**Файл:** `viewer_widget.py`

```python
def _prompt_mmode_time_span(self, length_px: float) -> None:
    ...
    time_per_pixel_ms = span_ms / length_px
    self.mmode_time_calibration_completed.emit(float(time_per_pixel_ms))
    # ← emit信号, но НЕ создаёт MmodeCalibrationState с ROI + depth
```

### 2.5 Heuristic panels без физики

**Файл:** `frame_panel_parser.py`

```python
UltrasoundPanel(kind=PanelKind.M_MODE, bounds=lower)  # deltas = None
```

Даёт ROI, но `mmode_state_from_panel` снова возвращает `None`.

### 2.6 Vendor quirks

В `ultrasound_region_physics.py` quirks работают, только если дельты **присутствуют**. Samsung часто пишет units без deltas.

---

## 3. Медицинский смысл осей

| Ось | Физика | Клиника |
|-----|--------|---------|
| **Y (depth)** | mm/px | IVSd, LVIDd, LVPWd, TAPSE, RWT, Teichholz volumes |
| **X (time)** | ms/px | HR из M-mode, время сокращения, DT-подобные интервалы |

Ошибка depth 10% → ошибка LVEF Teichholz ~15–20%.

---

## 4. План исправлений

### Fix M1: Partial `MmodeCalibrationState` (P0)

**Файл:** `frame_panels.py`

```python
@dataclass(frozen=True)
class MmodeCalibrationState:
    roi: DopplerSpectrogramRoi
    vertical_mm_per_pixel: float | None = None    # ← Optional
    horizontal_ms_per_pixel: float | None = None
    from_dicom_tags: bool = False

    def is_complete(self) -> bool:
        return (
            self.roi.width > 0
            and self.roi.height > 0
            and self.vertical_mm_per_pixel is not None
            and self.vertical_mm_per_pixel > 0.0
        )

    def has_depth_from_dicom(self) -> bool:
        return self.from_dicom_tags and self.vertical_mm_per_pixel is not None

    def has_time_from_dicom(self) -> bool:
        return self.from_dicom_tags and self.horizontal_ms_per_pixel is not None
```

### Fix M2: Не отбрасывать panel без depth (P0)

**Файл:** `mmode_calibration.py`

```python
def mmode_state_from_panel(panel: UltrasoundPanel) -> MmodeCalibrationState | None:
    if panel.kind is not PanelKind.M_MODE:
        return None
    # ROI всегда; scales — если есть
    return MmodeCalibrationState(
        roi=panel.bounds,
        vertical_mm_per_pixel=panel.vertical_mm_per_pixel,   # may be None
        horizontal_ms_per_pixel=panel.horizontal_ms_per_pixel,
        from_dicom_tags=True,
    )
```

### Fix M3: Dataset fallback — time из `FrameTime`/`CineRate` (P1)

**Файл:** `mmode_calibration.py` (новый helper)

```python
def horizontal_ms_from_dataset(ds: Dataset, roi_width_px: float) -> float | None:
    ft = ds.get("FrameTime")
    if ft is not None and float(ft) > 0 and roi_width_px > 0:
        return float(ft)
    rate = ds.get("CineRate") or ds.get("RecommendedDisplayFrameRate")
    if rate is not None and float(rate) > 0:
        return 1000.0 / float(rate)
    return None
```

### Fix M5: Ручной визард 3 шага: ROI → depth → time (P1)

**Файл:** `viewer_widget.py`

После `_prompt_mmode_depth_calibration`:
1. **Не** сбрасывать `_mmode_pending_roi`
2. **Не** вызывать `apply_mmode_calibration_state` сразу
3. Ставить `_calibration_kind = "mmode_time"` и продолжать
4. В `_prompt_mmode_time_span` — собирать полный `MmodeCalibrationState(roi, depth, time)`

### Fix M6: Partial auto → UI prompt (P1)

**Файл:** `viewer_widget.py`

```python
def try_apply_mmode_from_dicom_or_heuristic(self) -> bool:
    ...
    state = mmode_state_from_panel(m_panel)
    if state is None:
        return False
    self.apply_mmode_calibration_state(state)
    if not state.is_complete():
        # ROI применён; depth/time нет → предложить ручной ввод
        if state.vertical_mm_per_pixel is None:
            self._start_mmode_depth_only()
        elif state.horizontal_ms_per_pixel is None:
            self._start_mmode_time_only()
    return True
```

---

## 5. UI-визард: ручной режим M-mode

### 5.1 Последовательность шагов

```
start_mmode_panel_calibration()
    ↓
[ROI step] ← 2 клика (углы полосы)
    ↓
[depth step] ← 2 клика по шкале + prompt (см)
    ↓
[time step] ← 2 клика по горизонтали + prompt (мс)
    ↓
apply_mmode_calibration_state(full)
```

### 5.2 Промпты (i18n keys)

```yaml
viewer.mmode_cal1: "M-mode: кликните угол полосы M-режима"
viewer.mmode_cal2: "M-mode: кликните противоположный угол полосы"
viewer.mmode_cal_depth: "M-mode: кликните верх шкалы глубины"
viewer.mmode_cal_depth_prompt: "Известная глубина (см)"
viewer.mmode_cal_time: "M-mode: кликните начало интервала по времени"
viewer.mmode_cal_time_prompt: "Длительность интервала (мс)"
viewer.mmode_calibration_complete: "M-mode калибровка завершена"
viewer.mmode_partial_calibration: "M-mode: ROI из DICOM. Задайте depth/time вручную."
```

### 5.3 Отмена и сброс

- `Esc` — отмена визарда на любом шаге
- Повторный вызов `start_mmode_panel_calibration()` — сброс
- При переключении файла — автоматический сброс

---

## 6. Тест-план

| Сценарий | Ожидание |
|----------|----------|
| M-mode с полными `PhysicalDelta*` | `is_complete() == True`, depth + time |
| M-mode без `PhysicalDeltaY`, с `FrameTime` | partial ROI + time; depth manual |
| Secondary capture без regions | heuristic ROI; оба scale manual |
| Ручной визард 3 шага | `is_complete() == True`, calipers в mm/ms |
| Teichholz chain (IVS–LVID–PW) | мм из `vertical_mm_per_pixel` |
| Переключение файла | reset state, re-parse |

---

## 7. Критерии готовности (Definition of Done)

- [x] **M1** применён: `MmodeCalibrationState` с `vertical_mm_per_pixel: float | None`
- [x] **M2** применён: `mmode_state_from_panel` возвращает partial state без depth
- [x] **M5** применён: ручной визард 3 шага (ROI → depth → time)
- [x] **M3** применён: `FrameTime`/`CineRate` fallback для time
- [x] **M4** применён: B-mode `vertical_mm_per_pixel` как proxy для depth
- [x] **M6** применён: partial auto UI prompt
- [ ] i18n keys для всех промптов
- [ ] Unit-тесты: `test_mmode_calibration.py` — coverage ≥ 80%
- [ ] Integration-тест: Teichholz chain рассчитывается корректно
- [ ] CHANGELOG: запись `[fix(mmode)]: partial calibration + 3-step manual wizard`

---

## 8. Связь со спеками

- `docs/superpowers/specs/2026-07-31-doppler-calibration-fix.md` — симметричная спека для Doppler
- `docs/superpowers/specs/2026-07-15-anatomical-mmode-design.md` — anatomical M-mode (scan line на 2D); калибровка depth/time там через `FrameTime` / pixel spacing 2D, не через M-region

---

## 9. Риски и митигация

| Риск | Вероятность | Митигация |
|------|-------------|-----------|
| `FrameTime` ≠ ms/px для native M-mode strip (ms на sweep) | Средняя | Проверка на реальных файлах GE/Philips/Samsung |
| Partial state ломает downstream-расчёты | Низкая | `is_complete()` guard + unit-тесты |
| Пользователь не замечает partial calibration prompt | Средняя | Визуальный баннер на экране |

---

**Конец спеки.**
