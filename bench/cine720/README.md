# `bench/cine720` — измерительный комплект для 720p cine-playback

Комплект построен для аудита
[`docs/bench/2026-09-06-cine-720p-playback-audit.md`](../../docs/bench/2026-09-06-cine-720p-playback-audit.md)
и воспроизводит все числа из него. В отличие от `tests/bench/` (микросекундные замеры
операций кеша на синтетических кадрах 16×16…512×512), эти скрипты гоняют **настоящий
`AppController` + настоящий `ViewerWidget` в живом event-loop Qt** на кадрах 1280×720 и
считают то, что видит пользователь: FPS, интервалы между кадрами, задержку скролла,
стоимость кадра на главном потоке, RSS.

Продуктивный код (`src/`) комплект **не меняет**: прототипы фиксов применяются
monkey-patch'ем до создания контроллера.

## Требования

* Debian/Linux или Windows, Python 3.10–3.11
* зависимости приложения (`PySide6`, `pyqtgraph`, `opencv-python-headless`, `pydicom`,
  `pylibjpeg*`, `numpy`, `psutil`, `scipy`)
* headless-запуск: `QT_QPA_PLATFORM=offscreen`
* фикстуры генерируются локально (сотни МБ) и **не коммитятся**

```bash
python3 -m venv .venv-bench
.venv-bench/bin/pip install "numpy>=1.26,<2.0" "opencv-python-headless>=4.8" "pydicom>=2.4" \
    "pylibjpeg>=2.0" "pylibjpeg-openjpeg>=2.0" "pylibjpeg-libjpeg>=2.0" "psutil>=5.9" \
    "pyside6>=6.6" "pyqtgraph>=0.13" "scipy>=1.11" onnxruntime reportlab pymupdf pynetdicom \
    jsonschema openpyxl keyring
```

## Генерация фикстур

```bash
# каталог по умолчанию: $CINE720_DIR или <tmp>/sonoforge-cine720
.venv-bench/bin/python bench/cine720/gen_cine720.py "" 60  rgb_raw,mono_raw,jpeg
.venv-bench/bin/python bench/cine720/gen_cine720.py "" 120 rgb_raw,jpeg
```

| Вариант | Transfer Syntax / кодек | Размер (60 / 120 кадров) | Кадр в ОЗУ |
|---|---|---|---|
| `rgb_raw` | Explicit VR LE, RGB 8-bit | 165.9 / 331.8 МБ | 2.76 МБ |
| `mono_raw` | Explicit VR LE, MONOCHROME2 16-bit | 110.6 МБ | 1.84 МБ |
| `jpeg` | JPEG Baseline `1.2.840.10008.1.2.4.50` | 6.29 / 12.58 МБ | 2.76 МБ |

Контент похож на УЗИ-cine: секторный градиент, коррелированный спекл, движущаяся полость,
высоконасыщенный цветной допплеровский клин. `FrameTime = 33 мс` (30 FPS).
Для MP4-пути подойдёт любой 720p-ролик 30 fps (`--format mp4`).

## Скрипты

| Скрипт | Что измеряет |
|---|---|
| `bench_decode.py <file>` | `open()`, первый кадр, `decode_single_frame` (последовательно и параллельно), `decode_all_frames` (zero-copy), стоимость полного cine в ОЗУ |
| `bench_prefetch.py <file>` | стоимость одного вызова воркера (`_run_batch` как в `FrameLoaderWorker`) при разных размерах батча; сравнение «как в релизе» vs «тёплая сессия» |
| `bench_playback_e2e.py <file>` | сквозное проигрывание в штатной конфигурации: FPS, p95/max интервал, фазы тиков (`cache_hit`/`cache_miss`), число и латентность батчей, round-trip prefetch, глубина буфера на тик, render/paint, RSS, первый кадр, Play → первый сдвиг; флаги `--ram-cap-mb` и `--decode-slow-ms` имитируют слабую машину |
| `bench_playback_fixes.py <file>` | та же прогонка с прототипами фиксов: `--fix-session`, `--fix-levels`, `--fix-timing`, `--fix-roi`, `--hot`, `--cache-mb` |
| `bench_scroll.py <file>` | задержка одного шага скролла (12 случайных переходов) и клик → первый кадр |
| `bench_render.py` | изолированные стоимости операций рендера: `show_frame_fast`, paint viewport, W/L-пути, LUT |
| `bench_cpu.py <script> [args…]` | обёртка: сколько ядер CPU сжигает прогон (user+sys / wall); прогоните дважды с разным `--seconds` и вычтите старт |
| `bench_micro.py` | микро-стоимости вокруг playback: `_detect_leading_static_from_cache`, `FrameCache.frames` (`np.stack`), `compute_display_levels`, `resolve_cine_segment_roi_xyxy` |
| `probe_render_breakdown.py <file>` | пооперационный разбор кадра на главном потоке в реальном прогоне (таймеры на `show_frame_fast` → `_update_levels` → `compute_display_levels` → `setImage`, плюс ROI контроллера и paint) |
| `probe_threadlocal.py` | доказательство: `threading.local` не выживает между `QRunnable` в `QThreadPool` даже на одном ОС-потоке |
| `probe_session_trace.py <file> <frames>` | трассировка: какой `id(DicomSession)` получает каждый job воркера и сколько раз файл перечитывается полностью |

