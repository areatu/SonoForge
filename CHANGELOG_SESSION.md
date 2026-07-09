# CHANGELOG_SESSION.md

**Назначение:** Автоматическая передача ключевого контекста между чатами Cursor.
**Правила чтения:** При старте нового чата — `AGENTS.md`, затем последние записи здесь (не весь файл).
**Лимиты:** Только суть, без кода.

---

## [2026-07-09 23:00] Bench: exclude 7 bad gold files + finetune norm fix
- **Тип:** fix + feature
- **Файлы:** `manifest.json`, `scripts/generate_manifest_from_gold.py`, `scripts/finetune_lv_seg.py`, `scripts/run_lv_auto_bench.py`, `src/echo_personal_tool/infrastructure/onnx_engine.py`
- **Суть:** Исключены 7 инстансов с плохими gold-масками (gold38/gold71/gold82 IoU ES<0.5 + gold58/gold112/gold69/gold29 IoU<0.7+Δ>15%). Добавлен `--exclude` в generate_manifest_from_gold.py. Исправлена нормализация пикселей в finetune_lv_seg.py (min-max→0-255). Добавлен `engine.crop_mode` property. Bench: 98 инстансов, IoU 0.851 PASS, zero-edit 81.1% PASS.

## [2026-07-08 22:26] LV auto: annulus endpoint snapping improved
- **Тип:** fix
- **Файлы:** `src/echo_personal_tool/domain/services/segmentation_service.py`, `bench/reports/lv_baseline_lvannulus_20260708.csv`
- **Суть:** Уточнён выбор септальной/латеральной точек МК с привязкой к базальной кромке маски; на Tier-1 вырос median IoU и снизилась ошибка annulus.

## [2026-07-08 21:30] Шаг 2: LA fine-tune + bench fixes
- **Тип:** feature + fix
- **Файлы:** `finetune_la_seg.py`, `calibrate_echonet_norm.py`, `run_la_auto_bench.py`, `bench_metrics.py`, `models/echonet_la_resnet50_224.onnx`
- **Суть:** LA ONNX на 57 gold ES (ROI crop, кэш DICOM); bench по всем instance; LAV через `calculate_chamber`; LV norm-калибровка хуже per_frame. LA gates не пройдены — нужен warm-start.

## [2026-07-08 18:30] Generate manifest.json from consolidated gold
- **Тип:** feature
- **Файлы:** `scripts/generate_manifest_from_gold.py`, `manifest.json`
- **Суть:** Скрипт генерирует manifest.json из единого gold-файла (lv_*.json) — 105 записей с ED/ES frame_index для каждого DICOM instance. Запуск: `python scripts/generate_manifest_from_gold.py`.

## [2026-07-07 22:35] Gold merge fix — per-instance dedup + repair script
- **Тип:** fix
- **Файлы:** `gold_store.py`, `scripts/repair_gold_collisions.py`, `tests/unit/test_gold_store.py`
- **Суть:** `merge_frame_into_gold` дедуплицирует по `(instance, phase)`, а не глобально по `(frame_index, phase)`; добавлены audit/dedupe/repair-from-backup и CLI `repair_gold_collisions.py`.

## [2026-07-06 21:30] LA auto — QC fixes + spec alignment
- **Тип:** fix
- **Файлы:** `la_segmentation_service.py`, `app_controller.py`, `run_la_auto_bench.py`, `locales/{en,ru}.json`, `test_la_segmentation_service.py`, `docs/superpowers/specs/2026-07-06-la-auto-segmentation-design.md`
- **Суть:** Подключён ellipse-fit residual (1−IoU), ROI и mask в QC; LA auto-refine читает `la_inference`; Save Gold для LA только ES/A4C; bench gate A с 5 ml или 8%; спека приведена к `gold/la_<uid>.json`.

