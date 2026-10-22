# `bench/cine720` — measurement kit for 720p cine playback

> [Русская версия](README_RU.md)

The kit was built for the
[`docs/bench/2026-09-06-cine-720p-playback-audit.md`](../../docs/bench/2026-09-06-cine-720p-playback-audit.md)
audit and reproduces every number in it. Unlike `tests/bench/` (microsecond
measurements of cache operations on synthetic 16×16…512×512 frames), these scripts
run the **real `AppController` + real `ViewerWidget` in a live Qt event loop** on
1280×720 frames and measure what the user sees: FPS, frame intervals, scroll latency,
per-frame cost on the main thread, RSS.

The kit **does not modify** production code (`src/`): fix prototypes are applied via
monkey-patching before the controller is created.

## Requirements

* Debian/Linux or Windows, Python 3.10–3.11
* application dependencies (`PySide6`, `pyqtgraph`, `opencv-python-headless`, `pydicom`,
  `pylibjpeg*`, `numpy`, `psutil`, `scipy`)
* headless run: `QT_QPA_PLATFORM=offscreen`
* fixtures are generated locally (hundreds of MB) and **not committed**

```bash
python3 -m venv .venv-bench
.venv-bench/bin/pip install "numpy>=1.26,<2.0" "opencv-python-headless>=4.8" "pydicom>=2.4" \
    "pylibjpeg>=2.0" "pylibjpeg-openjpeg>=2.0" "pylibjpeg-libjpeg>=2.0" "psutil>=5.9" \
    "pyside6>=6.6" "pyqtgraph>=0.13" "scipy>=1.11" onnxruntime reportlab pymupdf pynetdicom \
    jsonschema openpyxl keyring
```

## Fixture generation

```bash
# default directory: $CINE720_DIR or <tmp>/sonoforge-cine720
.venv-bench/bin/python bench/cine720/gen_cine720.py "" 60  rgb_raw,mono_raw,jpeg
.venv-bench/bin/python bench/cine720/gen_cine720.py "" 120 rgb_raw,jpeg
```

| Variant | Transfer Syntax / codec | Size (60 / 120 frames) | Frame in RAM |
|---|---|---|---|
| `rgb_raw` | Explicit VR LE, RGB 8-bit | 165.9 / 331.8 MB | 2.76 MB |
| `mono_raw` | Explicit VR LE, MONOCHROME2 16-bit | 110.6 MB | 1.84 MB |
| `jpeg` | JPEG Baseline `1.2.840.10008.1.2.4.50` | 6.29 / 12.58 MB | 2.76 MB |

The content resembles an ultrasound cine: sector gradient, correlated speckle, a moving
cavity, a highly saturated color Doppler wedge. `FrameTime = 33 ms` (30 FPS).
Any 720p 30 fps clip works for the MP4 path (`--format mp4`).

## Scripts

| Script | What it measures |
|---|---|
| `bench_decode.py <file>` | `open()`, first frame, `decode_single_frame` (sequential and parallel), `decode_all_frames` (zero-copy), cost of the full cine in RAM |
| `bench_prefetch.py <file>` | cost of a single worker call (`_run_batch` as in `FrameLoaderWorker`) at different batch sizes; "as released" vs "warm session" |
| `bench_playback_e2e.py <file>` | end-to-end playback in the stock configuration: FPS, p95/max interval, tick phases (`cache_hit`/`cache_miss`), batch count and latency, prefetch round-trip, buffer depth per tick, render/paint, RSS, first frame, Play → first shift; the `--ram-cap-mb` and `--decode-slow-ms` flags emulate a weak machine |
| `bench_playback_fixes.py <file>` | the same run with fix prototypes: `--fix-session`, `--fix-levels`, `--fix-timing`, `--fix-roi`, `--hot`, `--cache-mb` |
| `bench_scroll.py <file>` | latency of one scroll step (12 random transitions) and click → first frame |
| `bench_render.py` | isolated costs of render operations: `show_frame_fast`, viewport paint, W/L paths, LUT |
| `bench_cpu.py <script> [args…]` | wrapper: how many CPU cores a run burns (user+sys / wall); run twice with different `--seconds` and subtract the start |
| `bench_micro.py` | micro-costs around playback: `_detect_leading_static_from_cache`, `FrameCache.frames` (`np.stack`), `compute_display_levels`, `resolve_cine_segment_roi_xyxy` |
| `probe_render_breakdown.py <file>` | per-operation breakdown of a frame on the main thread in a real run (timers on `show_frame_fast` → `_update_levels` → `compute_display_levels` → `setImage`, plus the controller ROI and paint) |
| `probe_threadlocal.py` | proof: `threading.local` does not survive between `QRunnable`s in a `QThreadPool`, even on a single OS thread |
| `probe_session_trace.py <file> <frames>` | trace: which `id(DicomSession)` each worker job gets and how many times the file is fully re-read |

