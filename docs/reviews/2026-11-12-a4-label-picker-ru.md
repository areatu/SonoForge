> **Снимок на 2026-11-12.** Ревью-записка к issue #526 (этап A4 плана после S-03). Граница владельца зафиксирована до кода; результаты прогонов сюда не дописываются задним числом.

# A4. Владелец label picker в ViewerWidget

## 1. Что дублируется сейчас

`ViewerWidget` хранит четыре поля состояния окна подписи:

- `_label_picker` — сам `LabelPicker`, создаваемый лениво;
- `_label_picker_enabled` — разрешена ли подпись в исследовании;
- `_label_picker_target` — `("contour", ref)`, `("caliper", key)` или `("trace", measurement_id)`;
- `_label_picker_context_override` — контекст каталога, выбранный хостом.

Рядом лежат ещё два состояния, которые обслуживают тот же сценарий:

- `_cardiac_context_override` — кардиологический/некардиологический тип исследования;
- `_caliper_labels` и `_caliper_label_index` — цикл подписей свободного калипера, который двигает `Tab` в открытом окне и `cycle_caliper_label()` без окна.

Сама логика размазана по виджету: `_ensure_label_picker` создаёт окно и подключает три сигнала, `accept_label_picker`/`dismiss_label_picker`/`handle_label_picker_key` повторяют проверку видимости, `_on_label_picker_tab_cycled` двигает индекс метки, `_on_label_picker_dismissed` чистит цель, а `_apply_picked_label` одновременно читает цель и меняет измерения.

## 2. Решение о владельце

Вводится `ViewerLabelPicker` (`src/echo_personal_tool/presentation/viewer/label_picker_owner.py`) — презентационный владелец **только UI-состояния выбора подписи**:

- хранит окно, цель, enabled, context override, cardiac override и цикл подписей;
- реализует `picker()`, `offer()`, `accept()`, `dismiss()`, `handle_key()`, `cycle_visible_selection()`, `resolve_context()`, `set_context()`, `set_cardiac_context()`, `is_cardiac_context()`, `set_enabled()`, `current_label()`, `set_label()`, `cycle_label()`;
- получает узкий порт: `parent`, `apply_label` callback, `can_cycle_label` callback и `cardiac_provider` callback. Это не `ViewerWidget` целиком и не документ;
- при выборе подписи забирает цель и передаёт `(option, target)` в `apply_label`; сам ничего не измеряет и не эмитит клинических сигналов.

`ViewerWidget` оставляет публичные фасады `label_picker()`, `is_label_picker_visible()`, `set_label_picker_enabled()`/`is_label_picker_enabled()`, `set_label_picker_context()`, `accept_label_picker()`, `dismiss_label_picker()`, `handle_label_picker_key()`, `set_cardiac_context()`/`is_cardiac_context()` и `cycle_caliper_label()`. Фасады только делегируют; полей `_label_picker*`, `_cardiac_context_override`, `_caliper_labels` и `_caliper_label_index` в виджете не остаётся.

### 2.1. Что не переезжает

- **`_apply_picked_label`** остаётся у виджета: он мутирует `_stored_linear_measurements`, вызывает `record_labeled_peak`/`record_labeled_interval`/`relabel_last_trace` и эмитит измерения. Это клиническое владение, а не UI выбора.
- **Сборка значения и якоря** (`_open_label_picker_for_contour`, `_open_label_picker_for_caliper`, `_on_doppler_trace_committed`, `_format_caliper_value_for_picker`, `_map_image_point_to_viewer`) остаётся у виджета: она читает контуры, допплер и геометрию кадра.
- **`_resolve_label_picker_context`** оставляет у виджета выбор контекста по измерению (M-mode/Doppler/2D) и лишь спрашивает владельца, нет ли override.
- **`_should_show_label_picker`** оставляет у виджета клинические ворота: vessel mode, активный протокол и кардиологический контекст.
- **`_protocol_active`/`_protocol_active_provider`** остаются у виджета: протокол — это клинический workflow, а не состояние окна.
- **Список доступных подписей** остаётся один — каталог `presentation/label_picker.py` (`DEFAULT_CONTEXT_OPTION_IDS`, `PICKER_CONTEXTS`). Владелец хранит только порядок цикла свободного калипера; второго каталога в `ViewerWidget` или tool panel нет.

