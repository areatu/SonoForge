# ROADMAP — SonoForge

**Обновлено:** 2026-11-01 (S3-03, issue 312: сверка с кодом, разрезанный CHANGELOG, восстановленный
`docs/bench`). Предыдущая правка — 2026-10-25 (S1-05).

**Что это:** статус функций и план на три спринта вперёд.
**Чем это не является:** спецификацией (спеки — `docs/superpowers/specs/`), списком коммитов
(он в git log и в [`CHANGELOG.md`](CHANGELOG.md) + `changelog/`) и источником истины по числу
тестов — его держит гейт `update_pytest_baseline.py` в `.github/scripts/verify_pytest_partition.py`.

Легенда: `[x]` есть в коде и покрыто тестами · `[~]` частично · `[ ]` не начато / отложено ·
`[—]` **cancelled**.

---

## Текущее состояние (2026-11-01)

| Область | Факт |
|---|---|
| Версия | `0.3.3` (`src/echo_personal_tool/__init__.py`); последний тег — `v0.3.3` (2026-10-15), выпуск после него — из `Unreleased` |
| Рантайм | Python **3.11–3.13** (`>=3.11,<3.14`), PySide6 6.11.x, numpy **2.1+**, pydicom 3, scipy, OpenCV headless |
| Дистрибуция | PyInstaller: `.exe` / `.dmg` / AppImage + `.deb` (lite), CycloneDX 1.6 SBOM на каждый пакет, `SHA256SUMS`, `latest.json`; модели — отдельным релизом с закреплённым sha256 |
| Тесты | **9 522** (3 919 GUI, 5 603 логических) в 205 GUI-файлах; маркеры `gui`, `gui_smoke`, `security`, `acceptance`, `regression`, `migration` |
| Архитектура | `presentation → infrastructure` = **0 рёбер** (allowlist пуст), `domain → infrastructure` = 0; mypy strict на `domain`/`imaging`, relaxed-override на `application`/`infrastructure` |
| UI | Дизайн-токены (`presentation/theme/`), храповик цветовых литералов 190, реестр клавиш, режим «Отчёт», multiview, STE, M-mode |
| Отчёты | Режим «Отчёт» R3: лист A4, PDF-экспорт в worker (S3-04), печать, фиксация версии |

**Гейты CI, которые обязательны на каждом PR:** `lint` (ruff, mypy, архитектурные инварианты,
длина функций), `pytest counters gate`, `test-logic` (ubuntu 3.11/3.12/3.13 + windows 3.11),
`test-gui` (6 шардов), `test-gui-smoke` (windows/macos), `test-regression` + migration,
`test-security`, `test-acceptance`, `ui-colors`, `package-smoke`, CodeQL и audit зависимостей.

**Чего в продукте сознательно нет** (и это заявлено, а не забыто): audit trail, идентичность
оператора и роли, шифрование at-rest измерений/экспортов, DICOM SR и отчёт в PACS, worklist,
веб-сборка. Подробности — §9.2 аудита и issue 331.

---

## Ближайшие три спринта

### Спринт 3 аудита 2026-10-22 — закрыт (2026-11-01)

| # | Тема | Статус |
|---|---|---|
| S3-01 | Windows/macOS GUI-smoke и regression/migration в CI (issue 310) | [x] PR #399 |
| S3-02 | numpy 2, Python 3.12/3.13, пере-базлайн метрик (issue 311) | [x] PR #400 |
| S3-03 | `docs/bench`, ROADMAP, CHANGELOG по релизам (issue 312) | [x] этот PR |
| S3-04 | PDF-экспорт в worker, лимит пикселей, accessibility (issue 313) | [x] PR #401 |

### Спринт 4 — хвосты проверки 2026-10-25 (следующий)

Порядок — по цене ошибки для пользователя, а не по объёму:

1. **#326** — `runtime_setup.install_deps` ставит `cv2`/`yaml` (таких дистрибутивов нет на PyPI)
   и неполный набор; починка = разделить модули и дистрибутивы, сверка с `uv.lock`, честная ошибка.
2. **#325** — mypy-гейт: 297 подавлений (99 bare), отключены коды и `check_untyped_defs`.
3. **#327** — метрика тестов: 50 % кейсов с ≤1 assert, 486 без сигнала, ≥72 теста мёртвого кода.
4. **#329** — 763 ID-ссылки в 158 файлах `src`, 22 ссылки в пустоту, 7 битых ссылок.
5. **#328** — 7 циклов импорта, слой отчётов и справочника без направления (5 модулей в одном SCC).

