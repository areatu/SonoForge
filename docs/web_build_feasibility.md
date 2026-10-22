# SonoForge Web — анализ осуществимости браузерной сборки

> Вопрос: реально ли с текущей архитектурой сделать web-build (запуск из браузера без
> привязки к ОС) наподобие браузерного клиента Orthanc, и насколько это сложно?
>
> Дата анализа: 2026-10-06. Оценки даны в «человеко-неделях» (hw) для одного
> опытного разработчика, знакомого и с Python-ядром, и с фронтендом.

---

## 1. Короткий ответ

**Реально, но не как «сборка текущего кода в WebAssembly», а как пересадка ядра + новый UI.**

Три разные цели, которые часто путают в этой формулировке, стоят очень по-разному:

| Цель | Что это значит | Реальность | Оценка |
|---|---|---|---|
| **A. Браузерный клиент к PACS/Orthanc** (аналог Orthanc Explorer / OHIF, но с вашей логикой измерений) | Python-ядро в Pyodide + новый JS/TS UI, данные только по DICOMweb (QIDO/WADO/STOW) | ✅ Да, без исследовательских работ | **28–40 hw** (≈7–10 мес. в одиночку) |
| **B. Полный паритет с десктопом** (+ AI-сегментация, STE/speckle, M-mode, мультивью, презентер, конструктор справочников, офлайн) | То же + перенос всей тяжёлой обработки и всей оболочки | ⚠️ Да, но упрётся в производительность/память | **60–90 hw** (≈1.5–2 года) |
| **C. Сам Orthanc (DICOM-сервер) в браузере** | SQLite + C++ + DIMSE внутри WASM-страницы | ❌ Нецелесообразно | — |

Про «Orthanc в браузере» отдельно: Orthanc — это сервер (хранилище + DIMSE + REST).
Браузер не умеет ни слушать порт, ни открывать произвольный TCP-сокет, поэтому
«Orthanc в браузере» технически означало бы не сервер, а Thick Client к нему. То, что
называют «браузерным клиентом Orthanc» (Orthanc Explorer 2, OHIF Viewer, Cornerstone3D) —
это всегда **клиент** к DICOMweb/REST API, а не сервер. Именно этот вариант (A/B) здесь и
разобран.

---

## 2. Что показывает анализ кода

Метрики по `src/echo_personal_tool` (Python, ~89k LOC):

| Слой | LOC | Файлов | Файлы с `PySide6` | Что переносится как есть |
|---|---|---|---|---|
| `domain` (модели, расчёты, сервисы) | 23 295 | 103 | **0** | ✅ целиком |
| `infrastructure` (DICOM, Orthanc, кодеки, репозитории) | 13 121 | 58 | 8* | ✅ ~76% (10 024 LOC без Qt) |
| `application` (контроллер, воркеры, кеш) | 10 196 | 25 | 15 | ⚠️ ~20% (2 088 LOC); логика воркеров(Qt-обёртки) — тонкая |
| `presentation` (весь GUI) | 34 464 | 59 | 52 | ❌ переписывать (345 LOC без Qt) |
| `ui` (панели STE, strain) | 4 099 | 11 | 7 | ❌ переписывать |
| `constructor` (редактор справочников) | 3 559 | 24 | 11 | ⚠️ ~30% (1 005 LOC) |

\* в `infrastructure` Qt встречается почти везде «мягко» и за отложенным импортом:
`QSettings` в `user_preferences.py`, `qInstallMessageHandler` в `logging_setup.py`,
`QGuiApplication` для диагностики. Единственное реально нетривиальное место —
`video_reader.py` (thread-local под пул потоков) и `dicom_session.py` (комментарии про GIL).

**Итого переносимого ядра: ~36–37k LOC (≈40% кода) — расчёты ASE, Doppler, M-mode,
Simpson, planimetria, калибровки, вендорные профили, парсинг DICOM, справочники, отчёты.
Переписываемого: ~42k LOC Qt-интерфейса.**

---

## 3. Сильные стороны текущей архитектуры (повод отвечать «да»)

1. **Честная гексагональная архитектура.** `domain/ports.py` описывает Protocol-ы:
   `IDicomReader`, `IStudyScanner`, `IVideoReader`, `IOnnxSegmenter`, `DicomWebClient`,
   `DimseClient`, `DicomUploadClient`. Домен — 103 файла, **ни одного** импорта `PySide6`.
   Это именно та граница, которая позволяет подменить транспорт, не трогая расчёты.
