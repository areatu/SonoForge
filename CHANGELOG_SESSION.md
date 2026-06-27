# CHANGELOG_SESSION.md

**Назначение:** Автоматическая передача ключевого контекста между чатами Cursor.
**Правила чтения:** При старте нового чата — `AGENTS.md`, затем последние записи здесь (не весь файл).
**Лимиты:** Максимум 30 записей; при превышении удаляются самые старые. Только суть, без кода.

---

## [2026-06-27 18:30] STE: окно ED–ES, оверлей, QC-таблица
- **Тип:** fix
- **Файлы:** `speckle_worker.py`, `viewer_widget.py`, `strain_curve_widget.py`, `segment_quality_panel.py`, `speckle.py`, `main_window.py`
- **Суть:** Трекинг только в окне ED…ES; график strain по этому окну; спеклы обновляются по кадру; Quality < 0.4 — тёмно-красный.

## [2026-06-27 17:00] Оверлей спеклов по кадрам ED–ES
- **Тип:** fix
- **Файлы:** `speckle.py`, `speckle_worker.py`, `viewer_widget.py`, `speckle_overlay.py`
- **Суть:** Спеклы рисовались только в позициях ES; добавлены полные траектории `tracked_positions_all` и обновление оверлея при смене кадра в окне ED…ES.

## [2026-06-19 37:00] Индексы при отклонении от ASE-норм
- **Тип:** feature
- **Файлы:** `ase_reference_norms.py`, `indexed_results_formatter.py`, `body_surface.py`, `measurements.py`, `measurement_results_formatter.py`, тесты
- **Суть:** При введённых росте/весе и выходе за ASE-нормы в overlay добавляются индексированные значения: LVMI, EDVi/ESVi, LAVi, RAVi, mm/m² для аорты и крупных линейных размеров.

## [2026-06-19 36:00] Калибровка см, blink, ОТС
- **Тип:** feature
- **Файлы:** `viewer_widget.py`, `measures_menu.py`, `main_window.py`, `tool_panel.py`, `rwt.py`, `measurements.py`, `app_controller.py`, `measurement_results_formatter.py`, тесты
- **Суть:** Калибровка B-mode/M-mode вводит см; после All Diastole мигает ES Diameter, после ED Simpson — ESV; в overlay добавлен ОТС = (2×LVPWd)/LVEDD.

## [2026-06-19 35:00] Нормативы: один документ + шрифт
- **Тип:** feature
- **Файлы:** `ase_reference_parser.py`, `ase_reference_dialog.py`, тесты
- **Суть:** Вместо вкладок — один прокручиваемый документ из `References ASE+.md`; меню «Настройки → Шрифт»; кнопки «Обновить» и «Открыть файл»; цветовые градации убраны.

## [2026-06-19 34:00] Кнопка «Нормативы» — таблицы ASE
- **Тип:** feature
- **Файлы:** `ase_reference_parser.py`, `ase_reference_dialog.py`, `system_bar.py`, `main_window.py`, `test_ase_reference_parser.py`, `test_system_bar.py`
- **Суть:** Кнопка «Нормативы» в system bar открывает диалог с вкладками по разделам `References ASE+.md`; колонки «Норма» — зелёные; степени патологии и строки клапанных таблиц — градация зелёный→красный.

## [2026-06-19 33:00] Stepped R refine: ±N px + lock узлов
- **Тип:** feature
- **Файлы:** `contour.py`, `stepped_border_refine.py`, `contour_edge_snap.py`, `mbs_lite_service.py`, `viewer_widget.py`, `main_window.py`, `app_controller.py`, тесты
- **Суть:** R для ai/manual: шаг 1..12, на каждом R поиск -N/+N px вдоль нормали; узлы с сильным градиентом фиксируются; locked не двигаются; drag/auto-segment сбрасывают состояние.

## [2026-06-19 32:00] AI refine: directed edge snap вместо Laplacian
- **Тип:** fix
- **Файлы:** `mbs_lite_service.py`, `test_mbs_lite_service.py`
- **Суть:** ai/manual: R/auto_refine через outward edge snap (направленный градиент + intensity ridge), без итеративного k_smooth active contour; sanity по глубине дуги; model — active contour + Lamé.

