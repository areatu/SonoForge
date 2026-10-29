# 2026-10-29 — Debian SIGSEGV: application-wide Python event filters + QtWebEngine

## Симптом

Быстрый скролл колесом по меню/пресетам инструментов на Debian воспроизводимо
приводил к фризу, затем к падению. В `crash.log` — только `Fatal Python error:
Segmentation fault`; session-логи обрываются без Python-исключения.

## Данные core-дампов

Четыре дампа (27–28.10) дали одинаковый стек:

- падение в `PySide::getWrapperForQObject` (`libpyside6`, PySide6 6.11.2);
- диспатч события шёл через `QCoreApplicationPrivate::sendThroughApplicationEventFilters`;
- receiver — внутренний `QtWebEngineCore::RenderWidgetHostViewQtDelegateItem`
  веб-справочника (`QWebEngineView`);
- Shiboken читает RTTI typeinfo из `vtable[-1]`; у QtWebEngineCore она собрана с
  `-fno-rtti`, указатель нулевой → `mov 0x8(%rax)` при `rax=0` → SIGSEGV;
- в стеке есть `QObject::doSetProperty`: динамическое свойство на внутреннем
  WebEngine-объекте. Быстрый скролл увеличивает поток repaint/compositor-событий
  и вероятность попасть в этот путь.

Кандидаты-провайдеры application-filter'ов: `main_window.py` (F11-kiosk),
`tooltip_text.py`, `theme/dialog_outline.py`, `study_loading_overlay.py`.
Дополнительно найден и устранён `_LoupeKeyRelay` во `viewer_widget.py`.

## Вывод

Это не дефект логики панели параметров. Это несовместимость PySide6 6.11.2
(RTTI-эвристика Shiboken) + QtWebEngine при наличии Python-фильтра событий на
`QApplication`. Проверка типа receiver'а внутри `eventFilter` не спасает:
обёртка создаётся до входа в тело фильтра.

## Исправление

Production-код больше не устанавливает Python event filters на QApplication:

- `ScrollSafeStyle` отключает wheel-selection у закрытых `QComboBox` через
  `SH_ComboBox_AllowWheelScrolling`; числовые поля защищаются локальным
  `SpinBoxWheelGuard` на самом поле. Глобальный `ScrollWheelGuard` удалён.
- Tooltip wrapping и dialog outlines больше не подписываются на приложение.
  Обводка подключается явно в construction-path диалогов; длинные подсказки
  должны сворачиваться у источника, а не глобальным фильтром.
- `StudyLoadingOverlay` фильтрует ввод только на виджетах своего окна и временно
  отключает его `QShortcut`; поддерево QtWebEngine пропускается.
- F11-kiosk reveal слушает viewport снимка и chrome-бары, а не QApplication.
- Z-лупа использует focus-scoped relay (текущий focus widget + окно), а не
  application-wide relay; WebEngine-фокус пропускается.
- Добавлен статический regression-gate: в `src/` не должно быть
  `app.installEventFilter(...)` / `QApplication.instance().installEventFilter(...)`.

Оптимизации отзывчивости из этой же ветки сохранены отдельно: повторное
использование строк инструментов, общие QSS панели, дедупликация неизменяемых
форм свойств на кадрах воспроизведения. Они уменьшают фриз, но сами по себе не
являются исправлением native-crash.

## Проверка

- `ruff check src tests`, `ruff format --check src tests` — чисто.
- `scripts/check_function_length.py` — без роста длинных функций.
- Offscreen GUI-наборы: scroll policy, tooltip/dialog outlines, magnifier relay,
  tool panel responsiveness, properties playback, loading veil/tabs, fullscreen
  kiosk, preferences/speckle dialogs — зелёные.
- Inventory baseline обновлён: total 9298 → 9313, gui 3847 → 3861,
  not_gui 5451 → 5452, gui_files 199 → 202.

## Ограничения

Нативная Debian-приёмка с реальным QtWebEngine и быстрый скролл на Win10 не
выполнялись в этой среде. Исправление убирает доказанный core-дампами путь
application-filter → Shiboken wrapper; подтверждение отсутствия падений требует
прогона на исходной Debian-машине с тем же веб-справочником.
