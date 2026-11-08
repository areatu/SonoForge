- `refactor(arch)`: #420 (QH-3 follow-up, срез 2) — удалены `FrameOverlayController` и
  `DebugOverlayController`. Оба создавались и регистрировались в `ViewerWidget._all_qh3_controllers`
  (ради учёта в lifecycle-тесте 50 циклов), но ни разу не вызывались виджетом: калибровочный баннер и
  текст по кадру в левом верхнем углу (`_overlay_label`), а также диагностический оверлей
  (`_debug_overlay_label`, `_debug_overlay_visible`) всегда вели себя напрямую, минуя контроллер —
  классический «мёртвый владелец» без единого внешнего вызова. Удалены сами классы
  (`presentation/viewer/overlay_controller.py`), их экспорт (`presentation/viewer/__init__.py`),
  конструирование и регистрация в `ViewerWidget.__init__` (`_all_qh3_controllers`: 9 → 7 владельцев) и
  единственный существовавший для них тест (`test_frame_overlay_append_and_clear`; у `DebugOverlayController`
  тестов не было вовсе). `test_50_cycles_controller_inventory_stable` и
  `test_controllers_are_owner_scoped_and_dispose_is_idempotent` обновлены на 7 владельцев с явной проверкой
  отсутствия удалённых имён в инвентаре. `ToolInteractionController`, `ContourEditingController`,
  `CalibrationController` и `WorkerBridge` — тоже «мёртвые» для `ViewerWidget` (виджет дублирует их
  поведение инлайн), но имеют полноценное протестированное поведение как отдельные модули (QH-3.2, #185);
  решение «подключить или удалить» для каждого из них вынесено в отдельный issue
  ([#466](https://github.com/areatu/SonoForge/issues/466)), а не решено механически в этом срезе.
