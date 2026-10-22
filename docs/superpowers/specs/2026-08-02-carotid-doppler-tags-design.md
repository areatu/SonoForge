# Спек: Авто-калибровка каротидного спектрального допплера из тегов (Samsung RS85)

**Дата:** 2026-08-02
**Статус:** проект
**Связанные файлы:**
- `src/echo_personal_tool/domain/models/doppler_roi.py`
- `src/echo_personal_tool/domain/models/doppler_axis.py`
- `src/echo_personal_tool/domain/services/doppler_calibration.py`
- `src/echo_personal_tool/domain/services/ultrasound_region_physics.py`
- `src/echo_personal_tool/infrastructure/dicom_doppler_calibration.py`
- `src/echo_personal_tool/presentation/viewer_widget.py`
- `tests/unit/test_dicom_doppler_calibration.py`

---

## 1. Контекст

Новые файлы Samsung RS85 (сонные артерии, линейный датчик) записывают **полный набор** тегов спектрального PW-допплера в `SequenceOfUltrasoundRegions` (Region SF=3, DT=3):

| Тег | Значение | Смысл |
|-----|----------|-------|
| `RegionSpatialFormat` | 3 | Spectral |
| `RegionDataType` | 3 | PW Spectral Doppler |
| `PhysicalUnitsXDirection` | 4 | секунды |
| `PhysicalUnitsYDirection` | 7 | cm/s (vendor quirk) |
| `PhysicalDeltaX` | ~0.004167 | с/пиксель |
| `PhysicalDeltaY` | −0.507 … +0.395 | см/с на пиксель, **может быть отрицательным** |
| `ReferencePixelY0` | 239 / 349 / 419 | позиция нулевой линии (**относительно MinY0**) |
| `ReferencePixelX0` | 0 | обычно 0 |
| `ReferencePixelPhysicalValueX/Y` | 0.0 | опорные физические значения |

В отличие от прежних Samsung-файлов (где дельты отсутствовали), здесь есть и дельты, и reference-пиксели. Авто-калибровка должна работать «из коробки» для PSV/EDV/RI.

---

## 2. Диагностика: текущее поведение на этих файлах

Прогон `try_parse_from_path` по 6 файлам каротид:

| Параметр | Текущий результат | Правильно | Статус |
|----------|-------------------|-----------|--------|
| `roi` | (4,554,1139×319) | верно | ✅ |
| `time_span_ms` | 4745.8 | `width·ΔX` | ✅ |
| `time_origin_ms` | **0.0 всегда** | `RefValueX·1000 − RefX0·ΔX_ms` | ❌ теги не читаются |
| `baseline_y_px` | **239** (=RefY0) | **793** (=MinY0+RefY0) | ❌ относительная → абсолютная |
| `velocity_per_pixel_cm_s` | нет поля | ±ΔY со знаком | ❌ знак теряется через `abs()` |
| velocity mapping | ±span/2 симметрично | асимметрично (напр. +121 … −40.6) | ❌ |

**Проверка baseline пикселями** (файл 1): самый тёмный ряд / медиана яркой полосы ≈ 767–793, теговая формула `MinY0+RefY0` = 793 — физически корректна.

---

## 3. Дизайн

### 3.1 Модель: `doppler_roi.py` — `DopplerCalibrationState`

Добавить поле:

```python
velocity_per_pixel_cm_s: float | None = None  # знаковый масштаб скорости, = PhysicalDeltaY
```

- Обновить `has_velocity_scale()` и `has_velocity_scale_from_dicom()` — считать шкалу скорости заданной, если задан `velocity_per_pixel_cm_s` (в дополнение к `velocity_span_cm_s > 0`).
- `velocity_span_cm_s` сохраняется (полный размах = `height·|ΔY|`) — используется в `DopplerWidget` и проверках полноты.

### 3.2 Парсер: `dicom_doppler_calibration.py`

1. **Baseline** — `_extract_samsung_baseline(region)` возвращает `RegionLocationMinY0 + ReferencePixelY0`. Если `ReferencePixelY0` отсутствует — `None`, далее fallback на `detect_baseline_y` / центр ROI (без изменений).
2. **Знаковый ΔY** — читать `region.get("PhysicalDeltaY")` напрямую (без `abs()`), сохранять в `velocity_per_pixel_cm_s`. Для размаха `velocity_span_cm_s` продолжать использовать `abs` (`velocity_span_cm_s_from_region`).
3. **Время** — `time_origin_ms = ReferencePixelPhysicalValueX*1000 − ReferencePixelX0·ΔX_ms`, передавать в `calibration_from_roi_and_baseline` (параметр уже есть, сейчас не передаётся). Если reference-тегов нет — 0.0.
4. **Consistency-проверка** (документ, §4): вычислить `v_top=(roi.y0−baseline)·ΔY`, `v_bot=(roi.y1−baseline)·ΔY`, `full_scale=|v_top−v_bot|`; залогировать `warning`, если вне 10…400 см/с (не блокирует калибровку).
5. Логика выбора региона (`_sorted_doppler_regions`, приоритеты) не меняется — SF=3+DT=3 уже выбирается первым.