### Спринт 5 — решения, а не код

1. **#331** — клинический путь: исследовательский инструмент или клиническое применение.
   Решение владельца открывает (или закрывает) identity/RBAC → audit trail → at-rest → SR/worklist.
   Реализацию trail не начинать до identity: событие без субъекта — не trail.
2. **#176** (QH-1c, `status:partial`), **#179** (QH-1e-STE), **#205** (TP-6), **#276** (UI-4 отчёт):
   добить частичные срезы, каждый — отдельным PR со своим evidence.
3. **#189 / #181** (`status:blocked`): внешние условия — подпись кода и policy администратора.

---

## Явные non-goals (на горизонте трёх спринтов)

- **Клиническая сертификация и регуляторика** — вне инженерного объёма; disclaimer в README остаётся.
- **Новые фичи в отчёте и STE** — до закрытия спринта 4 не начинаем: сначала честные гейты.
- **UI-редизайн** — только дефекты и accessibility, без смены системы дизайна.
- **Веб-сборка, плагины, multi-user сервер** — не планируются (см. `docs/web_build_architecture*`).
- **Ослабление гейтов ради скорости CI** — сокращать время прогона можно только без потери тестов.

---

## Хронология major changes (июнь–июль 2026)

### Июнь 2026

| Дата | Изменение | Статус |
|------|-----------|--------|
| 06-01 | **M-mode domain models** — `MModeScanLine`, `MModeState`, `MModeCaliperMeasurement` | [x] |
| 06-02 | **M-mode column extractor** — bilinear interpolation по scan line | [x] |
| 06-03 | **M-mode sweep display** — PyQtGraph panel с image buffer | [x] |
| 06-04 | **M-mode vertical splitter** — toggle layout в MainWindow | [x] |
| 06-05 | **M-mode extraction pipeline** — AppController + MainWindow wiring | [x] |
| 06-06 | **M-mode caliper tool** — distance/time measurements | [x] |
| 06-07 | **M-mode anatomical integration** — tests + DICOM calibration | [x] |
| 06-08 | **M-mode scan line tool** — draggable nodes на ViewBox | [x] |
| 06-09 | **M-mode status bar hints** — activation + scan line placement | [x] |
| 06-10 | **M-mode DICOM calibration** — vertical axis cm, horizontal ms | [x] |
| 06-11 | **M-mode close button** — × deactivates M-mode | [x] |
| 06-12 | **M-mode caliper UX** — preview first point, multiple calipers per session | [x] |
| 06-13 | **M-mode smart smoothing** — log compression + spatial Gaussian + temporal EMA | [x] |
| 06-14 | **M-mode measurement tools** — vertical (depth), horizontal (time), arbitrary с guide lines | [x] |
| 06-15 | **M-mode vertical lock** — toggle button + guide lines | [x] |
| 06-16 | **M-mode horizontal lock** — horizontal measurement с guide lines preview | [x] |
| 06-17 | **M-mode heart rate** — ЧСС в horizontal measurement label | [x] |
| 06-18 | **STE Phase 5** — Bull's Eye Plot (17-segment polar map) | [x] |
| 06-19 | **STE Phase 6** — Summary Table (clinical-style layout) | [x] |
| 06-20 | **STE Phase 7** — Strain Curves View | [x] |
| 06-21 | **STE Phase 8** — Display Mode Toggle (Deformation/SR/Peak) | [x] |
| 06-22 | **STE Phase 9** — Quality Control Checkboxes | [x] |
| 06-23 | **STE Phase 10** — Manual Kernel Correction | [x] |
| 06-24 | **STE Phase 11** — Save/Export Deformation Data | [x] |
| 06-25 | **STE fixes** — auto-load frames, QC checkboxes, critical blockers | [x] |
| 06-26 | **Gold store** — UI tab in preferences + ECHO_GOLD_EXPORT env var | [x] |
| 06-27 | **Gold UX** — per-frame instance_path, auto-update manifest, dedup | [x] |
| 06-28 | **Gold multi-DICOM** — per-instance dedup + multi-DICOM study support | [x] |
| 06-29 | **Gold annotation UX** — save/load gold contours with validation | [x] |
| 06-30 | **Bench** — LV auto-contour bench + annulus landmarks + gold tooling | [x] |
| 07-01 | **Bench** — MA landmark ONNX + baseline reports | [x] |
| 07-02 | **Bench** — LVEF reject gate, temporal smoothing, per-frame normalization | [x] |
| 07-03 | **LA auto** — gold UX + la_mask_to_contour + quality gate + LA-2 finetune | [x] |
| 07-04 | **ONNX fixes** — atexit shutdown, thread safety, per-instance WL/DR | [x] |
| 07-05 | **Segmentation fixes** — stuck + slow scroll + diagnostics | [x] |
| 07-06 | **Structured reference browser** — ASE reference в AseReferenceDialog | [x] |
| 07-07 | **Reference constructor** — visual editor для structured reference handbook | [x] |
| 07-08 | **Reference widget** — tables instead of cards, image scaling, gradation table | [x] |
| 07-09 | **Overlay** — color-coded out-of-range values + click-to-reference navigation | [x] |
| 07-10 | **M-mode depth calibration** — detected ticks (5cm intervals) вместо DICOM pixel spacing | [x] |
| 07-11 | **M-mode deactivate** — simplify by directly manipulating splitter | [x] |
| 07-12 | **M-mode expand/collapse animation** — smooth QPropertyAnimation + 50% taller panel | [x] |

