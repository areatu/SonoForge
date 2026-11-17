# Сборка артефактов SonoForge: macOS Intel и Windows 11

**Дата:** 2026-10-22
**Область:** локальная сборка артефактов из `main` для ручной приёмки.
**Исходные точки:** `pyproject.toml`, `sonoforge-standalone.spec`,
`build/windows/build.bat`, `build/windows/build.spec`,
`build/windows/sonoforge.iss`, `build/presenter/sonoforge-presenter.spec`,
`.github/workflows/release.yml`.

---

## 0. Что важно знать до начала

### 0.1. Linux не собирает артефакты для macOS и Windows

PyInstaller **не выполняет кросс-компиляцию**. На Linux нельзя получить:

- `.app`/`.dmg` для macOS: нужны macOS, `hdiutil`, `codesign`, `spctl`;
- `.exe` для Windows: нужен Windows и Inno Setup (`ISCC.exe`);
- подпись/нотаризацию Apple: только на macOS с Apple Developer ID.

Сборка каждого артефакта идёт на своей ОС. Linux остаётся платформой
CI-тестов и `.deb`, но не заменяет сборочный Mac/Windows.

### 0.2. Что собирает CI, а что придётся собрать локально

`.github/workflows/release.yml` собирает:

| Платформа | Артефакты CI | Ограничение |
|---|---|---|
| Windows | `SonoForge-Setup-<ver>-x64.exe`, `SonoForge-<ver>-portable.exe` | x64, Python 3.11 |
| macOS | `SonoForge-<ver>-macos-arm64.dmg` | **только Apple Silicon (arm64)** |
| Linux | `.deb` | не относится к этой инструкции |

**Intel-сборки macOS в CI нет.** Для Mac mini 2018 (x86_64) DMG нужно
собирать локально по §2. Это не ошибка: `macos-latest` — arm64-раннер, а
`target_arch=None` в spec означает «архитектура сборочной машины».

### 0.3. Версия и HEAD

Версия берётся из `src/echo_personal_tool/__init__.py` и подставляется в
имя артефакта, `CFBundleShortVersionString` (macOS) и PE-ресурс (Windows).

Перед сборкой зафиксируйте:

```bash
git fetch origin
git log --oneline -1 origin/main
git rev-parse --short HEAD
```

Версия:

```bash
python -c "import sys; sys.path.insert(0, 'src'); from echo_personal_tool import __version__; print(__version__)"
```

Дальше `<ver>` — это выведенное значение.

### 0.4. Куда кладутся результаты

