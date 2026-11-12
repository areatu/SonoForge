# CHANGELOG — SonoForge

Все значимые изменения проекта. Формат записи: `[feat/fix/refactor/perf/docs/chore]: описание` (коммит-конвенция).

## Как устроен файл

* **`Unreleased`** — всё, что уже в `main`, но ещё не выпущено. Это **индекс**: одна строка на запись
  (новейшие сверху) со ссылкой на полный текст во фрагменте `changelog.d/NNN-<тип>-<область>-<ссылка>.md`.
  Так файл читается за минуту, а подробности и результаты прогонов остаются под рукой (issue 329).
* **`changelog.d/`** — по одному фрагменту на запись; формат и номера — в `changelog.d/README.md`.
* **`changelog/YYYY-MM.md`** — история по месяцам. При выпуске релиза фрагменты переезжают
  (в порядке номеров) в файл своего месяца, `changelog.d/` очищается, а в `Unreleased` остаётся только
  строка «выпущено в vX.Y.Z». Так `CHANGELOG.md` остаётся читаемым, а история — полной (S3-03, issue 312).
* Один PR = один фрагмент + одна строка индекса, с номерами issue/спеки и результатами прогонов.

## История по месяцам

| Месяц | Записей | Первая (свежая) запись |
|---|---|---|
| [2026-11](changelog/2026-11.md) | 1 | v0.4.0 — 2026-11-09 |
| [2026-10](changelog/2026-10.md) | 2 | v0.3.3 — 2026-10-15 |
| [2026-09](changelog/2026-09.md) | 19 | v0.3.1 — 2026-09-27 |
| [2026-08](changelog/2026-08.md) | 19 | 2026-08-23 |
| [2026-07](changelog/2026-07.md) | 24 | 2026-07-31 |
| [2026-06](changelog/2026-06.md) | 17 | 2026-06-30 |

---

## Unreleased

Не выпущено: ниже — индекс, полный текст каждой записи — по ссылке.

- `refactor(arch)`: S-02a — сорванное переключение вкладки возвращает её значения сразу, а не при следующем переключении ([полностью](changelog.d/024-refactor-abort-restores-tab-512.md))

- `refactor(arch)`: S-02 — память вкладки вернула калибровку, BSA и измерения при переключении ([полностью](changelog.d/023-refactor-tab-memory-510.md))

- `fix(ui)`: автовход в «Фокус» выключен по умолчанию, сохранённые настройки остаются ([полностью](changelog.d/022-fix-focus-default-288.md))

- `refactor(ui)`: частичная чистка UI-8 и перевод трёх компонентов на токены ([полностью](changelog.d/021-refactor-ui8-278.md))

- `refactor(viewer)`: единый владелец DICOM tags overlay в TagsOverlayController ([полностью](changelog.d/020-refactor-tags-overlay-504.md))
- `refactor(main-window)`: протокольный workflow вынесен в owner-scoped ProtocolCoordinator ([полностью](changelog.d/019-refactor-protocol-503.md))
- `refactor(viewer)`: DopplerController — единый владелец калибровки и инструментов, закрывающая инвентаризация QH-3 ([полностью](changelog.d/018-refactor-viewer-420.md))
- `feat(a11y,i18n)`: доступные имена/описания иконочных кнопок (потолок `0`), явный `setTabOrder` и AST-гейт локализации `tr()`, закрытие эпика `#485` ([полностью](changelog.d/017-feat-a11y-i18n-484-485.md))
- `refactor(formatting)`: унифицировано форматирование клинических измерений через `MEASUREMENTS` и единую модель строк оверлея/отчёта/PDF ([полностью](changelog.d/016-refactor-formatting-482.md))
- `fix(layout)`: вертикальная галерея Mirrored вместо компактной горизонтальной ленты, с регрессионными проверками переключения раскладок ([полностью](changelog.d/015-fix-layout-500.md))
- `test(ci)`: подключены наборы `exploratory`/`compat`/`system`/`integration` в CI, покрыты `dcm_export_worker`/`roi_validator`/`orthanc_enrichment_worker` и введён ratchet непокрытых модулей ([полностью](changelog.d/014-test-ci-coverage-483.md))
- `refactor(viewer)`: удалены четыре неподключённых QH-3 владельца (`ToolInteractionController`, `ContourEditingController`, `CalibrationController`, `WorkerBridge`) и их тесты ([полностью](changelog.d/013-refactor-viewer-qh3-466.md))
- `refactor(arch)`: заморожен `constructor` в храповике слоёв и обнулены рёбра `ui>presentation`, `ui>infrastructure` и `constructor>infrastructure` ([полностью](changelog.d/012-refactor-ui-constructor-481.md))
- `refactor(arch)`: введён корень композиции `build_app_services(profile)` и убрана сборка графа объектов из конструкторов `MainWindow`/`AppController` ([полностью](changelog.d/011-refactor-composition-480.md))
- `ci(mypy)`: `mypy --strict` на `ui`, `constructor` и 71 модуле `presentation` + пофайловый храповик для оставшихся (`−124` `# type: ignore`, `271 → 377` строгих файлов) ([полностью](changelog.d/010-ci-mypy-476.md))
- `refactor(arch)`: контракт `UserPreferences` расширен до 88 полей, закрыт реэкспорт адаптерных типов через фасады `application` и убраны последние `pydicom.dcmread` из `presentation` ([полностью](changelog.d/009-refactor-arch-477.md))
- `refactor(viewer)`: состояние M-mode вынесено из ViewerWidget в `MModeController` (−10 полей, −13 имён allowlist) ([полностью](changelog.d/008-refactor-viewer-479.md))
- `refactor(main-window)`: режим отчёта вынесен из MainWindow в `ReportCoordinator` (−692 строки, −41 метод) ([полностью](changelog.d/007-refactor-main-window-478.md))
- `fix(dicom)`: предел на один кадр до декодирования и подсчёт кадров без чтения файла целиком ([полностью](changelog.d/006-fix-dicom-475.md))
- `ci(ratchets)`: храповики размера классов, приватного доступа к MainWindow/AppController и молчаливых `except` ([полностью](changelog.d/005-ci-ratchets-474.md))
- `ci(tests)`: гейт инвентаря тестов сравнивает с базовым коммитом вместо `_BASELINE` ([полностью](changelog.d/004-ci-tests-473.md))
- `docs(audit)`: анализ слабых сторон 2026-11-09 и план по фазам в issues #473–#485 ([полностью](changelog.d/003-docs-audit-485.md))
- `fix(release)`: проверяемое восстановление 0.4.0 без перемещения тега ([полностью](changelog.d/002-fix-040-recovery.md))
- `fix(release)`: версия SBOM и единые окончания строк lock-файла для release evidence ([полностью](changelog.d/001-fix-release-evidence.md))
