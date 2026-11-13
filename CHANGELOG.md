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

- `fix(units)`: #546 + #549 + часть #547 — пиксельные площади/объёмы без ложной конверсии, отказ от NaN/±∞ в Bernoulli/сосудистых метриках и калибровке ([полностью](changelog.d/041-fix-units-numeric-validation-546-549.md))
- `fix(dicom)`: #541 + #550 — декодер отдаёт корректные пиксели для всех поддержанных форматов и публикует cine только целиком ([полностью](changelog.d/040-fix-dicom-decode-contract-541-550.md))
- `fix(orthanc)`: #554 — атомарная запись в кэш (`0600`/`0700` при создании, temp+fsync+rename), валидация session id и символьных ссылок, fault-injection тесты ([полностью](changelog.d/039-fix-orthanc-cache-554.md))
- `fix(dicom)`: #543/#544 — file-aware immutable pixel cache и строгая полнота cine ([полностью](changelog.d/039-fix-dicom-cine-543-544.md))

- `test(ci)`: #556 — отдельный Qt/OpenGL-free regression lane и сохранение GUI hygiene ([полностью](changelog.d/038-test-pure-core-556.md))

- `docs(tracker)`: #538 — трекер синхронизирован с `main`: закрыты #510/#512/#514/#516/#518/#524, вопрос о FPS-правке вынесен в #539 ([полностью](changelog.d/037-docs-tracker-p24-538.md))

- `ci(ratchets)`: #536 — private-access ratchet видит контуры/зум и Orthanc-диалог: группы `ViewerWidget` (410 обращений в 30 файлах) и `OrthancStudyDialog` (497 в 4) ([полностью](changelog.d/036-ci-private-access-groups-536.md))

- `fix(orthanc)`: #534 — cache-сессия очищается при отмене загрузки и при любом завершении disk-экспорта ([полностью](changelog.d/035-fix-orthanc-cache-cleanup-534.md))

- `fix(orthanc)`: #532 — частичный отказ при сохранении на диск больше не уводит batch в cache-режим; успешные исследования экспортируются ([полностью](changelog.d/034-fix-orthanc-disk-partial-532.md))

- `refactor(arch)`: S-03a — состояние загрузки Orthanc перешло к одному Qt-free владельцу `DownloadBatch`; координатор использует публичный seam диалога ([полностью](changelog.d/033-refactor-arch-s03a-download-batch-530.md))

- `refactor(arch)`: A5 — состояние рисования и хранения контуров перешло к одному владельцу `ViewerContours`; клинические расчёты и рендеринг остались у виджета ([полностью](changelog.d/032-refactor-a5-contours-528.md))

- `refactor(arch)`: A4 — окно подписи измерения, overrides и цикл подписей калипера перешли к одному владельцу `ViewerLabelPicker`; клиническое применение подписи осталось у виджета ([полностью](changelog.d/031-refactor-a4-label-picker-526.md))

- `refactor(arch)`: A3 — режимы зума, Ctrl+wheel и «лупа» перешли к одному владельцу `ViewerZoom`; виджет оставил только публичные фасады ([полностью](changelog.d/030-refactor-a3-viewer-zoom-524.md))

- `refactor(arch)`: A2 — window/level/DR, LUT и кэши WL/DR перешли к одному владельцу `ViewerDisplay`; `set_state`/`show_frame` делегируют восстановление значений ([полностью](changelog.d/029-refactor-a2-viewer-display-522.md))

- `refactor(arch)`: A1 — транспорт просмотра перешёл к одному владельцу `ViewerTransport`, `set_state`/`set_transport_state` больше не дублируют проекцию ([полностью](changelog.d/028-refactor-a1-viewer-transport-520.md))

- `refactor(arch)`: S-03 — выбор исследований в Orthanc-диалоге перешёл к одному владельцу `StudySelection` ([полностью](changelog.d/027-refactor-arch-s03-518.md))

- `test(viewer)`: QH-0 — characterization harness зафиксировал наблюдаемое поведение `ViewerWidget` перед экстракцией кластеров ([полностью](changelog.d/026-test-viewer-qh0-516.md))

- `refactor(arch)`: S-02b — FPS-правка и посчитанный strain теперь принадлежат вкладке ([полностью](changelog.d/025-refactor-tab-state-514.md))

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
