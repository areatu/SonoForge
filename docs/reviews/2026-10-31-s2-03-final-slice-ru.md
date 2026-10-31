# S2-03 (#307): финальный срез — profiler, instance_sort, pixel_utils — evidence

Дата: 2026-10-31. Спринт 2 аудита 2026-10-22, §5.2 P2-8. Этот срез **завершает
#307**: allowlist `presentation → infrastructure` пуст, ratchet запрещает любое
новое ребро.

## Область среза

| Запись (было) | Источников | Решение |
|---|---|---|
| `profiler` | 2 (main_window, viewer_widget) | `profiled` добавлен в единый diagnostics-порт `application/diagnostics.py` (кросс-срезный instrumentation) |
| `instance_sort` | 1 (thumbnail_gallery_groups) | pure helper **перенесён** в `domain/services/instance_sort.py` (зависит только от domain.models + stdlib); потребители (workers, local_scanner, тесты) переведены |
| `pixel_utils` | 1 (viewer_widget) | display/WL-алгоритмы **перенесены** в новое `imaging/display.py`; `infrastructure/pixel_utils.py` стал чистым compat-shim'ом (workers/бенчи/тесты не менялись) |

Дополнительно: viewer_widget больше не импортирует приватное
`_grayscale_source_array` — публичное имя `grayscale_source_array` в
`imaging/display.py` (legacy-алиас сохранён в shim).

## Итог #307 за сессию (4 среза, 4 коммита)

1. user preferences за application-фасадом (allowlist 11 → 9)
2. i18n за application/localization (9 → 8)
3. diagnostics-группа за application/diagnostics (8 → 3)
4. profiler/instance_sort/pixel_utils (3 → **0**, пустой allowlist)

## Приёмка

- **presentation → infrastructure: 0 рёбер, allowlist пуст**; ratchet точного
  совпадения: actual 0 = 0.
- Инварианты слоёв сохранены: domain → infrastructure 0; imaging →
  остальные слои 0 (`imaging/display.py` — только cv2/numpy).
- `ruff check`/`format --check` — чисто; гейт длины функций зелёный.
- `tests/security` — 325 зелёных; `tests/unit/test_architecture_boundaries.py`
  + поведенческие прогоны перенесённого кода (`test_instance_sort`,
  `test_pixel_utils_display_range`, `test_wl_lut`, `test_profiler`) — 46
  зелёных; shim-паритет проверен тождеством объектов функций.
- Инвентарь pytest не менялся (тесты не добавлялись/не удалялись).

## Статус задач #307

- [x] Вынести оставшиеся I/O-вызовы за фасады `application/`.
- [x] Не тащить Qt в application/domain.
- [x] Ratchet: новые `presentation → infrastructure` запрещены; список
      сокращён до нуля.
- [x] Двигаться по 5–6 модулей за PR — срезы выполнены сериями коммитов.
- [ ] UI-сценарии (открытие, экспорт, настройки сервера) — код менялся на
      пасsthrough/переносе без изменения поведения; подтверждается
      полным GUI-матрицем при PR.
- [x] `test_architecture_boundaries.py` и `test_qh3_boundary.py` зелёные
      (первый локально; второй — в CI, требует Qt).
