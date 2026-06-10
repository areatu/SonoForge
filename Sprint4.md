# Sprint 4 — Domain Calculations & MeasurementPanel

**Фаза:** 1  
**Предшественник:** Sprint 3 (DopplerWidget + MeasurementPanel stub)  
**Статус:** Реализован  
**Scope:** [`Этап2.md`](Этап2.md) S4 — Тей-Хольц, Симпсон, допплер-метрики, панель результатов

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement task-by-task with spec + quality review after each task.

**Goal:** Реализовать domain-расчёты ASE/EACVI Фазы 1 и показывать вычисленные клинические значения в `MeasurementPanel`.

**Architecture:** Чистые функции в `domain/calculations/`; `AppController` оркестрирует пересчёт при изменении контуров, допплер-маркеров и калиперов; `MeasurementSnapshot` агрегирует результаты для UI.

**Tech Stack:** Python 3.10+, NumPy, SciPy (trapz), pytest, PySide6 (только Presentation)

---

## 1. Цель

Заменить stub MeasurementPanel (сырые маркеры S3) на вычисленные параметры:

| Группа | Параметры |
|---|---|
| **Допплер** | E, A, E/A, DT, IVRT, AT, e' sept/lat, E/e', VTI, Vpeak, Vmean, PGpeak, PGmean |
| **Объёмы ЛЖ** | EDV, ESV, LVEF — Симпсон (моно/биплан), Тей-Хольц |
| **Геометрия** | LVEDD, LVESD, IVSd, LVPWd, LVOT (из калиперов) |

---

## 2. Контекст

- S3: `DopplerWidget` → `DopplerMeasurementDTO` → `StateManager.doppler_measurement` → stub panel
- S2: `ViewerWidget` — контуры (`Contour`), `LineROI` калипер (label «Length»)
- Расчёты — **только Domain** (без Qt/pydicom)
- Формулы: Этап3 §8.2, Этап2 §5–6

### Формулы (reference)

**Bernoulli:** `PG_mmHg = 4 × (V_m_s)²`, где `V_m_s = velocity_cm_s / 100`

**Teichholz:** `V_mL = 7 / (2.4 + L_cm) × L_cm³`, L — внутренний размер в cm (LVEDD/LVESD)

**Simpson monoplan:** 20 дисков по длине оси; площадь контура в mm² через `pixel_spacing`

**LVEF:** `(EDV - ESV) / EDV × 100%`

**VTI:** `numpy.trapz(velocities, times)` по точкам трассировки

**Vmean:** `VTI / AT` при наличии интервала AT (с)

---

## 3. Задачи

### Task 1: Domain result models

**Files:**
- Create: `src/echo_personal_tool/domain/models/measurements.py`
- Modify: `src/echo_personal_tool/domain/models/__init__.py`
- Test: `tests/unit/test_measurement_models.py`

Dataclasses:
- `DopplerResults` — optional fields for each computed parameter
- `LvefResult` — edv_ml, esv_ml, lvef_percent, method (str)
- `TeichholzResult` — edv_ml, esv_ml, lvef_percent
- `MeasurementSnapshot` — aggregates DopplerResults, LvefResult, TeichholzResult, linear measurements tuple

### Task 2: bernoulli.py

**Files:**
- Create: `src/echo_personal_tool/domain/calculations/bernoulli.py`
- Create: `src/echo_personal_tool/domain/calculations/__init__.py`
- Test: `tests/unit/test_bernoulli.py`

`pressure_gradient_mmhg(velocity_cm_s: float) -> float`

### Task 3: doppler_metrics.py

**Files:**
- Create: `src/echo_personal_tool/domain/calculations/doppler_metrics.py`
- Test: `tests/unit/test_doppler_metrics.py`

`compute(dto: DopplerMeasurementDTO) -> DopplerResults`:
- Peaks by label: E, A, e_sept, e_lat, Vmax
- E/A, e' average, E/e'
- Intervals: DT, IVRT, AT (duration = end - start, ms → report ms)
- VTI from trace trapz
- PGpeak from Vmax; Vmean from VTI/AT; PGmean from Vmean

### Task 4: teichholz.py

**Files:**
- Create: `src/echo_personal_tool/domain/calculations/teichholz.py`
- Test: `tests/unit/test_teichholz.py`

`volume_ml(lvedd_mm: float) -> float`  
`from_linear_measurements(measurements: tuple[LinearMeasurement, ...]) -> TeichholzResult | None`  
Match labels: LVEDD, LVESD (case-insensitive)

### Task 5: lvef_simpson.py

**Files:**
- Create: `src/echo_personal_tool/domain/calculations/lvef_simpson.py`
- Test: `tests/unit/test_lvef_simpson.py`

`calculate(contours: tuple[Contour, ...], pixel_spacing: tuple[float, float]) -> LvefResult | None`:
- Monoplan: one view with ED + ES contours
- Biplan: A4C + A2C when both views present
- Requires pixel_spacing; return None if missing

### Task 6: StateManager + MeasurementSnapshot

**Files:**
- Modify: `domain/models/viewer_state.py` — add contours, linear_measurements, measurement_snapshot
- Modify: `application/state_manager.py` — setters, clear on new instance
- Test: `tests/unit/test_state_manager.py` (extend)

### Task 7: AppController orchestration

**Files:**
- Modify: `application/app_controller.py`
- Test: `tests/unit/test_measurement_controller.py`

`_recompute_measurements()` calls domain calcs; wired from doppler/contour/linear changes.

### Task 8: ViewerWidget signals + caliper labels

**Files:**
- Modify: `presentation/viewer_widget.py`
- Test: extend `tests/unit/test_contour.py` or new test file

- `contours_changed = Signal(list)` on contour add/clear
- `linear_measurements_changed = Signal(list)` when caliper moves
- Cycle caliper labels: LVEDD → LVESD → IVSd → LVPWd → LVOT → LVEDD (status in measurement label)

### Task 9: MeasurementPanel computed display

**Files:**
- Modify: `presentation/measurement_panel.py`
- Modify: `presentation/main_window.py` (wire snapshot)
- Test: update `tests/unit/test_measurement_panel.py`

Show computed DopplerResults, LvefResult, Teichholz, linear geometry sections.

---

## 4. Критерии приёмки

1. Допплер: E/A, DT, VTI, PGpeak отображаются после расстановки маркеров
2. Контур ED+ES → EDV, ESV, LVEF (Симпсон) при наличии pixel_spacing
3. Калиперы LVEDD+LVESD → Тей-Хольц объёмы и LVEF
4. Смена instance сбрасывает расчёты
5. Все unit-тесты проходят; ruff clean

### Этап E — Верификация

- [x] `uv run pytest` (96 tests)
- [ ] Ручная проверка на Tier 1 DICOM с pixel_spacing и допплер-сериями

---

## 5. Out of scope (S5+)

- Area-Length method
- ONNX / AI contour
- PDF export
- Doppler on MP4/JPEG