## [2026-06-19 31:00] Refine: ONNX shape вместо Lamé для ai/manual
- **Тип:** fix
- **Файлы:** `mbs_lite_service.py`, `test_mbs_lite_service.py`
- **Суть:** R/auto_refine больше не тянет ai/manual к Lamé-шаблону: internal template = исходные точки; Lamé только для source=model; отдельный ActiveContourConfig для ai.

## [2026-06-19 30:00] A4C annulus guard + cine ROI basal pad
- **Тип:** fix
- **Файлы:** `segment_roi.py`, `segmentation_service.py`, `cine_segment_diagnostics.py`, `app_controller.py`, тесты
- **Суть:** A4C: flip когда annulus выше apex (annulus_end=bottom). Cine ROI: +5% panel снизу, без sector bottom trim. При загрузке MP4 — сброс frozen ROI и pending AI контуров. DICOM без изменений.

## [2026-06-19 29:00] Frozen cine ROI + sloped MV annulus
- **Тип:** fix
- **Файлы:** `study_measurement_session.py`, `segment_roi.py`, `segmentation_service.py`, `app_controller.py`, `cine_segment_diagnostics.py`, `scripts/diagnose_cine_segment.py`, тесты
- **Суть:** MP4: ROI фиксируется на frame 0 и перезаписывается при ED auto-segment; ES использует frozen ROI. MV-линия: отдельный Y для septal/lateral (percentile trim), A4C-guard annulus выше apex. CLI: `--freeze-roi-from-frame`.

## [2026-06-19 28:00] Cine sector trim + center_square embed
- **Тип:** fix
- **Файлы:** `segment_roi.py`, `cine_segment_diagnostics.py`, `test_segment_roi.py`
- **Суть:** MP4 ROI обрезается по ткани сектора (без чёрных полей); EchoNet снова center_square внутри ROI — маска шире и ближе к полости (DICOM_0027 f59: ~17k px vs ~8k).

## [2026-06-19 27:30] Cine lateral trim ROI + annulus flip
- **Тип:** fix
- **Файлы:** `segment_roi.py`, `segmentation_service.py`, `app_controller.py`, `cine_segment_diagnostics.py`, `test_segment_roi.py`
- **Суть:** MP4: обрезка боковых UI-полос (маска больше не на x≈1200); при annulus_y>apex_y — annulus_end=top. DICOM без изменений.

## [2026-06-19 27:00] Cine auto-contour: full ROI + диагностика
- **Тип:** feature
- **Файлы:** `segment_roi.py`, `segmentation_service.py`, `cine_segment_diagnostics.py`, `app_controller.py`, `onnx_engine.py`, `onnx_worker.py`, `scripts/diagnose_cine_segment.py`, `tests/interactive/`, `tests/unit/test_segment_roi.py`
- **Суть:** Для non-DICOM cine (MP4) — эвристика B-mode + full_roi embed; DICOM без изменений (center_square). Интерактивные тесты и CLI для диагностики ROI/маски/контура.

## [2026-06-19 26:30] Откат cine ROI экспериментов (восстановлен DICOM auto)
- **Тип:** fix
- **Файлы:** `segmentation_service.py`, `frame_panel_parser.py`, `app_controller.py`, `lvef_simpson.py`, `mbs_lite_service.py`, `onnx_worker.py`, тесты
- **Суть:** Откат изменений после «DICOM Фото контур не плохо»: снова DICOM-first ROI, center-square EchoNet embed, без heuristic-priority и OOB-gate; убраны 25:35 и 26:10 правки.

## [2026-06-19 25:15] MV: широкий конец маски + drag концов
- **Тип:** fix
- **Файлы:** `segmentation_service.py`, `viewer_widget.py`, `test_segmentation_service.py`
- **Суть:** Annulus на более широком конце полости (не y_min); прямой drag узлов 0/N (раньше pinned → не двигались).

## [2026-06-19 25:00] MV annulus из верхней полосы маски + drag MV
- **Тип:** fix
- **Файлы:** `segmentation_service.py`, `app_controller.py`, `viewer_widget.py`, `test_segmentation_service.py`
- **Суть:** Annulus = верхнее отверстие полости (не longest chord/ось ЛЖ); ручной drag концов open-arc обновляет mitral_annulus и линию MV.

