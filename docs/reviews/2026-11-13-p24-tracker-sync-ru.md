# P2.4: синхронизация трекера с `main`

> **Снимок на 2026-11-13.** Документ фиксирует состояние на эту дату и не обновляется вслед за кодом: актуальное состояние — в коде, `README.md`, HELP и открытых issues.

Дата: 2026-11-13. Основание: P2.4 в [аудите после шести этапов](2026-11-12-post-six-stages-audit-ru.md).
Issue: [#538](https://github.com/areatu/SonoForge/issues/538). Кода и поведения изменение не касается.

## Проблема

Шесть срезов были реализованы и влиты, но их issues оставались OPEN. По открытым issues нельзя было понять, что этапы закрыты, а #514 смешивал завершённый S-02b с нерешённым вопросом владельцу о хранении FPS-правки.

## Evidence

Каждый срез проверен по состоянию PR и merge-коммиту в `main`:

| Issue | Срез | PR | Merge commit |
|---|---|---|---|
| [#510](https://github.com/areatu/SonoForge/issues/510) | S-02: память вкладки | [#511](https://github.com/areatu/SonoForge/pull/511) | `ea0b3bd` |
| [#512](https://github.com/areatu/SonoForge/issues/512) | S-02a: сорванное переключение | [#513](https://github.com/areatu/SonoForge/pull/513) | `02c4703` |
| [#514](https://github.com/areatu/SonoForge/issues/514) | S-02b: FPS-правки и strain | [#515](https://github.com/areatu/SonoForge/pull/515) | `ed42443` |
| [#516](https://github.com/areatu/SonoForge/issues/516) | QH-0: characterization harness | [#517](https://github.com/areatu/SonoForge/pull/517) | `38af151` |
| [#518](https://github.com/areatu/SonoForge/issues/518) | S-03: `StudySelection` | [#519](https://github.com/areatu/SonoForge/pull/519) | `bb8d186` |
| [#524](https://github.com/areatu/SonoForge/issues/524) | A3: zoom/pan-владелец | [#525](https://github.com/areatu/SonoForge/pull/525) | `e65e790` |

Проверка: `gh pr view <N> --json state,mergedAt,mergeCommit` для каждого PR; все шесть PR — `MERGED`, их merge-коммиты входят в `main`.

## Что сделано

- #510, #512, #516, #518, #524 закрываются этим PR как выполненные; в PR перечислены evidence-ссылки.
- #514 закрывается как выполненный S-02b. Его единственный незакрытый вопрос — сохранять ли ручную FPS-правку в запись измерения — вынесен в отдельный [#539](https://github.com/areatu/SonoForge/issues/539) с тремя вариантами (view-only, запись измерения, сессионный снимок), границей «код/DTO не меняются до решения» и критериями приёмки.
- В [аудите](2026-11-12-post-six-stages-audit-ru.md) добавлен статус P2.4; в [плане после S-03](2026-11-12-future-work-plan-after-s03-ru.md) и [исходном плане](2026-11-12-future-work-plan-ru.md) ссылка на открытый вопрос переведена с #514 на #539.

## Состояние трекера после слияния

- Закрыты: #510, #512, #514, #516, #518, #524, #538.
- Остаётся открытым по этой теме только #539 — решение владельца о FPS-правке.
- #539 не блокирует текущий код: S-02b уже закрепил RAM-поведение, а FPS остаётся просмотровой настройкой с файловым таймбазом для измерений, Auto-HR, фазовой шкалы и MP4-экспорта (`test_frame_time_override.py`).

## Ограничения

- Только трекер и документация; тесты поведения, ratchet'ы и код не менялись.
- Закрытие issues выполнено через `Closes #…` в PR: приложение не имеет права закрывать или редактировать issues напрямую (`Resource not accessible by integration`).
- Нативная GUI-приёмка, реальные PACS и клиническая валидация не относятся к этому изменению и не выполнялись.
