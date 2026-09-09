# Расследование долгой загрузки папки DICOM

Дата: 2026-09-09. Исследован код `df7cd2d` (исходное состояние рабочей ветки).

> Разделы 1–9 фиксируют расследование **до исправлений**. Реализованные затем изменения и их проверка перечислены в разделе 10; старые тайминги и описания дефектов сохранены как baseline.

## Краткий вывод

**Стоимость декомпрессии действительно существенна, но «JPEG/J2K медленный» — недостаточное объяснение 30 секунд до начала работы.** В текущем GUI уже используется загрузка только первого кадра. Найдены механизмы, которые превращают фоновую подготовку миниатюр в конкурента интерактивной загрузке, повторно освобождают нужные буферы и иногда заставляют декодировать весь ролик ради одного кадра.

Приоритет исправлений:

1. **Перестать сбрасывать активную сессию при открытии файлов для миниатюр.** Ввести явное владение/закрепление активных сессий и ограничение памяти вместо `release_stale_sessions()` при каждом `open()`.
2. **Убрать полное `Dataset.pixel_array` из покадрового fallback.** В pydicom 3 использовать индексированное декодирование кадра; отдельно исправить восстановление буферов после освобождения.
3. **Убрать GIL-bound J2K из критического пути UI.** Проверить GIL-releasing backend на поддерживаемых форматах либо использовать ограниченный долгоживущий процессный пул.
4. **Реально приоритизировать выбранный ролик и видимые миниатюры.** Сейчас приоритет теряется в подключении callback; фон должен приостанавливаться при открытии/воспроизведении.
5. Затем оптимизировать чтение compressed PixelData, кэш миниатюр, повторные заголовки и дополнительные операции UI.

Это расследование, а не внедрение оптимизаций: production-файлы не изменены. Добавлены воспроизводимый диагностический скрипт и тесты его работы.

## 1. Что удалось и не удалось проверить

**Доступно:** исходный код, существующие тесты и предыдущий аудит playback; зависимости декодирования из `uv.lock`; собственные синтетические DICOM.

**Недоступно:** исходные 114 DICOM на 2.2 GB, профиль машины пользователя, исходный скрипт/сырые результаты указанного бенчмарка, trace конкретного запуска GUI. В этой копии `gold/` содержит только README и две JSON-аннотации. Поэтому ниже нет утверждения «мы воспроизвели ваши 30 секунд» и нет гарантированного ускорения на этих файлах.

Обозначения:

- **Код:** поведение однозначно следует из текущего call path.
- **Замер:** воспроизведено в sandbox на синтетических данных.
- **Гипотеза для gold:** требуется проверка на реальной папке.

Предыдущий [аудит playback 720p](2026-09-06-cine-720p-playback-audit.md) полезен как история. Его проблему `threading.local` нельзя выдавать за неисправленный дефект: текущий код уже использует process-wide registry и mmap для uncompressed. Здесь исследована оставшаяся проблема взаимодействия файлов, особенно compressed.

## 2. Что означает приведённый бенчмарк

Данные пользователя: 30 файлов, header read 466 ms, decode 141447 ms, среднее decode 4714.9 ms/файл, throughput 4.7 MB/s.

- Доля decode: `141447 / (141447 + 466) = 99.67%` **от двух измеренных фаз**, не обязательно от всего GUI pipeline.
- `stop_before_pixels=True` читает заголовок. Его 466 ms **не измеряют чтение всех compressed PixelData с диска**. Нельзя на основании этой цифры исключить I/O, особенно сетевой диск, холодный файловый кэш или повторные чтения.
- В зависимости от границ таймера «decode» может включать чтение payload, повторный pydicom parse, сборку фрагментов, аллокации и ожидание locks. Без исходного скрипта нельзя приписать все 99.7% непосредственно JPEG/J2K kernel.
- 4.7 MB/s — эффективная скорость обработки размера DICOM-файлов, не bandwidth диска и не скорость выдачи распакованных кадров. Для декодера нужны **ms/frame, frames/s, MPix/s**, отдельно по TransferSyntaxUID, размеру, цветности и битности.
- Сумма 141 s и пользовательские 30 s — разные метрики. Возможны разные пути, subset, конкуренция, кэши и границы наблюдения. **Нельзя заключать, что GUI просто распараллелил 141 s на пять потоков.** В проверенном J2K backend потоки почти не дают ускорения.
- Полное устранение только 466 ms header-read сократило бы эти две фазы всего на 0.33%. Это не главный приоритет.

Нужно различать:

| Метрика | Что пользователь получает |
|---|---|
| folder → studies/tree ready | Можно выбрать ролик |
| click → first pixels painted | Видно изображение |
| click → controls usable | Доступны измерения/навигация |
| Play → первый следующий кадр | Воспроизведение реально началось |
| sustained FPS / stalls | Можно комфортно смотреть |
| all thumbnails ready | Галерея полностью оформлена, не условие начала работы |
| full cine decode / full folder processing | Производительность пакетной обработки, не интерактивная готовность |

## 3. Фактический путь загрузки

### 3.1 Сканирование и галерея

