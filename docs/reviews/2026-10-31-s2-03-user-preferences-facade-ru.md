# S2-03 (#307): срез «user preferences за application-фасадом» — evidence

Дата: 2026-10-31. Спринт 2 аудита 2026-10-22, §5.2 P2-8; срез «5–6 модулей за PR».

## Область среза

Из растущего allowlist-а `tests/architecture/presentation_infrastructure_allowlist.json`
удалены **две записи целиком** (14 presentation-источников → 0):

- `infrastructure.user_preferences` (6 модулей: `download_coordinator`,
  `main_window`, `measures_menu`, `presenter_view`,
  `user_preferences_dialog`, `viewer_widget`);
- `infrastructure.ui_scale` (1 модуль: `user_preferences_dialog`).

## Как устроено

- `application/user_preferences.py` (Qt-free фасад) теперь владеет контрактом:
  session-source маркеры, все сжимаемые UI-диапазоны (font/opacity/line/
  playback/WL/magnetic/magnifier/PDF), `PRESENTATION_PRESET_OVERRIDES`,
  `UI_SCALE_AUTO`/`UI_SCALE_CHOICES`, `resolve_wl_values` (перенесённая чистая
  функция) и ленивые обёртки `default_user_preferences`,
  `default_measurement_persistence_enabled`, `normalize_ui_scale`,
  `restart_application`, новая `gold_annotation_enabled` (вместо приватных
  `_settings_store`/`_read_bool` в `viewer_widget`).
- `infrastructure/user_preferences.py` и `infrastructure/ui_scale.py`
  импортируют контрактные значения из фасада и ре-экспортируют их
  (`infrastructure → application` — устоявшееся направление: dimse_client,
  measurement_codec, orthanc_client уже так делают). Тесты и
  `main.py`, импортирующие имена из infra, продолжают работать без правок.
- Протокол `UserPreferences` расширен полями, которые presentation читает через
  типизированные ссылки.

## Приёмка

- Allowlist сокращён с 11 до 9 записей; точное совпадение рatchet-а
  проверено: actual 94 = allowlist 94, added/removed пусты
  (`test_presentation_has_only_reviewed_infrastructure_imports`).
- Новые `presentation → infrastructure` рёбра не добавлены.
- Фасад импортируется без Qt: проверено локально
  (`import application.user_preferences` не тянет PySide6 и
  `infrastructure.user_preferences` в `sys.modules`).
- `ruff check`/`ruff format --check` — чисто; гейт длины функций зелёный.
- `tests/security` — 325 зелёных; `tests/unit/test_architecture_boundaries.py`
  — 8 зелёных (прогон `--noconftest`: песочница без libGL не поднимает Qt-
  conftest; полный GUI-матриц подтверждает GitHub Actions).
- UI-сценарии (открытие, настройки, экспорт) — код менялся только на
  пасsthrough-уровне; поведение и значения по умолчанию не менялись
  (константы — те же объекты, `resolve_wl_values` — тот же код).

## Остаток #307 (следующие срезы)

- `i18n` (60+ источников) — требует отдельного слоя локализации.
- `safe_diagnostics`/`diagnostics`/`log_sanitizer`/`profiler` — application
  diagnostics port.
- `user_preferences_dialog → diagnostics` (create_diagnostic_bundle) —
  входит в diagnostics-срез.
- `support_report`, `profile`, `instance_sort` (→ domain/imaging),
  `pixel_utils` (→ imaging core).