Прототипы фиксов (не для продакшена, только для измерения эффекта):

| Модуль | Что делает |
|---|---|
| `sessioncache_patch.py` | общая `DicomSession` на процесс с ключом по resolved path под `RLock` (+ прокси `LockedReader` для общего `VideoReader`), `release_heavy()` отключён |
| `levelsfix_patch.py` | чинит кеш уровней W/L: порядок ключа `_cached_levels_key` (permutation-сравнение) + dtype-aware пороги `_is_levels_outlier` |

Флаги `--fix-timing` и `--fix-roi` живут внутри `bench_playback_fixes.py`: первый снимает
метку времени в начале тика и не перепланирует таймер по устаревшей метке, второй убирает
покадровый вызов `resolve_cine_segment_roi_xyxy`.

## Быстрый прогон (команды из аудита)

```bash
D=/tmp/sonoforge-cine720
export QT_QPA_PLATFORM=offscreen

# базовая линия
.venv-bench/bin/python bench/cine720/bench_playback_e2e.py $D/cine720_rgb_raw_60.dcm --frames 60 --seconds 8

# матрица фиксов
.venv-bench/bin/python bench/cine720/bench_playback_fixes.py $D/cine720_mono_raw_60.dcm \
    --frames 60 --cache-mb 64 --fix-session --fix-levels --fix-timing --fix-roi

# разбор кадра на главном потоке
.venv-bench/bin/python bench/cine720/probe_render_breakdown.py $D/cine720_mono_raw_60.dcm \
    --frames 5 --seconds 5 --fix-session --fix-levels

# скролл
.venv-bench/bin/python bench/cine720/bench_scroll.py $D/cine720_rgb_raw_120.dcm --frames 120 --fix-session

# расход CPU (два прогона, разница = фаза проигрывания)
.venv-bench/bin/python bench/cine720/bench_cpu.py bench/cine720/bench_playback_fixes.py \
    $D/cine720_rgb_raw_60.dcm --frames 60 --seconds 8
.venv-bench/bin/python bench/cine720/bench_cpu.py bench/cine720/bench_playback_fixes.py \
    $D/cine720_rgb_raw_60.dcm --frames 60 --seconds 1

# доказательства корневой причины
.venv-bench/bin/python bench/cine720/probe_threadlocal.py
.venv-bench/bin/python bench/cine720/probe_session_trace.py $D/cine720_rgb_raw_60.dcm 60
```

Общие аргументы: `--frames` (число кадров в инстансе), `--seconds` (длительность прогона),
`--cache-mb` (нижняя граница бюджета `FrameCache` — тюнинг кеша растит её под загруженный
cine), `--format dicom|mp4`, `--label` (подпись в отчёте).

Только у `bench_playback_e2e.py`:

| Флаг | Зачем |
|---|---|
| `--ram-cap-mb N` | ограничить долю ОЗУ, которую тюнинг кеша может занять (имитация машины с малым объёмом свободной памяти) |
| `--decode-slow-ms X` | добавить X мс wall-времени к декодированию каждого кадра (имитация медленного CPU; заодно гарантирует настоящие промахи кеша) |
| `--profile auto\|low\|high` | принудительно выбрать профиль `detect_playback_config` |
| `--warm-session` | отключить `release_heavy()` после батча (исторический флаг: в продуктовом коде сессия и так одна на файл) |
| `--no-render` | пропускать рендер во вьюере (только декод/кеш) |

