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
| **ER-02 T VERIFIED-SLICE** | `application/saved_records.py::read_saved_records/_read_one/summarize_record` + `MeasurementPersistence.list_saved_records` — list/load summaries | `OSError`, `MeasurementStorageError`, unexpected codec boundary exception | Typed frozen listing различает failed vs empty; corrupt/unsupported/unavailable сосед не скрывает readable; closed API даёт `io` | Не возвращать `[]` как success при отказе. Переносить защиту и на legacy API (ER-03); arbitrary injected code не является approved diagnostic | `unit/test_saved_records_listing.py::test_listing_failure_is_not_an_empty_store`, `::test_corrupt_neighbour_does_not_hide_a_readable_record`, `::test_persistence_api_reports_a_failed_listing_instead_of_an_empty_one`; `unit/test_measurement_storage_dialog.py::test_manager_failed_listing_is_not_an_empty_store` |
| **ER-03 T/P OPEN** | `application/measurement_persistence.py::list_record_summaries/_summarize_entry` — legacy parallel listing | `OSError`, `MeasurementStorageError`; programming `AttributeError/TypeError` | Вторые DTO и путь декодирования рядом с canonical `saved_records`; raw `exc.code`/type попадает в warning и `list_error`; `read_bytes()` вместо canonical bounded read | Consolidate/retire legacy API отдельно с проверкой callers; allowlist codes/types, bounded reader. Не добавлять новый store или общий catch→empty | Существующие `unit/test_measurement_persistence_disk.py::test_list_record_summaries_list_error_distinct_from_empty`, `::test_list_record_summaries_classifies_corrupt_and_unsupported_neighbours` не закрывают arbitrary-code/bounds. Нужны sentinel + oversized read tests; #160 ER-03 |
| **ER-04 T OPEN** | `application/measurement_persistence.py::_submit/_complete/save_pending` — asynchronous failure delivery | Storage codes, I/O; catch-all future boundary | Неожиданное исключение → `io`, callback доставляется в owner Qt thread, без traceback; однако storage code и dynamic class name не нормализованы allowlist | Approved error category/code + operation; no raw payload/type identifiers. Сохранять dirty/retry и не подавлять callback failure как success | Failed-save tests ER-01 — evidence только dirty/retry. Нужны PHI sentinel exception/code + late/deleted callback tests; #160 ER-04 |
| **ER-05 T OPEN** | `application/measurement_persistence.py::load` + `infrastructure/measurement_sources.py::describe_study` — identity/restore | Storage `source/identity/version`, `OSError`, `ValueError` fingerprint/metadata | Source mismatch blocks restore/overwrite, partial сохраняет unavailable часть. Но non-storage `OSError` и `ValueError` оба становятся `source` | Отличать unavailable I/O от доказанного identity mismatch; нельзя снимать identity checks ради restore. Типизированные independent outcomes | `unit/test_measurement_persistence_disk.py::test_source_mismatch_blocks_restore_and_overwrite`, `::test_partial_projection_preserves_unavailable_measurements`; `unit/test_measurement_repository.py::test_corrupt_or_future_record_never_overwritten`; добавить I/O-vs-source classification fault test; #160 ER-05 |
| **ER-06 T OPEN** | `application/measurement_persistence.py::close`, `save_pending` reconciliation cleanup | `TimeoutError`, executor `RuntimeError`, repository `OSError`/storage error | close сначала flush; после repository-close exception логирует type и всё равно True. Read-back после save failure имеет justified `pass`: сохраняет исходный failure/dirty, не claims success | Shutdown outcome должен отличать flush success от cleanup timeout/failure. Для narrow reconciliation `pass` сохранить rationale: secondary read failure не должен заменить исходную ошибку. Native owner lifecycle evidence отдельно | `unit/test_measurement_persistence_disk.py::test_failed_save_keeps_dirty_snapshot_and_retry` проверяет flush, не failed close. Нужны close failure/time budget/resource test; #160 ER-06 |
| **ER-07 P/T OPEN** | `presentation/report_dialog.py::ReportDialog._export_pdf` → `infrastructure/measurement_report_pdf.py::export_report_document_pdf/_register_cyrillic_font` — report export | `PdfExportError`, `OSError`, font/render errors | Dialog ловит только PdfExportError; missing font обёрнут, но mkdir/write/render exceptions могут выйти наружу. `str(PdfExportError)` показан UI; output открывается после возврата exporter | Все expected export failures → safe typed code/localized text; partial file не открывать как finished report. Не blanket catch в каждом renderer | `unit/test_measurement_report_pdf.py`, `unit/test_qh1e_formulas.py::test_disk_restore_text_document_and_real_pdf_rounding` — success/rounding, **не** отказ записи. Нужны denied path/font/render fault tests и assertion 0 openUrl; #160 ER-07 |
| **ER-08 P/T OPEN** | `presentation/viewer_widget.py::_finish_model_contour`, `_handle_doppler_calibration_click` — landmarks/calibration | `ValueError` geometry; expected calibration no-candidate; optional boundary unexpected exception | Landmark failure → rejection signal/False (не contour completion), но raw str(exc); auto velocity/grid detection catch-all с debug traceback | Stable rejection codes; invalid calibration не становится accepted scale. Optional fallback допустим, traceback не считать sanitized; no algorithm change при переносе handler | `unit/test_doppler_calibration.py` — calibration semantics, не PHI boundary. Нужны rejected signal/no commit/sentinel tests на exact handlers; #160 ER-08 |

