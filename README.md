# ECHO Personal Tool

Персональный десктопный инструмент для просмотра и количественного анализа эхокардиографических исследований: **DICOM**, **MP4**, **JPEG/PNG**. Интерфейс и workflow ориентированы на ASE — без облака, локально на вашей машине.

**Стек:** PySide6, PyQtGraph, pydicom, OpenCV, NumPy, SciPy, httpx, ONNX Runtime, reportlab, openpyxl — **Clean Architecture** (`domain` / `infrastructure` / `application` / `presentation`).

---

## Возможности (обзор)

| Область | Что реализовано |
|---------|-----------------|
| **Источники данных** | Локальная папка; **Orthanc DICOMweb** (QIDO-RS / WADO-RS / STOW-RS); **DIMSE** (C-ECHO, C-FIND, C-STORE, **C-GET**, **C-MOVE**); **TLS**; mock offline |
| **Просмотр** | Gallery, 2D viewer, таймлайн, cine play/pause, W/L + DR |
| **Производительность** | Lazy decode DICOM/MP4 (первый кадр мгновенно); prefetch при playback; LRU frame cache |
| **Калибровка** | DICOM tags; ручная B-mode (см); **авто** по шкале глубины (MP4/JPEG); snap к тикам |
| **Линейные измерения** | Калиперы ASE (LVEDD, IVSd, TAPSE…); подписи **вдоль линейки** в реальном времени |
| **Объёмы / площади** | LV/LA/RA Simpson (open-arc), planimeter, generic area/volume |
| **Doppler** | Пики, интервалы, VTI, mitral inflow; калибровка ROI/baseline/шкалы |
| **M-Mode** | Калибровка, scan line, измерения, сглаживание |
| **Контуры** | Ручной / MBS-lite / ONNX LV Auto; R-refine, magnetic snap, Bézier spline |
| **Speckle tracking (STE)** | NCC block-matching, GLS, AHA 17 segments, strain curves, QC |
| **ONNX** | LV Auto A4C (hotkey `I`), LA Auto, temporal fusion, review + gradient refine (`R`) |
| **Отчёты** | Study overlay, индексы BSA, нормативы ASE, PDF export |
| **Справочник ASE** | Интерактивный браузер с темами, патологиями, градациями, изображениями |
| **Конструктор справочника** | Редактор параметров, импорт Excel, экспорт PDF/HTML, валидация YAML-схемы |
| **UX** | Clinical theme (dark/light), hover lerp, dialog fade+scale, анимации, reduced-motion |

---

## Фишки и отличия

### Быстрый просмотр cine (lazy loading)

- При открытии DICOM/MP4 декодируется **только первый кадр** — UI отзывается сразу.
- Скролл и playback подгружают кадры **по запросу** через фоновые workers.
- **Prefetch-буфер** при воспроизведении: адаптивный размер под CPU/RAM.
- **Leading static skip** — автоматический пропуск статичного lead-in.

### Калибровка без лишних кликов

- **Автокалибровка B-mode** для MP4/JPEG/PNG: детекция сантиметровых меток → mm/px.
- При ручной калибровке — **magnetic snap** к тикам шкалы глубины.
- DICOM: spacing из тегов (`PixelSpacing`, ultrasound regions, functional groups).

### Линейные калиперы Clinical-style

- Формат подписи: `LVEDD 52.3 mm` — обновление **в реальном времени**.
- Текст **вдоль линейки**, без переворота.
- Цепочки измерений (МЖП → КДР → ЗСЛЖ) с **blink** следующей кнопки.

### M-Mode

- Калибровка времени/глубины из DICOM tags или вручную.
- Scan line overlay, измерения расстояний и интервалов.
- Сглаживание сигналов (Savitzky-Golay).

### Speckle Tracking (STE)

- Двухконтурная зона миокарда, NCC block-matching, **bidirectional ED-anchored** трекинг.
- **GLS**, segment strain по AHA, strain curves, QC.
- Пресеты: `standard`, `research` (настраиваемые параметры).

### Контуры и AI

