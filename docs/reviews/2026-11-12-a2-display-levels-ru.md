> **Снимок на 2026-11-12.** Ревью-записка к issue #522 (этап A2 плана после S-03). Граница владельца зафиксирована до кода; результаты и последующие изменения сюда не дописываются задним числом.

# A2. Display/lut-владелец в ViewerWidget

## 1. Что дублируется сейчас

`ViewerWidget` одновременно хранит:

- три `QSlider` (`_window_slider`, `_level_slider`, `_dr_slider`) и их значения;
- кэш вычисленных уровней (`_cached_levels_key`, `_cached_display_low/high`);
- LUT и двойной display-буфер (`_cached_lut`, `_cached_lut_key`, `_display_buffers`, `_display_buf_idx`);
- два независимых кэша WL/DR: `_instance_wl_dr_cache` по `sop_instance_uid` (в `set_state`) и `_per_file_wl_dr` по `Path` (в `show_frame`), плюс `_current_instance_path`;
- внешние слайдеры панели и замыкание `_sync_display_control_enabled`.

Формула уровней записана дважды: в `_update_levels()` и `_effective_display_levels()`. Слайдеры напрямую подключены к `_update_levels()`, а внешние — через `bind_display_controls()`, поэтому владение размазано между виджетом и панелью.

## 2. Решение о владельце

Вводится `ViewerDisplay` (`src/echo_personal_tool/presentation/viewer/display.py`) — презентационный владелец **display-проекции**:

- владеет слайдерами window/level/DR, кэшем уровней, LUT, двойным буфером и обоими кэшами WL/DR;
- реализует `update_levels()`, `effective_levels()`, `levels_key()`, `is_levels_outlier()`, `set_values()`, `apply_preferences()`-обвязку, `bind_external()/disconnect_external()`, `save_current_wl_dr()`, `set_current_path()`, `remember_instance()/restore_instance()`;
- получает узкий порт: `frame_provider`, `enabled_provider`, `color_source_provider`, `color_active_provider`, `image_item`, `invalidate_edge_map` callback. Это данные и один sink, а не `ViewerWidget` целиком и не service locator;
- не хранит `ViewerState` и ничего не знает об UID/zoom/overlay/контурах.

`ViewerWidget` оставляет публичные сигналы и `_window_level_enabled`, `_is_color_frame`, `_color_source_rgb`, `_color_display_active`: определение цветного режима и despeckle — входы display-проекции, а не её состояние. Владелец получает их через провайдеры.

### 2.1. Два кэша WL/DR — один владелец

`_instance_wl_dr_cache` (UID) и `_per_file_wl_dr` (путь) обслуживают разные пути: `set_state` при смене инстанса и `show_frame` при смене файла. Поведение каждого сохраняется буквально, включая порядок «сохранить старый → восстановить новый → иначе 100/50/50». Оба словаря переезжают в `ViewerDisplay`; в `ViewerWidget` не остаётся ни одного кэша WL/DR. Объединять ключи в один словарь в этом срезе нельзя: это изменило бы поведение при несовпадении `sop_instance_uid` и пути.

## 3. Границы среза

Переносится:

- создание трёх слайдеров, подключение `valueChanged`, вычисление и кэш уровней, LUT, double buffer;
- `_update_levels`, `_ensure_display_buffer`, `_is_levels_outlier`, `_effective_display_levels`, `_levels_sliders_key`;
- `_set_wl_dr_sliders`, `_save_current_wl_dr`, кэши UID/пути, внешние слайдеры;
- `_apply_window_level_preferences` остаётся тонкой обвязкой: `resolve_wl_values()` — application-политика, владелец получает три числа.

Не переносится:

- `_resolve_display_mode`, `_frame_confirms_color`, `_color_display_active`, `_is_color_frame`, `_window_level_enabled`, `_color_source_rgb` — входы display-проекции;
- edge-map, контуры, zoom/pan;
- любое изменение формул или порогов.

`ViewerContract` не меняет allowlist: transport/display-имена адаптер маршрутизирует к `viewer.display`, как A1 сделал для `viewer.transport`.

## 4. Harness до кода

В `test_viewer_characterization.py` добавлены два сценария, прошедшие на текущем коде:

- комбинация трёх слайдеров меняет `instance_snapshot["pixels"]`, но не UID/zoom/overlay и не эмитит measurement-сигналы;
- возврат к первому инстансу восстанавливает `(140, 63, 37)` из кэша UID без measurement-сигналов.

После среза эти же ожидания не меняются. Дополнительно прогоняются `test_viewer_levels_cache.py`, `test_viewer_display_mode.py`, `test_viewer_widget.py`, `test_presentation_viewer_widget.py`, `test_viewer_contract_api.py`, `test_presenter_view.py`.

Новый изолированный `tests/unit/test_viewer_display.py` покрывает:

- `set_values` не эмитит лишних сигналов и обновляет пиксели;
- `update_levels()` при `enabled=False`/пустом кадре ничего не делает;
- `remember_instance`/`restore_instance` и `set_current_path` сохраняют значения;
- `effective_levels()` совпадает с `compute_display_levels` на том же кадре и слайдерах;
- негативный сценарий: неизвестный UID не сбрасывает текущие значения.

## 5. Что не проверено

- нативный GUI на Windows/macOS и ручная проверка отображения;
- клиническая валидация (уровни — отображение, не измерение);
- реальные PACS/диски и Multiview на живом исследовании.

## 6. Ratchet

`class_size_baseline.json` и `function_length_baseline.json` понижаются только для фактически уменьшившихся записей `ViewerWidget`/его конструктора, вручную. mypy presentation не растёт; новые модули, прошедшие strict, добавляются в `[tool.mypy].files`. `check_test_private_access.py` остаётся на нуле: новые тесты используют `viewer.display`.
