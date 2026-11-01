# S3-04 (#313): PDF-экспорт в worker, лимит пикселей, accessibility — evidence

Дата: 2026-11-01. Спринт 3 аудита 2026-10-22, P2-16/17/18, §7.3. Issue: #313.

Три независимых риска закрываются одним срезом: экспорт PDF больше не занимает
UI-поток, огромное исследование отклоняется до выделения памяти, у ключевых
контролов отчёта появились доступные имена и явный порядок Tab.

## 1. PDF-экспорт вне UI-потока

Было: `main_window._export_report_pdf` вызывал `export_report_document_pdf`
(ReportLab, весь лист A4) прямо в обработчике клика — окно не перерисовывалось,
пока документ собирался, а отменить экспорт было нечем.

Стало, три части:

| Слой | Файл | Роль |
|---|---|---|
| application | `application/workers/report_export_worker.py` | `QRunnable`: `render_report` на потоке пула, затем проверка отмены, затем `publish_report_pdf` (атомарная публикация). Наружу только коды: `finished(path)`, `failed("pdf_export_failed")`, `cancelled()` |
| application/infrastructure | `application/report_export.py` → `infrastructure/measurement_report_pdf.py` | `publish_report_pdf` / `write_report_pdf`: запись заранее отрендеренных байт через `mkstemp` + `os.replace`, ошибка — тот же `ReportExportError("pdf_export_failed")` |
| presentation | `presentation/report_mode/export_job.py` | `ReportPdfExportJob`: модальный `QProgressDialog` с «Отмена», владение worker'ом и ровно один outcome-callback |

Почему отдельный job, а не диалог в `main_window`:

- **Отмена побеждает публикацию.** Диалог закрывается в момент клика «Отмена», а
  worker продолжает рендер. Job после `exec()` синхронно вызывает
  `worker.cancel()`, иначе быстрый рендер успевает записать файл, который
  пользователь отменил. Проверено тестом
  `test_cancelling_while_the_sheet_renders_publishes_nothing`.
- **`QProgressDialog.canceled` в Qt 6 приходит не в тот же оборот цикла
  событий** (наблюдено на 6.11: сигнал доставлен уже после возврата из `exec()`).
  Полагаться на него как на «пользователь отменил» нельзя — job отменяет worker
  сам, а сигнал остаётся лишь подсказкой.
- **Worker должен пережить диалог.** Без ссылки на worker его `signals`-объект
  умирает вместе с локальной переменной, и `cancelled()`/`failed()` уже некуда
  доставлять (`RuntimeError: Signal source has been deleted`). Job — `QObject`
  с родителем-окном и держит worker до прихода исхода.

Отмена кооперативная: рендер — один проход ReportLab, он не прерывается
посреди страницы, но файл не публикуется. Это обещанный контракт («отмена
обрабатывается»), а не «частично записанный PDF».

## 2. Лимит пикселей до декодирования

Новый модуль `infrastructure/pixel_budget.py`:

- `MAX_DECODED_PIXELS = 200_000_000` (200 Мпикс — порог из issue);
- `decoded_pixels(rows, columns, frames, samples)` — `Rows × Columns × Frames ×
  SamplesPerPixel` (сэмплы входят, потому что память выделяется на сэмпл: RGB
  того же кадра стоит втрое);
- `StudyTooLargeError` — отказ с `code = "study_too_large"`, сообщение содержит
  только числа (никаких путей и идентификаторов), поэтому его можно показывать;
- `check_dataset_budget(dataset, frames)` — проверка по распарсенному заголовку.

Точки проверки в `DicomSession._open_impl`:

1. сразу после `stop_before_pixels`-парсинга с `frames=1` — одиночный
   патологический кадр отсекается до того, как восстановление `NumberOfFrames`
   прочитает весь файл (`read_bytes()`);
2. после того как реальное число кадров известно — бюджет всего исследования
   проверяется до `_map_pixel_data()`/чтения пиксельного блока.

Отказ **опустошает сессию** (`release()`): ни пути, ни числа кадров, ни
mapped-блока — повторный `open()` начинает с нуля, а не рапортует кадры,
которые не может декодировать. Причина идёт в статус-бар локализованной строкой
`status.study_too_large` из `DicomDecodeWorker` (стабильный код, без текста
исключения).

Почему 200 Мпикс не мешает клинике: 512×512 × 300 кадров = 79 Мпикс, 800×600 ×
120 = 58 Мпикс. Порог срабатывает на патологических заголовках, а не на длинных
легитимных петлях.

## 3. Accessibility отчёта

`ReportExportPanel` (экспортный блок режима «Отчёт»):

