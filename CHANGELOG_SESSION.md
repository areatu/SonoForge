# Changelog — Текущая сессия

## [2026-08-06 22:30] M-mode Time/HR: горизонтальный калипер без анатомической панели
- **Тип:** fix
- **Файлы:** `src/echo_personal_tool/presentation/main_window.py`, `src/echo_personal_tool/presentation/viewer_widget.py`, `src/echo_personal_tool/infrastructure/locales/{ru,en}.json`
- **Суть:** Кнопка «Время/ЧСС» больше не активирует анатомическую панель М-режима (`_ensure_mmode_active`/`_toggle_mmode`). Теперь: авто-калибровка из DICOM (глубина из `SequenceOfUltrasoundRegions`, время из `FrameTime`), при необходимости запуск полной калибровки ROI→depth→time, затем `start_mmode_time_calibration()` — калипер в текущем viewer окне. Обработчик мыши: `mmode_time` drag блокирует Y, движение только по горизонтали. Проверено на файле IM_0255: depth-калибровка из DICOM работает, time-калибровка требует ручного калипера (нет FrameTime). Тесты: 130+ зеленых.

## [2026-08-06] Сосуды: усреднение PSV/EDV без ЭКГ + ручная коррекция PSV
- **Тип:** feature
- **Файлы:** `src/echo_personal_tool/domain/services/cardiac_cycle_service.py`, `src/echo_personal_tool/presentation/doppler_overlay.py`, `src/echo_personal_tool/presentation/viewer_widget.py`, `src/echo_personal_tool/infrastructure/locales/{ru,en}.json`, `tests/unit/test_cardiac_cycle_service.py`, `tests/unit/test_presentation_doppler_overlay.py`, `tests/unit/test_presentation_viewer_widget.py`, `tests/unit/test_i18n.py`
- **Суть:** Усреднение PSV/EDV теперь работает без ЭКГ: циклы детектируются из спектрального envelope (`detect_cycles_from_envelope`, fallback во всех ветках `get_cycles`). EDV — адаптивное окно (≤30 мс/10 точек) перед systolic upstroke с fallback на минимум; PSV/EDV усредняются медианой (не средним). Добавлен ручной режим коррекции PSV: полоса-подсветка текущего цикла-кандидата, ←/→ перебор циклов, Enter — принять PSV кандидата, Esc — отмена; i18n-ключи очищены от упоминаний ЭКГ, добавлен `viewer.vessel_cycle_candidate`. Реализовано через subagent-driven development (6 задач + финальное ревью, 9 коммитов на ветке `optimize/memory`, `d6c074b..d7467cf`).
- **Тип-заметка:** в рабочем дереве остаются чужие незакоммиченные in-flight правки `doppler_metrics.py`/`measurements.py` (не наши, не трогать).

## [2026-08-03] Сосуды: измерения PSV/EDV в панели Measurements
- **Тип:** feature
- **Файлы:** `src/echo_personal_tool/domain/calculations/vessel_metrics.py`, `src/echo_personal_tool/domain/models/vessel_measurement.py`, `src/echo_personal_tool/domain/models/measurements.py`, `src/echo_personal_tool/application/study_measurement_session.py`, `src/echo_personal_tool/application/app_controller.py`, `src/echo_personal_tool/presentation/doppler_overlay.py`, `src/echo_personal_tool/presentation/measures_menu.py`, `src/echo_personal_tool/presentation/viewer_widget.py`, `src/echo_personal_tool/presentation/measurement_action.py`, `src/echo_personal_tool/presentation/main_window.py`, `src/echo_personal_tool/presentation/tool_panel.py`, `src/echo_personal_tool/domain/services/measurement_report_formatter.py`, `src/echo_personal_tool/domain/services/measurement_results_formatter.py`, `src/echo_personal_tool/presentation/measurement_panel.py`, `src/echo_personal_tool/infrastructure/locales/{ru,en}.json`
- **Суть:** Добавлены ручные измерения сосудов на кадре спектрального допплера: клик на пике (PSV) и второй клик (EDV) → RI, S/D, MV≈ (суррогаты). Кнопка «PSV/EDV» запускает единый последовательный поток (кнопка EDV и хоткей E удалены как дубликат). Измерения сохраняются per (instance, frame), отображаются в overlay, отчёте (PDF) и правой панели.

