# Tests

> [Русская версия](README_RU.md)

SonoForge tests: unit, integration, acceptance, regression, migration,
security, compatibility, and benchmarks.

## Structure

| Folder | Description |
|--------|-------------|
| `unit/` | Unit tests across domain, infrastructure, application, presentation; CI splits them losslessly by the `gui` marker |
| `integration/` | Real DICOM and a live Orthanc (`ECHO_ORTHANC=1`) |
| `acceptance/` | End-to-end user scenarios with mocked backends; required CI job `test-acceptance` (Xvfb) with a required-tests manifest |
| `regression/` | Snapshot and golden-file regressions (contours, Doppler, M-Mode) |
| `migration/` | Data migrations, schema compatibility, backups |
| `security/` | Fuzzing, anonymization, TLS/timeouts, credentials — fully mocked; required CI job `test-security` with a required-tests manifest |
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

The required Linux CI gate guards the current unit inventory: 9,019 eligible
items split losslessly into 5,261 logic and 3,758 GUI tests across 4 GUI file
shards. GUI-marked items currently span 193 files. The `pytest counters gate`
runs **before** any test job and fails fast when the collected inventory
diverges from the audited snapshot (`_BASELINE` in
`.github/scripts/verify_pytest_partition.py`). After any test-set change
(add/delete/rename of files, `gui` / `interactive` markers), refresh and
verify the baseline in the same commit as the tests:

```bash
uv run python .github/scripts/update_pytest_baseline.py --fix   # refresh _BASELINE
uv run python .github/scripts/update_pytest_baseline.py --check # verify before push
```

### Cross-platform GUI smoke (S3-01)

A curated subset of GUI tests carries the `gui_smoke` marker in addition to
`gui`: ≥20 fast, self-contained mainline scenarios (study tabs/open, linear
caliper and area contour measurement, doppler caliper, report export, layout
and user preferences, DICOM export dialog). The required jobs
`test-gui-smoke (windows-latest)` and `test-gui-smoke (macos-latest)` run
`pytest -m gui_smoke` on native runners with the default Qt platform plugin
and fail when fewer than 20 tests are selected, so the smoke cannot silently
shrink. When you add or rename a smoke scenario, update the markers and keep
the collect-guard in `.github/workflows/ci.yml` in sync; keep marked tests
fast (the whole job should stay well under ~15 minutes). `tests/regression/`
and `tests/migration/` run on every PR as the Linux job
`test-regression-migration` (no GPU, PACS or model download; an empty
selection is a failure).

### Required-tests gates (security, acceptance)

`tests/security/` and `tests/acceptance/` run on every PR as the required jobs
`test-security` and `test-acceptance`. Both are *non-vacuous*: the metrics
plugin records the outcome of every executed node, and
`.github/scripts/check_required_tests.py` fails the job unless every entry of
`.github/required-tests/security.txt` / `acceptance.txt` was collected **and
passed**. A skipped, xfailed, renamed or deleted required test, an empty
selection, or a fully skipped run is a failure, not a pass. Skips are only
tolerated for exact node ids listed in `security-allowed-skips.txt` with a
reason (currently none: the security suite has no live prerequisites).

```bash
export PYTHONPATH="$PWD/.github/scripts${PYTHONPATH:+:$PYTHONPATH}"
PYTEST_CI_METRICS_FILE=/tmp/pytest-metrics-security.json \
python -m pytest tests/security/ -p pytest_ci_metrics --junitxml=/tmp/pytest-junit-security.xml
python .github/scripts/check_pytest_counts.py \
  --junit /tmp/pytest-junit-security.xml --metrics /tmp/pytest-metrics-security.json
python .github/scripts/check_required_tests.py \
  --metrics /tmp/pytest-metrics-security.json \
  --required .github/required-tests/security.txt \
  --allowed-skips .github/required-tests/security-allowed-skips.txt
```

## Running

