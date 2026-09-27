# Build

> [Русская версия](README_RU.md)

Scripts and configuration for building the application. All scripts are run
**from the repository root**.

## Structure

| Folder | Description |
|--------|-------------|
| `linux/` | Linux build (.deb / portable folder) |
| `windows/` | Windows build (.zip / one-file) |
| `presenter/` | **SonoForge Presenter** — lightweight portable profile (onefile .exe / AppImage), see [`presenter/README.md`](presenter/README.md) |

## Linux (`linux/`)

| File | Description |
|------|-------------|
| `build.sh` | Portable folder (PyInstaller, folder mode) |
| `build-lite.sh` | Lightweight .deb (~50 MB, code only; dependencies and models are fetched on first run) |
| `build-deb.sh` | Full .deb with everything bundled (PyInstaller onedir, models inside) |
| `build.spec` | PyInstaller spec for the folder build |
| `sonoforge-launcher` | Bash launcher with automatic dependency installation |

The Linux desktop entry lives in [`scripts/sonoforge.desktop`](../scripts/sonoforge.desktop).

## Windows (`windows/`)

| File | Description |
|------|-------------|
| `build.bat` | Full build (PyInstaller) |
| `build-lite.bat` | Lightweight .zip (~50 MB, dependencies fetched on first run) |
| `build.spec` | PyInstaller spec |
| `sonoforge-launcher.bat` | Batch launcher with automatic installation |

Related files at the root and in `scripts/`:
[`sonoforge-standalone.spec`](../sonoforge-standalone.spec) (one-file spec, used by
the CI workflows `build.yml`/`release.yml`), [`installer_stub.py`](../installer_stub.py) and
[`scripts/create_installer.py`](../scripts/create_installer.py) (self-extracting
installer), [`scripts/setup.bat`](../scripts/setup.bat) /
[`scripts/uninstall.bat`](../scripts/uninstall.bat), [`launcher.py`](../launcher.py)
(launcher for the lightweight builds: finds Python, installs dependencies, downloads models).

## Building

```bash
# Linux: lightweight .deb
./build/linux/build-lite.sh

# Linux: full .deb
./build/linux/build-deb.sh [--clean]

# Windows (from Windows)
build\windows\build-lite.bat

# SonoForge Presenter (lite portable profile)
./build/presenter/build-appimage.sh                       # Linux → AppImage
python -m PyInstaller build/presenter/sonoforge-presenter.spec --noconfirm --clean   # Windows → onefile .exe
```

CI builds (release artifacts) are described in
[`.github/workflows/build.yml`](../.github/workflows/build.yml) and
[`.github/workflows/release.yml`](../.github/workflows/release.yml);
the Presenter profile is in [`.github/workflows/presenter.yml`](../.github/workflows/presenter.yml).
