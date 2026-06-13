# CHANGELOG_SESSION.md

**Назначение:** Автоматическая передача ключевого контекста между чатами Cursor.
**Правила чтения:** При старте нового чата Cursor ОБЯЗАН прочитать этот файл после AGENTS.md.
**Лимиты:** Максимум 30 записей. При превышении старые записи удаляются или архивируются. Не дублировать код, только суть.

---

## [2026-06-12] Simpson dual workflow — дизайн и план
**Тип:** design + plan
**Файлы:** `docs/superpowers/specs/2026-06-12-simpson-dual-workflow-design.md`, `docs/superpowers/plans/2026-06-12-simpson-dual-workflow.md`
**Суть:**
- Два параллельных пути Simpson: **Manual** (Diastole/Systole, оранжевый контур) и **MBS** (EDV Auto/ESV Auto, зелёный контур); раскладка панели — два блока × (4C | 2C).
- Удалить маркеры D/S (`ed_frame_index`/`es_frame_index`, горячие клавиши, метки на таймлайне); фаза только из кнопки + `frame_index` контура.
- После ED: подсказка в статус-баре/overlay + мигание ES-кнопки (Systole / ESV Auto); координатор — `MainWindow`, анимация — `MeasurementToolsPanel`.

## [2026-06-13] LvViewMetrics и расширенный LvefResult
- **Тип:** feature
- **Файлы:** `src/echo_personal_tool/domain/models/measurements.py`, `src/echo_personal_tool/domain/models/__init__.py`, `tests/unit/test_measurement_models.py`
- **Суть:** Добавлен `LvViewMetrics` (метрики по проекции 4C/2C); `LvefResult` теперь хранит `a4c`/`a2c` вместо плоских `edv_ml`/`esv_ml`. Подготовка к dual-view Simpson workflow.
- Measurements: частичные результаты после одного ED; русские метки по ракурсам (`Длина ЛЖ 4C`, `КДО ЛЖ 4C`, `КСО ЛЖ 4C`, аналогично 2C); площадь ЛЖ не показывать; overlay — длина + объём.
- Причина пустой панели сейчас: `lvef_simpson.calculate()` возвращает `None` без пары ED+ES.
- Авто-сегментация (`I`) — out of scope; реализация по плану в 8 задачах.

## [2026-06-13] Simpson dual workflow — реализация (8 задач)
- **Тип:** feature
- **Файлы:** `domain/models/measurements.py`, `domain/calculations/lvef_simpson.py`, `application/state_manager.py`, `application/app_controller.py`, `presentation/measurement_tools_panel.py`, `presentation/main_window.py`, `presentation/viewer_widget.py`, `presentation/measurement_panel.py`, `tests/unit/*`
- **Суть:** Manual/MBS Simpson с partial per-view метриками; удалены D/S маркеры; ED→ES подсказка + blink; русские метки в панели; numeric overlay на кадре. 223 unit-теста проходят.

---

## [2026-06-13] Simpson calculate — partial per-view metrics
- **Тип:** feature
- **Файлы:** `src/echo_personal_tool/domain/calculations/lvef_simpson.py`, `tests/unit/test_lvef_simpson.py`, `tests/unit/test_measurement_controller.py`, `tests/unit/test_mbs_lite_service.py`
- **Суть:** `calculate()` возвращает `LvefResult` с `a4c`/`a2c` (`LvViewMetrics`); при одном ED — частичные метрики без LVEF. Добавлены `_contour_length_mm`, `_contour_volume_ml`, `_build_view_metrics`, `format_contour_overlay`.

## [2026-06-13] MeasurementPanel — Russian per-view LV labels
- **Тип:** feature
- **Файлы:** `src/echo_personal_tool/presentation/measurement_panel.py`, `tests/unit/test_measurement_panel.py`
- **Суть:** `_format_lvef_section` показывает метрики по проекциям 4C/2C с русскими подписями (Длина, КДО, КСО, ФВ); частичные данные без КСО/ФВ.

## [2026-06-13] Fix MeasurementToolsPanel click KeyError
- **Тип:** fix
- **Файлы:** `src/echo_personal_tool/presentation/measurement_tools_panel.py`, `tests/unit/test_measurement_tools_panel.py`
- **Суть:** QPushButton.clicked передаёт bool checked в lambda; без `_checked=False` view становился False и ломал `_VIEW_MAP`. Интеграционный тест изолирован от устаревшего `_format_lvef_section`.

- **Тип:** feature + refactor
- **Файлы:** `viewer_state.py`, `state_manager.py`, `app_controller.py`, `measurement_tools_panel.py`, `main_window.py`, `viewer_widget.py`, связанные тесты
- **Суть:** Удалены `ed_frame_index`/`es_frame_index`, горячие клавиши D/S, `mark_ed`/`mark_es`. Панель разделена на Manual и MBS; после ED — overlay + мигание Systole/ESV Auto. Auto-segment (`I`) временно отключён до активного Simpson workflow.