## [2026-07-06 12:00] LV Auto Commercial Parity v2 — Phase 2a + 2b
- **Тип:** feature
- **Файлы:** `bench/`, `gold_store.py`, `bench_metrics.py`, `run_lv_auto_bench.py`, `onnx_engine.py`, `segment_roi.py`, `segmentation_service.py`, `lvef_simpson.py`, `user_preferences.py`, `viewer_widget.py`, `app_controller.py`, `main_window.py`, `model_manifest.json`, `locales/{ru,en}.json`
- **Суть:** Phase 2a: Tier-1 bench infrastructure (gold JSON I/O, metrics, bench runner, gold annotation UX via QSettings + context menu). Phase 2b: 224x224 model support in onnx_engine, ROI apex guard on sector trim, landmark fallbacks A/B in open_arc, quality gate v2 (spacing-aware MA < 3mm, arc depth < 0.15×MA, centroid outside ROI). 47 new unit tests, all passing.

## [2026-07-05 18:00] LV Auto ONNX Quality v1.5 — Per-Frame Segmentation
- **Тип:** feature + fix
- **Файлы:** `app_controller.py`, `segmentation_service.py`, `segment_roi.py`, `onnx_engine.py`, `model_manifest.json`, `ROADMAP.md`, `scripts/calibrate_echonet_norm.py`, `tests/unit/test_segmentation_service.py`
- **Суть:** MP4 ROI fix (_resolve_segment_roi_bounds делегирует resolve_segment_roi_xyxy для всех форматов); DICOM sector trim (SequenceOfUltrasoundRegions уже корректен, trim убран); adaptive Otsu threshold в logits_to_mask (clamp [0.35, 0.65]); embed upscale order=1; fixed norm v1.1 (fixed_if_available mode); phase-aware papillary (ED/ES se_length_ratio и depth_threshold_ratio); auto_refine manifest flag only (default true); calibrate_echonet_norm.py скрипт; 7 новых unit-тестов. FIX: DICOM trim убран (режет апекс), cine возврат None если frozen ROI не закэширован.

## [2026-07-05 20:00] LV Auto Temporal Fusion v1.0
- **Тип:** feature
- **Файлы:** `domain/models/temporal_fusion.py`, `domain/services/lv_temporal_fusion.py`, `app_controller.py`, `viewer_widget.py`, `main_window.py`, `model_manifest.json`, `tests/unit/test_lv_temporal_fusion.py`, `tests/unit/test_auto_segment_controller.py`
- **Суть:** Neighbor-aware contour fusion (N±2): translation registration, mask vote, node clamp (apex ratio), annulus fuse (center_ref), apex direction lock. Ghost overlays (G=center vs fused, Shift+G=neighbor, [/]=cycle). Neighbor points aligned to anchor canvas. Debug ROI overlay. P0 fusion hang fix. P1 annulus δ + refine after fusion. i18n. 45 tests.

## [2026-07-01 16:00] Playback timing, overlay i18n, test_i18n
- **Тип:** fix + feature
- **Файлы:** `app_controller.py`, `measurement_results_formatter.py`, `indexed_results_formatter.py`, `viewer_widget.py`, `tool_panel.py`, `main_window.py`, `locales/*.json`, `tests/unit/test_i18n.py`
- **Суть:** Timing compensation для cine; status/formatters через tr(); adaptive smooth off при playback; parity-тест локалей; tab titles reload.

## [2026-07-01 14:30] Caliper/playback fixes + i18n quick fixes
- **Тип:** fix
- **Файлы:** `app_controller.py`, `main_window.py`, `viewer_widget.py`, `system_bar.py`, `linear_measurement.py`, `locales/en.json`, `locales/ru.json`
- **Суть:** Warm-up playback: флаг до state change, таймер только для poll; Win32 maximize без showMaximized; калипер drag in-place без preview-линии + constrain start; en.json parity 60 ключей; reload_text viewer; display_text через tr().

## [2026-07-01 12:00] i18n: user_preferences_dialog translated
- **Тип:** feature
- **Файлы:** `user_preferences_dialog.py`, `ru.json`, `en.json`
- **Суть:** Все ~55 строк UI в UserPreferencesDialog заменены на tr() вызовы; добавлены 29 новых ключей в оба локале; переключение языка в диалоге теперь работает.