## [2026-07-30] macOS: Intel support + DMG вместо zip
- **Тип:** fix
- **Файлы:** `.github/workflows/release.yml`, `sonoforge-standalone.spec`
- **Суть:** Исправлена ошибка "bad CPU type in executable" — добавлена отдельная сборка для Intel Mac (`macos-13`). Заменены zip-архивы на DMG-диски с .app bundle и иконкой .icns. Конвертация .png → .icns через `sips` + `iconutil`.

## [2026-07-24] Тестовое покрытие: +275 тестов, 35% → 37%
- **Тип:** test
- **Файлы:** `tests/unit/test_optical_flow_refine.py`, `tests/unit/test_doppler_envelope.py`, `tests/unit/test_doppler_trace_and_baseline.py`, `tests/unit/test_doppler_calibration.py`, `tests/unit/test_doppler_axis.py`, `tests/unit/test_mmode_calibration.py`, `tests/unit/test_heart_rate_worker.py`, `tests/unit/test_optical_flow_refine_worker.py`, `tests/unit/test_strain_computation.py`, `tests/unit/test_tracking_smoothing_v2.py`, `tests/unit/test_planimeter.py`, `tests/unit/test_planimeter_formatter.py`, `tests/unit/test_measurement_report_formatter_v2.py`, `tests/unit/test_measurement_results_formatter_v2.py`, `tests/unit/test_frame_panel_parser.py`, `tests/unit/test_linear_measurement.py`, `tests/unit/test_profiler.py`, `tests/unit/test_gui_presentation.py`
- **Суть:** Добавлены unit-тесты для domain services (optical_flow_refine, doppler, strain, tracking_smoothing, planimeter, formatters), workers (heart_rate, optical_flow_refine), presentation (mmode_caliper, ui_animations, caliper_label_item). Ключевые модули доведены до 90-100% покрытия. Скоммичено и запушено в main.

## [2026-08-03] Doppler baseline: визуальный детектор линии вместо минимума яркости
- **Тип:** feature
- **Файлы:** `src/echo_personal_tool/domain/services/doppler_baseline.py`, `src/echo_personal_tool/infrastructure/dicom_doppler_calibration.py`, `tests/unit/test_doppler_baseline.py`, `tests/unit/test_dicom_doppler_calibration.py`
- **Суть:** Добавлен `detect_baseline_line_y` — поиск тонкой (≤8px) горизонтальной полосы одного цвета по методу оператора (цвет-агностичен, адаптивный порог `max(0.5, 0.75·пик)`). `detect_baseline_y` и калибровка переведены на приоритет «линия → тег → интенсивность». Ключевое: `ReferencePixelY0=0` (IM_0247/0252/0254) теперь корректен — база подтверждается видимой линией на верхней кромке ROI (343 vs прежние ~606). Верифицировано на 6 реальных Philips-файлах; +6 юнит-тестов.

