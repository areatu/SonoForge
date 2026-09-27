# SonoForge Presenter (lite portable profile)

> [Русская версия](README_RU.md)

**SonoForge Presenter** is a lightweight portable SonoForge profile for
demonstrations from a USB stick on other people's computers (a projector, "between
slides"). It is built from **the same source tree** as the full SonoForge: the
profile is enabled by the `SONOFORGE_PROFILE=presenter` environment variable (entry
point `__main_presenter__.py`), and heavy modules are excluded at packaging time
(`sonoforge-presenter.spec`). The main profile's code is not changed destructively —
all edits are additive (guarded/lazy imports).

## Product composition

| | Full SonoForge | Presenter |
|---|---|---|
| AI segmentation (ONNX, LV/LA) | yes (+ ~193 MB model download) | **no** (buttons hidden, `onnxruntime` excluded) |
| ASE reference (web + PDF) | yes (QtWebEngine, PyMuPDF) | **no** (QtWebEngine/fitz excluded, button hidden) |
| Reference constructor | yes (openpyxl) | **no** |
| Reference values in reports (YAML ~180 KB) | yes | **yes** (measurement-vs-normal comparison kept) |
| Measurements, Doppler, M-mode, strain/STE | yes | **yes** |
| PACS: Orthanc REST, DICOMweb (QIDO/WADO/STOW), DIMSE (C-FIND/C-GET/C-MOVE/C-STORE, built-in SCP) | yes | **yes** |
| PDF reports (reportlab) | yes | **yes** |
| Settings storage | registry/`~/.config`, passwords in the OS keyring | **portable**: files next to the exe/AppImage |

Estimated size: ~120–180 MB (instead of ~350–450 MB for the full onefile build).
Models are not downloaded and there is no first-run setup — the app starts right away.

## Portable mode (USB stick)

With `SONOFORGE_PORTABLE=1` (the default in Presenter) all data is written to a folder
**`SonoForgePresenter-data/` next to the executable**:

```
SonoForgePresenter-data/
├── preferences.ini   # QSettings → INI (instead of the Windows registry / ~/.config)
├── server.ini        # PACS server profiles
├── secrets.ini       # Fernet tokens for PACS passwords (AES-128-CBC + HMAC-SHA256)
├── device.key        # random device secret (PBKDF2 key material)
├── logs/diag.log     # server loading diagnostics
└── cache/orthanc/    # cache of downloaded DICOM instances
```

Nothing is written to the host machine except the temporary extraction directory
(Windows onefile: `%TEMP%\_MEIxxxx`, deleted on exit).

The portable directory location is resolved as follows:
1. `SONOFORGE_PORTABLE_DIR` — explicit override (tests/development);
2. the directory of the `$APPIMAGE` file (AppImage runtime) — data stays on the stick
   rather than inside the transient squashfs mount point;
3. the frozen exe's directory (`sys.executable`) — Windows onefile: that is the exe on
   the stick, not temp;
4. `SONOFORGE_PORTABLE=1` in dev mode → `./SonoForgePresenter-data` in the CWD.

> **Security:** `secrets.ini` stores PACS passwords encrypted (Fernet — AES-128-CBC +
> HMAC-SHA256, the `cryptography` package). The key is derived via PBKDF2-HMAC-SHA256
> from `device.key` — a random secret created once on the same stick. The trust model is
> like a machine-bound OS keychain: the stick's owner can recover the passwords, but the
> file is not human-readable and the ciphertexts differ across devices. Keep the stick
> with you; if it is lost, change the PACS passwords. You can disable password storage by
> leaving the password field empty in the server settings. Without `cryptography`
> installed (full profile + `SONOFORGE_PORTABLE=1`), passwords are simply not saved —
> there is no cleartext fallback.

## Running from a USB stick

- **Windows:** double-click `SonoForgePresenter.exe`. The onefile unpacks to the host's
  `%TEMP%` on each launch (USB 3.0: ~2–4 s; USB 2.0 is slower). No admin rights or
  installation required. Windows 10/11 x64.