```text
AppController.open_folder()
  → ScanWorker [QThreadPool]
    → LocalMediaDirectoryScanner.scan()
      → заголовки / metadata / построение studies
  → MainWindow._on_studies_loaded() [GUI]
    → ThumbnailGallery.populate()
    → request_visible_previews()
    → QTimer(0): _after_populate()
      → visible previews + background previews ДЛЯ ВСЕХ instances
```

Ссылки на код: `application/app_controller.py:388–427`, `infrastructure/local_scanner.py:73–96,160–212`, `presentation/main_window.py:1216–1237`, `presentation/thumbnail_gallery.py:245–316` (всё под `src/echo_personal_tool/`).

Scanner не декодирует каждый ролик целиком. Но перечитывает заголовок для StudyUID, иногда ещё раз для StudyDate. Если нет NumberOfFrames, выполняет полный read PixelData для определения числа кадров. Сканирование выдаёт готовый список в конце, не streaming-результаты.

### 3.2 Открытие выбранного ролика

```text
AppController.load_instance()
  → повторное чтение заголовка аннотаций [GUI]
  → decode_in_progress = True
  → DicomDecodeWorker(first_frame_only=True) [тот же QThreadPool]
    → get_dicom_session(path)
    → session.open()
    → session.decode_first_frame()
    → first_frame_ready
  → _on_first_frame_ready() [GUI]
    → frame cache.put(0)
    → decode_in_progress = False
    → frame_loaded / decode_finished
  → показ кадра; отложенное восстановление overlays/calibration
```

Код: `application/app_controller.py:439–548,2515–2538`; `application/workers/dicom_decode_worker.py:46–76`; `presentation/main_window.py:1428–1491`.

**В текущем основном GUI нет требования полностью декодировать выбранный cine или всю папку перед снятием `decode_in_progress`.** Предложение «внедрить lazy loading» без этой оговорки повторяет уже реализованное. Проблема — сделать существующую lazy-схему действительно покадровой и защищённой от фона.

При Play есть дополнительная подготовка: leading-static scan и prefetch; начальный min_buffer — 3 или 5 кадров в зависимости от профиля. `FrameLoaderWorker._run_batch()` читает DICOM последовательно и отдаёт список по завершении батча. Это может увеличивать задержку Play даже при уже показанном первом кадре (`app_controller.py:644–798`; `infrastructure/system_profiler.py:24–58`).

## 4. Основные узкие места

### P0-A. Открытие миниатюры освобождает активный cine

**Код + замер.** `DicomSession.open()` перед открытием «холодного» файла вызывает `release_stale_sessions(exclude=self)`. Та освобождает тяжёлые буферы **всех других** зарегистрированных сессий. Выбранный пользователем файл ничем не закреплён.

Код: [`dicom_session.py`](../../src/echo_personal_tool/infrastructure/dicom_session.py), строки 188–210, 495–562, 848–863; `ThumbnailLoaderWorker.run()` → `DicomReaderImpl.read_pixels()` → та же registry/session.

Последствия:

1. Миниатюры разных файлов взаимно охлаждают сессии; повторяются чтение compressed bytes, парсинг и сборка фрагментов.
2. `release_heavy()` берёт lock освобождаемой сессии. Открытие B может ждать декодирования A. Это скрытая межфайловая сериализация, которой не должно быть между независимыми файлами.
3. Между отдельными кадрами batch на A может вклиниться `open(B)`. Batch открывает A только один раз. После сброса у compressed A `_raw_bytes`, `_pixel_data_raw`, `_encapsulated_frames` пусты; `_ensure_pixel_data()` при отсутствии `_raw_bytes` просто возвращается. Следующий кадр проваливается в **полный pydicom fallback**.
4. Даже без batch между `session.open(A)` и `decode_first_frame/read_frame(A)` возможна такая же интерференция.

**Детерминированное воспроизведение без подмены кодека:**

```text
A = shared JPEG session; open(A); decode_first_frame(A)
A has pixels: True
B = shared J2K session; open(B)
A has pixels: False
decode_single_frame(A, 1), без повторного open как в обычном batch:
  fallback_calls = 1
  elapsed = 648.52 ms
Обычный прогретый кадр A: около 2.14 ms
```

Это приблизительно **300-кратная деградация одного запроса** на данном синтетическом файле, не обещание ускорения всей gold-папки на 300×. Probe воспроизводит допустимый порядок операций, но не измеряет частоту такого interleaving в реальном GUI.

**Исправление:** registry с `acquire/release` lease и in-use count; pin активного/второго viewport cine; ограниченный byte-budget + LRU только незанятых сессий. Временные thumbnail sessions не должны освобождать чужие buffers. Если бюджет занят — backpressure фоновой очереди, а не eviction активной сессии. Восстановление compressed payload должно работать и после `release_heavy()` без обязательного внешнего `open()`.

Не исправлять простым удалением всей очистки: это вернёт multi-GB расход RAM. Не держать общий registry lock во время I/O/декодирования и ожидания session lock.

### P0-B. Fallback «один кадр» = декодирование всего ролика

**Код + замер.** `DicomSession._decode_pydicom_fallback(index)` создаёт новый `Dataset`, вызывает `full_ds.pixel_array`, затем выбирает `frames[index]` (`dicom_session.py:766–807`). Результат полного декодирования не кэшируется между fallback-вызовами.

