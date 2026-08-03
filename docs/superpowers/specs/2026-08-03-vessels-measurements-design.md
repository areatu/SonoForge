**Design: Секция «Сосуды» — ручное измерение PSV / EDV на одном кадре**

## 1. Цель

Реализовать в секции «Сосуды» панели Measurements ручное измерение PSV и EDV на одном кадре спектрального допплера с мгновенным оверлеем суррогатных показателей (RI, S/D, MV≈), вычисляемых только из этих двух значений.

## 2. Область / вне области

**В области:**
- PSV/EDV calipers на спектре (клик + перетаскивание).
- Оверлей результатов поверх спектра, обновление в реальном времени.
- Секция «Сосуды» в MeasuresMenuWidget (measures_menu.py).
- Сохранение нескольких измерений per-instance в StudyMeasurementData → MeasurementSnapshot.
- Горячие клавиши P / E / Enter / Esc.
- Кнопки disabled без velocity-калибровки и baseline.

**Вне области (YAGNI):**
- Усреднение по циклам, выбор артерии/стороны/сегмента.
- ICA/CCA ratios, St. Mary's и прочие artery-specific показатели.
- Snap-to-envelope.
- Time-калибровка не требуется для активации.

## 3. Архитектура

Следуем Подходу A: новая ветка внутри существующего `DopplerOverlayTools` + новая секция «Сосуды» в `MeasuresMenuWidget` (measures_menu.py) + чистые domain-функции. Примечание: изначально дизайн предполагал `MeasurementToolsPanel`, но эта панель не подключена в UI — активной является `MeasuresMenuWidget`; решение пользователя от 2026-08-03: добавлять секцию туда.

```
[MeasuresMenuWidget]                    "Сосуды": PSV / EDV / Clear / Accept + статус
        │  сигналы
        ▼
[ViewerWidget]  routing кликов, hotkeys, активация кнопок
        │  markers_changed
        ▼
[DopplerOverlayTools]  tool-mode "vessel": 2 маркера + перетаскивание + TextItem-оверлей
        │
        ▼
[app_controller / state_manager]  Accept → session.add_vessel_measurement → snapshot
        ▼
[MeasurementSnapshot.vessel_measurements]  → measurement_panel / measurement_worksheet
```

### 3.1 Domain

**Новый файл `domain/calculations/vessel_metrics.py`:**
- `@dataclass(frozen=True) VesselMetrics: ri, sd, mv_approx` (поля `float | None`).
- `compute_vessel_metrics(psv_cm_s: float, edv_cm_s: float) -> VesselMetrics`:
  - `ri = (psv - edv) / psv` при psv > 0, иначе None.
  - `sd = psv / edv` при edv > 0, иначе None.
  - `mv_approx = (psv + 2*edv) / 3`.
  - Проверки: psv ≤ edv → psv/edv флагируются через отдельный булев флаг `valid` (см. §5); edv ≤ 0 → sd и ri = None.
  - Округление: скорости 1 знак, RI/S/D 2 знака — на уровне форматирования в оверлее/панели, не в домене.

**Новый файл `domain/models/vessel_measurement.py`:**
- `@dataclass(frozen=True) VesselMeasurement`:
  - `psv_cm_s: float`, `edv_cm_s: float`
  - `ri: float | None`, `sd: float | None`, `mv_approx: float`
  - `sop_instance_uid: str`
  - `frame_index: int`
  - `calibration_id: str | None = None`

**`domain/models/measurements.py`:**
- `MeasurementSnapshot.vessel_measurements: tuple[VesselMeasurement, ...] = ()`.

### 3.2 Study session (паттерн linear_measurements)

**`application/study_measurement_session.py`:**
- `StudyMeasurementData.vessel_measurements: tuple[VesselMeasurement, ...] = ()`.
- `merge_vessel_measurements(existing, incoming) -> tuple[...]`: замена по ключу `(sop_instance_uid, frame_index)`; очистка при пустом incoming (как `merge_linear_measurements`).
- `vessel_measurements_for_instance(measurements, sop_instance_uid)`.
- `StudyMeasurementSessionStore.merge_vessel_measurements(study_uid, incoming)`.
- `reset_measurements` также очищает vessel_measurements.

**`application/app_controller.py`:**
- В `_build_measurement_snapshot` — проброс `vessel_measurements` в `MeasurementSnapshot`.
- В `_recompute_measurements` — фильтрация `vessel_measurements_for_instance`.
- Новый метод `accept_vessel_measurement(...)` → merge в session → `_recompute_measurements()`.

### 3.3 Presentation

**`presentation/doppler_overlay.py` (DopplerOverlayTools):**
- Новый tool-mode `"vessel"`.
- Клик по спектру → ставит PSV (1-й) / EDV (2-й) маркер: вертикальная линия + точка на линии baseline или на скорости клика.
- Два `pg.PlotDataItem` (вертикальные линии PSV/EDV) + `pg.ScatterPlotItem` (точки).
- После двух точек — `markers_changed.emit(VesselCaliperDTO)`.
- Перетаскивание: обработка движения мыши в vessel-режиме (X — позиция на спектре, скорость = `velocity_cm_s_from_y(y)`), на лету перерисовка + обновление оверлея.
- Оверлей результатов: `pg.TextItem` с полупрозрачным фоном в углу спектра; текст: PSV/EDV (1 знак), RI/S/D (2 знака), MV≈ (1 знак); строка предупреждения если psv ≤ edv; скрытие строк если edv ≤ 0.
- `clear_vessel()` — убирает маркеры и оверлей (без сигнала, как `clear_measurements`).
- `load_vessel_from_measurement(m)` / `set_axis_mapping` — восстановление calipers при редактировании.

