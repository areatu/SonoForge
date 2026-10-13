# QH-1a.1: сохранённые записи — один читатель для приветственной страницы и менеджера (2026-10-13)

**Область:** первый исправляющий срез плана QH (спека и план — PR [#153](https://github.com/areatu/SonoForge/pull/153)),
инварианты S-06, S-07, S-09, S-10.

**Что проверялось:** заявленный разрыв QH-1a «Блок „Недавние исследования“ подключён к сохранённым измерениям
Z2-M» (CHANGELOG v0.3.3) на реальном хранилище, а не на моке.

---

## 1. Дефект: «нет сохранённых исследований» при здоровых файлах

`MainWindow._stored_measurement_records()` получал записи так:

```python
persistence = self._controller.measurement_persistence
store = persistence.store           # StudyMeasurementSessionStore — RAM-сессия
for path in store.entries():        # entries() принадлежит MeasurementRepository
```

`entries()` есть только у файлового репозитория; у RAM-хранилища его нет. `AttributeError` попадал в
широкий `except Exception` и превращался в `logger.debug(...)` + пустой список — то есть в «недавних
исследований нет» независимо от содержимого `<app-data>/measurements`. Тест
`test_stored_measurement_records_render_as_disabled_rows` подменял сам метод (`monkeypatch`), поэтому
дефект не воспроизводился в CI: проверялась разметка строки, а не её источник.

Второй потребитель — менеджер сохранённых измерений — читал репозиторий сам
(`[(path.stem, path.stat().st_size) for path in repository.entries()]`) и показывал только размер файла:
повреждённая запись выглядела как обычная, а неудачное чтение каталога — как пустой список с нулём записей.

## 2. Воспроизведение до исправления

```
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=<stub> pytest \
  tests/unit/test_start_page_recents.py::test_saved_record_appears_as_a_disabled_row_after_a_real_save -q
```

С прежним `presentation/main_window.py` и остальными изменениями этой ветки тест падает:
`TimeoutError: waitUntil timed out in 5000 milliseconds` — сохранённая запись, записанная настоящим
`MeasurementRepository`, на странице не появляется. С исправлением — проходит.

## 3. Что сделано

| Слой | Изменение |
|---|---|
| `application/saved_records.py` (новый) | Чистая проекция: `SavedRecordSummary` (непрозрачный ключ, статус, `saved_at`, ревизия, размер, число источников/измерений/доплеровских меток, allowlist семейств), `SavedRecordsListing` (+ `failed`), `summarize_record()`, `read_saved_records(repository, limit=None)` |
| `application/measurement_persistence.py` | Публичный `list_saved_records(callback, *, limit=None)` — чтение на serial-worker'е, `callback` в owning thread; после `close()` возвращает `failed`, а не исключение |
| `presentation/main_window.py` | `_request_saved_records()` / `_on_saved_records_listed()` / `_invalidate_saved_records()` вместо `_stored_measurement_records()`; строки хранилища дедуплицируются по тому же sha256-ключу, что пишет репозиторий (UID на страницу не попадает); инвалидизация кэша по статусам `saved/saved_drafts/restored/partial/disabled` и после менеджера |
| `presentation/measurement_storage_dialog.py` | Тот же API; строка записи = дата · размер · число измерений, нечитаемые — со статусом и подсказкой; явный текст «не удалось прочитать список» |
| Локали | 27 ключей RU/EN: `persistence.record_row*`, `persistence.record_status.*`, `persistence.stats_unreadable*`, `persistence.records_failed`, `start_page.recent_studies_{measurements,unreadable,failed}*`; `test_locale_key_parity` проходит |

Статусы записи: `readable` — документ разобран и провалидирован кодеком; `corrupt` — повреждён
(включая отсутствующий/нечисловой `schema_version`); `unsupported` — объявленная версия схемы/семантики
новее этой сборки; `unavailable` — файл не читается (права, носитель). Различие `corrupt`/`unsupported`
делается по объявленной версии в самом документе только после отказа кодека; повреждённый сосед не мешает
читать остальные, а `failed` списка никогда не рендерится как пустое хранилище.

## 4. Проверка

Прогон на Linux, offscreen (`QT_QPA_PLATFORM=offscreen`), Python 3.11.2, PySide6 6.11.2:

| Набор | Результат |
|---|---|
| `tests/unit/test_saved_records_listing.py` (новый, 9) | passed |
| `tests/unit/test_start_page_recents.py` (8) | passed |
| `tests/unit/test_measurement_storage_dialog.py` (10) | passed |
| `test_measurement_cache_compatibility`, `test_presentation_start_page`, `test_i18n`, `test_measurement_persistence_disk`, `test_measurement_persistence_rules`, `test_measurement_repository`, `test_measurement_session_persistence` | passed |
| `test_main_window_tabs`, `test_presentation_main_window`, `test_tab_coordinator`, `test_main_window_layout` | passed |
| `ruff check src/ tests/`, `ruff format --check src/ tests/` | чисто |

Покрытые сценарии (соответствуют A-01/Э5 в матрице спеки): реальная запись → строки на приветственной
странице и в менеджере; повреждённая и «будущая» запись рядом с читаемой; недоступный файл; неудачное
чтение каталога ≠ пустое хранилище; отключённое автосохранение (Presenter/off-policy) не читает записи вовсе.

## 5. Остаток QH-1a и что не заявляется

- **Э10 (клип A из вкладки 1 + клип B из вкладки 2)** — отдельный срез QH-1a.2: пары/поколения,
  владение источником при закрытии вкладки, бейджи/mirror. В этом PR не менялось.
- **QH-0 baseline** (characterization-тесты ViewerWidget и метрики lifecycle) не выполнялся; этот отчёт —
  evidence только по срезу QH-1a.1.
- Перемещение не-DICOM источника (hash-remap), import preview, partial-restore barriers — QH-1c.
- Provenance/freshness производных результатов (stale/fresh/unavailable) — QH-1b.
- Ограничения формулировок: «Приложение сообщает о состоянии файла» не означает проверку клинической
  достоверности содержимого; чтение остаётся только чтением — файлы не перезаписываются и не «лечатся»
  автоматически, решение об удалении остаётся за пользователем (S-05/S-06).
