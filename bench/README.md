# Bench

> [Русская версия](README_RU.md)

Benchmarks and research runs (segmentation, STE tracking, DICOM loading,
playback smoothness). These are **not tests**: the scripts work on real data
and write reports; for CI-run benchmarks see `tests/bench/`.

## Scripts

| File | Description |
|------|-------------|
| `dicom_loading_audit.py` | Headless audit of DICOM folder loading through the production `DicomSession`: header read, PixelData preparation, first frame, per-frame and full decode, scaling across 1/2/4 threads |
| `ste_phantom.py` | STE phantom validation (plan rev.4 §3.7 KPI, §7.1) |
| `ste_contour_tracking.py` | Inter-frame contour tracking accuracy without ground truth |
| `ste_trust_flags.py` | Which "confirming" tracking number can be reported without ground truth |
| `ste_verification_preview.py` | Illustrations for `docs/STE_TRACKING_VERIFICATION.md` |
| `ste_segment_labels_preview.py` | Illustration of segment labels on a kinematic phantom |
| `render_utils.py` | Shared rendering helpers for STE illustrations |

## Data and manifests

| Path | Description |
|------|-------------|
| `tier1/manifest.json` | Main manifest for segmentation benchmarks (data paths are local, not in the repo) |
| `tier1_subset_manifest.json` | Subset of tier1 (study level: ED/ES frames) |
| `cine720/` | 1280×720 cine-playback smoothness measurement kit — see [`cine720/README.md`](cine720/README.md) |

Run outputs (`reports/`, `la/`, `tier1/gold/`, …) are not committed to git
(`.gitignore`) and live locally.

## Examples

```bash
# Audit DICOM folder loading (start without --bulk to avoid allocating memory for the whole cine)
python bench/dicom_loading_audit.py /path/to/dicom-folder \
  --limit 30 --reference --output reports/loading.json

# STE phantom
python bench/ste_phantom.py
```

Details on the loading audit and the optimization plan live in internal notes
(`docs/bench/`, a local folder, not committed to the repository). Segmentation
quality metrics (Dice, Hausdorff, mean surface distance, LVEF error) and the
runs themselves are in [`scripts/run_lv_auto_bench.py`](../scripts/run_lv_auto_bench.py)
and [`scripts/run_la_auto_bench.py`](../scripts/run_la_auto_bench.py); the
references are in [`gold/`](../gold/).
