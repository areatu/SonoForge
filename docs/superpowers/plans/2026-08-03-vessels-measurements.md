# Секция «Сосуды» (PSV/EDV manual) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить в панель Measures секцию «Сосуды» с ручным измерением PSV/EDV на одном кадре спектрального допплера, мгновенным оверлеем суррогатов (RI, S/D, MV≈) и сохранением нескольких измерений per-instance.

**Architecture:** Подход A. Новая ветка `vessel` внутри существующего `DopplerOverlayTools` (клики + перетаскивание + TextItem-оверлей). Новая аккордеон-секция «Сосуды» в `measures_menu.py`. Чистые domain-функции (`vessel_metrics.py`) и модель (`vessel_measurement.py`). Хранение по паттерну `linear_measurements` в `StudyMeasurementData` → `MeasurementSnapshot.vessel_measurements` → панель/отчёт.

**Tech Stack:** Python 3.11, PySide6, pyqtgraph, pydicom, pytest. Тесты через `.venv/bin/python -m pytest`.

## Global Constraints

- `doppler_baseline.py` уже коммичен (feat line detector) — не менять.
- `DopplerAxisMapping.velocity_cm_s_from_y(y)` и `y_from_velocity_cm_s(v)` — единственный легальный способ перевода y↔скорость.
- Активация кнопок: `is_doppler_velocity_calibrated() and get_doppler_calibration_state().baseline_y_px is not None`. Time-калибровка НЕ требуется.
- Округление: скорости 1 знак, RI/S/D 2 знака — только в форматировании, домен хранит float.
- Коммиты только после прохождения тестов соответствующей задачи. Без пушей.
- Pre-existing failure `test_doppler_axis.py::TestDopplerAxisMappingDefaults::test_poc_default` — не фиксировать.
- GUI-тесты: `pytestmark = pytest.mark.gui`, автофикстура QApplication.

---

### Task 1: Domain — `vessel_metrics` (расчёты RI/S/D/MV)

**Files:**
- Create: `src/echo_personal_tool/domain/calculations/vessel_metrics.py`
- Test: `tests/unit/test_vessel_metrics.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `@dataclass(frozen=True) VesselMetrics` с полями `ri: float | None`, `sd: float | None`, `mv_approx: float | None`, `valid: bool`.
  - `compute_vessel_metrics(psv_cm_s: float, edv_cm_s: float) -> VesselMetrics`.

- [ ] **Step 1: Write the failing test**

```python
"""Tests for vessel_metrics.compute_vessel_metrics."""

from __future__ import annotations

from echo_personal_tool.domain.calculations.vessel_metrics import (
    VesselMetrics,
    compute_vessel_metrics,
)


def test_happy_path() -> None:
    m = compute_vessel_metrics(178.4, 62.1)
    assert m.ri == pytest.approx((178.4 - 62.1) / 178.4)
    assert m.sd == pytest.approx(178.4 / 62.1)
    assert m.mv_approx == pytest.approx((178.4 + 2 * 62.1) / 3)
    assert m.valid is True


def test_psv_leq_edv_marks_invalid() -> None:
    m = compute_vessel_metrics(50.0, 80.0)
    assert m.valid is False
    assert m.ri is None
    assert m.sd is None


def test_edv_zero_omits_ratios() -> None:
    m = compute_vessel_metrics(120.0, 0.0)
    assert m.sd is None
    assert m.ri is None
    assert m.mv_approx == pytest.approx(40.0)


def test_psv_zero_no_ri() -> None:
    m = compute_vessel_metrics(0.0, 10.0)
    assert m.ri is None
```

(файл использует `pytest` — добавьте `import pytest` сверху)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/areatu/ECHO2026 && .venv/bin/python -m pytest tests/unit/test_vessel_metrics.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'echo_personal_tool.domain.calculations.vessel_metrics'`

- [ ] **Step 3: Write minimal implementation**

```python
"""Compute surrogate vessel indices from manual PSV/EDV values."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VesselMetrics:
    ri: float | None
    sd: float | None
    mv_approx: float | None
    valid: bool


def compute_vessel_metrics(psv_cm_s: float, edv_cm_s: float) -> VesselMetrics:
    valid = psv_cm_s > edv_cm_s
    ri = (psv_cm_s - edv_cm_s) / psv_cm_s if psv_cm_s > 0 else None
    sd = psv_cm_s / edv_cm_s if edv_cm_s > 0 else None
    if not valid:
        ri = None
        sd = None
    mv_approx = (psv_cm_s + 2 * edv_cm_s) / 3.0
    return VesselMetrics(ri=ri, sd=sd, mv_approx=mv_approx, valid=valid)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/areatu/ECHO2026 && .venv/bin/python -m pytest tests/unit/test_vessel_metrics.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_vessel_metrics.py src/echo_personal_tool/domain/calculations/vessel_metrics.py
git commit -m "feat: add compute_vessel_metrics (RI/S/D/MV surrogates)"
```

---

### Task 2: Domain — `VesselMeasurement` модель + снапшот

**Files:**
- Create: `src/echo_personal_tool/domain/models/vessel_measurement.py`
- Modify: `src/echo_personal_tool/domain/models/measurements.py:125-130` (добавить поле в `MeasurementSnapshot`)
- Test: `tests/unit/test_vessel_measurement_model.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `@dataclass(frozen=True) VesselMeasurement`: `psv_cm_s: float`, `edv_cm_s: float`, `ri: float | None`, `sd: float | None`, `mv_approx: float`, `sop_instance_uid: str`, `frame_index: int`, `calibration_id: str | None = None`.
  - `MeasurementSnapshot.vessel_measurements: tuple[VesselMeasurement, ...] = ()`.

- [ ] **Step 1: Write the failing test**

```python
"""Tests for VesselMeasurement model and snapshot field."""

from __future__ import annotations

from dataclasses import fields

from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
from echo_personal_tool.domain.models.vessel_measurement import VesselMeasurement


def test_vessel_measurement_fields() -> None:
    m = VesselMeasurement(
        psv_cm_s=178.4,
        edv_cm_s=62.1,
        ri=0.65,
        sd=2.87,
        mv_approx=100.9,
        sop_instance_uid="1.2.3",
        frame_index=5,
    )
    assert m.psv_cm_s == 178.4
    assert m.calibration_id is None


def test_snapshot_has_vessel_measurements_field() -> None:
    field_names = {f.name for f in fields(MeasurementSnapshot)}
    assert "vessel_measurements" in field_names


