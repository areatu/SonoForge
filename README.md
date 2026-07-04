# ECHO Personal Tool

Персональный десктопный инструмент для просмотра и количественного анализа эхокардиографических исследований: **DICOM**, **MP4**, **JPEG/PNG**. Интерфейс и workflow ориентированы на EchoPAC / ASE — без облака, локально на вашей машине.

**Стек:** PySide6, PyQtGraph, pydicom, OpenCV, NumPy, SciPy, httpx, ONNX Runtime (optional) — **Clean Architecture** (`domain` / `infrastructure` / `application` / `presentation`).

**Статус разработки:** активная ветка `fix/orthanc-wado-rs-series-level` (lazy loading, STE, playback, калибровка). Дорожная карта: **[ROADMAP.md](ROADMAP.md)**.

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
| **Doppler / M-mode** | Пики, интервалы, VTI, mitral inflow; калибровка ROI/baseline/шкалы |
| **Контуры** | Ручной / MBS-lite / ONNX LV Auto; R-refine, magnetic snap, Bézier spline |
| **Speckle tracking (STE)** | NCC block-matching, GLS, AHA 17 segments, strain curves, QC |
| **ONNX** | EchoNet LV A4C (hotkey `I`), review + gradient refine (`R`) |
| **Отчёты** | Study overlay, индексы BSA, нормативы ASE, PDF export |
| **UX** | EchoPAC theme (dark/light), blink «следующей кнопки», настраиваемые preferences |

---

## Фишки и отличия

### Быстрый просмотр cine (lazy loading)

- При открытии DICOM/MP4 декодируется **только первый кадр** — UI отзывается сразу, без ожидания полной cine.
- Скролл и playback подгружают кадры **по запросу** через фоновые workers.
- **Prefetch-буфер** при воспроизведении: адаптивный размер под CPU/RAM (`PlaybackConfig`).
- **Leading static skip** — автоматический пропуск статичного lead-in в начале клипа.
- Полная cine загружается только для speckle tracking (`require_full_cine`).

### Калибровка без лишних кликов

- **Автокалибровка B-mode** для MP4/JPEG/PNG: детекция сантиметровых меток справа → mm/px без QInputDialog (вкл. по умолчанию, настройки).
- При ручной калибровке — **magnetic snap** к тикам шкалы глубины.
- DICOM: spacing из тегов (`PixelSpacing`, ultrasound regions, functional groups).

### Линейные калиперы EchoPAC-style

- Формат подписи на линейке: `LVEDD 52.3 mm`, `Dist1 12.0 mm` — обновление **в реальном времени** при перетаскивании.
- Текст **вдоль линейки**, без переворота; для TAPSE — сбоку от вертикали.
- Цепочки измерений (МЖП → КДР → ЗСЛЖ) с **blink** следующей кнопки в меню Measures.
- После All Diastole → подсветка ES Diameter; после ED Simpson → ESV.

### Speckle Tracking (STE)

- Двухконтурная зона миокарда, NCC block-matching, **bidirectional ED-anchored** трекинг.
- **GLS**, segment strain по AHA, график strain ED…ES, таблица QC (NCC / quality).
- Преprocessing (CLAHE + log), drift compensation, пресеты (`echo_pac`, incremental).
- Диалог ED/ES (auto-detect + ручной ввод), overlay спеклов по кадрам в окне цикла.

### Контуры и AI

- **Open-arc Simpson** — mitral annulus + apex, без папиллярных впадин в дуге.
- **ONNX LV Auto** (EchoNet Segmentation Lite): `I` → маска → open-arc → review (`Enter`/`Esc`).
- **R** — stepped border refine (±N px вдоль нормали) + directed edge snap.
- **Magnetic snap** контуров к границам миокарда (настраиваемая сила).
- Bézier cubic spline для LV (ED S-shape / ES smooth).

### DICOMweb / Orthanc

- Поиск исследований (QIDO / C-FIND), скачивание серий: **WADO-RS**, **C-GET**, **C-MOVE** (parallel, progress bar).
- **STOW-RS** и **C-STORE** upload («Отправить на сервер…»).
- Источник поиска: DICOMweb / DIMSE / Auto; `query_source` сохраняется в настройках.
- Источник скачивания: WADO / DIMSE (C-GET) / C-MOVE / Auto; `retrieval_source` сохраняется в настройках.
- **TLS** для защищённых DIMSE-ассоциаций (CA + optional client cert).
- **DIMSE-only** режим: работа без DICOMweb URL (каталог + download + upload через DIMSE).
- Сессионный кэш, cancel загрузки, pre-scan метаданных.
- После загрузки — тот же pipeline, что для локальной папки.

