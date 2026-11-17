# Обзор: 8 пунктов интерфейса от 2026-11-17

> **Снимок на 2026-11-17.** Документ фиксирует состояние на эту дату и не обновляется вслед за кодом: актуальное состояние — в коде, `README.md`, HELP и открытых issues.

Ветка `arena/ae1d55b4-sonoforge`. Все 8 пунктов закрыты кодом и тестами; ниже —
корневая причина, решение и что закреплено тестами.

---

## 1. dP/dt МР/ТК: направляющие 100 → 300 см/с и Δt из двух кликов

**Причина (две отдельные).** Первая: инструмент «интервал» был свободным
измерением — врач ставил оба клика куда курсор придёт, и ничто на экране не
говорило, к какой скорости привязан клик. Для dP/dt это неверно по сути:
`dP/dt = ΔP / Δt`, где `Δt` — время подъёма струи регургитации от 1 м/с до
3 м/с (МР) или до 2 м/с (ТК); высота клика задана физикой, выбирается только
время. Вторая: значения `mr.dpdt` / `tr.dpdt` считались и попадали в доменную
модель, но **не печатались в results-overlay** — отсюда «результата не видно».

**Решение.**

* `domain/doppler_catalog.py`: `DPDT_CLICK_VELOCITIES_CM_S` (МР 100 → 300,
  ТК 100 → 200), `DPDT_SNAP_RADIUS_PX`, `dpdt_click_velocity_cm_s(label, *, second)`.
* `presentation/viewer/doppler_interval_guide.py` (новый модуль-сотрудник):
  `DopplerIntervalGuide` знает, к какой скорости привязан следующий клик,
  зеркалит её на ту сторону базовой линии, где реально нарисована струя
  (инвертированный спектр не остаётся без ориентира; нечитаемый буфер — фолбэк
  «выше»), рисует пунктирную направляющую и отдаёт её plot-`y`.
* `presentation/doppler_overlay.py`: `interval_guide` — свойство-ссылка на
  сотрудника; направляющая пересчитывается при смене инструмента, метки
  интервала, после первого и после второго клика, при очистке состояния.
  `overlay` больше не держит ни одного метода геометрии направляющей.
* `presentation/viewer_widget.py`: кроссхэйр берёт `y` направляющей, если она
  есть, — `x` остаётся свободным, оба клика ложатся точно на 100 и 300
  (ТК 100 и 200) см/с.
* `presentation/viewer/doppler_controller.py`: `interval_guide_prompt()` —
  подсказка под кликером называет скорость и клик: «1-й клик — 100 см/с на
  восходящем колене струи» / «2-й клик — 300 см/с» (en: «1st/2nd click —
  {velocity} cm/s»), ключи `doppler.dpdt_click_start` / `doppler.dpdt_click_end`.
* `domain/services/measurement_results_formatter.py`: две строки `_push` в
  доплеровском блоке — `dP/dt ЛЖ` и `dP/dt ПЖ` (`mmHg/s`), значения из
  `lv_dpdt_mmhg_s` / `rv_dpdt_mmhg_s` (входы — `dop.mr_dpdt_ms` /
  `dop.tr_dpdt_ms`); каталог и ASE T6 получили подписи «dP/dt ЛЖ»/«dP/dt ПЖ»
  (en «LV dP/dt»/«RV dP/dt»).

**Цепочка (одна, без дублей).** два клика → `mr_dpdt_ms` / `tr_dpdt_ms` →
`lv_dpdt_mmhg_s` / `rv_dpdt_mmhg_s` (`Δt ≤ 0` → `None`) → калькулятор `DPDT` в
registry → overlay и отчёт.

**Тесты.** `test_doppler_interval_guide.py` (12: каталог, зеркалирование,
скрытие для свободных интервалов, полоса-превью), `test_presentation_doppler_overlay.py`,
`test_doppler_mode_units.py` — **197 passed**; `test_measurement_results_formatter.py`,
`test_dpdt_calculator.py`, `test_ase_table6.py`, `test_measurement_catalog.py`,
`test_formatting_unification.py` — зелёные.

---

## 2. Две колонки отчёта: плотно, без белых полос

