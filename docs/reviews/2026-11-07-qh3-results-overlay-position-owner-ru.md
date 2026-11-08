# QH-3 follow-up, срез 3: единственный владелец позиции оверлея результатов

> **Снимок на 2026-11-07.** Документ фиксирует состояние на эту дату и не обновляется вслед за кодом:
> актуальное состояние — в коде, `README.md`, HELP и открытых issues. Issue:
> [#420](https://github.com/areatu/SonoForge/issues/420). Предыдущий срез — единственный владелец
> магнитной лупы (`docs/reviews/2026-11-06-qh3-magnifier-owner-ru.md`), §5 п. 3.

## 1. Что было не так

QH-3-пилот создал `ResultsOverlayController` и подключил его к `ViewerWidget`
(`presentation/viewer_widget.py`), но реально контроллер использовался только для `apply_style()`.
Вся остальная логика осталась внутри виджета второй, независимой копией:

1. **Параллельное состояние.** Виджет держал `_results_overlay_custom_position`,
   `_results_overlay_cleared`, `_results_overlay_position_just_restored`,
   `_results_overlay_suppressed` — те же четыре поля, что уже были на контроллере
   (`_custom_position`, `_cleared`, `_position_just_restored`, `_suppressed`), никогда не читавшиеся.
2. **Дубль геометрии и текста.** `_reposition_results_overlay_label`, `_request_results_overlay_reposition`,
   `_reposition_results_overlay_deferred` в виджете повторяли `_reposition_results_label` /
   `_request_reposition` / `_reposition_deferred` контроллера буква в букву; `set_results_overlay` /
   `set_results_overlay_position` / `reset_results_overlay_to_default` на виджете повторяли
   `set_text` / `set_position` / `reset_to_default` контроллера.
3. **Бесхозный фикс.** Баг «очистка должна стирать текст, а не только прятать» (иначе следующий
   «HR: …» дописывался к старому значению) был исправлен только в копии виджета; версия на
   контроллере никогда не вызывалась, поэтому фикс в неё не попал.
4. **`MainWindow` писал напрямую в приватное поле.** `main_window.py` делал
   `self._viewer._results_overlay_cleared = False` при смене инстанса — чтение/запись чужого
   приватного состояния в обход какого-либо шва.

## 2. Что сделано

| Решение | Где |
|---|---|
| Состояние позиции/cleared/suppressed живёт только на контроллере; в виджете не осталось полей | `viewer_widget.py` |
| `set_text()` контроллера получил «erase, не только hide» и теги причины (`CommandResult.reason`: `shown` / `erased` / `suppressed` / `cleared_until_next_non_empty`) | `overlay_controller.py` |
| Новые методы владельца: `mark_cleared()`, `is_cleared()`, `reset_cleared()` (симметричны уже существовавшим `mark_custom_position()` / `custom_position()` / `reset_to_default()`) | `overlay_controller.py` |
| `ViewerWidget.set_results_overlay` / `set_results_overlay_position` / `reset_results_overlay_to_default` / `set_results_overlay_suppressed` / `results_overlay_*` остаются как тонкие обёртки для существующих вызывающих, но делегируют контроллеру целиком | `viewer_widget.py` |
| `_position_overlay_labels` зовёт `controller.reposition(reposition_results=...)` вместо дублирующей геометрии; три приватных метода-дубля удалены | `viewer_widget.py` |
| Новый публичный метод `reset_results_overlay_cleared()` — `MainWindow` больше не пишет в приватное поле виджета | `viewer_widget.py`, `main_window.py` |
| Два имени убраны из замороженного `tests/architecture/viewer_contract_allowlist.json` (`_results_overlay_cleared`, `_results_overlay_custom_position`) — поля больше не существуют, доступ к ним через `.contract` стал бы ошибкой | `viewer_contract.py`, `tests/architecture/viewer_contract_allowlist.json` |

Поведенческая правка по ходу среза: `ResultsOverlayController.set_text("")` теперь стирает текст
лейбла (`QLabel.clear()`), а не только прячет его — тот же фикс, что раньше был только в коде
виджета, стал частью единственной реализации.

## 3. Числа

| Показатель | До | После |
|---|---|---|
| Полей состояния оверлея результатов в виджете | 4 | 0 |
| Реализаций геометрии/текста оверлея результатов | 2 | 1 |
| Прямых записей `MainWindow` в приватное поле виджета (`_results_overlay_cleared`) | 1 | 0 |
| Приватных имён `_results_overlay_*`, допустимых через `.contract` (атрибуты, не методы) | 3 (`cleared`, `custom_position`, `label`) | 1 (`label` — сам Qt-виджет, не состояние) |

## 4. Тесты

- `tests/unit/test_qh3_results_overlay_owner.py`: новый класс `TestResultsOverlayPositionOwner`
  (7 GUI-случаев) — виджет не держит второй копии состояния; позиция и флаг `custom` проходят через
  владельца туда и обратно; `reset_to_default` снимает флаг владельца; очистка стирает текст лейбла,
  а не только прячет; `cleared` блокирует новый текст до явного `reset_cleared()`; `suppressed`
  прячет и блокирует новый текст до снятия; сброс `cleared` из «внешнего» вызова не требует записи в
  приватное поле.
- `tests/unit/test_presenter_view.py::test_overlay_position_forward_updates_audience` — прямой доступ
  `viewer._results_overlay_custom_position` заменён на публичный `results_overlay_custom_position()`.
- `tests/unit/test_viewer_widget.py` — три теста (`test_reset_results_overlay_to_default`,
  `test_on_results_overlay_clear`, `test_on_results_overlay_reset_position`) переведены с записи
  `w.contract.results_overlay_custom_position = True` на `w.results_overlay_controller.mark_custom_position()`
  и с чтения `w.contract.results_overlay_cleared` на `w.results_overlay_controller.is_cleared()`.
- `ruff check` / `ruff format --check` по изменённым файлам — чисто.
- Базовая линия разбиения pytest обновлена вручную (`total 10171 → 10178, gui 4108 → 4115`) — см.
  ограничение ниже.

## 5. Что осталось от #420 (отдельные срезы)

1. `_controller_ref` → три узких провайдера (ROI автоматической сегментации, LA-assist ×2, слияние фаз).
2. Мёртвые владельцы: `FrameOverlayController`, `DebugOverlayController`, `ToolInteractionController`,
   `ContourEditingController`, `CalibrationController`, `WorkerBridge` — подключать или удалять;
   правка `test_50_cycles_controller_inventory_stable` (ожидает ровно 9 владельцев).

## 6. Ограничения

- **В этой песочнице не было возможности запустить набор GUI-тестов**: нет `libGL`/`libEGL`/X11-стека,
  а сеть ограничена `github.com`/`pypi.org`/`npmjs.org` — установить системные библиотеки (`apt`) или
  собрать их из исходников не получилось. Проверка ограничилась `ruff check`, `ruff format --check` и
  построчным прослеживанием кода (каждый вызов удалённых методов и каждое поле найдены через `grep` по
  всему `src/`). Базовая линия pytest-партиции посчитана вручную, а не скриптом
  `update_pytest_baseline.py --fix`. **CI обязателен для подтверждения** — это не замена прогону, а
  честная фиксация того, что было и не было проверено локально.
- Нативная проверка Windows/macOS по этому срезу не проводилась (как и у предыдущего среза).