## 3. Границы среза

Переносится:

- четыре поля окна, `_cardiac_context_override`, `_caliper_labels`, `_caliper_label_index`;
- создание/подключение `LabelPicker`, `accept`/`dismiss`/`handle_key`, `cycle_visible_selection`;
- `_on_label_picker_tab_cycled`, `_on_label_picker_dismissed`, `_set_caliper_label`, `_current_caliper_label`;
- override-логика контекста и кардиологического типа, `set_label_picker_context`, `set_label_picker_enabled`;
- `_set_caliper_label`/`_current_caliper_label` остаются тонкими фасадами.

Не переносится:

- `_apply_picked_label` и любые записи в измерения, контуры или Doppler overlay;
- `_open_label_picker_*` и форматирование значений;
- `_should_show_label_picker`, `_resolve_label_picker_context`, `_protocol_active`;
- изменения клавиш, контекстов и каталога подписей.

`ViewerContract` сохраняет allowlist: `_caliper_labels`, `_caliper_label_index`, `_current_caliper_label` и `_set_caliper_label` адаптер маршрутизирует к `viewer.label_picker_owner`, как A1–A3 сделали для transport/display/zoom.

## 4. Characterization до кода

В `tests/unit/test_viewer_characterization.py` добавлены пять тестов:

- открытие/закрытие окна не меняет документ и не эмитит сигналов (`test_label_picker_is_ui_only_and_dismisses_silently`);
- принятие подписи без цели измерения ничего не запускает (`test_accepting_a_picker_without_a_measurement_target_is_silent`);
- `accept`/`dismiss` на скрытом окне — no-op (`test_hidden_picker_accept_is_a_noop`);
- смена кадра и инстанса закрывает окно (`test_instance_and_frame_switches_dismiss_the_picker`);
- context override остаётся UI-состоянием, применяется к следующему открытию и не трогает документ (`test_picker_context_override_is_ui_state_only`).

В `tests/unit/test_label_picker.py` добавлен повторный выбор: второй свободный калипер открывает окно для собственного измерения (`test_a_second_free_caliper_opens_the_picker_for_its_own_measurement`). Остальное покрытие уже было: цифра/Enter/Tab, Esc, отказ для анатомических/серийных калиперов, не-кардио и неизвестное исследование, `set_cardiac_context`, протокол, preference, допплер-калипер и free-trace VTI, русская раскладка.

Новый изолированный `tests/unit/test_viewer_label_picker_owner.py` (10 тестов) проверяет ленивое создание, `offer`/`take_target`, disabled, поздний выбор после dismiss, no-op на скрытом окне, override контекста и кардиологического типа, `Tab`-цикл с запретом и без, добавление метки и перенос выделения без закрытия.

## 5. Результаты

- `ViewerWidget`: 7 313 → 7 268 строк, 407 → 406 методов, 169 → 163 поля; модуль `viewer_widget.py` 8 203 → 8 159 строк.
- Новый `presentation/viewer/label_picker_owner.py` — 207 строк, порог модуля в 2 000 строк не затрагивает.
- `mypy presentation`: 818 → 813 exact, 80/159 strict-модулей; полный `mypy --no-incremental` по пинам `uv.lock` — 395 файлов, 0 ошибок.
- Импорт каталога из нового владельца вскрыл давнюю ошибку `label_picker.py` (`option` выводился как `LabelOption`, а `_option_from_spec()` возвращает `LabelOption | None`). Присваивание переименовано в `candidate`; модуль стал чистым и переведён в strict-список `[tool.mypy].files`.
- `class_size_baseline.json` понижен точечно для `ViewerWidget`; `function_length_baseline.json` — `ViewerWidget.__init__` 335 → 323; mypy-базлайн — 813, `total_files` 67, `no-untyped-call` 17 → 13.
- Все ratchet-скрипты зелёные: function-length 200, id-references 641, private-access 0, doc-links 264, test-signal 10 011 тестов, type-ignores 53, ui-colors 188, untranslated 0, broad-excepts 280.

## 6. Что не проверено

- нативный GUI на Windows/macOS и ручная проверка позиционирования окна над измерением;
- клиническая валидация: подпись по-прежнему не меняет расчёт, но реальные PACS/диски и Multiview на живом исследовании не прогонялись;
- поведение на очень маленьком окне вьюера и при нескольких мониторах.
