# Анализ спек `docs/superpowers/specs`: что реализовано, что осталось, от чего отказаться

**Дата:** 2026-10-14
**База:** `main` @ `958eed4` (PR #190), 55 файлов в `docs/superpowers/specs/`
**Метод:** сверка «спека → код → тест → PR/CHANGELOG» (не по шапкам документов: статусы в них
устарели). Дополнительно использованы `ROADMAP.md`, `CHANGELOG.md` (включая `v0.3.3 — unreleased`),
`docs/reviews/*`, список PR #1–#190 и GitHub-трекер QH (issues #171–#189).

> Документ отвечает на три вопроса: что уже сделано (и это надо закрыть формально), что стоит
> реализовать (и в каком порядке), от чего отказаться или что переписать. Он не меняет ни одну
> спеку и не объявляет клинических выводов: оценки — инженерные, по коду и артефактам.

---

## 0. Главные выводы

1. **Из 55 спеков 40 можно закрыть как реализованные.** Июнь–августовские спеки (viewer,
   измерения, MBS/Simpson, STE, DICOMweb/DIMSE, перфоманс, калибровки, справочник, допплер-сосуды,
   память) на сегодня **полностью покрыты кодом**; несоответствие только в шапках документов,
   которые остались на статусах «Draft / не начато».
2. **Единственный действительно живой многошаговый план — QH** (спека `2026-10-13`). Он уже выведен
   в GitHub Projects (19 epic-issues #171–#189, 8 milestones, 15 labels); закрыто 7 пакетов из 19,
   ещё 4 — `PARTIAL`, 3 — `BLOCKED` внешними предпосылками, 5 не начаты. Начинать новые крупные спеки до закрытия G1/G2 (data safety + transport) смысла нет:
   QH прямо запрещает смешивать новые фичи с верификационными срезами.
3. **Частично реализованы 9 спеков.** У восьми из них остаток — это либо внешние данные (gold/STE,
   Tier-1 bench ≥50 исследований), либо owner-only прогоны (Windows acceptance, 4K, правила
   rulesets, подпись), либо срезы, явно вынесенные в QH (`WP4.1` → QH-1c/1d, multiview stage 4 → QH-3).
4. **Отказаться предлагается от трёх вещей:** NELAFO (research-концепт без данных и команды),
   GPU-пути из `viewer-performance` (перекрыт дешёвыми оптимизациями: 30 FPS 720p, LUT-кэш,
   adaptive FrameCache, prefetch) и `MeasurementWorksheet` из `echopac-worksheet`
   (UI ушёл в `MeasuresMenuWidget` + `MeasurementToolsPanel`; модуль в окно так и не подключён).
   Плюс технический дубль `2026-08-03-vessels-measurements.md`.
5. **Что стоит реализовать после QH** (ничего из этого не противоречит QH, но и не входит в него):
   – Э10 этап 4 — измерительные инструменты в панелях multiview (спека multiview §10.2–10.3);
   – оставшийся реестр N-01…N-10 из дорожной карты 2026-10-02 (PHI-политика целиком, запуск из
   Проводника, установщик/подпись, реестр горячих клавиш, Windows/macOS GUI-smoke, CSV/JSON-экспорт,
   2D|Doppler-переключатель);
   – backl-задачи LV/LA-auto (fixed train mean/std v1.1, A2C auto, validation gate ±3%).
6. **Документальная гигиена дешевле любой фичи и даёт больше всего пользы сейчас:** устаревшие
   статусы в шапках, неразрешающиеся ссылки на `docs/superpowers/plans/` (каталог в `.gitignore`),
   `ROADMAP.md` последний раз обновлён 2026-07-18, статус-снапшоты не помечены как исторические.

---

## 1. Сводная таблица (все 55 спеков)

Легенда: **✅ реализовано** · **🟡 частично** · **⛔ не начато** · **⚫ закрыто/не делать** (superseded,
дубль, отменено) · **📄 не план** (журнал, снапшот, ревью).

### Июнь 2026 — viewer, измерения, STE

| # | Спека | Статус | Факт / evidence | Вердикт |
|---|-------|--------|-----------------|---------|
| 1 | `2026-06-11-dicom-performance-design` | ✅ | `application/frame_cache.py`, `infrastructure/dicom_session.py`, decode-on-open, `bench/cine720/*` | закрыть |
| 2 | `2026-06-11-display-ux-design` | ✅ | `local_browser._instance_label` (имя файла, не SOP-UID), `pixel_utils` (RGB-кадры), W/L + slider DR (`dr_percentiles_from_slider`) | закрыть; отдельной поддержки PALETTE COLOR в коде не найдено — низкий приоритет, проверить нужность |
| 3 | `2026-06-12-mbs-lite-design` | ✅ | `mbs_lite_service.py`, контур `source="model"`, Simpson-конвейер | закрыть |
| 4 | `2026-06-12-simpson-dual-workflow-design` | ✅ | ручной Simpson + MBS, blink-переходы ES, D/S-маркеры удалены | закрыть |
| 5 | `2026-06-13-mbs-advanced-design` | ✅ | R-refine opt-in, синусоидальный домен → Lamé | закрыть |
| 6 | `2026-06-13-preview-thumbnail-priority-design` | ✅ | `application/thumbnail_scheduler.py` (P0/P1/P2) | закрыть |
| 7 | `2026-06-13-rbf-contour-deform-design` | ✅ | RBF-деформация в `contour_geometry.py`, `contour_edge_snap.py` | закрыть |
| 8 | `2026-06-14-echopac-worksheet-design` | ⚫ | SystemBar сделан; `measurement_worksheet.py` существует, но в `MainWindow` не подключён (ROADMAP `[~]`); реальный UI — `MeasuresMenuWidget` + `MeasurementToolsPanel` | **закрыть как superseded**, модуль-сироту либо удалить, либо пометить legacy |
| 9 | `2026-06-14-lv-lame-template-design` | ✅ | Lamé-шаблон в конвейере MBS (`app_controller`), ROADMAP `[x]` | закрыть |
| 10 | `2026-06-19-measurement-workflow-design` | ✅ | `rwt.py`, `planimeter.py`, `SPLINE_AREA/VOLUME`, open-arc LAV/RAV | закрыть |
| 11 | `2026-06-19-onnx-lv-auto-segment-design` | 🟡 | v1/v1.5 ✅ (A4C ONNX, papillary cleanup, review UX); **не сделано:** v1.1 fixed train mean/std, A2C auto v2, validation gate ±3% LVEF | закрыть v1-часть; остатки перенести в backl-список (§3.4) |
| 12 | `2026-06-22-rv-fac-design` | ✅ | `rv_fac.py`, кнопка FAC | закрыть |
| 13 | `2026-06-23-dicomweb-orthanc-design` | ✅ | `orthanc_client`, `OrthancSessionCache`, диалог, cancel, STOW-RS; + DIMSE | закрыть |
| 14 | `2026-06-25-nelafo-speckle-tracking-design` | ⛔ | в коде нет ни одного упоминания (`nelafo` не встречается) | **отказаться/в research-бэклог** (§3.5) |
| 15 | `2026-06-27-ste-clinical-parity-design` | ✅ | STE фазы 5–11, GLS, AHA-17, кривые, QC, EACVI/ASE, фантом, реальные клипы | закрыть |
| 16 | `2026-06-29-dicom-scroll-performance-design` | ✅ | batch-load, decode gate, per-frame decoding (PR #72) | закрыть |
| 17 | `2026-06-29-playback-prefetch-design` | ✅ | prefetch-конвейер, 720p → 30 FPS (PR #65) | закрыть |
| 18 | `2026-06-30-customize-layout-spec` | ✅ | `LayoutConfig` (5 режимов), меню layout, сохранение в QSettings (multiview — session-only) | закрыть |

### Июль 2026

| # | Спека | Статус | Факт / evidence | Вердикт |
|---|-------|--------|-----------------|---------|
| 19 | `2026-07-02-viewer-performance-design` | ⚫ 🟡 | сделаны LUT-кэш и per-frame оптимизации; GPU-путь W/L не реализован и не нужен при текущих SLO | **закрыть как superseded**, оставить пункт «W/L latency» в бенч-бэклоге |
| 20 | `2026-07-04-dimse-phase2-design` | ✅ | `dimse_client.c_get_instance/c_move_instances`, embedded Storage SCP, TLS, `DicomRetrieveService` | закрыть |
| 21 | `2026-07-04-micro-ux-design` | ✅ | Inter, fade, hover lerp, focus ring, loading state; Darcula — cancelled по ROADMAP | закрыть |
| 22 | `2026-07-05-lv-auto-onnx-quality-design` | ✅ | ROI, adaptive Otsu, per-frame preprocessing, papillary post-process | закрыть |
| 23 | `2026-07-05-lv-auto-temporal-fusion-design` | ✅ | `domain/services/lv_temporal_fusion.py` (N±2, mask vote, clamp) | закрыть |
| 24 | `2026-07-06-la-auto-segmentation-design` | ✅ | `la_segmentation_service.py`, `scripts/finetune_la_seg.py`, `run_la_auto_bench.py`, контур + quality gate | закрыть |
| 25 | `2026-07-06-lv-auto-commercial-parity-design` | 🟡 | конвейер v2 и gates реализованы (`bench_metrics.py`: IoU, reject gate, zero-edit); Tier-1 (≥50 DICOM) числа не закрыты — нет данных | **data-blocked**: оставить как протокол измерения, не «план работ» |
| 26 | `2026-07-08-lv-mv-bench-v21-design` | 🟡 | MA ONNX (`ma_landmark_224.onnx`, `scripts/train_ma_landmark.py`), bench-метрики annulus; Gate C′ (light-edit) отложен автором в v2.1.1 | закрыть, оставив C′ в backl-списке |
| 27 | `2026-07-09-structured-reference-browser-design` | ✅ | `AseReferenceDialog` + структурная вкладка | закрыть |
| 28 | `2026-07-13-reference-constructor-design` | ✅ | конструктор, YAML + JSON-schema, импорт Excel, экспорт PDF/HTML | закрыть |
| 29 | `2026-07-15-anatomical-mmode-design` | ✅ | `mmode_scan_line.py`, `mmode_widget.py`, `mmode_extractor.py`, калиперы | закрыть |
| 30 | `2026-07-23-heart-rate-estimation` | ✅ | `heart_rate.py`, `workers/heart_rate_worker.py`, UI-кнопка | закрыть (сам документ и говорит «базовый набор») |
| 31 | `2026-07-31-doppler-calibration-fix` | ✅ | исправлены ключи тегов, знаковый ΔY, авто- и ручная калибровка, wizard | закрыть; статус `[~]` в шапке устарел |
| 32 | `2026-07-31-mmode-calibration-fix` | ✅ | `depth_from_dicom_tags`/`time_from_dicom_tags`, partial-состояние, FrameTime-fallback | закрыть; шапка `[ ]` противоречит коду |

### Август 2026

| # | Спека | Статус | Факт / evidence | Вердикт |
|---|-------|--------|-----------------|---------|
| 33 | `2026-08-01-maximum-calibration-design` | ✅ | разбиение M-mode на depth/time, 5-уровневая цепочка fallback, баннер с источником | закрыть |
| 34 | `2026-08-02-carotid-doppler-tags-design` | ✅ | `velocity_per_pixel_cm_s`, `baseline = MinY0 + ReferencePixelY0`, `time_origin_ms`, тесты в `test_dicom_doppler_calibration.py` | закрыть; шапка «проект» устарела |
| 35 | `2026-08-03-vessels-measurements-design` | ✅ | `VesselMeasurement`, PSV/EDV, RI/S-D, stenosis-diameter/area, пресеты | закрыть |
| 36 | `2026-08-03-vessels-measurements` (без `-design`) | ⚫ | ранняя версия той же спеки | **удалить/слить** (дубль) |
| 37 | `2026-08-04-aotutrace-doppler` | ✅ | auto-trace up/down, пресеты чувствительности, ручная правка огибающей | закрыть |
| 38 | `2026-08-05-vessel-cycle-averaging-design` | ✅ | `multi_beat_average.py` (median, ECG-free), кнопка «Усреднить 3 цикла» | закрыть |
| 39 | `2026-08-06-trace-doppler-metrics` | ✅ | `doppler_metrics.py`: Vpeak/Vmean/PGpeak/PGmean из трассы, `mean(v²)` вместо `mean(v)²` | закрыть |
| 40 | `2026-08-07-memory-optim-spec` | ✅ | adaptive budget 8 % RAM (`app_controller`), LRU-эвикция, async `release_stale_sessions` (PR #40/#43/#49) | закрыть |
| 41 | `2026-08-11-samsung-calibration-fixes-design` | ✅ | `samsung_calibration_builder.py`, `vendor_calibration_bridge.py`, 2-click velocity wizard (PR #42, #71) | закрыть |
| 42 | `2026-08-11-samsung-tick-calibration-design` | ✅ | `samsung_tick_detector.py`, `samsung_tick_calibration.json`, `tests/test_samsung_tick_calibration.py` | закрыть |
| 43 | `2026-08-16-reference-redesign-design` | ✅ | PR #53 «redesign reference editor with gradation tables», PR #55 web-based reference viewer | закрыть |

### Октябрь 2026 — persistence, вкладки, предрелиз, QH

| # | Спека | Статус | Факт / evidence | Вердикт |
|---|-------|--------|-----------------|---------|
| 44 | `2026-10-01-multiview-two-clips-spec-ru` | 🟡 | этапы 0–3 ✅ (панели, транспорт, маркеры, режимы синхронизации, бейджи, genera-контракт QH-1a.2); **этап 4** (инструменты в панелях) ⛔ — ворота явно отказывают | оставить живой: этап 4 = часть QH-3 |
| 45 | `2026-10-01-persistence-packaging-security-plan` | 🟡 | WP1 (installer), WP2 (paths/migration), WP3 (managed persistence) ✅ (PR #105/#109); WP4 — «поздние фазы» → QH-1c/1d | закрыть WP1–3, WP4 вести в QH |
| 46 | `2026-10-02-ui-data-doppler-roadmap-ru` | 🟡 📄 | Э1–Э12 в основном выполнены (Э9 ✅, Э10 этап 1 ✅, Э8 ✅, Э11 ✅, Э12 ✅); открыт реестр N-01…N-10 (кроме N-07) | **обновить статусы в файле или объявить журналом**; N-* → отдельный backlog/tracker |
| 47 | `2026-10-03-wp4-1-measurement-persistence-spec-ru` | 🟡 | ядро ✅ (schema v1→v4, atomic write, OS lock, delete/import, manual inputs, BSA provenance); остаток — QH-1b.2/1c/1d | оставить живой как контракт; закрыть вместе с G1 |
| 48 | `2026-10-03-wp4-2-patient-metrics-spec-ru` | ✅ | height/weight в снапшоте, origin, границы, индексные производные | закрыть |
| 49 | `2026-10-03-wp4-cache-compatibility-review-ru` | 📄 | ревью-снапшот; переработан в `docs/persistence-native-acceptance-d1-d4.md` | архив (пометить «исторический») |
| 50 | `2026-10-04-orthanc-loader-ux-ru` | ✅ | PR #112 (карточки, миниатюры, мастер-деталь, история пациента), дальнейшее — PR #93/#95 | закрыть |
| 51 | `2026-10-05-status-manual-testing-next-steps-ru` | 📄 | статус-снапшот; большая часть пунктов закрыта в v0.3.2/v0.3.3 | архив; ссылаться на `docs/reviews/*` новее |
| 52 | `2026-10-07-tabs-start-page-spec-ru` | ✅ | Э9/Э5/Э10 реализованы (приветственная страница в пустой вкладке, недавние исследования, восстановление кадра/W-L, drag/контекстное меню вкладок, сравнение из двух вкладок); плюс QH-1a.1/1a.2 | закрыть |
| 53 | `2026-10-08-wp4-windows-acceptance-checklist-ru` | 🟡 | D1–D6 (taskkill, два процесса, ACL, битый JSON) — PASS в `docs/persistence-native-acceptance-d1-d4.md`; P1–P7 (Presenter/USB/read-only) и полная приёмка — за владельцем | **owner-run**, не кодовая работа |
| 54 | `2026-10-09-pre-release-ui-fixes-spec-ru` | ✅ | Ф1–Ф9 в v0.3.2; замечания аудита 2026-10-11 (§1.1–1.4, 2.1–2.2) закрыты в цикле v0.3.3 — `fix(start-page)`, `feat(tabs)`, `feat(multiview)` в разделе `v0.3.3 — unreleased` | закрыть |
| 55 | `2026-10-13-quality-safety-hardening-spec-plan-ru` | 🟡 | живой план, 6/19 пакетов закрыто, G0/G1-STE и остатки — по трекеру issue #171–#189 | **единственный план, который стоит вести дальше** |

---

## 2. Единственный живой план — QH: что именно осталось

Состояние выверено по GitHub-трекеру (issues #171–#189) и срезам в `docs/reviews/2026-10-14-*`.

| Пакет | Issue | Состояние | Следующий шаг |
|---|---|---|---|
| QH-0 baseline | #171 ✅ | закрыт | — |
| QH-1a.1 reader | #172 ✅ | закрыт | — |
| QH-1a.2 Э10 ownership | #173 ✅ | закрыт | — |
| QH-1b.1 provenance DTO/v3 | #174 ✅ | закрыт | — |
| **QH-1b.2** invalidation per-result + freshness projection | #175 | PARTIAL (2 среза: BSA freshness + единый ППТ) | **P0**: persisted derived results, инвалидация по ревизиям входов, одна проекция UI/текст/PDF |
| **QH-1c** delete/barriers/import | #176 | PARTIAL | hash-remap moved non-DICOM, directory-fsync, native fault harness |
| **QH-1d** manual inputs | #177 | PARTIAL | остальные ручные входы по allowlist, persisted derived results, provenance в UI |
| QH-1e формулы | #178 ✅ | закрыт (111 synthetic cases, 29 required) | — |
| QH-1e-STE same-frame gold | #179 | 🔒 BLOCKED | нужны gold-контуры ED/landmarks и определения вендора |
| QH-2a.1 locked CI | #180 ✅ | закрыт | — |
| **QH-2a.2** policy/rulesets | #181 | 🔒 BLOCKED | подтверждение администратором репозитория |
| QH-2b.1 transport evaluator | #182 ✅ | закрыт | — |
| **QH-2b.2** enforcement в клиентах | #183 | ⛔ не начат, помечен `p0` | Orthanc-клиент, DIMSE-клиент, диалог настроек, миграция профилей, тест «0 сетевых запросов» |
| **QH-3.1 / 3.2** ViewerWidget → композиция | #184/#185 | ⛔ не начат | ViewerContext/commands + pilot; затем tools → contours → calibration/workers |
| **QH-4a** остаток register | #186 | PARTIAL (ER-07…ER-12, producer allowlist, raw crash/log privacy) | адресно рядом с изменяемыми сценариями |
| **QH-4b** boundary ratchet | #187 | ⛔ не начат | ноль прямых domain→infrastructure |
| **QH-5a** packaged release | #188 | ⛔ не начат | locked package matrix, clean-machine smoke, manifests |
| QH-5b signing | #189 | 🔒 BLOCKED | провайдер/сертификаты/approval |

**Вывод по QH:** план не «расползается», а честно доходит до внешних предпосылок. Три пакета
реально блокированы снаружи (gold, админ, сертификаты) — их нельзя закрыть кодом. Остальные
(QH-1b.2, 1c, 1d, 2b.2, 3.x, 4a/4b, 5a) — это очередь работ на несколько итераций.

---

## 3. Что стоит реализовать (кроме QH) и почему

### 3.1. Э10 этап 4 — измерительные инструменты в панелях multiview

Спека `2026-10-01-multiview-two-clips-spec-ru` §10.2–10.3 формально требует: инструменты работают
только в активной панели, геометрия принадлежит `Study + Series + SOP + frame`, LV-auto не угадывает
цель, при переключении клипа незавершённая геометрия не переносится. Сейчас ворота корректно
**отказывают** — это «безопасно, но неполно». Реализация требует pane-scoped состояния, то есть
того же рефакторинга, что в QH-3. **Рекомендация:** не открывать отдельную спеку, а привязать к
QH-3.1/3.2 (как и предлагает QH §7).

### 3.2. Реестр N-01…N-10 из дорожной карты 2026-10-02 (кроме закрытого N-07)

| ID | Тема | Текущее состояние в коде |
|---|---|---|
| N-01 | PHI-политика целиком | частично: N-07 (Presenter), `phi_mask`, деидентификация экспорта, sanitizer. Единого реестра «где ФИО допустима» нет |
| N-03 | Запуск из Проводника | нет: `main()` понимает только `--version`/`-V`, нет одного экземпляра/Jump List |
| N-04 | Установка и старт | частично: installer есть (WP1), подписи нет (QH-5b), onedir/скорость старта onefile не решены |
| N-05 | Единый реестр горячих клавиш | registry есть (#150), переназначения пользователем и разрешения конфликтов нет |
| N-06 | Тесты и CI | частично: locked CI, required manifests, coverage; Windows/macOS GUI-smoke и допплер-фикстуры отсутствуют |
| N-08 | Рефакторинг перед фичами | первый срез (#152 + координаторы), остальное — в QH-3 |
| N-09 | Доступность, HELP, экспорт | HELP RU/EN есть; CSV/JSON-экспорт измерений и 2D \| Doppler-переключатель не реализованы (проверено в `system_bar.py` и по коду отчётов) |
| N-10 | RUO-позиция | частично: формулировки и источники в HELP/README есть, формального «preview-режима» расчётов нет |

**Рекомендация:** завести один трекер-файл `.github/tracker/backlog.yml` (движок
`project_sync.py` уже план-агностичен, см. §5.1 трекер-ревью) и перенести туда N-01, N-03…N-06,
N-09, N-10 — вместо того чтобы держать их в 105-КБ дорожной карте со снятыми статусами.

### 3.3. Owner-run приёмки (код готов, нужен прогон)

- `2026-10-08-wp4-windows-acceptance-checklist-ru`: P1–P7 (Presenter/USB/read-only) + полная
  приёмка WP4 на Windows 10/11 1920×1080 — от неё зависит перевод автосохранения в default-on.
- 4K/масштаб (Э4): подтверждение на реальном мониторе пользователя.
- Rulesets/branch protection (QH-2a.2, issue #181).
- STE same-frame gold (QH-1e-STE, issue #179) и Tier-1 bench ≥50 исследований (Gates A/C из
  `2026-07-06-lv-auto-commercial-parity`) — без данных любые «PASS» будут синтетическими.

### 3.4. Функциональный бэклог LV/LA-auto (мелкий, не блокирует безопасность)

- v1.1 fixed train mean/std (ROADMAP: отложено);
- A2C auto (отдельная модель/transfer; кнопки biplane сейчас ручные — это ожидаемо, не дефект);
- AI validation gate ±3 % LVEF — станет осмысленным после появления Tier-1 данных;
- Gate C′ light-edit из `2026-07-08-lv-mv-bench-v21` (сам автор отложил в v2.1.1).

---

## 4. От чего предлагается отказаться или что закрыть формально

| Что | Почему | Действие |
|---|---|---|
| **NELAFO** (`2026-06-25`) | research-концепт (neural operator + flow matching) без данных, тренеров и плана валидации; в коде нет ни строки. При нынешнем контуре (один разработчик + агент) это неисполнимо и отвлекает от G1/G2 | помечать `cancelled/research-backlog` в шапке; не планировать в продуктовые волны |
| **GPU-путь viewer-performance** (`2026-07-02`) | исходная мотивация (5–20 мс W/L, ~100 мс scroll) закрыта другими средствами: per-frame decoding, LUT-кэш, adaptive budget, 30 FPS 720p | закрыть как superseded; держать только измеримый SLO в бенч-бэклоге |
| **`MeasurementWorksheet`** (`2026-06-14-echopac-worksheet`) | UI-потребность закрыта другими виджетами; модуль висит неподключённым, риск «двух UI» | закрыть спеку; модуль — либо удалить, либо явно пометить legacy с тестом на отсутствие импортов |
| **`2026-08-03-vessels-measurements.md`** | дубль (ранняя версия `-design`) | удалить, оставив одну спеку |
| **Darcula/palette migration** (`2026-07-04-micro-ux`) | уже помечено cancelled в ROADMAP | оставить как есть |
| **Закрепление/переименование вкладок, «закрепление клипа»** (решения D-29/D-30 в `2026-10-07-tabs-start-page-spec-ru`) | вердикт владельца: «не нужны»; закрепление отложено «если понадобится» | закрыть явной строкой в спеке, чтобы не всплывало в новых планах |

---

## 5. Документальная гигиена (дешево, снимает половину путаницы)

1. **Шапки спеков врут.** Примеры: `2026-07-31-mmode-calibration-fix` — «`[ ]` не начато» при
   реализованном коде; `2026-08-02-carotid` — «проект»; `2026-07-31-doppler-calibration-fix` —
   «`[~]` в реализации»; `2026-10-02-roadmap` — «реализация не начата» при закрытых Э1–Э12.
   Предложение: в каждой закрываемой спеке одну строку `**Закрыто:** 2026-10-14, PR #N`
   (партия из одного PR с правками 40 шапок).
2. **Ссылки на `docs/superpowers/plans/` не разрешаются в репозитории.** Каталог намеренно не
   поставляется (`.gitignore`: «Internal dev plans and specs (not shipped)»), но `ROADMAP.md`
   (§3 и §Ссылки) обещает его как место планов, а 13 спеков ссылаются на конкретные файлы
   (`../plans/2026-06-29-dicom-mp4-lazy-loading.md`, `2026-06-30-ui-enhancement.md`,
   `2026-07-02-dimse-stow-rs-implementation.md`, `2026-08-07-memory-optim.md`,
   `doppler-calibration-overhaul.md`, планы LV/LA-auto и др.). Предложение: пометить ссылки
   «(внутренний план, не входит в репозиторий)» или переписать на `specs/` + `reviews/`.
3. **`ROADMAP.md` устарел** (шапка «Обновлено 2026-07-18», тогда как август–октябрь закрыты).
   Варианты: (а) обновить и сверить с этой таблицей; (б) объявить архивом и перенести статус в
   GitHub Projects (движок синхронизации уже есть).
4. **Статус-снапшоты и ревью** (`2026-10-03-wp4-cache-compatibility-review`,
   `2026-10-05-status-manual-testing-next-steps`, `2026-10-11-recent-prs-implementation-audit`)
   пометить «Исторический документ, актуальный статус — `docs/reviews/` новее» — иначе их читают
   как текущее состояние.
5. **Triage-правило на будущее** (предложение): спека живёт ровно до того PR, который её закрыл;
   после — переносится в `docs/superpowers/specs/archive/` либо получает строку `Закрыто`.

---

## 6. Предлагаемый порядок работ

**Волна 0 (сейчас, дешево).** Пакет правок документации из §5: шапки, дубль, мёртвые ссылки,
статус ROADMAP. Отдельно — вынести N-01…N-10 в трекер.

**Волна 1 (P0, data safety).** Закрыть G1: QH-1b.2 (инвалидация per-result + единая проекция
UI/текст/PDF), QH-1c остаток (hash-remap, directory-fsync, fault harness), QH-1d остаток
(persisted derived results, provenance в UI). Параллельно, если есть ресурс — QH-2b.2
(enforcement транспортной политики в клиентах, issue #183 помечен `p0`).

**Волна 2 (P1, архитектура).** QH-3.1 → QH-3.2 (ViewerContext, композиция ViewerWidget), к ним
же Э10 этап 4 (инструменты в панелях). Без этой волны multiview остаётся «просмотрщиком без
измерений», а `ViewerWidget` продолжает расти.

**Волна 3 (P1/P2).** QH-4a остаток и QH-4b (границы domain), затем QH-5a (locked package matrix,
clean-machine smoke, manifests).

**Параллельно, вне кода:** owner-run приёмки (§3.3) и внешние предпосылки (gold, rulesets,
certificates) — их старт не зависит от рефакторингов и стоит начинать немедленно.

**Чего не делать сейчас:** новых крупных продуктовых спеков (AI-assist, NELAFO, auto-update,
сетевые хранилища) до закрытия G1/G2 — QH §3.2 прямо выносит их за скобки, а незакрытые
S-инварианты сидят ровно на клинической достоверности чисел.

---

## 7. Ограничения этого анализа

- Статусы выставлены по коду, PR, CHANGELOG и трекеру; **клиническая пригодность и native-прогоны
  не проверялись** — там, где нужны данные/стенд, стоит маркер «data-blocked»/«owner-run».
- Для «✅ реализовано» проверялось наличие и связность кода (модуль есть, вызывается из UI,
  покрыт тестами по имени файла); полнота edge-case'ов сверялась только там, где это было
  критично (калибровки, persistence, multiview).
- Оценки объёма («S/M/L») взяты из QH-спеки и трекера, а не пересчитаны.

---

## 8. Ссылки

- Спеки: `docs/superpowers/specs/` (55 файлов)
- Живой план: `2026-10-13-quality-safety-hardening-spec-plan-ru.md` + `.github/tracker/qh-plan.yml`
- Ревью-срезы QH: `docs/reviews/2026-10-13-*`, `docs/reviews/2026-10-14-*`
- Аудит предрелизных PR: `docs/reviews/2026-10-11-recent-prs-implementation-audit-ru.md`
- Native-приёмка WP4: `docs/persistence-native-acceptance-d1-d4.md`
- Трекер: issues [#171–#189](https://github.com/areatu/SonoForge/issues)