**Причина.** Правая колонка добивалась пустотой до высоты левой: каждая
«ячейка» таблицы резервировала максимум высоты своей пары, поэтому короткая
группа оставляла полосу под собой.

**Решение** (`infrastructure/measurement_report_pdf.py`): `_two_column_groups`
строит две рамки, высота каждой — по фактическому содержимому
(`Frame(..., height=…)`), внутренний отступ `_FRAME_PADDING = 6.0` pt,
межколоночный зазор `_COLUMN_GAP = 4 mm`. Поток собирается `_AnchorSink`, чтобы
не потерять якоря (без него ссылки в содержании «съезжают»).

**Проверка.** anchors 106/106; максимальный `x` содержимого 511.2 pt ≤ 544.25 pt
(полоса A4 минус поля); `_two_columns_content_width() = A4[0] − 36 мм − 12 pt`.
Тесты: `test_measurement_report_pdf.py`, `test_report_*.py`.

---

## 3. s′ ПЖ в отчёте

**Причина.** Систолическая скорость фиброзного кольца ПЖ считалась и была в
модели, но в печатный документ не попадала — в отчёте оставались только
левые TDI-величины.

**Решение** (`domain/services/report_builder.py`): строка s′ ПЖ печатается
отдельной записью рядом с остальными доплеровскими величинами, с единицей и
подписью из каталога.

**Тесты.** `test_report_*.py` (в наборе из 290).

---

## 4. Peak-калиперы в отчёте подписаны дисплейными именами

**Причина.** В отчёт и на капшен каплеров уходила сохранённая метка
(`s_prime_rv`, `s_sept`, …) — сырой идентификатор, а не клиническое имя.

**Решение** (`domain/services/nomenclature.py`): `_MARKER_TO_CATALOG` и
`marker_label()`: `s_prime_rv` → «s′ ПЖ», `s_sept` → «s′ септ.», `e_sept` →
«e′ септ.». Метка в документе остаётся прежней (совместимость хранения), а
отчёт и подпись капшена (`doppler_overlay.peak_marker_caption`) читают
дисплейное имя. Flow-пики и неизвестные метки печатаются как раньше. Ключей
`tdi.a_prime_sept/lat` в каталоге нет, поэтому `e`/`a` печатаются как есть —
выдумывать подписи нельзя.

**Тесты.** `test_doppler_mode_units.py -k Caption` (7), `test_report_*.py`.

---

## 5. Provenance для калиперов и dP/dt

**Причина.** По напечатанному значению нельзя было восстановить, откуда оно
взялось: ни калибровки, ни исходных кликов.

**Решение.**

* `domain/models/linear_measurement.py`: у линейного измерения есть
  `measurement_id` (каталожная цель калипера) и калибровка, по которой
  посчитана длина.
* `domain/services/doppler_provenance.py`: для dP/dt сохраняются оба времени
  кликов и обе скорости, между которыми взят интервал.

Значение становится воспроизводимым при разборе исследования: видно и цель
измерения, и масштаб, и точки, между которыми считалось.

**Тесты.** `test_report_*.py`, `test_viewer_measurement_geometry.py`.

---

## 6. Dist1…Dist5 убраны из отчёта

**Причина.** Универсальный калипер (`DistN`) — вспомогательный инструмент для
замера «на глаз»; в клиническом документе он только шумит и не имеет цели.

**Решение** (`domain/services/report_builder.py`): измерения с меткой
`GENERIC_DIST_LABEL_PREFIX` (`Dist…`) отфильтровываются при сборке отчёта.
В просмотрщике и в сохранённом документе они остаются — убирается только
печать.

**Тесты.** `test_report_*.py`, `test_measurement_results_formatter.py`.

---

## 7. Лаг при первом нажатии Z (лупа)

**Причина.** Первое удержание `Z` на Windows 10 замирало на 3–5 с: именно это
нажатие оплачивало `import cv2` (модуль линзы), сборку SVG-курсора и создание
первого полупрозрачного дочернего виджета процесса — то есть аллокацию backing
store композитором. Ничего из этого не зависит от клика.

**Решение.**

