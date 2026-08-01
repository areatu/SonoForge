Кратко по фактам с ваших тестовых DICOM (Samsung RS85) и текущего кода.

### Что реально есть в тегах

| Файл | SF | UnitsX | Δx | Интерпретация |
|------|----|--------|-----|----------------|
| 14/15/63 | **2 (M-mode)** | **4 (Hz)** | ≈0.004167 | **ms/px = Δx × 1000 ≈ 4.17** — это sweep speed. Depth из Δy UnitsY=3 (cm) |
| 17/61 | **1 + 1** (B + Color) | 3 | ~0.04 | **Нет SF=3**. Спектральная полоса — pure burned-in. Time/velocity тегов **нет** |

`ReferencePixelY0` на M-mode часто отсутствует/0; на spectral region его тоже нет.
Приватные sweep/speed/PRF теги, которые можно было бы выжать для 17/61 — не нашлись.

**Главная причина «авто не работает» для Doppler:** нет region с `RegionSpatialFormat=3`. Код `try_parse_from_dataset` ищет только spectral regions → возвращает `None` → fallback на слабый `detect_spectrogram_roi` + **silent `time_span_ms=1000`**.

Для M-mode теги уже достаточны, но текущий путь всё ещё может проглатывать partial и не показывать status.

---

### Проблемы текущего UX/кода (подтверждено)

1. **Time scale не first-class** — `calibration_from_roi_and_baseline(..., time_span_ms=1000.0)` и в `try_parse...` fallback 1000. VTI/interval на fake time — клинически опасно.
2. **ROI Doppler** — detector v1 путает M-mode strip (тёмная нижняя полоса) и захватывает side panels; нет confidence, нет исключения SF=2.
3. **Manual** — wizard не заставляет задать time, если его нет; много кликов; нет prefill из partial DICOM/heuristic.
4. **Горизонталь** — физика Hz→ms есть в спеке, но не доведена до guard’ов и partial state.

У вас уже лежат хорошие черновики:
- `docs/superpowers/specs/2026-08-01-doppler-mmode-calibration-overhaul.md`
- `docs/superpowers/plans/2026-08-01-doppler-mmode-calibration-plan.md`

Ниже — **уточнённая и ужесточённая** версия под реальные Samsung-кейсы и вашу жалобу «только амплитуда, не время».

---

## Spec (обновлённый фокус)

### 1. Модель состояния (обязательно)

```text
DopplerCalibrationState:
  roi
  baseline_y_px
  time_span_ms: float | 0          # 0 = unknown, NEVER default 1000
  velocity_span_cm_s: float | 0
  time_source: "dicom_region" | "manual" | "heuristic" | "none"
  velocity_source: ...
  roi_source: ...
  from_dicom_tags: bool
  time_from_dicom_tags: bool
  velocity_from_dicom_tags: bool

  has_time_scale() → time_span_ms > 0
  has_velocity_scale() → velocity_span_cm_s > 0
  is_complete() → has_time + has_velocity + valid roi
  is_partial() → roi ok + (time XOR velocity)
```

**Жёсткое правило:** `build_axis_mapping` / VTI / DT / any time-based calc **refuse**, если `not has_time_scale()`. UI: disabled + tooltip «задайте калибровку времени».

### 2. Physics (выжать Hz/cm)

```text
horizontal_ms_per_pixel(delta_x, units_x):
  units_x == 4 (Hz)  → delta_x * 1000.0     # Samsung M-mode / некоторые spectral
  units_x == 3 (sec) → delta_x * 1000.0
  иначе → None

time_span_ms = width_px * ms_per_px   # только если region is_mmode OR is_spectral
```

**Никогда** не брать Δx из SF=1 (B-mode/Color) для spectrogram time — это spatial mis-tag.

Depth/velocity аналогично только из правильного region kind.

### 3. Auto pipeline (порядок)

```
1. try_parse_from_dataset → partial OK (time и/или velocity)
2. если spectral region отсутствует:
   detect_spectrogram_roi_v2(frame)  # exclude SF=2, texture classifier
3. apply partial state
4. prompt ТОЛЬКО missing оси (velocity или time)
5. никогда не ставить complete с fake 1000 ms
```