## [2026-06-19 24:40] mask_to_contour: cv2.findContours
- **Тип:** fix
- **Файлы:** `segmentation_service.py`, `test_segmentation_service.py`, `lvef_simpson.py`
- **Суть:** Moore-tracer обходил только 2×2 px угол при большой маске (25862 px, дуга 1 px); граница через OpenCV findContours.

## [2026-06-19 24:25] W/L/DR для B-mode DICOM RGB
- **Тип:** fix
- **Файлы:** `pixel_utils.py`, `viewer_widget.py`, `test_pixel_utils_display_range.py`
- **Суть:** Слайдеры отключались на 3-канальных DICOM (псевдо-RGB); включены для effective grayscale и составных кадров (B-mode сверху).

## [2026-06-19 24:10] EchoNet B-mode crop перед ONNX
- **Тип:** fix
- **Файлы:** `segmentation_service.py`, `onnx_engine.py`, `onnx_worker.py`, `app_controller.py`, `test_segmentation_service.py`
- **Суть:** ONNX получает квадратный кроп B-mode сектора (DICOM regions / heuristic), а не сжатие всего кадра с UI — устраняет схлопнутую маску в центре; статус с mask_px и arc_px.

## [2026-06-19 23:55] LV auto-segment quality gate по пикселям
- **Тип:** fix
- **Файлы:** `lvef_simpson.py`, `app_controller.py`, `model_manifest.json`, `test_lvef_simpson.py`
- **Суть:** Отклонение ONNX-контура по геометрии в px (не по мм при плохом PixelSpacing); ранний fail при малой маске; `auto_refine_after_segment` выключен по умолчанию; статус с конкретной причиной отказа.

## [2026-06-24] DICOM tag dictionary + рефакторинг orthanc_dicom_json
- **Тип:** feature + refactor
- **Файлы:** `domain/services/dicom_tag_dictionary.py` (новый), `infrastructure/orthanc_dicom_json.py`, `tests/test_dicom_tag_dictionary.py` (новый)
- **Суть:** Легковесный словарь ~211 DICOM-тегов с lookup по int/hex/tuple. Заменены хардкод hex-констант в orthanc_dicom_json.py на импорт из словаря. Анализ Weasis показал, что Doppler/M-mode калибровка в ECHO2026 уже продвинутее.

## [2026-06-24] Speckle Tracking (2D Strain) — ядро + UI
- **Тип:** feature
- **Файлы:** `domain/models/speckle.py`, `domain/services/myocardial_zone.py`, `domain/services/speckle_tracking.py`, `domain/services/strain_computation.py`, `domain/services/cardiac_cycle_detector.py`, `presentation/speckle_overlay.py`, `presentation/strain_curve_widget.py`, `application/workers/speckle_worker.py`, `tests/unit/test_speckle_tracking.py`, `presentation/measurement_action.py`, `presentation/measures_menu.py`, `presentation/main_window.py`, `application/app_controller.py`, `presentation/viewer_widget.py`
- **Суть:** Block-matching speckle tracking с NCC, пирамидальный подход, sub-pixel точность. Dual-contour (Philips/Samsung стиль): эндокард + эпикард с фиксированной толщиной. GLS + radial strain, авто-определение ED/ES через FFT. Offline batch режим. UI: кнопка "Speckle Tracking" в Measures → Strain, AppController.run_speckle_tracking(), SpeckleOverlay + StrainCurveWidget.

## [2026-06-25] Orthanc download + play + performance fixes
- **Тип:** fix + feature
- **Файлы:** `orthanc_study_dialog.py`, `main_window.py`, `app_controller.py`, `orthanc_client.py`, `orthanc_cache.py`, `viewer_widget.py`, `video_decode_worker.py` (новый), `frame_cache.py`, `pixel_utils.py`, `dicom_session.py`
- **Суть:**
  1. Multi-study download: `_collect_all_checked_series` собирает все отмеченные серии из всех исследований, очередь загрузки с `_start_next_download`, `session_path()` для сканирования всей сессии.
  2. `_parse_multipart` заменён email-модуль на boundary-based парсер; добавлено логирование ответа.
  3. Play freeze: `_pending_decode_id` устанавливается до `emit_state()`; partial frame cache serving во время декодирования; `show_frame_fast` пропускает layout/doppler/panel при воспроизведении.
  4. MP4 pre-decode: `VideoDecodeWorker` декодирует все кадры MP4 в `FrameCache` при загрузке (аналог DICOM).
  5. Диалог загрузки: `accept()` прямой вместо `QMetaObject.invokeMethod`; `closeEvent` корректно обрабатывает завершённую загрузку; `result_data()` проверяется без привязки к `exec()` result.

