- `refactor(arch)`: #420 (QH-3 follow-up, slice 3) — у позиции оверлея результатов остался один
  владелец: `ResultsOverlayController`. `ViewerWidget` больше не держит
  `_results_overlay_custom_position` / `_results_overlay_cleared` / `_results_overlay_position_just_restored`
  / `_results_overlay_suppressed`, и вторую реализацию геометрии (`_reposition_results_overlay_label` и
  соседние методы удалены — три метода, ~45 строк). `set_results_overlay`, `set_results_overlay_position`,
  `reset_results_overlay_to_default`, `set_results_overlay_suppressed` и `_mark_results_overlay_custom_position`
  остаются как тонкие обёртки для существующих вызывающих (`main_window.py`, тесты), но всё состояние и вся
  геометрия — на контроллере. `MainWindow` больше не пишет напрямую в приватное поле виджета
  (`_results_overlay_cleared = False` → публичный `reset_results_overlay_cleared()`). Попутно унаследован
  фикс «очистка должна стирать текст, а не только прятать» — он был только в виджете и не попадал в
  контроллер, пока тот не использовался по-настоящему; теперь обе ветки (`clear`/`reset`) используют одну
  реализацию `ResultsOverlayController.set_text`. Новые случаи — `TestResultsOverlayPositionOwner` в
  `tests/unit/test_qh3_results_overlay_owner.py` (7 GUI-случаев: отсутствие второй копии состояния,
  круговой проезд позиции через владельца, erase-при-очистке, блокировка `cleared` до явного сброса,
  suppressed прячет и блокирует новый текст, сброс `cleared` без приватной записи). Обновлены
  `tests/unit/test_presenter_view.py` и `tests/unit/test_viewer_widget.py`: прямой доступ к
  `viewer._results_overlay_custom_position` и запись `w.contract.results_overlay_custom_position = True`
  заменены на публичный `results_overlay_custom_position()` / `results_overlay_controller.mark_custom_position()`;
  две записи убраны из замороженного `tests/architecture/viewer_contract_allowlist.json`
  (`_results_overlay_cleared`, `_results_overlay_custom_position`).
