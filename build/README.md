# Build

> [Русская версия](README_RU.md)

Scripts and configuration for building the application. All scripts are run
**from the repository root**.

## Structure

| Folder | Description |
|--------|-------------|
| `linux/` | Linux build (.deb / portable folder) |
| `windows/` | Full Windows installer and versioned portable executable, plus the lightweight ZIP build |
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
| `build.bat` | Builds the onefile portable executable and the onedir installer payload; compiles the setup EXE when Inno Setup 6 is installed |
| `build-lite.bat` | Lightweight ZIP build (~50 MB, dependencies fetched on first run) |
| `build.spec` | PyInstaller onedir spec used by the installer |
| `sonoforge.iss` | Inno Setup script: per-user by default, with an all-users option |
| `sonoforge-launcher.bat` | Batch launcher for the lightweight build |

The Windows release publishes `SonoForge-Setup-<version>-x64.exe` and
`SonoForge-<version>-portable.exe`. The existing `SonoForge.exe` URL is also
kept as a compatibility alias for the portable executable.

The root [`sonoforge-standalone.spec`](../sonoforge-standalone.spec) builds the
onefile portable application. The legacy zip-stub installer (`installer_stub.py`
and `scripts/create_installer.py`) has been retired. The separate
[`scripts/setup.bat`](../scripts/setup.bat) and
[`scripts/uninstall.bat`](../scripts/uninstall.bat) remain for the lightweight
ZIP package only; [`launcher.py`](../launcher.py) is its Python/dependency
bootstrapper.

## Building

```bash
# Linux: lightweight .deb
./build/linux/build-lite.sh

# Linux: full .deb
./build/linux/build-deb.sh [--clean]

# Windows full packages (from Windows; requires Inno Setup 6 for the installer)
build\windows\build.bat

# Windows lightweight ZIP
build\windows\build-lite.bat

# SonoForge Presenter (lite portable profile)
./build/presenter/build-appimage.sh                       # Linux → AppImage
python -m PyInstaller build/presenter/sonoforge-presenter.spec --noconfirm --clean   # Windows → onefile .exe
```

CI builds (release artifacts) are described in
[`.github/workflows/build.yml`](../.github/workflows/build.yml) and
[`.github/workflows/release.yml`](../.github/workflows/release.yml);
the Presenter profile is in [`.github/workflows/presenter.yml`](../.github/workflows/presenter.yml).