2. **DICOMweb уже реализован и является основным путём.** `infrastructure/orthanc_client.py`
   (666 LOC) — QIDO-RS + WADO-RS + STOW-RS поверх `httpx`, плюс фолбэки на Orthanc REST
   (`/instances/{id}/preview`, `frames/{n}/rendered`), ретраи, отмена, `study_statistics`,
   батчинг STOW. Адаптеры `stow_upload_adapter.py`, `dimse_upload_adapter.py`, фабрика
   `server_client_factory.py`. Для браузера это ровно тот протокол, который доступен.
3. **DIMSE изолирован в 4 файлах** (`dimse_client.py`, `dimse_find_mapper.py`,
   `dimse_upload_adapter.py`, `embedded_storage_scp.py`) и закрыт протоколом
   `DimseClient`. В веб-сборке он просто не инстанцируется — домен и сервисы запросов
   (`application/dicom_query_service.py`) этого не заметят.
4. **Уже есть готовый веб-актив.** `presentation/web_reference/` — это `index.html`,
   `script.js` (32 KB), `styles.css` (21 KB) и мост `web_reference_bridge.py`; работает в
   Qt через `QWebEngineView`. В веб-сборке этот кусок (структурированный справочник
   ASE) переиспользуется **как есть**, без переписывания.
5. **Сильная тестовая база:** 418 тестовых файлов, ~6 374 тест-функций, маркеры
   `gui`/`integration`/`regression`/`bench`. Домен можно гонять в CI и под CPython, и под
   WASM — это резко удешевляет валидацию порта.
6. **Совместимость с NumPy 2 уже почти есть.** В коде уже стоит защита
   `getattr(np, "trapezoid", None) or np.trapz` (`doppler_metrics.py`,
   `vti_cycle_service.py`), а `np.ptp(...)` используется в функциональной форме
   (удаляемые в NumPy 2 синонимы `np.float_`, `np.NaN`, `np.Inf`, `np.alltrue`,
   `np.round_` — не встречаются). Это важно: Pyodide поставляет **numpy 2.4.6**,
   а `pyproject.toml` требует `<3.12` и `numpy>=1.26,<2.0` — обновление пинов потребуется,
   но массовой правки кода, скорее всего, нет.

---

## 4. Ограничения среды (что несовместимо в принципе)