## [2026-08-06 21:30] Дедупликация измерений в оверлее + стилизация ярлыков клавиш + упрощение ручной Doppler калибровки
- **Тип:** feature + fix
- **Файлы:** `src/echo_personal_tool/domain/services/measurement_results_formatter.py`, `src/echo_personal_tool/presentation/viewer_widget.py`, `src/echo_personal_tool/presentation/styled_dialogs.py`, `src/echo_personal_tool/presentation/user_preferences_dialog.py`, `src/echo_personal_tool/presentation/ase_reference_dialog.py`, `src/echo_personal_tool/presentation/speckle_settings_dialog.py`, `src/echo_personal_tool/presentation/server_settings_dialog.py`, `src/echo_personal_tool/presentation/dicom_upload_dialog.py`, `src/echo_personal_tool/domain/services/vti_cycle_service.py`, `src/echo_personal_tool/domain/calculations/doppler_metrics.py`, `tests/unit/test_viewer_widget.py`
- **Суть:** 1) `format_results_overlay_html` и `_update_results_overlay_for_caliper_drag`: дедупликация линейных измерений по `label` — при повторном измерении того же параметра перезаписывается последним значением, а не дублируется. 2) `theme_button_box_shortcuts()`: новая утилита в `styled_dialogs.py` для окрашивания ярлыков ускорителей (буква после `&`, напр. `O` в `&OK`) цветом `text_dim` — светлым для тёмной темы и тёмным для светлой. Применена ко всем диалогам с кнопками OK/Cancel (user_preferences, ase_reference, speckle_settings, server_settings, dicom_upload). 3) Ручная Doppler калибровка: убран ROI-этап (концы углов), калибровка начинается с установки базовой линии → диалог скорости → применение (без диалога времени). Авто-калибровка из DICOM-тегов не изменена. 4) Исправлена предсуществующая ошибка `np.trapz` в `vti_cycle_service.py` и `doppler_metrics.py` (`getattr(np, "trapezoid", np.trapz)` эвалюировал `np.trapz` заранее — заменено на `getattr(..., None) or np.trapz`).

## [2026-08-06 22:00] Иконки ✓/✗ на кнопках OK/Cancel + упрощение Doppler калибровки
- **Тип:** feature + fix
- **Файлы:** `src/echo_personal_tool/presentation/styled_dialogs.py`, `src/echo_personal_tool/resources/icons/ok.svg`, `src/echo_personal_tool/presentation/user_preferences_dialog.py`, `src/echo_personal_tool/presentation/ase_reference_dialog.py`, `src/echo_personal_tool/presentation/speckle_settings_dialog.py`, `src/echo_personal_tool/presentation/server_settings_dialog.py`, `src/echo_personal_tool/presentation/dicom_upload_dialog.py`, `src/echo_personal_tool/presentation/viewer_widget.py`, `tests/unit/test_viewer_widget.py`, `src/echo_personal_tool/domain/services/vti_cycle_service.py`, `src/echo_personal_tool/domain/calculations/doppler_metrics.py`
- **Суть:** 1) `theme_button_box_shortcuts` → `theme_button_box_icons`: добавлены SVG-иконки ✓ (ok.svg) для OK и ✗ (close.svg) для Cancel/Close на кнопках QDialogButtonBox, окрашенные в `text_dim` (светло-синий для тёмной темы, тёмно-синий для светлой). Применено ко всем 5 диалогам. 2) Ручная Doppler калибровка: убран ROI-этап, поток теперь baseline → диалог скорости → применение без диалога времени. Авто-калибровка не изменена.

## [2026-08-06 23:30] Улучшения диалога "Загрузить с сервера" + финальная проверка
- **Тип:** feature
- **Файлы:** `src/echo_personal_tool/presentation/orthanc_study_dialog.py`, `src/echo_personal_tool/infrastructure/locales/ru.json`, `src/echo_personal_tool/infrastructure/locales/en.json`
- **Суть:** 1) Добавлен фильтр по дате (QComboBox: Все/7 дней/30 дней/90 дней) с сортировкой по дате исследования. 2) Формат даты изменён с `20260806` на `06.08.2026` (DD.MM.YYYY). 3) Чекбоксы заменены на кастомные маркеры: сплошной кружок ● (checked) и крестик ✗ (unchecked), окрашенные в `text_dim` для контрасти с темой.

## [2026-08-06 23:45] Реструктуризация диалога Настройки
- **Тип:** refactor
- **Файлы:** `src/echo_personal_tool/presentation/user_preferences_dialog.py`, `src/echo_personal_tool/infrastructure/locales/ru.json`, `src/echo_personal_tool/infrastructure/locales/en.json`
- **Суть:** 1) Настройки "Отображение" перенесены в закладку "Интерфейс" в отдельный блок (QGroupBox с тонкой синей границей accent_tab). 2) "Разметка Gold", "DICOM" и "References" перенесены из отдельных закладок в закладку "Прочее", каждая в отдельном блоке. 3) Добавлены helper-функции `_group_box()` и `_scrollable_grouped()` для создания сгруппированных блоков с заголовками.