| ОС | Каталог | Что появится |
|---|---|---|
| macOS | `dist/` | `SonoForge.app`, `.dmg` |
| Windows | `dist/` | portable `.exe`, `SonoForge\`, Setup `.exe`, Presenter `.exe` |

`dist/` и `build/` — рабочие каталоги PyInstaller; в git они не коммитятся.

### 0.5. Модели не входят в артефакт

Модели ONNX скачиваются при первом запуске с GitHub Releases в каталог данных
пользователя. Поэтому:

- чистая машина без интернета покажет диалог загрузки и не запустит AI-функции;
- для приёмки заранее проверьте доступ к `github.com`;
- размер `.app`/`.exe` — сотни мегабайт, но не гигабайты из-за моделей.

---

## 1. Общие требования

| Компонент | macOS Intel | Windows 11 |
|---|---|---|
| ОС | macOS 13+ (проверено на 15.8.1) | Windows 11 x64 |
| Python | **3.10.x** | **3.11.x x64** |
| Сборщик | PyInstaller (ставится pip) | PyInstaller + Inno Setup 6 |
| Свободное место | 4–6 ГБ | 4–6 ГБ |
| Интернет | нужен для зависимостей и первого запуска | то же |
| Права | пользовательские; `sudo` только для Xcode CLT | пользовательские; UAC для «for all users» |

### 1.1. Почему на macOS Intel именно Python 3.10

`uv.lock` для Python 3.11 фиксирует `onnxruntime 1.26.0`, у которого на PyPI
нет wheel для macOS x86_64 (только arm64). На Python 3.10 разрешается
`onnxruntime 1.23.2` с wheel `macosx_13_0_x86_64`.

Если запустить `uv sync` на Intel с Python 3.11, установка зависимостей
упадёт. Это ожидаемо, а не дефект приложения. На Windows 3.11 подходит:
там wheel `win_amd64` есть.

### 1.2. Чистая сборка

Перед релизной сборкой:

```bash
rm -rf build dist
```

На Windows:

```powershell
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
```

`--clean` у PyInstaller очищает кэш, но не заменяет удаление старых
`build/`/`dist/`, если нужно гарантированно исключить старые файлы.

---

## 2. macOS Intel: пошаговая сборка

Проверено для Mac mini 2018 (Intel Core i5, UHD 630, 32 ГБ, macOS 15.8.1).
На других Intel Mac с macOS 13+ шаги те же.

### 2.1. Подготовка Xcode Command Line Tools

```bash
xcode-select --install
```

Если инструменты уже стоят, команда сообщит об этом. При необходимости
примите лицензию:

```bash
sudo xcodebuild -license accept
```

Проверка:

```bash
xcode-select -p
clang --version
```

PyInstaller использует системный `clang` для сборки/подписи вспомогательных
бинарников; без CLT сборка может упасть на этапе bootloader/codesign.

### 2.2. Установка Python 3.10

Вариант A, через `uv` (рекомендуется, если `uv` уже есть):

```bash
uv python install 3.10
uv python find 3.10
```

Вариант B, установщик python.org:

1. Скачайте **Python 3.10.11 macOS 64-bit universal2 installer**.
2. Установите.
3. Проверьте:

```bash
python3.10 --version
python3.10 -c "import platform; print(platform.machine())"
```

На Intel ожидается `x86_64`.

Вариант C, Homebrew:

```bash
brew install python@3.10
```

Homebrew на Intel-маках с macOS 15 обычно доступен; если brew не установлен,
не тратьте время — используйте python.org или `uv`.

### 2.3. Получение исходников

```bash
git clone https://github.com/areatu/SonoForge.git
cd SonoForge
git checkout main
git pull --ff-only
git log --oneline -1
```

Не собирайте из старого рабочего каталога с незакоммиченными правками: для
приёмки нужен артефакт, соответствующий зафиксированному HEAD.

### 2.4. Виртуальное окружение и зависимости

Вариант A, `uv`:

```bash
uv venv --python 3.10 .venv
source .venv/bin/activate
uv sync --python 3.10
uv pip install pyinstaller
```

Вариант B, `pip`:

```bash
python3.10 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
python -m pip install pyinstaller
```

Проверка, что окружение правильное:

```bash
python -c "import sys, platform; print(sys.version); print(platform.machine())"
python -c "import PySide6, onnxruntime; print(PySide6.__version__, onnxruntime.__version__)"
```

Ожидается Python 3.10.x, `x86_64`, PySide6 6.11.x, onnxruntime 1.23.x.

Если `onnxruntime` не ставится, проверьте, что вы не в Python 3.11:

```bash
python -c "import sys; print(sys.version_info[:2])"
```

### 2.5. Сборка `.app`

Из корня репозитория, с активированным окружением:

```bash
python -m PyInstaller sonoforge-standalone.spec --noconfirm --clean
```

Ожидаемый результат:

```text
dist/SonoForge.app
```

Проверка архитектуры и версии:

```bash
file dist/SonoForge.app/Contents/MacOS/SonoForge
lipo -info dist/SonoForge.app/Contents/MacOS/SonoForge
defaults read "$PWD/dist/SonoForge.app/Contents/Info" CFBundleShortVersionString
```

На Intel:

```text
Mach-O 64-bit executable x86_64
Non-fat file: ... is architecture: x86_64
```

Если увидели `arm64`, вы собрали не на той машине/не тем Python.

### 2.6. Быстрый smoke-тест до упаковки

```bash
open dist/SonoForge.app
```

Если приложение не открывается, запустите бинарник из терминала и посмотрите
stderr:

```bash
dist/SonoForge.app/Contents/MacOS/SonoForge
```

Проверьте:

1. Появилось окно или приветственная страница.
2. «О программе» показывает ту же версию, что `<ver>`.
3. Первый запуск предлагает скачать модели (если каталога моделей нет).
4. Приложение не требует установленного Python — это уже бандл.

### 2.7. Сборка DMG

```bash
VERSION=$(python -c "import sys; sys.path.insert(0, 'src'); from echo_personal_tool import __version__; print(__version__)")
hdiutil create \
  -volname "SonoForge" \
  -srcfolder dist/SonoForge.app \
  -ov -format UDZO \
  "dist/SonoForge-${VERSION}-macos-intel.dmg"
hdiutil verify "dist/SonoForge-${VERSION}-macos-intel.dmg"
shasum -a 256 "dist/SonoForge-${VERSION}-macos-intel.dmg" \
  > "dist/SonoForge-${VERSION}-macos-intel.dmg.sha256"