| Возможность | Статус в браузере | Последствие для SonoForge |
|---|---|---|
| **PySide6 → WASM** | ❌ Нет. Тикет [PYSIDE-962](https://qt-project.atlassian.net//browse/PYSIDE-962) открыт с 2019, фикс-версия в Jira — 6.7, коммиты уходят в `dev`/`6.11` (март 2026), но wasm-колёс на PyPI нет (только win/linux/macos); Qt Wiki прямо: *«iOS, and WebAssembly are not supported yet»* [3](https://wiki.qt.io/PySide6), платформа отмечена как *«(2) Ongoing research»* [5](https://qtinfo.dev/qtforpython/) | ~42k LOC GUI не переносятся — писать UI на JS/TS (Canvas/WebGL) |
| **Потоки / процессы** | ❌ Pyodide: `threading`, `multiprocessing`, `sockets` — *«included but not working»* [1](https://pyodide.org/en/stable/usage/wasm-constraints.html); FAQ: *«fork and pthreads do not work… attempts raise RuntimeError»* [4](https://pyodide.org/en/stable/usage/faq.html); ABI платформы прямо запрещает `-pthread` [1](https://pyodide.org/en/stable/development/abi.html) | В проекте 82 места с `QThreadPool`/`ThreadPoolExecutor`/`Lock`, 4 потока декодера, `decode_gate`. Всё фоновое → **Web Workers** (отдельные инстансы Pyodide, `postMessage`, без общей памяти) |
| **Сырые TCP-сокеты (DIMSE)** | ❌ Принципиально недоступны | `pynetdicom` (C-ECHO/C-FIND/C-GET/C-MOVE/C-STORE) и встроенный SCP (`embedded_storage_scp.py`, порт 11112) отпадают. Только DICOMweb, либо шлюз DIMSE↔DICOMweb |
| **CORS у Orthanc** | ⚠️ Orthanc **не** отдаёт CORS-заголовки: *«Orthanc does not feature built-in support for cross-origin resource sharing (CORS)»* [5](https://orthanc.uclouvain.be/book/faq/nginx.html) | Нужен reverse proxy (nginx) с `Access-Control-Allow-*` [5](https://orthanc.uclouvain.be/book/faq/nginx.html), либо раздача самого приложения с того же origin через плагин `serve-folders` [1](https://groups.google.com/g/orthanc-users/c/GG-dFIn2LQ0) |
| **Файловая система** | ⚠️ Есть `pyodide.mountNativeFS` (File System Access API) — https://pyodide.org/en/stable/usage/accessing-files.html, но только Chromium; кросс-браузерно — OPFS/IndexedDB + drag&drop | `infrastructure/paths.py` (XDG/AppData), `local_scanner.py` (рекурсивный обход каталогов), кеш инстансов на диске → виртуальная ФС + «импорт папки» вручную |
| **Память** | ⚠️ Одна WASM-куча, на практике 1–2 ГБ (предел Chrome — 4 ГБ) | `FrameCache` рассчитан на **2 ГБ**; копирование массивов через JS↔Python мост надо минимизировать (memoryview → `ImageData` без копии) |
| **Производительность** | ⚠️ Одно ядро, без потоков; WASM-SIMD есть, но ускорение не сравнимо с 4 потоками + нативным openjpeg | Декод JPEG2000-кино и optical-flow (STE, `speckle_worker.py` 1510 LOC) — главные кандидаты на тормоза |
| **Таймеры/точность** | ⚠️ Нет `timeBeginPeriod` (Win), таймеры браузера квантуются, throttling в фоновых табах | Плавность воспроизведения кино придётся перестраивать на `requestAnimationFrame` |

---

## 5. Вердикт по зависимостям

| Пакет | В Pyodide | Комментарий / замена |
|---|---|---|
| `pydicom` 3.0.2 | ✅ | Чистый Python, `py3-none-any` → `micropip.install` |
| `numpy`, `scipy`, `Pillow`, `scikit-image`, `shapely` | ✅ | Есть в сборке Pyodide (numpy 2.4.6, scipy 1.18.0) |
| `opencv-python` | ✅ | Есть (4.11.0.86). НО: ~90 вызовов cv2 в 17 файлах (оптический поток, контуры, CLAHE, `VideoWriter`, `VideoCapture`) — часть функциональности (видеокодеки) в wasm-сборке может отсутствовать → WebCodecs / `ffmpeg.wasm` |
| `httpx` 0.28.1 | ⚠️ | Pyodide кладёт httpx, но синхронный транспорт идёт через сокеты. Решение известное и дешёвое: патч-транспорт на Fetch API (Cloudflare делает это для Python Workers *«fewer than 100 lines of code»* [3](https://blog.cloudflare.com/python-workers/)), либо `requests` + `pyodide-http` (урllib3/requests в браузере работают через XHR/fetch [1](https://pyodide.org/en/stable/usage/wasm-constraints.html)) |
| `pynetdicom` | ❌ | Сокеты. Удалить из веб-профиля (DIMSE за протоколом) |
| `pylibjpeg-openjpeg` (JPEG2000) | ❌ | Нет wasm-рецепта. Обход: (1) WADO-RS `frames/{n}/rendered` / Orthanc `/preview` — сервер отдаёт PNG/JPEG, браузер декодирует сам (этот путь **уже есть** в `orthanc_client.py` для превью); (2) JS-WASM кодеки (`@cornerstonejs/codec-*`) через мост |
| `onnxruntime` | ❌ | Нет Python-wasm колёс. Замена — **ONNX Runtime Web** (WASM/WebGL/WebGPU) [1](https://onnxruntime.ai/docs/tutorials/web/) через JS-мост. Модели тяжёлые: LA-модель **158.5 МБ**, int8 LV — 40 МБ → кеш в OPFS/Cache Storage, WebGPU-EP |
| `psutil` (14 упоминаний) | ❌ | Заменить на `performance.memory` / заглушки (профилирование памяти) |
| `keyring` (15 упоминаний) | ❌ | WebCrypto + IndexedDB (учётные данные PACS). Секрет не защищён от XSS — важно для threat model |
| `pymupdf` | ✅ | PyMuPDF 1.28 публикует колёса **`pyemscripten_*_wasm32`** — PDF-справочники можно оставить |
| `reportlab`, `openpyxl`, `pyyaml`, `jsonschema` | ✅ | Чистые `py3-none-any` → `micropip` (PDF/Excel-экспорт сохраняется) |
| `pyqtgraph` (24 импорта) | ❌ | Нужен Qt → заменить на Chart.js/uPlot/Plotly/WebGL (Doppler, M-mode, ECG, кривые strain) |
| `cryptography` (Presenter) | ✅ | Есть в сборке Pyodide |

Размер бандла (порядок величин, мерить спайком): ядро Pyodide — 6.8 МБ
(`pyodide-core-314.0.7.tar.bz2`), полный дистрибутив всех пакетов — 337 МБ; реальный
cold start веб-страницы — ядро + numpy + scipy + opencv + pydicom, то есть десятки МБ и
единицы секунд до первого кадра.

---

## 6. План работ (этапы и оценка)

| # | Этап | Объём | hw |
|---|---|---|---|
| 0 | **Спайк:** загрузить `domain` + Qt-free `infrastructure` в Pyodide, прогнать тесты домена, измерить старт/декод/память | — | 2–3 |
| 1 | **Абстракция исполнителя:** вынести Qt из `application/workers/*` за интерфейс `IExecutor` (Qt: `QRunnable`/`Signal`; Web: `postMessage` в Worker); рефакторинг `app_controller.py` (4061 LOC) и `decode_gate.py` | 3.4k LOC воркеров | 3–4 |
| 2 | **HTTP-слой:** httpx-транспорт на Fetch (или `pyodide-http` + requests), обёртка над `pyfetch` с ретраями/отменой/прогрессом | ~1 файл + тесты | 1–2 |
| 3 | **Пиксельный конвейер:** мост numpy→`ImageBitmap`/Canvas без копий; стратегия кодеков (rendered-frames + WASM-кодеки); `FrameCache` под лимит WASM-кучи | `dicom_session.py` 905 LOC | 4–6 |
| 4 | **PACS-сценарий:** QIDO/WADO/STOW, кеш инстансов в OPFS, CORS-прокси + инструкция по nginx, диалог загрузки (аналог `orthanc_study_dialog.py`, 2380 LOC) | — | 3–4 |
| 5 | **Базовый UI:** каркас (React/Vue или vanilla+TS), вьюер кино-петли, калиперы, контуры, оверлеи, отчёт (аналог `viewer_widget.py`, 8267 LOC — самая дорогая часть) | — | 10–16 |
| 6 | **AI-сегментация:** `onnxruntime-web` + WebGPU, кеш моделей, адаптер `IOnnxSegmenter` | — | 2–3 |
| 7 | **Экспорт:** PDF/Excel работают как есть; MP4 — WebCodecs/`ffmpeg.wasm` | — | 2–4 |
| 8 | **Тяжёлые режимы:** Doppler/M-mode (замена pyqtgraph), STE/speckle (оптический поток, 1510 LOC воркера — вынос в воркер + проверка скорости) | — | 8–16 |
| 9 | **Прочее:** мультивью, презентер (зеркалирование), конструктор справочников (переиспользовать готовый `web_reference/`), офлайн/PWA | — | 6–10 |
| 10 | **Регрессия и тюнинг:** перф-бюджеты, golden-тесты под wasm, e2e в браузере | — | 6–10 |

**Суммарно:**
- **Tier 0 «Просмотрщик»** (Orthanc → список исследований → кино-петля → калиперы → PDF-отчёт): **12–16 hw** (≈3–4 мес.)
- **Tier 1 «Рабочий клиент»** (+ Doppler, M-mode, AI, локальные файлы, экспорт): **28–40 hw** (≈7–10 мес.)
- **Tier 2 «Паритет с десктопом»** (+ STE, мультивью, презентер, конструктор, офлайн): **60–90 hw** (≈1.5–2 года)

---

## 7. Главные риски

1. **Непредсказуемость производительности.** Всё, что сегодня прячется за 4 потоками
   (`ThreadPoolExecutor` в `dicom_session.py`, `decode_gate`, `speckle_worker`), в браузере
   станет однопоточным, если не выносить в Web Workers, а воркеры не делят память →
   копирование кадров между воркерами дорого. *Проверить спайком этапа 0.*
2. **Кодеки DICOM.** JPEG2000 (1.2.840.10008.1.2.4.90-93) — обычный формат эхо-кинопетель.
   Без `pylibjpeg-openjpeg` остаётся либо серверный рендер (`rendered`), либо JS-кодеки.
   Для локальных файлов (без PACS) это критичный путь.
3. **CORS/инфраструктура.** Браузерный клиент к Orthanc **не заработает** без nginx-прокси
   (или `serve-folders`) — это надо заложить в документацию и в установку [5](https://orthanc.uclouvain.be/book/faq/nginx.html).
4. **Память.** 2-ГБ `FrameCache` и кинопетли 1280×720×N в одной WASM-куче — нужен новый,
   более жёсткий бюджет и пред-декодинг в воркере.
5. **Дрейф кодовой базы.** Появление второго UI (Qt + Web) удваивает стоимость каждой
   новой фичи. Обязательное условие окупаемости — чтобы вся новая логика рождалась в
   `domain`/`application`, а UI-слои оставались тонкими. Сейчас это в целом выполняется
   (домен без Qt), но `presentation/viewer_widget.py` (8267 LOC) — явно «жирный» виджет,
   в котором часть логики стоит вынести вdomain до начала порта.
6. **Безопасность.** Хранение паролей PACS в IndexedDB/WebCrypto слабее OS keychain;
   браузерный клиент чувствителен к XSS. Требуется пересмотр threat model из `SECURITY.md`.

---

## 8. Рекомендация

1. **Начать со спайка (2–3 недели), а не с порта.** Цель спайка — ответить на три
   вопроса цифрами: (а) грузится ли `domain` + Qt-free `infrastructure` в Pyodide и
   проходят ли тесты домена; (б) время декода одного кадра JPEG2000 и всей петли без
   потоков; (в) реальный размер бандла и cold start. Если (б) даёт >150 мс/кадр на
   720p — AI/STE в браузере придётся либо упрощать, либо считать на сервере.
2. **Портировать не «приложение», а ядро:** домен + инфраструктура + DICOMweb.
   UI — новый, на JS/TS. Пытаться тащить Qt в браузер (PySide6-WASM, Qt for WebAssembly,
   PyQt) — тупик: официальной поддержки нет [3](https://wiki.qt.io/PySide6) [5](https://qtinfo.dev/qtforpython/).
3. **Первый релиз делать как Tier 0/Tier 1 и позиционировать не как замену десктопу**, а
   как «SonoForge Viewer» для Orthanc: просмотр, калиперы, Doppler, отчёт. Это закрывает
   80% сценариев «посмотреть исследование с любого компьютера» и не требует STE/AI/конструктора.
4. **Держать один источник правды по расчётам.** Веб-клиент ценен именно тем, что считает
   **той же** формулой ASE/Simpson, что и десктоп. Любое дублирование расчётов на JS
   обесценивает затею — поэтому Pyodide (а не переписывание домена на TS) оправдан,
   несмотря на стоимость загрузки рантайма.

---

## 9. Что трогать в первую очередь (карта работ)

```
domain/                    23 295 LOC   — не трогать, портируется как есть
infrastructure/
  orthanc_client.py           666 LOC   — использовать; заменить httpx-транспорт на fetch
  orthanc_dicom_json.py                 — QIDO-парсинг, как есть
  stow_upload_adapter.py                — как есть
  dicom_session.py             905 LOC  — кодеки + ThreadPoolExecutor → воркер/JS-кодеки
  local_scanner.py                      — обход каталогов → FSA/OPFS
  paths.py                              — XDG/AppData → виртуальная ФС
  onnx_engine.py                        — ORT → onnxruntime-web
  server_settings.py                    — keyring → WebCrypto/IndexedDB
  dimse_*.py, embedded_storage_scp.py   — исключить из веб-профиля
  playback_diagnostics.py               — psutil → performance.memory
application/
  workers/*                  3 384 LOC  — Qt-обёртки → Web Worker messaging (IExecutor)
  app_controller.py          4 061 LOC  — QThreadPool/Signal → IExecutor + JS-колбэки
presentation/              34 464 LOC   — переписывать (кроме web_reference/*)
ui/                         4 099 LOC   — переписывать
constructor/                3 559 LOC   — частично (Qt-редактор), web_reference переиспользовать
tests/                      6 374 теста — доменные тесты гонять под wasm в CI
```

---

## Источники

- Ограничения Pyodide (threading/multiprocessing/sockets не работают): [1](https://pyodide.org/en/stable/usage/wasm-constraints.html), FAQ [4](https://pyodide.org/en/stable/usage/faq.html)
- Pyodide ABI: `-pthread` запрещён [1](https://pyodide.org/en/stable/development/abi.html)
- Список пакетов Pyodide (версии numpy/scipy/opencv/httpx): https://pyodide.org/en/stable/usage/packages-in-pyodide.html
- Доступ к файлам в браузере (`mountNativeFS`, File System Access API): https://pyodide.org/en/stable/usage/accessing-files.html
- PySide6 и WebAssembly не поддерживается: [3](https://wiki.qt.io/PySide6), [5](https://qtinfo.dev/qtforpython/), тикет [PYSIDE-962](https://qt-project.atlassian.net//browse/PYSIDE-962)
- Orthanc не поддерживает CORS, обход через nginx/serve-folders: [5](https://orthanc.uclouvain.be/book/faq/nginx.html), [1](https://groups.google.com/g/orthanc-users/c/GG-dFIn2LQ0)
- ONNX Runtime Web (WASM/WebGL/WebGPU): [1](https://onnxruntime.ai/docs/tutorials/web/)
- Патч httpx на Fetch API в WASM-рантайме: [3](https://blog.cloudflare.com/python-workers/)
