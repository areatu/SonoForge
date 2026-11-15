- `feat(key-images)`: #561 — «Ключевые кадры»: per-study JSON-закладки, переход к кадру после смены сортировки, честный статус источника.

**Что добавлено**

- Документ `<measurements_dir>/key-images/<study_key>.json` (`sonoforge.key-images`, версия 1): строгий allowlist полей, лимиты 500 записей и 2 MiB, атомарная запись через хранилище измерений, запрет symlink. Путь к файлу и пиксели не персистятся; измерения не меняются (`measurement_codec.VERSION` остаётся 6).
- Закладка хранит SOP/серию/номер кадра, число кадров, `measurement_id` (только при однозначном кандидате на кадре), размер и `mtime_ns` источника. Переход идёт по SOP и кадру, а не по позиции миниатюры.
- `available` — источник совпал по кадрам и `stat`; `missing` — SOP/файл не найден; `changed` — изменились размер, `mtime_ns` или число кадров. В двух последних случаях переход блокируется с явным статусом.
- Меню приложения → «Ключевые кадры…», команда `key_images` в `Ctrl+K`; диалог со списком, добавлением текущего кадра, удалением и переходом. Переход использует `report_coordinator.open_frames`, поэтому карточка происхождения #284 не дублируется.
- Справка RU/EN: раздел 2.9.

**Прогоны**

- `tests/unit/test_key_images.py` — 8 тестов, `tests/unit/test_key_images_dialog.py` — 5 GUI-тестов; `test_command_catalog`, `test_composition_root`, `test_i18n`, `test_docs_links`, `test_main_window_layout` — проходят.
- `ruff check`/`format`, `mypy` по четырём новым модулям, ратчеты class-size/function-length/private-access/type-ignores/broad-excepts/layer-directions/ui-colors/doc-links/id-references/untranslated-ui-strings — проходят.