## [2026-06-30 18:30] Speckle fix, layout tests, docs
- **Тип:** fix
- **Файлы:** `speckle_tracking.py`, `orthanc_study_dialog.py`, `test_main_window_layout.py`, `test_lv_bezier_contour.py`, `test_simpson_live_feedback.py`, layout docs, `DICOM_VTI_tag_fix.md`, `rag-code-mcp.yaml`
- **Суть:** Инициализация `final_positions_prev` в speckle tracking; импорт OrthancSessionCache; 13 layout regression-тестов; стабилизация unit-тестов; spec/plan customize layout и заметки по VTI.

## [2026-06-29 23:00] MP4 keyframe index + scroll min_buffer
- **Тип:** feature
- **Файлы:** `video_reader.py`, `app_controller.py`, `test_video_reader.py`, `test_scroll_min_buffer.py`
- **Суть:** Индекс keyframe для seek назад; scroll prefetch сначала до min_buffer, затем до scroll_batch_size.

## [2026-06-29 22:00] JPEG-2000 multiframe: openjpeg + EOT index
- **Тип:** feature
- **Файлы:** `dicom_session.py`, `generate_synthetic_dicom.py`, `test_dicom_session.py`
- **Суть:** Декод J2K через openjpeg; `generate_frames` с Extended Offset Table; фикстуры BOT/EOT.

## [2026-06-29 21:00] P1: BOT / encapsulated frame index в DicomSession
- **Тип:** feature
- **Файлы:** `dicom_session.py`, `generate_synthetic_dicom.py`, `test_dicom_session.py`, `docs/.../dicom-scroll-performance-p1.md`
- **Суть:** `pydicom.encaps.generate_frames` + `parse_basic_offsets` для O(1) доступа к JPEG-кадрам без full-cine fallback.

## [2026-06-29 20:00] Fix scroll color flash и playback FPS
- **Тип:** fix
- **Файлы:** `viewer_widget.py`, `main_window.py`, `app_controller.py`, `test_viewer_display_mode.py`
- **Суть:** scroll_settled больше не передаёт grayscale в show_frame; цветной допплер без W/L; playback только через QTimer без двойных advance.

## [2026-06-29 18:00] DICOM scroll P0: debounce, two-phase load, fast path
- **Тип:** feature
- **Файлы:** `system_profiler.py`, `viewer_widget.py`, `app_controller.py`, `main_window.py`, `viewer_state.py`, `state_manager.py`, `test_scroll_debounce.py`, `test_scroll_two_phase_load.py`, `test_playback_prefetch.py`
- **Суть:** Колесо коалесцируется (debounce), целевой кадр грузится первым (batch=1), соседи — prefetch; при скролле `show_frame_fast`, после паузы — полный `show_frame` с оверлеями. `scroll_frame_selected` отделён от timeline.

