# Сравнительный анализ: Weasis vs SonoForge

## Почему Weasis загружает за секунды

### Ключевые настройки Weasis (base.json)

| Параметр | Weasis | SonoForge |
|----------|--------|---------------------|
| `download.concurrent.series` | **3** (3 серии параллельно) | **1** (последовательно) |
| `download.concurrent.series.images` | **4** (4 инстанса параллельно) | **1** |
| Метод скачивания | **Per-instance WADO-RS** (отдельный HTTP-запрос на каждый файл) | **Series-level multipart** (один запрос на всю серию, multipart) |
| Декодирование | **OpenCV native** (JNI, C++) | **pydicom + numpy** (pure Python) |
| Первый кадр | Показывает **сразу** после декодирования первого | Ждёт **декодирования ВСЕХ кадров** |
| Кадры для cine | **Ленивая загрузка** (on-demand) | **Все кадры в RAM** сразу (FrameCache) |
| Миниатюры | Параллельно с загрузкой | `max_in_flight=2`, после загрузки |
| Авторизация | Basic, OAuth 2.0, OpenID Connect | Basic + HTTP Headers |
| Код | Java 99%, native OpenCV | Python 3.11, PySide6, pydicom |

### Архитектура Weasis

Weasis — Java OSGi-приложение на базе Felix. Модульная структура:
- `weasis-core` — ядро (OGC, сигналы, настройки)
- `weasis-dicom` — DICOM операции (C-FIND, C-GET, WADO-RS, QIDO-RS)
- `weasis-imageio` — ImageIO кодеки
- `weasis-opencv` — OpenCV native-библиотеки для декодирования пикселей
- `weasis-dicom-viewer2d` — 2D просмотрщик

Ключевой файл: `base.json` содержит:
```json
"download.concurrent.series": 3,
"download.concurrent.series.images": 4,
"weasis.download.immediately": true
```

### Модель скачивания Weasis

1. **QIDO-RS** — запрос списка серий/инстансов (`studies/{uid}/series`, `series/{uid}/instances`)
2. **Per-instance WADO-RS** — каждый инстанс скачивается отдельным HTTP-запросом
3. **4 параллельных потока** скачивают инстансы внутри серии
4. **3 серии** скачиваются параллельно
5. **Декодирование OpenCV** — native C++, JNI-мост
6. **Первый кадр показывается сразу**, остальные — в фоне
7. **Ленивая загрузка** кадров при прокрутке (prefetch ±N кадров)

---

## Корневые проблемы SonoForge

### Проблема 1: Series-level multipart скачивание

**Текущий пайплайн:**
```
OrthancDownloadWorker.run()
  → _client.query_instances(study, series)     # QIDO-RS: список инстансов
  → _client.download_series(study, series)      # WADO-RS: ВСЯ серия одним запросом
    → httpx.stream("GET", .../series/{uid})     # multipart/related ответ
    → iter_bytes(chunk_size=65536)              # накопление всех байтов
    → _parse_multipart(content, content_type)   # парсинг boundary-based MIME
    → pydicom.dcmread(BytesIO(part))            # извлечение SOPInstanceUID
  → cache.save_instance(...)                    # запись на диск
```

**Почему ломается:**
- Ответ 1.2+ ГБ (51 инстанс) целиком загружается в память
- `_parse_multipart` 使用 `content.split(delimiter)` — потенциальная потеря частей при boundary-коллизии с бинарными DICOM-данными
- Таймаут 300 сек может быть недостаточен при медленном соединении
- Обрыв соединения = потеря ВСЕХ данных (нет resume)

**Сравнение:**
| | Series-level multipart | Per-instance WADO-RS |
|---|---|---|
| Запросов на серию | 1 | N (число инстансов) |
| Параллелизация | Невозможна | 4-6 параллельных |
| Объём памяти | Весь ответ сразу | Один файл за раз |
| Обрыв соединения | Потеря всех данных | Потеря одного файла |
| Resume | Невозможен | Повторный запрос одного файла |

### Проблема 2: Лишнее сканирование после скачивания

**Текущий пайплайн:**
```
OrthancStudyDialog._on_done()
  → MainWindow._open_orthanc_dialog()
    → AppController.open_folder(session_path)
      → ScanWorker()                          # ОТДЕЛЬНЫЙ воркер!
        → LocalMediaDirectoryScanner.scan()    # Сканирование директории
        → Построение StudyMetadata
      → _on_studies_scanned()
        → ThumbnailGallery.populate()
```

**Проблема:** После скачивания 51 файла приложение создаёт `ScanWorker`, который заново сканирует директорию, ищет DICOM-файлы по расширению, парсит заголовки. Это **лишний проход по диску**.

**Weasis:** Список инстансов уже известен из QIDO-RS. Нет отдельного сканирования.

### Проблема 3: Миниатюры — последовательные, после загрузки

**Текущий пайплайн:**
```
ThumbnailScheduler
  → max_in_flight = 2                          # Макс 2 параллельных
  → P0: Visible Selected (видимые+выбранные)
  → P1: Near Visible (рядом с видимыми)
  → P2: Background (остальные)
  → ThumbnailLoaderWorker()
    → pydicom.dcmread() или VideoReader
    → numpy_pixels_to_qimage(pixels, 96px)
    → QImage → QPixmap → QIcon
```

**Проблемы:**
- `max_in_flight=2` — слишком мало для 51+ инстансов
- Генерация начинается **после** полного сканирования
- Каждая миниатюра — отдельный `dcmread` (медленно)

**Weasis:** Миниатюры генерируются из уже декодированных кадров, параллельно со скачиванием.

