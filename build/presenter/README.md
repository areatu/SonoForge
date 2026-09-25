# SonoForge Presenter (lite portable profile)

**SonoForge Presenter** — облегчённый портативный профиль SonoForge для
демонстраций с флешки на чужих компьютерах (проектор, «между слайдами»).
Собирается из **того же исходного дерева**, что и полный SonoForge: профиль
включается переменной окружения `SONOFORGE_PROFILE=presenter` (точка входа
`__main_presenter__.py`), а тяжёлые модули исключаются на этапе упаковки
(`sonoforge-presenter.spec`). Код основного профиля не изменяется
деструктивно — все правки аддитивны (guarded/lazy-импорты).

## Состав продукта

| | Полный SonoForge | Presenter |
|---|---|---|
| AI-сегментация (ONNX, ЛЖ/ЛП) | да (+скачивание моделей ~193 МБ) | **нет** (кнопки скрыты, `onnxruntime` исключён) |
| Справочник ASE (web + PDF) | да (QtWebEngine, PyMuPDF) | **нет** (QtWebEngine/fitz исключены, кнопка скрыта) |
| Конструктор справочника | да (openpyxl) | **нет** |
| Нормативы в отчётах (YAML ~180 КБ) | да | **да** (сравнение измерений с нормой сохранено) |
| Измерения, доплер, M-mode, strain/STE | да | **да** |
| PACS: Orthanc REST, DICOMweb (QIDO/WADO/STOW), DIMSE (C-FIND/C-GET/C-MOVE/C-STORE, встроенный SCP) | да | **да** |
| Отчёты PDF (reportlab) | да | **да** |
| Хранение настроек | реестр/`~/.config`, пароли в OS keyring | **portable**: файлы рядом с exe/AppImage |

Оценка размера: ~120–180 МБ (вместо ~350–450 МБ полного onefile-сборки).
Модели не скачиваются, first-run setup отсутствует — старт сразу в приложение.

## Portable-режим (флешка)

При `SONOFORGE_PORTABLE=1` (по умолчанию в Presenter) все данные пишутся
в папку **`SonoForgePresenter-data/` рядом с исполняемым файлом**:

```
SonoForgePresenter-data/
├── preferences.ini   # QSettings → INI (вместо реестра Windows / ~/.config)
├── server.ini        # профили PACS-серверов
├── secrets.json      # пароли PACS (XOR+base64 — ОБФУСКАЦИЯ, не шифрование!)
├── logs/diag.log     # диагностика загрузки с сервера
└── cache/orthanc/    # кэш скачанных DICOM-инстансов
```

На хост-машину не пишется ничего, кроме временного каталога распаковки
(Windows onefile: `%TEMP%\_MEIxxxx`, удаляется при выходе).

Расположение portable-каталога определяется так:
1. `SONOFORGE_PORTABLE_DIR` — явное переопределение (тесты/разработка);
2. каталог файла из `$APPIMAGE` (AppImage-рантайм) — данные остаются на флешке,
   а не внутри временной squashfs-точки монтирования;
3. каталог замороженного exe (`sys.executable`) — Windows onefile: это сам
   exe на флешке, а не temp;
4. `SONOFORGE_PORTABLE=1` в dev-режиме → `./SonoForgePresenter-data` в CWD.

> **Безопасность:** `secrets.json` хранит пароли PACS в обфусцированном виде
> (XOR + base64). Любой, у кого есть флешка, может их восстановить. Держите
> флешку при себе; при потере — смените пароли PACS. Отключить сохранение
> паролей можно, не заполняя поле пароля в настройках сервера.

## Запуск с флешки

- **Windows:** `SonoForgePresenter.exe` двойным кликом. Onefile распаковывается
  в `%TEMP%` хоста при каждом запуске (USB 3.0: ~2–4 с; USB 2.0 дольше).
  Права администратора и установка не нужны. Windows 10/11 x64.
- **Linux:** `./SonoForge-Presenter-<ver>-x86_64.AppImage` (нужен FUSE;
  на машинах без FUSE: `--appimage-extract-and-run`). Стартует быстрее
  Windows-onefile — squashfs монтируется, а не распаковывается.

## Сборка

```bash
python3 -m venv .venv && . .venv/bin/activate        # Python 3.10/3.11
pip install -r build/presenter/requirements-presenter.txt pyinstaller

# Linux → AppImage
./build/presenter/build-appimage.sh
#   → dist/SonoForge-Presenter-<version>-x86_64.AppImage

# Windows → onefile exe
python -m PyInstaller build/presenter/sonoforge-presenter.spec --noconfirm --clean
#   → dist/SonoForgePresenter.exe
```

> **Пины зависимостей:** `requirements-presenter.txt` запинен ровно на
> версии из `uv.lock` (воспроизводимость сборок + CI-гейт dependency-review
> не видит «новых» версий относительно базового графа). При обновлении
> `uv.lock` обновляйте пины осознанно, например:
> `grep -A1 '^name = "<пакет>"$' uv.lock`.

CI: `.github/workflows/presenter.yml` (тег `presenter-v*` или ручной запуск).

## Как менять состав модулей

Профиль — это **конфигурация сборки**, а не удаление кода:

- **Вернуть AI-сегментацию в Presenter:** убрать `onnxruntime` из `excludes`
  в spec, добавить его в `requirements-presenter.txt`, вернуть
  `has_ai_segmentation() → True` в `infrastructure/profile.py` (или убрать
  presenter-ветку), при необходимости бандлить модели через `datas`.
- **Вернуть справочник:** убрать из `excludes` `PySide6.QtWebEngine*`,
  `PySide6.QtWebChannel`, `fitz`/`pymupdf`, `openpyxl` и app-модули
  (`ase_reference_dialog`, `structured_reference_widget`, `web_reference`,
  `constructor`); вернуть `has_reference_ui() → True`; добавить в `datas`
  `resources/references` целиком (включая images/ и PDF, +35 МБ).
- **Новые фичи основного профиля** автоматически доступны в Presenter,
  если не завязаны на исключённые зависимости. Механизм деградации:
  guarded-импорт (`try/except ImportError`) + флаг профиля + `excludes`.

## Запуск из исходников (dev)

```bash
# Presenter-профиль без упаковки:
SONOFORGE_PROFILE=presenter SONOFORGE_PORTABLE=1 python -m echo_personal_tool.__main_presenter__

# Portable-данные в конкретный каталог (тесты):
SONOFORGE_PORTABLE_DIR=/tmp/stick python -m echo_personal_tool.__main_presenter__
```

## Smoke-тесты

```bash
SONOFORGE_PROFILE=presenter QT_QPA_PLATFORM=offscreen \
  python -m pytest tests/unit/test_presenter_profile.py -q
```
