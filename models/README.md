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

Models are loaded automatically from the bundled `_MEIPASS/models/` directory when present, then from the per-user application-data directory, then from `models/` in a source checkout.

The per-user directory is `models/` under `%LOCALAPPDATA%\SonoForge` on Windows, `$XDG_DATA_HOME/sonoforge` on Linux (default `~/.local/share/sonoforge`), or `~/Library/Application Support/SonoForge` on macOS. Portable mode keeps models beside the executable. The previous `~/.local/share/sonoforge/models/` location remains a read fallback during the migration release.

See `model_manifest.json` for the configuration.
