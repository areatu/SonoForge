- `refactor(arch)`: #420 — у магнитной лупы остался один владелец: `ViewerWidget` больше не держит
  копию `enabled/zoom/radius/linear_persistent/held/persistent/reduce_motion` и вторую реализацию
  геометрии линзы. Настройка идёт одним `configure()` на компоненте, удержание Z — `set_held()`,
  постановка точки — `notify_point_placed()`, предикат постоянной лупы — `sync_persistent()`.
  Ссылок на `_magnifier_*` в виджете 69 → 21 (ни одного поля состояния), `viewer_widget.py`
  10 358 → 10 304 строки. Попутно исправлено: выключение магнификатора без смены зума больше не
  оставляет видимую линзу. Новый `tests/unit/test_qh3_magnifier_owner.py` (8 GUI-случаев),
  `test_magnifier_trigger.py` переведён на публичный шов `viewer.magnifier_controller`;
  baseline разбиения `9940 → 9948` (gui `3992 → 4000`). Доказательства —
  `docs/reviews/2026-11-06-qh3-magnifier-owner-ru.md`.