Fix prototypes (not for production, only to measure the effect):

| Module | What it does |
|---|---|
| `sessioncache_patch.py` | one shared `DicomSession` per process keyed by resolved path under `RLock` (+ a `LockedReader` proxy for a shared `VideoReader`), `release_heavy()` disabled |
| `levelsfix_patch.py` | fixes the W/L levels cache: key order in `_cached_levels_key` (permutation comparison) + dtype-aware `_is_levels_outlier` thresholds |

The `--fix-timing` and `--fix-roi` flags live inside `bench_playback_fixes.py`: the former
takes the timestamp at the start of the tick and does not reschedule the timer from a stale
timestamp, the latter removes the per-frame `resolve_cine_segment_roi_xyxy` call.

## Quick run (commands from the audit)

```bash
D=/tmp/sonoforge-cine720
export QT_QPA_PLATFORM=offscreen

# baseline
.venv-bench/bin/python bench/cine720/bench_playback_e2e.py $D/cine720_rgb_raw_60.dcm --frames 60 --seconds 8

# fix matrix
.venv-bench/bin/python bench/cine720/bench_playback_fixes.py $D/cine720_mono_raw_60.dcm \
    --frames 60 --cache-mb 64 --fix-session --fix-levels --fix-timing --fix-roi

# per-frame breakdown on the main thread
.venv-bench/bin/python bench/cine720/probe_render_breakdown.py $D/cine720_mono_raw_60.dcm \
    --frames 5 --seconds 5 --fix-session --fix-levels

# scroll
.venv-bench/bin/python bench/cine720/bench_scroll.py $D/cine720_rgb_raw_120.dcm --frames 120 --fix-session

# CPU usage (two runs, the difference = playback phase)
.venv-bench/bin/python bench/cine720/bench_cpu.py bench/cine720/bench_playback_fixes.py \
    $D/cine720_rgb_raw_60.dcm --frames 60 --seconds 8
.venv-bench/bin/python bench/cine720/bench_cpu.py bench/cine720/bench_playback_fixes.py \
    $D/cine720_rgb_raw_60.dcm --frames 60 --seconds 1

# root-cause evidence
.venv-bench/bin/python bench/cine720/probe_threadlocal.py
.venv-bench/bin/python bench/cine720/probe_session_trace.py $D/cine720_rgb_raw_60.dcm 60
```

Shared arguments: `--frames` (number of frames in the instance), `--seconds` (run duration),
`--cache-mb` (lower bound of the `FrameCache` budget — cache tuning raises it to fit the
loaded cine), `--format dicom|mp4`, `--label` (label in the report).

`bench_playback_e2e.py` only:

| Flag | Why |
|---|---|
| `--ram-cap-mb N` | limit the share of RAM the cache tuning may occupy (emulates a machine with little free memory) |
| `--decode-slow-ms X` | add X ms of wall time to decoding each frame (emulates a slow CPU; also guarantees real cache misses) |
| `--profile auto\|low\|high` | force a `detect_playback_config` profile |
| `--warm-session` | disable `release_heavy()` after a batch (a historical flag: in production code the session is already one per file) |
| `--no-render` | skip rendering in the viewer (decode/cache only) |

