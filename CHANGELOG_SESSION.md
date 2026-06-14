# CHANGELOG_SESSION.md

**Назначение:** Автоматическая передача ключевого контекста между чатами Cursor.
**Правила чтения:** При старте нового чата — `AGENTS.md`, затем последние записи здесь (не весь файл).
**Лимиты:** Максимум 30 записей; при превышении удаляются самые старые. Только суть, без кода.

---

## [2026-06-13 21:02] Preview-only thumbnail worker по умолчанию 96
- **Тип:** feature
- **Файлы:** `thumbnail_loader_worker.py`, `test_thumbnail_qimage.py`
- **Суть:** Worker рендерит preview по запрошенному размеру (default 96) без второй full-size фазы.

## [2026-06-13 21:04] Уточнена preview_only логика и error-path тест
- **Тип:** fix
- **Файлы:** `thumbnail_loader_worker.py`, `test_thumbnail_qimage.py`
- **Суть:** Явная ветка preview_only в `run()`; тест эмиссии `failed` при исключении reader.

## [2026-06-13 21:06] Strict preview-only MVP режим
- **Тип:** fix
- **Файлы:** `thumbnail_loader_worker.py`, `test_thumbnail_qimage.py`
- **Суть:** Убран full-size рендер из worker; параметр `preview_only` задокументирован как игнорируемый в MVP.

## [2026-06-13 21:07] Scheduler thumbnail в AppController
- **Тип:** feature
- **Файлы:** `app_controller.py`, `test_app_controller_thumbnail_priority.py`
- **Суть:** ThumbnailScheduler с приоритетами P0/P1/P2; main frame не блокируется thumbnail backlog.

## [2026-06-13 21:12] QA thumbnail scheduler
- **Тип:** fix
- **Файлы:** `app_controller.py`, `test_app_controller_thumbnail_priority.py`
- **Суть:** Очистка `_thumbnail_instances` при success/fail; release-slot после failed.

## [2026-06-13 21:13] In-flight state thumbnail
- **Тип:** fix
- **Файлы:** `app_controller.py`, `test_app_controller_thumbnail_priority.py`
- **Суть:** Явный учёт `_thumbnail_in_flight` в dispatch/finish/fail.

## [2026-06-13 21:18] LocalBrowser lazy preview
- **Тип:** feature
- **Файлы:** `local_browser.py`, `test_local_browser_thumbnail_requesting.py`
- **Суть:** Visibility-driven preview вместо eager-запросов всех series при populate.

## [2026-06-13 21:21] Fallback и scroll-jank fix
- **Тип:** fix
- **Файлы:** `local_browser.py`, `test_local_browser_thumbnail_requesting.py`
- **Суть:** Сигнатура loader на set_loader; debounce scroll-trigger; non-blocking update.

## [2026-06-13 21:24] LocalBrowser helper-сигнатуры
- **Тип:** fix
- **Файлы:** `local_browser.py`
- **Суть:** `_collect_visible_instances` / `_collect_nearby_instances` для plan-совместимости.

## [2026-06-13 21:25] Initial preview и readiness метрики
- **Тип:** feature
- **Файлы:** `main_window.py`, `app_controller.py`, `test_main_window_doppler.py`
- **Суть:** `request_visible_previews()` после populate; лог-точки scan/preview/frame timing.

## [2026-06-13 21:30] Дубликат preview и таймер
- **Тип:** fix
- **Файлы:** `main_window.py`, `test_main_window_doppler.py`
- **Суть:** Убран лишний preview trigger; сброс click-to-frame таймера на load failure.

## [2026-06-13 21:32] Единая точка initial preview
- **Тип:** fix
- **Файлы:** `main_window.py`, `local_browser.py`, `test_local_browser_thumbnail_requesting.py`
- **Суть:** Initial preview только из `_on_studies_loaded`; убран автозапрос из `populate()`.

## [2026-06-13 21:40] Preview-thumbnail тесты
- **Тип:** fix
- **Файлы:** `local_browser.py`, `test_thumbnail_qimage.py`
- **Суть:** Флаг `_building_tree` подавляет лишние запросы при populate.

## [2026-06-13 21:45] Preview без искажения пропорций
- **Тип:** fix
- **Файлы:** `browser_item_delegate.py`, `thumbnail_loader_worker.py`, `test_thumbnail_qimage.py`
- **Суть:** KeepAspectRatio в delegate и preview scaling.