## [2026-06-30 10:00] UI Enhancement: палитра, шрифты, иконки, collapse, анимации
- **Тип:** feature + refactor
- **Файлы:** `echopac_theme.py`, `bundled_fonts.py`, `system_bar.py`, `thumbnail_gallery.py`, `tool_panel.py`, `main_window.py`, `viewer_widget.py`, `resources/fonts/` (Inter, JetBrains Mono), `resources/icons/` (8 SVG)
- **Суть:** Тёплая палитра (#111827), скругления 4/8/12, 8px grid. Шрифты Inter (UI) + JetBrains Mono. 8 SVG-иконок в SystemBar. Gallery/ToolPanel collapse + QSplitter. Slide-анимация gallery 200ms, theme fade 150ms. Timeline: step ⏮/⏭ кнопки. Gallery large thumbnails 176×132. F11 fullscreen.

## [2026-06-27 23:30] STE: progressive zone deformation, preprocessing, quality improvements
- **Тип:** feature + fix
- **Файлы:** `speckle_tracking.py`, `speckle_worker.py`, `tracking_smoothing.py`, `speckle.py`, `myocardial_zone.py`, `speckle_overlay.py`, `viewer_widget.py`, `speckle_settings_dialog.py`, `aha_segments.py`, `contour_utils.py`
- **Суть:**
  1. Progressive zone deformation: двухпроходный трекинг с интерполяцией зоны от ED к ES на каждом кадре
  2. Preprocessing: CLAHE + log compression + median denoise (одинаковый для всех кадров)
  3. Outlier interpolation: невалидные kernel'ы заменяются линейной интерполяцией от соседей
  4. Iterative refinement: повторный трекинг с уточнёнными ED позициями (n_iterations=2)
  5. Quality-weighted smoothing: per-kernel NCC weights в UnivariateSpline
  6. Motion model: эндокард → внутрь, эпикард → наружу при систоле
  7. LV cavity center normals: правильное направление эпиокарда
  8. Kernel radius из config (hardcoded 10 → config.kernel_size // 2)
  9. ED/ES диалог с auto-detect checkboxes и ручным вводом
  10. Dynamic zone overlay: зона обновляется по кадрам из tracked positions
  11. Debug dump: positions/NCC/contours в ~/ECHO2026_ste_debug/
  12. AHA segment assignment + per-segment strain/quality computation
  - SpeckleConfig: 16 полей + 3 пресета (echo_pac: kernel=12, sr=8, incremental)
  - TrackingKernel: aha_segment, arc_length_param
  - StrainResult: tracked_positions_all, ncc_all_frames, segment_strain, segment_quality
  - 26 unit tests passing, quality ~62% на auto-contour кадрах 88/100

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


## [2026-06-24] DICOM tag dictionary + рефакторинг orthanc_dicom_json
- **Тип:** feature + refactor
- **Файлы:** `domain/services/dicom_tag_dictionary.py` (новый), `infrastructure/orthanc_dicom_json.py`, `tests/test_dicom_tag_dictionary.py` (новый)
- **Суть:** Легковесный словарь ~211 DICOM-тегов с lookup по int/hex/tuple. Заменены хардкод hex-констант в orthanc_dicom_json.py на импорт из словаря. Анализ Weasis показал, что Doppler/M-mode калибровка в ECHO2026 уже продвинутее.

## [2026-06-24] Speckle Tracking (2D Strain) — ядро + UI
- **Тип:** feature
- **Файлы:** `domain/models/speckle.py`, `domain/services/myocardial_zone.py`, `domain/services/speckle_tracking.py`, `domain/services/strain_computation.py`, `domain/services/cardiac_cycle_detector.py`, `presentation/speckle_overlay.py`, `presentation/strain_curve_widget.py`, `application/workers/speckle_worker.py`, `tests/unit/test_speckle_tracking.py`, `presentation/measurement_action.py`, `presentation/measures_menu.py`, `presentation/main_window.py`, `application/app_controller.py`, `presentation/viewer_widget.py`
- **Суть:** Block-matching speckle tracking с NCC, пирамидальный подход, sub-pixel точность. Dual-contour (Philips/Samsung стиль): эндокард + эпикард с фиксированной толщиной. GLS + radial strain, авто-определение ED/ES через FFT. Offline batch режим. UI: кнопка "Speckle Tracking" в Measures → Strain, AppController.run_speckle_tracking(), SpeckleOverlay + StrainCurveWidget.


## [2026-07-02 21:00] Viewer perf Phase 0/2 + Phase 3–4 unit tests
- **Тип:** feature
- **Файлы:** `infrastructure/pixel_utils.py`, `presentation/viewer_widget.py`, `tests/unit/test_wl_lut.py`, `tests/bench/test_viewer_perf.py`, `tests/unit/test_frame_cache.py`, `tests/unit/test_playback_prefetch.py`
- **Суть:** LUT-based W/L (`apply_wl_lut`, uint16 через numpy indexing), benchmark suite с таблицей до/после, прямые тесты `loaded_before`, adaptive batch, small-loop prefetch и double-next skip.

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