## [2026-06-26 15:30] P0: Per-instance скачивание + parallel downloads + memory fixes
- **Тип:** fix + refactor + feature
- **Файлы:** `orthanc_client.py`, `orthanc_download_worker.py`, `frame_cache.py`, `dicom_decode_worker.py`, `domain/ports.py`, `fake_dicom_web_client.py`, `tests/unit/test_orthanc_download_worker.py`
- **Суть:**
  1. Заменён series-level multipart на per-instance WADO-RS (`download_instance` вместо `download_series`).
  2. Добавлен `ThreadPoolExecutor(max_workers=4)` для параллельного скачивания инстансов.
  3. Убраны `.copy()` в `FrameCache.get()` и `DicomDecodeWorker.run()` — устранена утечка памяти ~510 МБ при 170 кадрах.
  4. Удалены `download_series()` из `DicomWebClient` Protocol и `FakeDicomWebClient`.
  5. Удалён `_parse_multipart()` и неиспользуемые импорты из `orthanc_client.py`.
  6. Диагностический трейсинг `[DIAG]` на каждом этапе загрузки.

## [2026-06-26 16:15] P1: Первый кадр сразу — прогрессивный показ
- **Тип:** feature + refactor
- **Файлы:** `dicom_session.py`, `dicom_decode_worker.py`, `video_decode_worker.py`, `app_controller.py`, `test_app_controller_dicom_cache.py`, `test_app_controller_thumbnail_priority.py`
- **Суть:**
  1. `DicomSession.decode_first_frame()` — быстрое декодирование только первого кадра (без стекирования всех фреймов).
  2. `DicomDecodeWorker` и `VideoDecodeWorker` эмитят `first_frame_ready` сразу после первого кадра, затем `finished` с полным результатом.
  3. `AppController._on_first_frame_ready()` — показывает первый кадр немедленно, не дожидаясь декодирования остальных.
  4. Тесты обновлены: `_FakeDecodeWorker` и `_FakeVideoDecodeWorker` включают `first_frame_ready` сигнал.

## [2026-06-26 16:45] P2: Прогресс-бар декодирования кадров
- **Тип:** feature
- **Файлы:** `system_bar.py`, `dicom_decode_worker.py`, `video_decode_worker.py`, `app_controller.py`, `main_window.py`, тесты
- **Суть:**
  1. `SystemBar`: добавлен `QProgressBar` (160px, скрыт по умолчанию), методы `show_decode_progress(current, total)` / `hide_decode_progress()`.
  2. `DicomDecodeWorker` и `VideoDecodeWorker`: добавлен сигнал `progress(int, int)` — для DICOM эмитится при завершении, для MP4 — каждые 5 кадров.
  3. `AppController`: сигналы `decode_progress` и `decode_finished` прокидываются в `SystemBar`.
  4. Тесты: `_FakeDecodeWorker` и `_FakeVideoDecodeWorker` включают `progress` сигнал.

## [2026-06-26 17:00] P3: Параллельные миниатюры max_in_flight 2→6
- **Тип:** config
- **Файлы:** `thumbnail_scheduler.py`, `app_controller.py`
- **Суть:** `max_in_flight` увеличен с 2 до 6 — теперь до 6 миниатюрок генерируются параллельно.

## [2026-06-26 18:30] Cine play: статичные lead-in кадры + flicker
- **Тип:** fix
- **Файлы:** `app_controller.py`, `viewer_widget.py`, `main_window.py`
- **Суть:** Исправлено «зависание» первых кадров при воспроизведении DICOM/MP4: при декодировании определяется число leading static frames (MAD от кадра 0), при старте play и при loop индекс перескакивает на первый динамический кадр; `toggle_playback` маршрутизирован через `set_playing`. В `show_frame_fast` убрана пересборка display mode на каждом кадре — устранён flicker color/grayscale. Отладочная инструментация удалена.