### Проблема 4: Просмотр — декодирование всех кадров перед показом

**Текущий пайплайн:**
```
AppController.load_instance()
  → DicomDecodeWorker()                        # QRunnable
    → session.decode_all_frames()              # ВСЕ кадры!
    → ndarray shape (N, H, W) или (N, H, W, C)
  → _on_dicom_decoded()
    → FrameCache.load(path, frames)            # Весь массив в RAM
    → _emit_cached_frame(current_index)
  → MainWindow._on_frame_loaded()
    → ViewerWidget.show_frame(image)
```

**Проблемы:**
- 170 кадров × ~3 МБ/кадр = ~510 МБ RAM только для одного cine
- Пользователь ждёт **7+ секунд** до первого кадра
- `_FRAME_CACHE_WARN_BYTES = 512 * 1024 * 1024` — предупреждение при превышении

**Weasis:** Показывает первый кадр сразу. Остальные декодируются в фоне.

### Проблема 5: Cine — все кадры в FrameCache

**Текущий FrameCache:**
```python
@dataclass
class FrameCache:
    source_path: Path
    frames: np.ndarray  # shape (N, H, W) или (N, H, W, C)

    def get(self, index: int) -> np.ndarray:
        return self.frames[index].copy()  # Копия! Дополнительный аллок
```

**Проблемы:**
- Весь numpy-массив в RAM
- `get()` возвращает **копию** фрейма (дополнительные аллокации)
- Нет prefetch следующих кадров
- Нет освобождения памяти при прокрутке远距离

---

## План оптимизации

### P0 — Замена multipart на per-instance скачивание

**Цель:** Надёжность + скорость ×4–6

**Изменения:**
1. Убрать `download_series()` из `OrthancDicomWebClient`
2. Добавить пул параллельных загрузок (concurrent.futures.ThreadPoolExecutor)
3. Скачивать каждый инстанс отдельным `download_instance()` запросом
4. Лимит concurrency: 4–6 параллельных потоков

**Файлы:**
- `orthanc_client.py` — убрать `download_series`, `_parse_multipart`
- `orthanc_download_worker.py` — ThreadPoolExecutor вместо последовательного цикла

**Ожидаемый эффект:**
- Скачивание 51 файла: ~15–30 сек вместо 60–120 сек
- Обрыв одного файла ≠ потеря всех
- Меньше потребление памяти (нет buffer всего multipart-ответа)

### P1 — Прогрессивный показ (первый кадр сразу)

**Цель:** Показать изображение за <1 сек после клика

**Изменения:**
1. `DicomDecodeWorker` — декодировать **только первый кадр** для показа
2. Остальные кадры декодировать в фоне (отдельный поток)
3. `FrameCache` — заполнять постепенно

**Файлы:**
- `dicom_decode_worker.py` — два режима: first_frame_only / decode_all
- `frame_cache.py` — поддержка инкрементального заполнения
- `app_controller.py` — показ первого кадра, затем обновление по мере готовности

**Ожидаемый эффект:**
- Первый кадр: <1 сек
- Cine доступен через 2–3 сек (вместо 7+)

### P2 — Ленивая загрузка кадров для cine

**Цель:** Снизить RAM и время первого показа

**Изменения:**
1. Не декодировать все кадры при открытии
2. Декодировать по мере прокрутки + prefetch ±5 кадров
3. Освобождать кадры,远离ие от текущего позиции >20

**Файлы:**
- `frame_cache.py` — LRU-кэш с limited size (например, 30 кадров)
- `app_controller.py` — prefetch логика при `_advance_playback`

**Ожидаемый эффект:**
- RAM: ~90 МБ вместо ~500 МБ для 170-кадрового cine
- Мгновенный отзыв при прокрутке

### P3 — Параллельные миниатюры

**Цель:** Миниатюры готовы к моменту показа

**Изменения:**
1. Увеличить `max_in_flight` с 2 до 4–6
2. Начинать генерацию миниатюр **во время** скачивания
3. Кэшировать decoded pixels из `DicomDecodeWorker`

**Файлы:**
- `thumbnail_scheduler.py` — `max_in_flight=4`
- `orthanc_download_worker.py` — signal для gallery о доступности инстансов
- `thumbnail_loader_worker.py` — кэш decoded pixels

### P4 — Убрать лишнее сканирование

**Цель:** Убрать ScanWorker после скачивания

**Изменения:**
1. После скачивания сразу строить `StudyMetadata` из ответов QIDO-RS
2. Пропускать `ScanWorker` для orthanc-сессий

**Файлы:**
- `orthanc_download_worker.py` — эмитить список инстансов с UID/мета
- `app_controller.py` — прямой путь к viewer без `ScanWorker`

---

## Приоритеты и трудозатраты

| Приоритет | Задача | Трудоёмкость | Эффект |
|-----------|--------|-------------|--------|
| P0 | Per-instance скачивание | ~3 ч | ×4-6 скорость, надёжность |
| P1 | Первый кадр сразу | ~2 ч | 1 сек вместо 7 |
| P2 | Ленивая загрузка кадров | ~3 ч | −80% RAM |
| P3 | Параллельные миниатюры | ~1 ч | Миниатюры до показа |
| P4 | Убрать ScanWorker | ~1 ч | −1 проход по диску |

**Итого:** ~10 часов разработки

**Рекомендуемый порядок:** P0 → P1 → P4 → P3 → P2

P0 критичен для надёжности (решает баг 8/51). P1 —最大的 UX-эффект. P4 — быстрый win. P3 — дополнительное ускорение. P2 — оптимизация памяти.