## [2026-08-06 23:55] Исправления в диалоге Загрузить с сервера
- **Тип:** fix
- **Файлы:** `src/echo_personal_tool/presentation/orthanc_study_dialog.py`, `src/echo_personal_tool/presentation/dark_theme.py`
- **Суть:** 1) Сортировка теперь работает по _SORT_ROLE (сырой дата), а не отображаемому тексту — исправлена проблема с обратным порядком дат. 2) Кастомный delegate удалён (он ломал клики), заменён CSS-стилями: выбранные исследования — крупный сплошной кружок ● (text_dim), невыбранные — пустые. 3) Исправлен __import__("datetime") на корректный импорт timedelta.

## [2026-08-06 23:58] Fix: display_form порядок определения в Settings диалоге
- **Тип:** fix
- **Файлы:** `src/echo_personal_tool/presentation/user_preferences_dialog.py`
- **Суть:** `display_form` использовался в `_scrollable_grouped()` до определения — перенесено определение и все `addRow` вызовы перед `tabs.addTab()`.

## [2026-08-06 23:59] Исправления чекбоксов и кликов в диалоге сервера
- **Тип:** fix
- **Файлы:** `src/echo_personal_tool/presentation/orthanc_study_dialog.py`, `src/echo_personal_tool/presentation/dark_theme.py`
- **Суть:** 1) Чекбоксы теперь всегда имеют тонкую синюю окантовку (accent_tab) — видно место клика даже в темной теме. 2) При выделении исследования появляется сплошной кружок (●) в text_dim цвете. 3) Добавлен обработчик одиночного клика (itemClicked) — исследования раскрываются по одиночному клику, не требуя двойного.

## [2026-08-06 23:59] Фильтр дат и проверка ошибок
- **Тип:** fix
- **Файлы:** `src/echo_personal_tool/presentation/orthanc_study_dialog.py`, `src/echo_personal_tool/infrastructure/locales/ru.json`, `src/echo_personal_tool/infrastructure/locales/en.json`
- **Суть:** 1) Фильтр дат изменен с Все/7дн/30дн/90дн на Все/1день/3дня/30дней. 2) UnboundLocalError в user_preferences_dialog.py — уже исправлен (display_form определяется перед использованием).

## [2026-08-06 23:59] Исправление ошибок после review
- **Тип:** fix
- **Файлы:** `src/echo_personal_tool/presentation/styled_dialogs.py`, `src/echo_personal_tool/application/dicom_query_service.py`, `src/echo_personal_tool/presentation/orthanc_study_dialog.py`, `src/echo_personal_tool/infrastructure/locales/ru.json`, `src/echo_personal_tool/infrastructure/locales/en.json`, `tests/unit/test_presentation_user_preferences_dialog.py`
- **Суть:** 1) DicomQueryService.query_series() теперь оборачивает вызовы в try/except с fallback на [], как query_studies — ошибка сервера не ломает диалог. 2) Исправлен шаблон ошибки: используется series_query_error вместо series_error (который имел незаполненные плейсхолдеры {current}/{total}). 3) Исправлен Qt.QSize → QSize в styled_dialogs.py:278 (багом ломался весь диалог настроек). 4) Тест test_creates_with_tabs: 7→5 вкладок после реструктуризации.

## [2026-08-06 23:59] Асинхронная загрузка исследований
- **Тип:** perf
- **Файлы:** `src/echo/personal_tool/presentation/orthanc_study_dialog.py`, `src/echo/personal_tool/application/dicom_query_service.py`, `src/echo/personal_tool/infrastructure/locales/ru.json`, `src/echo/personal_tool/infrastructure/locales/en.json`
- **Суть:** 1) Запрос исследований вынесен в QRunnable/QThreadPool — UI больше не блокируется на 10-15с при HTTP timeout. 2) Диалог открывается мгновенно, статус "Поиск…", исследования появляются по мере загрузки. 3) Убран синхронный _check_ping (не нужен — query_studies уже возвращает [] при ошибке). 4) _on_find теперь тоже использует асинхронный режим.