### Отчёты и нормативы

- **Результаты** — сводка по study (LVEF, объёмы, Doppler, linear, RWT…).
- Индексы **LVMI, LAVi, RAVi, EDVi/ESVi** при росте/весе и отклонении от ASE.
- Встроенный справочник **ASE** (`References ASE+.md`).
- Экспорт **PDF** (optional `reportlab`).

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
| `M` | MBS-lite контур / Doppler peak (в контексте спектра) |
| `I` | LV Auto Segment (ONNX, в сессии LV Auto EDV/ESV) |
| `R` | Refine активного open-arc контура |
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

## Установка

```bash
# С uv (рекомендуется)
uv sync --extra dev --extra phase2
uv run echo-personal-tool

# Или pip
pip install -e ".[dev,phase2]"
python -m echo_personal_tool
```

| Extra | Содержимое |
|-------|------------|
| `phase2` | `onnxruntime` (LV Auto), `reportlab` (PDF) |
| `dev` | pytest, ruff, black |

Базовые зависимости включают `httpx` (DICOMweb), `opencv-python-headless`, `psutil` (adaptive playback).

---

## Быстрый старт

1. **Open folder…** — папка с DICOM/MP4/JPEG, или **Загрузить с сервера…** — Orthanc.
2. Выбрать серию в **Gallery** → кадр откроется в viewer.
3. Для MP4/JPEG без DICOM-тегов: автокалибровка по шкале (или `K` вручную).
4. **Measures** (справа) — линейные, Simpson, Doppler, STE, RV FAC…
5. **Результаты** — сводка и PDF.

### Orthanc DICOMweb / DIMSE

Orthanc по умолчанию слушает **два порта**:

| Порт | Протокол | Назначение в ECHO2026 |
|------|----------|------------------------|
| **8042** | HTTP | DICOMweb: QIDO-RS, WADO-RS, STOW-RS; REST `/system` (ping) |
| **4242** | TCP DIMSE | C-ECHO, C-FIND, C-STORE, C-GET, C-MOVE (native DICOM) |

Типичный URL DICOMweb: `http://127.0.0.1:8042/dicom-web`  
DIMSE: host `127.0.0.1`, port `4242`, Called AE `ORTHANC`, Calling AE `ECHO2026`.

