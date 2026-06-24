# CHANGELOG_SESSION.md

**Назначение:** Автоматическая передача ключевого контекста между чатами Cursor.
**Правила чтения:** При старте нового чата — `AGENTS.md`, затем последние записи здесь (не весь файл).
**Лимиты:** Максимум 30 записей; при превышении удаляются самые старые. Только суть, без кода.

---

## [2026-06-23] Оверлей между кадрами + «По умолчанию» в настройках
- **Тип:** fix + feature
- **Файлы:** `main_window.py`, `viewer_widget.py`, `app_controller.py`, `user_preferences.py`, `user_preferences_dialog.py`, `test_user_preferences.py`
- **Суть:** Оверлей результатов не пересчитывается при смене кадра одного cine (только при смене инстанса или измерений); позиция сохраняется per-instance. В диалоге настроек — кнопка «По умолчанию» с подтверждением (сброс к factory defaults, last_opened_folder сохраняется).

## [2026-06-23] ONNX v1.1 откат — остаёмся на v1
- **Тип:** fix
- **Файлы:** (код без изменений относительно HEAD; решение зафиксировано в changelog/ROADMAP)
- **Суть:** Локальная реализация v1.1 (fixed mean/std, PCA annulus + longest-chord fallback) ухудшила auto LV контур; откат к v1 pipeline. Annulus отдельно не уточняем — v1.1 отложен.

## [2026-06-23] Сессия: DICOMweb Orthanc + RV FAC + доработки (итог)

- **Тип:** feature + fix
- **Ветка:** `feat/phase2-echopac-ui` @ `7490405` (push на `origin`)
- **Файлы (ключевые):** `orthanc_*.py`, `fake_dicom_web_client.py`, `orthanc_study_dialog.py`, `server_settings*.py`, `rv_shape_template.py`, `main_window.py`, `system_bar.py`, `domain/ports.py`, `README.md`, `ROADMAP.md`, `DICOM_parsing.md`, спеки/планы в `docs/superpowers/`
- **Суть:**
  - **DICOMweb v1:** QIDO/WADO (httpx), session cache, mock offline, диалог «Загрузить с сервера…», настройки сервера; merge из worktree `feat/dicomweb-orthanc`; fix shadowing `domain/ports.py`.
  - **DICOMweb v1.1 (DICOM_parsing.md):** cancel worker + clear session; суммарный progress; lifecycle httpx в диалоге; QIDO `includefield`; парсинг `00201209` → «N инст.» в дереве серий.
  - **RV FAC:** одна кнопка FAC, crescent open-arc (3 клика), ED→blink→ES, FAC% в overlay; S ПП закрыт (площадь через RAV 4C).
- **Чеклист сессии:**
  - [x] Реализация DICOMweb (10 задач плана)
  - [x] Merge + push в `feat/phase2-echopac-ui`
  - [x] Коммит RV FAC отдельно
  - [x] README обновлён
  - [x] Замечания `DICOM_parsing.md` закрыты
  - [x] `instance_count` в `parse_series`
  - [ ] Workplace: записать реальные JSON-фикстуры с Orthanc (`curl` в spec)
  - [ ] Manual smoke на работе с живым сервером
- **Следующий приоритет:** DICOMweb smoke + фикстуры; ONNX v1.1 отложен (см. ROADMAP)

## [2026-06-19 45:00] ROADMAP, чеклисты, LAV/RAV овал, LV Auto
- **Тип:** feature
- **Файлы:** `ROADMAP.md`, `lv_shape_template.py`, `mbs_lite_service.py`, `measures_menu.py`, `main.py`, `docs/superpowers/specs/2026-06-19-measurement-workflow-design.md`, `docs/superpowers/specs/2026-06-11-display-ux-design.md`, `docs/superpowers/specs/2026-06-19-onnx-lv-auto-segment-design.md`, `docs/superpowers/plans/2026-06-19-onnx-lv-auto-segment.md`
- **Суть:** Единый `ROADMAP.md` с галочками по коду; обновлены чеклисты superpowers (workflow ✅, display UX, ONNX v1); п. 7 measurement-workflow снят как ошибочный; LAV/RAV — овальный шаблон (85% короткая ось); убраны кнопки Simpson Biplane из LV Auto; подавлено KDE-предупреждение в `main.py`.

## [2026-06-19 44:00] Результаты, PDF, overlay по ролику
- **Тип:** feature
- **Файлы:** `tool_panel.py`, `measurement_results_dialog.py`, `measurement_report_formatter.py`, `measurement_report_pdf.py`, `indexed_results_formatter.py`, `main_window.py`, `app_controller.py`, тесты
- **Суть:** Кнопка «Результаты» под рост/вес — окно отчёта по исследованию (последнее значение при дублях) и экспорт PDF с автооткрытием; LAVi/RAVi в overlay всегда при BSA, остальные индексы — при отклонении; overlay привязан к текущему instance, отчёт — study-wide.

## [2026-06-19 43:00] UI: настройки, overlay справа, рост/вес без суффиксов
- **Тип:** fix
- **Файлы:** `system_bar.py`, `main_window.py`, `viewer_widget.py`, `tool_panel.py`
- **Суть:** Убраны «cm»/«kg» у полей рост/вес; study overlay справа с выравниванием текста слева; Auto Segment убран, добавлена кнопка «Настройки».

## [2026-06-19 42:00] UI: system bar, overlay, рост/вес
- **Тип:** fix
- **Файлы:** `system_bar.py`, `viewer_widget.py`, `tool_panel.py`
- **Суть:** Кнопки Caliper/Calibration/Reset закреплены справа; статус слева после имени файла; study overlay слева; рост/вес — крупнее, целые см/кг, на 10% выше на панели.

## [2026-06-19 41:00] RAV 4C — Simpson как LAV 4C
- **Тип:** fix
- **Файлы:** `main_window.py`, `measurement_results_formatter.py`, тесты
- **Суть:** RAV 4C: open-arc Simpson (TV septal → lateral → apex → точки → Enter); результат RAV 4C в frame и study overlay.

## [2026-06-19 40:00] LAV: результат в оверлее после контура
- **Тип:** fix
- **Файлы:** `measurement_results_formatter.py`, `chamber_simpson.py`, `main_window.py`, `viewer_widget.py`, тесты
- **Суть:** LAV из Simpson (la_simpson) выводится в study/frame overlay после Enter; исправлен spacing для MP4 без DICOM; apex_landmark при завершении LA-дуги.

## [2026-06-19 39:00] Площадь/Объём и LAV: упрощённый контур
- **Тип:** fix
- **Файлы:** `planimeter.py`, `viewer_widget.py`, `main_window.py`, `lvef_simpson.py`, `planimeter_formatter.py`, `test_planimeter.py`
- **Суть:** Площадь и Объём — замкнутый полигон (двойной щелчок), точки двигаются по одной; LAV 4C/2C — Simpson как LV (МК → apex → дуга → Enter), без LAL-калипера.

## [2026-06-19 38:00] Общие: Площадь и Объём (сплайн)
- **Тип:** feature
- **Файлы:** `planimeter.py`, `planimeter_formatter.py`, `viewer_widget.py`, `main_window.py`, `measures_menu.py`, `contour.py`, `measurements.py`, тесты
- **Суть:** Площадь — замкнутый сплайн-контур (Площадь1, 2…); Объём — open-arc Simpson (Объем1, 2…); результаты в overlay и study summary.

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