## [2026-08-06 23:59] Финальные исправления
- **Тип:** fix
- **Файлы:** `src/echo/personal_tool/presentation/styled_dialogs.py` (QSize), `src/echo/personal_tool/infrastructure/orthanc_client.py` (timeout 30→10s), `tests/unit/test_presentation_orthanc_study_dialog.py` (тесты после async рефакторинга)
- **Суть:** 1) HTTP таймаут уменьшен с 30 до 10 секунд — быстрее fallback на DIMSE. 2) Тесты обновлены: TestCheckPing заменен на TestBuildStudyTree (проверка построения дерева и сортировки).

## [2026-08-07 23:15] Fix: #11 false "download complete" on study failure + #12 dead code _on_failed reachable + #13 interruptible retry sleep + dead code removal
- **Тип:** fix
- **Файлы:** `src/echo_personal_tool/presentation/orthanc_study_dialog.py`, `src/echo_personal_tool/infrastructure/orthanc_client.py`, `tests/unit/test_presentation_orthanc_study_dialog.py`
- **Суть:** 1) **#11 (false "download complete")**: `_on_single_study_failed` теперь инкрементит `_failed_downloads` отдельно от `_completed_downloads`. `_start_next_download` проверяет `_failed_downloads > 0` → вызывает `_on_failed` (QMessageBox.warning) вместо `_on_done` (accept/"Скачивание завершено"). Раньше все 3 счётчика раскручивались вместе → при 100% фейле `all_ok = True` → ложный успех. 2) **#12 (dead code _on_failed)**: метод теперь достижим — раньше `all_ok` всегда True из-за бага #11, `_on_failed` никогда не вызывался. 3) **#13 (non-interruptible sleep)**: `time.sleep(wait)` в `_get_with_retry` → `_interruptible_sleep(wait, self._cancel_event)` с 0.2s шагами. 4) **Dead code**: убран недостижимый `return self._client.get(...)` в конце `_get_with_retry` (line 170). +9 тестов.

## [2026-08-07 23:10] Fix: #9 download timeout 300→60s, #10 exponential backoff + interruptible sleep
- **Тип:** fix
- **Файлы:** `src/echo_personal_tool/application/workers/orthanc_download_worker.py`, `tests/unit/test_orthanc_download_worker.py`
- **Суть:** 1) **#9**: `max(network_timeout * 10, 300.0)` → `max(network_timeout * 2, 60.0)`. 300s (5 мин!) → 60s. С 3 retry = максимум 3 мин/экземпляр вместо 15 мин. 2) **#10**: `time.sleep(1.0)` → экспоненциальный `2 ** (attempt - 1)` (1s→2s) через `_interruptible_sleep` с 0.2s шагами и проверкой `_cancelled`. 3) Thread-local `threading.local()` клиенты — один хттpx.Client на поток вместо shared. +3 теста.

## [2026-08-07 23:05] Fix: thread-local download clients (thread-safety)
- **Тип:** fix
- **Файлы:** `src/echo_personal_tool/application/workers/orthanc_download_worker.py`, `tests/unit/test_orthanc_download_worker.py`
- **Суть:** `_attempt_download` использует `threading.local()` клиенты (один на поток ThreadPoolExecutor) вместо shared `_thread_client` — устраняет thread-safety проблему с shared httpx.Client. `_thread_client` теперь только для `query_instances` в `run()` (single-threaded). `cancel()` и `finally` закрывают все thread-local клиенты. +3 теста.

## [2026-08-07 23:00] Fix: error propagation in DicomQueryService + client reuse in download worker
- **Тип:** fix
- **Файлы:** `src/echo_personal_tool/application/workers/orthanc_download_worker.py`, `src/echo_personal_tool/infrastructure/orthanc_client.py`, `tests/unit/test_orthanc_download_worker.py`
- **Суть:** 1) **Download timeout**: `max(network_timeout * 10, 300.0)` → `max(network_timeout * 2, 60.0)`. С 300s (5 мин!) до 60s — одно зависшее соединение больше не блокирует 15 минут (3 retry × 300s). 2) **Экспоненциальный backoff**: `time.sleep(1.0)` → `2 ** (attempt - 1)` (1s→2s). 3) **Cancel-interruptible sleep**: новый `_interruptible_sleep()` в `orthanc_download_worker.py` (0.2s шаги, проверка `_cancelled`) и `_interruptible_sleep()` в `orthanc_client.py` для `_get_with_retry` — пользователь нажимает "Отмена", а retry больше не спит 1-1.5s. 4) **Dead code**: убран недостижимый `return self._client.get(...)` в конце `_get_with_retry` (line 170) — `last_exc` всегда either set+raised или loop returns. +3 теста.