```

Имя `macos-intel` важно: оно отличает локальную x86_64-сборку от CI-артефакта
`macos-arm64`.

### 2.8. Неподписанное приложение и Gatekeeper

Локальная сборка не подписана Apple Developer ID и не нотаризована. Это
ожидаемо до закрытия G5b.

Если DMG передан через интернет/мессенджер и macOS ставит карантин:

```bash
xattr -dr com.apple.quarantine /Applications/SonoForge.app
open /Applications/SonoForge.app
```

Либо:

1. Перетащите `SonoForge.app` в `/Applications`.
2. Кликните правой кнопкой → «Открыть» → «Открыть».
3. Или: «Системные настройки» → «Конфиденциальность и безопасность» →
   «Всё равно открыть».

Не обещайте пользователям «подписано/нотаризовано»: в текущем состоянии это
не так. Проверка:

```bash
spctl -a -vv -t execute /Applications/SonoForge.app
codesign -dv --verbose=4 /Applications/SonoForge.app
```

Ожидаемо: `rejected` у `spctl`, ad-hoc/без Developer ID у `codesign`.

### 2.9. Presenter на macOS

`build/presenter/sonoforge-presenter.spec` явно завершается с ошибкой на
macOS: профиль Presenter поддерживает только Windows и Linux. Для
macOS-приёмки пункт Presenter отмечается «Н/П».

### 2.10. Типовые ошибки macOS

| Симптом | Причина | Решение |
|---|---|---|
| `No module named PySide6` | не активировано окружение | `source .venv/bin/activate` |
| `uv sync` падает на `onnxruntime` | Python 3.11 на Intel | пересоздать venv на 3.10 |
| `hdiutil: create failed` | нет `dist/SonoForge.app` | сначала успешно выполнить §2.5 |
| Приложение «повреждено» | карантин неподписанного `.app` | `xattr -dr com.apple.quarantine` |
| `arm64` в `file` | сборка на Apple Silicon/другом Python | собрать на Intel с Python 3.10 |
| Пустое окно/краш при старте | несовместимая версия Qt/зависимостей | удалить `build/ dist/`, пересобрать с `--clean` |
| `codesign` ругается на entitlements | локальная сборка без подписи | для приёмки достаточно ad-hoc; подпись — G5b |

---

## 3. Windows 11: пошаговая сборка

### 3.1. Установка Python 3.11 x64

1. Скачайте Python 3.11.x для Windows (64-bit).
2. При установке включите **Add python.exe to PATH**.
3. Проверьте в новом окне PowerShell:

```powershell
py -3.11 --version
python --version
```

Оба должны показать 3.11.x. Если `python` указывает на другую версию,
используйте `py -3.11` или поправьте PATH.

### 3.2. Установка Inno Setup 6

Установщик нужен только для `SonoForge-Setup-*-x64.exe`; portable и onedir
соберутся и без него.

Вариант A:

```powershell
winget install -e --id JRSoftware.InnoSetup
```

Вариант B: скачать с `jrsoftware.org` и установить.

Проверка:

```powershell
& "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" /?
```

Если команда не находится, перезапустите терминал после установки.

### 3.3. Получение исходников

```powershell
git clone https://github.com/areatu/SonoForge.git
Set-Location SonoForge
git checkout main
git pull --ff-only
git log --oneline -1
```

Если git не установлен, скачайте ZIP с GitHub и распакуйте в путь без пробелов,
например `C:\src\SonoForge`.

### 3.4. Виртуальное окружение и зависимости

```powershell
py -3.11 -m venv .venv
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
python -m pip install pyinstaller
```

Проверка:

```powershell
python -c "import sys; print(sys.version)"
python -c "import PySide6, onnxruntime; print(PySide6.__version__, onnxruntime.__version__)"
```

### 3.5. Сборка одной командой (рекомендуется)

Из корня репозитория, в активированном окружении:

```cmd
build\windows\build.bat
```

Скрипт:

1. ставит `-e .` и PyInstaller;
2. собирает onefile portable через `sonoforge-standalone.spec`;
3. собирает onedir payload через `build\windows\build.spec`;
4. при наличии `ISCC.exe` компилирует Setup.

Ожидаемые файлы:

```text
dist\SonoForge-<ver>-portable.exe
dist\SonoForge\SonoForge.exe
dist\SonoForge-Setup-<ver>-x64.exe
```

Если Inno Setup не найден, скрипт завершится без Setup, но portable и onedir
останутся. Это видно в выводе `[4/4] ISCC not found`.

### 3.6. Сборка вручную (если скрипт не подходит)

PowerShell:

```powershell
$version = python -c "import sys; sys.path.insert(0,'src'); from echo_personal_tool import __version__; print(__version__)"

python -m PyInstaller sonoforge-standalone.spec --noconfirm --clean
Copy-Item dist\SonoForge.exe "dist\SonoForge-$version-portable.exe"

python -m PyInstaller build\windows\build.spec --noconfirm --clean

& "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" "/DMyAppVersion=$version" build\windows\sonoforge.iss
```

Важно: Setup компилируется **после** onedir-сборки, потому что `.iss` берёт
файлы из `dist\SonoForge\`.

### 3.7. Проверка артефактов

```powershell
Get-Item dist\SonoForge-*-portable.exe, dist\SonoForge-Setup-*-x64.exe |
  Select-Object Name, Length