## 3. Workers / diagnostics / optional cleanup (второй приоритет)

| ID / owner / статус | Место / operation | Ожидаемые exceptions | Текущая реакция / последствия | Целевая реакция / evidence |
|---|---|---|---|---|
| **ER-09 T/P OPEN** | `application/workers/onnx_worker.py::OnnxWorker.run` — pool submit/result | Model/inference/I/O failure, `ValueError` bad mask shape, pool `RuntimeError`; timeout — отдельный timed_out signal | Catch-all на worker boundary оправдан: failure доставлен UI, success signal не выдаётся. Но failed.emit(str(exc)) может содержать path/payload/секрет | Safe operation/code/type, failure и timeout остаются отличимы; correlation ID не source identity. `unit/test_onnx_worker.py::test_worker_emits_failed_on_exception`, `::test_worker_emits_timed_out` проверяют доставку, не anonymisation. Нужны sentinel + closed owner/generation tests; #160 ER-09 |
| **ER-10 T FIXED-SLICE / OPEN producer** | `infrastructure/log_sanitizer.py::sanitize_log_text`, `diagnostics.py::create_diagnostic_bundle` — support ZIP | `OSError` reading log (skip one file), failure writing ZIP (не catch→success) | Sanitizer пропускал JSON/repr quoted PHI keys, password/Authorization/API key и label/payload fields; **9 FAIL из 13 новых tests** до fix. Добавлен structured field filtering, имена источников не копируются, symlink не читается | `security/test_qh4a_diagnostics.py`: 13 cases, реальный ZIP writer, complete UID/name/ID/path/auth/password/label/payload sentinels; `unit/test_diagnostics.py` сохраняет прежние contracts. Новый файл required в `security.txt`. Это **не** разрешение публиковать любой log: nested/free text/raw exceptions остаются OPEN; #160 ER-10 |
| **ER-11 T/R OPEN** | `infrastructure/logging_setup.py::_install_exception_hooks/_install_qt_message_handler`, `diagnostics.py::create_diagnostic_bundle` — raw logs/crash dump | Main/thread unexpected exception, Qt message; native crash | Hooks пишут raw traceback и Qt message; faulthandler crash*.log + session logs включаются в ZIP через regex sanitizer. Raw log/crash не объявляется обезличенным, маскировка известных полей не proof для произвольного текста | Producer allowlist / безопасная отдельная diagnostic projection; явная user review policy. Crash dumps отдельно потенциально чувствительны. `unit/test_diagnostics.py::test_configure_logging_creates_unique_rotating_session_file` проверяет logging lifecycle, не отсутствие PHI; #160 ER-11 |
| **ER-12 T VERIFIED-SLICE / OPEN native** | `presentation/measurement_storage_dialog.py` async callbacks; `logging_setup.py::_shutdown_logging` — deleted receiver / cleanup | Expected deleted Qt `RuntimeError`, `ImportError` optional hook, stream `OSError/ValueError` | Closed dialog callback не обращается к widget; hook cleanup narrow best effort, часть debug handlers всё ещё с traceback | Quiet/debug допустим при сохранённом failure-state, narrow documented exception, 0 late widget use. `unit/test_measurement_storage_dialog.py::test_callback_after_close_never_touches_widgets`, `unit/test_diagnostics.py::test_configure_logging_creates_unique_rotating_session_file`; native/reference 50/500 lifecycle и raw cleanup diagnostic policy остаются #160 ER-12 |

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
