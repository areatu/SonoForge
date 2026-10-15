# Качество и безопасность SonoForge — спецификация и план реализации (QH)

**Дата:** 2026-10-13

**Статус:** Draft / предлагаемые требования для согласования; реализация этим документом не выполняется.

**Тип:** safety-контракты + архитектурная спецификация + поэтапный план PR и приёмки.

**Проверенная база:** `main` на `ca699673cb59b0215754da871e9075f5412b432e` (`ca69967`), после merge [#150](https://github.com/areatu/SonoForge/pull/150) и [#152](https://github.com/areatu/SonoForge/pull/152).

**Основание:** разбор аудита v0.3.2 / `a0c3f4a`; приоритет — доказанное поведение и достоверность результатов, а не уменьшение LOC или количества импортов.

**Область:** корректность измерений/persistence → реальные quality/security-gates и транспорт → композиция ViewerWidget → адресный аудит исключений/границ domain → проверяемые релизы и подпись.

> Это план инженерной верификации, а не заключение о клинической пригодности или соответствии MDR/FDA/GDPR. Наличие зелёного CI, gold-контуров или подписанного бинарника само по себе не подтверждает клиническую эквивалентность коммерческому ПО.

## 1. Решение в кратком виде

| Трек | Приоритет | Предлагаемый результат |
|---|---|---|
| **QH-1 — Достоверность и долговечность результатов** | P0 для ошибок привязки/потери данных; P1 для полноты | Правильный источник, явное происхождение, инвалидизация зависимых результатов, подтверждённое сохранение и честное восстановление |
| **QH-2 — Доказуемые gates и безопасный транспорт** | P0 для небезопасной передачи без согласия; P1 для инфраструктуры | Тесты вызывают production-код; критические наборы действительно выполняются; удалённый insecure transport требует явного исключения |
| **QH-3 — Композиция ViewerWidget и lifecycle** | P1 | Небольшие контроллеры с явным состоянием/владением ресурсами; ViewerWidget — тонкий Qt-фасад |
| **QH-4 — Ошибки и внутренние зависимости** | P1 адресно; P2 для остатка | Ошибки клинического действия не выглядят как успех; domain не зависит от infrastructure; ожидаемый cleanup не засоряет логи |
| **QH-5 — Проверяемый релиз и platform signing** | P1 для сборки/проверки; организационный трек для подписи | Зафиксированный toolchain, smoke упакованного приложения, согласованные manifests/SBOM/attestations, затем OS-подпись |

**Правила порядка:**

1. Сначала воспроизводящие тесты и исправления опасных интеграционных швов, а не массовый рефакторинг.
2. QH-1 и QH-2 идут параллельно; исправление обнаруженной ошибки не ждёт завершения всего трека.
3. Для QH-3 сначала фиксируются контракты состояния и тесты поведения. Изменение алгоритмов не смешивается с переносом кода.
4. QH-4 выполняется адресно рядом с изменяемыми сценариями; переписывать все `except Exception` одним PR запрещено.
5. Получение сертификатов/доступов QH-5 начинается сразу, но подписывается только проверенный артефакт разрешённого workflow.
6. При нехватке данных/доступов соответствующий gate имеет статус **BLOCKED**, а не PASS и не «готово по наличию кода».

## 2. Исходное состояние и связь с существующими планами

### 2.1. Что уже есть и не планируется повторно

| Срез на `ca69967` | Следствие |
|---|---|
| #147 / #151 в main: вкладки/StartPage, profile capabilities, portable settings; Full сохраняет измерения по умолчанию, Presenter — opt-in | Не повторять N-07 и не возвращать Full в default-off только из-за старого текста WP4 |
| #150 в main: канонический keyboard registry | Использовать существующий registry; пользовательский remapping не входит в QH |
| #152 в main: `TabCoordinator`, `DownloadCoordinator`, `ComparisonCoordinator` | Это первый срез N-08, а не завершённая декомпозиция ViewerWidget или pane-scoped инструменты |
| `StudyMeasurementSessionStore` + `MeasurementPersistence` + `MeasurementRepository` | Продолжать существующий вертикальный срез WP4, не создавать второй независимый store |
| Codec/schema v1/v2, `measurement_semantics_version`, bounded JSON, revision, атомарная запись, OS lock | Не заменять формат «с нуля»; новую схему вводить только с явной совместимостью |
| CodeQL `security-extended`, dependency-review, Ruff `S110`; Bandit/Safety в dev-зависимостях | SAST уже есть. Уточнять policy/покрытие/обязательность, не «возвращать отсутствующий SAST» |
| STE overview и GLS в отчёте, экспорт gold-разметки, фантом/референсы | Не повторять UI-функции; закрывать same-frame validation и происхождение результата |
| Native Windows persistence-проверки задокументированы | Не считать весь native acceptance незапущенным; учитывать точную область доказательства и отдельно остаток USB/native GUI |

**Старые документы содержат исторические статусы.** Например, WP4 §16 описывает первоначальный default-off/wire v1; это не актуальная конфигурация main. Настоящий план не переписывает ранее согласованные политики хранения, debounce/flush или профилей без отдельного решения.

### 2.2. Подтверждённые разрывы для работы

- `MainWindow._stored_measurement_records()` обращается к `MeasurementPersistence.store.entries()`. `store` — RAM `StudyMeasurementSessionStore`; `entries()` принадлежит файловому repository. Внешний `except` превращает ошибку интеграции в пустой список сохранённых исследований.
- При переключении вкладок `TabCoordinator.load_content()` выходит из special layouts; применение нового набора сбрасывает comparison session. Сценарий Э10 «клип A из вкладки 1 + клип B из вкладки 2» нельзя считать проверенным по отдельному тесту сравнимости пары.
- Строгий полный provenance/invalidation derived strain/vessel/Simpson ещё не закрыт. Ручные входы калькуляторов не имеют полного persistence-контракта.
- Основной `ci.yml` запускает `tests/unit`; отдельные `tests/security`/`tests/acceptance` не включены этим заданием. Это не означает отсутствия всех security unit-тестов, но не доказывает работу всей заявленной пирамиды.
- `test_https_enforcement.py` сам создаёт предупреждение внутри теста. Такой тест не проверяет production enforcement. Remote HTTP разрешён, DIMSE TLS выключен по умолчанию.
- Domain имеет прямые infrastructure-зависимости: ONNX/video/DICOM orchestration, image helpers, i18n и profiler. Само отсутствие Qt-импортов не означает строгую Clean Architecture.
- CI использует floating `pip install -e ".[dev]"`, а не существующий `uv.lock`; release-сборка также требует унификации установки и исключения скрытых fallback.
- Размер ViewerWidget и lifecycle тестового процесса — основание для декомпозиции/замеров, но не доказательство production-утечки или CPU-bottleneck.

Обязательность GitHub security-checks/rulesets не подтверждена: доступ к API branch protection был ограничен. Проверка администратором включена в QH-2, а не объявлена выполненной.

### 2.3. Документы-источники

- [WP4.1: measurement persistence](2026-10-03-wp4-1-measurement-persistence-spec-ru.md) — identity, storage, barriers, импорт/удаление.
- [WP4.2: рост/вес](2026-10-03-wp4-2-patient-metrics-spec-ru.md) — происхождение антропометрии.
- [Persistence / packaging / security](2026-10-01-persistence-packaging-security-plan.md) — зоны данных и packaging.
- [Вкладки / StartPage / Э10](2026-10-07-tabs-start-page-spec-ru.md) — существующее продуктовое требование сравнения.
- [Multiview](2026-10-01-multiview-two-clips-spec-ru.md) — инструменты в панелях отдельным этапом.
- [UI / data / Doppler roadmap](2026-10-02-ui-data-doppler-roadmap-ru.md) — Э/N/WP identifiers.
- [Windows acceptance](2026-10-08-wp4-windows-acceptance-checklist-ru.md) и [native D1–D4](../../persistence-native-acceptance-d1-d4.md) — фактическая область прошлых прогонов.
- [STE plan](../../STE_IMPROVEMENT_PLAN.md), [verification](../../STE_TRACKING_VERIFICATION.md), [vendor reference](../../STE_VENDOR_REFERENCE.md).
- [SECURITY](../../../SECURITY.md), [data inventory](../../security/data-inventory.md), [code signing](../../security/code-signing.md).

При реализации соответствующие документы обновляются вместе с поведением. Этот план задаёт приоритеты и проверяемые контракты; он не объявляет старые acceptance-пункты выполненными.

## 3. Scope и обязательные safety-инварианты

### 3.1. В scope

- Исправление интеграции сохранённых записей/StartPage и проверка уже согласованного Э10 на реальном lifecycle.
- Происхождение, актуальность и зависимости результатов; согласованное отображение в UI/тексте/PDF.
- Завершение safety-части WP4: authoritative delete, partial restore, ошибки записи, preview/status для небезопасных действий импорта/восстановления.
- Постоянное хранение согласованного allowlist ручных calculator inputs и переопределений.
- Реальные тесты транспортной политики, критических операций и клинических формул.
- Targeted native/platform lifecycle-проверки; воспроизводимое окружение CI и release.
- Постепенное выделение viewer-компонентов, внутренних границ и typed outcomes.
- Same-frame STE-сверка как отдельный, зависящий от эталонов подэтап.

### 3.2. Не входит

- Новый DICOM SR/XLSX-export, PACS-архив, сетевой shared store, RBAC и централизованный audit trail.
- Application-level шифрование всех PHI, secure erase, резервное копирование исходного PACS.
- Новый многопанельный measurement UX, включение LV-auto/Doppler/STE в обеих панелях. QH только готовит безопасный контракт и сохраняет существующие tool gates.
- Полный rewrite GUI, механическое разнесение в mixin, Protocol для каждого `tr()`/preferences helper.
- Новые STE-алгоритмы, low-SNR enhancement, tracking queue/cache или автоматический ED-draft в одном PR с верификацией.
- Disk frame/thumb cache, auto-update, полная accessibility-программа, report drafts и новая retention policy.
- Бинарная bit-for-bit воспроизводимость подписанных установщиков на разных машинах. Цель QH-5 — воспроизводимый состав/процесс/происхождение; подпись и timestamp меняют байты.

### 3.3. Контракты, которые нельзя нарушать

| ID | Инвариант |
|---|---|
| **S-01 Identity** | Измерение связано с проверенными study/source/frame, а не с текущим путём, названием вкладки или «последним viewer» |
| **S-02 Isolation** | Переключение study/tab/pane не переносит калибровку, ручной override, контур или worker-result на другой контекст |
| **S-03 Freshness** | Изменение значимого входа немедленно делает зависящий от него старый результат неактуальным; до пересчёта он не выдаётся как свежий |
| **S-04 Persistence** | «Сохранено» означает disk acknowledgement соответствующей ревизии; новая правка не становится clean по ответу старой записи |
| **S-05 Delete** | Удалённый объект/последний объект не воскресает из merge, queued save, restore или позднего callback |
| **S-06 Partial restore** | Недоступные записи не уничтожаются при сохранении доступной части и не участвуют как проверенные данные текущего отчёта |
| **S-07 Honest failure** | Неуспешное клиническое действие не отображается как успешное или как нормальный пустой результат |
| **S-08 Transport consent** | Перед credentials/PHI приложение проверяет effective endpoint/transport; небезопасный remote требует явного scoped исключения |
| **S-09 Privacy** | Диагностика содержит allowlisted codes/counters/opaque IDs, не PHI/payload/credentials/полные patient paths |
| **S-10 Profile boundary** | Presenter off не делает скрытого restore/autosave и не пишет на host при read-only portable root; Full сохраняет текущую политику |
| **S-11 Report parity** | UI, текст и PDF используют одну проверенную проекцию результата, единицы, округление, QC и provenance |
| **S-12 Proof** | Наличие тестового файла или успешный пустой/полностью skipped набор не является прохождением gate |

## 4. QH-0 — Подготовка и воспроизводящий baseline

Это небольшой первый PR, не самостоятельный большой аудит.

### Работы

1. Зафиксировать commit, Python/Qt/NumPy/ORT, платформу, профиль, версии инструментов и выбранные наборы. Использовать изолированные data roots и синтетические fixtures.
2. Воспроизвести через реальный controller/coordinator/repository:
   - StartPage после записи и рестарта;
   - A → B → A по вкладкам, включая разные spacing/ручные настройки;
   - неуспешный save + новая правка + Retry;
   - delete/reset при in-flight save;
   - Э10 с A/B из разных вкладок;
   - late frame/ONNX callback после смены контекста.
3. Зафиксировать существующее корректное поведение ViewerWidget characterization-тестами: shortcuts, drag/commit/cancel, переключение инструментов, frame change, overlay position, zoom/лупа, калибровка.
4. Снять production-like lifecycle baseline: открытие/закрытие clip/tab/dialog/strain window; RSS, живые owner-scoped QObject, threads/tasks, bounded caches. Отдельно от долгого pytest-suite.
5. Создать матрицу требований S-01…S-12 → test IDs → CI job → evidence. Возможное место отчёта: `docs/reviews/2026-10-13-quality-safety-baseline-ru.md` — только после фактического прогона.

**Gate G0:** известные дефекты воспроизводятся тестами или явно помечены «не воспроизведено/нужен стенд»; есть пригодный harness. Нельзя «закрепить» опасное старое поведение как ожидаемый эталон. Временные xfail — только с issue/reason/сроком; safety gate такой xfail не закрывает.

## 5. QH-1 — Достоверность, provenance и persistence

### 5.1. QH-1a: исправить reader и интеграционные швы Э5/Э10

**StartPage / manager:**

- UI получает summaries сохранённых записей через публичный application API, реализованный поверх существующего repository и persistence worker.
- Не делать `path.read_bytes()`/decode полного хранилища в GUI-потоке и не вызывать инфраструктурные/private методы coordinator из MainWindow.
- Summary: непрозрачный key, время/ревизия при наличии, количество/типы измерений, статус readable/corrupt/unsupported/unavailable. Полный payload не нужен странице.
- Один нечитаемый record не скрывает остальные. Ошибка всего списка отличается от нормального пустого хранилища.
- Уважать capability matrix и off-policy: Presenter без history не перечисляет записи на старте; выключенный persistence не включает скрытое восстановление. Явный manager — отдельное действие пользователя.

**Э10:**

- Завершить уже согласованный workflow выбора клипа A из одной вкладки и B из другой без разрушения выбранной comparison pair при промежуточном switch.
- Comparison context владеет ссылками на источники/сессии; переключение обычной активной вкладки не означает автоматически «новый пациент в comparison».
- Явная замена/очистка пары увеличивает generation; поздние ответы старой пары отбрасываются.
- Подписи источников, правила геометрии/частоты и ограничения синхронизации брать из спецификации Э10, не изобретать новые.
- Закрытие вкладки/очистка Z3 не удаляет источник, ещё используемый открытой comparison pair. Политика ownership/reference lifetime должна быть тестируемой.
- Инструменты измерений остаются заблокированными до отдельного pane-scoped этапа.

**Приёмка:** record записан настоящим repository → новый процесс/UI → summary доступен; один corrupt сосед не прячет valid. A/B из разных вкладок сохраняются после выбора; metadata badge и Presenter mirror совпадают; несовместимая синхронизация объясняется; закрытие owner-tab не оставляет viewer с удалённым cache path без явного завершения comparison.

### 5.2. QH-1b: контракт provenance и freshness

Новая модель расширяет существующие measurements/`StrainAnalysis`/`StudyMeasurementData`, а не дублирует их. Имена DTO и размещение уточняются в первом design PR; семантика ниже обязательна.

**Для каждого производного результата хранить:**

- stable result ID и method ID;
- проверенную study/source identity, frame/cycle/ROI/ED/ES там, где они реально использованы;
- ссылки на входные measurement IDs и их content revisions; для существующих типов без ID — добавить стабильный ID с правилами миграции;
- spatial/temporal/velocity calibration и версию её нормализации;
- algorithm/measurement-semantics version, значимые configuration values или их digest, model identity/hash для реально использованной AI-модели;
- единицы и определения результата (например, GLS peak/ESS/layer), источник ручного/измеренного входа;
- QC/coverage, причины исключений и declared fallback;
- состояние актуальности и reason codes. Timestamp сохраняется как метаданные, но не заменяет identity/revision.

**Freshness отдельно от QC:**

| Состояние | Смысл | UI / report |
|---|---|---|
| `fresh` | Требуемые входы доступны/совместимы, их ревизии и метод соответствуют результату | Дальнейшая допустимость определяется QC; `fresh` не означает клинически valid |
| `stale` | Значимый вход/калибровка/метод изменён | Не использовать как текущее число; дать действие пересчёта |
| `unverified` | Старый импорт/схема не содержит достаточного provenance | Явная метка; не угадывать отсутствующее происхождение |
| `unavailable` | Не хватает требуемого исходного источника/входа | Историческая запись остаётся на диске, но не активируется как проверенная текущая |

QC `valid/review/invalid` остаётся отдельным измерением. Review не превращается автоматически в invalid; правила допуска review в отчёт сохраняют существующую явную маркировку. Invalid не входит в обычные агрегаты. Historical/stale числа показываются только явно как исторические, не как результат текущего расчёта.

**Матрица зависимостей и инвалидизации:**

| Изменение | Обязательная реакция |
|---|---|
| Контур/ED/ES/ROI или исходное измерение | Инвалидировать зависящие Simpson/strain/vessel/calculator results, не весь study без необходимости |
| Pixel/velocity/time calibration своего source | Инвалидировать только зависимые физические величины; не трогать независимый source |
| Рост/вес/BSA | Обновить BSA-зависимые индексы; не инвалидировать независимые raw volumes |
| Manual input/override/выбранный набор повторов | Пересчитать соответствующие калькуляторы/агрегаты с сохранением источника ввода |
| Algorithm/model/значимый config | Старый result остаётся историческим либо требует явного пересчёта; автоматический expensive reanalysis не обязателен |
| Неполный/несовместимый restore | Не активировать производное число, требующее отсутствующего входа |
| Late worker callback | Принять только при совпадении captured context/generation/input revisions; иначе discard без dirty/write |

**Отчёт:** одна application-проекция feeds UI/text/PDF. Единицы и округление определяются существующей семантикой. `null/нет данных`, не `0`/NaN как нормальное значение. В отчёте указывать метод, coverage/QC и ограничения, не только число.

**Identity:** использовать `measurement_sources`/WP4 descriptors. Для DICOM не обещать полной пиксельной идентичности по одному UID/семантическому fingerprint. Для не-DICOM перемещение допускает только однозначное сопоставление content hash, не имени файла; неоднозначность требует отказа/выбора, а не эвристического auto-restore.

### 5.3. Совместимость схемы

1. Сохранить поддержку существующих v1/v2 и Doppler repeat/semantics migration. Новый wire-version выбрать в implementation PR; не менять meaning старого поля незаметно.
2. Pure migration отделена от I/O. Валидировать fixtures старых версий, round-trip нового результата, bounded parse/references/units и запрет executable deserialization.
3. Старый derived result без достоверного происхождения становится `unverified`, а не автоматически `fresh`; совместимые первичные измерения сохраняются.
4. До замены старой записи обеспечить согласованную политику recovery/export/backup. Backup/quarantine — тоже PHI, учитываются в квоте и удалении.
5. Future/unsupported/corrupt records не перезаписываются тихо. Не делать массовую destructive migration при запуске.
6. Если один PR вводит только подмножество provenance, UI не обещает полную достоверность остальных типов. Неподдержанный scope явно обозначается.

### 5.4. QH-1c: завершить safety-остатки WP4

- Authoritative delete всех поддержанных contour/measurement types, включая последний объект и accepted contour refinement; не трактовать пустой refresh как удаление.
- Barriers/generation для queued save, reset/delete-all, import, restore и поздних callbacks. Save/delete acknowledgement принадлежит своей operation/revision, не активной вкладке в момент ответа.
- Partial restore сохраняет недоступную часть полного record при следующем save активной проекции.
- Manager показывает даты/count/status; corrupt/unsupported handling и retry/export доступны без ложного успеха.
- Import preview до изменения RAM/диска: категории, совместимость, недоступные источники, действие replace/cancel. Replace сохраняет и удаления; no silent merge.
- Hash-remap перемещённого не-DICOM — отдельный шаг с identity checks, не снятие проверок существующего importer.
- Fault injection write/fsync/replace/quota/permission/conflict; failure сохраняет dirty RAM и возможность Retry/export. Не обещать export структурно невалидного snapshot.
- Сохранить текущие профили, atomic store, debounce/flush и retention. Удаление JSON не обещает secure erase внешних копий.

### 5.5. QH-1d: persistent manual calculator inputs

- Persist только allowlisted input IDs, canonical units, finite values/допустимые bounds, origin/manual override, revision и реально существующие measurement references.
- Study-scoped данные; per-source reference только там, где источник действительно есть. Свободному ручному вводу не придумывать SOP/frame.
- Сохранять первичный ввод, не текст виджета/целый widget state и не вычисленный display-cache.
- Restore до расчёта; единая приоритетность measured/manual override/derived, совпадающая с UI. Изменение измеренного кандидата не скрывает активный ручной override.
- Явное reset/delete override инвалидирует зависимые результаты и не затрагивает независимые измерения. Old records без inputs загружаются без выдуманных defaults.
- Добавление поля в application не добавляет его автоматически в disk allowlist. Обновить schema, inventory и HELP.

### 5.6. QH-1e: численная и same-frame STE-верификация

**Сразу, без внешних данных:**

- Formula/units/rounding cases для supported measurements и калькуляторов; проверить отрицательные/нулевые/неполные входы и разные калибровки.
- Simpson на аналитических синтетических фигурах; Doppler sign/time/velocity normalization; repeat window и число использованных измерений; BSA provenance.
- Пример физического эталона: `PGmax = 4v²`, `v = 2.8 м/с` → `31.36 мм рт. ст.` до существующего display rounding. Это один тест семантики, не общая клиническая валидация.
- UI/text/PDF parity и сохранение/restore при неизменных допустимых входах.

**STE отдельным data-dependent gate:**

1. Использовать существующие фантом/verification и KPI STE-plan §3.7, не переписывать пороги после получения результатов.
2. Получить gold ED/landmarks и соответствующие vendor measurements на одинаковых кадрах/циклах/видах; первый срез — 2–3 доступных клипа. Он проверяет workflow, но не доказывает vendor equivalence.
3. Manifest: обезличенный case ID, view, source/frame/cycle, frame rate, contour origin, definition/layer, algorithm/model/config, expected numbers и заранее выбранные tolerances.
4. Для расширенной оценки протокол фиксирует число независимых пациентов/клипов, inclusion/exclusion, QC-fail rate, bias/LoA и повторяемость. Существующие цели ≥20 клипов, bias ≤1.5 п.п., LoA ≤±3 п.п., r ≥0.9 — инженерные цели плана, не автоматическое клиническое разрешение; корреляция одна не доказывает согласие.
5. Невалидные кейсы остаются в отчёте QC/coverage; нельзя улучшать метрику, скрывая трудные строки или ослабляя gates.
6. Без gold/согласованных определений gate **BLOCKED**. Анализ результата с неподтверждённым эталоном не маркируется «вендорский уровень».
7. Оригиналы с впаянными PHI не коммитить и не публиковать в CI artifacts. Использовать действующую private/external fixture policy; права на derivative fixtures проверять отдельно.

**Gate G1 — data safety:** S-01…S-07/S-10/S-11 проходят для согласованного scope; старые snapshots не теряют первичные данные; new/partial/legacy results имеют честный статус. STE-вендорский gate **G1-STE** отдельный: его отсутствие не мешает исправлению persistence, но блокирует заявление о подтверждённом паритете STE.

## 6. QH-2 — Тесты реальной защиты, CI policy и transport

### 6.1. QH-2a: реальное выполнение quality/security-gates

| Набор | PR | Nightly / pre-release | Что является доказательством |
|---|---|---|---|
| Unit + formulas/codec/repository/critical persistence | Required | Полный повтор для release candidate | JUnit/exit code, выполненные test IDs, отсутствие safety-xfail |
| Fast synthetic security contracts | Required | Полный `tests/security` после классификации prerequisites | Production entry point + assertion воздействия/запрета |
| Critical GUI acceptance | Required на Linux/Xvfb | Native targeted smoke Windows/macOS и Full/Presenter | Реальный Qt event loop, не Qt stub вместо native |
| DICOMweb/DIMSE integration | Controlled local service subset | Выделенный Orthanc/PACS стенд с TLS/CA/timeout/legacy cases | Реальный протокол; external demo не единственное основание PASS |
| CodeQL/dependency policy | Проверяемый blocking policy для опасных новых findings | Full scan выбранного release состава | Результат policy, не просто успешное завершение analyzer |
| Performance/lifecycle | Существующий cine SLO сохраняет свой gate; targeted regressions — по scope PR | Stress/profile на reference runner | Замеры и заранее утверждённые budgets |

**Условия исполнения:**

- Разделить fast deterministic contracts и наборы с live PACS/model/data prerequisites. Нельзя сделать весь security набор required, получив 100% skip.
- Каждый обязательный сценарий представлен конкретным test ID. Job проверяет collection/run evidence; отсутствие required IDs, полностью skipped набор или collection error — FAIL. Допустимые skips перечислены с причиной, но не закрывают обязательный сценарий.
- Маркеры и `ECHO_*` flags проверять по фактическим hooks каждого набора; сами имена переменных в pyproject не включают тест автоматически.
- Fake/mocked transport допустим для детерминированного unit-теста политики; отдельный TLS/service integration подтверждает поведение реального клиента. Не мокать проверяемый production policy/repository/codec/formatter.
- Acceptance fixtures с mock ONNX не являются проверкой точности модели. Разделять wiring, algorithm и packaged-system evidence.
- Для критических защит локально выполнить controlled mutation/negative check: отключён enforcement → тест падает; возвращён старый RAM reader → тест падает; убрана invalidation → тест падает. Опасные мутации не публиковать в рабочем коде.
- Не скрывать exit code через `|| true`/`continue-on-error` в required jobs. Advisory benchmark отчёт не переименовывать в blocking gate, пока не стабилизированы runner/budgets; действующий cine gate не ослаблять.

**Toolchain:** использовать существующий `uv.lock` как source of truth, locked sync/export для выбранных extras и pin tools/actions. Core/dev/Presenter/build составы перечислить явно. Lock-refresh — отдельный reviewable diff. Сохранить безопасный Qt upper bound до воспроизведённого upstream fix. Проверить заявленную поддержку Python 3.10/3.11: минимум compatibility job на 3.10, reference CI/release на 3.11; сокращение диапазона — отдельное явное решение, не скрытое следствие lock.

**SAST/SCA policy:**

- Сохранить CodeQL `security-extended` и dependency-review. Проверить required checks/rulesets с владельцем репозитория.
- Добавление Bandit — дополнительный слой с baseline и review исключений; Safety или другой SCA выбирается по пригодности к locked extras/SBOM, не по названию.
- Блокировать новые high-confidence/high-severity findings по утверждённой policy. Для зависимости учитывать достижимость, severity, исправленную версию и экспозицию; documented waiver имеет owner/reason/expiry.
- Existing dangerous findings получают issue/срок, не бесконечный baseline. Сканировать фактический release состав, а не только dev installation.
- Проверить, что CodeQL finding действительно останавливает разрешённый merge/release путь: analyzer может завершиться успешно с alerts. Использовать доступную code-scanning protection либо отдельный проверяемый policy-result check.
- Администратор подтверждает настройки evidence-записью. Без доступа статус policy gate **BLOCKED**, даже если YAML написан.

### 6.2. QH-2b: единая транспортная политика

Предлагается один pure evaluator политики и adapters в production clients/settings UI. Точное API задаётся implementation PR; UI-warning без enforcement в клиенте недостаточен.

**Область:** все DICOMweb/Orthanc запросы, WADO/QIDO/STOW overrides, thumbnails/history/ping с credentials, redirects и DIMSE associations. Проверка до передачи credentials/PHI, не только при сохранении профиля.

| Ситуация | Default / обязательное поведение |
|---|---|
| HTTPS remote + verify=True | Разрешено при успешной проверке peer; custom CA поддержан |
| HTTP literal loopback / `localhost` | Допускается для локального профиля; не распространяется автоматически на remote redirect |
| HTTP remote, включая RFC1918/private LAN | Block до явного insecure exception для конкретного endpoint; private network не считается доказательством доверия |
| HTTPS remote + verify=False | Только отдельное явное insecure exception с постоянной видимой меткой; рекомендовать CA |
| Remote DIMSE без TLS | Такой же явный opt-in для legacy transport; не включать TLS слепо на существующем PACS |
| TLS/certificate failure | Ошибка без silent downgrade/auto verify=False; пользователь исправляет CA/peer либо явно меняет policy |
| Изменение endpoint/transport/security setting | Старое согласие не переносится автоматически; повторная проверка/подтверждение |
| Redirect / alternative endpoint | Проверить effective destination; no HTTPS→HTTP fallback; не отправлять auth/custom secret headers на другую authority без отдельного разрешённого scope |

**Детали:**

- Loopback проверять parsed host/IP, а не `startswith`/substring/suffix; `localhost.attacker.example` и похожие имена не исключения. Arbitrary DNS-name, случайно разрешённый в loopback, не получает постоянное доверие автоматически.
- Scope согласия: profile/authority/port/transport + существенные verification settings; не глобальная настройка «HTTP разрешён всем».
- Предупреждение RU/EN до сети: возможна передача медицинских данных и credentials; действия «Настроить TLS/CA», «Отмена», «Явно разрешить для этого сервера».
- Insecure state видим в профиле и перед подключением; логируется decision code/opaque profile ID, не URL с userinfo, query/UID, Authorization, password или PHI.
- Reject malformed/unsupported scheme и embedded URL credentials; не заменять неправильный адрес эвристически на рабочий.
- Не отключать cert verification ради самоподписанного PACS: основной путь — доверенный CA bundle. TLS minimum/hostname verification задаются общей security policy с совместимостным тестом.
- Legacy HTTP/clear DIMSE остаётся доступным после явного opt-in. Не переписывать URL/port автоматически и не считать VPN/private LAN автоматическим bypass.

### 6.3. Миграция и tests

- Существующие профили сохраняются, credentials не теряются. При загрузке старого remote insecure-профиля состояние `needs_confirmation`; первый сетевой запрос блокируется до решения пользователя. Loopback профиль продолжает работать.
- Повторное подтверждение при изменении scope; Presenter использует portable settings, не host fallback. Migration version не содержит plaintext secrets.
- Unit tests pure evaluator: parsed loopback/IPv6/look-alike, HTTP/HTTPS, invalid URL, changed scope, overrides, downgrade/cross-authority redirect.
- Production-client tests: отклонённая операция даёт **0 сетевых запросов/associations**; UI warning приходит из реального решения, не `warnings.warn()` теста.
- TLS service tests: approved CA работает с verify=True; неверный CA/hostname/expired certificate отклоняются; fallback отсутствует; auth не уходит на запрещённый redirect.
- DIMSE: TLS-enabled fixture и legacy fixture с явным opt-in; incompatible TLS даёт видимую ошибку без downgrade.
- Таймаут/отмена не оставляют бесконечный worker и не превращаются в «пустое успешное исследование».

**Gate G2:** required security contracts выполняются и ломаются при отключении защиты; миграция legacy-профилей безопасна/объяснима; protected workflow проверен администратором; отсутствие живого TLS/PACS evidence отмечено отдельно и не выдаётся за integration PASS.

## 7. QH-3 — ViewerWidget через композицию

### 7.1. Целевая граница

```text
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

**ViewerContext:** study identity, source identity, frame, pane/tab/session token и generation, необходимые view transforms/калибровка. Persistent identity не зависит от ephemeral pane/tab ID. Context не является вторым store: авторитетные измерения принадлежат существующей application session.

**Границы:**

| Компонент (предлагаемый) | Владеет | Не должен владеть |
|---|---|---|
| `ToolInteractionController` | Active tool, draft gesture, commit/cancel, routing | Disk/network I/O, глобальная identity через current MainWindow |
| `ContourEditingController` | Handles/selection/draft edit; команды accepted change/delete | Отдельная несогласованная копия study measurements |
| `CalibrationController` | Validation/commit per-source calibration и уведомление об invalidation | Калибровка «для последнего viewer» |
| `ResultsOverlayController` | Layout/visibility/position и render projection | Пересчёт клинических результатов из текста UI |
| `MagnifierController` | Zoom/pan/crop и transient state | Source identity/persistence/calculator inputs |
| Worker adapters | Lifecycle конкретной задачи, result delivery token | Mutating Qt/UI из фонового потока |

Имена/папки — проектные, не утверждение о наличии классов. Pure math не получает QWidget; QObject используется там, где требуется Qt lifecycle. Контроллеры получают узкие зависимости, не весь MainWindow/ViewerWidget как service locator.

### 7.2. Последовательность выделения

1. Context/commands/ownership contract и characterization harness; сохранить внешний API/signals фасада.
2. Низкорисковые overlay/magnifier-компоненты как пилот.
3. Tools/gesture commit/cancel, затем contour editing.
4. Per-source calibration и worker adapters с revision/generation checks.
5. Удалить временные delegate bridges и legacy state после перевода callers/tests, не поддерживать две авторитетные копии.

Каждый slice отдельный PR. Не переносить файл целиком «ради метрики», не менять формулы/видимый UX/shortcuts в том же PR. Существующий keyboard registry и N-08 coordinators переиспользуются; tool gates Multiview сохраняются.

### 7.3. Lifecycle и производительность

- Owner-scoped QObject/connection/task inventory; явный idempotent `dispose/shutdown`.
- При смене context инвалидировать callbacks/черновики; при закрытии остановить timers/playback, отменить/дождаться задач, завершить необходимые persistence barriers, затем отсоединить сигналы/разрушить UI. Generation check не заменяет освобождение ресурсов.
- Никакого mutating GUI из worker; никаких callbacks, использующих уничтоженный receiver; ожидаемый поздний callback обрабатывается контролируемо.
- PR stress: 50 циклов после warm-up; nightly/pre-release: 500 циклов open/switch/close на reference runner. Сценарии: tabs, dialogs, strain window, comparison, завершение/отмена worker.
- После teardown живых closed-owner controllers/widgets/tasks — 0; число сигналов/таймеров не накапливается. Допустимые shared resources и bounded caches перечислены.
- RSS может не вернуться к исходному из-за allocator/cache. Бюджет и измерение trend после warm-up фиксируются по baseline до рефакторинга; отсутствие неограниченного роста проверяется по повторяемому сценарию, а не требованием «RSS всегда одинаковый».
- Профилировать NumPy/OpenCV/ORT/native части до вывода «Python тормозит». Не лечить production lifecycle периодическим `gc.collect()` без установленной причины.
- Сохранить cine/playback SLO; ухудшение latency/RSS вне утверждённого budget требует исправления или явного review, а не удаления benchmark.

**Gate G3:** behavior parity и S-02/S-05/S-11; native targeted smoke и lifecycle evidence на поддержанных платформах; нет нового shared state/callback resurrection. LOC уменьшение — побочный эффект, не критерий приёмки.

## 8. QH-4 — Адресный аудит ошибок и границ domain

### 8.1. QH-4a: исключения по последствиям

Audit register: место, operation, ожидаемые exception types, последствия, текущая/целевая реакция, тест, owner/issue. Порядок — save/load/identity/calibration/report → worker boundaries → optional UI/cleanup.

| Категория | Политика |
|---|---|
| Клиническое действие / обязательный I/O | Typed outcome/error code; пользователь видит отказ/partial state; no silent success; RAM/retry/export сохраняются где допустимо |
| Неожиданная ошибка boundary worker | Catch-all допустим на границе, с безопасной диагностикой и доставкой failure в UI |
| Ожидаемый cancellation/deleted receiver/cleanup | Узкий handler; quiet/debug допустим с пояснением и lifecycle-тестом |
| Необязательная функция | Контролируемый fallback, отличимый от normal success если влияет на доступность данных |
| Programming error в обязательном коде | Не превращать в `[]/None/0` без признака failure; воспроизведение и исправление |

- Не ставить `logger.exception()` во все 230 обработчиков: traceback/exception message может содержать PHI/paths/credentials.
- Safe logging API/allowlist: operation/code/type/revision/count/duration, opaque correlation ID; подробности только после sanitizer. Сырой traceback не считается обезличенным.
- PHI sentinel-tests для names/IDs/full UIDs, paths, Authorization/password, labels/payload и diagnostic ZIP. Crash dumps отдельно маркируются как потенциально чувствительные, не автоматически «чистые».
- Полезный error сохраняется как статус/результат операции; лог не заменяет сообщение пользователю.
- Для оправданного `pass` фиксировать rationale и конкретный exception; не требовать нулевого количества `pass` как KPI.

### 8.2. QH-4b: внутренние зависимости

1. Снять AST-baseline всех `domain → infrastructure` и application I/O dependencies; new violations запрещены с первого architecture-check PR. Учитывать absolute/relative/type-only imports; dynamic imports проверяются review, AST не обещает полного анализа.
2. `cine_segment_diagnostics`/`bench_lvef`: чтение DICOM/video/ONNX orchestration в application/developer tools; pure calculations остаются внутри.
3. `segment_roi`: pure image/tick/pixel helpers перенести в независимое алгоритмическое место; DICOM parsing/reader — adapter. Не создавать infrastructure port для простой pure function.
4. Domain formatter/i18n/profiler dependencies: domain возвращает structured values/reason codes; перевод/рендер/инструментация выполняются снаружи. Compatibility API переводить постепенно без фасада, который продолжает импортировать infrastructure в domain.
5. Порты определить для реальных I/O границ — repository, source reader, inference execution, network. Infrastructure реализует их; composition root связывает зависимости.
6. Presentation может использовать внешние UI/config/i18n adapters, если не обходит application safety-контракт. Не делать запрет всех presentation→infrastructure imports по числу файлов.
7. После устранения baseline ratchet довести direct domain→infrastructure до **0** и закрепить check. Pure domain tests не требуют QApplication/диска/сети, кроме явно вынесенных адаптерных наборов.

**Gate G4:** критические операции имеют tested typed failures/fallback; новые прямые нарушения блокируются; финальный domain boundary чист. Отсутствие raw PHI в согласованных logging tests подтверждено; это не обещание автоматической анонимизации всех legacy logs.

## 9. QH-5 — Сборка, доказательства и OS-подпись

### 9.1. QH-5a: воспроизводимый и проверяемый релиз

- Один locked dependency policy для CI/build/release/Presenter; явные build tools и packaged extras. Не скрывать failed installation через набор альтернативных floating `pip install`.
- Record: source commit/tag/version, lock/model hashes, Python/Qt/NumPy/ORT, platform/architecture, Full/Presenter mode, workflow/run, artifact hashes.
- Build smoke проверяет **упакованный артефакт**, а не только import из checkout: first launch, synthetic DICOM/cine, measurement/save/restart/restore, text/PDF export, settings/privacy boundaries.
- Матрица поддержанных пакетов/архитектур фиксируется в release checklist; не объявлять пакет выпущенным по YAML. Presenter writable/read-only portable smoke и USB P1–P7 остаются явным отдельным acceptance.
- `verify_only` / equivalent staging: собрать/проверить без публикации. Tag == package version; не переписывать старые теги или v0.3.2 assets для внесения новой функциональности.
- SHA256SUMS, versioned asset names, manifests и SBOM согласованы с **финальными опубликованными байтами**. SBOM привязан к конкретному binary hash и фактическому packaged составу.
- Verification на чистом стенде: checksum + provenance attestation; для signed artifacts ещё native signature. `latest.json` указывает только проверенные существующие assets и корректные profile/platform/version/hash.
- Перед publish проверять комплектность ожидаемой матрицы. Partial release только по явно согласованной policy с видимыми ограничениями, не через успешный job, которому нечего публиковать.
- Артефакты/large fixtures/diagnostic dumps не коммитить; приватные данные не загружать в публичные workflow artifacts. Retention bounded и задокументирован.

### 9.2. QH-5b: OS code signing

**Организационные предусловия:** владелец/юридическая eligibility, бюджет/провайдер, доступ к signing/notarization, secure key custody и approval process. Стоимость/доступность провайдера уточнять перед выбором; план не полагается на устаревшие цены.

- Windows: Authenticode для финального executable payload и installer/portable/Presenter assets; timestamp; verification `signtool verify`/OS trust на clean machine. Не обещать немедленное отсутствие SmartScreen.
- macOS: Developer ID, hardened runtime/нужные entitlements, notarization и stapling применимых artifacts; `codesign`/`spctl`/notary verification и launch на clean machine. Ad-hoc signature не считается этим gate.
- Linux: checksum/provenance и при выбранной policy detached manifest/package/repository signature; не представлять её как аналог Gatekeeper для standalone файла.
- Build → sign/notarize/package в правильном порядке → final hashes/SBOM binding/attestations → verify → publish. Изменение байтов после хеширования требует нового manifest/attestation.
- Подписывать только разрешённый tested commit/artifact из доверенного workflow; approval/environment protection, least privilege, no fork PR code with signing secrets. Credentials/private keys не попадают в repository, docs, logs или чат.
- Пока external signing prerequisite не выполнен, статус **BLOCKED**. Допустима явно unsigned developer/beta публикация по текущей policy; требование signed distribution не считается закрытым.

**Gate G5a:** locked verified artifact + package smoke + согласованные provenance/manifests. **Gate G5b:** native signatures реально проверены на опубликованных assets; не закрывается одним Sigstore attestation. Формальная клиническая/регуляторная приёмка остаётся вне этого документа.

## 10. План PR и зависимости

S/M/L — относительный размер и риск, не обещание срока; L разбивается на несколько independently testable slices. Waiting for gold/CA/native stand/certificates в оценку кода не входит.

| Порядок / пакет | Состав | Размер | Зависимости / выход |
|---|---|---|---|
| **0 — QH-0** | Baseline, reproductions, characterization, traceability, lifecycle harness | M | G0; без massive refactor |
| **1 — QH-1a.1** | Saved-record application API + исправление StartPage/manager reader и failure state | M | QH-0; реальный restart test |
| **2 — QH-2a.1** *(параллельно)* | Locked CI, collection evidence, fast security/critical acceptance jobs | M | QH-0; non-vacuous checks |
| **3 — QH-1b.1** | Provenance/freshness DTO + dependency map + schema/migration tests | M | QH-0; согласованный data contract |
| **4 — QH-2b** *(параллельно)* | Transport evaluator → clients → settings/migration → TLS/DIMSE integration | L, ≥2 slices | QH-2a.1; G2 transport evidence |
| **5 — QH-1b.2** | Invalidation per-result + единая UI/text/PDF projection | L, по семействам результатов | QH-1b.1; formulas/parity/negative tests |
| **6 — QH-1a.2** | Э10 через реальный tab lifecycle, ownership cache, badges/mirror | M–L | QH-0/context contract; не включает pane tools |
| **7 — QH-1c** | Delete/barriers/partial restore → manager/import preview → hash-remap | L, ≥2 slices | QH-1b.1; WP4 safety acceptance |
| **8 — QH-1d** | Manual inputs allowlist/schema/restore/reset/provenance | M | QH-1b + QH-1c foundations; G1 |
| **D — QH-1e** *(отдельный параллельный data track)* | Formulas сейчас; STE gold/manifest/same-frame report при наличии данных | M + ожидание данных | Не блокирует fixes; отдельный G1-STE |
| **9 — QH-3.1** | ViewerContext/commands + overlay/magnifier pilot | M | G0 + согласованный QH-1 contract; сохраняет behavior |
| **10 — QH-3.2…** | Tools → contours → calibration/workers; cleanup bridges | M на slice | QH-3.1 + relevant G1 tests; G3 |
| **E — QH-4a** *(с первого исправления)* | Error register, typed outcomes, sanitized diagnostics | S–M на операцию | Идёт вместе с QH-1/2/3, не ждёт их конца |
| **11 — QH-4b** | Boundary ratchet → orchestration → helpers → formatters | M на slice | G0; финальный G4 |
| **12 — QH-2a.2 / QH-5a** | Policy/rulesets подтверждение, full release matrix, package verification | M–L | G1 + готовые tests/transport QH-2; завершает G2, затем G5a |
| **O — QH-5b prerequisite** *(сразу)* | Провайдер/владелец/approval/key custody | External | Не зависит от refactor; не выдаётся за кодовую готовность |
| **13 — QH-5b** | Signing/notarization + final verification/publish safeguards | M + external | G5a + разрешённый доступ; G5b |

**Ближайшие три PR:** QH-0 → QH-1a.1; параллельно QH-2a.1. Затем provenance/freshness и transport. Не начинать с тотальной перестройки ViewerWidget или включения всех сканеров в blocking-режим без baseline.

## 11. Минимальная матрица приёмки

| ID | Сценарий | Ожидаемое доказательство | Gate |
|---|---|---|---|
| A-01 | Настоящий save → рестарт → StartPage; corrupt сосед | Valid summary виден, corrupt/failure различимы; RAM reader regression ловится | G1 |
| A-02 | A/B с разными Study/SOP/spacing, переключение вкладок | Measurements/calibration/manual overrides/worker results не смешиваются | G1/G3 |
| A-03 | Изменение contour/calibration/input после расчёта | Stale до пересчёта; UI/text/PDF не выдают старое число как fresh | G1 |
| A-04 | Новая правка во время save; failed save → Retry | Старый ack не очищает новую dirty revision; последняя подтверждённая версия читается | G1 |
| A-05 | Delete последнего объекта/reset при queued save/late callback | Нет resurrection в RAM/диске после рестарта | G1/G3 |
| A-06 | Partial restore/save; source mismatch; future schema | Недоступная часть сохранена, incompatible не активирована/не overwritten | G1 |
| A-07 | Old v1/v2 → new schema; manual inputs round-trip | Первичные данные/единицы/repeats сохранены, unknown provenance честно unverified | G1 |
| A-08 | Э10 A из tab1 + B из tab2; закрытие owner-tab | Пара/badges/mirror/lifetime корректны; tool gates и sync policy сохранены | G1/G3 |
| A-09 | Remote HTTP / verify=False / DIMSE clear без согласия | 0 сетевых действий до решения; исключение scoped и видимо | G2 |
| A-10 | Custom CA, invalid cert/hostname, downgrade/cross-authority redirect | Проверка включена; плохой peer отклонён; credentials не утекли | G2 |
| A-11 | Presenter off, read-only portable, history capability | Нет скрытой записи/restore/host fallback; понятная деградация | G1/G2/G5a |
| A-12 | PHI sentinels в ошибках/log/diagnostic ZIP | Allowlisted diagnostics без sentinel payload/secrets/полных patient paths | G4 |
| A-13 | Controlled mutation + CI collection evidence | Required tests падают при отключении защиты; missing/all-skipped не PASS | G2 |
| A-14 | 50/500 lifecycle cycles + late callbacks | Closed-owner resources освобождены, нет неограниченного тренда/новой SLO-регрессии | G3 |
| A-15 | Synthetic formulas и STE phantom; same-frame gold отдельно | Допуски frozen; QC-fails не спрятаны; внешние данные/статистика описаны | G1/G1-STE |
| A-16 | Чистая машина, packaged Full/Presenter, save/restart/export | Работает artifact, а не checkout; version/profile/platform подтверждены | G5a |
| A-17 | Final assets checksums/SBOM/attestations/signatures | Ссылки/хеши относятся к опубликованным байтам; native signatures валидны | G5a/G5b |

Каждая строка реализуется несколькими тестами при необходимости. JUnit, manifest окружения, sanitized diagnostics и результаты reference-run сохраняются вне Git как bounded CI artifacts; краткое заключение/commit/test IDs — в `docs/reviews/`. Public evidence не содержит clinical originals или PHI.

## 12. Правила допуска и общая Definition of Done

### PR gate

- Точный scope и затронутые S-инварианты; воспроизводящий тест до исправления; нет смешивания refactor + algorithm change.
- Required jobs действительно прошли; перечислены executed/skipped/xfail и причины. Сбой среды не считается PASS продукта.
- Scheme/semantics/API changes совместимы или имеют явную migration/rollback policy. После new schema нельзя молча откатывать binary, не понимающий её.
- Новый пользовательский текст RU/EN, parity tests; behavior/limitations в HELP. SECURITY/inventory обновляются для transport/storage/logging changes.
- Нет large/generated/private artifacts в patch; `git diff --check` и проектные lint/format checks проходят.
- Ownership/cancellation/disposal описаны и тестируемы. Новый компонент не получает весь MainWindow как зависимость.

### Release gate

- Нет открытых воспроизведённых P0 про wrong-source, stale-as-fresh, ложный saved, resurrection или silent unsafe transport в заявленном scope.
- G1/G2 и relevant G3/G4 evidence относятся к release candidate; G5a проверяет его packaged artifacts. Нельзя подменять проверку другой версии или checkout.
- G1-STE отдельно определяет, какие STE-validation statements допустимы; недоступные данные не превращаются в «эквивалентность».
- Full/Presenter paths/defaults и native Windows/macOS/Linux scope документированы. Прошлые PASS повторяются только для затронутых контрактов; неизвестная область остаётся явным gap.
- Signed-channel claim требует G5b; unsigned build остаётся явно unsigned. Ни signing, ни QH-gates не означают регуляторного разрешения.

## 13. Риски, внешние блокеры и предлагаемые defaults

| Риск / вопрос | Предлагаемое правило |
|---|---|
| Нет gold/согласованного vendor definition | G1-STE BLOCKED; formulas/phantom/provenance и остальные fixes продолжаются |
| Доступа к rulesets нет | Администратор проверяет policy; YAML alone не закрывает G2 governance |
| Клиника использует legacy HTTP/DIMSE | Явное per-endpoint исключение с предупреждением; URL/TLS не переписываются автоматически |
| Legacy record не содержит lineage | Сохранить первичные измерения, derived пометить unverified; не угадывать происхождение |
| Нужна новая schema | Versioned additive/migrated change с tests и recovery; destructive bulk rewrite запрещён |
| Qt upstream regression | Сохранить проверенный upper bound; обновлять после native reproduction и lifecycle gates |
| Отсутствует signing provider/бюджет | G5b BLOCKED; не блокировать исправление P0 и verified unsigned developer builds |
| Слишком большой PR | Разделять по результату/контроллеру/границе; временный facade с removal criterion, не второй store |
| Clinical/native fixtures недоступны агенту | Synthetic automated evidence отдельно; owner-run evidence с commit/окружением, без обещания прогона |
| RSS растёт в длинном suite | Измерить owner lifecycle в приложении отдельно; не объявлять production leak по числу созданных тестом виджетов |

Предлагаемые defaults этого draft: сохранить текущие профили/retention; блокировать remote insecure до scoped согласия; legacy derived — unverified; reuse existing stores/registry/coordinators; минимальный compatibility job на Python 3.10 и reference toolchain на 3.11. Изменения этих решений фиксируются до соответствующего implementation PR.

### 13.1. Ответственные за решения и evidence

Имена назначаются владельцем проекта до соответствующего этапа; draft не предполагает, что согласование уже получено.

| Роль | Ответственность |
|---|---|
| Product/клинический рецензент | Определения, units/rounding, допустимость QC review, allowlist ручных inputs и заранее утверждённые допуски численной сверки |
| Разработчик/технический reviewer | Identity/revision/generation, schema/migration, architecture/lifecycle, тесты и воспроизводимость |
| Владелец данных/эталонов | Gold/definitions/manifest, независимость выборки, разрешения на использование и отсутствие PHI в public evidence |
| Администратор репозитория/CI | Реальная обязательность policy-checks, rulesets, signing environment protection, управление waivers |
| Release/signing maintainer | Toolchain/package matrix, clean-machine evidence, final hashes/SBOM/attestations и native signing verification |

Неопределённый owner/внешний допуск фиксируется как blocker соответствующего gate, а не решается угадыванием в коде. Клинический reviewer в этом плане проверяет определения и инженерные критерии; это не замена регуляторной оценки.

## 14. Checklist исполнения

- [ ] QH-0: актуальный baseline, reproductions, traceability и lifecycle budgets.
- [ ] QH-1a: saved-record reader исправлен; Э10 проверен на tab lifecycle.
- [ ] QH-1b: provenance/freshness и schema compatibility; invalidation всех заявленных families.
- [ ] QH-1c: authoritative delete/barriers/partial restore/import preview/status/remap.
- [ ] QH-1d: manual calculator inputs persist/restore/reset с происхождением.
- [ ] QH-1e: formulas/phantom; G1-STE имеет отдельный доказанный статус и data protocol.
- [ ] QH-2a: non-vacuous required tests, locked CI, security policy/rulesets подтверждены.
- [ ] QH-2b: production transport enforcement, legacy migration, TLS/DIMSE evidence.
- [ ] QH-3: component slices, behavior parity, lifecycle/native smoke.
- [ ] QH-4a: критические failures обработаны адресно, sanitized diagnostics проверены.
- [ ] QH-4b: boundary ratchet, финальный zero direct domain→infrastructure.
- [ ] QH-5a: locked package builds, clean-machine smoke, final manifests/provenance.
- [ ] QH-5b: OS-подпись и verification либо честный BLOCKED/unsigned status.

**Отчёт о готовности:** по gate/work package, а не по доле строк или числу созданных классов. Для каждого — commit, evidence, PASS/FAIL/BLOCKED, remaining limitations и ссылка на issue. Все пункты выше остаются незакрытыми до выполнения; создание этой спеки не является реализацией или тестовым прогоном.

## 15. Execution ledger — срез 2026-10-14 (не меняет исходную спецификацию)

Исходный draft/checklist §14 сохранён как scope. Статусы ниже — по конкретному срезу,
а не blanket PASS всего gate. База этой сессии `3d23a8f` (после #159), QH-1e commit `9d0b420`.
Полный остаток/назначение владельцев: [#160](https://github.com/areatu/SonoForge/issues/160).
CI текущего patch подтверждается checks PR, не наличием YAML.

| Work package | Текущая область evidence / статус | Остаток |
|---|---|---|
| QH-0 / QH-1a | Ранее внесены baseline, saved-record reader и comparison ownership slices; см. `docs/reviews/2026-10-13-*` | Старые traceability IDs/claims — исторический baseline, не новая acceptance всех сценариев |
| QH-1b.1 | В базе существуют `result_provenance.py`, dependency map, codec/schema v3 и `test_result_provenance.py` | DTO/schema groundwork не завершает production invalidation/QH-1b.2 и единую freshness projection |
| **QH-1c** | Барьеры save/delete/reset/import, preview→explicit full replacement (digest/source/category checks), bounded legacy list и write/fsync/replace/quota/permission/conflict evidence — [slice](../../reviews/2026-10-14-qh-1c-1d-persistence-slices-ru.md) | Hash-remap moved non-DICOM, directory-fsync/native fault harness и полный WP4/G1 не закрыты; не объявлять весь пакет закрытым |
| **QH-1d** | Wire v4 explicit allowlist ручных primary calculator inputs, bounds/finite/origin/revision, restore до calculation, clear/reset/import semantics — [slice](../../reviews/2026-10-14-qh-1c-1d-persistence-slices-ru.md) | Persisted derived calculator results/full result-provenance UI и clinical acceptance не входят; old records честно пусты, без invented override |
| **QH-1e formulas** | **Реализован synthetic slice**: 111 новых cases; required manifest 29 записей / 276 executed PASS локально, 0 skip/xfail; [report](../../reviews/2026-10-14-qh-1e-formulas-ru.md) | Native/clinical validation не выполнялась; **G1-STE BLOCKED** до same-frame gold/definitions/manifest; полный G1 не PASS |
| QH-2a.1 / QH-2b.1 | Locked CI/non-vacuous security/acceptance gates и pure transport evaluator уже есть; formulas и diagnostic sentinels добавлены в required manifests | Rulesets/policy admin confirmation остаётся за QH-2a.2 |
| **QH-2b.2** | **Реализован**: enforcement транспортной политики в `OrthancDicomWebClient`, `PynetdimseClient`, `DicomQueryService`, `DicomRetrieveService`, `OrthancDownloadWorker`, редиректах (`evaluate_redirect` + очистка секретных заголовков), миграции профилей (`needs_confirmation`, scoped `InsecureException`), UI предупреждениях RU/EN и сервисных сокетных фикстурах HTTPS TLS / DIMSE TLS (`362 passed` в `tests/security/`, `17/17` записей манифеста); [report](../../reviews/2026-10-15-qh-2b2-transport-enforcement-ru.md) | Локальные TLS/DIMSE фикстуры подтверждают сервисный контур в CI; проверка против внешнего госпитального PACS/TLS стенда не эмулируется локальными фикстурами и отмечается отдельно |
| QH-3 | Coordinator groundwork существует | Последующие component/native/lifecycle slices не входят в эту пару коммитов |
| **QH-4a register** | **Register выполнен**, ER-10 structured-filter fix + 13 новых required sentinel/ZIP tests; [register](../../reviews/2026-10-14-qh-4a-error-register-ru.md) | **PARTIAL G4**: OPEN operation-scoped handlers, producer allowlist и raw crash/log privacy; owner names ещё не назначены (#160) |
| QH-4b | Требования boundary ratchet сохранены | Финальный zero direct domain→infrastructure не достигнут и не заявлен |
| QH-5a / QH-5b | Нет нового packaged-release evidence в этой сессии | Locked full package matrix/clean machine отдельно; signing prerequisites → **BLOCKED/unsigned**, не PASS |

Закрытые хвосты этого среза: finite input failures BSA/Teichholz, lazy QtGui для PDF font access,
исчезновение/skip numerical tests как CI failure, quoted structured PHI/credential leakage в support ZIP,
честные diagnostics limitations в SECURITY/inventory/HELP RU+EN. Большие оставшиеся work packages
не смешаны с formulas/register, внешние data/native/admin/signing prerequisites не подменены синтетикой.
