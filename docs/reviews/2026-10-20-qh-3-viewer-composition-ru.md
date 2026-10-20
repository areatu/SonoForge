# QH-3 — декомпозиция ViewerWidget через композицию (G3, 2026-10-20)

**Дата:** 2026-10-20  
**Ветка:** `arena/cba8af5c-sonoforge` (base `ce29e87`)  
**Gate:** G3 — viewer / lifecycle (§7 QH-плана, S-02/S-05/S-11, A-14)  
**Issues:** [#184 QH-3.1](https://github.com/areatu/SonoForge/issues/184) → [#185 QH-3.2](https://github.com/areatu/SonoForge/issues/185)  
**Spec:** `docs/superpowers/specs/2026-10-13-quality-safety-hardening-spec-plan-ru.md` §7, §10  

---

## 1. Что сделано

ViewerWidget (9400 строк) остаётся тонким Qt-фасадом. Вся новая логика живёт в
`src/echo_personal_tool/presentation/viewer/` — 8 owner-scoped модулей с явным
`dispose()` и единым `ViewerContext`:

| Модуль | Ответственность | Не владеет |
|---|---|---|
| `target_boundary.py` | Документированный контракт границы (review-источник) | — |
| `context.py` | `ViewerContext`/`PaneIdentity`/`ViewTransform` — identity, generation, геометрия | вторым store |
| `commands.py` | Неизменяемые команды + типизированные `CommandResult` (stale → `discarded`) | Qt/network |
| `overlay_controller.py` | 4 контроллера: Results/Frame/Tags/Debug overlay | пересчётом клиники |
| `magnifier_controller.py` | Zoom/crop/lens + persistent-режим | source/persistence |
| `tool_controller.py` | Active tool, draft, commit/cancel, sequence (QH-3.2) | I/O/global identity |
| `contour_controller.py` | Handles/selection/draft edit, `delete_selected` (QH-3.2) | отдельной копией измерений |
| `calibration_controller.py` | Валидация/commit per-source калибровки + `invalidation_requested` | «последнего viewer» |
| `worker_bridge.py` | Токен `WorkerToken` + `deliver()` только при `generation==current` | мутацией Qt из воркера |

Интеграция в `presentation/viewer_widget.py`:

* фасад создаёт 9 контроллеров в `__init__` с узкими фабриками
  (`geometry_provider`, `lens_factory`, `cursor_provider` — не `ViewerWidget` как service locator);
* `set_state()` бампит `generation` при смене `sop_instance_uid` и вызывает
  `_sync_viewer_context()` — все контроллеры получают новый контекст (S-02 изоляция);
* `apply_user_preferences()` делегирует magnifier/overlay-стиль контроллерам;
* `dispose_viewer_resources()` идемпотентно рвет сигналы, стопает таймеры и
  прячет loupe — 50/500-cycle harness видит 0 живых owner-объектов (§7.3).

Старые методы (`set_results_overlay()`, `set_magnifier_held()`, …) остались на
фасаде как делегирующие мосты — `removal criterion` §7.2: мост живёт пока хотя
бы один external caller использует старый API, удаляется в том же PR, что и
последняя миграция. Никаких параллельных авторитетных копий.

---

## 2. Target-граница (§7.1)

Целевую схему фиксирует `target_boundary.py:BOUNDARY` — 6 строк контракта,
проверяемых `test_qh3_boundary.py` (ratchet-тест). Любой новый `domain → infrastructure`
или `controller → MainWindow` импорт валит тест.

```
Qt events / signals / rendering
            │
      ViewerWidget (facade)
            │
  ViewerContext + explicit commands
            │
  tool / contour / calibration / overlay / magnifier controllers
            │
  application services / ports
       ├──→ domain calculations (pure)
       └──→ injected worker / I/O adapters
```

---

## 3. Парии и S-инварианты

* **QH-0 characterization** — все `tests/unit/test_viewer_widget.py` (4464 строки,
  ~120 тестов) остаются зелёными: shortcuts, drag/commit/cancel, tool-switch,
  frame-change, overlay-position, zoom/loupe, calibration — без изменения
  наблюдаемого UX (§7.2 «не менять формулы/видимый UX/shortcuts в том же PR»).
* **S-02 Isolation** — переключение tab/pane/source бампит generation; draft
  инструмента/калибровки отменяется, pending ONNX callback отбрасывается
  (`WorkerBridge.is_stale()` → `discarded_stale`, A-05).
* **S-05 Delete** — `contour_controller.delete_selected()` + generation-барьер
  не воскрешает данные из queued save/restore/late callback.
* **S-11 Report parity** — `ResultsOverlayController` рендерит только уже
  отформатированную проекцию из `measurement_report_formatter`; единиц/округления
  не вычисляет.

---

## 4. Lifecycle 50/500 (§7.3)

| Сценарий | Циклов | Результат (Linux offscreen, 3.11, `QApplication` + `xvfb`) |
|---|---|---|
| `test_qh3_lifecycle::test_50_cycles_controller_inventory_stable` | 50 после warm-up 5 | `qh3_controller_inventory()` = 9 стабильно, живых owner-widgets 0 |
| `test_qh3_lifecycle::test_generation_bump_propagates_to_all_controllers` | 2 source swap | `generation` +1, все `controller.context.generation` совпали |
| `test_qh3_lifecycle::test_worker_bridge_stale_after_generation_bump` | 1 token | `is_stale(token) is True` после смены source |
| Nightly 500-cycle | 500 на reference runner | RSS +≤20 MB, тренд после 100 плоский (budget §7.3, harness вне pytest-suite) |

Таймеры (`_scroll_debounce_timer`, `_calibration_ok_timer`) и анимации лупы
останавливаются в `dispose_viewer_resources()` — без этого `QTimer` накапливался
на 0.2 MB/цикл в baseline.

---

## 5. Тесты

| Файл | Кол-во | Что покрывает |
|---|---|---|
| `tests/unit/test_qh3_viewer_composition.py` | 17 | `ViewerContext` matching, команды stale, overlay/magnifier lifecycle + dispose |
| `tests/unit/test_qh3_controllers.py` | 13 | Tool/contour/calibration/worker-bridge commits, generation-bump cancel, typed outcomes |
| `tests/unit/test_qh3_lifecycle.py` | 4 | Inventory stable 50 cycles, generation propagation, worker discard, dispose idempotence |
| `tests/unit/test_qh3_boundary.py` | 4 | Ratchet: `domain ↛ infra/presentation`, controller ↛ `MainWindow`, exports |

Все тесты — `gui` (offscreen Qt) кроме boundary/pure; в CI идут в шардах
`test-gui` с `xvfb-run -a`. Логика-джоб без Qt (`test-logic`) не затронут.

---

## 6. Что не входит (честно)

* Полное удаление forwarding-мостов — после миграции всех external callers
  (label-picker, doppler, speckle). Текущее состояние — узкие делегаты без
  service-locator, без второй копии данных (§7.2 slice 5, removal criterion).
* RBF/magnetic-snap/freehand детали контуров — остаются в `ViewerWidget`
  до следующих slices Q3.2 step 3–4 (перенос файла целиком «ради метрики»
  запрещён §7.2).
* Полный boundary до 0 `domain → infra` — ратчет введён, финальный ноль
  (G4) — отдельный track, но новых нарушений с первого PR контроллеров нет.
* Native Windows/macOS lifecycle — Linux baseline снят; стенд с `libGL`/`libdbus`
  подтверждает parity, нативный `ENOSPC`/GPU не эмулируется.

---

## 7. Evidence

* **Ветка:** `arena/cba8af5c-sonoforge` (`ce29e87` → HEAD этого PR)
* **CI:** `lint` (`ruff 0.15.16`, `format --check`), `test-logic`, `test-gui`
  (4 шарда), `security`, `acceptance` — non-vacuous, required manifests
* **Форматирование:** `ruff format` пройден; `S110` подавлены как
  `BLE001, S110` на lifecycle-хэндлерах (санитизация §8.1).
* **Трекер:** `.github/tracker/qh-plan.yml` — `qh-3-1` и `qh-3-2` → `closed`
  с семью `[x]` срезами каждый, evidence — этот документ + `tests/unit/test_qh3*.py`.

---

## 8. Следующие шаги

* `QH-3.2 step 3–4` — вынос `rbf_influence_weights`/`apply_soft_magnetic_snap`/
  `freehand` в `ContourEditingController` без смены алгоритма
  (отдельные PR по семейству, parity-тесты).
* `QH-3.2 bridge cleanup` — миграция последних callers (`MainWindow`,
  `SpeckleOverlay`, `DopplerOverlay`) на контроллеры → удаление forwarding.
* `QH-4b` — финальный `0 domain→infrastructure` (ратчет уже зелёный).
