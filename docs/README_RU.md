# Documentation

> [English version](README.md)

Техническая документация, спеки и планы реализации.

## Структура

| Папка | Описание |
|-------|----------|
| `superpowers/specs/` | Технические спеки фич (STE, DICOMweb/DIMSE, lazy loading, M-Mode, ONNX-сегментация, reference browser и др.) |
| `reviews/` | Ревью кода и решений |
| `spikes/` | Технические спайки с замерами и выводами (например, UI-4.0 — предпросмотр отчёта) |
| `screenshots/` | Скриншоты приложения для документации; `screenshots/ste_references/` — вендорские референсы (изображения не коммитятся, см. `.gitignore`) |

> Локальные (не коммитятся, см. `.gitignore`): `superpowers/plans/` — планы по
> спринтам, `compose/` — документация compose workflow, `bench/` — заметки по
> бенчмаркам. Ссылки на них из других документов ведут только в локальные чекауты.

## User help / Пользовательская документация

| File / Файл | Description / Описание |
|------|----------|
| [`HELP_EN.md`](HELP_EN.md) | English user help covering the current UI, local/server data, measurements, calibration, references, settings, export, shortcuts, and troubleshooting |
| [`HELP_RU.md`](HELP_RU.md) | Расширенная русскоязычная справка по фактической реализации SonoForge: локальные и серверные данные, измерения, калибровка, справочник, настройки, экспорт, shortcuts и диагностика |
| [`TECHNICAL_HELP_EN.md`](TECHNICAL_HELP_EN.md) | English technical help: formulas, source chain, calibration, Settings effects, and DICOMweb/DIMSE/PACS protocols |
| [`TECHNICAL_HELP_RU.md`](TECHNICAL_HELP_RU.md) | Техническая справка на русском: формулы, источники значений, калибровка, влияние Settings и протоколы DICOMweb/DIMSE/PACS |

## Безопасность и целостность релизов

| Файл | Описание |
|------|----------|
| [`security/data-inventory.md`](security/data-inventory.md) | Инвентарь данных и сопоставление с отдельными требованиями безопасности |
| [`security/code-signing.md`](security/code-signing.md) | Подпись кода и проверка релизов: статус подписи по платформам, проверки `SHA256SUMS` и подтверждения происхождения сборки, варианты и стоимость, политика подписи кода |

См. также [`../SECURITY.md`](../SECURITY.md).

## Отдельные документы

| Файл | Описание |
|------|----------|
| [`ui_tokens_ru.md`](ui_tokens_ru.md) | Токены оформления интерфейса: три слоя, группы токенов, правила (никаких сырых цветов вне модуля палитр, проверка контраста, прежние темы закреплены golden-файлами) и соответствие прежним ключам палитры — [English](ui_tokens.md) |
| [`superpowers/specs/2026-10-13-quality-safety-hardening-spec-plan-ru.md`](superpowers/specs/2026-10-13-quality-safety-hardening-spec-plan-ru.md) | Спека-план приоритетов качества и безопасности: достоверность результатов/persistence, реальные CI-гейты и транспорт, композиция ViewerWidget, ошибки/границы domain, проверяемые релизы и подпись |
| [`superpowers/specs/2026-10-01-multiview-two-clips-spec-ru.md`](superpowers/specs/2026-10-01-multiview-two-clips-spec-ru.md) | Спека Multiview: два клипа, общий фрагмент, маркеры МК и синхронизация по циклам |
| `STE_IMPROVEMENT_PLAN.md` | План развития модуля STE до коммерческого уровня (rev.4, действующий; §5.2 — состояние реализации) |
| `STE_TRACKING_VERIFICATION.md` | Верификация STE-трекинга |
| `STE_VENDOR_REFERENCE.md` | Вендорские референсные значения STE (Samsung RS85, Philips EPIQ) |
| `speckle_tracking_analysis.md` | Измерительный анализ текущего STE-трекинга (диагностика) |
| `dicom_parcer_advanced.md` | Продвинутый парсинг DICOM-тегов |
| `DICOM_VTI_tag_fix.md` | Исправление VTI-тегов |
| `doppler_baseline_samsung.md` | Базовые допплеровские параметры Samsung |
| `outlier_rejection.md` | Отсеивание аномальных данных |
| `web_reference_review.md` | Ревью web-просмотра справочника |
| [`spikes/2026-10-19-ui-4-0-report-preview-spike-ru.md`](spikes/2026-10-19-ui-4-0-report-preview-spike-ru.md) | Итоги спайка UI-4.0 (RU): предпросмотр отчёта байтами PDF в QPdfView, бюджет пересборки против 500 мс, пиксельная проверка геометрии QPdfView, контракт `render_report` |
| `new_reference_parameters.yaml` | Новые параметры справочника (сосуды, щитовидная железа, почки и др.) с верифицированными источниками |

Данные и всё, что с ними связано, описаны в [`../data/README.md`](../data/README.md).