Если быстрый путь не поддерживает syntax/данные или буферы были сброшены, стоимость одного кадра становится `O(N)` вместо `O(1)` относительно числа кадров. Для `decode_all_frames()` с N fallback-вызовами — потенциально **O(N²)** декодированных кадров. Внутренние futures удерживают полученные результаты до конца bulk-вызова, добавляя transient memory к заранее выделенному `_frames`.

RLE использован как штатный поддерживаемый pydicom формат без быстрого пути в SonoForge: на cine из 24 кадров bulk дал **24 fallback-вызова**, т.е. 24 полных декодирования по 24 кадра. Это проверка механизма, **не утверждение о наличии RLE в gold**. JPEG/J2K тоже попадают туда при сбросе сессии/ошибках fast path.

**Дополнительное усиление по RAM, также проверено:** `np.ascontiguousarray(frames[index])` не делает копию уже contiguous кадра. Возвращённый frame может удерживать через `.base` весь распакованный cine. На RLE из 24 кадров кадр имел `nbytes=16384`, `OWNDATA=False`, а корневой ndarray — `393216` bytes. FrameCache, учитывающий только `frame.nbytes`, такой backing buffer недооценивает. При серии fallback-запросов можно удерживать несколько полных копий cine; при bulk futures — потенциально квадратичную по N память. Поэтому нужны проверки ownership/backing size, не только суммы `nbytes` кадров. В harness добавлено поле `first_frame_ndarray_backing_mb`; оно измеряет ndarray base chain, не физическую резидентность mmap.

**Исправление:** pydicom 3 `pydicom.pixels.pixel_array(path, index=i)` или индексированный decoder API с переиспользуемым источником. Для bulk fallback — один полный decode/`iter_pixels`, но не N полных decode. Индексированный API не обязан быть лучшим fast path: на healthy JPEG у нас 11.57 ms против 2.14 ms у cv2; он нужен прежде всего вместо аварийного full-array path.

В `pyproject.toml` ещё разрешён pydicom >=2.4, хотя production импортирует API encaps из pydicom 3 и lock закрепляет 3.0.2. При внедрении явно согласовать minimum version либо поддержать ограниченный compatibility fallback с однократным full decode под lock и учётом памяти.

### P0-C. J2K backend удерживает GIL: потоки не масштабируются

**Замер + проверка исходника зависимости.** Для J2K `_decode_compressed_frame()` сначала вызывает `openjpeg.decode()`; только при неудаче — cv2 (`dicom_session.py:357–418`). В lock используется `pylibjpeg-openjpeg 2.3.0`.

