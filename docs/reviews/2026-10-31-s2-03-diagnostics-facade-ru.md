# S2-03 (#307): срез «единый application diagnostics port» — evidence

> **Снимок на 2026-10-31.** Документ фиксирует состояние на эту дату и не обновляется вслед за кодом: актуальное состояние — в коде, `README.md`, HELP и открытых issues.

Дата: 2026-10-31. Спринт 2 аудита 2026-10-22, §5.2 P2-8; третий срез после
`user preferences` и `i18n`.

## Область среза

Из allowlist удалены **пять записей целиком** (28 источников → 0):

| Запись | Источников | Что мигрировано |
|---|---|---|
| `safe_diagnostics` | 22 | `log_boundary_failure`, `log_boundary_event`, `safe_error_category` |
| `diagnostics` | 3 | `create_diagnostic_bundle` (ленивые сайты в feedback/main_window/preferences dialogs) |
| `support_report` | 1 | `build_issue_url`, `environment_text` |
| `log_sanitizer` | 1 | `sanitize_log_text` (presenter_diagnostics) |
| `profile` | 1 | `diag_log_dir` (presenter_diagnostics) |

## Как устроено

- Новый `application/diagnostics.py` — единый diagnostics-порт: ре-экспорт
  allowlisted boundary-логирования, санитизации, сборки support-bundle,
  prefill issue-ссылок и пути диаг-логов.
- Module-level импорт — по той же схеме, что localization: все пять адаптеров
  Qt-free на уровне импорта (проверено эмпирически и
  `test_application_io_facades_have_no_qt_imports`); `log_boundary_failure`
  работает на горячих путях ошибок. Профильный адаптер подтягивается
  транзитивно через `infrastructure.paths` (portable-root) — он тоже Qt-free.
- Фасад зарегистрирован в AST-списке фасадов и в subprocess-цепочке no-Qt
  теста.

## Приёмка

- Allowlist: 8 → 3 записи (`instance_sort`, `pixel_utils`, `profiler`);
  ratchet точного совпадения: actual 4 = 4, added/removed пусты.
- Прямых `presentation → infrastructure` импортов diagnostics-группы не
  осталось (включая ленивые сайты внутри функций).
- `ruff check`/`format --check` — чисто (24 .py); гейт длины функций зелёный.
- `tests/security` — 325 зелёных; `tests/unit/test_architecture_boundaries.py`
  — 8 зелёных (включая новый фасад в no-Qt subprocess-цепочке).
- Инвентарь pytest не менялся.

## Остаток #307 (последний срез)

- `profiler` (2 источника: main_window, viewer_widget) — cross-cutting
  instrumentation; рассмотреть application diagnostics/instrumentation port.
- `instance_sort` (thumbnail_gallery_groups) — перенести pure helper в
  domain/imaging.
- `pixel_utils` (viewer_widget) — перенести imaging-алгоритмы в независимое
  imaging-ядро.