### Июль 2026 — Cleanup & Release Prep

| Дата | Изменение | Статус |
|------|-----------|--------|
| 07-18 | **Project cleanup** — удаление debug-логов, old/, orphan-директорий, backup-файлов, кэшей | [x] |
| 07-18 | **Dependencies fix** — добавлены pyyaml, jsonschema; убран black; hatch version source | [x] |
| 07-18 | **Commercial names** — замена Standard/Research/Device/GE/Clinical на generic-названия | [x] |
| 07-18 | **Phase2 → required** — onnxruntime, reportlab, openpyxl теперь обязательные зависимости | [x] |
| 07-18 | **README update** — актуализация возможностей, требований, установки | [x] |

### Июль 2026 — New Features

| Дата | Изменение | Статус |
|------|-----------|--------|
| 07-18 | **Teichholz M-mode** — 3 последовательных калипера (МЖП→КДР→ЗСЛЖ) с chain-логикой | [x] |
| 07-18 | **Teichholz ESV** — измерение КСР после подсветки | [x] |
| 07-18 | **Teichholz results** — КДО, КСО, ФВ, ОТС, ММЛЖ, ИММЛЖ в overlay | [x] |

---

## Фаза 1 — MVP (viewer, ручные измерения)

- [x] Локальный скан DICOM/MP4, thumbnail gallery
- [x] 2D viewer (PyQtGraph), таймлайн, play/pause
- [x] Ручная калибровка B-mode (ввод **см**)
- [x] Линейные калиперы, study-wide session merge
- [x] LV Simpson manual (A4C/A2C, open-arc, Lamé)
- [x] LV 2D: All Diastole, ES Diameter → Тей-Хольц
- [x] ОТС (RWT) в snapshot и overlay
- [x] Doppler: пики, интервалы, VTI, mitral inflow workflow
- [x] M-mode калибровка времени/глубины
- [x] RBF-деформация контуров, magnetic snap, stepped R-refine (R)
- [x] Study overlay результатов (per-instance кэш + study-wide отчёт)

---

## Measurement workflow (спека 2026-06-19)

| # | Тема | Статус |
|---|------|--------|
| 1 | Калибровка в см | [x] `viewer_widget.py` |
| 2 | Blink «следующей» кнопки | [x] `MeasuresMenuWidget.highlight_action` |
| 3 | ОТС после All Diastole | [x] `rwt.py`, overlay |
| 4 | Общие → Площадь (замкнутый полигон) | [x] `planimeter.py`, `SPLINE_AREA` |
| 5 | Общие → Объём (замкнутый полигон → Simpson) | [x] `SPLINE_VOLUME` |
| 6 | LAV/RAV Simpson open-arc | [x] `chamber_simpson`, овальный шаблон `warp_elliptical_open_arc` |

---

## LV Auto ONNX (спека 2026-06-19)

| Фаза | Содержание | Статус |
|------|------------|--------|
| **v1** | A4C ONNX, papillary cleanup, review UX (Enter/Esc), hotkey I | [x] |
| **v1.1** | Фиксированные train mean/std | [ ] отложено |
| **v1.5** | Per-frame quality: MP4 ROI fix, DICOM sector trim, adaptive Otsu threshold | [x] |
| **v1.5+** | Temporal fusion: neighbor-aware contour (N±2), mask vote, node clamp | [x] |
| **v2** | A2C auto (отдельная модель / transfer) | [ ] «в следующей версии» |

