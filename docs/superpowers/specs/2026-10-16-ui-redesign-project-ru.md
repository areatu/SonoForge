# Проект «UI-редизайн» (спека 2026-10-16) — структура для GitHub Projects

Цель: https://github.com/users/areatu/projects/ → новый user-проект
«SonoForge — Переработка дизайна интерфейса (UI, 2026-10-16)».

Источник: `2026-10-16-ui-redesign-spec-plan-ru.md`
(upstream `areatu/SonoForge @ arena/ea808c3a-sonoforge`, §10–§11).

Статус: проект создан — https://github.com/users/areatu/projects/8
(«SonoForge — Переработка дизайна интерфейса (UI, 2026-10-16)»),
30 items: UI-0…UI-8, UA-01…UA-20, UQ-трекер; поля `Status` (Todo /
In Progress / Done, по умолчанию), `Package`, `Size`; связан
с репозиторием `areatu/SonoForge`.

## Доступ и повторное наполнение

Токен из `git remote origin` имеет только scope `public_repo` — для
Projects V2 нужен scope `project`. Создание/наполнение выполнялось
через `gh`-аккаунт из keyring (`gist, project, read:org, repo, workflow`).
В сессии shell переменную `GH_TOKEN` снимать, чтобы `gh` брал keyring:

```powershell
Remove-Item Env:GH_TOKEN -ErrorAction SilentlyContinue
gh auth status
```

Повторное (идемпотентное по полям) наполнение существующего проекта:

```bash
python scripts/create_ui_redesign_project.py --owner areatu --project-number 8 --link-repo areatu/SonoForge
```

Новый проект с нуля (если понадобится ещё один):

```bash
python scripts/create_ui_redesign_project.py --owner areatu --link-repo areatu/SonoForge
```

## Структура проекта

Поля: `Status` (Todo / In Progress / Done), `Package` (UI-0…UI-8),
`Size` (S/M/L). Связь с репозиторием — link `areatu/SonoForge`.

| # | Item | Size | Зависит от |
|---|---|---|---|
| 1 | UI-0 — Токены, «Графит», храповик, скриншот-база | L | — |
| 2 | UI-1 — Оболочка окна Win11 + строка пациента | L | UI-0 |
| 3 | UI-2 — Пресеты компоновки + настройки | L | UI-1; PR-3 — TP-0 |
| 4 | UI-3 — Полоса шага под снимком | M | UI-2 PR-1, TP-3 |
| 5 | UI-4 — Отчёт R3 | L | UI-1; TP-1; QH-1b |
| 6 | UI-5 — Справочник S1 + карточка S2 (+PR-0 ММЛЖ сразу) | M | UI-0 |
| 7 | UI-6 — Фокус для одиночного файла | M | UI-2 |
| 8 | UI-7 — Стартовая → браузер A2 | M | UI-1 |
| 9 | UI-8 — Чистка и документация | S | все |
| 10–29 | UA-01…UA-20 — приёмка (§11) | — | к своим UI |
| 30 | UQ-01…UQ-12 — открытые вопросы (§1.2, defaults) | — | согласование |

Порядок: UI-0 → UI-1 → UI-2 → (UI-3 ∥ UI-4 ∥ UI-5) → UI-6 → UI-7 → UI-8.

## Вручную через веб (запасной путь)

1. Открыть https://github.com/users/areatu/projects/ → New project → Blank.
2. Название — как выше; описание — из `PROJECT_DESC` в скрипте.
3. Add field → `Package`, `Size` (text); открыть Board по `Status`.
4. Add item → вставить 9 пакетов UI-0…UI-8 и 20 приёмок UA-01…UA-20
   (тексты — §10 и §11 спеки; короткие формулировки — в скрипте).
5. Link repository → `areatu/SonoForge`.
