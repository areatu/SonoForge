# Documentation

Техническая документация, спеки и планы реализации.

## Структура

| Папка | Описание |
|-------|----------|
| `superpowers/specs/` | Технические спеки (STE, DICOMweb, lazy loading, M-Mode) |
| `superpowers/plans/` | Планы реализации фич |
| `compose/` | Документация compose workflow |
| `bench/` | Документация по бенчмаркам |

## User help / Пользовательская документация

| File / Файл | Description / Описание |
|------|----------|
| [`HELP_EN.md`](HELP_EN.md) | English user help covering the current UI, local/server data, measurements, calibration, references, settings, export, shortcuts, and troubleshooting |
| [`HELP_RU.md`](HELP_RU.md) | Расширенная русскоязычная справка по фактической реализации SonoForge: локальные и серверные данные, измерения, калибровка, справочник, настройки, экспорт, shortcuts и диагностика |
| [`TECHNICAL_HELP_EN.md`](TECHNICAL_HELP_EN.md) | English technical help: formulas, source chain, calibration, Settings effects, and DICOMweb/DIMSE/PACS protocols |
| [`TECHNICAL_HELP_RU.md`](TECHNICAL_HELP_RU.md) | Техническая справка на русском: формулы, источники значений, калибровка, влияние Settings и протоколы DICOMweb/DIMSE/PACS |

## Отдельные документы

| Файл | Описание |
|------|----------|
| `dicom_parcer_advanced.md` | Продвинутый парсинг DICOM тегов |
| `DICOM_VTI_tag_fix.md` | Исправление VTI тегов |
| `outlier_rejection.md` | Отсеивание аномальных данных |
| `speckle_tracking_analysis.md` | Измеренный анализ текущего STE-трекинга (диагностика) |
| `STE_IMPROVEMENT_PLAN.md` | План развития модуля STE до коммерческого уровня (rev.4, действующий; §5.2 — состояние реализации) |

## Спеки (`superpowers/specs/`)

Детальные технические описания ключевых фич:
- STE (Speckle Tracking Echocardiography)
- DICOMweb / DIMSE интеграция
- Lazy loading и производительность
- M-Mode измерения
- ONNX сегментация
- Reference browser

## Планы (`superpowers/plans/`)

Планы реализации по спринтам с описанием задач и сроков.
