# Benchmarks

Бенчмарк-данные и результаты для оценки качества сегментации LV.

## Структура

| Папка | Описание |
|-------|----------|
| `tier1/` | Основной набор данных для бенчмарков (manifest + gold standard) |
| `tier1/gold/` | Gold standard аннотации для tier1 |
| `tier1/reports/` | Отчёты по результатам бенчмарков tier1 |
| `la/` | Бенчмарки для LA (left atrium) сегментации |
| `la/reports/` | Отчёты по LA бенчмаркам |
| `reports/` | Общие отчёты (LV baseline, finetuned, smoothing) |
| `cine720/` | Измерительный комплект плавности cine-playback 1280×720 (см. `cine720/README.md` и `docs/bench/2026-09-06-cine-720p-playback-audit.md`) |

## Загрузка DICOM-папок

`dicom_loading_audit.py` разделяет чтение заголовка, подготовку PixelData, первый
кадр, покадровое и полное декодирование; считает full-cine fallback и сравнивает
масштабирование на 1/2/4 потоках. Не требует GUI, не меняет исходные DICOM.

```bash
python bench/dicom_loading_audit.py /path/to/dicom-folder \
  --limit 30 --reference --output bench/reports/loading.json
```

Начинайте **без `--bulk`**, чтобы не выделять память под весь cine. В исходной
версии fallback декодировал весь ролик ради каждого кадра; исправленная версия
использует индексированный доступ. `--synthetic` создаёт временные тестовые файлы, `--alternatives`
сравнивает J2K через cv2 с текущим backend (скорость и sampled pixel equality).

Подробности, ограничения измерений и план оптимизации:
[расследование загрузки DICOM, 2026-09-09](../docs/bench/2026-09-09-dicom-folder-loading-audit.md).

## Метрики

- **Dice coefficient** —Overlap масок
- **Hausdorff distance** — Максимальное расстояние между контурами
- **Mean surface distance** — Среднее расстояние между поверхностями
- **LVEF error** — Ошибка расчёта фракции выброса

## Запуск бенчмарков

```bash
# LV бенчмарк
python -m scripts.run_lv_auto_bench

# LA бенчмарк
python -m scripts.run_la_auto_bench
```

## Формат данных

Gold standard аннотации хранятся в JSON формате с координатами контуров LV/LA.