def test_snapshot_default_empty() -> None:
    assert MeasurementSnapshot().vessel_measurements == ()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/areatu/ECHO2026 && .venv/bin/python -m pytest tests/unit/test_vessel_measurement_model.py -v`
Expected: FAIL (`ModuleNotFoundError` / field missing)

- [ ] **Step 3: Write minimal implementation**

Create `vessel_measurement.py`:
```python
"""Domain model for a manual vessel Doppler measurement (PSV/EDV)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VesselMeasurement:
    psv_cm_s: float
    edv_cm_s: float
    ri: float | None
    sd: float | None
    mv_approx: float
    sop_instance_uid: str
    frame_index: int
    calibration_id: str | None = None
```

Modify `measurements.py` — add import and field:
```python
from echo_personal_tool.domain.models.vessel_measurement import VesselMeasurement
```
```python
    planimeter: tuple[PlanimeterResult, ...] = ()
    vessel_measurements: tuple[VesselMeasurement, ...] = ()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/areatu/ECHO2026 && .venv/bin/python -m pytest tests/unit/test_vessel_measurement_model.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_vessel_measurement_model.py src/echo_personal_tool/domain/models/vessel_measurement.py src/echo_personal_tool/domain/models/measurements.py
git commit -m "feat: add VesselMeasurement model and snapshot field"
```

---

### Task 3: Study session — merge/filter/accept vessel measurements

**Files:**
- Modify: `src/echo_personal_tool/application/study_measurement_session.py` (добавить поле в dataclass, функции merge/filter, методы store)
- Test: `tests/unit/test_study_measurement_session.py`

**Interfaces:**
- Consumes: `VesselMeasurement` (Task 2), `StudyMeasurementData`, `StudyMeasurementSessionStore`.
- Produces:
  - `StudyMeasurementData.vessel_measurements: tuple[VesselMeasurement, ...] = ()`.
  - `merge_vessel_measurements(existing, incoming) -> tuple[VesselMeasurement, ...]`.
  - `vessel_measurements_for_instance(measurements, sop_instance_uid)`.
  - `StudyMeasurementSessionStore.merge_vessel_measurements(study_uid, incoming)`.
  - `reset_measurements` очищает vessel_measurements.

- [ ] **Step 1: Write the failing test**

```python
"""Tests for vessel measurement merge/filter in study session."""

from __future__ import annotations

from echo_personal_tool.application.study_measurement_session import (
    StudyMeasurementSessionStore,
    merge_vessel_measurements,
    vessel_measurements_for_instance,
)
from echo_personal_tool.domain.models.vessel_measurement import VesselMeasurement


def _m(psv: float, uid: str, frame: int) -> VesselMeasurement:
    return VesselMeasurement(
        psv_cm_s=psv,
        edv_cm_s=psv / 2.0,
        ri=0.5,
        sd=2.0,
        mv_approx=psv * 2.0 / 3.0,
        sop_instance_uid=uid,
        frame_index=frame,
    )


def test_merge_replaces_by_instance_and_frame() -> None:
    existing = (_m(100.0, "A", 1), _m(200.0, "A", 2))
    incoming = (_m(150.0, "A", 1),)  # заменяет frame 1, сохраняет frame 2
    result = merge_vessel_measurements(existing, incoming)
    assert len(result) == 2
    by_frame = {m.frame_index: m for m in result}
    assert by_frame[1].psv_cm_s == 150.0
    assert by_frame[2].psv_cm_s == 200.0


def test_merge_empty_clears() -> None:
    existing = (_m(100.0, "A", 1),)
    assert merge_vessel_measurements(existing, ()) == ()


def test_filter_by_instance() -> None:
    measurements = (_m(100.0, "A", 1), _m(120.0, "B", 1))
    assert vessel_measurements_for_instance(measurements, "B") == (measurements[1],)


def test_store_merge_and_reset() -> None:
    store = StudyMeasurementSessionStore()
    store.merge_vessel_measurements("study1", (_m(100.0, "A", 1),))
    data = store.get("study1")
    assert len(data.vessel_measurements) == 1
    store.reset_measurements("study1")
    assert store.get("study1").vessel_measurements == ()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/areatu/ECHO2026 && .venv/bin/python -m pytest tests/unit/test_study_measurement_session.py -v`
Expected: FAIL (import/attribute errors)

- [ ] **Step 3: Write minimal implementation**

В `study_measurement_session.py` добавить импорт и функции (по образцу `merge_linear_measurements`):
```python
from echo_personal_tool.domain.models.vessel_measurement import VesselMeasurement
```

```python
def merge_vessel_measurements(
    existing: tuple[VesselMeasurement, ...],
    incoming: tuple[VesselMeasurement, ...],
) -> tuple[VesselMeasurement, ...]:
    """Replace vessel measurements by instance and frame; clear when incoming is empty."""
    if not incoming:
        return ()
    by_key: dict[tuple[str, int], VesselMeasurement] = {}
    for measurement in existing:
        by_key[(measurement.sop_instance_uid, measurement.frame_index)] = measurement
    for measurement in incoming:
        by_key[(measurement.sop_instance_uid, measurement.frame_index)] = measurement
    return tuple(by_key.values())


def vessel_measurements_for_instance(
    measurements: tuple[VesselMeasurement, ...],
    sop_instance_uid: str,
) -> tuple[VesselMeasurement, ...]:
    """Return only vessel measurements belonging to the given instance."""
    return tuple(m for m in measurements if m.sop_instance_uid == sop_instance_uid)
```

В `StudyMeasurementData` dataclass:
```python
    vessel_measurements: tuple[VesselMeasurement, ...] = ()
```

В `StudyMeasurementSessionStore`:
```python
    def merge_vessel_measurements(
        self,
        study_uid: str,
        incoming: tuple[VesselMeasurement, ...],
    ) -> None:
        data = self.get(study_uid)
        self._studies[study_uid] = replace(
            data,
            vessel_measurements=merge_vessel_measurements(data.vessel_measurements, incoming),
        )
```

В `reset_measurements` — поля vessel уже сброшены т.к. создаётся чистый `StudyMeasurementData(height_cm=..., weight_kg=...)`. Проверить, что нет других полей, которые надо сохранить (в текущем коде только height/weight — ок).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/areatu/ECHO2026 && .venv/bin/python -m pytest tests/unit/test_study_measurement_session.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_study_measurement_session.py src/echo_personal_tool/application/study_measurement_session.py
git commit -m "feat: merge/filter/reset vessel measurements in study session"
```

---

### Task 4: Controller — accept vessel measurement + проброс в снапшот

**Files:**
- Modify: `src/echo_personal_tool/application/app_controller.py` (добавить `accept_vessel_measurement`, проброс в `_build_measurement_snapshot` и `_recompute_measurements`)
- Test: `tests/unit/test_app_controller_vessel.py`

**Interfaces:**
- Consumes: `merge_vessel_measurements`, `vessel_measurements_for_instance` (Task 3), `_build_measurement_snapshot`, `_recompute_measurements`, `_resolve_study_uid`.
- Produces:
  - `AppController.accept_vessel_measurement(measurement: VesselMeasurement) -> bool`.
  - `MeasurementSnapshot.vessel_measurements` заполняется в `_build_measurement_snapshot`.

- [ ] **Step 1: Write the failing test**

```python
"""Tests for AppController.accept_vessel_measurement."""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.models.vessel_measurement import VesselMeasurement


def _make_controller():
    from echo_personal_tool.application.app_controller import AppController

    from tests.unit.conftest import app_controller  # noqa: F401

    controller = AppController()
    return controller


def _m() -> VesselMeasurement:
    return VesselMeasurement(
        psv_cm_s=178.4,
        edv_cm_s=62.1,
        ri=0.65,
        sd=2.87,
        mv_approx=100.9,
        sop_instance_uid="UID",
        frame_index=0,
    )


def test_accept_vessel_measurement_returns_bool():
    controller = _make_controller()
    assert isinstance(controller.accept_vessel_measurement(_m()), bool)


def test_accept_vessel_measurement_rejects_non_vessel():
    controller = _make_controller()
    with pytest.raises(TypeError):
        controller.accept_vessel_measurement("not a vessel measurement")  # type: ignore[arg-type]
```

> Примечание: если `AppController.__init__` требует зависимостей, используйте существующую фикстуру из `tests/unit/conftest.py` — проверьте её при реализации. Если конструктор тяжёлый, вместо создания контроллера тестируйте только ветку валидации через частичный mock.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/areatu/ECHO2026 && .venv/bin/python -m pytest tests/unit/test_app_controller_vessel.py -v`
Expected: FAIL (`AttributeError: 'AppController' object has no attribute 'accept_vessel_measurement'`)

- [ ] **Step 3: Write minimal implementation**

Добавить в `app_controller.py` (рядом с `on_linear_measurements_changed`, ~строка 1139):
```python
    def accept_vessel_measurement(self, measurement: object) -> bool:
        if not isinstance(measurement, VesselMeasurement):
            raise TypeError("Expected a VesselMeasurement")
        study_uid = self._resolve_study_uid()
        self._measurement_session.merge_vessel_measurements(study_uid, (measurement,))
        self._recompute_measurements()
        return True
```

Добавить импорт `VesselMeasurement` и в `_recompute_measurements` — фильтрацию:
```python
        from echo_personal_tool.application.study_measurement_session import (
            linear_measurements_for_instance,
            vessel_measurements_for_instance,
        )

        instance_vessel = vessel_measurements_for_instance(session.vessel_measurements, instance_uid)
```
и передать `vessel_measurements=instance_vessel` в `_build_measurement_snapshot`.

В `_build_measurement_snapshot` — параметр `vessel_measurements: tuple[VesselMeasurement, ...]` (по умолчанию `()`), добавить в `MeasurementSnapshot(...)`:
```python
            vessel_measurements=vessel_measurements,
```

> Внимание: `_build_measurement_snapshot` вызывается из двух мест (`compute_overlay` и `_recompute_measurements`). В обоих прокинуть `vessel_measurements` (в `compute_overlay` — через `vessel_measurements_for_instance`).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/areatu/ECHO2026 && .venv/bin/python -m pytest tests/unit/test_app_controller_vessel.py tests/unit/test_study_measurement_session.py tests/unit/test_measurement_wiring.py -v`
Expected: PASS (без регрессий)

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_app_controller_vessel.py src/echo_personal_tool/application/app_controller.py
git commit -m "feat: accept_vessel_measurement in controller + snapshot wiring"
```

---

### Task 5: Overlay — vessel-режим в DopplerOverlayTools (маркеры + перетаскивание + TextItem)

**Files:**
- Modify: `src/echo_personal_tool/presentation/doppler_overlay.py`
- Test: `tests/unit/test_presentation_doppler_overlay.py` (добавить класс `TestVesselMode`)

**Interfaces:**
- Consumes: `DopplerAxisMapping`, `VesselMetrics`, `compute_vessel_metrics` (Task 1), `_axis_mapping` (time↔velocity↔px).
- Produces:
  - `set_vessel_mode()`, `vessel_status() -> str` (`"psv"` / `"edv"` / `"done"` / `"none"`).
  - `handle_vessel_click(x_px, y_px) -> bool`.
  - `move_vessel_caliper(x_px, y_px)` (drag), `finish_vessel_drag()`.
  - `get_vessel_values() -> tuple[float, float] | None` (psv, edv в cm/s).
  - `get_vessel_metrics() -> VesselMetrics | None`.
  - `clear_vessel()` — убрать маркеры+оверлей, без сигнала.
  - `vessel_changed = Signal(object)` — emits `VesselMetrics | None` после размещения/перетаскивания.

- [ ] **Step 1: Write the failing test**

```python
"""Vessel-mode tests for DopplerOverlayTools (append to existing file)."""

from __future__ import annotations

import pytest


class TestVesselMode:
    def test_set_vessel_mode_and_status(self, overlay, mock_plot):
        overlay.set_axis_mapping(_vessel_mapping())
        overlay.set_vessel_mode()
        assert overlay.vessel_status() == "psv"
        overlay.handle_vessel_click(200.0, 100.0)
        assert overlay.vessel_status() == "edv"
        overlay.handle_vessel_click(300.0, 50.0)
        assert overlay.vessel_status() == "done"
        assert overlay.get_vessel_values() is not None

    def test_vessel_metrics_emitted(self, overlay, mock_plot):
        overlay.set_axis_mapping(_vessel_mapping())
        received = []
        overlay.vessel_changed.connect(received.append)
        overlay.set_vessel_mode()
        overlay.handle_vessel_click(200.0, 100.0)
        overlay.handle_vessel_click(300.0, 50.0)
        assert received and received[-1] is not None

    def test_clear_vessel(self, overlay, mock_plot):
        overlay.set_axis_mapping(_vessel_mapping())
        overlay.set_vessel_mode()
        overlay.handle_vessel_click(200.0, 100.0)
        overlay.handle_vessel_click(300.0, 50.0)
        overlay.clear_vessel()
        assert overlay.vessel_status() == "none"
        assert overlay.get_vessel_values() is None


def _vessel_mapping():
    from echo_personal_tool.domain.models.doppler_axis import DopplerAxisMapping
    from echo_personal_tool.domain.models.doppler_roi import (
        DopplerCalibrationState,
        DopplerSpectrogramRoi,
    )

    roi = DopplerSpectrogramRoi(x0=0.0, y0=0.0, width=1000.0, height=200.0)
    return DopplerAxisMapping(
        roi=roi,
        baseline_y_px=100.0,
        velocity_span_cm_s=200.0,
        velocity_min_cm_s=-100.0,
        velocity_max_cm_s=100.0,
        plot_width=1000.0,
        plot_height=200.0,
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/areatu/ECHO2026 && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/unit/test_presentation_doppler_overlay.py -v`
Expected: FAIL (`AttributeError: 'DopplerOverlayTools' object has no attribute 'set_vessel_mode'`)

- [ ] **Step 3: Write minimal implementation**

В `doppler_overlay.py`:

Импорты:
```python
from echo_personal_tool.domain.calculations.vessel_metrics import (
    VesselMetrics,
    compute_vessel_metrics,
)
```

Добавить в `__init__` после существующих атрибутов:
```python
        self._vessel_mode: str = "none"  # "none" | "psv" | "edv" | "done"
        self._vessel_psv_px: tuple[float, float] | None = None
        self._vessel_edv_px: tuple[float, float] | None = None
        self._vessel_drag_target: str | None = None
        self._vessel_items: list[pg.PlotDataItem] = []
        self._vessel_points: pg.ScatterPlotItem | None = None
        self._vessel_text_item: pg.TextItem | None = None
```

Сигнал на уровне класса:
```python
    vessel_changed = Signal(object)
```

Методы:
```python
    def set_vessel_mode(self) -> None:
        self.set_tool_mode("none")
        self._vessel_mode = "psv"

    def vessel_status(self) -> str:
        return self._vessel_mode

    def get_vessel_values(self) -> tuple[float, float] | None:
        if self._vessel_psv_px is None or self._vessel_edv_px is None:
            return None
        psv = self._axis_mapping.velocity_cm_s_from_y(self._vessel_psv_px[1])
        edv = self._axis_mapping.velocity_cm_s_from_y(self._vessel_edv_px[1])
        return psv, edv

    def get_vessel_metrics(self) -> VesselMetrics | None:
        values = self.get_vessel_values()
        if values is None:
            return None
        psv, edv = values
        return compute_vessel_metrics(psv, edv)

    def handle_vessel_click(self, x_px: float, y_px: float) -> bool:
        if self._vessel_mode not in {"psv", "edv"}:
            return False
        if self._vessel_mode == "psv":
            self._vessel_psv_px = (float(x_px), float(y_px))
            self._vessel_mode = "edv"
        else:
            self._vessel_edv_px = (float(x_px), float(y_px))
            self._vessel_mode = "done"
        self._redraw_vessel_graphics()
        self._emit_vessel_changed()
        return True

    def move_vessel_caliper(self, x_px: float, y_px: float) -> None:
        if self._vessel_drag_target is None:
            return
        if self._vessel_drag_target == "psv" and self._vessel_psv_px is not None:
            self._vessel_psv_px = (float(x_px), float(y_px))
        elif self._vessel_drag_target == "edv" and self._vessel_edv_px is not None:
            self._vessel_edv_px = (float(x_px), float(y_px))
        self._redraw_vessel_graphics()
        self._emit_vessel_changed()

    def finish_vessel_drag(self) -> None:
        self._vessel_drag_target = None

    def begin_vessel_drag(self, x_px: float, y_px: float) -> bool:
        if self._vessel_mode != "done":
            return False
        if self._vessel_psv_px is not None and _near_point(x_px, y_px, self._vessel_psv_px):
            self._vessel_drag_target = "psv"
            return True
        if self._vessel_edv_px is not None and _near_point(x_px, y_px, self._vessel_edv_px):
            self._vessel_drag_target = "edv"
            return True
        return False

    def clear_vessel(self) -> None:
        self._vessel_mode = "none"
        self._vessel_psv_px = None
        self._vessel_edv_px = None
        self._vessel_drag_target = None
        self._redraw_vessel_graphics()

    def _redraw_vessel_graphics(self) -> None:
        for item in self._vessel_items:
            self._plot.removeItem(item)
        self._vessel_items.clear()
        if self._vessel_points is not None:
            self._plot.removeItem(self._vessel_points)
            self._vessel_points = None
        if self._vessel_text_item is not None:
            self._plot.removeItem(self._vessel_text_item)
            self._vessel_text_item = None

        if self._vessel_psv_px is not None:
            self._vessel_items.append(_vertical_line(self._plot, self._vessel_psv_px[0], "#e53935", self._vessel_items))
        if self._vessel_edv_px is not None:
            self._vessel_items.append(_vertical_line(self._plot, self._vessel_edv_px[0], "#43a047", self._vessel_items))

        spots = []
        if self._vessel_psv_px is not None:
            spots.append({"pos": self._vessel_psv_px, "data": "PSV"})
        if self._vessel_edv_px is not None:
            spots.append({"pos": self._vessel_edv_px, "data": "EDV"})
        if spots:
            self._vessel_points = pg.ScatterPlotItem(size=10, pen=pg.mkPen("#ffffff", width=1))
            self._vessel_points.setZValue(25)
            self._vessel_points.setData(spots)
            self._plot.addItem(self._vessel_points)

        metrics = self.get_vessel_metrics()
        if metrics is not None:
            self._vessel_text_item = _build_vessel_text(metrics)

    def _emit_vessel_changed(self) -> None:
        self.vessel_changed.emit(self.get_vessel_metrics())
```

Модульные хелперы (внизу файла):
```python
def _near_point(px: float, py: float, target: tuple[float, float], tol: float = 15.0) -> bool:
    return abs(px - target[0]) <= tol and abs(py - target[1]) <= tol


def _vertical_line(plot, x: float, color: str, registry: list) -> pg.PlotDataItem:
    item = pg.PlotDataItem(
        [x, x],
        [plot.getViewBox().viewRange()[1][0], plot.getViewBox().viewRange()[1][1]]
        if hasattr(plot, "getViewBox")
        else [0.0, 200.0],
        pen=pg.mkPen(color, width=2),
    )
    item.setZValue(22)
    plot.addItem(item)
    registry.append(item)
    return item


def _build_vessel_text(metrics: VesselMetrics) -> pg.TextItem:
    lines = [f"PSV: {metrics.mv_approx if False else ''}"]
    lines = [
        f"PSV: —",
        f"EDV: —",
        f"RI: {metrics.ri:.2f}" if metrics.ri is not None else "RI: —",
        f"S/D: {metrics.sd:.2f}" if metrics.sd is not None else "S/D: —",
        f"MV≈: {metrics.mv_approx:.1f}" if metrics.mv_approx is not None else "MV≈: —",
    ]
    if not metrics.valid:
        lines.append("Проверьте точки")
    text = "\n".join(lines)
    item = pg.TextItem(text, anchor=(1.0, 0.0))
    item.setZValue(30)
    return item
```

> Примечание: значения PSV/EDV в оверлее (1 знак) должны браться из `get_vessel_values()` — чтобы не дублировать, `_build_vessel_text` следует переписать так, чтобы принимать `(psv, edv, metrics)`. В тестах достаточно проверить, что `get_vessel_metrics()` корректен; точный текст оверлея проверяется в Task 6 (integrations). Доработайте сигнатуру `_build_vessel_text(psv: float, edv: float, metrics: VesselMetrics)` при реализации — здесь приведён рабочий минимум.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/areatu/ECHO2026 && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/unit/test_presentation_doppler_overlay.py -v`
Expected: PASS (существующие + новые vessel-тесты)

> Если `mock_plot` не имеет `getViewBox`, `_vertical_line` использует fallback `[0, 200]` — удостоверьтесь, что `_redraw_vessel_graphics` не падает на mock.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_presentation_doppler_overlay.py src/echo_personal_tool/presentation/doppler_overlay.py
git commit -m "feat: vessel mode in DopplerOverlayTools (PSV/EDV markers, drag, overlay)"
```

---

### Task 6: Measures menu — секция «Сосуды» + активация

**Files:**
- Modify: `src/echo_personal_tool/presentation/measures_menu.py` (новая секция `menu.vessels_group`, расширение `_MenuButton` флагом `vessel`, `set_doppler_tool_availability` параметром `vessel_ok`, статус-лейбл)
- Modify: `src/echo_personal_tool/infrastructure/locales/ru.json`, `en.json` (новые ключи)
- Test: `tests/unit/test_measures_menu_vessel.py`

**Interfaces:**
- Consumes: `MeasurementAction` (Task: добавить `VESSEL_PSV`, `VESSEL_EDV`, `VESSEL_CLEAR`, `VESSEL_ACCEPT` в `measurement_action.py`).
- Produces:
  - `MeasuresMenuWidget.set_doppler_tool_availability(*, time_ok: bool, vessel_ok: bool)`.
  - `MeasuresMenuWidget.set_vessel_status(text: str)`.

- [ ] **Step 0 (part of this task): Add enum values**

В `src/echo_personal_tool/presentation/measurement_action.py` добавить:
```python
    VESSEL_PSV = "vessel_psv"
    VESSEL_EDV = "vessel_edv"
    VESSEL_CLEAR = "vessel_clear"
    VESSEL_ACCEPT = "vessel_accept"
```

- [ ] **Step 1: Write the failing test**

```python
"""Tests for vessel section in MeasuresMenuWidget."""

from __future__ import annotations

import pytest

from echo_personal_tool.presentation.measurement_action import MeasurementAction

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def _qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def menu():
    from echo_personal_tool.presentation.measures_menu import MeasuresMenuWidget

    return MeasuresMenuWidget()


def test_vessel_section_has_buttons(menu):
    actions = {spec.action for _, spec in menu._tool_buttons}
    assert MeasurementAction.VESSEL_PSV in actions
    assert MeasurementAction.VESSEL_EDV in actions
    assert MeasurementAction.VESSEL_ACCEPT in actions
    assert MeasurementAction.VESSEL_CLEAR in actions


def test_vessel_buttons_disabled_without_calibration(menu):
    menu.set_doppler_tool_availability(time_ok=False, vessel_ok=False)
    for button, spec in menu._tool_buttons:
        if spec.action in {
            MeasurementAction.VESSEL_PSV,
            MeasurementAction.VESSEL_EDV,
            MeasurementAction.VESSEL_ACCEPT,
            MeasurementAction.VESSEL_CLEAR,
        }:
            assert button.isEnabled() is False


def test_vessel_buttons_enabled_with_calibration(menu):
    menu.set_doppler_tool_availability(time_ok=False, vessel_ok=True)
    for button, spec in menu._tool_buttons:
        if spec.action == MeasurementAction.VESSEL_PSV:
            assert button.isEnabled() is True


def test_set_vessel_status(menu):
    menu.set_vessel_status("Готово")
    assert menu._vessel_status_label.text() == "Готово"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/areatu/ECHO2026 && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/unit/test_measures_menu_vessel.py -v`
Expected: FAIL (нет секции / метода)

- [ ] **Step 3: Write minimal implementation**

В `measures_menu.py`:

Расширить `_MenuButton` полем:
```python
    vessel: bool = False
```

Добавить секцию в `_MENU` (перед `menu.strain_group`):
```python
    (
        "menu.vessels_group",
        (
            _btn("menu.vessel_psv", MeasurementAction.VESSEL_PSV),
            _btn("menu.vessel_edv", MeasurementAction.VESSEL_EDV),
            _btn("menu.vessel_clear", MeasurementAction.VESSEL_CLEAR),
            _btn("menu.vessel_accept", MeasurementAction.VESSEL_ACCEPT),
        ),
    ),
```

В `__init__` добавить статус-лейбл (после `_build_menu()`):
```python
        self._vessel_status_label = QLabel("")
        self._vessel_status_label.setWordWrap(True)
        self._vessel_status_label.setStyleSheet("color: #90caf9; font-size: 12px;")
```

В `_build_menu`, после `layout.addStretch(1)`, добавить статус-лейбл:
```python
        layout.addWidget(self._vessel_status_label)
```

`set_doppler_tool_availability` — заменить сигнатуру и добавить vessel-логику:
```python
    def set_doppler_tool_availability(
        self,
        *,
        time_ok: bool,
        vessel_ok: bool = False,
    ) -> None:
        for button, spec in self._tool_buttons:
            if spec.vessel:
                button.setEnabled(vessel_ok)
                continue
            needs_time = bool(
                spec.doppler_interval
                or spec.doppler_trace
                or spec.action == MeasurementAction.DOPPLER_MITRAL_INFLOW
                or spec.action == MeasurementAction.DOPPLER_TRACE
            )
            if not needs_time:
                continue
            button.setEnabled(time_ok)

    def set_vessel_status(self, text: str) -> None:
        self._vessel_status_label.setText(text)
```

> Важно: `_btn(...)` для vessel-кнопок должен передавать `vessel=True` в `_MenuButton`. В `_MENU` выше этого не сделано — исправьте при реализации: добавьте `vessel=True` в каждый из четырёх `_btn(...)`. `_btn` должен пробрасывать `vessel` в `_MenuButton`.

В locale `ru.json`:
```json
  "menu.vessels_group": "Сосуды",
  "menu.vessel_psv": "PSV",
  "menu.vessel_edv": "EDV",
  "menu.vessel_clear": "Clear",
  "menu.vessel_accept": "Accept"
```
В `en.json`:
```json
  "menu.vessels_group": "Vessels",
  "menu.vessel_psv": "PSV",
  "menu.vessel_edv": "EDV",
  "menu.vessel_clear": "Clear",
  "menu.vessel_accept": "Accept"
```

> `_btn` принимает `**kwargs`? Нет — у него явные параметры. Расширьте `_btn` параметром `vessel: bool = False` и передайте его в `_MenuButton`. Аналогично `_MenuButton` конструктору.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/areatu/ECHO2026 && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/unit/test_measures_menu_vessel.py tests/unit/test_measures_menu_highlight.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_measures_menu_vessel.py src/echo_personal_tool/presentation/measures_menu.py src/echo_personal_tool/presentation/measurement_action.py src/echo_personal_tool/infrastructure/locales/ru.json src/echo_personal_tool/infrastructure/locales/en.json
git commit -m "feat: Vessels section in Measures menu with activation"
```

---

### Task 7: ViewerWidget — routing, hotkeys, активация

**Files:**
- Modify: `src/echo_personal_tool/presentation/viewer_widget.py`
- Test: `tests/unit/test_viewer_vessel.py`

**Interfaces:**
- Consumes: `DopplerOverlayTools` vessel-методы (Task 5), `is_doppler_velocity_calibrated`, `get_doppler_calibration_state`, `_map_view_event`, `keyPressEvent`, `measurement_label`.
- Produces:
  - `start_vessel_psv() -> bool`, `start_vessel_edv() -> bool`, `accept_vessel_measurement() -> bool`, `clear_vessel_measurement() -> bool`.
  - `is_vessel_available() -> bool`.
  - Hotkeys P/E/Enter/Esc в vessel-контексте.
  - Сигнал `vessel_accept_requested = Signal(object)` — emits `VesselMetrics`.

- [ ] **Step 1: Write the failing test**

```python
"""Tests for viewer vessel measurement integration."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.gui