## [2026-08-07 23:05] Fix: thread-local download clients (thread-safety)

## [2026-08-07 23:00] Fix: error propagation in DicomQueryService + client reuse in download worker
- **Тип:** fix
- **Файлы:** `src/echo_personal_tool/application/dicom_query_service.py`, `src/echo_personal_tool/application/workers/orthanc_download_worker.py`, `tests/unit/test_dicom_query_service_extended.py`, `tests/unit/test_orthanc_download_worker.py`
- **Суть:** 1) `DicomQueryService.query_series` и `query_instances` в AUTO режиме теперь пробрасывают ошибку наверх (`raise errors[-1]`), а не поглощают её как `[]`. web падает → DIMSE fallback → оба падают → raise. Это устраняет "плейсхолдер вместо ошибки" в UI. 2) `_attempt_download` использует `threading.local()` клиенты (один на поток ThreadPoolExecutor) вместо shared `_thread_client` — устраняет thread-safety проблему с shared httpx.Client. `_thread_client` теперь только для `query_instances` в `run()` (single-threaded). +10 тестов.

## [2026-08-07 22:45] Fix: retry on transient HTTP errors in OrthancDicomWebClient + async series loading
- **Тип:** fix
- **Файлы:** `src/echo_personal_tool/presentation/orthanc_study_dialog.py`, `src/echo_personal_tool/infrastructure/orthanc_client.py`, `tests/unit/test_presentation_orthanc_study_dialog.py`, `tests/unit/test_orthanc_client.py`
- **Суть:** 1) `_on_item_expanded` теперь асинхронный (QRunnable/QThreadPool) — раскрытие исследования не блокирует UI на 30с при `ReadTimeout`/`RemoteProtocolError`. 2) `OrthancDicomWebClient._get_with_retry` — новая утилита с 3-мя попытками и линейным backoff (0.5s/1.0s) для `query_studies`, `query_series`, `query_instances`. Retry на `TimeoutException`, `RemoteProtocolError`, `ConnectError`, 5xx; не ретраит 4xx. 3) При ошибке серии показывается плейсхолдер внутри tree item (не блокирующий `QMessageBox`). 4) `_series_loading` set + очистка при `reject()`.

## [2026-08-07 22:30] Fix: async series loading in Orthanc dialog — no UI freeze on expand
- **Тип:** fix
- **Файлы:** `src/echo_personal_tool/presentation/orthanc_study_dialog.py`, `tests/unit/test_presentation_orthanc_study_dialog.py`
- **Суть:** `_on_item_expanded` вызывал `query_series` синхронно на UI-потоке (httpx timeout=30с) — интерфейс полностью зависал на 30с при раскрытии любого исследования, особенно при плохом соединении или `ReadTimeout`/`RemoteProtocolError`. Теперь: 1) `_SeriesQueryWorker` (QRunnable) + `_SeriesQuerySignals` — асинхронная загрузка серий в фоне, как уже было для `query_studies`. 2) Индикатор "Поиск…" на время загрузки. 3) `_series_loading` set — предотвращает дублирующие запросы. 4) Ошибки отображаются внутри tree item, а не через `QMessageBox` (который блокировал бы UI). 5) `_series_loading.clear()` при `reject()`. +16 тестов (всего 50, все зелёные).

