# Build

> [English version](README.md)

Скрипты и конфигурации для сборки приложения. Все скрипты запускаются **из корня репозитория**.

## Структура

| Папка | Описание |
|-------|----------|
| `linux/` | Сборка для Linux (.deb / portable-папка) |
| `windows/` | Windows-установщик и версионированный portable-exe, а также облегчённый ZIP |
| `presenter/` | **SonoForge Presenter** — лёгкий портативный профиль (onefile .exe / AppImage), см. [`presenter/README.md`](presenter/README.md) |

## Linux (`linux/`)

| Файл | Описание |
|-------|----------|
| `build.sh` | Portable-папка (PyInstaller, folder mode) |
| `build-lite.sh` | Лёгкий .deb (~50 МБ, только код; зависимости и модели докачиваются при первом запуске) |
| `build-deb.sh` | Полный .deb со всем содержимым (PyInstaller onedir, модели внутри) |
| `build.spec` | PyInstaller spec для folder-сборки |
| `sonoforge-launcher` | Bash-лаунчер с автоустановкой зависимостей |

Desktop entry для Linux лежит в [`scripts/sonoforge.desktop`](../scripts/sonoforge.desktop).

## Windows (`windows/`)

| Файл | Описание |
|-------|----------|
| `build.bat` | Собирает onefile portable-приложение и onedir-папку для установщика; компилирует setup EXE при наличии Inno Setup 6 |
| `build-lite.bat` | Облегчённая ZIP-сборка (~50 МБ, зависимости докачиваются при первом запуске) |
| `build.spec` | PyInstaller onedir spec, используемый установщиком |
| `sonoforge.iss` | Inno Setup: установка для текущего пользователя по умолчанию, с выбором установки для всех |
| `sonoforge-launcher.bat` | Batch-лаунчер облегчённой сборки |

Windows-релиз публикует `SonoForge-Setup-<version>-x64.exe` и
`SonoForge-<version>-portable.exe`. Для обратной совместимости также сохраняется
ссылка `SonoForge.exe` на тот же portable-файл.

Корневой [`sonoforge-standalone.spec`](../sonoforge-standalone.spec) собирает
onefile portable-приложение. Старый self-extracting ZIP-stub-поток
(`installer_stub.py` и `scripts/create_installer.py`) выведен из эксплуатации.
Отдельные [`scripts/setup.bat`](../scripts/setup.bat) и
[`scripts/uninstall.bat`](../scripts/uninstall.bat) остаются только для лёгкого
ZIP-пакета; [`launcher.py`](../launcher.py) устанавливает зависимости для этой сборки.

## Сборка

```bash
# Linux: лёгкий .deb
./build/linux/build-lite.sh

# Linux: полный .deb
./build/linux/build-deb.sh [--clean]

# Windows: полные пакеты (из-под Windows; для установщика нужен Inno Setup 6)
build\windows\build.bat

# Windows: облегчённый ZIP
build\windows\build-lite.bat

# SonoForge Presenter (lite portable профиль)
./build/presenter/build-appimage.sh                       # Linux → AppImage
python -m PyInstaller build/presenter/sonoforge-presenter.spec --noconfirm --clean   # Windows → onefile .exe
```

CI-сборки (релизные артефакты) описаны в
[`.github/workflows/build.yml`](../.github/workflows/build.yml) и
[`.github/workflows/release.yml`](../.github/workflows/release.yml);
Presenter-профиль — в [`.github/workflows/presenter.yml`](../.github/workflows/presenter.yml).