def _viewer():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from echo_personal_tool.presentation.viewer_widget import ViewerWidget

    return ViewerWidget()


def test_is_vessel_available_without_calibration():
    viewer = _viewer()
    assert viewer.is_vessel_available() is False


def test_vessel_mode_requires_frame():
    viewer = _viewer()
    assert viewer.start_vessel_psv() is False
    assert viewer.start_vessel_edv() is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/areatu/ECHO2026 && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/unit/test_viewer_vessel.py -v`
Expected: FAIL (`AttributeError`)

- [ ] **Step 3: Write minimal implementation**

В `viewer_widget.py` добавить сигнал рядом с другими сигналами (~строка 638):
```python
    vessel_accept_requested = Signal(object)
```

Методы (рядом с doppler-калибровкой, ~после `is_doppler_axis_calibrated`):
```python
    def is_vessel_available(self) -> bool:
        if self._current_frame is None:
            return False
        if not self.is_doppler_velocity_calibrated():
            return False
        state = self.get_doppler_calibration_state()
        if state is None or state.baseline_y_px is None:
            return False
        return True

    def start_vessel_psv(self) -> bool:
        if not self.is_vessel_available():
            return False
        self.cancel_active_tool()
        self._doppler.set_vessel_mode()
        self._measurement_label.setText(tr("viewer.vessel_psv_prompt"))
        self._measurement_label.show()
        return True

    def start_vessel_edv(self) -> bool:
        if not self.is_vessel_available():
            return False
        self.cancel_active_tool()
        self._doppler.set_vessel_mode()
        self._doppler.set_vessel_status("edv")
        self._measurement_label.setText(tr("viewer.vessel_edv_prompt"))
        self._measurement_label.show()
        return True
