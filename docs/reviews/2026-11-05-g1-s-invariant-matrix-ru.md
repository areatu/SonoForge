# G1 data safety: матрица S-01…S-12 и решение по power-loss (2026-11-05)

**Связанные issues:** #176 (QH-1c), G1 из `docs/superpowers/specs/2026-10-13-quality-safety-hardening-spec-plan-ru.md`.
**Код под проверкой:** дерево `2908112` (поведение продукта); этот документ добавлен в `90fef74` и кода не меняет.
**Замена:** §5 `docs/reviews/2026-10-13-quality-safety-baseline-ru.md` устарела, см. раздел 4.

## 1. Решение по scope G1

Владелец решил 2026-11-05: **power-loss не входит в G1**.

G1 закрывается как **«data safety без устойчивости к отключению питания»**. Это означает:

- Проверяется: сохранённые ревизии не теряются при ошибках записи, delete/reset/import не воскресают, частичный restore не уничтожает недоступные данные, отказы честно видны пользователю.
- **Не проверяется и не заявляется:** сохранность данных при внезапном отключении питания ОС или оборудования, сброс write-cache хоста, поведение конкретной ФС при потере питания.
- Доказательства, которые **не** являются power-loss evidence: `taskkill /F` и падение процесса, tmpfs ENOSPC, unit-тесты порядка `fsync → replace → directory fsync`. Порядок вызовов в коде — не доказательство долговечности.
- Устойчивость к отключению питания — отдельный будущий gate с собственным протоколом (VM hard-stop на стенде владельца). Пока его нет, он не заявляется ни в одном документе как PASS.

## 2. Как получена матрица

- Тестовые ID взяты из кода, а не из старой таблицы. Каждый ID проверен через `pytest --collect-only`: все 56 записей собираются.
- Прогон локально: Linux sandbox, `QT_QPA_PLATFORM=offscreen`, системные GL/dbus-библиотеки заменены заглушками `/home/user/stublibs`. Это **не нативная GUI-приёмка**.
- Результаты:
  - S-набор (`tests/unit`, 56 записей, 337 тестов после развёртывания файловых ID): **337 passed, 0 failed, 0 skipped**.
  - `tests/security/`: **410 passed, 0 failed, 0 skipped**.
  - Дополнительные ID (S-09, S-11): **46 passed, 0 failed, 0 skipped**.
- **CI на ветке `arena/83d9286f-sonoforge` не запускался** (по `gh run list` для `ci.yml` записей нет; запущен только `native-disk-full`). Поэтому колонка «CI job» показывает, где тест выполняется в CI по разбиению, а не прохождение в CI.

## 3. Матрица S-01…S-12

Статусы: **PASS** — тест есть, выполняется локально, не пустой. **PARTIAL** — есть, но покрывает часть инварианта; пробел записан.