| Контрол | visible | `accessibleName` (RU) | Tab |
|---|---|---|---|
| `reportExportPdf` | «PDF…» | «Экспорт отчёта в PDF» | 1 |
| `reportExportPrint` | «Печать…» | «Печать отчёта» | 2 |
| `reportFinish` | «Завершить» / «Новый черновик» | «Завершить отчёт» / «Новый черновик отчёта» | 3 |
| `reportExportStatus` | строка результата | «Результат экспорта» | — |

Имена пересоздаются в `reload_text()`/`set_finished()`, то есть переживают
смену языка и фиксацию версии. Порядок Tab задан явно
(`setTabOrder(pdf → print → finish)`) — совпадает с визуальным.

### Ручной чек-лист (screen reader, Windows + NVDA)

Автоматика покрывает имена, порядок и доступность фокуса
(`tests/unit/test_report_accessibility.py`), но не проверяет, *как* это звучит.
Перед релизом:

1. Открыть исследование → режим «Отчёт» (Ctrl+R).
2. Tab от последнего поля пациента: фокус проходит «PDF…» → «Печать…» →
   «Завершить», ни один не пропущен и не переставлен.
3. NVDA + стрелки по экспортному блоку: озвучиваются полные имена, а не
   «PDF…».
4. «Завершить» → имя меняется на «Новый черновик отчёта» (без перезапуска).
5. «PDF…» → диалог прогресса объявляется; «Отмена» возвращает фокус в блок,
   статус «Экспорт отменён».
6. Смена языка на EN (Настройки) → имена английские, Tab-порядок тот же.
7. Открыть исследование с бюджетом больше 200 Мпикс → в статус-баре
   «Исследование слишком велико для декодирования: … Мпикс при пределе 200
   Мпикс», без трейсбека и без «залипания» окна.

Известные ограничения: полная автоматизация screen reader в CI не делается
(нужен живой AT); проверяются имена/порядок/фокус — этого достаточно, чтобы
регрессия «кнопка без имени» падала тестом.

## Приёмка #313

- [x] PDF-экспорт не блокирует UI (рендер в пуле, окно живо).
- [x] Отмена и ошибка обрабатываются (job + stable codes; тесты на оба пути).
- [x] Огромное исследование отклоняется до выделения памяти (два рубежа, тест
      с запретом `read_bytes`).
- [x] Ключевые controls имеют accessible name; Tab-order логичен.
- [x] Есть тест/чек-лист accessibility.
- [x] Внешний вид отчёта не менялся (ни одна строка `measurement_report_pdf`
      про вёрстку не правилась).

## Проверки

```bash
uv run pytest tests/unit/test_pixel_budget.py \
    tests/unit/test_report_export_worker.py \
    tests/unit/test_report_export_job.py \
    tests/unit/test_report_accessibility.py -q
uv run pytest tests/unit/test_measurement_report_pdf.py \
    tests/unit/test_report_export.py tests/unit/test_application_report_export.py -q
uv run pytest tests/unit -q -m "not gui"
ruff check src tests && ruff format --check src tests
mypy
```

Результат в песочнице (Linux, Qt 6.11, стабы `libGL`/`libxkbcommon`, платформа
`minimal`):

- **новые наборы** — `test_pixel_budget.py` 23 логических, `test_report_export_worker.py`
  12 GUI, `test_report_export_job.py` 6 GUI, `test_report_accessibility.py` 9 GUI — зелёные;
- **смежные наборы** — `test_measurement_report_pdf`, `test_report_export`,
  `test_application_report_export`, `test_report_locale_goldens`, `test_dicom_session`,
  `test_i18n`, `test_architecture_boundaries`, `test_ui_colors_ratchet`,
  `test_overlay_tokens` — зелёные;
- **полный логический прогон** `tests/unit -m "not gui" -n 4` — 12 падений, и все 12
  падают на коде **без** этого среза (проверено прогоном тех же файлов со спрятанными
  изменениями): `test_ui_scale` (5, `SIGABRT` подставочного Qt в subprocess) и
  `test_video_reader`/`test_session_registry` (7, кодеки/индексация кадров в
  синтетическом видео этого образа). Новых падений нет;
- **храповик цветовых литералов** остался 190: ссылки на issue в проверяемых
  областях записаны комментарием, а не строкой (`#313` в докстринге считается
  цветовым литералом `#313`);
- `ruff check` / `ruff format --check` — чисто; `mypy` по изменённым модулям — success;
  baseline инвентаря pytest пере-базирован 9463 → 9512 (gui 3893 → 3919,
  not_gui 5570 → 5593, gui_files 202 → 205) скриптом `update_pytest_baseline.py --fix`.
- **GUI-матрица** (Windows/macOS smoke + Linux-шарды) — CI; локально MainWindow-тесты
  неисполнимы из-за шрифтовых артефактов `minimal`-платформы.
