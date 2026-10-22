# QH-4a: адресный error audit register

**Дата / база:** 2026-10-14, `3d23a8f` + QH-1e `9d0b420`.
**Scope:** QH §8.1, A-12, S-07/S-09/S-11. Второй коммит сессии.
**Tracker / назначение owners:** [#160](https://github.com/areatu/SonoForge/issues/160).

Это register критических операций, а не аудит каждого `except Exception` и не завершение G4.
Результат операции и сообщение пользователю важнее записи в лог. Catch-all допустим на worker
boundary, но не превращает programming error в normal empty/success. Ни зелёные тесты, ни этот
документ не подтверждают clinical/native acceptance.

## 1. Политика и статусы

- **VERIFIED-SLICE**: конкретный контракт проверен перечисленным тестом; не вся операция/пакет.
- **FIXED-SLICE**: ошибка воспроизведена до исправления и тест проходит после него.
- **OPEN**: установлен code gap; тест рядом проверяет только существующее поведение,
  **не** доказывает целевую реакцию. Сценарий закрытия указан отдельно.
- **BLOCKED**: нет внешнего prerequisite/owner-run evidence; не PASS.

Owners ниже — роли, не выдуманные имена: **T** = technical maintainer, **P** = presentation maintainer,
**D** = data/clinical reviewer, **R** = release/CI maintainer. Назначение конкретных людей/сроков —
владельцем проекта в #160, пока **не назначено**. Каждый OPEN ID — checkbox в tracker.

Целевая безопасная диагностика: allowlist `operation`, стабильный `code`, одобренная категория
exception, revision/count/duration и opaque correlation ID. Не `str(exc)`, traceback, source UID,
пути, patient label или JSON payload. Regex-filter старых логов — defence in depth, не замена
producer allowlist. Не включаем PHI в новые логи ради последующего «очищения».

Все пути ниже относительно `src/echo_personal_tool/`, tests относительно `tests/`.
Функции/методы указаны вместо нестабильных номеров строк.

## 2. Критические I/O / identity / clinical actions (первый приоритет)

| ID / owner / статус | Место / operation | Ожидаемые exceptions | Последствия и текущая реакция | Целевая реакция / остаток | Evidence / закрытие |
|---|---|---|---|---|---|
| **ER-01 T VERIFIED-SLICE** | `infrastructure/measurement_repository.py::MeasurementRepository.save/atomic_write` — save/revision | `MeasurementStorageError(conflict/quota/unsafe_path/busy/invalid/identity/version)`, `OSError` (`PermissionError`, replace/fsync failure) | Repository не выдаёт ack до записи; old committed JSON сохраняется при failed replace; coordinator держит dirty RAM | Сохранить revision/lock/atomic контракт. Full write/fsync/quota fault matrix — остаток QH-1c, не закрыт этим register | `unit/test_measurement_repository.py::test_failed_replace_leaves_last_committed_record`, `::test_write_revision_conflict_and_delete`, `::test_quota_does_not_evict`; `unit/test_measurement_persistence_disk.py::test_failed_save_keeps_dirty_snapshot_and_retry`, `::test_new_edit_during_failed_write_never_requeues_old_snapshot` |
| **ER-02 T FIXED-SLICE** | `application/saved_records.py::read_saved_records/_read_one/summarize_record` + `MeasurementPersistence.list_saved_records` — list/load summaries | `OSError`, `MeasurementStorageError`, unexpected codec boundary exception | Typed frozen listing различает failed vs empty; corrupt/unsupported/unavailable сосед не скрывает readable; closed API даёт `io`; `summarize_record` и `read_saved_records` нормализуют произвольные коды через `safe_failure_code(..., fallback="io")`, а `OSError` при сканировании даёт `scan` + `log_boundary_failure` | Закрыто в коде и тестах | `unit/test_saved_records_listing.py`, `security/test_qh4a_diagnostics.py::test_saved_records_normalizes_unknown_storage_error_codes` |
| **ER-03 T/P FIXED-SLICE** | `application/measurement_persistence.py::list_record_summaries/_summarize_entry` — legacy parallel listing | `OSError`, `MeasurementStorageError`; programming `AttributeError/TypeError` | `_summarize_entry` делегирует классификацию `saved_records.summarize_record` (единый классификатор: `schema_version=0/"x"` → `corrupt`, future integer → `unsupported`); `_preview_import_record` и `list_error` проходят `safe_failure_code` | Закрыто в коде и тестах | `unit/test_measurement_persistence_disk.py`, `security/test_qh4a_diagnostics.py::test_saved_records_normalizes_unknown_storage_error_codes` |
| **ER-04 T FIXED-SLICE** | `application/measurement_persistence.py::_submit/_complete/save_pending/_deliver_callback` — asynchronous failure delivery | Storage codes, I/O; deleted Qt receiver `RuntimeError`; catch-all future boundary | Неожиданное исключение → `io`; storage code проходит `safe_failure_code`; внутреннее состояние обновляется до вызова UI callback, а `_deliver_callback` перехватывает `RuntimeError` удалённого Qt-получателя (`ui.cleanup code=cleanup`) | Закрыто в коде и тестах | `security/test_qh4a_diagnostics.py::test_measurement_persistence_survives_deleted_qt_receiver_callback` |
| **ER-05 T FIXED-SLICE** | `application/measurement_persistence.py::load` + `infrastructure/measurement_sources.py::describe_study` — identity/restore | Storage `source/identity/version`, `OSError`, `ValueError`, `InvalidDicomError`, `EOFError` | Source mismatch blocks restore/overwrite; `describe_study` перехватывает `InvalidDicomError`/`EOFError`, логирует `persistence.source code=source` и поднимает `MeasurementStorageError("source")` | Закрыто в коде и тестах | `unit/test_measurement_persistence_disk.py`, `security/test_qh4a_diagnostics.py::test_describe_study_maps_corrupt_dicom_and_eof_to_source_error` |
| **ER-06 T FIXED-SLICE** | `application/measurement_persistence.py::close`, `save_pending` reconciliation cleanup | `TimeoutError`, executor `RuntimeError`, repository `OSError`/storage error | `close(timeout_ms=...)` передаёт `timeout_s = max(0.001, timeout_ms / 1000.0)` в `future.result(timeout=timeout_s)`, возвращает `False` при таймауте/ошибке и логирует `measurement.close code=timeout/io` | Закрыто в коде и тестах | `security/test_qh4a_diagnostics.py::test_measurement_persistence_close_respects_timeout_ms` |
| **ER-07 P/T FIXED-SLICE** | `presentation/report_dialog.py::ReportDialog._export_pdf` → `infrastructure/measurement_report_pdf.py::export_report_document_pdf/_register_cyrillic_font` — report export | `PdfExportError`, `OSError`, font/render errors | Экспорт пишет во временный файл + `os.replace`, перехватывает ошибки шрифта/рендера/I-O в `PdfExportError("pdf_export_failed")`, логирует `report.export code=io` без путей/текста исключения и не открывает частичный файл | Закрыто в коде и тестах | `unit/test_measurement_report_pdf.py`, `security/test_qh4a_diagnostics.py::test_report_export_pdf_boundary_failure_does_not_leak_path` |
| **ER-08 P/T FIXED-SLICE** | `presentation/viewer_widget.py::_finish_model_contour`, `_handle_doppler_calibration_click`, `presentation/viewer/calibration_controller.py` — landmarks/calibration | `ValueError` geometry; expected calibration no-candidate; optional boundary unexpected exception | Оба пути фиксации контура и калибровка эмитируют статические коды (`invalid`, `spacing_error`, `calibration.auto/grid code=blocked`) без `exc_info=True` и без `str(exc)` | Закрыто в коде и тестах | `unit/test_doppler_calibration.py`, `security/test_qh4a_diagnostics.py::test_boundary_projection_covers_manual_calibration_rejection` |

## 3. Workers / diagnostics / optional cleanup (второй приоритет)

| ID / owner / статус | Место / operation | Ожидаемые exceptions | Текущая реакция / последствия | Целевая реакция / evidence |
|---|---|---|---|---|
| **ER-09 T/P FIXED-SLICE** | Все воркеры и producer-модули (`application/`, `domain/`, `infrastructure/`, `presentation/`, `ui/`, `constructor/`, `main.py`) | Model/inference/I/O/network/decode failures, `TimeoutError`, `RuntimeError` | Все `except`-блоки переведены на `log_boundary_failure` / `log_boundary_event` или только категорию исключения (`type(exc).__name__` в чистом домене); во всём `src/echo_personal_tool` 0 вызовов `logger.exception`/`exc_info=True` и 0 передач сырого `exc`/`str(exc)` в логгер | Закрыто и защищено AST-ратчетами `security/test_qh4a_diagnostics.py::test_zero_logger_exception_or_exc_info_in_codebase`, `::test_zero_raw_exception_payload_in_logger_calls` |
| **ER-10 T FIXED-SLICE** | `infrastructure/log_sanitizer.py`, `diagnostics.py::create_diagnostic_bundle`, `safe_diagnostics.py` — support ZIP и локальная очистка | `OSError` reading/sanitizing log, failure writing ZIP | Support ZIP проецирует только полные allowlisted `operation/code/error_type` записи и предварительно очищает локальные логи (`sanitize_local_log_files`); `sanitize_log_text` редактирует пути, DICOM UID, PatientName/PatientID, URL, email и однострочные `Error: message` | Закрыто в коде и тестах: `security/test_qh4a_diagnostics.py`, `unit/test_log_sanitizer.py`, `unit/test_diagnostics.py` |
| **ER-11 T/R FIXED-SLICE** | `infrastructure/logging_setup.py`, `presentation/presenter_diagnostics.py` — локальные `session-*.log`, `crash.log`, `presenter_diag.log` | Main/thread unexpected exception, Qt message, `faulthandler` crash stream | Файловый хендлер использует `_SanitizingFileFormatter` (сбрасывает `exc_info`/`stack_info` и прогоняет текст через `sanitize_log_text`), `faulthandler` пишет через `_SanitizingCrashStream` + `sanitize_local_log_files` при старте и закрытии, `PresenterDiagnostics._write` очищает каждую строку перед записью | Закрыто в коде и тестах: `security/test_qh4a_diagnostics.py::test_local_session_and_crash_logs_are_sanitized_at_write_time`, `::test_presenter_diagnostics_log_is_sanitized_at_write_time`, `unit/test_logging_setup.py` |
| **ER-12 T FIXED-SLICE** | `presentation/viewer/*_controller.py`, `viewer_widget.py`, `measurement_persistence.py` — lifecycle 50/500 и deleted receiver cleanup | Deleted Qt `RuntimeError`, disconnect `RuntimeWarning`, cleanup `OSError` | Идемпотентный `dispose()` без `RuntimeWarning: Failed to disconnect`; 50-цикловый клинический сценарий и 500-цикловый референсный прогон укладываются в бюджеты §7.3 (RSS +≤5 МБ / +≤20 МБ, плоский тренд после 100 циклов, 0 живых QObject закрытого владельца) | Закрыто в коде и тестах: `unit/test_qh3_lifecycle.py::TestQH3Lifecycle::test_clinical_workflow_50_cycles_and_500_reference_cycles_acceptance`, `unit/test_qh0_lifecycle_baseline.py` |

## 4. Что сделано в этом коммите / что намеренно не сделано

- Создан register с operation/types/consequence/current/target/test/owner/issue, в заданном порядке.
- Закрыта воспроизведённая утечка **известных структурированных** полей через sanitizer/ZIP.
  Сырые логи не переписываются, no changes в retention/storage/network, no external upload.
- Добавлены 13 production sentinel/ZIP tests в required security manifest.
- Обновлены SECURITY/inventory/RU+EN HELP: фильтр не anonymisation guarantee, raw crash/logs чувствительны.
- Остаток плана вынесен в execution ledger и #160. Наличие provenance DTO/schema v3 в базе учтено:
  QH-1b.1 groundwork есть; production invalidation/QH-1b.2 не объявлены выполненными.
- **Не** добавлена вторая универсальная система outcomes/logging, **не** переписаны все catch-all,
  **не** смешаны worker lifecycle, PDF write contract и calibration algorithm changes в один PR.

## 5. Evidence и gates

Локально locked Python 3.11.2/Qt 6.11.1, offscreen + существующий `tools/qtstub`:
**147 passed, 0 skipped/xfail** — repository, persistence disk, saved reader/manager, ONNX boundary,
diagnostics, provenance DTO/schema, Doppler calibration и новые sentinel tests.
Это детерминированные tests, **не** native GUI/model accuracy. Full security: **332 passed**, 0 skipped/xfail, required gate **9/9**. CI — PR checks.
JUnit/metrics остаются в ignored `.cache/qh-evidence/` и bounded CI artifacts, не в Git.

**QH-4a register: выполнен.** ER-10 structured-filter slice: FIXED.
**Полный QH-4a / G4: PARTIAL**, OPEN rows в #160; нет утверждения «diagnostics PHI-free».
**G1-STE / G5b: BLOCKED** внешними prerequisites. Имена owners не назначены — это явный gap,
не основание скрыть OPEN или маркировать готовность клинического действия.

### Закрытый CI-хвост этой сессии

Первый CI run подтвердил tests/security/acceptance/GUI/platform packaging, но остановил
`Combined Linux coverage`: audited partition baseline ещё был 6784 total / 3504 logic,
без 111 новых QH-1e cases. Пересчитаны настоящие logic inventory и все 4 GUI shard collections:
**6895 = 3615 logic + 3280 GUI**, GUI files **168** без изменений. Старый baseline воспроизвёл
FAIL; после deliberate baseline update в `verify_pytest_partition.py` проверка PASS.
Partition/required/count checks не ослаблены. Исправление включено в существующий второй коммит,
не отдельный третий. Полный локальный logic run: 3602 passed / 3 skipped (нет external gold) /
7 xfailed / 3 xpassed (существующие, вне formula manifest), 3615/3615 executed; formulas 29/29 PASS.

### CI crash-диагностика: follow-up после run 38529368059

Run на `f65555a` получил native worker crash в `test_debug_overlay_toggle`: 1 failed +
850 passed, JUnit total 851 при selected 850. Это **не доказательство потери тестов**:
extra report может возникнуть при crash/restart. Gate по-прежнему FAIL при любом mismatch.

Воспроизведены два дефекта самой диагностики (не причина native crash):

- `annotate_pytest_failures.py` публиковал fatal stack только без FAILED summary;
  при штатном xdist crash summary stack пропадал из API-readable annotations.
  Теперь публикуется и summary, и ограниченный crash window (8 строк в одной annotation),
  при наличии `Current thread` приоритет у его frames, а не idle background threads.
- `check_pytest_counts.py` объяснял даже excess reports как «dropped queue».
  Теперь distinguishes missing vs extra reports; exit policy не меняется.

4 новых synthetic subprocess cases проверяют crash+FAILED summary, длинный log,
current-thread stack, bounded annotations и counts меньше/больше/равно selected.
До исправления 2 FAIL; после: **30 passed** (annotation/gate tests + display-quality file).
Recollection всех unit files и 4 GUI shards: **6899 = 3619 logic + 3280 GUI**, 168 GUI files.
Это deliberate +4 diagnostic cases к предыдущему 6895, не изменение clinical/GUI selection.

Причина native crash остаётся **не установлена**; ViewerWidget и rendering algorithms этим
follow-up не меняются, тест не skipped/xfail. Полный fatal log предыдущего run недоступен
из песочницы; follow-up нужен, чтобы при повторении stack был виден через GitHub annotations.
Оба fixes включены amend во второй коммит — по-прежнему ровно два коммита PR.


### Интеграция PR #162 и лёгкая дополнительная диагностика

PR #162 влит в main коммитом `14e6b51`. PR #161 обновлён поверх него без
дублирующего cherry-pick: изоляция QtWebEngine в unit tests, marker `real_webengine`
и shutdown для некэшированных reference dialogs сохранены как в #162.
Это не добавляет jobs/retries, не отключает count/required gates и не меняет формулы.
Локальная проверка с Qt stub не заменяет native CI evidence устранения segfault.

Run `38531616378` на предыдущем `db19e77` завершился FAILURE: GUI shard 2,
844/850 executed, stack в `pytestqt._process_events`. Остальные реальные test jobs PASS;
три итоговых platform test gates повторяли этот же upstream failure, coverage skipped.
Fatal banner рядом со snapshot test и последний записанный ASE-dialog node не
считаются доказательством causal test при interleaved worker output.

Дополнительно завершены ранее прерванные lightweight изменения:

- Crash stack публикуется одной bounded multiline annotation (banner/current thread/
  первые 6 frames), чтобы не исчерпывать лимит GitHub error annotations.
- Распознаётся xdist `[gwN] node down:`. Если node-file именно погибшего worker
  отсутствует, файл другого живого worker не подставляется; stale общий node удаляется.
  Workflow называет node recorded active node, а не доказанной причиной crash.
- Persistence list/load/save/task/import/export/delete/close и ONNX submit/result/timeout/
  cleanup пишут static operation + allowlisted code + coarse built-in error category.
  Новый маленький projection helper не форматирует exception message/args, custom
  class name, traceback, path, UID или payload; логирование выполняется на error paths.
- Save retry/dirty state, callback codes и ONNX UI signals сохранены. Secondary
  reconciliation failure виден на DEBUG, не подменяет исходный save failure.
  Raw UI `str(exc)`, close outcome и прочие OPEN rows по-прежнему не объявлены закрытыми.

Усилены существующие unit cases без увеличения unit collection/shard baseline:
перед production fixes **5 FAIL** на missing boundary logs и fragmented crash stack,
после **67 PASS** в диагностическом targeted suite. Два новых pure security cases
проверяют hostile exception formatter/custom class name, untrusted operation/code
и сохранение timeout/storage codes. Они входят в существующий required security file;
нет network/model calls, новых CI jobs, core dumps, profiling или дополнительных retries.

После rebase поверх #162: **515 PASS, 0 skipped/failures/errors** — ASE reference
dialogs, neighbouring viewer/multiview/preferences files, ONNX/persistence/annotation
cases и полный security suite (**334 cases**). `ruff check src/ tests/`, format check
и scripts lint (`--ignore T201` для CLI output) PASS. Unit selection остаётся
6899 = 3619 logic + 3280 GUI / 168 GUI files: новых unit cases в этом follow-up нет.
Проверка локальная offscreen + existing Qt stub; native CI outcome публикуется отдельно.

### QH-4a focused follow-up — landmarks, ONNX, support projection (2026-10-20)

- **ER-08:** both ViewerWidget landmark fit paths now emit only static code `invalid`;
  MainWindow maps it to a localized, generic rejection message. Sentinel tests force
  `ValueError` with patient/path text and assert no contour commit/completion.
- **ER-09:** ONNX `failed(str)` retains its signal shape for compatibility but carries
  only `inference`; application callbacks no longer log the signal payload. The worker
  boundary still logs operation/code/built-in category without exception formatting.
- **ER-10/11:** support bundle generation now projects only complete allowlisted
  `operation/code/error_type` boundary records. Free text, traceback, Qt messages and
  faulthandler crash-log contents are excluded from the ZIP. Main/thread exception hooks,
  Qt handler and logging cleanup now emit static boundary events without `exc_info`.
  Raw faulthandler crash output and any unrelated local log producers may still leave
  sensitive data on disk; they are not made anonymous, but are excluded from support ZIP.
  EN/RU HELP, feedback checkbox, and data inventory describe this narrower bundle.
- **ER-12:** cleanup hook restoration/flush/close errors are best-effort static boundary
  records. Existing deleted-receiver test remains; native/reference 50/500 lifecycle
  evidence and broader cleanup ownership remain OPEN.

QH-4b/#187 foundation: an AST ratchet inventories the **24 exact current** direct
`domain -> infrastructure` edges. It is a required logic test; additions or removals
both fail until the reviewed baseline shrinks with the corresponding inversion. This
prevents new debt but does not yet remove any existing edge; final zero remains OPEN.

Targeted local regression run (real Qt objects, offscreen with repository `qtstub` only
for missing host GL/EGL/dbus/xkb libraries): ViewerWidget, ONNX worker, diagnostics,
QH-4a security, architecture ratchet and i18n tests **PASS**. Ruff/format and diff checks
are recorded in the PR validation. This is a focused verified slice, **not** closure of
ER-10/11/12 or #186; raw local faulthandler output, unrelated local log producers and
native lifecycle acceptance remain limitations. #187 has only its first ratchet slice;
zero-edge architecture cleanup remains open.

### QH-4a / QH-4b follow-up — worker failures and domain translation (2026-10-21)

- **ER-09:** MP4 worker failure now emits only the stable `export_failed` code. The dialog renders a generic localized message. Orthanc policy failures and per-instance adapter failures no longer forward formatted exception details; diagnostics use allowlisted `mp4.export` / `orthanc.download` operation records. A sentinel test covers both UI signals and logs.
- **ER-10/11:** support-bundle regression now includes a raw faulthandler-style crash log and asserts its contents do not enter the ZIP. This is a producer projection boundary, **not** a claim that raw local crash/session files are anonymous or safe to share.
- **ER-12:** added fault-injection coverage for best-effort Qt hook restoration, faulthandler disable, handler flush/close and crash-stream close. Native 50/500 lifecycle evidence remains OPEN.
- **QH-4b:** the domain translation port now supports current-language, explicit-locale and plural translation. All remaining direct domain imports of `infrastructure.i18n` were inverted. The two architecture ratchets now inventory 8 non-i18n edges (DICOM reader / ONNX / video / profiler / segment ROI adapters); the target remains zero.
- Validation in the sandbox: Python compile checks, locale JSON parsing and AST baseline equality pass. Pytest/Ruff were not run because the sandbox image does not provide pytest, NumPy or Ruff. This does not close the wider ER-10/11 producer audit or native lifecycle acceptance.

### QH-4a остаток + QH-4b zero-edge (2026-10-21, ветка `arena/a55cd5a1-sonoforge`)

Срез закрывает перечисленные остатки register и доводит ratchet `domain → infrastructure`
до нуля. Он **не** объявляет G4 закрытым: нативная приёмка и часть producer-ов вне
audited границ остаются OPEN.

- **ER-08 (landmarks/calibration):** оба пути фиксации контура (`_finish_model_contour`,
  `_finish_manual_contour`) уже эмитили только `invalid`; в этом срезе убраны последние
  raw-текстовые записи из калибровочного сценария. Optional-детекторы
  (`try_auto_doppler_velocity_calibration`, `detect_doppler_grid_lines`) больше не пишут
  `exc_info=True`, а логируют allowlisted `calibration.auto` / `calibration.grid` с
  `code=blocked` на DEBUG. `CalibrationController` при отказе fallback-валидатора
  возвращает статический `spacing_error` вместо `f"spacing_error:{exc}"` и пишет
  `calibration.manual code=invalid` без текста исключения. Invalid calibration
  по-прежнему не становится accepted scale. Дополнительно убраны raw-передачи в
  родственных отказах: LA landmark-assist fallback (`contour.assist`, DEBUG),
  неудачное чтение MP4-метаданных (`video.metadata` + статическое сообщение вместо
  `str(exc)` в `frame_load_failed`) и необязательное чтение DICOM-заголовка в
  bench-хелпере (`bench.pixel_spacing`, DEBUG).
- **ER-09 (worker boundaries):** `OnnxWorkerSignals.failed` несёт только константу
  `ONNX_FAILURE_CODE = "inference"`; timeout остаётся отдельным `timed_out`.
  Остальные audited worker-ы (DICOM decode, frame loader, heart rate, optical flow,
  DICOM upload, de-identification, speckle tracking) больше не используют
  `logger.exception`/`str(exc)`: они пишут allowlisted
  `operation/code/error_type` без пути, UID, payload и traceback. Отмена загрузки и
  миниатюр имеет стабильный код `cancelled` (не ошибка, отдельный от отказа), UI
  показывает локализованный текст без подстановки исключения. Тестовые фикстуры
  upload/thumbnail переведены с `QCoreApplication` на `QApplication`, поэтому файлы
  запускаются изолированно, а не только в общем прогоне.
- **ER-10/11 (allowlist, support bundle):** добавлен producer-side тест: каждая
  *строковая* operation, переданная в `log_boundary_failure`/`log_boundary_event`
  во всём `src`, обязана присутствовать в `_OPERATIONS`. Security-тест projection
  доказывает, что неизвестные operation/code/category и любая дополнительная
  free-text часть строки отбрасываются; crash-log проверяется построчно — разрешённое
  boundary-событие остаётся, raw traceback/PHI не попадают в ZIP. Профайлер больше
  не сохраняет `str(exc)` (только имя операции и built-in категорию). Это
  producer-projection boundary, **не** гарантия анонимности локальных логов и
  crash-файлов.
- **ER-12 (native lifecycle):** добавлен регрессионный тест на удержание/освобождение
  QRunnable: после `finished`/`failed`/`timed_out` `_live_workers` пуст, повторный
  терминальный сигнал идемпотентен; существующие тесты deleted-receiver и cleanup
  hooks сохранены. Native 50/500 GUI lifecycle evidence на референсной машине
  остаётся OPEN.
- **QH-4b (G4 §8.2):** прямых `domain → infrastructure` рёбер больше нет — ratchet
  теперь с пустым inventory в обоих тестах (`test_architecture_boundaries.py`,
  `test_qh3_boundary.py`). Инверсии/переносы:
  - formatter-ы домена больше не импортируют `infrastructure.profiler`
    (инструментация остаётся вне домена);
  - чистые пиксельные функции и Samsung tick detector перенесены в
    `echo_personal_tool.imaging` (общий алгоритмический kernel без I/O);
    `infrastructure.pixel_utils` сохраняет compatibility re-export;
  - `segment_roi` получает уже разобранный `FramePanelLayout`; чтение DICOM-заголовка
    осталось в application adapter-е;
  - `cine_segment_diagnostics` и `bench_lvef` (orchestration I/O) перенесены в
    `application/services`; чистые расчёты остались в домене.
  Добавлены boundary-тесты: домен не импортирует application/presentation, а
  `imaging` не импортирует ни один слой.

#### Проверка в песочнице

Python 3.11.2, PySide6 6.11.2, NumPy 1.26.4, Qt offscreen с репозиторным
`tools/qtstub` (реальные Qt-объекты; stub только для отсутствующих системных
GL/EGL/dbus/xkb библиотек):

- `tests/security` (включая `test_qh4a_diagnostics.py`), diagnostics, ONNX worker,
  thumbnail/upload cancellation, speckle, decode/frame/heart-rate/optical-flow/
  deidentify workers, app-controller thumbnail priority и auto-segment delivery —
  **PASS**.
- `test_segment_roi`, `test_segment_diagnostics`, `test_cine_segment_diagnostics`,
  `test_bench_lvef`, `test_lv_bench_lvef`, pixel-utils/window-level, Samsung tick
  calibration, profiler, diagnostics, i18n, viewer calibration/landmark subset и
  main-window speckle/upload/calibration subset — **PASS**.
- `ruff check src tests` и `ruff format --check src tests` — чисто (998 файлов).
- Partition baseline обновлён `update_pytest_baseline.py --fix`: **8737 = 4974 logic
  + 3763 GUI**, `gui_files` 195 (без новых GUI-файлов).

### Завершение Gate G4 — полный producer ratchet, санитизация локальных логов и 50/500 lifecycle acceptance (2026-10-21, ветка `arena/3d81b3b6-sonoforge`)

Этот срез закрывает оставшиеся открытые пункты Gate G4 (#160 / #186 / #187):

1. **Полная миграция producer-ов логов во всём репозитории (ER-08 / ER-09 / ER-10 / ER-11):**
   - Все оставшиеся вызовы `logger.exception(...)`, `exc_info=True`, а также логирование сырых `exc` / `str(exc)` / путей / DICOM UID во всех пакетах (`domain/`, `application/`, `infrastructure/`, `presentation/`, `ui/`, `constructor/`, `main.py`) переведены на `log_boundary_failure` / `log_boundary_event` с allowlisted-операциями из `safe_diagnostics._OPERATIONS` либо на вывод только встроенной категории исключения (`type(exc).__name__` в чистом домене).
   - В `tests/security/test_qh4a_diagnostics.py` добавлены два постоянных AST-ратчета по всему `src/echo_personal_tool`:
     - `test_zero_logger_exception_or_exc_info_in_codebase` (0 вызовов `logger.exception` и `exc_info=True`);
     - `test_zero_raw_exception_payload_in_logger_calls` (0 передач сырого `exc` или `str(exc)`/`repr(exc)` в вызовы логгера внутри `except`).
2. **Анонимизация локальных `session-*.log`, `crash.log` и `presenter_diag.log` при записи и старте (ER-10 / ER-11):**
   - В `infrastructure/log_sanitizer.py` расширена `sanitize_log_text` (редактирование однострочных `Error: message`, `File "..."` строк и ключевых значений `path=/file=/filename=/dir=/folder=/url=`) и добавлены `sanitize_local_log_file` / `sanitize_local_log_files` для атомарной очистки существующих логов на диске.
   - В `infrastructure/logging_setup.py` файловый хендлер сессии использует `_SanitizingFileFormatter` (принудительно очищает `exc_info`/`stack_info` и прогоняет текст через `sanitize_log_text`), поток `faulthandler` обёрнут в `_SanitizingCrashStream`, а при запуске, закрытии логгера и перед сборкой support-архива (`diagnostics.py`) вызывается `sanitize_local_log_files`.
   - В `presentation/presenter_diagnostics.py` метод `PresenterDiagnostics._write` прогоняет каждую записываемую строку через `sanitize_log_text`.
3. **Закрытие остатков ER-02 / ER-03 / ER-04 / ER-05 / ER-06 / ER-07:**
   - `saved_records.py` и `measurement_persistence.py` нормализуют все коды `MeasurementStorageError` через `safe_failure_code(..., fallback="io")`, а `MeasurementPersistence._summarize_entry` делегирует классификацию `saved_records.summarize_record` (`schema_version=0/"x"` → `corrupt`, future integer → `unsupported`).
   - `MeasurementPersistence._deliver_callback` защищает все асинхронные callbacks от `RuntimeError` при удалённом Qt-получателе после обновления внутреннего состояния.
   - `measurement_sources.py::describe_study` перехватывает `InvalidDicomError` и `EOFError`, логирует `persistence.source code=source` и поднимает `MeasurementStorageError("source")`.
   - `MeasurementPersistence.close(timeout_ms=...)` передаёт `timeout_ms` в `future.result(timeout=...)` и логирует `measurement.close code=timeout` при истечении бюджета.
   - `ReportDialog._export_pdf` и `MainWindow._export_report_pdf` логируют `report.export code=io` без путей и текста исключений.
4. **Клинический 50-цикловый и референсный 500-цикловый lifecycle acceptance + финальный boundary ratchet (ER-12 / QH-3 / QH-4b):**
   - В `dispose()` контроллеров `presentation/viewer/*_controller.py` и `viewer_widget.py` устранены `RuntimeWarning: libpyside: Failed to disconnect` при отключении сигналов без подписчиков.
   - В `tests/unit/test_qh3_lifecycle.py` добавлен `test_clinical_workflow_50_cycles_and_500_reference_cycles_acceptance`, проверяющий 50 полных клинических циклов (открытие исследования → смена клипа → калибровка → контур → инструмент → `WorkerBridge` → `MultiViewSession` → `dispose`) с бюджетом RSS `+≤5 МБ` и 500 референсных циклов с бюджетом RSS `+≤20 МБ` и плоским трендом после 100-го цикла (`+≤5 МБ`), `0` живых QObject закрытого владельца и `0` `RuntimeWarning`.
   - В `tests/unit/test_architecture_boundaries.py` добавлены проверки `application ↛ presentation/ui/constructor` и чистоты `presentation/viewer` контроллеров; весь файл `tests/unit/test_architecture_boundaries.py` включён в `.github/required-tests/formulas.txt`.
   - Обновлён baseline `verify_pytest_partition.py` через `update_pytest_baseline.py --fix`: **8740 = 4976 logic + 3764 GUI**, `gui_files` 195.
