# WP4.1–4.2: проверка совместимости с main и кэшем

Дата: 2026-10-03. Проверена рабочая реализация на `arena/01a0fde0-sonoforge`.
После `git fetch origin main` актуальный `origin/main` — `e355228d7f4ffddd8b7fa5a02fbcac32f61246ae` (merge #105; включает #106 и `22f3a3f`). Он является предком HEAD этой ветки. Реализация и исправления проверки пока не закоммичены.

## Вывод

Переработки самого кэша в WP4.1–4.2 нет. Однако первоначальная интеграция содержала регрессии жизненного цикла, поэтому одного сравнения cache-модулей недостаточно. Ниже перечисленные воспроизведённые ошибки исправлены и покрыты тестами. В проверенных сценариях существенного нарушения существующей работы кэша не обнаружено. Равенство производительности с main и native/PACS acceptance **не подтверждены**; экспериментальная функция остаётся выключенной по умолчанию.

## Что осталось как в main

Прямой `git diff origin/main --` пуст для:

- `infrastructure/orthanc_cache.py`;
- `infrastructure/dicom_session.py`;
- `application/frame_cache.py`;
- `application/workers/orthanc_download_worker.py`.

Не изменены раскладка `session-<uuid>/<StudyUID>/<SOP>.dcm`, квота Orthanc по умолчанию 20 GiB, очистка старых сессий через 7 дней, обновление mtime сессий, filesystem guards и механизм исключения защищённых сессий из очистки. Настройка удаления кэша при выходе сохранена. RAM frame cache, его лимиты, декодирование и prefetch не переписаны.

Измерения лежат отдельно: `<data_dir>/measurements`, не внутри `cache/orthanc`. Очистка DICOM-кэша не удаляет измерения; удаление измерений не удаляет DICOM. Повторная загрузка тех же синтетических DICOM в другую cache session восстанавливает рост/вес и Doppler при совпавших источниках.

## Найдено и исправлено

1. **Очистка ещё отображаемого исследования во время restore.** Контроллер уже публиковал входящий набор через `studies`, а viewer/multiview ещё держали старый. Теперь старый набор временно удерживается для защиты кэша; MainWindow защищает объединение старого и нового. Защита старого освобождается после обработки `studies_loaded`; при неуспешном scan старые studies остаются текущими и защищёнными.
2. **Старый Doppler попадал в новый store под fallback Series UID.** Первый gallery selection пытался сохранить исходящий viewer после очистки study-store. Это создавало orphan dirty record и блокировало flush. При успешном переходе identity StateManager теперь сбрасывается до публикации нового набора. При провале scan прежняя identity сохраняется.
3. **Лишний deepcopy при выключенной persistence.** Observer создавал копию всего исследования на каждую правку, хотя coordinator затем игнорировал событие. В выключенном режиме observer теперь отключён, включая runtime disable/discard/delete paths.

Дополнительно: переключение клипа проецирует его калибровку без deepcopy всех накопленных контуров и без dirty/autosave; пустой enabled restore завершает статус loading состоянием ready.

Первые три случая воспроизведены до исправлений: **3 failed, 3 passed** в начальном regression-наборе. После исправлений первоначальный focused-прогон четырёх модулей дал **26 passed**. Последующие расширенные проверки приведены ниже; старые и новые результаты не складываются.

## Текущее влияние и ограничения

- PACS pre-scanned fast path не создаёт ScanWorker ни при включённой, ни при выключенной persistence. При выключенной persistence нет дополнительного source fingerprint pass и записи measurement-store.
- При включённой persistence перед публикацией исследования повторно читаются DICOM-заголовки для проверки источников. Для не-DICOM рассчитывается hash всего файла. Это дополнительный I/O, особенно на USB/сетевых дисках и больших видео; сравнительный benchmark не проводился.
- Выключенная функция не означает буквально нулевой overhead: coordinator копирует метаданные при загрузке исследования. В локальном сканере WP4 также добавлены разделение смешанных папок по Study UID и повторное чтение заголовков для этого разделения — независимо от настройки persistence. Это намеренное изменение принадлежности данных, но не измеренная по скорости замена main. PACS pre-scanned обходится без этого scanner pass.
- При включённой persistence перед навигацией/выходом выполняется flush до 5 секунд. Ошибка отменяет переход/закрытие; очистка кэша на выходе тогда не выполняется. Сначала сохраняются измерения, затем запускается прежняя очистка. Выход только из M-mode не закрывает persistence.
- Не проверялись реальный PACS, native Windows/macOS, реальный медленный накопитель и многочасовой playback. Эти тесты не закрывают оставшиеся пункты §16 спецификации WP4.1.

## Проверки после исправлений

Среда: Linux, Python 3.11, Qt offscreen с репозиторными `tools/qtstub`; DICOM синтетические, реальные `OrthancSessionCache`/measurement repository в `tmp_path`. Новые controller-тесты используют fake decode pool; существующие playback/cache tests запускаются отдельно в том же наборе. Реальной сети PACS нет.

| Набор | Результат |
|---|---|
| Cache/PACS/frame/prefetch/scroll/main-window/preferences/paths, 20 модулей | **381 passed, 4 xfailed**, 106.03 с |
| Measurement/controller/multiview/state/scanner/preferences/main-window, расширенный набор после добавления финальных edge cases | **690 passed**, 176.73 с |
| `ruff check src tests` | passed |
| `git diff --check` | passed |
| `python -m compileall -q src/echo_personal_tool` | passed |

Наборы пересекаются, поэтому итоговое количество уникальных тестов не суммируется. Четыре xfail относятся к уже помеченным в main проверкам pixel values в `test_dicom_session.py`; новые xfail не добавлялись. Полный pytest-suite не запускался.

Новые регрессии: `tests/unit/test_measurement_cache_compatibility.py`; close ordering/cancel/M-mode — в `tests/unit/test_presentation_main_window.py`. Дополнительно проверены начальная пустая cache lease, освобождение lease только после callbacks нового выбора, провал scan, пустой study set, отсутствие dirty/copy при проекции калибровки, неизменность DICOM bytes/mtime, независимость удаления двух хранилищ и восстановление после повторного скачивания.

### Команды воспроизведения

После установки dev-зависимостей и `MKSTUB_CI_ONLY=1 .venv/bin/python tools/qtstub/mkstub.py`:

```bash
export LD_LIBRARY_PATH=tools/qtstub/lib
export QT_QPA_PLATFORM=offscreen
.venv/bin/pytest \
  tests/unit/test_measurement_cache_compatibility.py \
  tests/unit/test_orthanc_cache.py tests/unit/test_orthanc_download_worker.py \
  tests/unit/test_orthanc_export_layout.py tests/unit/test_p4_skip_scan_worker.py \
  tests/unit/test_orthanc_study_dialog.py tests/unit/test_presentation_orthanc_study_dialog.py \
  tests/unit/test_presentation_user_preferences_dialog.py tests/unit/test_presentation_main_window.py \
  tests/unit/test_frame_cache.py tests/unit/test_frame_cache_extended.py tests/unit/test_frame_cache_memory_budget.py \
  tests/unit/test_app_controller_dicom_cache.py tests/unit/test_dicom_session.py tests/unit/test_p3_pixel_cache.py \
  tests/unit/test_playback_prefetch.py tests/unit/test_scroll_debounce.py \
  tests/unit/test_scroll_min_buffer.py tests/unit/test_scroll_two_phase_load.py tests/unit/test_paths.py --tb=short

.venv/bin/pytest tests/unit/test_measurement_*.py tests/unit/test_multiview*.py \
  tests/unit/test_state_manager.py tests/unit/test_study_measurement_session*.py \
  tests/unit/test_local_media_scanner.py tests/unit/test_app_controller_critical.py \
  tests/unit/test_app_controller_vessel.py tests/unit/test_app_controller_thumbnail_priority.py \
  tests/unit/test_user_preferences.py tests/unit/test_presentation_main_window.py --tb=short
```

Первый зафиксированный результат получен до добавления трёх последних cache edge cases; они вошли во второй прогон. Поэтому при повторении первой команды количество тестов будет больше.
