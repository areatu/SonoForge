# ROADMAP — ECHO Personal Tool

**Обновлено:** 2026-07-04 (DIMSE Phase 2 + Micro-UX specs)  
**Источник истины по коду:** этот файл + `CHANGELOG_SESSION.md` (последние записи).  
**Детальные спеки:** `docs/superpowers/specs/`, планы — `docs/superpowers/plans/`.

Легенда: `[x]` реализовано в коде · `[~]` частично · `[ ]` не начато / отложено · `[—]` **cancelled**

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
| — | ~~П. 7~~ | **Снят** — ошибочный пункт исходного запроса |

**Решённые вопросы спеки:** generic объём — замкнутый полигон; LAV primary — Simpson (area-length код есть, не в меню); overlay — **ОТС**.

**Критерии готовности спеки:**

- [x] Калибровка: 5.0 см → корректный mm/px
- [x] После All Diastole → blink ES Diameter; после EDV Simpson → ESV
- [x] ОТС в overlay при IVSd+LVEDD+LVPWd
- [x] Площадь1/2, Объем1/2 в generic tools
- [x] LAV 4C/2C + RAV 4C: open-arc, snap, group delete (как LV)

---

## LV Auto ONNX (спека 2026-06-19)

| Фаза | Содержание | Статус |
|------|------------|--------|
| **v1** | A4C ONNX, papillary cleanup, review UX (Enter/Esc), hotkey I | [x] |
| **v1** | Biplane A2C в LV Auto | [x] убрано из меню (не v1) |
| **v1.1** | Фиксированные train mean/std | [ ] отложено — v1 annulus не трогаем |
| **v2** | A2C auto (отдельная модель / transfer) | [ ] «в следующей версии» |

- [x] Stepped border refine + edge snap для ai/manual
- [x] Lamé template только для `source=model` LV
- [ ] AI validation gate ±3% LVEF vs EchoPAC (не release gate v1)

---

## EchoPac UI и отчёты

- [x] SystemBar, Measures accordion, ToolPanel (Controls)
- [x] Нормативы ASE (`ase_reference_dialog`)
- [x] Рост/вес, индексы BSA, LAVi/RAVi в overlay
- [x] Кнопка **Результаты** + PDF export (`measurement_results_dialog`, `reportlab` optional)
- [~] `MeasurementWorksheet` — модуль есть, в `MainWindow` не подключён (заменён `MeasuresMenuWidget`)
- [ ] CSV / JSON export (`ReportService` из Этап2)
- [ ] 2D | Doppler layout toggle в SystemBar

---

## Measures-block.md — пробелы в меню

Код handlers есть, **кнопок в `measures_menu.py` нет:**

- [x] ~~**S ПП**~~ — **закрыто**: площадь ПП через RAV 4C (Simpson), отдельной кнопки не будет
- [x] **RV FAC** — одна кнопка, ED→blink→ES, шаблон crescent open-arc (спека `2026-06-22-rv-fac-design.md`)

**Реализовано в меню:** LV, LV Auto (EDV/ESV A4C), Aorta, LA, RA (диаметр + RAV 4C), RV + **FAC**, Diastology, MV/AV, TV/PV.

**Area-length LA/RA:** `la_area_length.py`, `start_atrial_area_length_contour` — legacy, не в меню (Simpson primary).

---

## Этап 2 / Этап 3 — архитектурный backlog

- [ ] Side-by-side viewer + `MasterClock`
- [ ] ECG waveform → ED/ES (`EcgWaveformParser`)
- [ ] Полный блок ASE 2016 градации в UI (частично: `diastology_grade`, нормативы)
- [ ] Doppler auto-trace / speckle tracking (исключено в Этап3)
- [ ] Автоматические цепочки производных Doppler (S AV, полные MV/AV trace metrics)

---

## Инфраструктура и UX (старые планы)

| План | Статус |
|------|--------|
| Display UX (labels, RGB DICOM, DR sliders) | [~] gallery вместо tree browser; DR/W/L в Controls |
| DICOM performance (decode worker, cache) | [x] |
| Thumbnail priority P0/P1/P2 | [x] |
| Simpson dual workflow (manual + MBS) | [x] |
| LV Lamé template | [x] |
| RBF contour deform | [x] |
| MBS Advanced (ED→ES propagate) | [—] **cancelled** — superseded Lamé + R-refine |
| LV Lamé template v2 (piecewise asymmetric) | [—] **cancelled** |
| Open-arc Simpson (2026-06-11) | [x] |
| DICOMweb Orthanc (QIDO/WADO, mock offline, session cache) | [x] |

