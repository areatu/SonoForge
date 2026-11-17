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
| [2026-11](changelog/2026-11.md) | 2 | v0.4.1 — 2026-11-16 |
| [2026-10](changelog/2026-10.md) | 2 | v0.3.3 — 2026-10-15 |
| [2026-09](changelog/2026-09.md) | 19 | v0.3.1 — 2026-09-27 |
| [2026-08](changelog/2026-08.md) | 19 | 2026-08-23 |
| [2026-07](changelog/2026-07.md) | 24 | 2026-07-31 |
| [2026-06](changelog/2026-06.md) | 17 | 2026-06-30 |

---

## Unreleased

- `fix(mmode)`: происхождение ручной калибровки (#547) и opt-in диагностика памяти/очередей (#553/#545) ([полностью](changelog.d/010-fix-mmode-provenance-547.md))
- `fix(ui)`: 2026-11-17 — Tab-цепочка диалога «Загрузка с сервера» реально применяется: вызов `setTabOrder` перенесён из середины сборки в её конец, иначе Qt молча игнорировал цепочку ([полностью](changelog.d/009-fix-ui-pacs-tab-chain.md))
- `feat(ui)`: 2026-11-17 — произвольная дата в диалоге «Загрузка с сервера»: чип «Дата» и селектор «День · Месяц · Год», клиентский фильтр плюс `study_date` в запросе ([полностью](changelog.d/008-feat-ui-pacs-exact-date.md))
- `fix(ui)`: 2026-11-17 — разная высота кириллических букв и бахрома ClearType: полный хинтинг заменён на `PreferNoHinting`, подписи поверх кадра переведены на bundled Inter в px ([полностью](changelog.d/007-fix-ui-cyrillic-hinting.md))
- `perf(viewer)`: лаг при первом нажатии Z (лупа) убран прогревом линзы в простое после первого показа ([полностью](changelog.d/006-perf-viewer-loupe-warmup.md))
- `feat(report)`: UI-батч из 8 пунктов кардиолога: плотные две колонки без белых полос, s′ ПЖ и dP/dt в отчёте, дисплейные имена peak-калиперов, provenance калиперов и dP/dt, Dist1…Dist5 убраны ([полностью](changelog.d/005-feat-report-ui-batch-8-items.md))
- `feat(doppler)`: dP/dt МР/ТК — направляющие 1 м/с и 3 м/с (ТК 2 м/с), кроссхэйр по направляющей, Δt из двух кликов, результат в overlay и отчёт ([полностью](changelog.d/005-feat-doppler-dpdt-guides.md))
- `feat(ctmr)`: #557 — header-only classic CT/MR stack index с patient-space порядком ([полностью](changelog.d/005-feat-ctmr-stack-index-557.md))

- `feat(imt)`: #558 — редактируемый research overlay двух границ и документ v7 ([полностью](changelog.d/004-feat-imt-viewer-document-558.md))
- `feat(imt)`: #558 — исследовательское ядро seeded КИМ, физические нормали и draft/QC workflow; без GUI-интеграции ([полностью](changelog.d/003-feat-imt-research-core-558.md))
- `refactor(analysis)`: #552 — владелец публикации STE и защита от устаревших success/error ([полностью](changelog.d/002-refactor-analysis-ownership-552.md))
- `fix(decode)`: #553 — приёмка очередей и отмены: caps входящего prefetch и bounded full-decode futures ([полностью](changelog.d/001-fix-decode-cancellation-553.md))


