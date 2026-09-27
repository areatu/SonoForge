# Tests

> [Русская версия](README_RU.md)

SonoForge tests: unit, integration, acceptance, regression, migration,
security, compatibility, and benchmarks.

## Structure

| Folder | Description |
|--------|-------------|
| `unit/` | ~333 unit test files: domain, infrastructure, application, presentation |
| `integration/` | Real DICOM and a live Orthanc (`ECHO_ORTHANC=1`) |
| `acceptance/` | End-to-end user scenarios (`ECHO_ACCEPTANCE=1`) |
| `regression/` | Snapshot and golden-file regressions (contours, Doppler, M-Mode) |
| `migration/` | Data migrations, schema compatibility, backups |
| `security/` | SAST/DAST, fuzzing, anonymization (`ECHO_SECURITY=1`) |
| `system/` | Black-box tests of the installed application (`ECHO_SYSTEM=1`) |
| `compat/` | OS/platform compatibility (`ECHO_COMPAT=1`) |
| `exploratory/` | Property-based and fuzzing explorations |
| `interactive/` | Manual cine segmentation diagnostics (excluded by default: `-m 'not interactive'` in `pyproject.toml`) |
| `bench/` | Performance: decode, memory, network, pipeline, playback, scrolling, rendering (`ECHO_BENCH=1`) |
| `benchmark/` | pytest-benchmark baselines for core operations |
| `fixtures/` | Test data and generators (see below) |

The `tests/` root also holds end-to-end modules: `test_smoke.py`,
`test_annotation_chain.py`, `test_dicom_tag_dictionary.py`,
`test_samsung_tick_calibration.py`, `test_upload_flow.py`,
`test_vendor_profiles*.py`, the shared `conftest.py`, and the debug helper
`debug_doppler_tags.py`.

## Running

```bash
# Whole suite (without interactive)
python -m pytest tests/ -x -q

# Unit tests only
python -m pytest tests/unit/ -x -q

# Individual groups (environment variables enable the corresponding markers)
ECHO_ORTHANC=1    python -m pytest tests/integration/ -v
ECHO_ACCEPTANCE=1 python -m pytest tests/acceptance/ -v
ECHO_SECURITY=1   python -m pytest tests/security/ -v
ECHO_SYSTEM=1     python -m pytest tests/system/ -v
ECHO_COMPAT=1     python -m pytest tests/compat/ -v
ECHO_BENCH=1      python -m pytest tests/bench/ -v

# Performance baselines
python -m pytest tests/benchmark/ --benchmark-json=results.json

# GUI tests (usually excluded in CI)
QT_QPA_PLATFORM=offscreen python -m pytest tests/ -m gui
```

Wrapper for problematic environments (Cyrillic paths, non-activatable venv):
[`scripts/run_tests.sh`](../scripts/run_tests.sh) — it sets `PYTHONPATH` and
`QT_QPA_PLATFORM=offscreen` itself.

## Fixtures (`fixtures/`)

| Path | Description |
|------|-------------|
| `generate_synthetic_dicom.py` | Generate synthetic DICOM |
| `generate_synthetic_media.py` | Generate MP4/JPEG test data |
| `orthanc/` | Mocked Orthanc API responses (+ example `sample.dcm`) |
| `reference_manifest.json` | Test reference manifest |
| `ste_phantom.py` | Synthetic STE phantom generator |
| `for_pero/` | Compact fixtures from real clips — see [`for_pero/README.md`](fixtures/for_pero/README.md); their contract is checked by `unit/test_ste_real_clips.py` |

## Unit tests (`unit/`)

They cover:
- Data models (Contour, Doppler, Speckle, MMode)
- Calculations (Simpson, Bernoulli, Teichholz, BSA, RWT, FAC)
- Infrastructure (DICOM, Orthanc, ONNX, DIMSE)
- Presentation layer (Viewer, M-Mode, Doppler, STE)
- Security (validation, PHI filtering, TLS)