### 4. ROI v2 (критично)

- Если в dataset есть SF=2 → **исключить** его bounds из Doppler search.
- Texture: M-mode = высокая горизонтальная корреляция строк; Doppler = вертикальные всплески, низкая row-corr.
- Side margins: left ~12 %, right ~8 % (текст/шкала), если content не выходит.
- Aspect width/height ∈ [1.5, 6].
- Confidence score; UI показывает ROI только при confidence > threshold.
- Baseline: `ReferencePixelY0` только если `roi.y0 ≤ y ≤ roi.y1` и не «0 при ROI.y0 > 10».

### 5. Manual UX (быстро)

- Prefill ROI из heuristic/DICOM → пользователь только корректирует.
- Wizard: ROI → baseline → **velocity** → **time** (time всегда, если `time_span==0`).
- 2-point time: клик двух точек + ввод известного интервала (сек или ms) **или** выбор preset (1/2/3/4/5 s) + drag horizontal line.
- Аналогично velocity: drag vertical на известную скорость (100/150/200 cm/s presets).
- Цель: при prefilled ROI ≤ 2 действия до complete.

### 6. Acceptance (ваши файлы)

| ID | Файл | Ожидание |
|----|------|----------|
| T1 | 14/63 M-mode | auto: ms/px ≈ 4.17, depth ≈ UI scale (±5 %), banner виден |
| T2 | 17/61 PW/CW | heuristic ROI IoU > 0.7 vs manual gold; **partial**; prompts только missing; **нет** complete с 1000 ms |
| T3 | Manual Doppler | time step всегда присутствует |
| T4 | VTI | None/disabled без time scale |
| T5 | Synthetic SF=3 | full auto from tags |

---

## Plan (порядок внедрения, ~2–3 дня)

**Phase A — Time first-class (P0, ~4 h)**
Убрать silent 1000. `time_span_ms` default 0. Refuse VTI/axis без time. 4-й шаг wizard + i18n.

**Phase B — Выжать time/depth из regions (P0, ~3 h)**
`horizontal_ms_per_pixel` только M-mode/spectral. Partial parse. M-mode banner (mm/px + ms/px). Regression на 14/63.

**Phase C — Samsung spectral без SF=3 (P0, ~5 h)**
`detect_spectrogram_roi_v2` + texture + SF=2 exclude. Partial apply → prompt missing only. Не брать B-mode Δx.

**Phase D — Manual UX (P1, ~4 h)**
Prefill, presets time/velocity, 2-point, ≤2 actions. Status source (DICOM/manual/heuristic).

**Phase E — Tests + docs**
Матрица выше + CHANGELOG.

Порядок: **A → B → C**. Не делать C до A, иначе heuristic снова проставит 1000 ms.

---

### Риски и митигации

| Риск | Митигация |
|------|-----------|
| Heuristic ROI = M-mode strip | SF=2 exclude + texture classifier |
| Samsung RefY0=0 | guard outside ROI / ==0 with y0>10 |
| User игнорирует time prompt | VTI/interval disabled |
| GE/Philips regression | SF=3 path first; тесты на gold когда появятся |

---

### Out of scope сейчас

- OCR burned-in «cm/s» / time labels (P2, полезно именно для 17/61)
- CW vs PW из private PRF
- Live re-cal на multi-frame spectral

---

Существующие файлы в `docs/superpowers/` уже близки к этому. Рекомендую **перезаписать** их уточнённой версией выше (особенно: жёсткий отказ от 1000 ms, partial state, ROI v2, acceptance на 17/61).

Могу сразу:
1. Обновить оба md-файла в artifacts под эту спецификацию,
2. Набросать конкретные diff’ы по `dicom_doppler_calibration.py` / `doppler_calibration.py` / detector,
3. Или сначала разобрать конкретный failing path в `viewer_widget` / `_try_auto_detect...`.

Что делаем дальше?
