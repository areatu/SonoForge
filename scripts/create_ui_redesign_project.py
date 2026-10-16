"""Create GitHub user Project for UI-redesign spec (2026-10-16).

Spec: docs/superpowers/specs/2026-10-16-ui-redesign-spec-plan-ru.md
      (upstream: areatu/SonoForge @ arena/ea808c3a-sonoforge)
Target: https://github.com/users/areatu/projects/ (user-owned Project V2)

Usage:
  python scripts/create_ui_redesign_project.py --dry-run
  python scripts/create_ui_redesign_project.py --owner areatu --link-repo areatu/SonoForge

Requires: gh CLI logged in with `project` scope:
  gh auth login -h github.com -s project,repo,read:org
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):  # Windows cp1251 console vs UTF-8 bodies
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT_TITLE = "SonoForge — Переработка дизайна интерфейса (UI, 2026-10-16)"
PROJECT_DESC = (
    "Проект по спеке 2026-10-16-ui-redesign-spec-plan-ru.md: "
    "A1 «Рабочая станция», графит, 3 пресета, полоса шага, отчёт R3, "
    "справочник S1/S2, фокус, токены. Порядок: UI-0, UI-1, UI-2, затем "
    "(UI-3, UI-4, UI-5), затем UI-6, UI-7, UI-8."
)

PACKAGES: list[dict] = [
    {"id": "UI-0", "size": "L", "deps": "—",
     "title": "UI-0 — Токены, «Графит», храповик, скриншот-база",
     "body": "tokens.py/palettes.py/qss.py; get_theme_palette() совместимость; исправление system-темы Windows; check_ui_colors + check_contrast; PR-1..PR-7 по областям (§10). Gate: navy до/после совпадает, храповик зелёный."},
    {"id": "UI-1", "size": "L", "deps": "UI-0",
     "title": "UI-1 — Оболочка окна Windows 11 + строка пациента",
     "body": "hit_test + win32_chrome + запасная рамка; заголовок с вкладками и Ctrl+K; строка пациента 42px; разнос SystemBar; Send to server в локаль (§4.1, §4.3). Gate: hit_test, чек-лист WP4."},
    {"id": "UI-2", "size": "L", "deps": "UI-1; PR-3 — TP-0",
     "title": "UI-2 — Пресеты компоновки + настройки",
     "body": "LayoutConfig v2 + миграция 16 сочетаний; табличный _rebuild_layout; раздел настроек; ряд/рейка; лента клипов (§4.2, §8.1). Gate: ≤300мс, скриншоты 3×3×RU/EN×100/150%."},
    {"id": "UI-3", "size": "M", "deps": "UI-2 PR-1, TP-3",
     "title": "UI-3 — Полоса шага под снимком",
     "body": "Виджет полосы внутри TP-3 (§4.4). Gate: геометрия «ничего поверх снимка», Enter/S/Esc, reduce_motion."},
    {"id": "UI-4", "size": "L", "deps": "UI-1; TP-1; QH-1b",
     "title": "UI-4 — Отчёт R3",
     "body": "Переключатель Изображения|Отчёт; разделы; A4=PDF; «откуда значение»; фразы ≤30 RU/EN; PDF+печать (§4.6). Gate: golden RU/EN, маркеры не печатаются."},
    {"id": "UI-5", "size": "M", "deps": "UI-0 (PR-0 данных — сразу)",
     "title": "UI-5 — Справочник S1 + карточка S2",
     "body": "PR-0 данные ММЛЖ (lvm: женщины М-режим 67–162г); S2 без рисунков; S1 окно; how_to (§4.7, UQ-12). Gate: тест дерева (без изображений), градации по полу."},
    {"id": "UI-6", "size": "M", "deps": "UI-2",
     "title": "UI-6 — Фокус для одиночного файла",
     "body": "F1 (по умолч., UQ-02) или F2; автовход настройкой; F — выход (§4.8). Gate: состояние у вкладки."},
    {"id": "UI-7", "size": "M", "deps": "UI-1",
     "title": "UI-7 — Стартовая → браузер исследований A2",
     "body": "Список исследований, фильтры, открытие из папки/PACS (§4.10)."},
    {"id": "UI-8", "size": "S", "deps": "все",
     "title": "UI-8 — Чистка и документация",
     "body": "Удалить activity bar/v1-чекбоксы/совместимость палитр; HELP RU/EN; скриншоты docs/screenshots; CHANGELOG; a11y-проход."},
]

ACCEPTANCE = [
    ("UA-01", "Snap Layouts на Win11"), ("UA-02", "Snap/Win+стрелки/вытаскивание"),
    ("UA-03", "Ресайз за 4 стороны и углы"), ("UA-04", "Переключение пресетов ≤300мс"),
    ("UA-05", "Матрица скриншотов 3×3×2 разрешения×2 масштаба×RU/EN"),
    ("UA-06", "Миграция старых настроек"), ("UA-07", "Шаг Симпсона в полосе"),
    ("UA-08", "Полосы нет вне протокола"), ("UA-09", "Режим у вкладки"),
    ("UA-10", "PDF == экран"), ("UA-11", "«Откуда значение»"),
    ("UA-12", "«Не заполнено» → взвод шага"), ("UA-13", "Карточка КДР без рисунка"),
    ("UA-14", "ММЛЖ 162г М-режим Ж — норма"), ("UA-15", "Точки норм выкл. по умолч."),
    ("UA-16", "System-тема на Win тёмная"), ("UA-17", "CI: храповик+контраст"),
    ("UA-18", "Фокус + F"), ("UA-19", "Только клавиатура"),
    ("UA-20", "Запасная системная рамка"),
]

OPEN_QUESTIONS = ["UQ-01", "UQ-02", "UQ-03", "UQ-04", "UQ-05", "UQ-06",
                  "UQ-07", "UQ-08", "UQ-09", "UQ-10", "UQ-11", "UQ-12"]


def run(cmd: list[str], dry: bool) -> dict:
    print("+ " + " ".join(cmd))
    if dry:
        return {}
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        print(out.stderr.strip(), file=sys.stderr)
        raise SystemExit(out.returncode)
    try:
        return json.loads(out.stdout) if out.stdout.strip() else {}
    except json.JSONDecodeError:
        print(out.stdout)
        return {}


def _existing_field_names(number: int, owner: str, dry: bool) -> set[str]:
    if dry:
        return set()
    out = subprocess.run(
        ["gh", "project", "field-list", str(number),
         "--owner", owner, "--format", "json"],
        capture_output=True, text=True)
    if out.returncode != 0:
        print(out.stderr.strip(), file=sys.stderr)
        raise SystemExit(out.returncode)
    try:
        return {f["name"] for f in json.loads(out.stdout).get("fields", [])}
    except (json.JSONDecodeError, KeyError, TypeError):
        return set()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--owner", default="areatu")
    ap.add_argument("--link-repo", default="areatu/SonoForge")
    ap.add_argument("--project-number", type=int, default=None,
                    help="Populate existing project instead of creating one")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.project_number is not None:
        num = args.project_number
        print(f"using existing project number: {num}")
    else:
        num = run(["gh", "project", "create", "--owner", args.owner,
                   "--title", PROJECT_TITLE, "--format", "json"], args.dry_run).get("number")
    if num is None and args.dry_run:
        print(f"[dry-run] project: {PROJECT_TITLE!r} owner={args.owner}")
        print(f"[dry-run] packages={len(PACKAGES)} acceptance={len(ACCEPTANCE)} "
              f"open_questions={len(OPEN_QUESTIONS)}")
        return
    print(f"project number: {num}")
    have = _existing_field_names(num, args.owner, args.dry_run)
    # NOTE: Status (Todo/In Progress/Done) exists by default — reuse it.
    for field in ("Package", "Size"):
        if field in have:
            print(f"field {field!r} exists, skipping")
            continue
        run(["gh", "project", "field-create", str(num), "--owner", args.owner,
             "--name", field, "--data-type", "TEXT"], args.dry_run)
    for p in PACKAGES:
        run(["gh", "project", "item-create", str(num), "--owner", args.owner,
             "--title", p["title"], "--body", p["body"]], args.dry_run)
    for uid, title in ACCEPTANCE:
        run(["gh", "project", "item-create", str(num), "--owner", args.owner,
             "--title", f"{uid} — {title}",
             "--body", f"Приёмка §11 спеки UI-2026-10-16. {PROJECT_TITLE}."], args.dry_run)
    run(["gh", "project", "item-create", str(num), "--owner", args.owner,
         "--title", "UQ-01…UQ-12 — Открытые вопросы (defaults в §1.2)",
         "--body", "Трекер согласования UQ-01…UQ-12; план пользуется defaults без ответа."],
        args.dry_run)
    if args.link_repo:
        run(["gh", "project", "link", str(num), "--owner", args.owner,
             "--repo", args.link_repo], args.dry_run)


if __name__ == "__main__":
    main()
