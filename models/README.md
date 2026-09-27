# Models

> [Русская версия](README_RU.md)

ONNX models for automatic segmentation.

## Models

| File | Description | Status |
|------|-------------|--------|
| `echonet_seg_resnet50.onnx` | LV segmentation A4C (EchoNet-Dynamic) | Exported |
| `echonet_seg_resnet50_int8.onnx` | INT8 quantized version | Exported |
| `echonet_la_resnet50_224.onnx` | LA segmentation (fine-tuned) | Exported |
| `ma_landmark_224.onnx` | Mitral annulus landmark detection | Exported |
| `deeplabv3_resnet50_random.pt` | PyTorch source weights | Source |
| `model_manifest.json` | Model configuration | — |

## Sizes

- LV segmentation: ~400 KB (+ 158 MB external data)
- LA segmentation: ~152 MB
- INT8 version: ~39 MB
- Landmark: ~1.3 MB

## Usage

Models are loaded automatically from:
1. `~/.local/share/sonoforge/models/` (installed version)
2. `models/` (from source)
3. `_MEIPASS/models/` (PyInstaller)

See `model_manifest.json` for the configuration.
