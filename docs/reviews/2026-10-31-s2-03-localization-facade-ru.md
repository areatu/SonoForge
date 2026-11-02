# S2-03 (#307): срез «i18n за application-слоем» — evidence

> **Снимок на 2026-10-31.** Документ фиксирует состояние на эту дату и не обновляется вслед за кодом: актуальное состояние — в коде, `README.md`, HELP и открытых issues.

Дата: 2026-10-31. Спринт 2 аудита 2026-10-22, §5.2 P2-8; продолжение срезов
после `user preferences`-фасада.

## Область среза

Запись `infrastructure.i18n` — крупнейшая в allowlist — удалена целиком:
**62 presentation-модуля, 114 точек импорта** переведены с
`infrastructure.i18n` на новый application-фасад.

## Как устроено

- `infrastructure/i18n.py` — Qt-free адаптер (JSON-локали,
  `domain.translation`, `safe_diagnostics`); реализация не менялась.
- Новый `application/localization.py` — узкий ре-экспортный фасад
  (`tr`, `tr_plural`, `tr_for_language`, `get_language`, `set_language`,
  `register_ui_reload`, `unregister_ui_reload`). В отличие от
  settings-фасадов, импорт здесь module-level: адаптер не тянет Qt, а `tr`
  работает на горячих путях (оверлеи вызывают его каждый кадр) — ленивый
  импорт на вызов дал бы только накладные расходы.
- Фасад зарегистрирован в `test_application_io_facades_have_no_qt_imports`
  (AST-проверка Qt-свободы + импорт в subprocess-цепочке).
- Два устаревших комментария о «presentation → infrastructure.i18n edge»
  (`reference_card.py`, `theme/palette_picker.py`) переписаны без привязки к
  infrastructure.

## Приёмка

- Allowlist: 11 → 8 записей; ratchet точного совпадения: actual 32 = 32,
  added/removed пусты.
- Прямых `presentation → infrastructure.i18n` импортов не осталось
  (абсолютных, относительных и package-level).
- `ruff check`/`format --check` — чисто (64 .py); гейт длины функций зелёный.
- `tests/security` — 325 зелёных; `tests/unit/test_architecture_boundaries.py`
  — 8 зелёных (включая новый фасад в no-Qt subprocess-цепочке).
- Инвентарь pytest не менялся (тесты не добавлялись/не удалялись).
- Локальный импорт-смоук: `application.localization` импортируется без
  PySide6; `tr`/`get_language` отвечают.

## Остаток #307 (последующие срезы)

- diagnostics-группа: `safe_diagnostics` (22 источника), `diagnostics`,
  `log_sanitizer`, `support_report`, `profile` — единый application
  diagnostics port.
- `user_preferences_dialog → diagnostics` (create_diagnostic_bundle) — входит
  в diagnostics-срез.
- `profiler` (2 источника), `instance_sort` (→ domain/imaging),
  `pixel_utils` (→ imaging core).
