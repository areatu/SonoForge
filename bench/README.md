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
