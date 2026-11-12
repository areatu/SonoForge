> **Снимок на 2026-11-12.** Ревью-записка к issue #528 (этап A5 плана после S-03). Граница владельца зафиксирована до кода; результаты прогонов сюда не дописываются задним числом.

# A5. Владелец состояния контуров в ViewerWidget

## 1. Что дублируется сейчас

`ViewerWidget` одновременно хранит состояние рисования и хранения контуров:

- `_stored_contours` — все контуры клипа, `_contours` — отрисованные на текущем кадре;
- `_contour_mode_active`, `_contour_mode_kind`, `_contour_stage` — режим и шаг активного контура;
- `_active_contour_phase`, `_active_contour_view`, `_active_contour_chamber` — клинический контекст будущего `Contour`;
- `_active_mitral_septal`, `_active_mitral_annulus`, `_active_apex_landmark`, `_active_arc_points` — landmark-шаги и точки дуги;
- `_freehand_recording`, `_freehand_points`, `_freehand_open_arc` — идущий freehand-штрих;
- `_last_contour_click_ms`, `_last_contour_click_screen`, `_last_contour_point_screen`, `_first_contour_point_screen` — жест завершения;
- `_area_tool_mode`, `_lv_contour_input`, `_atrial_contour_input` — режим инструмента и ввод контура.

Эти поля читаются и пишутся в десятках методов, а `ViewerContract` и существующие тесты обращаются к ним напрямую. Поэтому «просто перенести» их означало бы сломать замороженный seam.

## 2. Решение о владельце

Вводится `ViewerContours` (`src/echo_personal_tool/presentation/viewer/contours.py`) — Qt-free владелец **состояния рисования и хранения**:

- `stored`/`visible` — списки контуров;
- `mode_active`, `mode_kind`, `stage`, `active_phase`, `active_view`, `active_chamber`;
- landmark-поля (`active_mitral_septal`, `active_mitral_annulus`, `active_apex_landmark`, `active_arc_points`);
- freehand-поля и click-tracking;
- `area_tool_mode`, `lv_input`, `atrial_input`;
- операции `find_index()`, `upsert()`, `set_stored()`, `clear_active()`, `reset_clicks()`, `remember_click()`, `forget_point_screens()`.

`ViewerWidget` больше не хранит ни одного из этих полей: все обращения идут в `self.contour_state`. Чтобы замороженные имена (`viewer._stored_contours`, `viewer._freehand_points`, …) продолжали работать для `ViewerContract` и тестов, на классе объявлены `ContourStateAttribute`-дескрипторы. Это **не второй экземпляр состояния**, а тонкий доступ к тому же owner'у; новых property-методов у виджета нет.

### 2.1. Что не переезжает

- **Создание `Contour` и клинические расчёты** (`fit_contour_from_landmarks`, `refine_open_arc_contour`, площади/объёмы, `contour_completed`) остаются у виджета.
- **Графические items** (`_contour_items`, `_contour_nodes`, `_active_contour_item`, `_active_ma_chord_item`, перья) остаются у виджета: это рендеринг, а не состояние.
- **Сигналы и undo/redo** остаются у виджета; `UndoRedoManager` хранит и контуры, и линейные измерения, поэтому его нельзя отдать контурному owner'у.
- **Persistence и DICOM-аннотации** не затрагиваются.

## 3. Границы среза

Переносится:

- 21 поле состояния контуров;
- `find_index`/`upsert` (бывшие `_find_stored_contour_index`/`_upsert_stored_contour`);
- `reset_clicks`/`remember_click`/`forget_point_screens` (бывшие `_reset_contour_click_tracking`/`_remember_contour_click`/`_forget_contour_point_screens`);
- `clear_active`, которым `_clear_active_contour_drawing` теперь сбрасывает состояние одной операцией;
- совместимость `ViewerContract` через `_CONTOUR_STATE_MEMBERS`.

Не переносится:

- рендеринг, клинические расчёты, сигналы, undo/redo, persistence;
- `_find_stored_contour_index`/`_upsert_stored_contour` как методы виджета удалены, их имена в allowlist маршрутизируются к owner'у.

## 4. Characterization до кода

В `tests/unit/test_viewer_characterization.py` добавлены четыре теста:

- открытый model-контур сохраняет `phase`/`view`/`chamber`, `frame_index`, `is_open_arc` и порядок `contours_changed` → `contour_completed`;
- отклонённые landmark'ы дают `contour_landmark_rejected` и не коммитят контур;
- `refine_active_open_contour()` без открытого контура возвращает `(False, "")` и не эмитит сигналов;
- смена кадра во время freehand-штриха сбрасывает запись, точки и режим, не создавая контур.

Существующий тест закрытого контура уже фиксировал payload и undo/redo после удаления. Новый изолированный `tests/unit/test_viewer_contours.py` (9 тестов) покрывает defaults, копирование списка, identity-поиск, различие planimeter-полигонов по метке, frame/instance, `clear_active`, click tracking и дескриптор совместимости.

## 5. Результаты

- `ViewerWidget`: 7 268 → 7 240 строк, 406 → 401 метод, 163 → 142 поля; модуль `viewer_widget.py` 8 159 → 8 132 строки.
- Новый `presentation/viewer/contours.py` — 142 строки, порог модуля в 2 000 строк не затрагивает.
- `mypy presentation`: 813 exact, 81/160 strict-модулей; полный `mypy --no-incremental` по пинам `uv.lock` — 396 файлов, 0 ошибок.
- `class_size_baseline.json` понижен точечно для `ViewerWidget`; `function_length_baseline.json` — `ViewerWidget.__init__` 323 → 299.
- Все ratchet-скрипты зелёные: function-length 200, class-size, mypy-presentation, id-references 641, private-access 0, layer-directions, doc-links 264, test-signal 10 024 теста, type-ignores 53, ui-colors 188, untranslated 0, broad-excepts 280.

## 6. Что не проверено

- нативный GUI на Windows/macOS и ручное рисование мышью на реальном кадре;
- клиническая валидация контуров LV/LA/RA, Simpson и planimeter на живых PACS/дисках;
- поведение при очень длинном freehand-штрихе и на нескольких мониторах.