- [x] Stepped border refine + edge snap для ai/manual
- [x] Lamé template только для `source=model` LV
- [ ] AI validation gate ±3% LVEF vs Standard (не release gate v1)

---

## M-Mode (июнь–июль 2026)

| Компонент | Описание | Статус |
|-----------|----------|--------|
| Domain models | `MModeScanLine`, `MModeState`, `MModeCaliperMeasurement` | [x] |
| Column extractor | Bilinear interpolation по scan line | [x] |
| Sweep display | PyQtGraph panel с image buffer | [x] |
| Vertical splitter | Toggle layout в MainWindow | [x] |
| DICOM calibration | Vertical axis cm, horizontal ms | [x] |
| Smart smoothing | Log compression + spatial Gaussian + temporal EMA | [x] |
| Measurement tools | Vertical (depth), horizontal (time), arbitrary с guide lines | [x] |
| Vertical lock | Toggle button + guide lines | [x] |
| Horizontal lock | Horizontal measurement с guide lines preview | [x] |
| Heart rate | ЧСС в horizontal measurement label | [x] |
| Expand/collapse animation | Smooth QPropertyAnimation + 50% taller panel | [x] |
| Teichholz ED | 3 sequential calipers (МЖП→КДР→ЗСЛЖ) с chain-логикой | [x] |
| Teichholz ESV | ESV measurement после подсветки | [x] |
| Teichholz results | КДО, КСО, ФВ, ОТС, ММЛЖ, ИММЛЖ в overlay | [x] |

---

## Speckle Tracking (STE)

| Фаза | Содержание | Статус |
|------|------------|--------|
| Phase 5 | Bull's Eye Plot (17-segment polar map) | [x] |
| Phase 6 | Summary Table (clinical-style layout) | [x] |
| Phase 7 | Strain Curves View | [x] |
| Phase 8 | Display Mode Toggle (Deformation/SR/Peak) | [x] |
| Phase 9 | Quality Control Checkboxes | [x] |
| Phase 10 | Manual Kernel Correction | [x] |
| Phase 11 | Save/Export Deformation Data | [x] |

- [x] NCC block-matching, bidirectional ED-anchored tracking
- [x] GLS, AHA 17 segments, strain curves, QC
- [x] Пресеты: `standard`, `research` (настраиваемые параметры)
- [x] Auto-load all frames перед tracking

---

## Clinical UI и отчёты

- [x] SystemBar, Measures accordion, ToolPanel (Controls)
- [x] Нормативы ASE (`ase_reference_dialog`)
- [x] **Structured reference browser** — интерактивный браузер с темами, патологиями, градациями, изображениями
- [x] **Reference constructor** — visual editor для structured reference handbook
- [x] **Overlay** — color-coded out-of-range values + click-to-reference navigation
- [x] Рост/вес, индексы BSA, LAVi/RAVi в overlay
- [x] Кнопка **Результаты** + PDF export
- [x] Устаревший `MeasurementWorksheet` удалён в S1-05; `ReportDialog` удалён как осиротевший (дрифт после S1-05) — активный отчёт: режим «Отчёт» (`presentation/report_mode/`) / структурированный PDF
- [ ] CSV / JSON export (`ReportService` из Этап2)
- [ ] 2D | Doppler layout toggle в SystemBar

---

## Gold Standard & Benchmarks

- [x] **Gold store** — UI tab in preferences + ECHO_GOLD_EXPORT env var
- [x] **Gold UX** — per-frame instance_path, auto-update manifest, dedup
- [x] **Gold multi-DICOM** — per-instance dedup + multi-DICOM study support
- [x] **Gold annotation UX** — save/load gold contours with validation
- [x] **Bench** — LV auto-contour bench + annulus landmarks + gold tooling
- [x] **Bench** — MA landmark ONNX + baseline reports
- [x] **Bench** — LVEF reject gate, temporal smoothing, per-frame normalization
- [x] **LA auto** — gold UX + la_mask_to_contour + quality gate + LA-2 finetune

---

## DICOMweb Orthanc (спека 2026-06-23)

- [x] QIDO-RS + WADO-RS через `OrthancDicomWebClient` (httpx)
- [x] Сессионный кэш `OrthancSessionCache`, очистка при выходе
- [x] Mock offline: `FakeDicomWebClient` + JSON/DICOM фикстуры
- [x] UI: `OrthancStudyDialog`, «Загрузить с сервера…», настройки сервера
- [x] Интеграция: `open_folder(study_path)` после загрузки
- [x] Cancel загрузки + очистка session cache
- [x] Суммарный progress-bar по всем выбранным сериям
- [x] QIDO `includefield`; парсинг `00201209` → «N инст.» в диалоге
- [ ] Workplace: реальные JSON-фикстуры с Orthanc

