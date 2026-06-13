# ECHO Personal Tool

Персональный десктопный инструмент для анализа эхокардиографических исследований (DICOM, MP4, JPEG/PNG).

**Стек:** PySide6, PyQtGraph, pydicom, NumPy — Clean Architecture.

## Требования

- Python 3.10–3.11
- [uv](https://docs.astral.sh/uv/) (рекомендуется) или `pip` + virtualenv

## Установка

```bash
# С uv (рекомендуется)
uv sync --extra dev
uv run echo-personal-tool

# Опционально: AI-сегментация (ONNX) и PDF-отчёты
uv sync --extra dev --extra phase2

# Или pip
pip install -e ".[dev]"
python -m echo_personal_tool
```

## Разработка

```bash
uv run pytest
uv run ruff check src tests
```

Конфигурация VS Code: `.vscode/launch.json` — запуск отладчика на `echo_personal_tool`.

## Структура

```text
src/echo_personal_tool/
├── domain/           # Модели и расчёты (без pydicom/Qt)
├── infrastructure/   # DICOM, сканер, ONNX (Фаза 2)
├── application/      # AppController, workers
└── presentation/     # MainWindow, Viewer, Browser
```

## Документация

- [Общий план.md](Общий%20план.md)
- [Этап 1.md](Этап%201.md) — MVP scope
- [Этап2.md](Этап2.md) — SDD
- [Этап3.md](Этап3.md) — UI/UX
- [Sprint3.1.md](Sprint3.1.md) — MP4/JPEG support

- [Sprint4.md](Sprint4.md) — domain calculations & MeasurementPanel

## ONNX (Фаза 2)

Автосегментация эндокарда (EchoNet Segmentation Lite) и сплайн-редактор контуров.

### Установка

```bash
uv sync --extra dev --extra phase2   # onnxruntime для инференса
```

### Экспорт модели

```bash
python scripts/export_echonet_seg_to_onnx.py --verify
```

Скрипт создаёт `models/echonet_seg_resnet50.onnx` и обновляет `models/model_manifest.json`.
Для INT8-квантизации добавьте `--quantize-int8`.

### Использование в приложении

1. Отметьте кадры ED (`D`) и ES (`S`).
2. На кадре ED или ES нажмите **`I`** (Auto Segment) — ONNX строит контур эндокарда (`source="ai"`).
3. Перетащите сплайн-узлы на контуре для коррекции; `MeasurementPanel` пересчитает объёмы по Симпсону.

Если модель недоступна или инференс превышает таймаут, в статус-баре появится подсказка использовать ручной контур (`C`).