```

> Примечание: `set_vessel_status` — это статус внутри overlay (psv/edv/done/none), а не текст статус-лейбла меню. Для EDV после PSV используем `_doppler.handle_vessel_click` естественным образом: если `start_vessel_edv` нажат повторно после уже установленного PSV — просто остаёмся в `"edv"`. Уточните реализацию: в `set_vessel_mode` выставить `"psv"`, а `start_vessel_edv` вызывает `set_vessel_mode` затем переключает в `"edv"` напрямую. Ниже корректная версия:

```python
    def start_vessel_edv(self) -> bool:
        if not self.is_vessel_available():
            return False
        self.cancel_active_tool()
        self._doppler.set_vessel_mode()  # psv
        self._doppler.handle_vessel_edv_start()  # переключает в "edv", если psv не установлен
        self._measurement_label.setText(tr("viewer.vessel_edv_prompt"))
        self._measurement_label.show()
        return True
```

> Для этого в `doppler_overlay.py` добавьте метод `handle_vessel_edv_start()`:
> ```python
>     def handle_vessel_edv_start(self) -> None:
>         if self._vessel_psv_px is None:
>             self._vessel_mode = "edv"
> ```
> (Если PSV уже поставлен и режим `"done"` — повторный EDV не меняет ничего.)

Приём кликов — в `_handle_doppler_mouse_click`, перед `_doppler.handle_click` (после строки `if self._doppler.get_tool_mode() == "none": return False` добавить branch):
```python
        if self._doppler.get_tool_mode() == "none" and self._doppler.vessel_status() != "none":
            click = self._map_view_event(ev)
            if click is None:
                return False
            return self._doppler.handle_vessel_click(click[0], click[1])