- **Linux:** `./SonoForge-Presenter-<ver>-x86_64.AppImage` (requires FUSE; on machines
  without FUSE: `--appimage-extract-and-run`). Starts faster than the Windows onefile —
  squashfs is mounted, not unpacked.

## Building

```bash
python3 -m venv .venv && . .venv/bin/activate        # Python 3.10/3.11
pip install -r build/presenter/pinned-packages.txt pyinstaller

# Linux → AppImage
./build/presenter/build-appimage.sh
#   → dist/SonoForge-Presenter-<version>-x86_64.AppImage

# Windows → onefile exe
python -m PyInstaller build/presenter/sonoforge-presenter.spec --noconfirm --clean
#   → dist/SonoForgePresenter.exe
```

> **Dependency pins:** `pinned-packages.txt` is pinned exactly to the versions in `uv.lock`
> (reproducible builds + the dependency-review CI gate does not see "new" versions relative
> to the base graph). When updating `uv.lock`, update the pins deliberately, e.g.:
> `grep -A1 '^name = "<package>"$' uv.lock`.

CI: `.github/workflows/presenter.yml` (tag `presenter-v*` or a manual run).

## Changing the module set

The profile is a **build configuration**, not code removal:

- **Bring AI segmentation back into Presenter:** remove `onnxruntime` from `excludes` in
  the spec, add it to `pinned-packages.txt`, restore `has_ai_segmentation() → True` in
  `infrastructure/profile.py` (or remove the presenter branch), and bundle the models via
  `datas` if needed.
- **Bring the reference back:** remove `PySide6.QtWebEngine*`, `PySide6.QtWebChannel`,
  `fitz`/`pymupdf`, `openpyxl` and the app modules (`ase_reference_dialog`,
  `structured_reference_widget`, `web_reference`, `constructor`) from `excludes`; restore
  `has_reference_ui() → True`; add all of `resources/references` to `datas` (including
  images/ and PDF, +35 MB).
- **New main-profile features** are automatically available in Presenter unless they depend
  on the excluded dependencies. The degradation mechanism: a guarded import
  (`try/except ImportError`) + a profile flag + `excludes`.

## Running from source (dev)

```bash
# Presenter profile without packaging:
SONOFORGE_PROFILE=presenter SONOFORGE_PORTABLE=1 python -m echo_personal_tool.__main_presenter__

# Portable data in a specific directory (tests):
SONOFORGE_PORTABLE_DIR=/tmp/stick python -m echo_personal_tool.__main_presenter__
```

## Presenter mode (second display for the audience)

The classic "Extend these displays" (Windows) or second-monitor (Linux) presentation
scenario is supported directly — just like PowerPoint and LibreOffice Impress:

- **your monitor** — the regular SonoForge window with all panels and tools;
- **the audience display (projector)** — a separate full-screen viewer window that
  **renders itself** on that display: only the image and overlays, no thumbnail gallery,
  panels, or top bar.

Key architectural decision: the second window receives the same decoded frames and state
through signals and draws them itself — **no pixel copying** (`QWidget.grab`) between
screens. Pixel "mirroring" does not work with the pyqtgraph OpenGL viewport: grab cannot
compose GL content (a black frame on the projector), and its readbacks dimmed the main
window's image. Independent rendering eliminates both problems by construction.

Launch: the `Presenter` button in the top bar (with a dropdown arrow) or `F10`.
Exit: `F10` or clicking the button again. The demonstration window does not steal focus
or activation — the main window keeps the keyboard.

Capabilities:

- **Independent rendering** — frames, calipers, contours, M-mode/Doppler, and the results
  overlay appear in the second viewer instantly (forwarding is tied to real frame
  decoding). The W/L/DR sliders are shared — a tone edit is immediately visible to the
  audience.
- **Reliable window placement** — show → `windowHandle().setScreen()` → fullscreen with a
  deferred check (a known Qt issue: `setScreen` before showing the window does not survive
  the platform-window creation). The status line reports the actual demonstration display.