| ID | Инвариант | Тестовые ID (фактические) | CI job (по разбиению) | Локально | Статус и оговорки |
|---|---|---|---|---|---|
| S-01 Identity | Связь с проверенными study/source/frame, не с путём или вкладкой | `tests/unit/test_measurement_sources.py::test_dicom_relocation_stable_and_wrong_study_rejected`, `::test_same_uid_changed_geometry_fingerprint_differs`, `::test_non_dicom_replacement_under_same_name_detected`; `tests/unit/test_measurement_persistence_disk.py::test_source_mismatch_blocks_restore_and_overwrite` | test-logic | PASS | Идентичность DICOM — по fingerprint, не по пикселям (ограничение спеки §5.3). |
| S-02 Isolation | Переключение study/tab/pane не переносит калибровку, override, контур, worker-result | `tests/unit/test_tab_session.py::test_tab_stores_its_own_studies_and_root`; `tests/unit/test_tab_coordinator.py::test_switching_back_reloads_the_parked_studies_and_restores_the_clip`; `tests/unit/test_tab_coordinator_qh1a2.py::test_close_inactive_skips_purge_when_comparison_owns_source`; `tests/unit/test_multiview_session_qh1a2.py::test_active_tab_switch_preserves_pair_without_bumping_generation`, `::test_closing_owner_tab_must_not_delete_still_referenced_source` | test-logic, test-gui | PARTIAL | Покрыты переключение вкладок и пара Э10. Прямого теста «калибровка/ручной override не переезжает на другую вкладку» в этом наборе нет. Это отдельный пробел. |
| S-03 Freshness | Изменение входа делает старый результат неактуальным | `tests/unit/test_simpson_freshness.py::test_edited_contour_revision_is_stale`, `::test_changed_spacing_is_stale_with_calibration_changed`; `tests/unit/test_derived_freshness.py::test_changed_doppler_input_is_stale`; `tests/unit/test_doppler_freshness.py::test_edited_peak_velocity_is_stale`; `tests/unit/test_bsa_freshness.py::test_height_change_makes_result_stale_with_height_weight_reason`; `tests/unit/test_result_provenance.py::test_legacy_unverified_provenance` | test-logic | PASS | В старой матрице был BLOCKED; теперь закрыт QH-1b.2 (#175, закрыт 2026-10-20). Legacy без basis — unverified, не fresh. |
| S-04 Persistence | «Сохранено» = disk ack ревизии; новая правка не становится clean по старому ack | `tests/unit/test_measurement_persistence_disk.py::test_failed_save_keeps_dirty_snapshot_and_retry`, `::test_new_edit_during_failed_write_never_requeues_old_snapshot`, `::test_directory_sync_failed_save_keeps_dirty_and_reconciles_retry`; `tests/unit/test_measurement_repository.py::test_failed_replace_leaves_last_committed_record`, `::test_failed_file_fsync_leaves_last_committed_record`, `::test_write_revision_conflict_and_delete` | test-logic | PASS | Мутация «убрать file fsync» → `test_failed_file_fsync_leaves_last_committed_record` падает (проверено, см. раздел 5). |
| S-05 Delete | Удалённое не воскресает из merge, queued save, restore, позднего callback | `tests/unit/test_measurement_persistence_disk.py::test_delete_all_queued_save_cannot_resurrect`, `::test_reset_barrier_discards_late_pre_reset_save_callback`, `::test_explicit_delete_one_suppresses_autosave_until_reopen`, `::test_doppler_authoritative_deletion_roundtrips`; `tests/unit/test_measurement_persistence_rules.py::TestContourDeletionPropagation::test_deleted_planimeter_contour_is_dropped`; `::TestPerInstanceCaliperReplacement::test_deletion_in_one_clip_does_not_resurrect` | test-logic | PASS, но см. оговорку | Мутация «убрать проверку эпохи barrier» ловится одним тестом (`test_discard_unsaved_fences_inflight_failure_from_requeue`). Тесты delete-all и reset проходят без неё — там защищает другой механизм. Единственный детектор позднего callback — слабое место. |
| S-06 Partial restore | Недоступное не уничтожается при сохранении доступной части | `tests/unit/test_measurement_persistence_disk.py::test_partial_projection_preserves_unavailable_measurements`, `::test_source_mismatch_blocks_restore_and_overwrite`; `tests/unit/test_saved_records_listing.py::test_corrupt_neighbour_does_not_hide_a_readable_record`; `tests/unit/test_measurement_repository.py::test_corrupt_or_future_record_never_overwritten`; `tests/unit/test_measurement_persistence_rules.py::TestContourDeletionPropagation::test_lv_contours_survive_a_partial_report` | test-logic | PASS | — |
| S-07 Honest failure | Неуспешное действие не выглядит успешным или пустым | `tests/unit/test_saved_records_listing.py::test_listing_failure_is_not_an_empty_store`; `tests/unit/test_start_page_recents.py::test_failed_listing_is_not_shown_as_an_empty_block`, `::test_unreadable_record_is_reported_instead_of_an_empty_block`; `tests/unit/test_measurement_persistence_disk.py::test_saved_record_listing_failure_is_distinct_from_empty`, `::test_failed_save_does_not_report_a_stored_basis`, `::test_import_preview_blocks_source_mismatch_without_ram_or_disk_change` | test-logic, test-gui | PASS | — |
| S-08 Transport consent | Перед credentials/PHI проверка endpoint/transport; небезопасный remote — только scoped исключение | `tests/security/test_https_enforcement.py::TestHttpUrlPolicy`, `::TestHttpsRealTlsSocketService`; `tests/security/test_transport_policy.py` (файл) | test-security (required, `.github/required-tests/security.txt`) | PASS | Живой внешний PACS/TLS-стенд не проверялся — это эксплуатационная проверка (спека §5 baseline). |
| S-09 Privacy | Диагностика — allowlisted коды и непрозрачные ID, без PHI и полных путей | `tests/unit/test_saved_records_listing.py::test_summarize_record_never_raises_and_keeps_codes_allowlisted`; `tests/security/test_qh4a_diagnostics.py` (22 теста, файл); `tests/unit/test_security_phi_filtering.py` (файл) | test-security, test-logic | PASS | Сырые локальные crash/session-логи не объявляются анонимными (ER-10/11, см. error register). |
| S-10 Profile boundary | Presenter off не делает скрытых restore/autosave/записи на host при read-only portable | `tests/unit/test_measurement_persistence_disk.py::test_disabled_no_root_created`; `tests/unit/test_presenter_profile.py::TestPortableRoot::test_paths_are_none_when_disabled`, `::test_host_paths_untouched_when_not_portable`; `tests/security/test_portable_credentials.py::TestFailClosedWrites::test_read_only_media_does_not_fall_back`; `tests/security/test_https_enforcement.py::TestProfileMigrationAndScopeInvalidation::test_presenter_profile_uses_portable_settings_without_host_fallback` | test-logic, test-gui, test-security | PASS | — |
| S-11 Report parity | UI, текст и PDF используют одну проверенную проекцию | `tests/unit/test_report_render.py::TestRenderReport::test_export_writes_the_same_document_the_preview_shows`; `tests/unit/test_report_provenance.py::test_a_calculator_output_lists_the_inputs_it_consumed`, `::test_calculator_origin_without_inputs_is_unverified`; `tests/unit/test_measurement_report_pdf.py::test_bsa_provenance_reaches_the_pdf_story`; файлы `test_measurement_results_formatter_v2.py`, `test_report_builder.py`, `test_ste_protocol_report.py` | test-logic | PASS | Прямой автотест «текст на экране = текст формата» по всем полям отчёта в этом наборе не выделен; совпадение UI/PDF проверено через preview/export тест и provenance-тесты. |
| S-12 Proof | Наличие файла или пустой/skipped набор ≠ PASS | `tests/unit/test_ci_required_tests_gate.py::test_a_fully_skipped_run_is_not_a_pass`, `::test_an_empty_run_is_not_a_pass`, `::test_a_missing_required_test_fails_instead_of_vanishing`, `::test_a_collection_error_fails_even_when_everything_else_passed`; `.github/scripts/check_required_tests.py`; `.github/required-tests/*.txt` | test-logic, test-security | PASS | Gate-тесты локально выполняются. Применение gate к CI-прогону ветки — не проверялось (CI не запускался). |

Вне S-матрицы, но входит в G1 по спеке: A-15 (формулы/фантом) — отдельный manifest `.github/required-tests/formulas.txt` и G1-STE; G1-STE остаётся BLOCKED и G1 не блокирует.

## 4. Исправление старой матрицы

В `docs/reviews/2026-10-13-quality-safety-baseline-ru.md` §5 **19 тестовых ID не существуют** в репозитории (проверено `pytest --collect-only`, например `test_measurement_persistence_disk.py::test_partial_restore_preserves_unavailable_part`, `test_multiview_controller.py::test_late_frame_for_old_generation_is_discarded`). Статусы «PASS» в той таблице не подтверждены этими ID. Эта таблица заменена разделом 3 настоящего документа. Старый файл не переписан, а получил пометку об устаревании.

## 5. Контрольные мутации (A-13, ограниченно)

Мутации выполнены в временной копии вне репозитория, исходный код восстановлен и сверен побайтно.

| Мутация | Ожидание | Результат |
|---|---|---|
| Убрана `os.fsync(file)` в `MeasurementRepository.atomic_write` | падает тест на сбой fsync | падает `test_failed_file_fsync_leaves_last_committed_record`; проверено |
| Убрана проверка эпохи barrier при позднем save-callback (`measurement_persistence.py`) | падают тесты позднего callback | падает только `test_discard_unsaved_fences_inflight_failure_from_requeue`; остальные три теста проходят — см. S-05 |

Этого мало для полноценного A-13: мутационное покрытие выборочное. Для G1-closure нужен полный набор мутаций по S-04/S-05/S-06 или явный отказ от этого требования.

## 6. Статус G1 и что осталось

**Закрыто по доказательствам:**
- Автоматическая часть S-01…S-07, S-10, S-11 — PASS локально (см. раздел 2).
- Native Windows/macOS disk-full — PASS, run `42062351545` (commit `29081127`), артефакты с JSON `status: PASS` (см. `docs/reviews/2026-10-16-qh-1c-remap-faults-ru.md`, раздел «Native Windows/macOS ENOSPC evidence»).

**Не закрыто и блокирует объявление G1 закрытым:**
1. **CI на кандидате.** Спека требует evidence на release candidate. Ветка не запускала `ci.yml`. Нужен CI-прогон на коммите, который будет объявлен кандидатом (либо на `main` после слияния).
2. **Ручные owner-run пункты WP4** (`docs/superpowers/specs/2026-10-08-wp4-windows-acceptance-checklist-ru.md`, пункты с пометкой [ОБЯЗ]; перечень для #176 — `docs/reviews/2026-10-21-owner-manual-acceptance-checklist-ru.md`, §8.2). Это проверка на реальной машине владельца, агент её не выполняет. Нужно решение владельца: входят ли они в G1 или достаточно автоматической матрицы и native disk-full.
3. **Пробелы матрицы:** S-02 (прямой тест калибровки между вкладками) и S-05 (один детектор позднего callback). Либо дописать тесты, либо явно принять риск.
4. **Мутации:** либо полный набор по S-04/S-05/S-06, либо явный отказ от A-13 для G1.

**Не закрываем:** #176 и G1 сейчас не закрываются этим документом. Комментарий в issue и отметку чекбоксов не делаю без вашего подтверждения.
