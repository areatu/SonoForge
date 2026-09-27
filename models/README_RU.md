# Models

> [English version](README.md)

ONNX модели для автоматической сегментации.

## Модели

| Файл | Описание | Статус |
|------|----------|--------|
| `echonet_seg_resnet50.onnx` | LV сегментация A4C (EchoNet-Dynamic) | Exported |
| `echonet_seg_resnet50_int8.onnx` | INT8 квантизованная версия | Exported |
| `echonet_la_resnet50_224.onnx` | LA сегментация (fine-tuned) | Exported |
| `ma_landmark_224.onnx` | Mitral annulus landmark detection | Exported |
| `deeplabv3_resnet50_random.pt` | PyTorch исходные веса | Source |
| `model_manifest.json` | Конфигурация моделей | — |

## Размеры

- LV segmentation: ~400 KB (+ 158 MB external data)
- LA segmentation: ~152 MB
- INT8 версия: ~39 MB
- Landmark: ~1.3 MB

## Использование

Модели загружаются автоматически из:
1. `~/.local/share/sonoforge/models/` (установленная версия)
2. `models/` (из исходников)
3. `_MEIPASS/models/` (PyInstaller)

См. `model_manifest.json` для конфигурации.