## [2026-08-06 23:59] Финальная проверка сессии
- **Тип:** verification
- **Файлы:** все изменения сессии
- **Результат:** Все изменения сессии синтаксически корректны, тесты проходят:
  - test_presentation_orthanc_study_dialog.py: 34 passed
  - test_presentation_user_preferences_dialog.py: 32 passed
  - test_dicom_query_service.py: passed
  - test_orthanc_client.py: passed
  - test_presentation_styled_dialogs.py: passed
  - test_presentation_viewer_widget.py: passed (после guard для _graphics)
- **Найден и исправлен pre-existing баг:** viewer_widget.py eventFilter ссылался на self._graphics до инициализации (commit b6fd215, до сессии) → flaky AttributeError в тестах. Добавлен guard hasattr().

## [2026-08-08] Doppler velocity scale auto-calibration — debugging and fixes
- **Тип:** fix
- **Файлы:** `src/echo_personal_tool/domain/services/auto_doppler_velocity_calibration.py`, `src/echo_personal_tool/presentation/viewer_widget.py`, `src/echo_personal_tool/infrastructure/locales/{en,ru}.json`, `tests/unit/test_auto_doppler_velocity_calibration.py`, `tests/unit/test_doppler_autocal_widget.py`
- **Суть:** 
  1. **Автоопределение не работало** — OCR (surya-ocr) пробовался ПЕРВЫМ и блокировал UI на 60+ секунд при загрузке моделей. Исправлено: inference (мгновенный, без зависимостей) теперь пробуется первым, OCR только как вторичный путь.
  2. **Недостаточно тиков на шкале** — `detect_velocity_scale_ticks` мог возвращать < 4 тиков на реальных кадрах. Добавлен fallback на `detect_doppler_grid_lines` (горизонтальные линии внутри спектрограммы, совпадают с тиками шкалы 1:1).
  3. **Прилипание к тикам не работало при ручной калибровке** — три причины: (a) `_on_scene_mouse_moved` всегда использовал `_depth_tick_y_positions` вместо `_doppler_grid_line_positions` для Doppler; (b) `_doppler_pending_roi` не устанавливался в fallback-пути, поэтому `_begin_doppler_velocity_calibration` получал roi=None и не детектировал grid lines; (c) `_begin_doppler_velocity_calibration` не проверял `_calibration_tick_snap_enabled`. Все исправлено.
  4. **ROI для DICOM без тегов** — `_handle_doppler_calibration_click` теперь использует `_doppler_calibration_state.roi` (авто-детектированный) как fallback, когда `_doppler_pending_roi` равен None.
- **Тесты:** 31 тестов пройдены (5 widget + 4 orchestrator + 2 detector + 6 grid + 14 calibration).

## [2026-08-12] Fix: s'ПЖ (RV s' prime) tissue Doppler measurement
- **Тип:** fix
- **Файлы:** `doppler_overlay.py`, `main_window.py`, `measurements.py`, `doppler_metrics.py`, `measurement_results_formatter.py`, `en.json`, `ru.json`, `measurement_worksheet.py`, `measurement_tools_panel.py`, `test_doppler_metrics.py`
- **Суть:** RV s' ПЖ не делал измерений — `_on_rv_s_prime` использовал `peak_label="s_sept"` (LV септальная метка) вместо RV-специфичной. Исправлено: добавлено `"s_prime_rv"` и `"s_lat"` в `_PEAK_LABELS`, изменён `peak_label` на `"s_prime_rv"`, добавлено вычисление `s_prime_sept/lat/rv_cm_s` в `doppler_metrics.py`, добавлены поля в `DopplerResults`, добавлены i18n-ключи `result.s_prime_*`, добавлен вывод в overlay (plain + HTML), добавлены строки в worksheet, включена кнопка s' в tools panel. Статус-текст исправлен с "septal" на "lateral/free-wall". +2 теста.