---

## DICOMweb Orthanc (спека 2026-06-23)

- [x] QIDO-RS + WADO-RS через `OrthancDicomWebClient` (httpx)
- [x] Сессионный кэш `OrthancSessionCache`, очистка при выходе
- [x] Mock offline: `FakeDicomWebClient` + JSON/DICOM фикстуры
- [x] UI: `OrthancStudyDialog`, «Загрузить с сервера…», настройки сервера
- [x] Интеграция: `open_folder(study_path)` после загрузки
- [x] Cancel загрузки + очистка session cache (`DICOM_parsing.md`)
- [x] Суммарный progress-bar по всем выбранным сериям
- [x] QIDO `includefield`; парсинг `00201209` → «N инст.» в диалоге
- [ ] Workplace: реальные JSON-фикстуры с Orthanc (см. spec footer)

**Спека:** `docs/superpowers/specs/2026-06-23-dicomweb-orthanc-design.md` · **Замечания:** `DICOM_parsing.md`

---

## DIMSE / STOW-RS (план 2026-07-02)

- [x] pynetdicom dep + DimseClient / DicomUploadClient ports
- [x] PynetdimseClient: c_echo, c_find (study/series/instances), c_store
- [x] FakeDimseClient для offline dev
- [x] ServerSettings: dimse_enabled, ae_title, called_ae, host, port, stow_dicom_web_url, query_source
- [x] UI: DIMSE section + Test C-ECHO кнопка
- [x] UI: Query source selector (DICOMweb / DIMSE / Auto)
- [x] STOW-RS: stow_instances() в OrthancDicomWebClient
- [x] DicomUploadWorker: STOW-RS batch + DIMSE sequential C-STORE
- [x] UI: «Отправить на сервер…» в SystemBar
- [x] Unit + integration tests (ECHO_ORTHANC=1 / ECHO_ORTHANC_DIMSE=1)

### DIMSE Phase 2 (спека 2026-07-04)

- [x] C-GET retrieval (`c_get_instance`)
- [x] C-MOVE + embedded Storage SCP (port 11112, lifecycle = download)
- [x] `DicomRetrieveService` + DIMSE-only (без WADO URL)
- [x] TLS client (CA + optional client cert)
- [x] `retrieval_source`: wado / dimse / cmove / auto

**Спека:** `docs/superpowers/specs/2026-07-04-dimse-phase2-design.md`

---

## Micro-UX (спека 2026-07-04)

- [x] Inter fonts, theme fade, SVG icons — done
- [x] Hover lerp 100ms (SystemBar, ActivityBar, ToolPanel)
- [x] Dialog fade+scale open/close
- [x] Focus ring + disabled opacity (global QSS)
- [x] Loading state on Search / Upload / C-ECHO
- [—] Darcula palette migration — **cancelled**

**Спека:** `docs/superpowers/specs/2026-07-04-micro-ux-design.md`

---

## Performance Benchmarks (2026-07-02)

- [x] test_pipeline_bench.py — full end-to-end scan→decode→cache
- [x] test_decode_bench.py — DicomSession (uncompressed, JPEG, JPEG-2000, single-frame, fallback)
- [x] test_network_bench.py — C-ECHO, C-FIND, C-STORE, STOW multipart, QueryService
- [x] pytest-benchmark autosave + compare workflow (.benchmarks/ history)

---

## Следующие приоритеты (рекомендация)

1. [x] RV FAC (одна кнопка, crescent open-arc, blink ED→ES)
2. [ ] Workplace smoke DICOMweb + обновить `tests/fixtures/orthanc/` с сервера
3. [ ] ONNX v1.1 (mean/std only, annulus — без изменений)
4. [ ] ONNX v2 / A2C auto
5. [ ] CSV/JSON отчёт
6. [ ] Side-by-side + ECG (Этап 3)

---

## Ссылки

- Требования кнопок: `Measures-block.md`
- Архитектура: `Этап2.md`, UI: `Этап3.md`
- Актуальная спека workflow: `docs/superpowers/specs/2026-06-19-measurement-workflow-design.md`
