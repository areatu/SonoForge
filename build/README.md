# Build

Скрипты и конфигурации для сборки приложения. Все скрипты запускаются **из корня репозитория**.

## Структура

| Папка | Описание |
|-------|----------|
| `linux/` | Сборка для Linux (.deb / portable-папка) |
| `windows/` | Сборка для Windows (.zip / one-file) |

## Linux (`linux/`)

| Файл | Описание |
|------|----------|
| `build.sh` | Portable-папка (PyInstaller, folder mode) |
| `build-lite.sh` | Лёгкий .deb (~50 МБ, только код; зависимости и модели докачиваются при первом запуске) |
| `build-deb.sh` | Полный .deb со всем содержимым (PyInstaller onedir, модели внутри) |
| `build.spec` | PyInstaller spec для folder-сборки |
| `sonoforge-launcher` | Bash-лаунчер с автоустановкой зависимостей |

Desktop entry для Linux лежит в [`scripts/sonoforge.desktop`](../scripts/sonoforge.desktop).

## Windows (`windows/`)

| Файл | Описание |
|------|----------|
| `build.bat` | Полная сборка (PyInstaller) |
| `build-lite.bat` | Лёгкий .zip (~50 МБ, зависимости докачиваются) |
| `build.spec` | PyInstaller spec |
| `sonoforge-launcher.bat` | Batch-лаунчер с автоустановкой |

Сопутствующие файлы в корне и в `scripts/`:
[`sonoforge-standalone.spec`](../sonoforge-standalone.spec) (one-file spec, используется
CI-воркфлоу `build.yml`/`release.yml`), [`installer_stub.py`](../installer_stub.py) и
[`scripts/create_installer.py`](../scripts/create_installer.py) (self-extracting
установщик), [`scripts/setup.bat`](../scripts/setup.bat) /
[`scripts/uninstall.bat`](../scripts/uninstall.bat), [`launcher.py`](../launcher.py)
(лаунчер лёгких сборок: ищет Python, ставит зависимости, качает модели).

## Сборка

```bash
# Linux: лёгкий .deb
./build/linux/build-lite.sh

# Linux: полный .deb
./build/linux/build-deb.sh [--clean]

# Windows (из-под Windows)
build\windows\build-lite.bat
```

CI-сборки (релизные артефакты) описаны в
[`.github/workflows/build.yml`](../.github/workflows/build.yml) и
[`.github/workflows/release.yml`](../.github/workflows/release.yml).
