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
| [2026-10](changelog/2026-10.md) | 2 | v0.3.3 — 2026-10-15 |
| [2026-09](changelog/2026-09.md) | 19 | v0.3.1 — 2026-09-27 |
| [2026-08](changelog/2026-08.md) | 19 | 2026-08-23 |
| [2026-07](changelog/2026-07.md) | 24 | 2026-07-31 |
| [2026-06](changelog/2026-06.md) | 17 | 2026-06-30 |

---

## Unreleased

Не выпущено: ниже — индекс, полный текст каждой записи — по ссылке.

- `docs(links)`: #329 — документация больше не ссылается в пустоту; проверка ссылок и ratchet ID-ссылок в CI, CHANGELOG стал индексом ([полностью](changelog.d/076-docs-links-329.md))
- `refactor(arch)`: #328 — циклы импорта 8 → 0 (в issue 7: к ним добавились цикл фасада настроек и цикл темы) ([полностью](changelog.d/075-refactor-arch-328.md))
- `test(ci)`: #327 (срез 2) — долг гейта «тест без проверочного сигнала» 216 → 164: 51 тест усилен настоящей проверкой (вызов, запись в лог, состояние, сигнал вместо «не упало»; `smoke` не потребовался ни разу), ручные диагностики `interactive`… ([полностью](changelog.d/074-test-ci-327.md))
- `test(ci)`: #327 (срез 1) — гейт «тест без проверочного сигнала». `scripts/check_test_signal.py` (только stdlib, шаг job `lint`) требует у каждого нового теста `assert`, `raises`/`warns`, `assert_*`-вызов, `waitSignal`/`waitUntil` или… ([полностью](changelog.d/073-test-ci-327.md))
- `build(mypy)`: #325 (финальный срез) — голых `# type: ignore` больше нет: 63 → 0, подавлений 252 (64 bare) → 178 (0 bare, 0 без причины) в 49 файлах, per-package override'ы удалены, issue закрывается ([полностью](changelog.d/072-build-mypy-325.md))
- `build(mypy)`: #325 (срез 4) — `disallow_untyped_defs` и `disallow_incomplete_defs` включены: `application` и `infrastructure` теперь не просто проверяются, а аннотированы ([полностью](changelog.d/071-build-mypy-325.md))
- `build(mypy)`: #325 (срез 3) — `attr-defined` включён, `disable_error_code` больше нет ни в одном override'е ([полностью](changelog.d/070-build-mypy-325.md))
- `build(mypy)`: #325 (срез 2) — `disable_error_code` сжат с трёх кодов до одного ([полностью](changelog.d/069-build-mypy-325.md))
- `build(mypy, ci)`: #325 (срез 1) — bare `# type: ignore` больше не проходит, счётчик подавлений стал ratchet'ом, `application` поднят на ступень строгости ([полностью](changelog.d/068-build-mypy-ci-325.md))
- `fix(setup)`: #326 (закрытие остатка) — диалог первого запуска больше не отвечает «успех» всегда, а установка зависимостей говорит, что именно случилось ([полностью](changelog.d/067-fix-setup-326.md))
- `docs`: #312 / S3-03 — `docs/bench` снова отслеживается, CHANGELOG разрезан, ROADMAP переписан ([полностью](changelog.d/066-docs-312.md))
- `fix(report, safety)`: #313 / S3-04 — PDF-экспорт в worker, лимит пикселей, accessibility отчёта ([полностью](changelog.d/065-fix-report-safety-313.md))
- `chore(deps, ci)`: #311 / S3-02 — numpy 2 и Python 3.12/3.13 в поддерживаемом диапазоне ([полностью](changelog.d/064-chore-deps-ci-311.md))
- `ci(gui, tests)`: #310 / S3-01 — Windows/macOS GUI-smoke и regression/migration в CI ([полностью](changelog.d/063-ci-gui-tests-310.md))
- `chore(distribution)`: #302 / S1-03 (P1-3/4/5) — приёмка верифицирована, issue закрывается ([полностью](changelog.d/062-chore-distribution-302.md))
- `chore(quality)`: #309 / S2-05 — mypy для `domain/` и `application/` завершён ([полностью](changelog.d/061-chore-quality-309.md))
- `fix(ui, multiview)`: #308 / S2-04 (хвост) — удаление event-маркеров Multiview теперь спрашивает подтверждение ([полностью](changelog.d/060-fix-ui-multiview-308.md))
- `fix(ui, tool-row)`: режим ряда инструментов выбирается по числу скрытых кнопок, а не по доле подписей ([полностью](changelog.d/059-fix-ui-tool-row.md))
- `fix(i18n, ui)`: отчёт Linux-сессии 2026-10-30, пункт 4 — в английском интерфейсе оставались русские подписи ([полностью](changelog.d/058-fix-i18n-ui.md))
- `fix(ui, tool-panel)`: отчёт Linux-сессии 2026-10-30 (скриншоты 1–3) — панель измерений по умолчанию открывается шириной 420 px (было 320 при свежем профиле: 280) ([полностью](changelog.d/057-fix-ui-tool-panel.md))
- `fix(ui, stability)`: Debian SIGSEGV при быстром скролле меню/пресетов — устранён доказанный core-дампами путь application-wide Python event filter → Shiboken wrapper внутреннего no-RTTI объекта QtWebEngine (`RenderWidgetHostViewQtDelegateItem`) ([полностью](changelog.d/056-fix-ui-stability.md))
- `chore(quality)`: #304 / S1-05 (дрифт после слияния) — осиротевший `ReportDialog` удалён: режим «Отчёт» (`presentation/report_mode/`) полностью забрал шапку (`ReportPatientEditor`), заключение, предпросмотр и экспорт PDF (UI-4 PR-2/3/5), а импорт из… ([полностью](changelog.d/055-chore-quality-304.md))
- `feat(orthanc)`: Load from Server — обогащение строк метаданными инстансов: чипы-фильтры режимов 2D/Color/M/PW/CW (по SequenceOfUltrasoundRegions, с учётом mis-tag Samsung), фильтры «Стресс» (ДОБУТАМИН/StageName) и «STE?» (эвристика: мультикадровый… ([полностью](changelog.d/054-feat-orthanc.md))
- `fix(tabs, ui)`: PR #372 «Fix 4 UI bugs on Windows 10» + починка его CI-прогона (run40691554153, ветка `arena/5b68af15-sonoforge`, ошибки lint/test-gui) ([полностью](changelog.d/053-fix-tabs-ui-372.md))
- `fix(tools, cine)`: приёмка Win10 от 2026-10-27 — сетка «Анатомии» получила собственный минимум высоты, двухстрочные кнопки считают высоту по метрикам шрифта, вложенные layouts обновляются до перерисовки; на короткой панели элементы прокручиваются… ([полностью](changelog.d/052-fix-tools-cine.md))
- `fix(errors)`: #306 + QH-4a ER-05/ER-06 — отказы persistence/viewer больше не прячут произвольные ошибки: в `measurement_persistence` и `presentation/viewer/*` широкие перехваты заменены ожидаемыми типами; для fallback-ошибок используются… ([полностью](changelog.d/051-fix-errors-306.md))
- `fix(persistence)`: #323 — автосохранение, включённое в сессии, теряло уже сделанные измерения (потеря данных, P0) ([полностью](changelog.d/050-fix-persistence-323.md))
- `chore(app)`: #330 (пункт 3) — `__import__("numpy")` в `app_controller.py` заменён на модульный `np` (файл и так импортирует numpy и использует его в десятках мест); `grep __import__( src` пуст ([полностью](changelog.d/049-chore-app-330.md))
- `ci(security)`: #324 — security-гейты bandit + pip-audit по двум контурам зависимостей ([полностью](changelog.d/048-ci-security-324.md))
- `fix(setup)`: #326 (остаток после триажа) — список проверки окружения в `runtime_setup` приведён в соответствие с фактическими зависимостями, успех установки теперь верифицируется ([полностью](changelog.d/047-fix-setup-326.md))
- `chore(tests)`: S1-04 (аудит 2026-10-22 §13) — храповик строгих `xfail` ([полностью](changelog.d/046-chore-tests.md))
- `fix(ui)`: приёмка 0.3.3 на Win10 — семь дефектов интерфейса (список от 2026-10-23) ([полностью](changelog.d/045-fix-ui.md))
- `fix(ui)`: четыре правки по приёмке 0.3.3 — окошко подписи только в эхокардиографии, парные инструменты в Quick, подсказка поверх карточки норм, палитра концепта ([полностью](changelog.d/044-fix-ui.md))
- `fix(deps)`: закрыты все алерты Dependabot (31 уязвимая запись по GitHub Advisory Database: 3 critical, 19 high, 9 medium; сам GitHub на `main` насчитывал 28) — `uv.lock` пересобран, нижняя граница Python поднята 3.10 → 3.11… ([полностью](changelog.d/043-fix-deps.md))
- `feat(release)`: QH-5a — locked package matrix и доказательства по упакованному артефакту (issue #188, спека QH §9.1, A-16/A-17, gate G5a) ([полностью](changelog.d/042-feat-release-qh-5a.md))
- `test(report)`: UI-4 gate — golden-тесты текста экрана и PDF на RU и EN (спека редизайна §4.6, S-11) ([полностью](changelog.d/041-test-report-ui-4.md))
- `feat(report)`: UI-4 PR-4 — «откуда значение»: карточка происхождения по наведению на значение листа (спека редизайна §4.6, QH §5.3 пп ([полностью](changelog.d/040-feat-report-ui-4.md))
- `feat(report)`: UI-4 PR-5 — экспорт PDF, печать и «Завершить»; «не оценивалось» теперь печатается (спека редизайна §4.6, UQ-06, UQ-07) ([полностью](changelog.d/039-feat-report-ui-4.md))
- `feat(report)`: UI-4 PR-3 — «Фразы»: библиотека готовых фраз и вставка в заключение (спека редизайна §4.6, UQ-08) ([полностью](changelog.d/038-feat-report-ui-4.md))
- `feat(studies)`: UI-7 — браузер исследований A2 на пустой вкладке (спека редизайна §4.10, UD-01) ([полностью](changelog.d/037-feat-studies-ui-7.md))
- `feat(focus)`: UI-6 — режим «Фокус» для одиночного файла (спека редизайна §4.8, UQ-02, UD-04, S-02) ([полностью](changelog.d/036-feat-focus-ui-6.md))
- `feat(reference)`: UI-5 PR-4 — карточка S2 у строк панели измерений и точки норм (спека редизайна §4.7, §8.2, UD-14, UQ-03, UA-15; хозяин списка — панель 2.0 после TP-2 gate) ([полностью](changelog.d/035-feat-reference-ui-5.md))
- `feat(report)`: UI-4 PR-1 — режим «Отчёт» R3: переключатель, режим вкладки и предпросмотр листа A4 (спека редизайна §4.6, §8.4, UD-08; путь (а) спайка UI-4.0) ([полностью](changelog.d/034-feat-report-ui-4.md))
- `fix(tools)`: окошко «Подписать измерение» (TP-4) теперь гарантированно не выходит за границы вьюера при любых метриках шрифтов ([полностью](changelog.d/033-fix-tools-tp-4.md))
- `feat(report)`: UI-4.0 спайк — предпросмотр отчёта (спека редизайна §4.6, §8.4): путь (а) принят — лист A4 в режиме «Отчёт» показывает байты PDF из `measurement_report_pdf.py` через `QPdfDocument` + `QPdfView`, «откуда значение» — по координатам… ([полностью](changelog.d/032-feat-report-ui-4-0.md))
- `feat(tools)`: TP-4 — окошко «Подписать измерение» после свободного калипера или трассы (спека TP §4.4, §8.1, §9, макет 5) ([полностью](changelog.d/031-feat-tools-tp-4.md))
- `feat(reference)`: UI-5 PR-2 — окно справочника S1 (немодальное, в стиле заголовка Windows 11; спека редизайна §4.7, §8.5; UD-06, UD-14, UQ-03, UA-13) ([полностью](changelog.d/030-feat-reference-ui-5.md))
- `feat(reference)`: UI-5 PR-1 — карточка нормы S2 без рисунков (спека редизайна §4.7, §8.5, §9; UD-06, UD-14, UD-15, UQ-12; UA-13) ([полностью](changelog.d/029-feat-reference-ui-5.md))
- `refactor(theme, gallery)`: UI-2 PR-4 — однострочная лента клипов с группами и перенос `thumbnail_gallery` на токены (спека редизайна §4.2/§5.2, редизайн §8.1; продолжение PR-7b — последний блок хрома, который ждал ленту) ([полностью](changelog.d/028-refactor-theme-gallery-ui-2.md))
- `refactor(theme)`: хвост переноса оверлеев на токены (UI-0 PR-7b, спека редизайна §5.2, UD-16, продолжение PR-7) ([полностью](changelog.d/027-refactor-theme-ui-0.md))
- `fix(fonts)`: атомарная запись кэша bundled-шрифтов (найдено на CI UI-2 PR-2: GUI-шард падал с `Failed to load bundled font: Inter-Medium.ttf`, когда xdist-воркеры одновременно грели общий кэш и читатель видел недописанный файл… ([полностью](changelog.d/026-fix-fonts-ui-2.md))
- `feat(layout)`: UI-2 PR-2 — раздел компоновки в настройках, пресеты и новое меню «Компоновка» (спека редизайна §4.2/§4.9/§8.1, UA-04/G-2) ([полностью](changelog.d/025-feat-layout-ui-2.md))
- `feat(tools)`: TP-2 PR-1 — каркас панели измерений 2.0 под экспериментальным флагом (спека TP §4.2, A-01/A-02) ([полностью](changelog.d/024-feat-tools-tp-2.md))
- `fix(persistence)`: QH-1c (#176) — после failed directory-fsync импорт и delete/delete-all retry больше не застревают на устаревшей revision: read-back обновляет только ожидаемую CAS-ревизию/подтверждённое отсутствие, не выдавая success и не… ([полностью](changelog.d/023-fix-persistence-qh-1c.md))
- `feat(persistence)`: QH-1c (#176) — явный импорт перемещённого не-DICOM по однозначному полному SHA-256 + frames/spacing, с count в preview и повторным hash на подтверждении ([полностью](changelog.d/022-feat-persistence-qh-1c.md))
- `fix(reference)`: UI-5 PR-0 — ММЛЖ (`lvm`) в RU/EN приведена к линейному методу (М-режим): женщины 67–162 / 163–186 / 187–210 / ≥211 г; мужские диапазоны без изменений ([полностью](changelog.d/021-fix-reference-ui-5.md))
- `fix(tracker)`: серия падений workflow `Project sync` — первый реальный прогон (bootstrap из PR #170 прошёл, секрет `PROJECTS_TOKEN` настроен) умирал на каждой записи single-select поля с… ([полностью](changelog.d/020-fix-tracker-170.md))
- `ci(quality)`: QH-2a.1 ч.2 — одна зафиксированная инструментальная цепочка и невакуумные гейты безопасности/приёмки (спека QH, G1/S-12, A-13) ([полностью](changelog.d/019-ci-quality-qh-2a-1.md))
- `ci(ui)`: храповик цветовых литералов и проверка контраста токенов (UI-0 PR-1, спека редизайна §5.3, G-3/G-4) ([полностью](changelog.d/018-ci-ui-ui-0.md))
- `refactor(theme)`: UI-0 PR-5 — справочник на токенах (спека редизайна §5, UD-09; вид не меняется) ([полностью](changelog.d/017-refactor-theme-ui-0.md))
- `refactor(theme)`: UI-0 PR-3 — верхняя панель и строка состояния на токенах (спека редизайна §5, UD-09; вид не меняется, кроме снятой подсветки «Нормативов») ([полностью](changelog.d/016-refactor-theme-ui-0.md))
- `refactor(theme)`: токены оформления вместо сырых цветов (UI-0 PR-1, спека редизайна §5, UD-09) ([полностью](changelog.d/015-refactor-theme-ui-0.md))
- `refactor(theme)`: слияние UI-0 PR-1 с #213 — один источник истины вместо двух параллельных реализаций (спека редизайна §9). #213 успел слить плоский модуль токенов `presentation/theme_tokens.py` и скрипт `scripts/check_theme_contrast.py`; этот PR… ([полностью](changelog.d/014-refactor-theme-ui-0.md))
- `fix(tests)`: время ожидания в `tests/unit/test_start_page_recents.py` (5 с → 15 с) ([полностью](changelog.d/013-fix-tests.md))
- `fix(theme)`: инверсия темы «Как в системе» на Windows (UI-0 PR-1, спека редизайна §2.1, UA-16) ([полностью](changelog.d/012-fix-theme-ui-0.md))
- `feat(security)`: QH-2b срез 1 — чистый evaluator транспортной политики `application/transport_policy.py` (S-08, спека QH §6.2; без сети, Qt, настроек и клиентов — только stdlib) ([полностью](changelog.d/011-feat-security-qh-2b.md))
- `feat(protocol)`: TP-3 PR-3 (UI-3) — слой представления протоколов: карточка протокола в панели 2.0 и полоса шага под снимком (UD-04) вместо баннера, уведомление автоперехода с чипами ДПП (Q-04/Q-07), подключение `ProtocolRunner` + `StudyProjection`… ([полностью](changelog.d/010-feat-protocol-tp-3.md))
- `feat(window-chrome)`: UI-1 PR-3 + UI-2 PR-1 — строка пациента 42 px и разнос кнопок `SystemBar` («PACS ▾» с загрузкой и отправкой, «Справочник» вместо «Нормативы», «ЧСС» и «Сравнить» в строке, «Презентация» в Presenter; «Настройки», «Компоновка» и… ([полностью](changelog.d/009-feat-window-chrome-ui-1.md))
- `feat(window-chrome)`: UI-1 PR-2 — заголовок окна 38 px: вкладки, «+», поле команд `Ctrl+K` и меню логотипа (спека UI §4.1, §4.3, §7, §8.3, §9, §11; UA-19; UA-01…UA-03 сохраняются) ([полностью](changelog.d/008-feat-window-chrome-ui-1.md))
- `feat(window-chrome)`: UI-1 PR-1 — hit-test зон оболочки окна, Win32-хром и запасная системная рамка (спека UI §4.3, §4.9, §8.2, §8.3, §9–§11; UA-01, UA-02, UA-03, UA-20) ([полностью](changelog.d/007-feat-window-chrome-ui-1.md))
- `feat(theme)`: UI-0 PR-2 — тема «Графит» выбирается в интерфейсе и база скриншотов (спека UI §5.2, §10; компоновка и поведение прежние) ([полностью](changelog.d/006-feat-theme-ui-0.md))
- `feat(catalog)`: TP-0 PR-3 — сверка каталога измерений с ASE 2025 Table 6 «Measurement dictionary» (спека TP §5.2, A-12; видимых изменений нет) ([полностью](changelog.d/005-feat-catalog-tp-0.md))
- `feat(tools)`: TP-0 PR-2 — раскладка панели измерений версии 3 и миграция раскладки v1/v2 (спека TP §8.2–8.3, A-11; видимых изменений нет) ([полностью](changelog.d/004-feat-tools-tp-0.md))
- `feat(doppler)`: ручная «ЧСС по допплеру» в «Общие» — два клика по одноимённым пикам соседних циклов задают горизонтальный интервал, ЧСС = 60 000 / Δt (мс) ([полностью](changelog.d/003-feat-doppler.md))
- `feat(calculations)`: QH-1b.2 срез 2 — единый ППТ и сохранённое происхождение ППТ (спека QH §5.2, A-03; срез 1 — PR #166) ([полностью](changelog.d/002-feat-calculations-qh-1b-2.md))
- `feat(profile)`: N-07 — единая capability-матрица Full/Presenter управляет историей путей/исследований, последней сессией, измерениями, вкладками, калькуляторами, серверными действиями и окном докладчика ([полностью](changelog.d/001-feat-profile-n-07.md))
