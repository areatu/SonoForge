# QH-план → GitHub Projects: трекер и синхронизация (2026-10-14)

> **Снимок на 2026-10-14.** Документ фиксирует состояние на эту дату и не обновляется вслед за кодом: актуальное состояние — в коде, `README.md`, HELP и открытых issues.

**Назначение.** Вывести спеку QH (`docs/superpowers/specs/2026-10-13-quality-safety-hardening-spec-plan-ru.md`)
в трекер GitHub: labels, milestones и epic-issues, и заполнять поля Projects v2 по мере продвижения.

**Статус.** Механизм написан и проверен на реальном репозитории (read-only). Включение требует двух
действий владельца (§4) — PAT с доступом к Projects и заполнение номера/названия проекта.

**Источники истины.** Текст плана — спека в `docs/superpowers/specs/`. Структура трекера —
`.github/tracker/qh-plan.yml`. Статус — состояние issue и label'ы `status:*`, а не отдельное поле.

---

## 1. Какой токен нужен (проверено по документации 2026-10-14)

Работа агентской сессии выполняется installation-токеном GitHub App (client id `Iv23lifFg4c9eT1T6hLC`).
У приложения **нет permission `Projects`**, поэтому доска недоступна и на чтение:

| Проверка | Результат |
|---|---|
| `repository.projectsV2` / `user.projectsV2` | `FORBIDDEN: Resource not accessible by integration` |
| `createProjectV2`, `addProjectV2ItemById` | `FORBIDDEN: Resource not accessible by integration` |
| Секреты репозитория (создать секрет) | `403` |
| Issues / labels / milestones | разрешено (probe: пустой payload → `422`, а не `403`) |
| `gh` CLI | 2.23.0, без команды `gh project` (апгрейд не помогает — блокирует permission) |

`GITHUB_TOKEN` в Actions **не может** управлять Projects v2 в принципе, поэтому workflow нужен
отдельный PAT. Тип PAT определяется **владельцем проекта**:

### 1.1. Проект принадлежит пользователю → только classic PAT

Репозиторий `areatu/SonoForge` принадлежит **пользовательскому** аккаунту (`owner.__typename = User`
по API), а проекты v2, созданные из вкладки Projects репозитория, тоже принадлежат пользователю.
Для них fine-grained PAT не подходит — это документированные ограничения, а не настройка UI:

* GitHub Docs, «Managing your personal access tokens» → *Fine-grained personal access tokens
  limitations*: **«Using fine-grained personal access token to access Projects owned by a user
  account.»** ([docs.github.com](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens#fine-grained-personal-access-tokens-limitations))
* Unity fine-grained-разрешения «Projects» (`organization_projects`) находится в разделе
  **Organization permissions**, про который там же сказано: *«Organization permissions can only be
  used if the resource owner is an organization.»* Именно поэтому при Resource owner = личный
  аккаунт пункта **Projects** в списке нет вообще — искать его там бесполезно.

**Что выбирать:** Settings → Developer settings → Personal access tokens →
**Tokens (classic)** → *Generate new token (classic)* → scopes:

| Scope | Зачем |
|---|---|
| `project` | read/write доступ к проектам пользователя и организаций — то, что нужно доске |
| `repo` | по таблице scopes он «also grants the ability to manage projects owned by users», плюс работа с issues/labels/milestones репозитория |

Для режима только чтения (`mode = check`) хватает `read:project` вместо `project`.
`repo` даёт доступ ко всем вашим репозиториям, включая приватные, — это осознанный компромисс
classic-токена (см. §6).

#### Что именно отмечать в группе `repo`

В форме classic-токена под родительским `repo` есть вложенные пункты `repo:status`,
`repo_deployment`, `public_repo`, `repo:invite`, `security_events`. Это **не дополнения к `repo`, а
его подмножества** — они существуют, чтобы выдать узкий доступ *вместо* полного. В таблице scopes
про них так и написано: «only necessary to grant other users or services access to … *without*
granting access to the code».

| Пункт | Что даёт | Нужен нам |
|---|---|---|
| `repo` (родитель) | полный доступ: код, commit statuses, приглашения, коллабораторы, deployments, webhooks + issues/labels/milestones | **да** |
| `repo:status` | только commit statuses | нет |
| `repo_deployment` | только deployment statuses | нет |
| `public_repo` | то же, но лишь для публичных репозиториев | нет (см. минимум ниже) |
| `repo:invite` | только приглашения | нет |
| `security_events` | только code scanning events | нет |

**Отмечайте только родительский `repo` + `project`.** Когда отмечаете родителя, вложенные пункты
проставляются автоматически — это нормально и ничего не добавляет: при сохранении GitHub нормализует
список scopes, «discarding those that are implicitly included by another requested scope», то есть
эти подмножества схлопываются в `repo`. Проверить фактические scopes выданного токена можно по
заголовку `X-OAuth-Scopes`: `curl -sI -H "Authorization: token <PAT>" https://api.github.com | grep -i x-oauth-scopes`.

**Минимальный вариант (по желанию).** Репозиторий `areatu/SonoForge` публичный, поэтому вместо
родительского `repo` можно взять **`public_repo` + `project`**: доступ будет только к публичным
репозиториям. Сначала прогоните `mode = check` и первый `bootstrap` — если какая-то запись
(labels/milestones/issues) вернёт 403, вернитесь к `repo`.

### 1.2. Проект принадлежит организации → fine-grained PAT (least privilege)

Если перенести доску в организацию (бесплатный план подходит), ограничения на user-owned проекты
перестают действовать, и хватает fine-grained токена с Resource owner = эта организация:

| Раздел | Разрешение | Зачем |
|---|---|---|
| Organization permissions | **Projects: Read and write** | поля и элементы доски |
| Repository permissions | **Metadata: Read** | обязательное базовое разрешение |
| Repository permissions | **Issues: Read and write** | issues, labels, milestones |

`GITHUB_TOKEN` не работает ни в одном из вариантов — только PAT или GitHub App с permission
`Projects`, установленный на владельца проекта.

### 1.3. Источники

* [Managing your personal access tokens](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens#fine-grained-personal-access-tokens-limitations) — ограничения fine-grained PAT и состав разделов permissions.
* [Scopes for OAuth apps](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/scopes-for-oauth-apps) — таблица scopes classic: `project`, `read:project`, `repo`.
* [`gh project` manual](https://cli.github.com/manual/gh_project) — «The minimum required scope for the token is: project».

---

## 2. Что попадает в трекер

19 work packages из §10 спеки (QH-1e разделён на формулы и STE-gold: это разные gate'ы), 8 milestones
по gate'ам и 15 labels.

| # | Epic | Gate | Размер | Milestone | Статус на 2026-10-14 |
|---|---|---|---|---|---|
| 1 | `qh-0` baseline / traceability | G0 | M | G0 — baseline | ✅ закрыт (#159) |
| 2 | `qh-1a1` saved-record reader | G1 | M | G1 — data safety | ✅ закрыт (#154) |
| 3 | `qh-1a2` Э10 ownership | G1 | M | G1 — data safety | ✅ закрыт (#156) |
| 4 | `qh-1b1` provenance DTO + v3 | G1 | M | G1 — data safety | ✅ закрыт (#159) |
| 5 | `qh-1b2` invalidation per-result | G1 | **L** | G1 — data safety | ⚠️ PARTIAL: slice 1 (#166) + slice 2 (#168) merged |
| 6 | `qh-1c` delete/barriers/import | G1 | **L** | G1 — data safety | ⚠️ PARTIAL: PR **#167** merged; hash-remap и directory-fsync — OPEN |
| 7 | `qh-1d` manual inputs | G1 | M | G1 — data safety | ⚠️ PARTIAL: BSA (#168) + allowlist inputs (#167 merged) |
| 8 | `qh-1e` формулы/единицы | G1 | M | G1 — data safety | ✅ закрыт (#161) |
| 9 | `qh-1e-ste` same-frame gold | G1-STE | M | G1-STE — STE gold | 🔒 BLOCKED: нет gold/определений |
| 10 | `qh-2a1` locked CI / required gates | G2 | M | G2 — security / transport | ✅ закрыт (#158) |
| 11 | `qh-2a2` policy/rulesets | G2 | S | G2 — security / transport | 🔒 BLOCKED: нужен админ |
| 12 | `qh-2b1` transport evaluator | G2 | M | G2 — security / transport | ✅ закрыт (#158) |
| 13 | `qh-2b2` enforcement в клиентах | G2 | **L** | G2 — security / transport | ⛔ не начат (`p0`) |
| 14 | `qh-3-1` ViewerContext pilot | G3 | M | G3 — viewer / lifecycle | ⛔ не начат |
| 15 | `qh-3-2` остальные срезы | G3 | M | G3 — viewer / lifecycle | ⛔ не начат |
| 16 | `qh-4a` error register | G4 | M | G4 — diagnostics / boundaries | ⚠️ PARTIAL: #161, часть в #167, есть issue #160 |
| 17 | `qh-4b` boundary ratchet | G4 | M | G4 — diagnostics / boundaries | ⛔ не начат |
| 18 | `qh-5a` package matrix | G5a | M | G5a — packaged release | ⛔ не начат |
| 19 | `qh-5b` OS signing | G5b | M | G5b — OS signing | 🔒 BLOCKED: нет провайдера/сертификатов |

В тело каждого issue попадают цель, ссылка на раздел спеки, чеклист срезов со снимком прогресса,
evidence (PR и `docs/reviews/*`) и внешние блокеры.

**Не переносится:** полный текст спеки (82 KB против лимита body в 64 KB), содержание
`docs/reviews/*` (остаётся evidence в репозитории), клинические/gold-данные и PHI.

---

## 3. Как это устроено

| Файл | Роль |
|---|---|
| `.github/tracker/qh-plan.yml` | Источник структуры: project, labels, milestones, epics (срезы/evidence/блокеры) |
| `.github/scripts/project_sync.py` | Идемпотентная синхронизация: `bootstrap` / `sync` / `check` + `--dry-run` |
| `.github/workflows/project-sync.yml` | Триггеры (dispatch, issues, push по tracker-файлам, nightly) и передача секрета |

**Идемпотентность.** Каждый epic несёт в теле невидимый маркер `<!-- qh-tracker:<key> -->`; повторный
прогон не создаёт дубликат и не перезаписывает тело без `--refresh-bodies`. Labels дополняются, а не
заменяются: ручные метки сохраняются.

**Разделение ответственности (важно).**

* `state:` в плане — только **начальное** состояние нового issue. Дальше состояние issue авторитетно:
  план не может молча переоткрыть или закрыть работу (`--enforce-state` — только явным флагом).
* Статус на доске **вычисляется**: closed → `Done`, `status:blocked` → `Blocked`, `status:partial` →
  `In Progress`, иначе `Todo`.
* Чеклист в теле — снимок; обновляется по `--refresh-bodies` и помечен датой снимка.

**Поля доски.** `Status` (встроенное), `Gate` и `Size` (single select), `Plan` (текст) — создаются
`bootstrap --create-fields`, если их нет. Свои поля проекта не трогаются.

**Закрытие milestone.** Gate-milestone закрывается сам, когда в нём не осталось открытых issue
(пустой milestone остаётся открытым: это gate, а не завершённый этап).

---

## 4. Включение (runbook)

1. **PAT.** Проекты принадлежат пользователю `areatu` → нужен **classic** токен (см. §1.1):
   github.com → Settings → Developer settings → Personal access tokens → **Tokens (classic)** →
   *Generate new token (classic)* → scopes **`project`** и **`repo`**.
   * В группе `repo` отмечайте **только родительский пункт `repo`** (вложенные `repo:status`,
     `repo_deployment`, `public_repo`, `repo:invite`, `security_events` — подмножества, они
     проставятся сами и ничего не добавят; подробнее §1.1).
   * Пункт **Projects** в fine-grained токене не появится при Resource owner = личный аккаунт —
     это не ошибка UI, а документированное ограничение (§1.1).
   * Если PAT принадлежит другому пользователю, проект должен быть ему доступен — иначе будет
     тот же `FORBIDDEN`.
   * Срок жизни — на усмотрение владельца; ротация описана в §6.
2. **Секрет.** Репозиторий → Settings → Secrets and variables → Actions → **New repository secret**,
   имя — `PROJECTS_TOKEN`, значение — токен.
3. **Проект.** В `.github/tracker/qh-plan.yml` заполнено `project.owner: areatu`,
   `project.title: "SonoForge Tracker"`, `project.create: true`, `project.link_to_repo: true`.
   Доска **создаётся первым же прогоном** `bootstrap` (в режимах `check`/`dry-run` создание
   запрещено). Номер доски GitHub присваивает сам; поиск идёт по названию, поэтому номер знать
   не обязательно. Если доска уже существует и названа иначе — впишите её `number` или `title`.
4. **Первый прогон.** Автоматически: push в `main` с изменениями в `.github/tracker/**` запускает
   `bootstrap` + `sync` сам. Вручную: Actions → **Project sync (tracker)** → *Run workflow*
   (`mode = bootstrap`, при желании сначала `dry_run = true`).
5. **Проверка.** `mode = check` показывает дрейф: чего не хватает в структуре и на доске.

Локальный прогон без доступа к GitHub: `bootstrap --dry-run` без токена печатает, что будет создано.

---

## 5. Эксплуатация

### 5.1. Порядок автоматического заполнения (что происходит после пуша плана)

| Шаг | Кто выполняет | Что получается |
|---|---|---|
| 1. План/спека в репозитории | человек или агент | `docs/superpowers/specs/*.md` — прозаический план; `.github/tracker/*.yml` — его структура |
| 2. Push в `main` (или Run workflow) | GitHub Actions | запуск workflow **Project sync (tracker)**; токен берётся из секрета `PROJECTS_TOKEN` |
| 3. `bootstrap` | `project_sync.py` с PAT | создаёт доску (если её нет), поля `Gate`/`Size`/`Plan`, labels, milestones, epic-issues |
| 4. `sync` | `project_sync.py` с PAT | добавляет issue на доску и проставляет `Status`/`Gate`/`Size`/`Plan` |
| 5. Дальнейшее движение | события GitHub | закрыли PR с `Closes #N` → issue закрылся → событие `issues: closed` → `Status = Done` |

Правила, по которым это не расходится с реальностью:

* **Статус выводится, а не хранится.** closed → `Done`; `status:blocked` → `Blocked`;
  `status:partial` → `In Progress`; иначе `Todo`. Поэтому доска всегда отражает состояние issue.
* **`state:` в плане — только для новых issue.** Правка плана не переоткрывает и не закрывает
  выполненную работу (`--enforce-state` — отдельным явным флагом).
* **Тело issue — снимок на дату `snapshot:`.** Чеклист срезов обновляется прогоном
  `bootstrap --refresh-bodies`, а не сам.
* **Ночная сверка** (`schedule`) ловит правки, сделанные мимо событий.

* **Статус по мере продвижения** меняется сам: merge PR с `Closes #N` закрывает issue → событие
  `issues: closed` → workflow ставит `Done`. Частичная готовность — label `status:partial`
  (`In Progress`), внешний блокер — `status:blocked` (`Blocked`).
* **Новый срез** добавляется в `.github/tracker/qh-plan.yml` (`slices:`) и переносится в трекер
  прогоном `bootstrap` с `--refresh-bodies` (или вручную — тело issue не перезаписывается само).
* **Новый пакет** добавляется в план и создаётся тем же `bootstrap`; push в `main` с изменениями
  tracker-файлов запускает его автоматически.
* **Ночная сверка** (`schedule`) ловит изменения, сделанные мимо событий.
* **Новый план** (например, отдельный трек STE или WP4) — новый файл `.github/tracker/<name>.yml` и
  вызов скрипта с `--plan .github/tracker/<name>.yml`: движок планов не знает, он читает план.

### 5.2. Что может агент, а что — только PAT

Спека/план в репозитории — это обычные документы, которые пишем мы (агент по запросу, владелец вручную).
Доска — их отображение, и запись в неё требует токена с правом `Projects`:

| Действие | Агент из сессии | Workflow с `PROJECTS_TOKEN` |
|---|---|---|
| Создать/править спеку и `.github/tracker/*.yml` | **да** (коммит в ветку) | — |
| Разобрать план и распечатать, что будет сделано (`--dry-run`, без токена) | **да** | — |
| Создать доску, поля, labels, milestones, issue, заполнить поля | **нет** — у токена сессии нет permission `Projects` | **да** |
| Прочитать доску, чтобы сверить состояние | **нет** | **да** (в логе прогона и в summary) |
| Запустить синхронизацию | через `gh workflow run`, если у токена есть `actions: write`; иначе кнопкой в UI | автоматически на push в `main` |

Поэтому «заполнить проект по запросу» работает так: агент правит план-файл и push'ит его в `main` →
workflow сам приводит доску в соответствие. Прямая запись в Projects из песочницы невозможна —
и не нужна: единственный путь изменений всё равно идёт через git, где он ревьюится.

---

## 6. Безопасность

* Пат используется **только** для `bootstrap`/`sync`/`check`; в остальные workflow он не передаётся.
  В этом job'е нет сторонних actions — только `actions/checkout` и `actions/setup-python`.
* Токен никогда не печатается: скрипт не логирует заголовки запросов, в ошибках только метод, URL и
  код ответа.
* **Classic-путь (§1.1) шире, чем нужно:** scope `repo` даёт доступ ко всем вашим репозиториям, а
  `project` — ко всем вашим проектам. Ограничить это можно так: держать токен только в секрете
  репозитория (а не в открытом виде), задать срок жизни и, если нужен least privilege, перейти на
  §1.2 (доска в организации + fine-grained токен). Альтернатива — GitHub App с permission `Projects`,
  установленный вами же, и генерация installation-токена в workflow.
* Fine-grained-путь (§1.2) уже минимален: Projects (RW) + Metadata (R) + Issues (RW) в одной
  организации, без доступа к содержимому репозиториев.
* Ротация: при подозрении на утечку — отозвать PAT в Settings, создать новый, обновить секрет
  `PROJECTS_TOKEN`, запустить `mode = check` (убедиться, что доступ восстановлен).
* В трекер не попадают PHI, clinical originals и содержимое `docs/reviews/*` — только ссылки.

---

## 7. Если отдельный PAT не нужен

Без PAT доска всё равно наполняется, но без записи полей: workflow `Project sync` тогда работает как
no-op с предупреждением, а в проекте включаются встроенные автоматизации:
**Workflows → Auto-add to project** с фильтром `label:qh` плюс «Item closed → Done» и
«Item reopened → In progress». Поля Gate/Size/Plan в этом варианте заполняются вручную.
Файлы `.github/tracker/qh-plan.yml` и скрипт в этом сценарии продолжают служить источником структуры.

---

## 8. Что проверено в этом срезе

* `check` против реального репозитория (read-only): корректно перечислены 15 отсутствующих labels,
  8 milestones, 19 несозданных issue и честная строка «проект недоступен — состав доски не проверен»
  (43 расхождения, exit 1).
* `bootstrap --dry-run` с токеном: список запланированных действий, деградация недоступного проекта в
  предупреждение, ноль записей.
* `bootstrap --dry-run` без токена: офлайн-предпросмотр, exit 0.
* `ruff check` / `ruff format --check` (0.15.16 из `uv.lock`), `py_compile`, разбор обоих YAML.
* Подсказки по токену: прогон с токеном GitHub App без permission `Projects` даёт не только `FORBIDDEN`,
  но и объяснение, что нужен classic PAT со scopes `project` + `repo` (проверено на реальном ответе API).
* `tests/unit/test_project_sync.py` — 36 тестов на движок: чистые функции (разбор срезов,
  производный статус, подсказки по токену, валидация плана, разметка тела issue), 8 случаев
  owner-type-tolerant поиска доски и 5 случаев типов переменных GraphQL; baseline инвентаря
  7020 (`not_gui` 3720, GUI 3300 в 168 файлах), gui-маркеры не менялись.
* Создание доски и привязка к репозиторию выполняются только в `bootstrap` и никогда в `check`/`dry-run`;
  прогон с `--create-project` в dry-run проверен — проект не создаётся.

**Не проверено в этом срезе (осознанно):** GraphQL-мутации Projects (`createProjectV2Field`,
`addProjectV2ItemById`, `updateProjectV2ItemFieldValue`) — их нельзя выполнить без PAT с доступом к
проекту, и они не выполнялись, чтобы не менять GitHub. Первый `bootstrap` владельца и есть проверка
этого пути — что из этого вышло, см. §9.

---

## 9. Первый реальный прогон: type mismatch и исправление (2026-10-14)

Первый настоящий прогон workflow `Project sync` (событие `issues`, секрет `PROJECTS_TOKEN` настроен)
прошёл bootstrap-путь и упал на первой же записи single-select поля:

```
GraphQL error: Type mismatch on variable $option and argument singleSelectOptionId (ID! / String)
```

Причина: в схеме Projects v2 `ProjectV2FieldValue.singleSelectOptionId` объявлен как `String` (рядом
`text: String`, `number: Float`, `date: Date`), а мутация `_SET_SINGLE_SELECT` объявляла `$option: ID!`.
GitHub валидирует операцию целиком **до** выполнения, поэтому падал каждый прогон (событийные,
расписания и ручные), и ни одна запись доски не выполнялась — ни `Status`, ни `Gate`, ни `Size`.
Соседние `projectId/itemId/fieldId` в `UpdateProjectV2ItemFieldValueInput` действительно `ID!`.

Исправление и защита от повторов:

* `$option: ID!` → `$option: String!` в `.github/scripts/project_sync.py` (id варианта остаётся
  непрозрачной строкой и не переписывается);
* типы переменных **всех 15 операций** скрипта закреплены таблицей `_EXPECTED_VARIABLES` в
  `tests/unit/test_project_sync.py`, снятой с живой схемы (`__type(name: ...)`), плюс тест
  `test_the_type_table_pins_every_operation_constant`: новая операция не может проскочить мимо
  проверки. Расхождение со схемой теперь падает в CI, а не в проде;
* проверено без записи в доску: та же мутация с синтетическими id даёт на `ID!` ровно ошибку из CI,
  а на `String!` — уже ошибку исполнения («Could not resolve to a node…»), то есть валидация проходит.

Побочный вывод для эксплуатации: прогон, упавший на валидации, оставляет доску в промежуточном
состоянии — issues/milestones/labels создаются раньше записи полей, и после исправления достаточно
дождаться следующего прогона (`sync` идемпотентен, дублей не будет).

---

## 10. Обновление 2026-10-20: две доски и снимки issue

Сверка QH/TP зафиксирована в [`2026-10-20-tracker-refresh-ru.md`](2026-10-20-tracker-refresh-ru.md).
Что изменилось в механике:

* `project-sync.yml` теперь идёт матрицей по двум планам — `qh-plan.yml` (доска QH) и
  `tool-panel-plan.yml` (доска Tool Panel 2.0), у каждой свой `Plan` и свой набор полей.
* Добавлен `tracker-refresh.yml`: по push в `.github/tracker/**` (и вручную) он обновляет
  тела/labels issue скриптом `apply_tracker_snapshots.py`, затем синхронизирует обе доски.
  Так снимок issue перестаёт отставать от плана, не превращая каждое событие issue в
  перезапись тела.
* `tool-panel-plan.yml` получил `plan_name: TP`, `snapshot` и `spec`: до этого в телах
  TP-issues стояло «Источник: спека QH», а в поле Plan попадало имя файла, не имя плана.