В исходном дистрибутиве [pylibjpeg-openjpeg 2.3.0](https://files.pythonhosted.org/packages/94/6a/69c6e6d51540755807c7c90f0758c1f16ecf9edc3d6a9f5d51feeea43854/pylibjpeg_openjpeg-2.3.0.tar.gz), `openjpeg/_openjpeg.pyx:24,72–123`, Cython вызывает `Decode(p_in, p_out, codec)` без `with nogil`. Вход — Python file-like object. Просто добавить `nogil` к вызову без переработки callbacks небезопасно.

| 12 прогретых кадров 512×512 | 1 поток | 2 потока | 4 потока |
|---|---:|---:|---:|
| JPEG, текущий cv2 path | 25.13 ms | 13.65 ms | 14.81 ms |
| J2K, текущий openjpeg path | 513.21 ms | 519.21 ms | 520.51 ms |
| J2K, кандидат cv2 path | 513.88 ms | 263.11 ms | 262.76 ms |

Sandbox имеет 2 logical CPU. У J2K openjpeg CPU time близок к wall time даже с несколькими workers, у cv2 наблюдается использование двух CPU. Увеличение `_MAX_DECODE_WORKERS = 4` до 8/16 здесь не помогает. GUI prefetch вообще использует последовательный `decode_single_frame`, а не bulk ThreadPoolExecutor.

Помимо throughput, удержание GIL в worker мешает Python-слотам GUI исполняться. Перенос функции в QRunnable не гарантирует отзывчивость PySide-интерфейса. При частых J2K decode на ~42 ms/кадр возникают регулярные интервалы недоступности Python-потока UI; фактическую длительность GUI stalls нужно измерить heartbeat.

**Варианты:**

- Использовать cv2 для проверенного whitelist J2K (например, протестированные unsigned grayscale/RGB 8/16-bit). На наших 12 grayscale кадрах пиксели и dtype совпали во всех трёх повторениях. Это лишь candidate: проверить signed data, precision, YBR/RGB, planar layout, color Doppler, lossless/lossy и ошибки.
- Backend с native buffer API и освобождением GIL; отдельный benchmark применимых библиотек. Замена Python-обёртки иногда важнее замены самой OpenJPEG.
- Долгоживущий **ограниченный процессный пул**, если нужны неподдержанные cv2 форматы или гарантированная изоляция UI от GIL. Работать батчами, хранить decoder/source на стороне worker, передавать кадры через shared memory/ring buffer. Измерить Windows spawn, старт и IPC; не запускать процесс на каждый кадр/файл.

Обычный libjpeg-turbo относится к JPEG, а не автоматически к JPEG-2000. Установленный `pylibjpeg-libjpeg` не используется healthy fast path JPEG, который уже идёт через cv2. GPU/J2K SDK — отдельный проект с матрицей поддерживаемых TS/bit-depth/лицензий, не первоочередное решение.

### P1-A. Приоритеты миниатюр теряются, фон стартует для всей папки

**Код.** `MainWindow.__init__()` передаёт `self._controller.load_thumbnail` (`main_window.py:202`). Этот bound method принимает только `instance` и всегда вызывает `request_thumbnail_preview(..., P2_BACKGROUND)` (`app_controller.py:560–561`).

Галерея определяет поддержку приоритетов через `inspect.signature()` (`thumbnail_gallery.py:237–243`). Получается `_loader_accepts_priority=False`. Запросы выбранного/видимого элемента тоже поступают как P2. Первые visible задачи могут оказаться первыми по порядку вызова, но **priority upgrade фактически не работает**.

`_after_populate()` ставит в очередь миниатюры всех файлов. Scheduler ограничивает in-flight до 6, а не CPU budget. Все workers отправляются в общий `QThreadPool` без Qt priority; первый кадр selected cine — туда же. `DecodeGate` применяется только к FrameLoaderWorker и одному файлу, не к ThumbnailLoaderWorker/DicomDecodeWorker и не решает GIL/межфайловую конкуренцию.

**Исправление:** подключить callback, принимающий `(instance, priority)`; назначить абсолютный приоритет интерактивным запросам, затем playback, visible previews, near-visible и idle background. На открытии и Play приостанавливать/отменять фон. Ограничить background decode первоначально 1–2 задачами и проверить, а не поднимать concurrency вслепую. Использовать generation/cancellation при смене папки и выбранного файла; request_id, игнорирующий старый результат, не отменяет уже выполняющуюся тяжёлую работу.

Выделенный pool/Qt priority полезен против FIFO starvation, но сам по себе **не лечит GIL**. Thumbnail decoder обязан участвовать в общей политике владения сессиями.

### P1-B. Первый compressed кадр требует всего compressed файла

**Код.** `session.open()` для compressed делает `Path.read_bytes()` всего файла; `_ensure_pixel_data()` повторно парсит его через BytesIO; `_build_encapsulated_frame_index()` делает `list(generate_frames(...))`, материализуя compressed blobs всех кадров (`dicom_session.py:322–354,560–562,622–668`).

Lazy здесь означает «не распаковывать все кадры», но не «не читать/не копировать весь payload». Для одной миниатюры файла 70 MB это существенно. `_pixel_data_raw` и `_encapsulated_frames` удерживают примерно две копии compressed payload; transient parse может поднять память ещё выше. Несколько workers усугубляют аллокации и memory bandwidth. Влияние на gold необходимо измерить отдельно от codec.

**Исправление:** file-backed/mmap compressed source + frame offset/fragment index; BOT/EOT при наличии; fallback один раз сканирует fragment boundaries, но не копирует все кадры. Читать/собирать только нужный codestream. Учесть multi-fragment frames, пустой BOT, EOT, undefined-length sequences, отсутствие NumberOfFrames. Не заменять корректный DICOM parser поиском JPEG markers без проверок.

Миниатюра сейчас выбирает **средний** кадр, декодирует полный resolution и лишь затем уменьшается до 96 px (`thumbnail_loader_worker.py:27–31,126–152`). Поддерживаемый codec-level reduced-resolution decode может помочь, но для измерений нужен исходный кадр. Первый кадр вместо среднего — продуктовый компромисс: у УЗИ возможен замороженный/неинформативный префикс.

### P1-C. Дополнительные блокировки UI после первого кадра

**Код; вклад в 30 s не измерен.** В `load_instance()` заголовок аннотаций читается синхронно на GUI. В deferred restore выполняются overlays, Doppler calibration и auto-depth calibration.

При Doppler `_load_ecg_for_strip()` вызывает `read_ecg_waveform(path)` синхронно (`viewer_widget.py:2934,2971–2985`). Последняя использует **pixel session.open()**, хотя нужна WaveformSequence из metadata (`dicom_session.py:184–188`). Это может читать весь compressed payload, ждать locks и сбрасывать другие сессии даже при отсутствии ECG.

`QTimer.singleShot(0, restore)` откладывает работу, но не выносит её из GUI thread. Поэтому `first_frame_ready` не равняется «все инструменты отзывчивы». ECG/аннотации читать отдельно через metadata-only reader/cache в worker, expensive calibration профилировать и переносить асинхронно с проверкой request generation.

### P2. Кэши и второстепенные накладные расходы

- `FrameCache` активного ролика уже sparse/LRU. Defaults 64 MB с адаптивной настройкой и RAM cap 8%; очищается на смене instance. Полное кэширование всех роликов не нужно для начала работы.
- `_DecodedPixelCache` у DicomReader — отдельный 64 MB cache полных preview frames, с boundary-copy. FrameLoaderWorker его не использует: возможно повторное декодирование одного кадра разными путями. QImage/QPixmap галереи — ещё один слой.
- `_DecodedPixelCache.clear()` не сбрасывает `_current_bytes`; oversized entry может превысить лимит, ключ не учитывает mtime. Это отдельные дефекты accounting/invalidation, но не доказанная причина стартовых 30 s.
- Session registry ограничена количеством (10), не байтами; hit не продвигает порядок в cleanup list, это не полноценный LRU. Просто увеличить число сессий недостаточно.
- Галерея очищает thumbnail caches при populate; persistent thumbnail cache отсутствует в этом пути. Для повторного открытия полезен disk cache готовых маленьких preview с ключом по content/stat + frame index + размер + decoder/render version, quota и очисткой. УЗИ кадры могут содержать burned-in patient data: кэш должен оставаться локальным с защитой доступа, нельзя автоматически публиковать его.
- Повторные header reads/обход каталогов и построение QListWidget оптимизировать после основных причин. На сетевом диске они могут стать более важными, чем в приведённом бенчмарке.

## 5. Синтетические замеры

Среда: Linux, Python 3.11.2, 2 logical CPU, NumPy 1.26.4, pydicom 3.0.2, OpenCV headless 4.11.0.86, pylibjpeg 2.1.0, libjpeg plugin 2.2.0, openjpeg plugin 2.3.0. Версии decode-зависимостей соответствуют `uv.lock`.

Детерминированный random noise (seed 20260909), **не клиническое изображение**. Native/JPEG/J2K: 60 кадров, 512×512, MONOCHROME2 uint8; RLE: 24 кадра, 128×128. JPEG quality=90; J2K lossless. Три повторения, ниже медианы. Файлы созданы локально перед замером; OS cache не сбрасывался, это не cold-disk тест. RSS в JSON — snapshot после фаз, **не peak RSS**.

| Фаза | Native | JPEG | J2K | RLE |
|---|---:|---:|---:|---:|
| Размер файла, MB | 15.73 | 12.38 | 17.11 | 0.40 |
| Header only, ms | 0.42 | 0.36 | 0.60 | 0.39 |
| Session open, ms | 1.82 | 3.15 | 4.16 | 0.54 |
| Pixel setup/index, ms | <0.01 | 5.22 | 7.02 | 0.53 |
| First-frame decode после setup, ms | 0.12 | 2.20 | 42.51 | 2.50 |
| Open → первый кадр, ms | 2.00 | 10.98 | 53.72 | 3.64 |
| Полный decode после отдельного setup, ms | 0.06 | 68.43 | 2672.28 | 74.99 |
| Fallback calls на полный decode | 0 | 0 | 0 | 24 |

Медиана суммы не обязательно равна сумме медиан отдельных фаз. Native bulk возвращает mmap view — это не чтение всех страниц/отрисовка всего cine за 0.06 ms. RLE первый кадр включает full-cine fallback; название фазы обозначает запрос, а не гарантированное число реально декодированных кадров.

На J2K время полного decode в ~2.67 s и первого кадра в ~54 ms хорошо демонстрирует, почему нельзя ставить полный decode перед интерактивной готовностью. При ~42 ms/frame последовательный prefetch такого синтетического J2K не выдерживает 30 fps (бюджет ~33 ms/frame). Нужны более быстрый backend/реальный параллелизм, а не только более глубокий буфер.

**Не переносить эти миллисекунды на gold:** другая энтропия, размеры, TS, число каналов, CPU и состояние кэша. Числа подтверждают механизмы и порядок величин, но не дают коэффициента ускорения конкретной папки.

## 6. План внедрения и проверки

| Шаг | Изменение | Какой выигрыш ожидать | Проверка |
|---|---|---|---|
| 1 | Lease/pin активной сессии, thumbnails не освобождают чужие buffers; безопасное rewarm | Устранение повторных чтений и случайного full fallback | Interleaving A batch / B thumbnail, без потери pixels; bounded RAM при 114 файлах |
| 2 | Indexed single-frame fallback, один full decode для bulk fallback | Устранение O(N)/O(N²) лишней работы | Счётчик реально decoded frames = requested frames; RLE/JPEG/J2K и сломанные fast paths |
| 3 | Подключить thumbnail priority, pause/cancel idle work, generation | Меньше queue delay до first frame/Play | Click во время фоновой галереи и быстрая смена файлов/папок |
| 4 | GIL-releasing J2K backend либо persistent process pool | Throughput/отзывчивость; на нашем candidate ~2× batch на 2 CPU | Pixel equivalence + heartbeat + CPU/wall + IPC/RAM |
| 5 | Indexed file-backed compressed source, persistent preview cache | Меньше cold I/O/копий, существенно быстрее repeat-open | Cold/warm folder, BOT/EOT/empty BOT, invalidation |
| 6 | Metadata-only ECG/annotations, async calibration; prefetch tuning | Инструменты доступны без post-render блокировок | Paint и controls latency отдельно; all-frame инструменты имеют собственный progress |

Шаги 1–3 нужно делать вместе с тестами владения и очередей, а не удалением locks. Шаг 4 не заменяет их: быстрый codec всё ещё будет страдать от full fallback и cache thrashing.

Для будущих regression tests необходимы: B не освобождает leased A; rewarm compressed после release; first-frame без full-cine decode; registry соблюдает byte budget и не держит global lock на I/O; cancellation stale generation; visible priority действительно проходит MainWindow → Controller; supported TS pixel equivalence. Нужны stress tests двух viewport и repeated A→B→A, а не только многопоточного чтения одного файла.

### Ориентиры приёмки, не обещания результата

На согласованной целевой машине и реальном corpus:

- p95 click → painted frame порядка <1 s на локальном SSD;
- basic инструменты доступны после первого кадра, независимо от готовности галереи;
- p95 GUI heartbeat lag порядка <50 ms, отсутствие пауз >200 ms от фона;
- playback выбранных representative cine держит target FPS либо явно показывает buffering;
- healthy JPEG/J2K single-frame: 0 full-cine fallback;
- повторное открытие папки использует preview cache; память ограничена и не растёт с числом повторных открытий.

Точные бюджеты согласовать с resolution/TS/hardware. Инструменты, которым действительно нужен весь cine (speckle/M-mode/анализ), могут иметь отдельную подготовку по запросу, но не блокировать обычные измерения на одном кадре.

Не кэшировать всю папку распакованной в RAM: например, 114 роликов по 200 кадров 512×512 RGB uint8 — **около 17.9 GB только пикселей**, ещё до объектов, копий и моделей. Это иллюстрация формулы, не оценка фактического gold.

## 7. Как проверить на реальной папке

Добавлен [`bench/dicom_loading_audit.py`](../../bench/dicom_loading_audit.py). Запуск из корня в окружении проекта, без GUI:

```bash
# Первичная диагностика: 8 sampled frames, без опасного полного decode.
python bench/dicom_loading_audit.py /path/to/gold \
  --limit 30 --samples 8 --workers 1 2 4 --repeats 3 \
  --reference --alternatives --output bench/reports/gold_loading_audit.json

# Полный decode — сначала на одном representative файле!
python bench/dicom_loading_audit.py /path/to/one-file.dcm \
  --samples 8 --bulk --reference --output bench/reports/one_full_decode.json

# Воспроизведение синтетических результатов этого отчёта:
python bench/dicom_loading_audit.py --synthetic \
  --samples 12 --workers 1 2 4 --repeats 3 --bulk --reference --alternatives \
  --output bench/reports/dicom_loading_synthetic.json
```

Скрипт:

- Разделяет header, `open`, payload setup/index, first frame, warm middle, sampled codec batch и optional full decode.
- Считает fallback calls по фазам; измеряет wall/process CPU и RSS snapshots.
- Сравнивает 1/2/4 threads на тёплом codec path, **не заявляя это за GUI latency**.
- `--reference` проверяет время pydicom indexed API, `--alternatives` — cv2 J2K candidate и equality sampled пикселей относительно текущего декодера. Это не валидатор всех DICOM семантик.
- В synthetic режиме также запускает A/B session interference probe. Никаких клинических данных не генерирует/не меняет.
- JSON не содержит имён файлов, путей, patient fields и SOP/Study UIDs: только ordinal file_id и технические параметры. Сообщения ошибок ограничены именем типа исключения; сторонние библиотеки могут писать чувствительные значения в stderr, его перед публикацией надо проверять.
- Directory discovery принимает DICM-signature, включая extensionless; файл без preamble надо передать явно. SR/non-image/повреждённые файлы учитываются как error_type, не как «успешный быстрый decode».
- `--bulk` может быть очень медленным и потреблять много RAM из-за существующего fallback; на всей папке начинать без него. Скрипт не вводит таймаут на зависший codec: при необходимости запускать отдельный файл под внешним process timeout.
- Не запускать внутри работающего GUI: harness временно инструментирует класс decoder. Output лежит в уже игнорируемом `bench/reports/`; временные synthetic DICOM удаляются автоматически.

Для реального GUI A/B-эксперимента нужны дополнительные замеры, которых headless harness не делает:

1. folder_open, scan_done, gallery_populated;
2. click/request_submitted, worker_started (queue wait);
3. session open/release, lock wait, compressed bytes read, frame-index build;
4. backend/TS/index/fallback reason, число реально распакованных кадров;
5. first_frame_ready, Qt signal received, **первый paint**, controls usable;
6. Play, warmup complete, displayed FPS/stalls, cache hits/evictions;
7. heartbeat timer и sampled peak RSS/CPU/дисковые bytes.

Уже есть `scan_done`, `tree_populate_done`, `click_to_frame_loaded`, `first_preview_emitted`, `ECHO_FREEZE_DIAG=1`, `ECHO_PLAYBACK_DIAG=1`. Но click_to_frame_loaded логируется до actual paint, а decode_progress может сообщить total/total при `first_frame_only=True`; это не доказательство полного decode.

Сценарии: cold launch/cold filesystem cache отдельно от warm reopen; 1/30/114 файлов; выбранный cine без thumbnails против visible-only против all-background; J2K/JPEG раздельно; 1/2/4 workers; A→B→A и выбор кадра во время сканирования/фона. Не сбрасывать системный page cache без согласования и не смешивать холодные/тёплые результаты. Анализировать p50/p95/max и распределение по TS, не только сумму.

## 8. Уточнение по фактическим сценариям пользователя

После первоначального расследования пользователь описал два сценария:

1. Открыть папку из 114 файлов, сразу перейти к последнему, дождаться его миниатюры, нажать и дождаться декодирования: около **40 s суммарно**.
2. Открыть ту же папку, сразу выбрать первый/второй ролик, нажать Play и ждать начала воспроизведения: около **9 s от нажатия Play** (уточнено пользователем).

Это **наблюдения пользователя**, а не замеры sandbox. Пользователь уточнил, что третьего сценария не было.

### Последний файл: подозрение прежде всего на очередь миниатюр

После populate вся галерея ставится в background queue. Скролл вызывает request_visible_previews через debounce, но при текущем подключении callback приоритет P0/P1 не передаётся. ThumbnailScheduler.enqueue при повторном запросе с тем же P2 не меняет место уже поставленной задачи. Поэтому поздний элемент может остаться за множеством предшествующих запросов, хотя он уже видим пользователю.

Это объясняет качественную разницу между первым и последним элементом; точное место последнего запроса зависит от порядка Qt events, момента скролла и уже выполняющихся workers. Без trace нельзя утверждать, что обязательно завершились все 113 предшествующих задач.

Важно: 40 секунд включают **ожидание миниатюры до клика**, а не только декодирование выбранного ролика. Требуются отдельные отметки folder_open → last_item_visible → last_thumbnail_ready → click → first_frame_painted. Готовая миниатюра обычно получена из среднего кадра и сама по себе не означает, что первый кадр активного viewer или playback buffer уже готовы.

### Первый/второй файл: отдельный барьер первого playback batch

Ранние миниатюры обходят большую часть очереди, но после Play продолжаются фоновые thumbnail decode, конкуренция за GIL/pool и сбросы активной сессии.

Дополнительно в `AppController._prefetch_playback_buffer()` (`app_controller.py:1973–1984`) есть важная ветка: **cine до 60 кадров, помещающийся в cache, запрашивается целиком одним batch**. `FrameLoaderWorker._run_batch()` декодирует последовательно и отправляет `batch_finished` только после последнего кадра. Пока batch не доставлен в FrameCache, warmup не видит даже уже рассчитанные первые 3–5 кадров.

Таким образом, в этом условном случае Play фактически ждёт окончания полного первого batch, хотя формальный min_buffer мал. У длинных cine та же проблема существует в меньшем масштабе: UI получает все кадры начального батча вместе, не по достижении min_buffer. Это более точное объяснение возможной задержки старта, чем обязательная leading-static scan: если кадр 0 уже в кэше, `_ensure_leading_static_scanned()` проверяет доступные кадры и не запускает дополнительную загрузку префикса.

**Дополнение к плану:** отдельный короткий startup batch до min_buffer и немедленная его публикация; заполнение остального cine — после начала playback. Альтернатива — bounded streaming/chunked delivery кадров. Сохранить полезное кэширование короткого cine, но не делать его барьером первого движения. Размеры 55–60 кадров присутствуют в указанном пользователем диапазоне corpus; число кадров именно первого/второго ролика пока неизвестно, поэтому эта ветка остаётся проверяемой гипотезой для сценария 2.

Приёмочные сценарии теперь должны в точности повторять оба пользовательских workflow. Для первого основной KPI — viewport change → видимая миниатюра, не all-thumbnails-ready. Для второго — Play → первый следующий показанный кадр, отдельно от folder-open и первого статичного кадра.

## 9. Проверка изменений расследования

```text
ruff check bench/dicom_loading_audit.py tests/unit/test_dicom_loading_audit.py
All checks passed

QT_QPA_PLATFORM=offscreen python -m pytest \
  tests/unit/test_dicom_loading_audit.py \
  tests/unit/test_dicom_session.py \
  tests/unit/test_session_registry.py -o addopts='' -q
41 passed, 4 xfailed
```

Четыре xfail уже предусмотрены существующими тестами. Новых тестов harness — 6. Полный GUI/acceptance suite не запускался; тестовая среда для этих проверок дополнена scipy и PySide6-Essentials. Синтетический audit: 12 успешных запусков, 0 ошибок. Измерения в разделе 5 сняты до изменения production-кода — он в этом расследовании не менялся.

## 10. Реализованные исправления

Область изменений ограничена загрузкой/декодированием/миниатюрами/playback и их тестами. Код калибровок, контуров, сегментации, дизайн и виджеты инструментов не изменены. `pyproject.toml` и `uv.lock` изменены только в требовании pydicom >=3.0 для индексированного API; закреплённая версия 3.0.2 не обновлялась.

### Очередь миниатюр

- `load_thumbnail(instance, priority=...)` теперь сохраняет приоритет галереи. Не требуется менять MainWindow или внешний вид галереи.
- По умолчанию максимум 2 in-flight preview, отдельный QThreadPool, чтобы задачи первого кадра/playback не стояли за миниатюрами в общем FIFO.
- Во время pending first-frame decode и Play очередь не пополняет workers. Уже запущенным задачам разрешено закончить; после паузы/готовности первого кадра очередь возобновляется. Следовательно, при непрерывном Play невидимые миниатюры намеренно могут оставаться незагруженными.
- При смене папки pending thumbnail queue сбрасывается; cooperative cancellation пропускает ещё не начатое декодирование. Generation guard отбрасывает старые результаты, в том числе при совпадающих UID. Старые workers продолжают учитываться в общем лимите, пока не завершатся.

### Изоляция сессий

Вместо широкого изменения ownership всей registry применено более локальное исправление: `DicomReaderImpl(isolated=True)` для миниатюр, отдельная краткоживущая `DicomSession(isolated=True)`, `release()` в `finally`. Такие сессии не вызывают глобальную очистку, не регистрируются в playback registry, не ждут lock активного cine и не оставляют полный preview frame в глобальном pixel cache.

Существующая очистка shared sessions на смене активного файла сохранена: неконтролируемое удержание всех compressed cine в RAM не возвращается. Общая lease/byte-budget registry для нескольких активных viewers остаётся возможным следующим этапом, а не заявляется реализованной здесь.

Дополнительно compressed session после `release_heavy()` восстанавливает bytes/index при следующем покадровом запросе без требования повторного `open()`. Это защищает и другие допустимые interleavings shared sessions.

### Старт Play

- Пока warmup pending, запрашивается только недостающая часть стартового min_buffer, а не оставшиеся 54–59 кадров короткого cine.
- После доставки этого batch сначала завершается warmup и начинается движение; полное кэширование короткого cine сохраняется как последующая работа.
- Threshold ограничен числом кадров ролика и ёмкостью кэша; учтён переход через конец cine и уже готовые кадры.
- Результат prefetch старого файла больше не записывается в cache нового выбранного cine.

### Fallback и J2K

- `_decode_pydicom_fallback(i)` вызывает `pydicom.pixels.pixel_array(path, index=i, ...)`, возвращая принадлежащий одному кадру contiguous array. Ни `Dataset.pixel_array` всего cine на каждый запрос, ни удержания полного cine через `.base` больше нет в этом пути.
- OpenCV-first включён **только для JPEG2000Lossless `.90`, unsigned MONOCHROME1/2, BitsAllocated 8/16**. Проверены исходные пиксели и pydicom reference для 8/12/16 stored bits. Несоответствие dtype/shape или отказ cv2 возвращает существующий backend.
- Для color, signed, lossy и прочих J2K variants backend не переключён: их клиническую матрицу нужно проверять отдельно на corpus. Процессный пул в этом изменении не внедрялся. Поэтому устранение GIL для абсолютно всех файлов не обещается.

### Повторные синтетические измерения

Те же fixtures, 3 повторения, окружение decode прежнее; медианы, не GUI latency:

| Измерение | До | После |
|---|---:|---:|
| J2K, bulk 60 кадров | 2672 ms | 1297 ms |
| J2K, batch 12 кадров / 2 threads | 519 ms | 253 ms |
| RLE, bulk 24 кадра | 75 ms | 27 ms |
| Следующий JPEG кадр после принудительного охлаждения shared A через shared B | 649 ms, full fallback | 8.7 ms, **0 fallback**, восстановлен индекс |
| Backing array одного RLE frame 128×128 | 393216 bytes | 16384 bytes |

Последняя A/B-проверка намеренно использует **shared** B, сохраняя исходный probe. Реальная миниатюра теперь использует isolated B и вообще не охлаждает A; это покрыто отдельными regression tests. Синтетический audit после исправлений: 12 успешных запусков, 0 ошибок. Сырые данные — `bench/reports/dicom_loading_after.json` (ignored).

### Проверка и ограничения

Выполнено:

```bash
# В sandbox отключён автозапуск pytest-qt: у среды нет полного набора системных Qt/GL libs.
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p pytest_timeout \
  tests/unit/test_dicom_loading_fixes.py \
  tests/unit/test_dicom_loading_audit.py \
  tests/unit/test_dicom_session.py \
  tests/unit/test_session_registry.py \
  tests/unit/test_thumbnail_scheduler.py -o addopts='' -q
# 68 passed, 4 xfailed
```

Покрыты pixel equality, fallback per-index и ownership, отсутствие чужого lock/eviction при preview, очистка при ошибке, compressed rewarm, thread/session registry, порядок и reset очереди. Ruff для изменённых Python-файлов проходит.

Добавлены **Qt integration regression tests**, но их запуск в sandbox пока блокируется отсутствием системных OpenGL-библиотек (`libGL.so.1` при стандартном запуске). Они **не включены** в число успешно выполненных выше. Проверять в рабочем окружении SonoForge:

```bash
python -m pytest \
  tests/unit/test_app_controller_thumbnail_priority.py \
  tests/unit/test_playback_prefetch.py \
  tests/unit/test_thumbnail_qimage.py \
  tests/unit/test_presentation_thumbnail_gallery.py -o addopts='' -q
```

Новые сценарии этих тестов: callback галереи и последний из 114 элементов; пауза thumbnail pump на first-frame/Play; stale generation с одинаковым UID и соблюдением concurrency cap; отдельный preview pool; startup 2/5/55/60/61/380 кадров, loop wrap и запрет загрязнения cache старым cine.

**Реальные 40 s и 9 s после исправления пока не перемерены:** исходных 114 DICOM и GUI-trace машины пользователя здесь нет. Следующая приёмка — повторить оба пользовательских сценария, отдельно отметить время появления последней миниатюры, click → кадр и Play → первое движение. Полный GUI/acceptance suite также не заявляется пройденным.