`--frames` must match the fixture's actual frame count: a larger value yields an invalid
run (the instance is shorter than requested, so some ticks hit non-existent frames).

## After the fix series (2026-09-07)

The fixes from the audit landed in production code (a series of commits on the branch,
results in §6.1 of the audit), so:

* **The `sessioncache_patch.py` / `levelsfix_patch.py` prototypes and the `--fix-*` flags
  target the `cf82a7b` code.** They monkey-patch the old behavior, so on the current tree
  they either do not apply or have no effect (there is nothing left to fix). For a
  "before/after" comparison, do `git checkout cf82a7b` (or `git worktree add ../base cf82a7b`)
  and run the matrix there; `bench_playback_e2e.py` without flags is the run of the current
  production path.
* **The end-to-end 720p test lives in `tests/bench/test_cine_playback_e2e_ci.py`** and runs in
  CI on Linux under `xvfb-run`: real `AppController` + `ViewerWidget`, two synthetic 720p
  fixtures (MONO8 × 60 and RGB24 × 30), 4 s of playback, and asserts against the SLO (§4.3 of
  the audit). It generates its fixtures itself; no external files are needed:

  ```bash
  QT_QPA_PLATFORM=offscreen .venv-bench/bin/python -m pytest tests/bench/test_cine_playback_e2e_ci.py -v
  ```

* **Weak-machine emulation** — the `--ram-cap-mb` / `--decode-slow-ms` flags (table above);
  the measured profiles and their interpretation are in §4.4 of the audit.
* **Fixture directory:** the first argument of `gen_cine720.py` is a directory, not a label.
  An empty string (`""`) means the current directory, i.e. hundreds of MB of fixtures would
  land in the repository root; leave the argument empty only deliberately, otherwise pass
  `$CINE720_DIR` / `/tmp/...`.

## How to read the result

```text
=== mono16 ===
  fixes: timing=True roi=True warm=False session=True hot=False cache=64MB
  FPS  30.86 (target 30)   frames=278 in 9.0s   non-adjacent jumps=0
  gap ms: avg  32.44 p95  35.12 max   62.15
  render avg  2.14 ms | paint avg  8.19 ms | main-thread 10.33 ms
  cache 19/60 frames (35 MB) | RSS 504->580 MB peak 580 MB
```

* `FPS` — frames shown / run time; `target` = `1000 / frame_time`.
* `gap ms` — intervals between frame displays; the goal is p95 ≤ 1.25 × `frame_time`.
* `render` — `ViewerWidget.show_frame_fast`; `paint` — a forced `viewport().repaint()`;
  `main-thread` = render + paint (excluding the controller ROI cost — that is shown by
  `probe_render_breakdown.py`).
* `cache N/M frames (X MB)` — `FrameCache` fill at the end of the run.
* `RSS` — process memory (start → end, peak).

A useful model confirmed by the measurements:

```
without the timer fix:  FPS ≈ 1000 / (frame_time + W)      # W = main-thread work per frame
with the timer fix:     FPS ≈ 1000 / max(frame_time, W)
```

## Stand limitations

* `QT_QPA_PLATFORM=offscreen` → **raster rendering**: the `paint` numbers are the worst case.
  On a machine with working OpenGL, repainting is cheaper; the other metrics do not depend
  on the backend.
* `probe_threadlocal.py` prints `threading.get_native_id()` — on Windows this is a different
  identifier, but the output (thread-local loss between `QRunnable`s) is the same: this is
  PySide6 behavior, not OS kernel behavior.
* The shared-session prototype kept the active file's pixel block in RAM, so peak RSS did not
  drop (see §2.7 of the audit). In production code the uncompressed cine pixel block is mapped
  through `mmap`, so peak RSS includes file pages: they enter the working set but are dropped
  by the OS without writing, and comparing "before/after" only by RSS is incorrect (§4.2 of the
  audit).
* All numbers in the series are Linux/offscreen on a stand with 2 vCPU / 4 GB. There was no
  Windows stand: the platform risks are analyzed in §4.2 of the audit but not measured.