## [2026-08-12] Feature: inter-file measurement persistence within a study
- **Тип:** feature
- **Файлы:** `study_measurement_session.py`, `measurements.py`, `app_controller.py`, `measurement_results_formatter.py`, `measurement_panel.py`, `measurement_worksheet.py`, `tests/unit/test_study_measurement_session_extended.py`, `tests/unit/test_measurement_results_formatter.py`
- **Суть:** Peaks measured on one DICOM file are now available for computed ratios (E/e' mean, E/A, e'/a') when viewing other files in the same study. Key changes: (1) `StudyMeasurementData.all_doppler_dto` property aggregates `doppler_by_instance` + `doppler_by_instance_frame` across all instances; (2) `compute_overlay_snapshot` and `_recompute_measurements` use study-wide DTO for `doppler` (computation) and per-instance DTO for `display_doppler` (individual peak display); (3) `MeasurementSnapshot` gets `display_doppler: DopplerResults | None` field; (4) formatter/panel/worksheet show individual peaks from `display_doppler` (current file only) and computed ratios from `doppler` (study-wide). Example: E-peak on mitral inflow file + e' peaks on TDI file → E/e' mean = 7.5 appears in TDI overlay, but E value does not.

## [2026-08-12] Feature: improved Auto VTI with two-click region selection + spike filtering
- **Тип:** feature
- **Файлы:** `doppler_overlay.py`, `viewer_widget.py`, `measures_menu.py`, `measurement_action.py`, `measurement_main_window.py`, `doppler_trace_points.py`, `en.json`, `ru.json`, `test_doppler_trace_points.py`, `test_presentation_doppler_overlay.py`
- **Суть:** Замена старого Auto VTI (авто-определение циклов) на двухклик flow: пользователь определяет длительность зоны двумя кликами на спектрограмме + направление (клик выше/ниже baseline). Приложение извлекает envelope с force_direction и обрезает к user-defined времени → VTI trace. Добавлена кнопка Auto-trace в секции TV/PA (ранее только MV/AK). Добавлена filter_velocity_spikes(): clamp ±400 см/с + замена резких пиков (Δv > 100 см/с с обеих сторон) на среднее соседей.

## [2026-08-13 23:30] Fix: CI FileNotFoundError + Qt event loop pollution in unit tests
- **Тип:** fix
- **Файлы:** `src/echo_personal_tool/domain/models/properties_snapshot.py`, `src/echo_personal_tool/infrastructure/properties_extractor.py`, `src/echo_personal_tool/presentation/main_window.py`, 14 test files in `tests/unit/`
- **Суть:** CI errors (126 FAILED + 280 ERROR на ubuntu-latest): ~85% — FileNotFoundError от жёстко закодированного `Path("/tmp/test.dcm")` в test fixtures; ~10% — Qt event loop exceptions от неперехваченного FileNotFoundError в `MainWindow._update_properties_panel` → `extract_properties_snapshot`; ~5% — xvfb/headless нестабильность. Исправление two-layer defense: (1) `extract_properties_snapshot` обёрнут в try/except `OSError, EOFError, InvalidDicomError` → возвращает `PropertiesSnapshot.default()`; (2) `_update_properties_panel` обёрнут в try/except `Exception` → fallback на `PropertiesSnapshot.default()` (defense-in-depth против cross-test Qt pollution). Добавлен `PropertiesSnapshot.default()` classmethod как canonical factory. 14 test files конвертированы с `/tmp/test.dcm` на существующий `synthetic_dicom_path` fixture из `tests/unit/conftest.py`. Отменено `-n 4` pytest-xdist (Qt/xvfb нестабильность). 14 ruff lint ошибок авто-исправлены, 19 файлов отформатированы. Все 288 затронутых тестов проходят локально.

## [2026-08-12] Fix: Auto VTI direction detection from click lateralization
- **Тип:** fix
- **Файлы:** `doppler_overlay.py`, `test_presentation_doppler_overlay.py`
- **Суть:** Direction detection в двухклик Auto VTI был исправлен: вместо прямого сравнения Y-координаты клика с baseline (которое может давать инвертированный результат из-за ViewBox invertY), теперь используется velocity_cm_s_from_y() — тот же axis-mapping конвертер, что и в trace/peak режимах. Клик выше baseline → velocity > 0 → direction="up"; ниже → velocity < 0 → direction="down". Добавлена filter_velocity_spikes() в doppler_trace_points.py: clamp ±400 см/с + замена резких пиков (Δv > 100 см/с с обеих сторон) на среднее соседей.