```
> Примечание: `_handle_doppler_mouse_click` вызывает `handle_click` который возвращает False при `_tool_mode == "none"`. Для vessel-режима `_tool_mode` остаётся `"none"`, а работает `_vessel_mode`. Добавьте обработку vessel до общего вызова.

Drag — в `_handle_doppler_trace_drag`/press/release аналогично (vessel begin/move/finish).

Hotkeys в `keyPressEvent` (перед `super().keyPressEvent`):
```python
        if not event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.key() == Qt.Key.Key_P and self.is_vessel_available():
                self.start_vessel_psv()
                event.accept()
                return
            if event.key() == Qt.Key.Key_E and self.is_vessel_available():
                self.start_vessel_edv()
                event.accept()
                return
        if event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            if self._doppler.vessel_status() == "done" and self.is_vessel_available():
                self.accept_vessel_measurement()
                event.accept()
                return
        if event.key() == Qt.Key.Key_Escape:
            if self._doppler.vessel_status() != "none":
                self.clear_vessel_measurement()
                event.accept()
                return
```

Методы Accept/Clear:
```python
    def accept_vessel_measurement(self) -> bool:
        if not self.is_vessel_available():
            return False
        metrics = self._doppler.get_vessel_metrics()
        if metrics is None:
            return False
        values = self._doppler.get_vessel_values()
        if values is None:
            return False
        psv, edv = values
        self.vessel_accept_requested.emit(metrics)
        self._doppler.clear_vessel()
        self._measurement_label.hide()
        return True

    def clear_vessel_measurement(self) -> bool:
        had = self._doppler.vessel_status() != "none"
        self._doppler.clear_vessel()
        self._measurement_label.hide()
        return had