### 3.3 Ось: `doppler_calibration.py` + `doppler_axis.py`

`build_axis_mapping(state)`:
- если `state.velocity_per_pixel_cm_s` задан → вычислить скорости на краях ROI: `v_top=(roi.y0−baseline)·per_px`, `v_bot=(roi.y1−baseline)·per_px`; `velocity_min/max` = упорядоченные (`min`,`max`); пробросить `velocity_per_pixel_cm_s` в `DopplerAxisMapping`.
- иначе — текущее симметричное поведение (±span/2).

`DopplerAxisMapping`:
- новое поле `velocity_per_pixel_cm_s: float | None = None`.
- `velocity_cm_s_from_y(y)`: если `velocity_per_pixel_cm_s` задан → `(y − baseline_y_px) · per_px`; иначе текущая формула. Это точная физика `v=(y−baseline)·ΔY`.
- `y_from_velocity_cm_s(v)`: если задан → `baseline_y_px + v/per_px`; иначе текущая формула. Точная инверсия.
- Существующий fallback (без baseline) не трогаем.

### 3.4 Вьювер: `viewer_widget.py`

`apply_doppler_calibration_state` пересобирает `DopplerCalibrationState` (нормализация ROI/clamp baseline) — **сохранять** `velocity_per_pixel_cm_s` (сейчас новые поля теряются: `getattr(..., False)`).

### 3.5 Без изменений

- `ultrasound_region_physics.py` — только при необходимости; `region_physical_deltas` продолжает возвращать `abs`, знак читается напрямую в парсере.
- `DopplerWidget` (standalone, мёртвый код) — работает от `velocity_min/max`; получит корректные min/max из краёв, дополнительных правок не требует.

---

## 4. Тесты

`tests/unit/test_dicom_doppler_calibration.py`:
- Обновить `test_samsung_baseline_from_reference_pixel_y0`: ожидание `baseline == MinY0 + RefY0` (= 230 при MinY0=50, RefY0=180), не 180.
- Новые:
  - `test_negative_delta_y_inverted_spectrum` — ΔY<0, проверить `velocity_per_pixel_cm_s < 0`, `velocity_cm_s_from_y(roi.y0) > 0`.
  - `test_asymmetric_velocity_range` — baseline вне центра, `velocity_min/max` асимметричны.
  - `test_time_origin_from_reference_pixel_x0` — RefX0≠0/RefValueX≠0 → `time_origin_ms` корректен.
  - `test_baseline_relative_to_region_origin` — baseline = MinY0+RefY0, а не голый RefY0.
  - `test_roundtrip_inverse_consistency` — `y_from_velocity_cm_s(velocity_cm_s_from_y(y)) ≈ y` на случайном наборе y.
  - `test_apply_preserves_velocity_per_pixel` (viewer-level при наличии qtbot, иначе domain-level сборка состояния).

Интеграционный (опционально, при наличии `ECHO_TEST_DICOM_DIR` с каротидными файлами):
- `try_parse_from_path` по файлу → `velocity_per_pixel_cm_s` совпадает со знаком/величиной `PhysicalDeltaY` из файла.

---

## 5. Критерии готовности (DoD)

- [ ] `baseline_y_px = MinY0 + ReferencePixelY0`, когда RefY0 есть
- [ ] `time_origin_ms` из `ReferencePixelX0`/`ReferencePixelPhysicalValueX`
- [ ] знак `PhysicalDeltaY` сохранён в `velocity_per_pixel_cm_s`
- [ ] `velocity_cm_s_from_y` / `y_from_velocity_cm_s` — точные инверсии, физически корректны при инверсии спектра
- [ ] `apply_doppler_calibration_state` сохраняет новое поле
- [ ] тесты: обновлённый Samsung-baseline + новые (инверсия, асимметрия, время, round-trip)
- [ ] Прогон всех тестов: `scripts/run_tests.sh` или pytest
- [ ] CHANGELOG_SESSION.md: запись в конце сессии

---

**Конец спеки.**
