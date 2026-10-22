# Gold Standard

> [Русская версия](README_RU.md)

Reference annotations for validating LV/LA segmentation.

## Files

| File | Description |
|------|-------------|
| `lv_*.json` | Gold standard for LV (left ventricle) segmentation |
| `la_*.json` | Gold standard for LA (left atrium) segmentation |

## Format

The JSON files contain contour coordinates in normalized coordinates (0–1) for a
specific DICOM study (identified by Study Instance UID).

## Usage

The data is used for:
- Validating ONNX segmentation models
- Computing quality metrics (Dice, Hausdorff)
- Performance benchmarks

## Related scripts

| Script | Purpose |
|--------|---------|
| [`scripts/generate_manifest_from_gold.py`](../scripts/generate_manifest_from_gold.py) | Generate a manifest from gold annotations |
| [`scripts/repair_gold_collisions.py`](../scripts/repair_gold_collisions.py) | Fix collisions in gold data |
| [`scripts/ste_gold_qa.py`](../scripts/ste_gold_qa.py) | QA of the STE gold clips |
| [`scripts/run_lv_auto_bench.py`](../scripts/run_lv_auto_bench.py), [`scripts/run_la_auto_bench.py`](../scripts/run_la_auto_bench.py) | Segmentation benchmarks against these references (see [`../bench/`](../bench/)) |