- **Open-arc Simpson** — mitral annulus + apex.
- **ONNX LV Auto**: `I` → маска → open-arc → review (`Enter`/`Esc`).
- **LA Auto**: автоматическая сегментация левого предсердия.
- **Temporal Fusion**: neighbor-aware контур (N±2), mask vote, node clamp.
- **R** — stepped border refine (±N px вдоль нормали) + edge snap.
- **Magnetic snap** контуров к границам миокарда.
- Bézier cubic spline для LV.

### Справочник ASE

- Интерактивный браузер с темами, патологиями, градациями.
- Нормативы по полу/возрасту, изображения.
- Конструктор справочника: редактирование, импорт Excel, экспорт PDF/HTML.

### DICOMweb / DIMSE

- Поиск (QIDO / C-FIND), скачивание: **WADO-RS**, **C-GET**, **C-MOVE**.
- **STOW-RS** и **C-STORE** upload.
- **TLS** для защищённых DIMSE-ассоциаций.
- **DIMSE-only** режим (без DICOMweb URL).

### Отчёты и нормативы

- **Результаты** — сводка по study (LVEF, объёмы, Doppler, linear, RWT…).
- Индексы **LVMI, LAVi, RAVi, EDVi/ESVi**.
- Экспорт **PDF** (reportlab).

---

## Горячие клавиши

| Клавиша | Действие |
|---------|----------|
| `Space` | Play / Pause cine |
| `L` | Линейный калипер |
| `Tab` | Сменить метку калипера (LVEDD → IVSd → …) |
| `K` | Ручная калибровка B-mode |
| `Shift+K` | Сброс ручной калибровки |
| `C` | Ручной контур (open-arc) |
| `M` | MBS-lite контур / Doppler peak |
| `I` | LV Auto Segment (ONNX) |
| `R` | Refine активного контура |
| `T` | Doppler interval |
| `V` | Doppler VTI trace |
| `Enter` | Завершить контур / trace |
| `Esc` | Отмена активного инструмента |
| `Del` / `Backspace` | Удалить контур текущей фазы |

---

## Требования