* `presentation/viewer/magnifier_controller.py`: `schedule_warmup()` ставит
  `QTimer.singleShot(0, self._warm_up)`; `_warm_up()` собирает курсор и линзу.
  Флаг однократности (`_warmup_scheduled`) живёт в контроллере — у
  `ViewerWidget` не появилось ни атрибута, ни метода.
* `presentation/viewer_widget.py`: `showEvent` вызывает
  `self._magnifier_controller.schedule_warmup()` — кадр уже на экране, работа
  ложится между событиями, а не перед кадром.
* `presentation/magnifier_cursor.py` (новый модуль): `magnifier_cursor()`,
  `ZOOM_CURSOR_HOTSPOT = (9, 9)`; глиф грузится тем же SVG-загрузчиком, что и
  хром, фолбэк — `CrossCursor`. Контроллер использует его и при прогреве, и на
  первом показе.

**Почему это безопасно.** Прогрев — оптимизация: `RuntimeError`/`TypeError`/
`ValueError`/`ImportError` логируются на уровне `DEBUG`, линза просто создастся
по требованию, как раньше; выключенная лупа ничего не прогревает; повторные
`showEvent` не пересобирают линзу.

**Побочная уборка.** Заодно удалены четыре мёртвых метода `ViewerWidget`
(`_remove_rendered_contour`, `_update_drag_overlay`, `_repaint_contour_view`,
`_ensure_label_picker`) — ни одного вызова в `src` или тестах; из-за них потолок
class-size нельзя было опустить, хотя правка пункта 1 и 7 его требовала.

**Тесты.** `test_viewer_loupe_warmup.py` (7: ожидание очереди событий,
идемпотентность, выключенная лупа, сломанная фабрика, фолбэк курсора),
`test_magnifier_trigger.py`, `test_qh3_magnifier_owner.py`,
`test_viewer_zoom_loupe.py` — зелёные.

---

## 8. Changelog и этот обзор

* `changelog.d/005-feat-doppler-dpdt-guides.md` — пункт 1 (направляющие, Δt,
  результат в overlay и отчёт).
* `changelog.d/005-feat-report-ui-batch-8-items.md` — пункты 2–6 (колонки,
  s′ ПЖ, дисплейные имена, provenance, Dist).
* `changelog.d/006-perf-viewer-loupe-warmup.md` — пункт 7 (прогрев лупы).
* Строки индекса — в `CHANGELOG.md`, раздел `Unreleased` (новейшие сверху);
  `test_docs_links.py` — зелёный.

---

## Гейты

| Гейт | Результат |
|---|---|
| `scripts/check_class_size.py` | OK, baseline только понижен: `DopplerOverlayTools` 1657 → 1635 строк, 126 → 122 метода; `ViewerWidget` 7226 → 7214 строк, 401 → 398 методов; модуль `viewer_widget.py` 8113 → 8074. `doppler_overlay.py` — 2028 → 1916 строк (лимит 2000), `AppController` 167 → 166 методов, `MainWindow` 6436 → 6435. |
| `scripts/check_function_length.py` | OK |
| `scripts/check_layer_directions.py` | OK |
| `scripts/check_broad_excepts.py` | OK (фолбэки — через `log_boundary_failure`) |
| `scripts/check_untranslated_ui_strings.py` | OK (ru/en по 3419 ключей) |
| `scripts/check_id_references.py` | OK |
| `scripts/check_test_private_access.py` | OK |
| `scripts/check_ui_colors.py` | OK |
| `scripts/check_doc_links.py` | OK |
| `scripts/audit_untested_modules.py` | OK: 19 untested modules в baseline 19 — оба новых модуля покрыты поведенческими тестами |

## Что осталось за пределами этого батча

* Нативная GUI-приёмка на Windows 10 (в частности, реальное время первого Z)
  не заменяется прогоном с `qtstub`: экранные замеры ниже — из тестов, а не из
  глаз владельца.
* `scripts/audit_unreferenced_modules.py` сообщает о двух нерутируемых модулях
  (`doppler_derivative_panel`, `segment_labels`) — это состояние `HEAD`, к
  данному батчу не относится.
* Лаг лупы измерен по устранённой причине (перенос работы из обработчика
  клавиши в простой), а не секундомером на целевой машине.
