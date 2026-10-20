# Сверка трекера QH / Tool Panel / UI — 2026-10-20

**Ветка:** `arena/1ed784e3-sonoforge` (от `main` f5f61e0, после мержа PR #259).

**Зачем.** Привести issues и Projects в соответствие с фактически влитыми PR:
TP-0…TP-4 закрыты, TP-5 в review, TP-6 (issue #205) выполняется сейчас; QH-1b.2 и
QH-2b.2 закрыты, QH-4a продвинулся. До сверки снимки issue показывали «0/6» у
закрытого TP-3 и «0/5» у закрытого QH-2b.2.

**Источники истины.** Структура — `.github/tracker/qh-plan.yml` и
`.github/tracker/tool-panel-plan.yml`; прогресс — состояние issue и labels `status:*`;
текст планов — спеки QH, TP, UI. Тела issue — снимок, а не живое состояние.

---

## 1. Что обновлено

| Что | Было | Стало |
|---|---|---|
| `tool-panel-plan.yml` | `plan: tool-panel`, без `snapshot`/`spec`; TP-0…TP-4 `open`, срезы пустые | `plan_name: TP`, снимок 2026-10-20, путь спеки; TP-0…TP-4 `closed` со срезами и PR; TP-5/TP-6 `status:partial` |
| `qh-plan.yml` | снимок 2026-10-14; qh-1b2/qh-2b2 `open` с пустыми срезами | снимок 2026-10-20; оба `closed` со срезами; ER-07/08/09 и RAP отмечены по PR; остатки ER выписаны явно |
| Тела issues | снимки 2026-10-14, у TP — «Источник: спека QH» | рендер `render_body` из планов: правильный источник, снимок, срезы, evidence, примечания |
| Labels | у #204/#205 нет статуса; у закрытых #175/#183 висит `p0` | #204/#205 → `status:partial` (In Progress); с закрытых сняты `p0` и `status:*` |
| `project-sync.yml` | синхронизировал только `qh-plan.yml` | матрица QH + Tool Panel 2.0, у каждого своя доска и Plan |
| `tracker-refresh.yml` | — | новый workflow: тела/labels issue + синхронизация обеих досок |
| `apply_tracker_snapshots.py` | — | идемпотентный рендер тел и статус-labels из планов; `--dry-run` |

**Запись issues/Projects из этой сессии недоступна.** Токен сессии — GitHub App
installation с read-only Issues и без permission `Projects`:
`PATCH /issues/205` и `POST /issues/205/labels` → `403 Resource not accessible by integration`;
`projectsV2` → `FORBIDDEN` (это же зафиксировано в
`docs/reviews/2026-10-14-qh-plan-github-tracker-mapping-ru.md` §1). Поэтому запись
выполняется workflow `Tracker refresh` (у него `issues: write` от `GITHUB_TOKEN` и
`PROJECTS_TOKEN` для досок), а не вручную из агентской сессии.

## 2. Фактическое состояние TP

| Пакет | Issue | Состояние | PR / остаток |
|---|---|---|---|
| TP-0 каталог, раскладка v3 | #199 | ✅ closed | #213 (каталог), #215 (v3 + ASE Table 6) |
| TP-1 номенклатура RU xor EN | #200 | ✅ closed | #231 (подписи, golden RU/EN, мм/см) |
| TP-2 каркас панели 2.0 | #201 | ✅ closed | #228 (каркас), #232 (default, клавиатура, A-16 авто) |
| TP-3 протоколы | #202 | ✅ closed | #233, #234, #236, #241, #251 |
| TP-4 окошко подписи | #203 | ✅ closed | #243 |
| TP-5 настройки 2.0 | #204 | 🟡 in review | #261 домен (open), #262 UI (open, stacked) |
| TP-6 радиальное меню, палитра, Alt | #205 | 🟡 в работе | #237 влит (палитра, Alt, ⌘/⌥); радиальное меню и A-17 — остаток |
| TP-7 чистка и документация | #206 | ⚪ open | после TP-5/TP-6 |

**Остатки, которые нельзя терять:**

1. **TP-3 / A-08:** `presentation/viewer_clip_context.py::clip_view()` всегда возвращает `""`
   (DICOM `ViewName` не читается). Шаг, зависящий от вида клипа, блокируется по
   модальности, но не по `A4C/A2C/PLAX`. PR #251 прямо называет это следующим срезом.
2. **TP-2 / A-16:** закрыт offscreen-гейтом (280/320/420 px × 100/150/200 % × RU/EN);
   ручные скриншоты с реальной графикой перенесены в TP-7.
3. **TP-5:** A-15 — ручная приёмка диалога конфликта; порядок мержа #261 → retarget #262
   на `main` → #262.
4. **TP-6:** в палитре нет группы «Протоколы»: PR #237 писался до подключения
   `ProtocolSession` (#236/#241) и явно оставил это отдельным срезом.

## 3. Фактическое состояние QH

| Пакет | Issue | Состояние | Комментарий |
|---|---|---|---|
| QH-1b.2 freshness per-result | #175 | ✅ closed 2026-10-20 | #195 (Simpson), #259 (Simpson/Doppler/derived + единая проекция UI/текст/PDF, S-03) |
| QH-2b.2 transport enforcement | #183 | ✅ closed 2026-10-15 | #192: клиенты, редиректы, миграция профилей, TLS/DIMSE fixtures |
| QH-1c delete/barriers | #176 | 🟡 partial | #167, #223; остаток — native disk-full на Windows/macOS |
| QH-1d manual inputs | #177 | 🟡 partial | #167, #168, #191, #194; остаток — UI-evidence RAP |
| QH-4a error register | #186 | 🟡 partial | #191 ER-07; #194 ER-08 калибровка; #196/#198 ER-09 кроме onnx; ER-10…12 и landmarks открыты |
| QH-3.1 / 3.2 decomposition | #184/#185 | ⚪ open | не начаты; ждут стабилизации контракта G1 |
| QH-4b boundary ratchet | #187 | ⚪ open | не начат |
| QH-5a packaged release | #188 | ⚪ open | не начат |
| QH follow-ups | #160 | ⚪ open | остатки ER-08…12 и валидационных gate'ов |
| G1-STE / G2 policy / G5b signing | #179/#181/#189 | 🔴 blocked | внешние данные, админ-доступ, сертификаты |

## 4. UI-план (отдельного issue-трекера нет)

Ведётся текстом `docs/superpowers/specs/2026-10-16-ui-redesign-spec-plan-ru.md`.
По влитым PR: UI-0…UI-3, UI-5, UI-6, UI-7 в основном закрыты (последние: UI-5 PR-4 #249,
UI-6 #255, UI-7 #256). У UI-4 влит PR-3 «Фразы» (#260); остаются PR-4 «откуда значение»
и PR-5 «печать и Завершить». UI-8 (чистка, HELP, скриншоты, CHANGELOG) не начат.
Отдельные issues под UI не создавались — если нужен такой же трекер, как QH/TP,
это отдельное решение владельца (третий `*-plan.yml` + доска).

## 5. Следующие шаги

### Сейчас — TP-6 (#205)

1. **PR-2: радиальное меню (A-14).**
   - Новый `presentation/radial_menu.py`: 8 секторов на контекст, центр «Esc»,
     сектор «Ещё…» с прежним контекстным меню; `QPainter`, токены темы, `reduce_motion`.
   - `viewer_widget.contextMenuEvent`: ПКМ на пустом месте → меню через 250 мс;
     рывок ≥ 24 px выбирает сектор без показа; ПКМ во время контура — текущее
     поведение (отмена точки/откат freehand); macOS — Ctrl+клик и два пальца.
   - Тесты: открытие/закрытие, выбор сектора, жест, «во время рисования меню нет»,
     «Ещё…» возвращает прежние пункты.
2. **Палитра: группа «Протоколы».** Добавить команды `ProtocolSession` (старт/стоп/
   следующий шаг) в `command_catalog.py` и обработчики `main_window`; проверить, что
   выбор из палитры не ломает активный протокол в другой вкладке (A-10).
3. **A-17:** бенчмарк фильтра палитры (≤ 16 мс/символ) и обновления панели
   (≤ 50 мс p95). Результат — в `bench/` или отдельный perf-тест с зафиксированным
   бюджетом; без бюджета A-17 не закрывается.
4. **Ручная приёмка A-14/A-17** на Windows и macOS (Ctrl+клик, два пальца, ⌘/⌥).
5. Обновить снимок TP-6 в `tool-panel-plan.yml`, закрыть #205 после PR-2 + бенчмарка.

### Параллельно — TP-5 (#204)

1. Ревью и мерж **#261** (домен), затем переключить базу **#262** на `main` и мержить.
2. Ручная A-15: конфликт клавиш, «Оставить» ничего не меняет; битый JSON импорта не
   теряет настройки; сброс возвращает умолчания.
3. Закрыть #204, снять `status:partial`.

### После TP-5/TP-6 — TP-7 (#206)

- Удалить старый `MeasuresMenuWidget`/bridge'и, если флаг панели 2.0 снят.
- HELP RU/EN, CHANGELOG, `docs/screenshots` (включая реальные A-16).
- Финальный проход A-01…A-17 и снятие экспериментального флага.

### QH — по приоритету

1. **G1:** #176 native disk-full Windows/macOS; #177 UI-evidence RAP. После них G1
   можно объявлять закрытым (кроме G1-STE).
2. **G4:** #186 — landmarks без raw `str(exc)`, `onnx_worker` на статические коды,
   ER-10/11 producer allowlist и ER-12 native; #187 — boundary ratchet.
3. **G3:** #184 `ViewerContext`/commands + overlay/magnifier; #185 tools → contours →
   calibration/workers. Начинать после стабилизации G1-контракта.
4. **G5a:** #188 locked package matrix и clean-machine smoke; **G5b** #189 и **G1-STE**
   #179 остаются внешне заблокированными; **G2** #181 — нужен админ-подтверждённый
   ruleset/policy.
5. #160 — трекер остатков ER; не дублировать в нём уже закрытые ER-07/09.

### UI

- UI-4 PR-4 (ховер «откуда значение») и PR-5 (печать, «Завершить»).
- UI-8: удаление activity bar и совместимости палитр, HELP/скриншоты/CHANGELOG.

### Трекер / доски

1. Влить эту ветку в `main` (workflow-файлы и снимки плана).
2. `Tracker refresh` запустится сам на push по путям `.github/tracker/**`:
   обновит тела/labels issues и обе доски. Если `PROJECTS_TOKEN` не настроен, issues
   обновятся, а доски — нет (в логе будет warning).
3. Ручной запуск: Actions → **Tracker refresh (issues + boards)** → Run workflow.
   Локально с classic PAT (`project` + `repo`):
   ```bash
   GH_TOKEN=... python3 .github/scripts/apply_tracker_snapshots.py \
     --plan .github/tracker/qh-plan.yml \
     --plan .github/tracker/tool-panel-plan.yml
   GH_TOKEN=... python3 .github/scripts/project_sync.py sync \
     --plan .github/tracker/qh-plan.yml
   GH_TOKEN=... python3 .github/scripts/project_sync.py sync \
     --plan .github/tracker/tool-panel-plan.yml
   ```
4. Проверить на доске: TP-0…TP-4 → Done; TP-5/TP-6 → In Progress; TP-7 → Todo.
   Закрытые QH-1b.2/QH-2b.2 → Done; #176/#177/#186 → In Progress; blocked — Blocked.

## 6. Риски и ограничения

- **Projects v2 не читается и не пишется токеном сессии** — фактическое состояние
  досок проверяется только PAT-ом или workflow; этот документ фиксирует ожидаемое
  состояние, а не подтверждённое.
- **Тела issues — снимок.** После этой сверки они обновляются workflow при изменениях
  `.github/tracker/**`, но ручная правка тела будет перезаписана; менять надо план.
- **TP-3 `clip_view`** и **TP-2 A-16 скриншоты** — известные остатки, не выданы за
  закрытые; они выписаны в примечаниях TP-3/TP-2 и в §2.
- **QH-4a:** ER-07 и часть ER-08/09 закрыты; ER-10/11/12 и landmarks/onnx остаются,
  issue #186 не закрывается.
- Внешние блокеры (#179, #181, #189) не становятся «готовыми по коду» от обновления
  трекера.