- **Python 3.10–3.11**
- [uv](https://docs.astral.sh/uv/) (рекомендуется) или `pip` + virtualenv
- Linux / Windows (протестировано на Debian 12, Win 10)
- ~500 MB RAM (ONNX модели загружаются по требованию)

### Зависимости

| Категория | Пакеты |
|-----------|--------|
| **GUI** | PySide6, PyQtGraph |
| **DICOM** | pydicom, pylibjpeg (+openjpeg, libjpeg), pynetdicom |
| **ML** | ONNX Runtime |
| **Math** | NumPy, SciPy |
| **Image** | OpenCV (headless) |
| **HTTP** | httpx (DICOMweb) |
| **PDF** | reportlab, PyMuPDF |
| **Excel** | openpyxl |
| **Data** | PyYAML, jsonschema |
| **System** | psutil |

---

## Установка

```bash
# С uv (рекомендуется)
git clone https://github.com/areatu/ECHO2026.git
cd ECHO2026
uv sync --extra dev
uv run echo-personal-tool

# Или pip
pip install -e ".[dev]"
python -m echo_personal_tool
```

**Примечание:** все зависимости (включая ONNX Runtime, reportlab, openpyxl) устанавливаются автоматически.

---

## Быстрый старт

1. **Open folder…** — папка с DICOM/MP4/JPEG, или **Загрузить с сервера…** — Orthanc.
2. Выбрать серию в **Gallery** → кадр откроется в viewer.
3. Для MP4/JPEG без DICOM-тегов: автокалибровка по шкале (или `K` вручную).
4. **Measures** (справа) — линейные, Simpson, Doppler, M-Mode, STE, RV FAC…
5. **Результаты** — сводка и PDF.

### Orthanc DICOMweb / DIMSE

Orthanc по умолчанию слушает **два порта**:

| Порт | Протокол | Назначение |
|------|----------|------------|
| **8042** | HTTP | DICOMweb: QIDO-RS, WADO-RS, STOW-RS |
| **4242** | TCP DIMSE | C-ECHO, C-FIND, C-STORE, C-GET, C-MOVE |

Типичный URL DICOMweb: `http://127.0.0.1:8042/dicom-web`
DIMSE: host `127.0.0.1`, port `4242`, Called AE `ORTHANC`, Calling AE `ECHO2026`.

**Публичный demo (read-only):**
[https://orthanc.uclouvain.be/demo/dicom-web](https://orthanc.uclouvain.be/demo/dicom-web)

1. **Настройки → Сервер…** — DICOMweb URL, DIMSE, STOW override, Mock offline.
2. **Загрузить с сервера…** — QIDO / C-FIND; WADO-RS, C-GET или C-MOVE.
3. **Отправить на сервер…** — STOW-RS или C-STORE.

#### Режимы скачивания

| Режим | Описание |
|-------|----------|
| **WADO-RS** | HTTP; по умолчанию |
| **C-GET** | DIMSE (та же ассоциация); проще C-MOVE |
| **C-MOVE** | Embedded Storage SCP (порт 11112); требует настройку modality |

#### C-MOVE в Orthanc

```json
{
  "DicomModalities": {
    "ECHO2026": ["ECHO2026", "127.0.0.1", 11112]
  }
}
```

#### TLS

В настройках сервера: CA certificate, Client certificate + key, Verify server certificate.

#### Integration-тесты

```bash
# DICOMweb smoke
ECHO_ORTHANC=1 pytest tests/integration/test_orthanc_live.py -v

# DIMSE
ECHO_ORTHANC=1 ECHO_ORTHANC_DIMSE=1 pytest tests/integration/test_orthanc_live.py -v -k dimse

# C-GET / C-MOVE
ECHO_ORTHANC=1 ECHO_ORTHANC_RETRIEVAL=dimse pytest tests/integration/test_orthanc_live.py -k c_get
ECHO_ORTHANC=1 ECHO_ORTHANC_RETRIEVAL=cmove pytest tests/integration/test_orthanc_live.py -k c_move
```

### ONNX (LV Auto)

ONNX модели загружаются из `models/` автоматически. LV Auto (A4C) доступен по `I`.

### Speckle Tracking

1. Нарисовать контур LV (ED) на cine B-mode.
2. Measures → **Speckle Tracking**.
3. Диалог ED/ES → расчёт GLS, overlay, strain curves, QC.

---

## Настройки (Preferences)

- **Интерфейс:** шрифт UI, theme dark/light, скорость playback.
- **Просмотр:** W/L presets, crosshair, подписи калиперов, DR sliders.
- **Измерения:** единицы (mm/cm), magnetic snap, автокалибровка.
- **Doppler:** auto-calibration из DICOM tags.
- **Отчёты:** шрифт PDF, overlay результатов.
- **STE:** пресеты (standard, research), drift compensation, wall thickness.

---

## Разработка

```bash
# Запуск тестов
uv run pytest

# Линтер
uv run ruff check src tests

# Форматтер
uv run ruff format src tests
```

Отладка: `.vscode/launch.json` → `echo_personal_tool`.

Изолированные ветки: `git worktree add .worktrees/<name> -b feat/<name>`.

---

## Структура проекта

```text
src/echo_personal_tool/
├── domain/              # Модели, расчёты (Simpson, Doppler, STE, M-Mode) — без Qt
│   ├── models/          # Contour, Doppler, Speckle, MMode, TemporalFusion
│   ├── calculations/    # Simpson, Bernoulli, Teichholz, BSA, RWT, FAC
│   └── services/        # Segmentation, tracking, gold store, reference data
├── infrastructure/      # DICOM, Orthanc, ONNX, DIMSE, video, i18n
├── application/         # AppController, workers (11 шт.), services
├── presentation/        # MainWindow, Viewer, M-Mode, Doppler, STE, меню
├── constructor/         # Редактор справочника (editors, exporters, importers)
├── ui/                  # Strain window, strain curves
└── resources/           # Шрифты, SVG-иконки, ASE справочник, изображения
```

---

## Документация

| Документ | Назначение |
|----------|------------|
| [ROADMAP.md](ROADMAP.md) | Статус фич по коду |
| [docs/superpowers/specs/](docs/superpowers/specs/) | Спеки (STE, DICOMweb, lazy loading, M-Mode…) |
| [docs/superpowers/plans/](docs/superpowers/plans/) | Планы реализации |
| [docs/bench/](docs/bench/) | Бенчмарки производительности |

---

## Лицензия

См. репозиторий / автор.
