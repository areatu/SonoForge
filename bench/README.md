# Bench

Бенчмарки и исследовательские прогоны (сегментация, STE-трекинг, загрузка DICOM,
плавность воспроизведения). Это **не тесты**: скрипты работают с реальными данными
и пишут отчёты; для прогоняемых в CI бенчмарков см. `tests/bench/`.

## Скрипты

| Файл | Описание |
|------|----------|
| `dicom_loading_audit.py` | Headless-аудит загрузки DICOM-папок через боевой `DicomSession`: чтение заголовка, подготовка PixelData, первый кадр, покадровое и полное декодирование, масштабирование на 1/2/4 потока |
| `ste_phantom.py` | STE-фантомная валидация (план rev.4 §3.7 KPI, §7.1) |
| `ste_contour_tracking.py` | Точность межкадрового трекинга контуров без ground truth |
| `ste_trust_flags.py` | Какое «подтверждающее» число трекинга можно сообщать без ground truth |
| `ste_verification_preview.py` | Иллюстрации для `docs/STE_TRACKING_VERIFICATION.md` |
| `ste_segment_labels_preview.py` | Иллюстрация подписей сегментов на кинематическом фантоме |
| `render_utils.py` | Общие хелперы рендеринга для STE-иллюстраций |

## Данные и манифесты

| Путь | Описание |
|------|----------|
| `tier1/manifest.json` | Манифест основного набора для бенчмарков сегментации (пути к данным локальные, в репозитории не лежат) |
| `tier1_subset_manifest.json` | Подмножество tier1 (study-уровень: ED/ES кадры) |
| `cine720/` | Измерительный комплект плавности cine-playback 1280×720 — см. [`cine720/README.md`](cine720/README.md) |

Результаты прогонов (`reports/`, `la/`, `tier1/gold/`, …) в git не коммитятся
(`.gitignore`) и живут локально.

## Примеры запуска

```bash
# Аудит загрузки DICOM-папки (начинайте без --bulk, чтобы не выделять память под весь cine)
python bench/dicom_loading_audit.py /path/to/dicom-folder \
  --limit 30 --reference --output reports/loading.json

# STE-фантом
python bench/ste_phantom.py
```

Подробности по аудиту загрузки и план оптимизации — во внутренних заметках
(`docs/bench/`, локальная папка, в репозиторий не коммитится). Метрики качества
сегментации (Dice, Hausdorff, mean surface distance, LVEF error) и сами прогоны —
в [`scripts/run_lv_auto_bench.py`](../scripts/run_lv_auto_bench.py) и
[`scripts/run_la_auto_bench.py`](../scripts/run_la_auto_bench.py); эталоны — в
[`gold/`](../gold/).