```

> `vessel_accept_requested` emits `VesselMetrics`; main_window подхватит и соберёт `VesselMeasurement` с uid/frame. В Task 8.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/areatu/ECHO2026 && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/unit/test_viewer_vessel.py tests/unit/test_main_window_doppler.py tests/unit/test_presentation_doppler_overlay.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_viewer_vessel.py src/echo_personal_tool/presentation/viewer_widget.py src/echo_personal_tool/presentation/doppler_overlay.py
git commit -m "feat: vessel routing and hotkeys in ViewerWidget"
```

---

### Task 8: MainWindow — wire actions, активация, отчёт и panel

**Files:**
- Modify: `src/echo_personal_tool/presentation/main_window.py`
- Modify: `src/echo_personal_tool/domain/services/measurement_report_formatter.py` (секция «Сосуды»)
- Modify: `src/echo_personal_tool/presentation/measurement_panel.py` (секция «Сосуды»)
- Test: `tests/unit/test_main_window_vessel.py`, `tests/unit/test_measurement_report_vessel.py`

**Interfaces:**
- Consumes: `MeasurementAction.VESSEL_*` (Task 6), viewer vessel-методы (Task 7), `accept_vessel_measurement` (Task 4), `_sync_doppler_tool_availability`, `vessel_measurements_for_instance`, `VesselMeasurement`.
- Produces: полный вертикальный срез: меню → viewer → controller → snapshot → панель/отчёт.

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for vessel section in measurement report."""

from __future__ import annotations

from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
from echo_personal_tool.domain.models.vessel_measurement import VesselMeasurement
from echo_personal_tool.domain.services.measurement_report_formatter import (
    format_measurement_report,
)


def _m() -> VesselMeasurement:
    return VesselMeasurement(
        psv_cm_s=178.4,
        edv_cm_s=62.1,
        ri=0.65,
        sd=2.87,
        mv_approx=100.9,
        sop_instance_uid="A",
        frame_index=1,
    )


def test_report_contains_vessel_section():
    snapshot = MeasurementSnapshot(vessel_measurements=(_m(),))
    report = format_measurement_report(snapshot)
    assert "PSV" in report
    assert "EDV" in report
    assert "RI" in report
    assert "S/D" in report
```

```python
"""Tests for main window vessel wiring."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def _qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def window():
    from echo_personal_tool.presentation.main_window import MainWindow

    return MainWindow()