Get-FileHash dist\SonoForge-Setup-*-x64.exe -Algorithm SHA256
Get-FileHash dist\SonoForge-*-portable.exe -Algorithm SHA256
```

Неподписанная локальная сборка:

```powershell
Get-AuthenticodeSignature dist\SonoForge-Setup-*-x64.exe |
  Format-List Status, StatusMessage, SignerCertificate
```

Ожидаемо `NotSigned`. SmartScreen при запуске покажет «Unknown publisher» —
это ожидаемо до G5b, не считайте это дефектом приложения.

### 3.8. Smoke-тест установщика

1. Запустите `dist\SonoForge-Setup-<ver>-x64.exe`.
2. По умолчанию установка per-user, без UAC; «for all users» — через диалог,
   с UAC.
3. После установки проверьте:
   - `%LOCALAPPDATA%\Programs\SonoForge\SonoForge.exe`;
   - ярлык в меню «Пуск»;
   - ярлык на рабочем столе (если выбран).
4. Запустите, откройте тестовое исследование, закройте.
5. Удалите через «Параметры → Приложения»; каталог данных
   `%LOCALAPPDATA%\SonoForge` должен сохраниться (данные не удаляются).

Portable:

```powershell
dist\SonoForge-<ver>-portable.exe
```

Portable не требует установки и не пишет в `Program Files`.

### 3.9. Presenter (только Windows/Linux)

```powershell
python -m pip install -e ".[presenter]"
python -m PyInstaller build\presenter\sonoforge-presenter.spec --noconfirm --clean
```

Ожидаемый файл:

```text
dist\SonoForgePresenter.exe
```

Это onefile-профиль для запуска с USB. В CI он собирается отдельным
workflow; для приёмки Windows-артефакт Presenter нужен, если он входит в
переданный набор.

### 3.10. Типовые ошибки Windows

| Симптом | Причина | Решение |
|---|---|---|
| `python` не найден | PATH | переустановить с «Add to PATH» или `py -3.11` |
| `Activate.ps1 cannot be loaded` | Execution Policy | `Set-ExecutionPolicy -Scope Process Bypass` |
| Setup не создан | нет Inno Setup 6 | установить, перезапустить терминал |
| `ISCC` не найден | нестандартный путь | `where ISCC.exe`, добавить в PATH |
| Ошибка доступа к `dist` | приложение запущено | закрыть SonoForge, удалить `dist` |
| Долгие пути | глубокий каталог | собирать в `C:\src\SonoForge` |
| Антивирус удаляет `.exe` | эвристика PyInstaller | добавить исключение на `dist` |
| SmartScreen «Unknown publisher» | нет подписи | ожидаемо; см. G5b |
| `onnxruntime` не ставится | разрядность Python | использовать x64 Python 3.11 |

---

## 4. Что передать проверяющему

Для каждой ОС передайте одним архивом:

1. Артефакт:
   - macOS: `SonoForge-<ver>-macos-intel.dmg`;
   - Windows: `SonoForge-Setup-<ver>-x64.exe` и/или portable `.exe`;
   - Windows Presenter (если нужен): `SonoForgePresenter.exe`.
2. Файл(ы) SHA-256.
3. Версию и HEAD:
   - `SonoForge <ver>`, `git rev-parse --short HEAD`.
4. Тестовые данные (обезличенные):
   - исследование с 3+ клипами: B-mode, допплер, M-mode;
   - одиночный DICOM-файл;
   - клип с сохранёнными измерениями;
   - отчёт с незаполненными разделами.
5. Чек-лист для соответствующей ОС:
   - `docs/reviews/2026-10-22-acceptance-checklist-macos-intel-ru.md`;
   - `docs/reviews/2026-10-22-acceptance-checklist-windows11-ru.md`.
6. Требования к стенду (из чек-листа): чистый профиль, разрешения, RU/EN,
   отсутствие Python/старых данных SonoForge.

Не передавайте реальные ПДн/PHI. Для приёмки используется только тестовый
пациент и обезличенные файлы.

---

## 5. Ограничения текущего состояния

- macOS-артефакт **не подписан и не нотаризован** (G5b, #189): Gatekeeper
  будет блокировать скачанный DMG до ручного подтверждения.
- Windows-артефакт **не подписан Authenticode** (G5b, #189): SmartScreen
  покажет «Unknown publisher».
- CI не собирает macOS Intel; локальная Intel-сборка не воспроизводит
  arm64-артефакт и наоборот.
- Intel-сборка macOS требует Python 3.10 из-за `onnxruntime`; не меняйте
  версию Python «на глаз».
- Presenter для macOS не поддерживается.
- Модели не входят в артефакт и скачиваются при первом запуске.
