# Scripts

> [Русская версия](README_RU.md)

Utilities for model training, export, and benchmarking, plus helper scripts
for the lightweight Windows ZIP build. Run from the repository root.

## Models: training, export, benchmarks

| File | Description |
|------|-------------|
| `export_echonet_seg_to_onnx.py` | Export EchoNet-Dynamic to ONNX |
| `finetune_lv_seg.py` | Fine-tuning of LV segmentation |
| `finetune_la_seg.py` | Fine-tuning of LA segmentation |
| `train_ma_landmark.py` | Train mitral-annulus landmark detection |
| `calibrate_echonet_norm.py` | Normalization calibration |
| `generate_manifest_from_gold.py` | Generate a manifest from gold annotations |
| `repair_gold_collisions.py` | Fix collisions in gold data |
| `run_lv_auto_bench.py` | Run the LV benchmark |
| `run_la_auto_bench.py` | Run the LA benchmark |
| `ste_gold_qa.py` | QA of the STE gold clips |

## Installation and launch

| File | Description |
|------|-------------|
| `setup.bat` | Install the lightweight ZIP build on Windows |
| `uninstall.bat` | Uninstall the lightweight ZIP build on Windows |
| `run_constructor.py` | Launch the Reference Constructor dialog quickly, without the whole application |
| `run_tests.sh` | Test runner wrapper (Cyrillic paths, `PYTHONPATH`, offscreen Qt) |
| `sonoforge.desktop` | Linux desktop entry |

## Examples

```bash
# Export EchoNet to ONNX
python scripts/export_echonet_seg_to_onnx.py

# Fine-tuning
python scripts/finetune_lv_seg.py --data ./gold --epochs 50

# Benchmarks
python scripts/run_lv_auto_bench.py
python scripts/run_la_auto_bench.py

# Reference constructor dialog
python scripts/run_constructor.py
```