def test_vessel_actions_have_handlers(window):
    from echo_personal_tool.presentation.measurement_action import MeasurementAction

    for action in (
        MeasurementAction.VESSEL_PSV,
        MeasurementAction.VESSEL_EDV,
        MeasurementAction.VESSEL_CLEAR,
        MeasurementAction.VESSEL_ACCEPT,
    ):
        assert action.value in window._on_measure_action.__globals__  # smoke
```

> Примечание: тест main_window может требовать тяжелого конструктора. Если создание MainWindow падает в CI-окружении, ограничьте тест проверкой того, что `_on_measure_action` обрабатывает vessel-actions (через вызов handler без кадра) — подробности см. в существующем `tests/unit/test_main_window_doppler.py`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/areatu/ECHO2026 && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/unit/test_measurement_report_vessel.py tests/unit/test_main_window_vessel.py -v`
Expected: FAIL (нет vessel-секции в отчёте / нет обработчиков)

- [ ] **Step 3: Write minimal implementation**

**В `measurement_report_formatter.py`** — добавить секцию:
```python
def _format_vessel_section(snapshot: MeasurementSnapshot) -> list[str]:
    measurements = snapshot.vessel_measurements if snapshot is not None else ()
    if not measurements:
        return []
    lines = [tr("domain.report.vessels")]
    for m in measurements:
        lines.append(f"  PSV: {m.psv_cm_s:.1f} cm/s")
        lines.append(f"  EDV: {m.edv_cm_s:.1f} cm/s")
        if m.ri is not None:
            lines.append(f"  RI: {m.ri:.2f}")
        if m.sd is not None:
            lines.append(f"  S/D: {m.sd:.2f}")
        lines.append(f"  MV≈: {m.mv_approx:.1f} cm/s")
    return lines
```
и добавить `_format_vessel_section(report_snapshot)` в кортеж секций в `format_measurement_report`.

Locale (`ru.json` / `en.json`):
```json
  "domain.report.vessels": "Сосуды"
```
```json
  "domain.report.vessels": "Vessels"
```

**В `measurement_panel.py`** — секция в `_refresh_text`:
```python
        vessel_lines = self._format_vessel_section(snapshot)
        if vessel_lines:
            sections.append(vessel_lines)
```
и метод:
```python
    def _format_vessel_section(self, snapshot: MeasurementSnapshot | None) -> list[str]:
        measurements = snapshot.vessel_measurements if snapshot is not None else ()
        if not measurements:
            return []
        lines = [tr("panel.vessels")]
        for m in measurements:
            lines.append(self._line("PSV", m.psv_cm_s, " cm/s"))
            lines.append(self._line("EDV", m.edv_cm_s, " cm/s"))
            if m.ri is not None:
                lines.append(self._line("RI", m.ri, decimals=2))
            if m.sd is not None:
                lines.append(self._line("S/D", m.sd, decimals=2))
            if m.mv_approx is not None:
                lines.append(self._line("MV≈", m.mv_approx, " cm/s"))
        return lines
```
Locale: `"panel.vessels": "Сосуды"` / `"panel.vessels": "Vessels"`.

**В `main_window.py`:**
- В `_on_measure_action` — обработчики:
```python
        if action == MeasurementAction.VESSEL_PSV:
            if self._viewer.start_vessel_psv():
                self._show_status(tr("status.vessel_psv"))
            return
        if action == MeasurementAction.VESSEL_EDV:
            if self._viewer.start_vessel_edv():
                self._show_status(tr("status.vessel_edv"))
            return
        if action == MeasurementAction.VESSEL_CLEAR:
            self._viewer.clear_vessel_measurement()
            return
        if action == MeasurementAction.VESSEL_ACCEPT:
            self._viewer.accept_vessel_measurement()
            return
```
(разместить до `handler = handlers.get(action)`)