- **Projector visual profile** (enabled by default): thicker lines and contours (3.5 px),
  larger fonts (14 pt UI, 24 pt overlay, opacity 0.85), inline caliper labels. Only for the
  duration of the show; user settings are restored on exit.
- **Pointer** — a large semi-transparent red dot follows the presenter's mouse (exact
  mapping through the shared image).
- **Display selection** — the button's menu; by default, the display that does NOT contain
  the application window. It is remembered (`presenter_screen`). The demonstration window
  is read-only: clicks/wheel are absorbed.
- The button/mode is available **only in the Presenter (lite) build**: in the full build the
  button, its menu, and `F10` are not created.

Related improvements: `F11` — fullscreen kiosk mode; the Presenter profile offers a narrow
activity bar (caliper, play/pause, HR, LV2D, ESV/EDV/ES), but by default, as in the full
profile, the wide tool panel opens.

Benchmark: `QT_QPA_PLATFORM=offscreen python bench/presenter_mirror_bench.py`.

### Audience-screen rendering and diagnostics

- The demonstration window's render backend is set by the `presenter_audience_render`
  preference (default `raster`, option `opengl`). A raster viewport was chosen deliberately:
  on a real multi-monitor Linux machine (Debian 12, Qt 6.4, Intel) the second window's GL
  viewport stayed black, while the same window's raster overlays drew fine; the presenter's
  backend is unchanged (auto-detected in `main()`).
- The mode writes a file log `presenter_diag.log` in the same directory as the regular
  `diag.log` (`profile.diag_log_dir()`): environment (Qt, pyqtgraph, useOpenGL, the screen
  list with geometry and DPR), every window-placement step, frame/error counters with
  tracebacks, a 1 Hz probe of both viewers' frame data and the audience GL framebuffer
  brightness. Disabled by `SONOFORGE_PRESENTER_DIAG=0`; off by default under pytest.
- Protection against a stale `presenter_screen`: if the remembered name matches the
  application screen and another display exists, the value is ignored (otherwise the
  full-screen demonstration covers the working window and the status warning stays under it).
- A keepalive repaint of the presenter's viewer (250 ms) counters the Qt 6.4 "fading when
  idle" of the main window image; adaptive forwarding pacing (every 2nd/3rd frame when
  rendering is expensive) protects playback on the presenter's side.
- Contours and calipers are synchronized to the demonstration window via direct
  `contours_changed` / `linear_measurements_changed` forwards: the controller saves edits
  (dragging Simpson manual / auto-Simpson points, calipers) with `emit=False`, so without
  forwarding the audience would only see the initial contour. The update arrives on mouse
  release.
- Contour edits are synchronized as fresh contour copies through `apply_contours`
  (unconditional redraw): the host mutates the contour points in place, and a by-value
  comparison in `set_state` would otherwise skip the update (the audience would alias the
  same point lists).
- Doppler is mirrored in full (peak/interval markers, VTI and vessel traces, axis
  calibration, PSV/EDV) via the `forward_doppler` signal — this data lives locally in the
  viewer and does not reach `state_changed`.
- The drawing process is demonstrated in real time (~30 Hz): the active contour (click
  points/freehand) and the preliminary caliper line are mirrored to the demonstration
  window; after commitment the result is drawn persistently and the preview is hidden. Same
  for dragging points of an existing contour (the polyline of the active drag session), the
  vessel-mode auto-trace envelope, and the orange beam guide. Also the vessel measurement
  results: the PSV/EDV/RI/S/D text block at the top edge of the Doppler strip (with exact
  formatting and position) and the PSV/EDV points.
- Frame-forwarding pacing applies only during playback/scroll — static frames (file change,
  step, navigation) are always rendered: the single file-change frame cannot be skipped.
- Dragging the results overlay is mirrored via the `forward_results_overlay_position`
  signal; the initial position is passed at presentation start.

## Smoke tests

```bash
SONOFORGE_PROFILE=presenter QT_QPA_PLATFORM=offscreen \
  python -m pytest tests/unit/test_presenter_profile.py tests/unit/test_presenter_view.py -q
```
