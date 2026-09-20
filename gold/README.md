# Gold Standard

Эталонные аннотации для валидации сегментации LV/LA.

## Файлы

| Файл | Описание |
|------|----------|
| `lv_*.json` | Gold standard для LV (left ventricle) сегментации |
| `la_*.json` | Gold standard для LA (left atrium) сегментации |

## Формат

JSON файлы содержат координаты контуров в нормализованных координатах (0-1) для конкретного DICOM исследования (идентифицированного по Study Instance UID).

## Использование

Данные используются для:
- Валидации ONNX моделей сегментации
- Расчёта метрик качества (Dice, Hausdorff)
- Бенчмарков производительности

## Сопутствующие скрипты

| Скрипт | Назначение |
|--------|------------|
| [`scripts/generate_manifest_from_gold.py`](../scripts/generate_manifest_from_gold.py) | Генерация манифеста из gold-аннотаций |
| [`scripts/repair_gold_collisions.py`](../scripts/repair_gold_collisions.py) | Исправление коллизий в gold-данных |
| [`scripts/ste_gold_qa.py`](../scripts/ste_gold_qa.py) | QA gold-клипов для STE |
| [`scripts/run_lv_auto_bench.py`](../scripts/run_lv_auto_bench.py), [`scripts/run_la_auto_bench.py`](../scripts/run_la_auto_bench.py) | Бенчмарки сегментации по этим эталонам (см. [`../bench/`](../bench/)) |
