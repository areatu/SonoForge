# Сверка #160 с error-register и оставшимися гейтами

> **Снимок на 2026-11-06.** Документ фиксирует состояние на эту дату и не обновляется вслед за кодом:
> актуальное состояние — в коде, `README.md`, HELP и открытых issues.
> Issue: [#160](https://github.com/areatu/SonoForge/issues/160). Реестр, с которым идёт сверка:
> `docs/reviews/2026-10-14-qh-4a-error-register-ru.md` (снимок 2026-10-14).

## 1. Зачем эта сверка

Чеклист #160 не обновлялся с 2026-10-14: с тех пор закрыты QH-1b.2 (#175), QH-4b (#187),
QH-5a (#188), QH-2b.2 (#183), QH-3.1/QH-3.2 (#184/#185), QH-4a (#186), а строки ER-03…ER-12 в реестре
переведены в `FIXED-SLICE`. Незакрытые галочки в #160 при этом создают ложную картину «шестнадцать
открытых работ», хотя код этих работ в `main` есть.

Проверялось не «доверие документу», а три вещи по каждой строке:

1. **Существует ли код**, на который ссылается строка, и ведёт ли он себя так, как описано.
2. **Существуют ли процитированные тесты** и проходят ли они сейчас.
3. **Не устарели ли имена** — часть функций за месяц переехала или исчезла вместе с legacy-путём.

Статусы issues и PR получены через `gh` на 2026-11-06. Тесты прогнаны локально (Python 3.11, offscreen);
полный прогон — в CI этого PR.

## 2. Строки ER-03…ER-12: что в коде сейчас

| Строка #160 | Что в реестре | Что в коде на 2026-11-06 | Тесты (прогнаны) | Вердикт |
|---|---|---|---|---|
| **ER-03/04** — нормализация кодов на всех границах persistence + «свернуть дублирующий legacy listing DTO/API» | `measurement_persistence.list_record_summaries/_summarize_entry` делегирует `saved_records.summarize_record` | `list_saved_records` — **единственный** API списка и он делегирует `application/saved_records.read_saved_records` → `summarize_record`; legacy `_summarize_entry`/`list_record_summaries` **удалены** (0 вхождений в `src` и `tests`). `safe_failure_code(..., fallback="io")` на `_submit`/`_complete`/`save_pending`/import-preview/import; `_deliver_callback` ловит `RuntimeError` удалённого Qt-получателя → `ui.cleanup code=cleanup` | `security/test_qh4a_diagnostics.py::test_saved_records_normalizes_unknown_storage_error_codes`, `::test_measurement_persistence_survives_deleted_qt_receiver_callback`; `unit/test_saved_records_listing.py` (9), `unit/test_measurement_persistence_disk.py` (47) | **Закрыто**, причём сильнее формулировки: дубль не «нормализован», а удалён |
| **ER-05** — отличать настоящий I/O-сбой от несовпадения источника | `measurement_sources.describe_study` | `describe_study`: `InvalidDicomError`/`EOFError` → `log_boundary_failure(..., "persistence.source", code="source")` → `MeasurementStorageError("source")`; несовпадение UID → `"identity"`; `path is None` → `"source"`. Ни путей, ни `str(exc)` в лог | `security/…::test_describe_study_maps_corrupt_dicom_and_eof_to_source_error`, `unit/test_measurement_persistence_disk.py::test_source_mismatch_blocks_restore_and_overwrite` | **Закрыто**, код на месте |
| **ER-06** — провал shutdown — отдельный результат, а не безусловный `True` | `measurement_persistence.close` | `close(timeout_ms=2000)`: сначала `flush`, затем `future.result(timeout=max(0.001, timeout_ms/1000))`; при `CancelledError/OSError/RuntimeError/TimeoutError` → `closed=False`, `measurement.close code=timeout|io`, executor останавливается в `finally` | `security/…::test_measurement_persistence_close_respects_timeout_ms` | **Закрыто**, код на месте |
| **ER-07** — `PdfExportError`, локализованный сбой, никакого частичного файла | `presentation/report_dialog.py::ReportDialog._export_pdf` → `infrastructure/measurement_report_pdf.py` | **Имя устарело**: `presentation/report_dialog.py` больше нет. Цепочка сегодня: `MainWindow._export_report_pdf` → `presentation/report_mode/export_job.ReportPdfExportJob` (worker + отмена, S3-04/#313) → `application/report_export.py` (`ReportExportError`, code `pdf_export_failed`, `raise … from None`) → `infrastructure/measurement_report_pdf.py` (`tempfile.mkstemp` + `os.replace`, `PdfExportError("pdf_export_failed")`) | `unit/test_measurement_report_pdf.py` (9), `security/…::test_report_export_pdf_boundary_failure_does_not_leak_path` | **Закрыто**, но ссылка в реестре и в #160 указывает на несуществующий модуль — исправить на новую цепочку |
| **ER-08** — стабильные коды на отказах калибровки и ориентиров | `viewer_widget._finish_model_contour`, `_handle_doppler_calibration_click`, `viewer/calibration_controller.py` | `_finish_model_contour` на обоих путях отказа эмитирует `contour_landmark_rejected.emit("invalid")` (строки ~5606 и ~5668); `calibration.auto`/`calibration.grid` → `code="blocked"`; `calibration.manual` → `code="invalid"`. `exc_info` и `str(exc)` нет | `security/…::test_boundary_projection_covers_manual_calibration_rejection`, `unit/test_doppler_calibration.py` | **Закрыто**, код на месте |
| **ER-09** — воркеры не пробрасывают сырой `str(exc)` | все producer-модули | `grep -rn 'logger.exception\|exc_info=True' src/echo_personal_tool` → **0**; AST-ратчеты обходят весь `src` и падают на любом новом `logger.exception`, `exc_info=True` или передаче `exc`/`str(exc)` в логгер | `security/…::test_zero_logger_exception_or_exc_info_in_codebase`, `::test_zero_raw_exception_payload_in_logger_calls` (файл: 32 теста) | **Закрыто и защищено ратчетом** |
| **ER-10/11** — allowlisted producer-логи, очистка локальных логов | `log_sanitizer.py`, `diagnostics.py`, `safe_diagnostics.py`, `logging_setup.py`, `presenter_diagnostics.py` | Все модули на месте. `_SanitizingFileFormatter` сбрасывает `exc_info`/`stack_info` и прогоняет текст через `sanitize_log_text`; `faulthandler` пишет через `_SanitizingCrashStream` + `sanitize_local_log_files` при старте и закрытии; `PresenterDiagnostics._write` очищает каждую строку | `security/…::test_local_session_and_crash_logs_are_sanitized_at_write_time`, `::test_presenter_diagnostics_log_is_sanitized_at_write_time`, `unit/test_log_sanitizer.py`, `unit/test_diagnostics.py`, `unit/test_logging_setup.py` | **Закрыто как срез кода.** Оговорка реестра остаётся верной и должна жить в #160 одной строкой: это проекция на границе продюсера, а не анонимизация произвольного свободного текста |
| **ER-12** — cleanup удалённых получателей, lifecycle | `viewer/*_controller.py`, `measurement_persistence.py` | Идемпотентный `dispose()` есть у всех девяти владельцев (`overlay_controller` ×4, `magnifier`, `tool`, `contour`, `calibration`, `worker_bridge`); 50-цикловый клинический и 500-цикловый референсный сценарии проверяют бюджеты RSS, 0 живых QObject закрытого владельца, плоский тренд после 100 цикла и отсутствие `RuntimeWarning` | `unit/test_qh3_lifecycle.py` (5 passed, включая `test_clinical_workflow_50_cycles_and_500_reference_cycles_acceptance`), `unit/test_qh0_lifecycle_baseline.py` | **Закрыто как срез кода.** Нативного (Windows/macOS) прогона этого harness нет — это остаётся ограничением, а не «недоделанным кодом» |

## 3. «Remaining planned packages»: что из списка уже сделано

| Строка #160 | Факт на 2026-11-06 | Вердикт |
|---|---|---|
| **QH-1b.2** production invalidation/projection | Issue **#175 закрыт** 2026-10-20; производственная freshness-проекция живёт в `domain/models/result_provenance.py`, `application/study_measurement_session.py`; S-03 в матрице G1 — PASS | **Сделано**, строку в #160 снять |
| **QH-1c** import preview / hash remap / fault matrix | Код есть: `ImportPreview`, `infrastructure/measurement_remap.prepare_import`, directory fsync-after-replace, fault matrix, ENOSPC-harness. Нативный disk-full на Windows/macOS — **PASS** (run `42062351545`, `docs/reviews/2026-11-05-g1-s-invariant-matrix-ru.md` §6). PR #267 смержен | **Сделано**; остаются пункты владельца: ручной чеклист §8.2 и решение «входят ли они в G1» (issue #176 остаётся открытым именно поэтому) |
| **QH-1d** persistent manual calculator inputs | `CalculatorInputStore.restore_manual`, allowlisted `manual_calculator_inputs` в codec, восстановление после перезапуска | **Сделано**, строку снять |
| **QH-2b** client/settings/migration + TLS/DIMSE | QH-2b.1 (#182) и QH-2b.2 (**#183**) закрыты; enforcement и миграция профилей — `security/test_https_enforcement.py::TestProfileMigrationAndScopeInvalidation`, настоящий TLS-сокет — `::TestHttpsRealTlsSocketService`, DIMSE TLS — `infrastructure/dimse_client.py` (`use_tls`, `tls_verify`, `tls_ca_path`) + `unit/test_dimse_client*.py`, привязка SCP — `security/test_scp_bind_policy.py` | **Сделано**, строку снять |
| **QH-2a** governance/rulesets | Issue **#181** открыт, `status:blocked` — подтверждение администратором | **Внешняя блокировка**, оставить |
| **QH-3** decomposition / native lifecycle | QH-3.1 (#184) и QH-3.2 (#185) закрыты; остаток ведётся в **#420**: инвентаризация (PR #450), владелец лупы (PR #455); осталось три среза (см. `docs/reviews/2026-11-06-qh3-magnifier-owner-ru.md` §5) | **В работе**, оставить со ссылкой на #420 |
| **QH-4b** architecture ratchet / zero `domain→infrastructure` | Issue **#187 закрыт**; `scripts/check_layer_directions.py`: 29 отревьюенных запрещённых импортов в 25 рёбрах, 3 запрещённых направления, «no new, grown or stale edge» | **Сделано**, строку снять |
| **QH-5a** locked package matrix / clean-machine evidence | Issue **#188 закрыт** 2026-10-22; `.github/package-matrix.yml` — единственная декларация релиза, читается `tools/release/package_matrix.py`, проверяется `verify_release.py` и `unit/test_release_package_matrix.py` (69 тестов). **Объявленные пробелы** (`gaps`, никогда не пусты): bootstrap зависимостей lite-`.deb` в CI не исполняется; ручная USB-приёмка Presenter'а; подпись кода (=#189); клиническая приёмка | **Сделано с честно объявленными пробелами**; строку заменить на «пробелы matrix» |
| **G1-STE** | Issue **#179** открыт, `status:blocked` — нужны same-frame gold и определения вендора | **Внешняя блокировка** |
| **QH-5b** signing/notarization | Issue **#189** открыт, `status:blocked` | **Внешняя блокировка** |

## 4. Что именно устарело в #160

1. Восемь строк `ER-03…ER-12` помечены `[ ]`, хотя реестр держит их `FIXED-SLICE` с тестами, а тесты
   проходят. Галочки не проставлены ни разу с 2026-10-14.
2. `ER-07` ссылается на `presentation/report_dialog.py` — модуля нет; цепочка экспорта теперь
   worker → `application/report_export.py` → `infrastructure/measurement_report_pdf.py`.
3. `ER-03` описывает «дублирующий legacy listing», которого больше нет: остался один
   `list_saved_records` → `saved_records.read_saved_records`.
4. Четыре строки раздела «Remaining planned packages» (QH-1b.2, QH-1d, QH-2b, QH-4b) и QH-5a закрыты
   issues/PR'ами; строка QH-1c верна только в части, касающейся владельца, а не кода.
5. Строки QH-3 и QH-2a нужно переписать как ссылки на живые трекеры (#420, #181), иначе создаётся
   впечатление отдельной неучтённой работы.

### 4.1 Готовый чеклист для тела #160

Бот не имеет прав `issues: write`, поэтому тело трекера правит владелец. Ниже — текст, который можно
вставить как есть (он же — предлагаемая замена раздела «OPEN targeted QH-4a rows» и «Remaining planned
packages»).

```markdown
### QH-4a строки реестра — закрыты, проверено 2026-11-06
- [x] ER-03/04 — единая проекция списка (list_saved_records → saved_records.read_saved_records);
      legacy _summarize_entry/list_record_summaries удалены; safe_failure_code(..., "io") на границах
      _submit/_complete/save_pending/import; _deliver_callback ловит удалённого Qt-получателя.
- [x] ER-05 — describe_study отличает I/O-сбой (source) от несовпадения источника (identity).
- [x] ER-06 — close(timeout_ms) возвращает False при таймауте/ошибке, measurement.close code=timeout|io.
- [x] ER-07 — ссылка устарела: report_dialog.py нет; цепочка MainWindow._export_report_pdf →
      report_mode/export_job → application/report_export.py → infrastructure/measurement_report_pdf.py.
- [x] ER-08 — contour_landmark_rejected("invalid"), calibration.auto|grid code=blocked.
- [x] ER-09 — 0 logger.exception/exc_info=True в src; защищено AST-ратчетами.
- [x] ER-10/11 — очистка при записи; оговорка остаётся: проекция, а не анонимизация произвольного текста.
- [x] ER-12 — dispose() у всех девяти владельцев; 50/500 harness зелёный; нативного прогона нет.

### Remaining planned packages — сделано
- [x] QH-1b.2 (#175 закрыт) · [x] QH-1c код + нативный disk-full (run 42062351545) · [x] QH-1d
- [x] QH-2b (#182/#183) · [x] QH-4b (#187) · [x] QH-5a (#188, пробелы объявлены в package-matrix.yml)

### Остаётся открытым — решения владельца и внешние условия
- [ ] #176 (G1): owner-run §8.2, решение «входит ли в G1», решение по S-02.
- [ ] #420 (QH-3): _controller_ref → провайдеры, мёртвые владельцы, дубль позиции оверлея.
- [ ] #181 (QH-2a policy) · [ ] #179 (QH-1e-STE) · [ ] #189 (QH-5b).
- [ ] Пробелы QH-5a: bootstrap lite-.deb, ручная USB-приёмка Presenter'а.
```

## 5. Доказательства прогонов

Локально (Python 3.11, offscreen, 2026-11-06), команда — 16 файлов, перечисленных в таблицах выше:

```
pytest tests/security/test_qh4a_diagnostics.py tests/security/test_https_enforcement.py \
       tests/security/test_transport_policy.py tests/security/test_scp_bind_policy.py \
       tests/unit/test_log_sanitizer.py tests/unit/test_diagnostics.py tests/unit/test_logging_setup.py \
       tests/unit/test_saved_records_listing.py tests/unit/test_measurement_persistence_disk.py \
       tests/unit/test_measurement_repository.py tests/unit/test_measurement_report_pdf.py \
       tests/unit/test_doppler_calibration.py tests/unit/test_calculator_inputs.py \
       tests/unit/test_qh0_lifecycle_baseline.py tests/unit/test_release_package_matrix.py
→ 466 passed, 0 failed
pytest tests/unit/test_qh3_lifecycle.py → 5 passed
```

Размеры ключевых файлов (collect-only): `test_qh4a_diagnostics.py` — 32, `test_https_enforcement.py` — 52,
`test_measurement_repository.py` — 59, `test_measurement_persistence_disk.py` — 47,
`test_release_package_matrix.py` — 69, `test_calculator_inputs.py` — 15, `test_qh3_lifecycle.py` — 5.

Дополнительно проверено кодом, без тестов: `grep` по `src/echo_personal_tool` даёт 0 вхождений
`logger.exception` и `exc_info=True`; `scripts/check_layer_directions.py` — «no new, grown or stale edge»;
в `tests` и `src` нет `_summarize_entry`/`list_record_summaries`.

## 6. Что остаётся открытым по факту (и почему это не «сделать код»)

- **#176 / G1**: owner-run пункты чеклиста §8.2 (C1/C2, D1–D3, E1–E3, F1–F5), решение «входят ли они
  в G1» и решение по S-02 (восстанавливать ли ручную калибровку при возврате на вкладку) — за владельцем.
- **#179** (STE gold), **#181** (policy администратора), **#189** (подпись кода), **#418** (данные и
  независимые оценщики), **#421** (владелец GPG-ключа) — внешние условия.
- **#420** — остаток QH-3: `_controller_ref` → узкие провайдеры; мёртвые владельцы; дубль позиции
  оверлея результатов.
- **Пробелы QH-5a**, объявленные в matrix: bootstrap `.deb`, ручная USB-приёмка Presenter'а.
- **Ограничения, которые нельзя закрыть тестами**: нативный (Windows/macOS) lifecycle-прогон ER-12;
  анонимизация произвольного свободного текста в локальных логах (ER-10/11 — проекция, не анонимизация).

## 7. Ограничения этой сверки

- Проверялось соответствие **заявлений реестра** коду и тестам, а не полнота самого реестра: новых
  операций и новых `except`-границ сверка не ищет (это работа аудита, а не трекера).
- Тесты выполнены на offscreen-платформе; те же файлы входят в обязательные CI-джобы `test-security`,
  `test-logic` и `test-gui`, поэтому их прохождение на PR и есть подтверждение для `main`.
- Строки реестра 2026-10-14 не переписаны: он остаётся снимком. Устаревшие имена зафиксированы здесь и
  в #160, чтобы не переписывать историю задним числом.
