# Documentation

Техническая документация, спеки и планы реализации.

## Структура

| Папка | Описание |
|-------|----------|
| `superpowers/specs/` | Технические спеки фич (STE, DICOMweb/DIMSE, lazy loading, M-Mode, ONNX-сегментация, reference browser и др.) |
| `reviews/` | Ревью кода и решений |
| `screenshots/` | Скриншоты приложения для документации; `screenshots/ste_references/` — вендорские референсы (изображения не коммитятся, см. `.gitignore`) |

> Локальные (не коммитятся, см. `.gitignore`): `superpowers/plans/` — планы по
> спринтам, `compose/` — документация compose workflow, `bench/` — заметки по
> бенчмаркам. Ссылки на них из других документов ведут только в локальные чекауты.

## Отдельные документы

| Файл | Описание |
|------|----------|
| `STE_IMPROVEMENT_PLAN.md` | План развития модуля STE до коммерческого уровня (rev.4, действующий; §5.2 — состояние реализации) |
| `STE_TRACKING_VERIFICATION.md` | Верификация STE-трекинга |
| `STE_VENDOR_REFERENCE.md` | Вендорские референсные значения STE (Samsung RS85, Philips EPIQ) |
| `speckle_tracking_analysis.md` | Измерительный анализ текущего STE-трекинга (диагностика) |
| `dicom_parcer_advanced.md` | Продвинутый парсинг DICOM-тегов |
| `DICOM_VTI_tag_fix.md` | Исправление VTI-тегов |
| `doppler_baseline_samsung.md` | Базовые допплеровские параметры Samsung |
| `outlier_rejection.md` | Отсеивание аномальных данных |
| `web_reference_review.md` | Ревью web-просмотра справочника |
| `new_reference_parameters.yaml` | Новые параметры справочника (сосуды, щитовидная железа, почки и др.) с верифицированными источниками |

Данные и всё, что с ними связано, описаны в [`../data/README.md`](../data/README.md).