## [2026-06-13 22:00] MVP шаг A: Калибровка в Setup
- **Тип:** feature
- **Файлы:** `main_window.py`, `measurement_tools_panel.py`, `test_measurement_tools_panel.py`
- **Суть:** Убран Doppler toggle из UI; кнопка «Калибровка» в Setup.

## [2026-06-13 23:30] MVP шаг B: session persistence
- **Тип:** feature
- **Файлы:** `study_measurement_session.py`, `app_controller.py`, `state_manager.py`
- **Суть:** Измерения накапливаются по study_uid; не сбрасываются при смене instance.

## [2026-06-14 00:15] MVP шаг C: click-click калипер
- **Тип:** feature
- **Файлы:** `viewer_widget.py`, `test_linear_caliper_click_click.py`
- **Суть:** Линейный калипер click→click с live preview и session store.

## [2026-06-14 01:00] Caliper button и All Diastole chain
- **Тип:** fix
- **Файлы:** `viewer_widget.py`, `measurement_tools_panel.py`, `main_window.py`
- **Суть:** 2-й клик через mousePressEvent; Caliper в Setup; IVSd→LVEDD→LVPWd автоматически.

## [2026-06-14 02:00] MVP шаг D2: LAV/RAV/RV Simpson
- **Тип:** feature
- **Файлы:** `chamber_simpson.py`, `measurement_panel.py`, `main_window.py`, `mbs_lite_service.py`
- **Суть:** LA/RA/RV объёмы через Simpson; панели ЛП/ПП/ПЖ; LAV Bi 4C→2C ES.

## [2026-06-14 04:00] Overlay и калиперы по кадрам
- **Тип:** fix
- **Файлы:** `viewer_widget.py`, `main_window.py`, `study_measurement_session.py`
- **Суть:** Overlay/caliper per-frame для cine; LAV Bi шаг 2 только по кнопке на 2C.

## [2026-06-14 05:00] MVP E1+E2: рост/вес и indexed
- **Тип:** feature
- **Файлы:** `body_surface.py`, `measurement_panel.py`, `study_measurement_session.py`
- **Суть:** BSA (Du Bois), индексированные объёмы и диаметры (mL/m², mm/m²).

## [2026-06-14 06:00] LV Lamé open-arc template
- **Тип:** feature
- **Файлы:** `lv_shape_template.py`, `mbs_lite_service.py`, `viewer_widget.py`
- **Суть:** Piecewise Lamé по хорде МК с пресетами A4C/A2C ED/ES; manual и model LV.

## [2026-06-14 07:00] Lamé apex + R smoothing
- **Тип:** fix
- **Файлы:** `lv_shape_template.py`, `contour_geometry.py`, `mbs_lite_service.py`
- **Суть:** Foot-point→apex; R — Laplacian smooth с фиксацией MA.

## [2026-06-13 14:00] Lamé spec warp + равномерный resample
- **Тип:** fix
- **Файлы:** `lv_shape_template.py`, `contour_geometry.py`, `mbs_lite_service.py`
- **Суть:** Warp P(u)=B(u)+h(u)·d̂; `resample_open_arc_landmarks` septal→apex→lateral.

## [2026-06-13 16:00] Arc-length split узлов
- **Тип:** fix
- **Файлы:** `contour_geometry.py`, `mbs_lite_service.py`
- **Суть:** Число узлов по доле длины дуги Lamé; устранены вылеты septal.

## [2026-06-13 18:00] Без pin apex на узле
- **Тип:** fix
- **Файлы:** `lv_shape_template.py`, `contour_geometry.py`, `mbs_lite_service.py`
- **Суть:** Lamé через foot-point; фиксируются только концы МК; apex — метаданные клика.

## [2026-06-14 18:00] Завершение блока MVP измерений и калибровки
- **Тип:** feature + fix
- **Файлы:** `viewer_widget.py`, `main_window.py`, `app_controller.py`, `measurement_panel.py`, `measurement_tools_panel.py`, `linear_measurement.py`, `state_manager.py`, `study_measurement_session.py`, `AGENTS.md`, `.cursor/rules/changelog.mdc`
- **Суть:** Калибровка non-DICOM: вертикальный отрезок справа (96% ширины), 2 клика → диалог мм, крупный центральный оверлей. LAV 4C/Bi, S ПП, RAV — ручной Simpson 3 клика (MBS-lite только LV). Linear geometry без px. S ЛП в панели после LAV. Кнопка «Сброс» — контуры, caliper, Doppler, калибровка. Правило: changelog только в конце сессии, лимит 30 записей.
