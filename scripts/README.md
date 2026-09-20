# Scripts

Утилиты для обучения, экспорта и бенчмарков моделей, а также служебные скрипты
установки. Запускаются из корня репозитория.

## Модели: обучение, экспорт, бенчмарки

| Файл | Описание |
|------|----------|
| `export_echonet_seg_to_onnx.py` | Экспорт EchoNet-Dynamic в ONNX |
| `finetune_lv_seg.py` | Fine-tuning LV-сегментации |
| `finetune_la_seg.py` | Fine-tuning LA-сегментации |
| `train_ma_landmark.py` | Обучение mitral-annulus landmark detection |
| `calibrate_echonet_norm.py` | Калибровка нормализации |
| `generate_manifest_from_gold.py` | Генерация манифеста из gold-аннотаций |
| `repair_gold_collisions.py` | Исправление коллизий в gold-данных |
| `run_lv_auto_bench.py` | Запуск LV-бенчмарка |
| `run_la_auto_bench.py` | Запуск LA-бенчмарка |
| `ste_gold_qa.py` | QA gold-клипов для STE |

## Установка и запуск

| Файл | Описание |
|------|----------|
| `create_installer.py` | Сборка self-extracting установщика Windows (использует `installer_stub.py` из корня) |
| `setup.bat` | Установка лёгкой сборки под Windows |
| `uninstall.bat` | Удаление под Windows |
| `run_constructor.py` | Быстрый запуск диалога Reference Constructor без всего приложения |
| `run_tests.sh` | Обёртка для запуска тестов (кириллические пути, `PYTHONPATH`, offscreen Qt) |
| `sonoforge.desktop` | Desktop entry для Linux |

## Примеры

```bash
# Экспорт EchoNet в ONNX
python scripts/export_echonet_seg_to_onnx.py

# Fine-tuning
python scripts/finetune_lv_seg.py --data ./gold --epochs 50

# Бенчмарки
python scripts/run_lv_auto_bench.py
python scripts/run_la_auto_bench.py

# Диалог конструктора справочника
python scripts/run_constructor.py
```