- Подключить сигнал `vessel_accept_requested` → собрать `VesselMeasurement`:
```python
        self._viewer.vessel_accept_requested.connect(self._on_vessel_accept_requested)
```
и метод:
```python
    def _on_vessel_accept_requested(self, metrics: object) -> None:
        from echo_personal_tool.domain.calculations.vessel_metrics import VesselMetrics
        from echo_personal_tool.domain.models.vessel_measurement import VesselMeasurement

        if not isinstance(metrics, VesselMetrics):
            return
        values = self._viewer._doppler.get_vessel_values()
        if values is None:
            return
        psv, edv = values
        instance = self._controller.state_manager.snapshot.instance
        if instance is None:
            return
        measurement = VesselMeasurement(
            psv_cm_s=psv,
            edv_cm_s=edv,
            ri=metrics.ri,
            sd=metrics.sd,
            mv_approx=metrics.mv_approx or 0.0,
            sop_instance_uid=instance.sop_instance_uid,
            frame_index=self._viewer._current_frame_index() or 0,
        )
        self._controller.accept_vessel_measurement(measurement)
```
> Примечание: `get_vessel_values()` после `clear_vessel()` в `accept_vessel_measurement` вернёт None. Решение: сохранить psv/edv в сигнале или вызывать `get_vessel_values()` ДО `clear_vessel`. Измените `accept_vessel_measurement` в ViewerWidget, чтобы он emit'ил `(metrics, psv, edv)` кортежем, ИЛИ собрать `VesselMeasurement` внутри ViewerWidget. Рекомендуется: ViewerWidget собирает и emit'ит готовый `VesselMeasurement` (нужен `sop_instance_uid` — доступен через `self._current_instance_uid()`). Тогда `_on_vessel_accept_requested` принимает `VesselMeasurement` напрямую и вызывает `controller.accept_vessel_measurement`. Реализуйте этот вариант.

- Обновить `_sync_doppler_tool_availability`:
```python
    def _sync_doppler_tool_availability(self) -> None:
        self._tool_panel.set_doppler_tool_availability(
            time_ok=self._viewer.is_doppler_time_calibrated(),
            vessel_ok=self._viewer.is_vessel_available(),
        )
```
и в `ToolPanel.set_doppler_tool_availability` / `MeasureTab` — пробросить `vessel_ok`.

- `_restore_doppler_for_current_frame` — добавить восстановление vessel:
```python
    def _restore_vessel_for_current_frame(self) -> None:
        from echo_personal_tool.application.study_measurement_session import (
            vessel_measurements_for_instance,
        )

        instance = self._controller.state_manager.snapshot.instance
        if instance is None:
            return
        frame = self._controller.state_manager.snapshot.current_frame_index
        measurements = vessel_measurements_for_instance(
            self._controller._measurement_session.get(self._resolve_study_uid()).vessel_measurements,
            instance.sop_instance_uid,
        )
        # Найти измерение текущего кадра и показать его маркеры
        for m in measurements:
            if m.frame_index == frame:
                self._viewer._doppler.show_vessel_measurement(m)
                break
```
> Добавьте в `doppler_overlay.py` метод `show_vessel_measurement(m: VesselMeasurement)` — восстанавливает `_vessel_psv_px`/`_vessel_edv_px` из скоростей через `y_from_velocity_cm_s` (в Task 5 не описан — добавьте здесь как зависимость).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/areatu/ECHO2026 && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/unit/test_measurement_report_vessel.py tests/unit/test_main_window_vessel.py tests/unit/test_measurement_panel.py tests/unit/test_measurement_report_formatter.py -v`
Expected: PASS

- [ ] **Step 5: Run full regression**

Run: `cd /home/areatu/ECHO2026 && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/unit -q 2>&1 | tail -20`
Expected: только известный pre-existing failure `test_doppler_axis.py::TestDopplerAxisMappingDefaults::test_poc_default`.

- [ ] **Step 6: Commit**

```bash
git add tests/unit/test_measurement_report_vessel.py tests/unit/test_main_window_vessel.py src/echo_personal_tool/presentation/main_window.py src/echo_personal_tool/domain/services/measurement_report_formatter.py src/echo_personal_tool/presentation/measurement_panel.py src/echo_personal_tool/infrastructure/locales/ru.json src/echo_personal_tool/infrastructure/locales/en.json src/echo_personal_tool/presentation/doppler_overlay.py src/echo_personal_tool/presentation/tool_panel.py
git commit -m "feat: wire Vessels measurements into report, panel, and main window"
```

---

### Task 9: Завершение — CHANGELOG и финальная верификация

**Files:**
- Modify: `CHANGELOG_SESSION.md`

- [ ] **Step 1: Run the full unit suite**

Run: `cd /home/areatu/ECHO2026 && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/unit -q 2>&1 | tail -20`
Expected: все проходят, кроме известного pre-existing `test_poc_default`.

- [ ] **Step 2: Прогнать интеграционные тесты (если есть каталог)**

Run: `cd /home/areatu/ECHO2026 && ls tests/integration 2>/dev/null && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/integration -q 2>&1 | tail -10`
Expected: без новых падений.

- [ ] **Step 3: Записать CHANGELOG_SESSION.md**

Добавить блок в конец:
```markdown
## [2026-08-03] Секция «Сосуды»: ручное измерение PSV/EDV
- **Тип:** feature
- **Файлы:** `src/echo_personal_tool/domain/calculations/vessel_metrics.py`, `src/echo_personal_tool/domain/models/vessel_measurement.py`, `src/echo_personal_tool/application/study_measurement_session.py`, `src/echo_personal_tool/application/app_controller.py`, `src/echo_personal_tool/presentation/doppler_overlay.py`, `src/echo_personal_tool/presentation/measures_menu.py`, `src/echo_personal_tool/presentation/viewer_widget.py`, `src/echo_personal_tool/presentation/main_window.py`, `src/echo_personal_tool/presentation/measurement_panel.py`, `src/echo_personal_tool/domain/services/measurement_report_formatter.py`
- **Суть:** Ручное измерение PSV/EDV на одном кадре спектрального допплера с суррогатами RI/S/D/MV≈, сохранение per-instance по паттерну linear_measurements. Активация только при velocity-калибровке+baseline.
```

- [ ] **Step 4: Commit**

```bash
git add CHANGELOG_SESSION.md
git commit -m "docs: changelog for Vessels section"
```