## [2026-06-27 12:00] STE clinical parity: spec + implementation plan
- **Тип:** feature
- **Файлы:** `docs/superpowers/specs/2026-06-27-ste-clinical-parity-design.md`, `docs/superpowers/plans/2026-06-27-ste-clinical-parity.md`
- **Суть:** Утверждена Strategy 1 (Tier A + determinism fixes): bidirectional ED-anchored NCC, spline smoothing, Green–Lagrange strain, AHA segments, drift compensation, QC UI. Design spec и 8-task implementation plan для backlog #1–#8.

## [2026-06-27 15:05] STE Task 6: ED/ES pre-detect + worker pipeline
- **Тип:** feature
- **Файлы:** `src/echo_personal_tool/domain/services/cardiac_cycle_detector.py`, `src/echo_personal_tool/application/workers/speckle_worker.py`, `src/echo_personal_tool/domain/services/speckle_tracking.py`, `tests/unit/test_speckle_tracking.py`
- **Суть:** Добавлены pre-tracking ED/ES детекция по сглаженной кривой proxy-area и ROI mask для FFT HR-оценки; `SpeckleTrackingWorker` переведён на новый ED-anchored bidirectional pipeline с smoothing, GL strain, AHA segment aggregation и расширенным `StrainResult`. Исправлен возврат `track_cine_bidirectional` для корректной совместимости с `extract_trajectories` при `ed_index != 0`.

## [2026-06-27 15:20] STE Task 7: QC panel, settings, preset metadata
- **Тип:** feature
- **Файлы:** `src/echo_personal_tool/presentation/segment_quality_panel.py`, `src/echo_personal_tool/presentation/speckle_settings_dialog.py`, `src/echo_personal_tool/presentation/speckle_overlay.py`, `src/echo_personal_tool/presentation/main_window.py`, `src/echo_personal_tool/application/app_controller.py`, `src/echo_personal_tool/application/workers/speckle_worker.py`
- **Суть:** Добавлены UI-компоненты контроля качества сегментов и настроек speckle preset перед запуском, интеграция кривых strain + QC в окно и status bar. `run_speckle_tracking` принимает опциональный `SpeckleConfig`, а worker теперь возвращает выбранный `config_preset` в `StrainResult`.

## [2026-06-27 17:00] STE: окно ED-ES, зона миокарда, QC цвет
- **Тип:** fix
- **Файлы:** `speckle_worker.py`, `myocardial_zone.py`, `speckle_overlay.py`, `viewer_widget.py`, `segment_quality_panel.py`, `strain_computation.py`, `speckle.py`
- **Суть:** При ручном ED/ES трекинг и GLS только в окне фаз; drift comp ED→ES. Заливка стенки миокарда (endo–epi), kernels на ES с цветом по слою (endo/mid/epi). Quality 0.0 — тёмно-красный фон, белый текст.

- **Тип:** fix
- **Файлы:** `speckle_tracking.py`, `speckle_worker.py`, `speckle_overlay.py`, `viewer_widget.py`, `tracking_smoothing.py`, `aha_segments.py`
- **Суть:** Исправлено смешение ко координат ED и frame-t в bidirectional fusion (источник «веера» жёлтых линий и GLS -70%). Позиции только из forward match; backward — валидация NCC. Стрелки ED→ES по контурам; per-kernel strain на Green–Lagrange; GLS из кривой longitudinal.

- **Тип:** feature
- **Файлы:** `src/echo_personal_tool/domain/services/cardiac_cycle_detector.py`, `src/echo_personal_tool/application/workers/speckle_worker.py`, `tests/unit/test_ste_reproducibility.py`
- **Суть:** Добавлены `detect_cycle_boundaries` и `average_strain_curves` для выделения циклов по ED-пикам area-сигнала и post-hoc усреднения GLS-кривой по фазе. В `SpeckleTrackingWorker` включено multi-cycle усреднение longitudinal strain при `config.multi_cycle_average` и наличии >=2 циклов; добавлены тесты на детектор, ресемплинг-усреднение и воспроизводимость GLS (10 запусков).
