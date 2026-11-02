# Дизайн: калибровка, последовательные измерения, RWT, Area/Volume, LAV

**Статус:** ✅ Реализовано (2026-06-19). Актуальный статус по коду — `ROADMAP.md`.

## Контекст

Активный UI: `MeasuresMenuWidget` → `MainWindow._on_measure_action` → `ViewerWidget`. Blink реализован в `MeasuresMenuWidget` (`highlight_action` / `clear_highlight`).

---

## 1. Калибровка: см вместо мм в диалоге ✅

- Диалог принимает **см**; внутри `known_mm = known_cm * 10`.
- M-mode depth calibration — аналогично.

**Файлы:** `viewer_widget.py`, тесты calibration.

---

## 2. Мигающая кнопка «следующего» измерения ✅

`MeasuresMenuWidget.highlight_action` / `clear_highlight`, таймер 500 ms.

| После завершения | Мигает кнопка |
|---|---|
| All Diastole (3 caliper) | **ES Diameter** |
| LVEF Simpson EDV (manual, A4C) | **LVEF Simpson ESV** (A4C) |
| LVEF Simpson EDV (manual, A2C) | **LVEF Simpson ESV** (A2C) |
| Simpson Biplane EDV 4C | Simpson Biplane ESV 4C (и аналогично 2C) |
| LAV 4C ES | **LAV 2C** (biplane workflow) |

---

## 3. All Diastole → ОТС (RWT) в результатах ✅

- `domain/calculations/rwt.py`
- `AppController._recompute_measurements` → `rwt` в snapshot
- Overlay: **ОТС**

---

## 4. Общие → Площадь (замкнутый полигон) ✅

`SPLINE_AREA` → `start_generic_area_contour`, метки Площадь1, 2…

---

## 5. Общие → Объём ✅

`SPLINE_VOLUME` → замкнутый полигон + Simpson (`planimeter` / generic volume chamber).

**Решение:** замкнутый контур (не open-arc MA).

---

## 6. LAV 4C / LAV 2C / RAV 4C через Simpson ✅

- Open-arc: MA septal–lateral → apex → овальный шаблон (`ATRIAL_ELLIPSE_SHORT_AXIS_RATIO = 0.85`)
- Volume: `chamber_simpson` (LA/RA)
- Biplane LAV: blink LAV 2C после 4C ES
- Magnetic snap, group delete — как LV

**Area-length:** код сохранён (`la_area_length.py`), не в меню; Simpson — primary.

---

## План реализации (фазы)

| Фаза | Пункты | Статус |
|---|---|---|
| A | 1, 3 | ✅ |
| B | 2 | ✅ |
| C | 4, 5 | ✅ |
| D | 6 | ✅ |

---

## Открытые вопросы

1. ~~**П. 7** — текст обрывается; что требуется?~~ **Снят:** ошибочный фрагмент исходного запроса, не является задачей.
2. ~~**Объём (п.5):** open-arc или замкнутый контур?~~ **Решено:** замкнутый полигон.
3. ~~**LAV (п.6):** Simpson или area-length?~~ **Решено:** Simpson primary; area-length legacy.
4. ~~**RWT:** `ОТС` или `RWT`?~~ **Решено:** **ОТС** в overlay.

---

## Критерии готовности

- [x] Калибровка: ввод 5.0 см → корректный mm/px
- [x] После All Diastole мигает ES Diameter; после EDV мигает ESV
- [x] Overlay All Diastole содержит ОТС при IVSd+LVEDD+LVPWd
- [x] Площадь1/2, Объем1/2 в generic tools
- [x] LAV 4C/2C + RAV: open-arc + snap + group delete
