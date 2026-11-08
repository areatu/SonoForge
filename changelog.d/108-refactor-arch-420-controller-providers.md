- `refactor(arch)`: #420 (QH-3 follow-up, slice 1) — `_controller_ref` больше нет.
  `MainWindow` и `PresenterView` писали прямо в непубличное поле `viewer._controller_ref = controller`
  (без типа, без фиксированного контракта), а `ViewerWidget` читал его обратно через `hasattr`/
  `is not None` в четырёх местах: ROI последней автоматической сегментации (`_get_last_segment_roi`),
  результат слияния фаз (`_get_fusion_result`) и запрос/ответ LA AI-assist (`_request_la_assist_for_manual`,
  подписка на `la_assist_contour_ready`). Теперь это три явных узких провайдера, выставленных на
  `ViewerWidget`: `set_last_segment_roi_provider`, `set_fusion_result_provider`, `set_la_assist_provider`
  (приём запроса + сигнал готовности одним вызовом — таймингу подписки «один раз, лениво, при первом
  запросе» ничего не изменилось). `MainWindow._wire_viewer_controller_providers` и аналогичный блок в
  `PresenterView` вызывают их один раз при создании виджета вместо прямой записи приватного поля.
  Инициализация провайдеров вынесена в `ViewerWidget._init_controller_providers`, а проводка в
  `MainWindow._wire_viewer_controller_providers` — оба «вне бюджета длины `__init__`» (как у
  `_wire_gallery_signals`), чтобы не раздувать и так переразмеренные конструкторы. Новые случаи —
  `tests/unit/test_qh3_controller_providers.py` (12 GUI-случаев): `_controller_ref` отсутствует на виджете;
  каждый из трёх провайдеров по умолчанию неактивен (нет провайдера → `None`/no-op) и корректно
  прокидывает значение/запрос, когда выставлен; подписка на сигнал готовности LA-assist происходит ровно
  один раз и переподключается при повторной проводке (а не остаётся привязанной к устаревшему сигналу);
  сквозной путь «завершение ручного контура LA/A4C/ES запускает assist, остальные случаи — нет»
  (`_finish_manual_contour`). Контракт (`viewer_contract.py`/`viewer_contract_allowlist.json`) не менялся:
  `_get_last_segment_roi`, `_get_fusion_result`, `_on_la_assist_contour_ready` уже были в разрешённом
  списке как методы и их сигнатуры не изменились.

  Попутно найден и исправлен давний (добавленный задолго до этого слайса) живой баг в
  `_finish_manual_contour`: условие триггера LA-assist читало `self._active_contour_phase` уже после
  вызова `_clear_active_contour_drawing()`, которая сбрасывает это поле в `None` — поэтому проверка
  `== "ES"` никогда не была истинной и assist для LA/A4C/ES ни разу не срабатывал на практике. Фаза и
  вид теперь захватываются в локальные переменные до очистки активного состояния контура (как уже
  делалось для `chamber`) и используются и при построении контура, и в самой проверке триггера.
