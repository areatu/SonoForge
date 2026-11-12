> **Снимок на 2026-11-12.** Ревью-записка к issue #520 (этап A1 плана после S-03). Она фиксирует границу владельца до кода; последующие изменения поведения сюда не дописываются задним числом.

# A1. Frame/transport-владелец в ViewerWidget

## 1. Что именно дублируется сейчас

`ViewerWidget` содержит два почти одинаковых блока проекции транспорта:

- `set_state()` (строки ~3011–3038): range/enable слайдера и кнопок, `_play_button`, FPS-текст, счётчик, phase-strip, loop-кнопки;
- `set_transport_state()` (строки ~2899–2930): то же самое, но для Multiview-панели без `ViewerState`.

Различия, которые обязаны сохраниться:

| Поле | `set_state` | `set_transport_state` |
|---|---|---|
| play enabled | `total > 1 and not decode_in_progress` | `total > 1` |
| FPS | из `ViewerState.fps` | из `frame_time_ms` |
| счётчик | `current_frame_index + 1` (0 при `total == 0`) | `clamped(frame_index) + 1` |
| signals при установке слайдера | не эмитятся, потому что `_syncing_state` | явный `blockSignals` |

Кроме этого, в god-классе живут `_pending_scroll_index`, `_scroll_debounce_ms` и `_scroll_debounce_timer`, а `multiview_pane` и `presenter_view` читают `_timeline_slider`/`_play_button` как приватные поля чужого класса.

## 2. Решение о владельце

Вводится `ViewerTransport` (`src/echo_personal_tool/presentation/viewer/transport.py`) — презентационный владелец **UI-проекции**:

- владеет виджетами `bar`, `timeline_slider`, `play_button`, `fps_label`, `source_label`, кнопками first/step/last;
- владеет `pending_scroll_index`, `scroll_debounce_ms`, `QTimer` debounce и методом `dispose()`;
- единственный реализует проекцию `apply_state(...)`, поэтому `set_state()` и `set_transport_state()` делегируют в него, а не повторяют блок;
- эмитит собственные сигналы `play_pause_requested`, `frame_selected`, `scroll_frame_selected`, `fps_override_requested`; `ViewerWidget` оставляет свои публичные сигналы и ретранслирует их 1:1, чтобы внешний контракт не менялся.

`ViewerState` остаётся владельцем документа: `ViewerTransport` не хранит `ViewerState`, не читает `instance`, `fps` или `decode_in_progress` из домена — только примитивы, переданные вызывающей стороной. Второго источника истины нет.

### 2.1. Не входит в QH-3 inventory

`ViewerTransport` — не generation-scoped контроллер: у него нет `set_context`, он не зависит от `ViewerContext` и не должен получать контекст при `_sync_viewer_context()`. Поэтому он **не** добавляется в `_all_qh3_controllers` (иначе цикл рассылки контекста начнёт писать ему `context`). Его teardown явный: `dispose_viewer_resources()` вызывает `transport.dispose()` до остановки остальных таймеров. Инвентарь QH-3 остаётся `[ResultsOverlayController, TagsOverlayController, MagnifierController]`, characterization-ожидание не меняется.

### 2.2. Контракт `ViewerContract`

Имена `timeline_slider`, `play_button`, `fps_label`, `source_label`, `scroll_debounce_ms`, `pending_scroll_index`, `step_back`, `step_forward`, `on_timeline_changed`, `emit_pending_scroll`, `update_timeline_indicator` остаются в allowlist. Адаптер получает таблицу `transport`-имён и сначала ищет публичное имя у `viewer.transport`, а при его отсутствии (unit-тест адаптера с `SimpleNamespace`) — у самого viewer. Это ровно назначение адаптера: удерживать замороженный контракт при декомпозиции. Список `EXPOSED_PRIVATE_NAMES` и JSON allowlist не меняются.

`_syncing_state` остаётся у `ViewerWidget` (это оркестрация состояния, а не транспорт). Ретрансляция `transport.frame_selected → viewer.frame_selected` проверяет его, поэтому `contract.syncing_state = True` по-прежнему глушит `on_timeline_changed(5)`, как в characterization.

## 3. Границы среза

Переносится:

- построение transport-бара и его виджетов (включая `_FpsLabel`);
- `_fix_play_button_width`, `_sync_play_button`, `_set_frame_counter_label`;
- `_emit_pending_scroll`, `set_scroll_debounce_ms`, `_step_back`, `_step_forward`, `_on_timeline_changed`;
- `_update_timeline_indicator` (фактически очистка tooltip/style);
- блок проекции из `set_state`/`set_transport_state`.

Не переносится:

- `CinePhaseStrip`, `_phase_label`, `_phase_timeline`, `_update_phase_label`, `_on_phase_*` — фазовый кластер;
- `LoopControls` — остаётся child viewer'а; transport только раскладывает его кнопки/полосу и синхронизирует total/current;
- `_syncing_state`, `_current_state`, `_pending_viewer_state` — оркестрация документа.

`LoopControls` создаётся до `ViewerTransport` и получает `viewer._on_timeline_changed`; метод остаётся тонкой делегацией в `transport.on_timeline_changed`, поэтому порядок сигналов не меняется.

## 4. Проверки

До и после среза:

```bash
PYTHONPATH=src LD_LIBRARY_PATH=tools/qtstub/lib QT_QPA_PLATFORM=offscreen \
  python -m pytest tests/unit/test_viewer_characterization.py -q
PYTHONPATH=src LD_LIBRARY_PATH=tools/qtstub/lib QT_QPA_PLATFORM=offscreen \
  python -m pytest tests/unit/test_viewer_widget.py tests/unit/test_presentation_viewer_widget.py \
  tests/unit/test_viewer_contract_api.py -q
python -m pytest tests/unit/test_qh3_lifecycle.py -q
python scripts/check_class_sizes.py
python scripts/check_mypy_presentation.py
```

Новый изолированный тест `tests/unit/test_viewer_transport.py` покрывает:

- `apply_state` с `total=0` и с `decode_in_progress=True` (негативный сценарий: play выключен, счётчик не врёт);
- debounce: `queue_scroll` не эмитит сразу, `emit_pending_scroll` эмитит ровно один раз и очищает pending;
- `on_timeline_changed` эмитит `frame_selected`, а `select_frame` вне диапазона ничего не делает;
- `dispose()` идемпотентен и останавливает таймер.

Порядок и число сигналов на уровне `ViewerWidget` проверяются существующим `SignalRecorder` characterization без правки ожиданий.

## 5. Что не проверено

- нативный GUI на Windows/macOS (offscreen-прогон и CI-шарды не заменяют ручную проверку);
- клиническая валидация (её нет и не появляется из этого рефакторинга);
- реальные PACS/диски и Multiview на живом исследовании.

## 6. Ratchet

`class_size_baseline.json` уменьшается только для фактически уменьшившихся записей `ViewerWidget` (строки/методы/поля), вручную и точечно. `check_mypy_presentation.py` должен показать снижение или не рост; `check_test_private_access.py` — не расти (новые тесты используют `viewer.transport`, не приватные поля).
