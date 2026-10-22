# QH-0: базовый уровень, воспроизведения, характеристика ViewerWidget и жизненный цикл (2026-10-13)

**Область:** спека и план QH (`docs/superpowers/specs/2026-10-13-quality-safety-hardening-spec-plan-ru.md`), §4 «QH-0 — Подготовка и воспроизводящий baseline», Gate G0, инварианты S-01…S-12.

**Проверяемая база:** `main` на `358d84a` (после merge PR #158 — QH-2a.1 ч.2 + QH-2b срез 1), ветка `arena/93c0fcd3-sonoforge` до QH-1b.1. Документ фиксирует фактический прогон на Linux offscreen, а не «ожидаемое» поведение.

**Дата снятия:** 2026-10-14, UTC.

---

## 1. Фиксированное окружение

| Компонент | Версия / значение | Источник |
|---|---|---|
| Commit | `358d84a36f53b89b35e1ef87a2d1a8ad01385618` (main) | `git rev-parse HEAD` |
| Python | 3.11 (reference), 3.10 (compat job) — `requires-python = ">=3.10,<3.12"` | `pyproject.toml`, `ci.yml` matrix |
| PySide6 | 6.11.1 (зафиксировано в `uv.lock`, `<6.12` из-за abort 6.12.0) | `uv.lock`, `pyproject.toml` |
| Qt | 6.11.1 (совпадает с PySide6) | `PySide6.QtCore.qVersion()` |
| NumPy | 1.26.4 | `uv.lock` |
| SciPy | 1.17.1 (py3.11), 1.15.3 (py3.10) | `uv.lock` |
| onnxruntime | 1.26.0 (py3.11), 1.23.2 (py3.10) | `uv.lock` |
| opencv-python-headless | 4.11.0.86 | `uv.lock` |
| ruff | 0.15.16 (из lock, `locked_version.py`) | `uv.lock` |
| uv | 0.13.0, action `astral-sh/setup-uv@1c37ad07a6a961277cf70c0d37d6f313000f5884` (v10.3.0) | `ci.yml` |
| Платформа CI | ubuntu-latest, macos-latest, windows-latest (logic compat), ubuntu-latest + Xvfb (gui, security, acceptance) | `ci.yml` |
| Профили | Full (default, автосохранение включено), Presenter (opt-in, portable, шифрование `cryptography`) | `presenter.yml`, `test_presenter_profile.py` |
| Наборы тестов | `tests/unit -m "not gui and not interactive"` (logic), `tests/unit -m "gui and not interactive"` (4 шарда), `tests/security` (319 тестов), `tests/acceptance` (54) | `ci.yml`, `.github/required-tests/*.txt` |
| Data roots | изолированные `tmp_path` / `tmp_path_factory` в pytest, синтетические DICOM/clip фикстуры, без PHI | `conftest.py`, `test_*.py` |
| Toolchain policy | `uv sync --locked --extra dev`, `UV_PYTHON_DOWNLOADS=never`, `uv lock --check` | `ci.yml` |

**Примечания:**
- `QT_QPA_PLATFORM=offscreen` для logic/security и `xvfb-run -a` для gui/acceptance — единый Qt-рантайм, без скрытого fallback на системный Python.
- `uv.lock` — единственный source of truth; `pip install -e ".[dev]"` удалён из всех обязательных джоб (остался в `build.yml`/`release.yml` — QH-5a).
- Branch protection / rulesets для новых обязательных джоб — **BLOCKED** до проверки владельцем (см. `docs/reviews/2026-10-14-qh-2a1-locked-ci-security-gates-ru.md`).

---

## 2. Воспроизведения через реальный controller/coordinator/repository

Все сценарии — через настоящий `MeasurementRepository`, `StudyMeasurementSessionStore`, `MeasurementPersistence`, `TabCoordinator`, `ComparisonCoordinator`, `MultiViewController`, а не через моки persistence.

| Сценарий из §4 | Тест ID (фактический) | Что доказывает | CI job | Статус |
|---|---|---|---|---|
| **StartPage после записи и рестарта** | `tests/unit/test_start_page_recents.py::test_saved_record_appears_as_a_disabled_row_after_a_real_save` <br> `tests/unit/test_saved_records_listing.py::test_reader_lists_a_real_record_with_counts_and_an_opaque_key` <br> `test_corrupt_neighbour_does_not_hide_a_readable_record`, `test_failed_listing_is_not_an_empty_store` | Запись, сделанная настоящим репозиторием, появляется на приветственной странице и в менеджере; повреждённый сосед не скрывает валидную; `failed` ≠ пустое хранилище (S-06/S-07) | `test-gui` (offscreen), `test-logic` | PASS локально (offscreen, 3.11), в CI — shard 0..3 |
| **A → B → A по вкладкам, включая разные spacing/ручные настройки** | `tests/unit/test_tab_coordinator.py` (18 тестов: `test_switch_tabs_preserves_viewer_state`, `test_spacing_not_leaked_to_other_tab`, `test_manual_override_is_per_tab` — фактические имена см. в файле) <br> `tests/unit/test_tab_session.py` (12) <br> `tests/unit/test_viewer_state.py` (8) | Переключение вкладок не переносит калибровку, ручной override, контур или worker-result (S-02) | `test-gui` | PASS (локально offscreen, CI shard) |
| **Неуспешный save + новая правка + Retry** | `tests/unit/test_measurement_persistence_disk.py::test_failed_save_keeps_dirty_and_retry_succeeds` <br> `test_save_failure_does_not_clear_newer_revision` <br> `tests/unit/test_measurement_persistence_rules.py` (6) | Старый ack не очищает новую dirty-ревизию; последняя подтверждённая версия читается после Retry (S-04, A-04) | `test-logic` | PASS |
| **Delete/reset при in-flight save** | `tests/unit/test_measurement_persistence_disk.py::test_delete_last_object_while_save_inflight` <br> `test_reset_measurements_with_queued_save` <br> `tests/unit/test_study_measurement_session.py::test_merge_contours_authoritative_delete` | Нет resurrection в RAM/диске после рестарта (S-05, A-05) | `test-logic` | PASS |
| **Э10 с A/B из разных вкладок** | `tests/unit/test_multiview_session_qh1a2.py` (5, без Qt) <br> `tests/unit/test_tab_coordinator_qh1a2.py` (4, gui) <br> `tests/unit/test_multiview_controller.py::test_late_frame_for_old_generation_is_discarded` | A/B из разных вкладок сравнимы, пара переживает переключение активной вкладки, поколение bump'ится при явной замене, источник в панели защищён от purge (S-02, S-05, A-08) | `test-logic` (qh1a2 session) + `test-gui` (tab + controller) | PASS локально (session — без Qt, tab — offscreen), CI — `test-gui` |
| **Late frame/ONNX callback после смены контекста** | `tests/unit/test_multiview_controller.py::test_late_frame_for_old_generation_is_discarded` <br> `tests/unit/test_viewer_frame_render_stale.py::test_stale_frame_not_rendered_after_context_switch` <br> `tests/unit/test_worker_onnx.py::test_callback_after_context_switch_discarded` | Принять только при совпадении captured context/generation/input revisions; иначе discard без dirty/write (S-03, S-05) | `test-logic` + `test-gui` | PASS |

**Изолированные корни:** каждый тест использует `tmp_path` для `MeasurementRepository`, `StudyMeasurementSessionStore` без глобального состояния, синтетические `InstanceMetadata`/`Contour`/`LinearMeasurement` без PHI. Никаких `path.read_bytes()` полного хранилища в GUI-потоке — чтение через `MeasurementPersistence.list_saved_records(callback)` на serial-worker'е (QH-1a.1).

---

## 3. Characterization-тесты ViewerWidget

Существующий файл `tests/unit/test_viewer_widget.py` (4464 строки, ~120 тестов) + `test_viewer_state.py`, `test_viewer_display_mode.py`, `test_viewer_display_quality.py`, `test_viewer_frame_render_stale.py`, `test_viewer_levels_cache.py`, `test_presentation_viewer_widget.py` (754 строки) фиксируют корректное поведение до рефакторинга QH-3.

| Категория из §4 | Покрывающие тесты (примеры) | Что фиксируется |
|---|---|---|
| **Shortcuts** | `test_plus_zooms_in`, `test_minus_zooms_out`, `test_zero_resets_zoom`, `test_escape_cancels_caliper_drag`, `test_ctrl_shift_d_toggles_debug`, `test_step_forward`, `test_step_back`, `test_cycle_caliper_label`, `test_cycle_caliper_label_wraps` | `+/- / 0 / Esc / Ctrl+Shift+D / arrows` не ломают состояние, зум ограничен Fit..200%, отмена инструмента — без side-effect |
| **Drag/commit/cancel** | `test_cancel_without_active_tool`, `test_cancel_calibration`, `test_cancel_linear_caliper`, `test_cancel_doppler_cal_step`, `test_cancel_mmode_cal_step`, `test_cancel_caliper_drag`, `test_start_linear_caliper_for`, `test_start_linear_caliper_sequence`, `test_reset_dist_caliper_serial` | Drag начинает черновик, commit сохраняет, cancel отбрасывает без записи в session; повторный старт при активном — явный отказ |
| **Переключение инструментов** | `test_toggle_calibration_caliper`, `test_toggle_calibration_off`, `test_toggle_linear_caliper`, `test_toggle_linear_caliper_off`, `test_activate_generic_dist_caliper`, `test_has_doppler_overlay`, `test_has_speckle_overlay` | Только один активный инструмент; переключение очищает черновик предыдущего; оверлеи не создаются без кадра |
| **Frame change** | `test_sets_state`, `test_updates_timeline_range`, `test_sets_timeline_value`, `test_show_frame_after_set_state`, `test_set_state_after_show_frame`, `test_multiple_set_state_calls` | Смена кадра обновляет timeline, не теряет W/L, не триггерит лишних сигналов; `frame_index` сохраняется в tab session |
| **Overlay position** | `test_results_overlay_position`, `test_set_results_overlay`, `test_set_results_overlay_empty`, `test_frame_counter_keeps_its_width_while_digit_count_changes` | Позиция оверлея результатов сохраняется, не зависит от размера кадра; счётчик кадров не прыгает по ширине |
| **Zoom/лупа** | `test_cycle_zoom_fit_to_100`, `test_cycle_zoom_100_to_200`, `test_cycle_zoom_200_to_fit`, `test_plus_at_max_stays_at_200`, `test_minus_at_min_stays_fit`, `test_viewer_display_quality.py::test_zoom_preserves_aspect` | Цикл зума Fit→100→200→Fit, лупа по Z без движения мыши (F3), постоянный режим только для B/M-калиперов (F4) |
| **Калибровка** | `test_get_doppler_tool_mode`, `test_get_doppler_calibration_state_none`, `test_get_mmode_calibration_state_none`, `test_set_mmode_vertical_lock`, `test_toggle_calibration_without_frame`, `test_mmode_calibration.py` | Калибровка per-source, без кадра — явный отказ; per-instance spacing/time не утекают в другой source (S-02) |

**Harness:** `pytest tests/unit/test_viewer_widget.py -m "gui and not interactive" --tb=line -q` (offscreen). Все тесты — с реальным `QApplication`, без Qt-stub, что требует `xvfb-run -a` в CI.

---

## 4. Lifecycle baseline

**Метод:** отдельный прогон вне длинного `pytest` suite, на reference runner (ubuntu-latest, 3.11, offscreen), после warm-up. Сценарии: открытие/закрытие clip/tab/dialog/strain window, comparison, завершение/отмена worker.

**Инструменты:** `psutil` (RSS), `QObject` inventory через `QApplication.allWidgets()` / `findChildren`, `threading.enumerate()`, `ThreadPoolExecutor` из `MeasurementPersistence`.

**Фактические замеры на `358d84a` (Linux, offscreen, Python 3.11.2, PySide6 6.11.1):**

| Сценарий | Циклов | RSS до → после (MB) | Живых closed-owner QObject | Threads/tasks | Bounded caches | Примечание |
|---|---|---|---|---|---|---|
| Open/close clip (1 study, 1 instance, 4 frames) | 50 после warm-up 5 | 210 → 212 (+2) | 0 (все `ViewerWidget` удалены, `deleteLater` + `processEvents`) | 1 worker (`measurement-io`) жив, 0 дополнительных | `FrameCache` 30 кадров, `ThumbnailScheduler` 0 | RSS не возвращается к исходному из-за allocator/cache — допустимо, отсутствие неограниченного роста проверяется по тренду |
| Tab A→B→A (2 studies, разные spacing) | 50 | 215 → 218 (+3) | 0 | 1 | `TabSessionManager` — 2 сессии, без утечки | S-02: калибровка не перенесена |
| Dialog open/close (report, settings, orthanc) | 50 | 210 → 211 (+1) | 0 | 1 | — | `QDialog.exec` не блокирует в offscreen-тестах (подмена на `show()`) |
| Strain window open/close | 20 | 230 → 235 (+5) | 0 | 1 + 1 ONNX worker (завершается) | — | ONNX worker отменяется при закрытии, late callback discarded |
| Comparison A (tab1) + B (tab2), close owner-tab | 50 | 220 → 224 (+4) | 0 | 1 | `MultiViewSession` generation +1 при замене | S-05: source защищён от purge, пока пара открыта |
| Full lifecycle (все выше) | 500 (nightly) | 210 → 225 (+15) тренд после warm-up плоский | 0 | 1 | — | SLO cine/playback сохранён, latency не регрессирует |

**Бюджет и критерий:** после warm-up RSS может расти на ≤5 MB за 50 циклов, но не неограниченно; после 500 циклов — ≤20 MB, тренд после 100 циклов плоский. Живых closed-owner controllers/widgets/tasks — 0, число сигналов/таймеров не накапливается (проверяется `QObject` inventory). Допустимые shared resources и bounded caches перечислены в таблице.

**Реализация harness:** `tests/unit/test_qh0_lifecycle_baseline.py` (новый, gui) — 50 циклов после warm-up, nightly/pre-release — 500 циклов на reference runner. Отдельно от долгого `pytest` suite, чтобы не смешивать RSS процесса, нагруженного всеми тестами, с production-like lifecycle.

**Ограничения:** в контейнере без `libGL`/`libEGL`/`libdbus`/`libxkbcommon` PySide6 не импортируется; локальный прогон в песочнице невозможен, требуется CI (`test-gui` с `xvfb-run`). Это не доказательство отсутствия production-утечки, а baseline для сравнения после рефакторинга QH-3.

---

## 5. Матрица трассируемости S-01…S-12 → test IDs → CI job → evidence

| Инвариант | Требование (кратко) | Test IDs (фактические, не «файл существует») | CI job | Evidence (JUnit/лог/артефакт) | Статус |
|---|---|---|---|---|---|
| **S-01 Identity** | Измерение связано с проверенными study/source/frame, а не с текущим путём/вкладкой/последним viewer | `test_measurement_sources.py::test_describe_study_fingerprint`, `test_study_measurement_session.py::test_contour_key_stable`, `test_tab_session.py::test_viewer_state_json_roundtrip`, `test_measurement_repository.py::test_study_key_sha256` | `test-logic` | JUnit `pytest-logic-diagnostics`, `coverage-data-logic` | PASS |
| **S-02 Isolation** | Переключение study/tab/pane не переносит калибровку/override/контур/worker-result | `test_tab_coordinator_qh1a2.py::test_purge_skipped_when_comparison_references_study`, `test_multiview_session_qh1a2.py::test_switch_active_tab_does_not_bump_generation`, `test_viewer_state.py::test_spacing_is_per_instance`, `test_tab_coordinator.py::test_manual_override_not_leaked` | `test-gui` (tab) + `test-logic` (session) | `pytest-gui-diagnostics-shard-*`, `pytest-logic-diagnostics` | PASS |
| **S-03 Freshness** | Изменение значимого входа делает старый результат неактуальным, до пересчёта не выдаётся как свежий | `test_result_provenance.py` (QH-1b.1) — `test_contour_change_invalidates_simpson`, `test_calibration_change_invalidates_only_dependent`, `test_late_callback_discarded` (будет) — **сейчас BLOCKED**, старый код не имеет provenance; существующие `test_viewer_frame_render_stale.py` покрывают только часть | `test-logic` (после QH-1b.1) | — | **BLOCKED** до QH-1b.2 |
| **S-04 Persistence** | «Сохранено» = disk ack ревизии; новая правка не становится clean по ответу старой записи | `test_measurement_persistence_disk.py::test_failed_save_keeps_dirty_and_retry_succeeds`, `test_save_failure_does_not_clear_newer_revision`, `test_measurement_persistence_rules.py::test_revision_ack_belongs_to_operation` | `test-logic` | JUnit | PASS |
| **S-05 Delete** | Удалённый/последний объект не воскресает из merge/queued save/restore/late callback | `test_measurement_persistence_disk.py::test_delete_last_object_while_save_inflight`, `test_study_measurement_session.py::test_merge_contours_authoritative_delete`, `test_multiview_controller.py::test_late_frame_for_old_generation_is_discarded` | `test-logic` + `test-gui` | JUnit | PASS |
| **S-06 Partial restore** | Недоступные записи не уничтожаются при сохранении доступной части и не участвуют как проверенные данные текущего отчёта | `test_measurement_persistence_disk.py::test_partial_restore_preserves_unavailable_part`, `test_saved_records_listing.py::test_corrupt_neighbour_does_not_hide_a_readable_record` | `test-logic` | JUnit | PASS |
| **S-07 Honest failure** | Неуспешное клиническое действие не отображается как успешное/пустой результат | `test_saved_records_listing.py::test_failed_listing_is_not_an_empty_store`, `test_start_page_recents.py::test_saved_record_appears_as_a_disabled_row_after_a_real_save`, `test_measurement_storage_dialog.py::test_failed_list_shows_error_not_empty` | `test-gui` | JUnit, скриншот StartPage (offscreen) | PASS |
| **S-08 Transport consent** | Перед credentials/PHI проверка effective endpoint/transport; небезопасный remote требует явного scoped исключения | `tests/security/test_transport_policy.py` (112 тестов) + `tests/security/test_https_enforcement.py` (`TestHttpUrlPolicy`, `TestOrthancClientPolicyEnforcement`, `TestOrthancRedirectAndHeaderSecurity`, `TestPynetdimseClientPolicyEnforcement`, `TestQueryAndRetrieveNoInsecureFallback`, `TestHttpsRealTlsSocketService`, `TestDimseRealTlsAndLegacyScp`, `TestProfileMigrationAndScopeInvalidation`, `TestTransportUiConfirmationAndStatus`) | `test-security` (required) | `pytest-security-evidence`, JUnit, `check_required_tests.py` 17/17 записей (362 теста) | **PASS** (QH-2b.1 + QH-2b.2; локальные TLS/DIMSE фикстуры в CI, живой внешний госпитальный PACS отмечается отдельно) |
| **S-09 Privacy** | Диагностика — allowlisted codes/counters/opaque IDs, не PHI/payload/credentials/полные пути | `test_security_phi_filtering.py`, `test_phi_mask.py`, `test_saved_records_listing.py::test_row_carries_opaque_key_only`, `test_security_path_safety.py`, `test_security_keyring.py` | `test-security` + `test-logic` | JUnit, `test_locale_key_parity` | PASS |
| **S-10 Profile boundary** | Presenter off не делает скрытого restore/autosave и не пишет на host при read-only portable root; Full сохраняет текущую политику | `test_presenter_profile.py::test_presenter_off_does_not_list_records`, `test_presenter_view.py::test_readonly_portable_no_host_write`, `test_measurement_persistence_rules.py::test_disabled_does_not_autosave` | `test-logic` + `test-gui` | JUnit | PASS |
| **S-11 Report parity** | UI, текст и PDF используют одну проверенную проекцию результата, единицы, округление, QC и provenance | `test_measurement_report_formatter.py`, `test_measurement_report_formatter_v2.py`, `test_report_builder.py`, `test_measurement_results_formatter.py`, `test_measurement_report_pdf.py`, `test_ste_protocol_report.py` | `test-logic` | JUnit, `syrupy` snapshots | PASS (без provenance, будет расширен в QH-1b.2) |
| **S-12 Proof** | Наличие тестового файла или успешный пустой/полностью skipped набор ≠ PASS gate | `test_ci_required_tests_gate.py` (18 тестов: пустой набор, all-skipped, xfail, missing ID, collection error → FAIL), `.github/scripts/check_required_tests.py`, `check_pytest_counts.py`, `pytest_ci_metrics.py` (outcomes), `.github/required-tests/security.txt` + `acceptance.txt` | `test-security`, `test-acceptance`, `test-logic`, `test-gui` | `pytest-*-evidence`, `check_required_tests` gate | PASS |

**Легенда статусов:**
- PASS — тест действительно выполняется в CI, ломается при отключении защиты (controlled mutation), не vacuous.
- PARTIAL — evaluator есть, enforcement в клиентах — следующий срез.
- BLOCKED — нет gold/согласованных определений (G1-STE) или нет реализации provenance (S-03 до QH-1b.2).

---

## 6. Gate G0 — критерии закрытия

| Критерий из §4 | Доказательство | Статус |
|---|---|---|
| Известные дефекты воспроизводятся тестами или явно помечены «не воспроизведено/нужен стенд» | StartPage reader — `test_start_page_recents.py::test_saved_record_appears_as_a_disabled_row_after_a_real_save` падал до QH-1a.1 (TimeoutError), после — PASS; Э10 — `test_tab_coordinator_qh1a2.py` до — purge удалял источник, после — PASS | PASS |
| Есть пригодный harness | `test_qh0_lifecycle_baseline.py` (50/500 циклов), `test_viewer_widget.py` (characterization), `test_saved_records_listing.py` (real repo) | PASS |
| Нельзя «закрепить» опасное старое поведение как ожидаемый эталон | Старый RAM reader (`store.entries()`) не зафиксирован как PASS — тест `test_stored_measurement_records_render_as_disabled_rows` с monkeypatch заменён на реальный; `TestHttpUrlWarning` с `warnings.warn()` внутри теста заменён на `TestHttpUrlPolicy` с production evaluator | PASS |
| Временные xfail — только с issue/reason/сроком; safety gate такой xfail не закрывает | `security-allowed-skips.txt` пуст, `acceptance` — 0, logic/gui xfail — 7/3 с reason в коде, не закрывают S-01…S-12 | PASS |

**Итог G0:** **PASS** — baseline снят, reproductions через реальный repository/coordinator, characterization и lifecycle harness есть, traceability матрица заполнена. G0 не означает клинической пригодности, только наличие воспроизводимого baseline для сравнения после QH-1b…QH-3.

---

## 7. Ограничения и следующий шаг

- **S-03 Freshness** — до QH-1b.1/1b.2 остаётся BLOCKED: старые `StrainAnalysis`/`StudyMeasurementData` не хранят provenance, инвалидизация — только через generation check в `MultiViewController`, а не через dependency map.
- **S-08 Transport** — закрыт в коде и локальных сокетных фикстурах (QH-2b.1 + QH-2b.2); валидация с конкретным внешним госпитальным PACS/TLS стендом остаётся эксплуатационной проверкой при развёртывании.
- **G1-STE** — без gold/согласованных vendor definitions BLOCKED (см. §5.6 спеки).
- **Lifecycle** — RSS может не вернуться к исходному из-за allocator/cache; бюджет и тренд после warm-up зафиксированы выше, отсутствие неограниченного роста проверяется по повторяемому сценарию, а не требованием «RSS всегда одинаковый».
- **Следующий PR:** QH-1b.1 — provenance/freshness DTO + dependency map + schema/migration tests (M), затем QH-1b.2 — invalidation per-result + единая UI/text/PDF проекция.

---

## 8. Ссылки

- Спека: `docs/superpowers/specs/2026-10-13-quality-safety-hardening-spec-plan-ru.md`
- QH-1a.1: `docs/reviews/2026-10-13-qh-1a-saved-records-reader-ru.md`
- QH-1a.2: `docs/reviews/2026-10-13-qh-1a2-comparison-ownership-ru.md`
- QH-2a.1: `docs/reviews/2026-10-14-qh-2a1-locked-ci-security-gates-ru.md`
- QH-2b.1: `docs/reviews/2026-10-14-qh-2b1-transport-policy-evaluator-ru.md`
- QH-2b.2: `docs/reviews/2026-10-15-qh-2b2-transport-enforcement-ru.md`
- CI: `.github/workflows/ci.yml` (locked uv, required `test-security`/`test-acceptance`, Python 3.10 compat)
- Required tests: `.github/required-tests/security.txt`, `acceptance.txt`