## [2026-06-13] ViewerWidget overlay и русские метки Measurements
- **Тип:** feature
- **Файлы:** `viewer_widget.py`, `measurement_panel.py`, `tests/unit/test_contour.py`, `tests/unit/test_measurement_panel.py`, `tests/unit/test_measurement_wiring.py`
- **Суть:** Убраны ED/ES маркеры на таймлайне; overlay показывает длину/объём через `format_contour_overlay` (в т.ч. при drag). Панель измерений — русские метки по проекциям (`Длина ЛЖ 4C`, `КДО ЛЖ 4C`, `КСО ЛЖ 4C`, `ФВ ЛЖ`).

## [2026-06-13] ViewerWidget — markers off, overlay on drag
- **Тип:** feature
- **Файлы:** `src/echo_personal_tool/presentation/viewer_widget.py`, `tests/unit/test_contour.py`
- **Суть:** Убраны ED/ES метки на таймлайне; фаза контура по умолчанию ED. Overlay LV-контура через `format_contour_overlay` при завершении и после drag точек.

## [2026-06-13] Simpson live feedback без Enter
- **Тип:** fix
- **Файлы:** `app_controller.py`, `viewer_widget.py`, `main_window.py`, `measurement_panel.py`, `lvef_simpson.py`, `measurements.py`, `tests/unit/test_simpson_live_feedback.py`
- **Суть:** После 3-й точки и drag — немедленный пересчёт в overlay и панели. Без PixelSpacing — px/px³ с пометкой. Overlay восстанавливается при возврате на кадр с контуром.

## [2026-06-13 12:00] DICOM spacing fallbacks и ручная калибровка K
- **Тип:** feature
- **Файлы:** `pixel_spacing_resolver.py`, `dicom_metadata_mapper.py`, `metadata.py`, `viewer_state.py`, `state_manager.py`, `app_controller.py`, `viewer_widget.py`, `main_window.py`, `measurement_panel.py`, `tests/unit/test_pixel_spacing_resolver.py`, `tests/unit/test_dicom_metadata_mapper.py`
- **Суть:** PixelSpacing из нескольких DICOM-тегов (в т.ч. SequenceOfUltrasoundRegions). Ручная калибровка по шкале глубины: K — линия, Enter — мм, Shift+K — сброс. Manual override имеет приоритет над DICOM.

## [2026-06-13] MBS v1.1 — active contour, A2C, ED→ES
- **Тип:** feature
- **Файлы:** `active_contour_refine.py`, `lv_shape_template.py`, `mbs_lite_service.py`, `viewer_widget.py`, `main_window.py`, `docs/superpowers/specs/2026-06-13-mbs-advanced-design.md`, `docs/superpowers/plans/2026-06-13-mbs-advanced.md`, `tests/unit/test_active_contour_refine.py`, `tests/unit/test_mbs_propagation.py`, `tests/unit/test_mbs_lite_service.py`
- **Суть:** После 3 landmarks — discrete open snake refine к градиенту; A2C barycentric template; ESV Auto переносит ED model contour как init и уточняет на ES-кадре без повторных кликов.

## [2026-06-13] MBS v1.1 fixes — dome, bulk move, no propagation
- **Тип:** fix
- **Файлы:** `mbs_lite_service.py`, `lv_shape_template.py`, `viewer_widget.py`, `main_window.py`, `contour_geometry.py`, `tests/unit/test_mbs_lite_service.py`, `tests/unit/test_contour_geometry.py`, `docs/superpowers/specs/2026-06-13-mbs-advanced-design.md`
- **Суть:** Восстановлен sinusoidal dome (исправлен «треугольник»); ED→ES propagation удалён; auto-refine отключён (opt-in R); Alt+drag translate всего контура; `[`/`]` — normal shift ±3 px.

## [2026-06-13] R для manual+model; убраны bulk-коррекции
- **Тип:** fix
- **Файлы:** `viewer_widget.py`, `main_window.py`, `contour_geometry.py`, `mbs_lite_service.py`, `tests/unit/test_contour_geometry.py`, `tests/unit/test_mbs_lite_service.py`, `docs/superpowers/specs/2026-06-13-mbs-advanced-design.md`
- **Суть:** **R** — active contour refine для manual и model LV open-arc на текущем кадре. Удалены Alt+drag translate всего контура и `[`/`]` normal shift (искажали контур).

## [2026-06-13] RBF Gaussian contour drag (QLAB-style)
- **Тип:** feature
- **Файлы:** `contour_geometry.py`, `viewer_widget.py`, `tests/unit/test_rbf_contour_deform.py`, `tests/unit/test_spline_editor.py`, `tests/unit/test_contour_geometry.py`
- **Суть:** Drag узлов контура через Gaussian RBF от курсора; MA-концы pinned; σ от zoom viewRange; подсветка активных узлов; заменён drag_node_local.
