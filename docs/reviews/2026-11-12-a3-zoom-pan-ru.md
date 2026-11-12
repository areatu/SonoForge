> **Снимок на 2026-11-12.** Ревью-записка к issue #524 (этап A3 плана после S-03). Граница владельца зафиксирована до кода; результаты прогонов сюда не дописываются задним числом.

# A3. Zoom/pan-владелец в ViewerWidget

## 1. Что дублируется сейчас

`ViewerWidget` хранит четыре поля viewport-состояния:

- `_zoom_mode` — `"fit"`, `"100%"`, `"200%"` или `"custom"` после ручного зума;
- `_zoom_factor` — непрерывный фактор Ctrl+wheel и «лупы»;
- `_zoom_loupe_active` и `_zoom_loupe_hint` — armed-состояние клик-зума и его подсказка.

Логика размазана по трём местам:

- `_handle_wheel` сначала разбирает Ctrl+wheel, а затем прокрутку кадров через transport;
- `_apply_zoom_mode` сам считает диапазоны ViewBox по размеру кадра и DPR;
- `zoom_around`, `_handle_ctrl_wheel`, `_zoom_loupe_click` и `_zoom_loupe_status` повторно читают те же поля и `_graphics`/`_view`.

`ContourViewBox` (pan/zoom drag выключен, wheel игнорируется) — отдельный класс-представление. Его поведение остаётся на месте: это не состояние зума, а политика событий.

## 2. Решение о владельце

Вводится `ViewerZoom` (`src/echo_personal_tool/presentation/viewer/zoom.py`) — презентационный владелец **viewport-состояния**:

- хранит режим, фактор, armed-состояние и текст подсказки «лупы»;
- реализует `apply_mode()`, `cycle_mode()`, `set_mode()`, `zoom_around()`, `handle_ctrl_wheel()`, `set_loupe_active()`, `loupe_click()`, `loupe_status()`;
- получает узкий порт: `graphics`, `view`, `frame_provider`, `set_hint` callback и `refresh_cursor` callback. Это данные и два UI-sink'а, а не `ViewerWidget` целиком;
- не хранит `ViewerState`, не эмитит сигналов и не читает документ.

`ViewerWidget` оставляет публичные фасады `cycle_zoom_mode`/`set_zoom_mode`/`zoom_mode`/`zoom_factor`/`zoom_around`/`set_zoom_loupe_active`/`zoom_loupe_active`: их используют `MainWindow`, тесты и contract. Фасады только делегируют; полей `_zoom_mode`/`_zoom_factor` в виджете не остаётся.

### 2.1. Что не переезжает

- **Прокрутка кадров колесом** остаётся в `_handle_wheel` и transport: это документная навигация, а не viewport. Владелец получает только ветку Ctrl+wheel.
- **`ContourViewBox`** остаётся в `viewer_widget.py`: wheel игнорируется, `setMouseEnabled(x=False, y=False)` и `setMenuEnabled(False)` не меняются.
- **Курсор** остаётся у `_apply_viewport_cursor`: он выбирает между лупой и M-mode scan line, а владелец лишь просит его обновить.
- **Геометрия vendor-панелей** (`_frame_panel_layout`, `_frame_panels_from_dicom`, `_resolve_frame_panels`) не входит в кластер, хотя grep по «pan» её находит: это разметка кадра, а не pan.

## 3. Границы среза

Переносится:

- четыре поля viewport-состояния;
- `_apply_zoom_mode`, `cycle_zoom_mode`, `set_zoom_mode`, `zoom_mode`, `zoom_factor`;
- `_handle_ctrl_wheel`, `zoom_around`;
- `set_zoom_loupe_active`, `zoom_loupe_active`, `_zoom_loupe_click`, `_zoom_loupe_status`;
- константы `_ZOOM_MIN`, `_ZOOM_MAX`, `_ZOOM_CLICK_STEP` и текст `tr("viewer.zoom_loupe_*")`.

Не переносится:

- `_handle_wheel` (разбор событий и вызов transport.queue_scroll);
- `ContourViewBox` и `_apply_viewport_cursor`;
- `set_state`/`show_frame`/`show_frame_fast`, кроме замены чтения полей на вызовы владельца;
- любые изменения клавиш, шагов и границ.

`ViewerContract` не меняет allowlist: `_handle_ctrl_wheel`, `_zoom_loupe_click` и `_zoom_loupe_hint` адаптер маршрутизирует к `viewer.zoom`, как A1/A2 сделали для transport/display.

## 4. Harness до кода

QH-0 уже фиксирует критерии A3:

- `test_zoom_cycle_is_fit_100_200_and_leaves_transport_alone` — цикл и невалидный режим;
- `test_zoom_around_changes_only_the_factor` — документ и пиксели не меняются;
- `test_ctrl_wheel_zooms_and_never_steals_the_frame` — Ctrl+wheel не эмитит ни одного сигнала и не двигает кадр;
- `test_viewer_zoom_loupe.py` — клик, Shift+клик, границы и Esc.

Новый изолированный `tests/unit/test_viewer_zoom.py` покрывает:

- цикл `fit→100%→200%→fit`, `custom→100%` и невалидный режим;
- `apply_mode` в fit/100/200 меняет диапазон ViewBox, а без кадра ничего не делает;
- `zoom_around` меняет только фактор и возвращает `False` при отсутствии кадра/том же факторе;
- Ctrl+wheel принимает событие и не трогает провайдер кадра;
- лупа: armed/disarmed, hint очищается, клик без кадра игнорируется, Shift+клик уменьшает;
- негативный сценарий: `set_mode("bogus")` не сбрасывает ни режим, ни фактор.

## 5. Что не проверено

- нативный GUI на Windows/macOS и ручная проверка плавности зума/курсора;
- клиническая валидация (зум — отображение, не измерение);
- реальные PACS/диски и Multiview на живом исследовании.

## 6. Ratchet

`class_size_baseline.json`, `function_length_baseline.json` и mypy-базлайн понижаются только для фактически уменьшившихся записей `ViewerWidget`/его конструктора, вручную. `check_test_private_access.py` должен остаться на нуле: новые тесты используют `viewer.zoom`, а не приватные поля. `ViewerZoom` добавляется в strict-файлы mypy только если проходит без ошибок; иначе — отдельная запись в per-file baseline, без роста общего числа.