**`presentation/measures_menu.py` (MeasuresMenuWidget):**
- Новая секция-аккордеон «Сосуды» (`menu.vessels_group`) в `_MENU`.
- Кнопки: PSV → `MeasurementAction.VESSEL_PSV`, EDV → `MeasurementAction.VESSEL_EDV`, Clear → `MeasurementAction.VESSEL_CLEAR`, Accept → `MeasurementAction.VESSEL_ACCEPT`.
- `_MenuButton` расширяется флагом `vessel: bool`; `set_doppler_tool_availability` дополняется параметром `vessel_ok` (velocity-калибровка + baseline) — enabled только для vessel-кнопок.
- Статус-лейбл «Ожидание PSV / Ожидание EDV / Готово» — QLabel, обновляемый через новый метод `set_vessel_status(str)`.

**`presentation/viewer_widget.py`:**
- Маршрутизация vessel-режима в `DopplerOverlayTools` (клики уже через `_handle_doppler_calibration_click`-подобный хук; добавить `_handle_vessel_click`).
- Активация: кнопки enabled когда `is_doppler_velocity_calibrated() and get_doppler_calibration_state().baseline_y_px is not None` и текущий кадр — спектральный допплер.
- Hotkeys: P → PSV, E → EDV, Enter → Accept, Esc → Clear (в существующем keyPressEvent).
- Accept: собрать `VesselMeasurement`, вызвать `controller.accept_vessel_measurement(...)`.
- Восстановление при редактировании: по `sop_instance_uid`+`frame_index` вернуть кадр и загрузить calipers.

**`presentation/measurement_panel.py` + `measurement_worksheet.py`:**
- Новая секция «Сосуды»: строки PSV, EDV, RI, S/D, MV≈ (первое/последнее измерение текущего инстанса или все — решает §6).
- Worksheet: строка-действие «Vessel Doppler (manual)» → возврат к calipers.

## 4. Данные / поток

```
PSV-кнопка → tool_mode="vessel", шаг "psv" → клик → маркер PSV
EDV-кнопка → шаг "edv" → клик → маркер EDV → оверлей + markers_changed
Перетаскивание → перерисовка + оверлей (live)
Clear → удалить маркеры/оверлей (без сигнала)
Accept → VesselMeasurement в session → _recompute → snapshot → панель/worksheet
```

Хранимое представление (Accept):
```json
{
  "type": "vessel_doppler_manual",
  "sop_instance_uid": "...",
  "frame_index": 12,
  "psv_cm_s": 178.4,
  "edv_cm_s": 62.1,
  "ri": 0.65,
  "sd": 2.87,
  "mv_approx": 100.9,
  "calibration_id": "..."
}
```

## 5. Обработка ошибок

- `psv ≤ edv` → флаг `valid=False`; оверлей показывает «Проверьте точки»; Accept всё равно допустим (значения сохраняются, но помечены).
- `edv ≤ 0` → `sd=None`, `ri=None`; оверлей скрывает эти строки.
- Клики вне спектра/без velocity-калибровки — игнорируются (кнопки disabled).
- Esc в vessel-режиме прерывает активный ввод (не трогает принятые измерения).
- Смена кадра/инстанса в незавершённом состоянии → сброс активных calipers.

## 6. Открытые вопросы

1. Отображение в `measurement_panel`: показывать только последнее измерение инстанса или все? — **По умолчанию: все, в порядке ввода.**
2. `calibration_id`: сейчас нет явного id калибровки; пока генерировать `str` от `sop_instance_uid+frame_index` или `None`. — **По умолчанию: None (поле есть, заполняется позже).**
3. Валидация `psv ≤ edv`: блокировать Accept или разрешать с предупреждением? — **Разрешать с предупреждением** (спека допускает).

## 7. Тестирование

**Unit:**
- `test_vessel_metrics.py`: RI/S/D/MV корректны; psv≤edv → valid=False; edv≤0 → sd/ri None; округление.
- `test_study_measurement_session.py` (расширение): merge по ключу, замена, очистка при пустом, фильтр по instance.
- `test_measurement_models.py` (расширение): VesselMeasurement dataclass, снапшот-поле.

**Widget/presentation:**
- Активация кнопок: с velocity-калибровкой+baseline → enabled; без → disabled.
- Размещение PSV/EDV → оверлей появляется и содержит корректные значения.
- Clear сбрасывает маркеры и скрывает оверлей.
- Accept пишет в снапшот и панель/worksheet обновляются.
- Перетаскивание обновляет оверлей.

**Регрессия:** существующие doppler/calibration/measurement тесты проходят.

## 8. Порядок реализации

1. Domain: `vessel_metrics.py`, `vessel_measurement.py`, снапшот-поле + тесты.
2. Session: `merge_vessel_measurements` + store-метод + тесты.
3. Controller: `accept_vessel_measurement`, проброс в снапшот.
4. Overlay: tool-mode vessel, маркеры, перетаскивание, TextItem-оверлей.
5. Tools panel: группа «Сосуды» + сигналы + активация.
6. ViewerWidget: routing, hotkeys, Accept/Clear.
7. Панель + worksheet отображение.
8. Интеграционный прогон + регрессия.