```bash
# Whole suite (without interactive)
python -m pytest tests/ -x -q

# Unit tests only
python -m pytest tests/unit/ -x -q

# Individual groups (environment variables enable the corresponding markers;
# security and acceptance need none — they are mocked and run on every PR)
ECHO_ORTHANC=1    python -m pytest tests/integration/ -v
python -m pytest tests/acceptance/ -v
python -m pytest tests/security/ -v
ECHO_SYSTEM=1     python -m pytest tests/system/ -v
ECHO_COMPAT=1     python -m pytest tests/compat/ -v
ECHO_BENCH=1      python -m pytest tests/bench/ -v

# Performance baselines
python -m pytest tests/benchmark/ --benchmark-json=results.json

# GUI tests (required CI gate; use xvfb on Linux)
QT_QPA_PLATFORM=offscreen xvfb-run -a python -m pytest tests/unit/ -m "gui and not interactive"
```

### Parallel Linux run (CI-style)

After `uv sync --locked --extra dev` (the CI toolchain; `pip install -e ".[dev]"`
also works but does not pin versions), the full unit suite can be reproduced locally
with one logic invocation plus four GUI shards. They write coverage to separate
files; `interactive` tests remain excluded and the GUI files run under xvfb.
Sharding bounds per-process Qt widget accumulation (unreclaimed MainWindow-grade
widgets grow workers until the OOM killer strikes); each shard runs a disjoint
quarter of the sorted `tests/unit/test_*.py` file list:

```bash
export PYTHONPATH="$PWD/.github/scripts${PYTHONPATH:+:$PYTHONPATH}"
export QT_QPA_PLATFORM=offscreen PYTHONFAULTHANDLER=1 PYTHONUNBUFFERED=1

PYTEST_CURRENT_NODE_FILE=/tmp/pytest-last-node \
PYTEST_CI_METRICS_FILE=/tmp/pytest-metrics-logic.json \
COVERAGE_FILE=.coverage.logic \
python -m pytest tests/unit/ -n auto --dist loadfile --max-worker-restart=2 \
  -p pytest_current_node -p pytest_ci_metrics -m "not gui and not interactive" \
  --junitxml=/tmp/pytest-junit-logic.xml \
  --cov=src/echo_personal_tool --cov-report= --durations=25

python .github/scripts/check_pytest_counts.py \
  --junit /tmp/pytest-junit-logic.xml --metrics /tmp/pytest-metrics-logic.json

for shard in 0 1 2 3; do
  mapfile -t unit_files < <(git ls-files 'tests/unit/test_*.py' | sort)
  shard_files=()
  for i in "${!unit_files[@]}"; do
    if [ "$((i % 4))" -eq "$shard" ]; then shard_files+=("${unit_files[$i]}"); fi
  done
  PYTEST_CURRENT_NODE_FILE=/tmp/pytest-last-node \
  PYTEST_CI_METRICS_FILE=/tmp/pytest-metrics-gui-$shard.json \
  COVERAGE_FILE=.coverage.gui$shard \
  xvfb-run -a python -m pytest "${shard_files[@]}" -n 4 --dist loadfile --max-worker-restart=2 \
    -p pytest_current_node -p pytest_ci_metrics -m "gui and not interactive" \
    --junitxml=/tmp/pytest-junit-gui-$shard.xml \
    --cov=src/echo_personal_tool --cov-report= --durations=25
  python .github/scripts/check_pytest_counts.py \
    --junit /tmp/pytest-junit-gui-$shard.xml --metrics /tmp/pytest-metrics-gui-$shard.json
done

python .github/scripts/verify_pytest_partition.py \
  --logic /tmp/pytest-metrics-logic.json \
  --gui /tmp/pytest-metrics-gui-0.json /tmp/pytest-metrics-gui-1.json \
        /tmp/pytest-metrics-gui-2.json /tmp/pytest-metrics-gui-3.json
coverage combine
coverage report
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
