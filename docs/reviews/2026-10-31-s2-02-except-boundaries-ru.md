# S2-02 (#306): сузить except и добавить логирование — evidence

Дата: 2026-10-31. Спринт 2 аудита 2026-10-22, P2-8/§5.3.

## Исходная проблема (снимок аудита)

290 широких перехватов, 53 молчаливых (`pass`/`return None`). В
`measurement_persistence` и viewer-контроллерах молчание скрывало дефекты
сохранности данных. UI-перехваты вне этих границ часто оправданы (не падать
из-за одного виджета).

## Что уже было сделано до этой итерации

- `application/measurement_persistence.py`: все перехваты узкие
  (`MeasurementStorageError`, `OSError`, `ArithmeticError`, …). Единственный
  широкий — граница async-worker в `_submit`: любая ошибка воркера обязана
  завершить callback безопасным отказом, а не оставить UI висеть; событие
  пишется через `log_boundary_failure` (комментарий фиксирует решение).
- `presentation/viewer/*` (calibration/contour/magnifier/overlay/tool/worker
  bridge): узкие типы; молчаливые `pass` — только на Qt-teardown
  (`RuntimeError` уже отключённого объекта) с комментарием о
  идемпотентности.
- PR #373 (2026-10-28): 6 молчаливых `pass` после широких except в
  `viewer_widget.py` заменены на `log_boundary_failure`.

## Изменения этой итерации (`viewer_widget.py`)

1. Построение snapshot'а контекста (`view_range`, `vp_size`, `img_size`):
   широкие `except Exception` заменены узким кортежем
   `(ArithmeticError, AttributeError, IndexError, RuntimeError, TypeError,
   ValueError)` + DEBUG-событие `viewer.context_sync/invalid`.
   Незнакомая ошибка теперь не маскируется под «нет данных».
2. Границы I/O без логирования получили allowlisted DEBUG-события:
   - `_refresh_dicom_tags_overlay` — `dicom.annotations/invalid`
     (нечитаемый header прячет оверлей, но дефект наблюдаем);
   - `_doppler_cardiac_cycles` и `_load_ecg_for_strip` —
     `dicom.waveform/invalid` (отсутствующая/нечитаемая волна деградирует
     без ECG-полосы).
3. Оставшиеся широкие перехваты в `viewer_widget.py` не тронуты осознанно:
   контекст-propagate/magnifier/overlay-style/auto-calibration уже логируются
   (события allowlisted, `code="ui"` нормализуется в `unexpected`);
   геометрические fallback'и (`_event_screen_point`,
   `_map_image_point_to_viewer`) — молчаливые с комментарием: деградация
   координат на событии мыши, не потеря данных; лог на каждый mouse-move
   был бы шумом.

Семантика успешных сценариев не менялась; наблюдаемость отказов выросла.

## Тесты

- Новые gui-тесты `tests/unit/test_viewer_safe_diagnostics.py` (3):
  нечитаемый header, сбой чтения ECG-волны (strip и cardiac cycles) —
  DEBUG-событие allowlisted, PHI-заглушка не попадает в лог,
  `exc_info is None`.
- `tests/security/test_qh4a_diagnostics.py` — 30 зелёные, включая
  `test_every_literal_boundary_operation_is_allowlisted` (новые literal-операции
  проходят allowlist) и проверки отсутствия сырых exception-payload.
- `ruff check` / `ruff format --check` — чисто; гейт длины функций — зелёный
  (`_sync_viewer_context` не вырос за 200 строк).
- Ограничение песочницы: GUI/unit-сьют требует `libGL.so.1` (нет в sandbox,
  apt-зеркала недоступны) — прогон `tests/unit` и gui-отметка проверяются в
  GitHub Actions, как в PR #373.

## Приёмка #306

- [x] В целевых модулях нет необоснованных `except Exception`.
- [x] Нет новых молчаливых `pass` (остались только задокументированные
      Qt-teardown и геометрические fallback'и).
- [x] Логи не содержат PHI/путей/UID (`log_boundary_failure` + тесты
      sanitizer).
- [ ] Тесты persistence/viewer зелёные — ожидание GitHub Actions.