**Публичный demo (read-only, для smoke-тестов):**  
[https://orthanc.uclouvain.be/demo/dicom-web](https://orthanc.uclouvain.be/demo/dicom-web)  
REST root: `https://orthanc.uclouvain.be/demo` — DIMSE на demo обычно **не** exposed.

1. **Настройки → Сервер…** — DICOMweb URL, DIMSE (опционально), STOW override, **Mock** offline.
2. **Загрузить с сервера…** — источник поиска: DICOMweb / DIMSE / Auto; QIDO или C-FIND; скачивание через WADO-RS, C-GET или C-MOVE.
3. **Отправить на сервер…** — STOW-RS или C-STORE (локальные DICOM из загруженных studies).
4. Прогресс по сериям; после загрузки — локальный pipeline.

#### DIMSE Phase 2: C-GET, C-MOVE, TLS

Расширенная поддержка DIMSE для скачивания инстансов:

| Режим | Описание | Когда использовать |
|-------|----------|-------------------|
| **WADO-RS** | Скачивание через HTTP | По умолчанию; требует настроенный DICOMweb URL |
| **C-GET** | Скачивание по DIMSE (на той же ассоциации) | Когда DICOMweb недоступен; проще чем C-MOVE |
| **C-MOVE** | Скачивание через embedded Storage SCP (порт 11112) | Когда PACS требует C-MOVE; нужна настройка modality в Orthanc |

**Настройка C-MOVE в Orthanc:**

Для работы C-MOVE необходимо добавить modality в `orthanc.json`:

```json
{
  "DicomModalities": {
    "ECHO2026": ["ECHO2026", "127.0.0.1", 11112]
  }
}
```

Где:
- `ECHO2026` — AE Title приложения (по умолчанию)
- `127.0.0.1` — IP адрес компьютера с ECHO2026
- `11112` — порт embedded Storage SCP (только на время скачивания)

**TLS (опционально):**

Для защищённых DIMSE-ассоциаций с hospital PACS:

1. В настройках сервера включите "Use TLS"
2. Укажите CA certificate (опционально)
3. Укажите Client certificate и Client key (опционально)
4. Отключите "Verify server certificate" если PACS использует самоподписанный сертификат

**Режим "только DIMSE" (без DICOMweb URL):**

При включённом DIMSE и отсутствующем DICOMweb URL:
- Поиск: C-FIND
- Скачивание: C-GET или C-MOVE
- Загрузка: C-STORE
- STOW-RS недоступен (кнопка "Отправить на сервер" отключена)

**Integration-тесты** (live Orthanc):

```bash
# DICOMweb smoke против UCLouvain demo
ECHO_ORTHANC=1 pytest tests/integration/test_orthanc_live.py -v

# Свой сервер
ECHO_ORTHANC=1 ECHO_ORTHANC_URL=http://127.0.0.1:8042/dicom-web pytest tests/integration/test_orthanc_live.py -v

# Локальный DIMSE (C-ECHO, C-FIND)
ECHO_ORTHANC=1 ECHO_ORTHANC_DIMSE=1 pytest tests/integration/test_orthanc_live.py -v -k dimse

# C-GET retrieval
ECHO_ORTHANC=1 ECHO_ORTHANC_DIMSE=1 ECHO_ORTHANC_RETRIEVAL=dimse pytest tests/integration/test_orthanc_live.py -k c_get

# C-MOVE retrieval (требует настройки modality в Orthanc)
ECHO_ORTHANC=1 ECHO_ORTHANC_DIMSE=1 ECHO_ORTHANC_RETRIEVAL=cmove pytest tests/integration/test_orthanc_live.py -k c_move
```

Спека: [`docs/superpowers/specs/2026-06-23-dicomweb-orthanc-design.md`](docs/superpowers/specs/2026-06-23-dicomweb-orthanc-design.md)  
План DIMSE/STOW: [`docs/superpowers/plans/2026-07-02-dimse-stow-rs-implementation.md`](docs/superpowers/plans/2026-07-02-dimse-stow-rs-implementation.md)  
DIMSE Phase 2: [`docs/superpowers/specs/2026-07-04-dimse-phase2-design.md`](docs/superpowers/specs/2026-07-04-dimse-phase2-design.md)

### ONNX (LV Auto)

```bash
python scripts/export_echonet_seg_to_onnx.py --verify
```

1. Measures → **LV Auto** → EDV / ESV (A4C).
2. Кадр → **`I`** — ONNX сегментация → open-arc контур.
3. **`R`** — refine; drag узлов; **`Enter`** — принять.

Спека: [`docs/superpowers/specs/2026-06-19-onnx-lv-auto-segment-design.md`](docs/superpowers/specs/2026-06-19-onnx-lv-auto-segment-design.md)

### Speckle Tracking

1. Нарисовать контур LV (ED) на cine B-mode.
2. Measures → **Speckle Tracking** (или соответствующий пункт меню).
3. Диалог ED/ES → расчёт GLS, overlay, strain curve, QC.

Спека: [`docs/superpowers/specs/2026-06-25-nelafo-speckle-tracking-design.md`](docs/superpowers/specs/2026-06-25-nelafo-speckle-tracking-design.md)

---

## Настройки (Настройки → Preferences)

- **Интерфейс:** шрифт UI, theme dark/light, скорость playback.
- **Просмотр:** W/L presets, crosshair, подписи калиперов, DR sliders.
- **Измерения:** единицы (mm/cm), magnetic snap, **автокалибровка**, snap к тикам шкалы.
- **Doppler:** auto-calibration из DICOM tags.
- **Отчёты:** шрифт PDF, overlay результатов (позиция, opacity).

---

## Разработка

```bash
uv run pytest
uv run ruff check src tests
```

Отладка: `.vscode/launch.json` → `echo_personal_tool`.

Изолированные ветки: `git worktree add .worktrees/<name> -b feat/<name>`.

---

## Структура проекта

```text
src/echo_personal_tool/
├── domain/           # Модели, расчёты (Simpson, Doppler, STE, spacing) — без Qt/pydicom UI
├── infrastructure/   # DICOM, Orthanc, ONNX, scanners, user preferences
├── application/      # AppController, workers (decode, speckle, thumbnails)
└── presentation/     # MainWindow, ViewerWidget, Measures, диалоги, overlay
```

---

## Документация

| Документ | Назначение |
|----------|------------|
| [ROADMAP.md](ROADMAP.md) | Статус фич по коду |
| [CHANGELOG_SESSION.md](CHANGELOG_SESSION.md) | Контекст для новых чатов Cursor |
| [docs/superpowers/specs/](docs/superpowers/specs/) | Утверждённые спеки (STE, DICOMweb, lazy loading…) |
| [docs/superpowers/plans/](docs/superpowers/plans/) | Планы реализации |
| [DICOM_parsing.md](DICOM_parsing.md) | DICOMweb / Orthanc замечания |
| [Measures-block.md](Measures-block.md) | Карта кнопок Measures |

---

## Лицензия

См. репозиторий / автор.