`--frames` должен совпадать с реальным числом кадров фикстуры: большее значение даёт
недействительный прогон (инстанс короче запрошенного, часть тиков приходится на несуществующие
кадры).

## После серии фиксов (2026-09-07)

Фиксы из аудита вошли в продуктовый код (серия коммитов ветки, итоги — §6.1 аудита), поэтому:

* **Прототипы `sessioncache_patch.py` / `levelsfix_patch.py` и флаги `--fix-*` рассчитаны на
  код `cf82a7b`.** Они monkey-patch'ат старое поведение и на текущем дереве либо не
  применяются, либо не дают эффекта (чинить уже нечего). Для сравнения «до/после» делайте
  `git checkout cf82a7b` (или `git worktree add ../base cf82a7b`) и гоняйте матрицу там;
  `bench_playback_e2e.py` без флагов — это прогон текущего продуктивного пути.
* **Сквозной 720p-тест живёт в `tests/bench/test_cine_playback_e2e_ci.py`** и выполняется в
  CI на Linux под `xvfb-run`: настоящие `AppController` + `ViewerWidget`, две синтетические
  фикстуры 720p (MONO8 × 60 и RGB24 × 30), 4 с проигрывания и ассерты по SLO (§4.3 аудита).
  Фикстуры он генерирует сам, внешние файлы не нужны:

  ```bash
  QT_QPA_PLATFORM=offscreen .venv-bench/bin/python -m pytest tests/bench/test_cine_playback_e2e_ci.py -v
  ```

* **Имитация слабой машины** — флаги `--ram-cap-mb` / `--decode-slow-ms` (таблица выше);
  измеренные профили и их чтение — §4.4 аудита.
* **Каталог фикстур:** первый аргумент `gen_cine720.py` — это каталог, а не метка. Пустая
  строка (`""`) означает текущий каталог, то есть сотни МБ фикстур лягут в корень репозитория;
  оставляйте аргумент пустым только осознанно, иначе передайте `$CINE720_DIR` / `/tmp/...`.

## Как читать результат

```text
=== mono16 ===
  fixes: timing=True roi=True warm=False session=True hot=False cache=64MB
  FPS  30.86 (target 30)   frames=278 in 9.0s   non-adjacent jumps=0
  gap ms: avg  32.44 p95  35.12 max   62.15
  render avg  2.14 ms | paint avg  8.19 ms | main-thread 10.33 ms
  cache 19/60 frames (35 MB) | RSS 504->580 MB peak 580 MB
```

* `FPS` — число показанных кадров / время прогона; `target` = `1000 / frame_time`.
* `gap ms` — интервалы между показами кадров; цель p95 ≤ 1.25 × `frame_time`.
* `render` — `ViewerWidget.show_frame_fast`; `paint` — принудительный `viewport().repaint()`;
  `main-thread` = render + paint (без стоимости ROI в контроллере — её показывает
  `probe_render_breakdown.py`).
* `cache N/M frames (X MB)` — заполнение `FrameCache` в конце прогона.
* `RSS` — память процесса (старт → конец, пик).

Полезная модель, подтверждённая измерениями:

```
без фикса таймера:  FPS ≈ 1000 / (frame_time + W)      # W = работа главного потока на кадр
с фиксом таймера:   FPS ≈ 1000 / max(frame_time, W)
```

## Ограничения стенда

* `QT_QPA_PLATFORM=offscreen` → **raster-рендер**: цифры `paint` — худший случай.
  На машине с рабочим OpenGL перерисовка дешевле; остальные метрики от бэкенда не зависят.
* `probe_threadlocal.py` печатает `threading.get_native_id()` — на Windows это другой
  идентификатор, но вывод (потеря thread-local между `QRunnable`) тот же: это поведение
  PySide6, а не ядра ОС.
* Прототип общей сессии держал пиксельный блок активного файла в ОЗУ, поэтому пик RSS не
  падал (см. §2.7 аудита). В продуктовом коде пиксельный блок несжатого cine отображается
  через `mmap`, так что пик RSS включает файловые страницы: они попадают в рабочий набор, но
  сбрасываются ОС без записи, и сравнивать «до/после» только по RSS некорректно (§4.2 аудита).
* Все числа серии — Linux/offscreen на стенде 2 vCPU / 4 ГБ. Windows-стенда не было:
  платформенные риски разобраны в §4.2 аудита, но не замерены.