---

## DIMSE / STOW-RS (план 2026-07-02)

- [x] pynetdicom dep + DimseClient / DicomUploadClient ports
- [x] PynetdimseClient: c_echo, c_find (study/series/instances), c_store
- [x] FakeDimseClient для offline dev
- [x] ServerSettings: dimse_enabled, ae_title, called_ae, host, port
- [x] UI: DIMSE section + Test C-ECHO кнопка
- [x] UI: Query source selector (DICOMweb / DIMSE / Auto)
- [x] STOW-RS: stow_instances() в OrthancDicomWebClient
- [x] DicomUploadWorker: STOW-RS batch + DIMSE sequential C-STORE
- [x] UI: «Отправить на сервер…» в SystemBar
- [x] Unit + integration tests

### DIMSE Phase 2 (спека 2026-07-04)

- [x] C-GET retrieval (`c_get_instance`)
- [x] C-MOVE + embedded Storage SCP (port 11112, lifecycle = download)
- [x] `DicomRetrieveService` + DIMSE-only (без WADO URL)
- [x] TLS client (CA + optional client cert)
- [x] `retrieval_source`: wado / dimse / cmove / auto

---

## Micro-UX (спека 2026-07-04)

- [x] Inter fonts, theme fade, SVG icons
- [x] Hover lerp 100ms (SystemBar, ActivityBar, ToolPanel)
- [x] Dialog fade+scale open/close
- [x] Focus ring + disabled opacity (global QSS)
- [x] Loading state on Search / Upload / C-ECHO
- [—] Darcula palette migration — **cancelled**

---

## Constructor (июль 2026)

- [x] Reference constructor — visual editor для structured reference handbook
- [x] Editors: topic, pathology, metadata, parameter table, image
- [x] Storage: YAML, schema validation, image storage
- [x] Import: Excel (openpyxl)
- [x] Export: PDF (reportlab), HTML
- [x] Save/reload + focus + validation + Enter key fixes

---

## Этап 2 / Этап 3 — архитектурный backlog

- [ ] Side-by-side viewer + `MasterClock`
- [ ] ECG waveform → ED/ES (`EcgWaveformParser`)
- [ ] Полный блок ASE 2016 градации в UI
- [ ] Doppler auto-trace
- [ ] Автоматические цепочки производных Doppler

---

## Инфраструктура

| План | Статус |
|------|--------|
| DICOM performance (decode worker, cache) | [x] |
| Thumbnail priority P0/P1/P2 | [x] |
| Simpson dual workflow (manual + MBS) | [x] |
| LV Lamé template | [x] |
| RBF contour deform | [x] |
| Open-arc Simpson (2026-06-11) | [x] |
| DICOMweb Orthanc (QIDO/WADO, mock offline) | [x] |
| DIMSE Phase 1 + Phase 2 (C-GET, C-MOVE, TLS) | [x] |
| M-mode anatomical | [x] |
| Structured reference browser | [x] |
| Reference constructor | [x] |
| Gold store + benchmarks | [x] |
| Project cleanup for trial release | [x] |

---

## Maintenance / S1-05 (2026-10-25)

- [x] 18 исходных orphan-модулей разобраны: два developer-инструмента перенесены в `bench/`, 16 удалены.
- [x] Дополнительные три orphan-модуля удалены по результату AST-аудита; проверка не находит runtime-orphans.
- [x] Оставлены единые владельцы диалогов, M-mode-калипера и report форматирования.
- [x] Strain report context перенесён в `ReportGroup.notes`; общий Simpson contour grouping вынесен в `domain/calculations/simpson_contours.py`.

## Ссылки

- Детальные спеки: `docs/superpowers/specs/`
- Аудит-план трёх спринтов: [`docs/superpowers/specs/2026-10-23-audit-2026-10-22-three-sprint-plan-ru.md`](docs/superpowers/specs/2026-10-23-audit-2026-10-22-three-sprint-plan-ru.md)
- Аудиты и evidence: `docs/reviews/`
- История изменений: [`CHANGELOG.md`](CHANGELOG.md) (`Unreleased`) и `changelog/YYYY-MM.md`
- Бенчмарки и аудиты производительности: [`docs/bench/`](docs/bench/README.md) (отслеживается в git)
- Гайд по тестам: [`tests/README_RU.md`](tests/README_RU.md)
