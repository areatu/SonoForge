# Ревью: загрузчик DICOM с сервера (Orthanc / DICOMweb / DIMSE)

Дата: 2026-09-04
Ветка: `arena/01a06e35-sonoforge` (base `c213b56`)

## Охваченный код

| Модуль | Роль |
|---|---|
| `presentation/orthanc_study_dialog.py` | диалог поиска/скачивания (912 стр.) |
| `application/workers/orthanc_download_worker.py` | фоновое скачивание, retry, отмена |
| `application/dicom_query_service.py` | единая точка запросов DICOMweb/DIMSE/Auto |
| `application/services/dicom_retrieve_service.py` | адаптеры скачивания WADO/C-GET/C-MOVE, `auto` |
| `infrastructure/orthanc_client.py` | QIDO-RS запросы + Orthanc REST скачивание, retry |
| `infrastructure/dimse_client.py` | pynetdicom C-FIND / C-GET / C-MOVE |
| `infrastructure/server_client_factory.py` | сборка клиентов/сервисов |
| `infrastructure/server_settings.py`, `orthanc_cache.py`, `embedded_storage_scp.py` | настройки, кэш сессии, SCP приёмник |
| `presentation/server_settings_dialog.py` | настройки сервера, C-ECHO |
| `presentation/main_window.py` (`_open_orthanc_dialog`) | точка входа |

Проверка статическая; не-GUI unit-тесты (`test_dicom_*`, `test_orthanc_client*`, `test_dimse*`, `test_orthanc_download_worker`, `test_orthanc_cache`) в этом окружении проходят. GUI-тесты запустить не удалось (в песочнице нет системных `libGL`/`libEGL`, а apt-репозитории недоступны).

---

## Что сделано хорошо

- **UI не блокируется сетью**: все сетевые операции (поиск, список серий, скачивание, C-ECHO) вынесены в `QRunnable`/`QThreadPool` и `ThreadPoolExecutor`; сигналы — queued.
- **Жизненный цикл диалога защищён**: `_is_alive()` + `shiboken6.isValid`, отключение сигналов в `_shutdown()`, таймер принудительного закрытия 30 с (`_CANCEL_FORCE_CLOSE_MS`), корректная обработка `closeEvent/reject/accept` во время скачивания.
- **Скачивание**: дедупликация по SOP Instance UID, retry инстанса 3 раза с backoff 1с/2с, интервальный сон 0.2 с для быстрой отмены, пер-инстансные клиенты в потоках, валидация UID против path traversal (`safe_uid_path_component`), `chmod 600` у файлов, очистка сессии по возрасту.
- **HTTP**: retry только на транзиентные ошибки (timeout/5xx/сеть), не на 401/404; прерываемые паузы при отмене.
- **Безопасность**: пароли в keyring (не в QSettings), TLS-опции с предупреждением при `verify=False`, секрет не логируется.
- **Тесты** покрывают query/retrieve/client/worker/cache (все зелёные в прогоне выше).

---

## Находки

### 🔴 H1. Открытие диалога может «заморозить» GUI на время network_timeout (30 с)

`OrthancStudyDialog.__init__`, строка 140:

```python
self._retrieve_service = make_dicom_retrieve_service(server_settings) if server_settings is not None else None
```

→ `server_client_factory.make_dicom_retrieve_service` → `dicom_retrieve_service.make_retrieve_service` → `_wado_reachable(web_client)` → **синхронный** `GET {orthanc_root}/system` (таймаут `settings.network_timeout`, по умолчанию 30 с). Всё это выполняется в потоке GUI в конструкторе, ещё до показа окна. При недостижимом, но «молчащем» сервере (blackhole/firewall drop) интерфейс виснет до 30 с; при этом сам ping проверяет корень Orthanc (`/system`), а не DICOMweb-эндоинт.

**Предложение**: вынести ping в фоновый поток и строить retrieve-service лениво/по результату; либо использовать короткий таймаут проверки (2–3 с) и проверять доступность именно DICOMweb (например, лёгкий QIDO-запрос или `GET /dicom-web`).

---

### 🔴 H2. Частичный сбой стирает успешно скачанные исследования; в следующий запуск попадают «мёртвые» pre-scanned studies

При загрузке нескольких исследований (`_start_next_download`, стр. 640) завершение с `_failed_downloads > 0` ведёт в `_on_failed()` (стр. 879), который делает:

```python
self._cache.clear_session(self._session_id)   # стр. 888 — удаляется ВЕСЬ каталог сессии
```

т.е. **файлы успешно скачанных исследований удаляются** вместе с файлами упавших. При этом:

1. `_downloaded_studies` (стр. 778) не очищается ни в `_on_failed`, ни в начале нового `_on_load` (стр. 572). После сообщения «Часть исследований не загружена» диалог остаётся открытым; при повторном успешном скачивании `accept()` вернёт список, где **метаданные удалённой сессии соседствуют с новыми**, и `load_pre_scanned_studies` в `app_controller.py` (стр. 316) отдаст вьюеру StudyMetadata с несуществующими путями к файлам.
2. Та же проблема в ветке «Скачать на диск» (`_start_next_download_to_disk`, стр. 682→695): при частичном сбое копирование на диск вообще не выполняется, кэш очищается.

**Предложение (минимально-инвазивное)**:
- в начале каждого `_on_load`/`_on_save_to_disk` сбрасывать `_downloaded_studies = []`;
- в терминальной ветке `_start_next_download`: если что-то скачалось (`_completed_downloads > _failed_downloads`), не вызывать `_on_failed` с очисткой сессии, а показать предупреждение и завершиться через `_on_done(...)` — успешные исследования реально загружены и должны быть доступны пользователю; если не скачалось ничего — текущее поведение (очистка + ошибка) корректно.

Тесты `test_start_next_download::test_partial_failure_shows_error` зафиксируют необходимость обновить ожидание.

---

### 🟠 M1. Ошибки на уровне «список исследований» всегда превращаются в пустой список — сервер недоступен ≠ «ничего не найдено»

- `dicom_query_service._web_query_studies` (стр. 100) ловит `Exception` и возвращает `[]`.
- `DIMSE _c_find` (`dimse_client.py`, стр. ~215) глотает ошибки ассоциации и тоже возвращает `[]`.
- `_StudyQueryWorker` (dialog, стр. 78) при исключении возвращает `[]`, а `_on_studies_loaded` просто строит пустое дерево со статусом «Готово».

Итог: при недоступном сервере, неверном пароле (401) или отключённом DIMSE пользователь видит **пустой список** — неотличимо от «на сервере нет исследований». Ошибка показывается только на уровне серий (и то лишь для DICOMweb-исключений, `_on_series_loaded`, стр. 495). Неиспользуемые ключи i18n `orthanc.find_error`, `orthanc.connect_error.*`, `orthanc.server_available/unavailable` намекают, что индикация соединения задумывалась, но не реализована.

**Предложение**: вернуть признак ошибки из worker'а (как в `_SeriesQuerySignals`) и показывать строку/итем ошибки с текстом (401/таймаут/недоступен); в `DicomQueryService` — пробрасывать исключение в явном режиме `DICOMWEB`/`DIMSE` (не глотать), а `[]` резервировать только под «успешно, но пусто».

---

### 🟠 M2. Режим «Auto» скачивания — не fallback, а разовая привязка при старте; проверяется не тот эндпоинт

`make_retrieve_service` (стр. 233+): `auto` = тот адаптер, который ответил на **один** `ping()` в момент создания. Далее `DicomRetrieveService.retrieve_instance(source='auto')` всегда идёт в привязанный адаптер (`_resolve_adapter`), **без попытки переключиться** при сбоях. Сценарии:

- `/system` отвечает, а `/dicom-web` (QIDO/WADO) закрыт/сломан реверс-прокси → `auto` навсегда выбирает WADO, все скачивания падают, DIMSE не подхватывается;
- WADO «отвалился» в процессе — worker делает 3 retry инстанса и сдаётся, fallback на C-GET/C-MOVE не происходит.

**Предложение**: в `DicomRetrieveService.retrieve_instance` при ошибке выбранного адаптера пробовать остальные в порядке приоритета (например `wado → dimse → cmove`), а `ping` для выбора делать не по корню Orthanc, а по DICOMweb-возможностям, либо вообще отказаться от предварительного ping и пробовать адаптеры по очереди при первом сбое.

---

### 🟠 M3. Кнопка «Отмена» не прерывает активные запросы в реальном сценарии (через DicomRetrieveService)

`OrthancDownloadWorker.cancel()` (стр. 104) закрывает `_thread_client` и thread-local клиенты. Но в рабочем пути (диалог с `server_settings`) каждый инстанс качается через `_retrieve_service.retrieve_instance(...)` (стр. 387), где живёт **свой** `OrthancDicomWebClient`, которому `cancel_inflight()` не вызывается: его внутренний `_cancel_event` не взводится.

Последствия:
- активный WADO-запрос не прерывается и продолжается до таймаута (до 60 с, `download_timeout` стр. 355);
- запрос может завершиться после `clear_session()` при отмене и **пересоздать каталог сессии** (`save_instance`), оставив осиротевшие файлы;
- C-MOVE вообще не проверяет `is_cancelled` между статусами (`dimse_client.c_move_instances/c_move_series`) — отмена ждёт завершения/ошибки ассоциации (до `network_timeout`).

**Предложение**: передать единый `cancel_event`/колбэк в retrieve-service и прокидывать его в `OrthancDicomWebClient` (вызывать `cancel_inflight()`), а в C-MOVE добавить проверку отмены в цикле статусов (и прерывание по таймеру диалога — уже есть).

---

### 🟠 M4. Селектор источника в диалоге и плашка «Скачивание через DIMSE (C-GET)» не соответствуют реальному пути скачивания

`_on_source_changed` (стр. 368) меняет только `query_source` (поиск). Скачивание же управляется отдельной настройкой `settings.retrieval_source` (`server_client_factory.make_dicom_retrieve_service`), и переключение комбобокса на «DIMSE» на него **не влияет**:

- `orthanc.dimse_info_banner` = «Скачивание через DIMSE (C-GET)» показывается всегда при выборе DIMSE, даже когда `retrieval_source='wado'/'auto'` (и WADO доступен) — фактически скачивание пойдёт по WADO;
- при выборе DIMSE, когда DIMSE в настройках выключен (`dimse_enabled=False`), `DicomQueryService` молча вернёт `[]` (см. M1) — без какого-либо предупреждения, что C-FIND недоступен.

**Предложение**: при выборе источника в диалоге переключать и источник скачивания (хотя бы показывать фактический), проверять доступность DIMSE (`dimse_enabled`) и выдавать внятное сообщение вместо пустого списка.

---

### 🟡 L1. Косметика: строка статуса «Ошибка в серии {uid}» (литерал)

`_on_single_study_failed` (стр. 848) вызывает:

```python
tr("orthanc.series_error_status", current=..., total=..., message=message)
```

а шаблон (`ru`/`en`) — `Ошибка в серии {uid}` / `Error in series {uid}`: аргумент `uid` не передан → `tr()` ловит `KeyError` и возвращает текст с **литералом `{uid}`**. Существующий ключ `orthanc.series_error` (`Ошибка [{current}/{total}]: {message}`) нигде не используется — вероятно, перепутаны ключи. Также `_on_single_study_failed` инкрементит `_completed_downloads`, из-за чего прогресс показывает «завершено» для упавших исследований.

---

### 🟡 L2. Скрытые фильтром исследования с отмеченными сериями попадают в загрузку

`_collect_all_checked_series` (стр. 554) обходит все top-level итемы, включая `setHidden(True)` из-за фильтра дат (`_filter_studies_by_date`). Если пользователь отметил серии, затем выбрал фильтр «1 день» (скрывший старое исследование), кнопка «Загрузить» скачает и скрытое. Проверенные серии скрытых итемов невозможно и снять (они не видны).

**Предложение**: пропускать `item.isHidden()` в `_collect_all_checked_series` (и, опционально, снимать отметки при скрытии).

---

### 🟡 L3. Настройки сервера: краш на нечисловом порту и потеря `query_source` при сохранении

- `ServerSettingsForm.settings()` (стр. 211, 221): `int(...)` без валидации — нечисловое значение в поле порта (DIMSE/SCP) роняет `_on_accept` (ValueError), диалог не сохраняет настройки и не объясняет причину.
- В форме **нет поля `query_source`**, а `settings()` конструирует `ServerSettings` с дефолтом `query_source="dicomweb"`. Любое сохранение настроек сервера (например, смена пароля) **молча сбрасывает ранее выбранный в диалоге загрузки источник DIMSE/Auto на DICOMweb**.
- `network_timeout` в форме тоже не представлен → при сохранении всегда пишется дефолт 30.0 (терпимо, но стоит знать).

**Предложение**: валидация портов с понятным сообщением; добавить `query_source` в форму или читать текущее сохранённое значение при сборке `settings()`.

---

### 🟡 L4. Тройное дублирование клиентов в `main_window._open_orthanc_dialog`

Создаются три независимых `OrthancDicomWebClient` из одних настроек: (1) `client` для диалога — при наличии `query_service` фактически не используется (кроме закрытия через `_release_client`); (2) клиент внутри `DicomQueryService`; (3) клиент внутри retrieve-service. `_release_client` закрывает только первый; остальные живут до GC. При долгоживущем диалоге это 2–3 пула соединений вместо одного.

**Предложение**: сделать `make_dicom_query_service`/`make_dicom_retrieve_service` с приёмом готового клиента (внедрение одного экземпляра) или добавить `close()` в `DicomQueryService`.

---

### 🟡 L5. «WADO-RS» на самом деле Orthanc REST

`WadoRetrieveAdapter` вызывает `OrthancDicomWebClient.download_instance`, который ходит в **Orthanc REST** (`POST /tools/lookup` → `GET /instances/{id}/file`), а не в стандартный WADO-RS (`/studies/{s}/series/{se}/instances/{i}?accept=application/dicom`). Для Orthanc это нормально (и надёжнее), но название вводит в заблуждение, а портируемость на generic DICOMweb-сервер (DCM4CHEE, dcm4chee, Conquest, Weasis-style) отсутствует. Плюс: `parse_series` делает `int(c)` без try — нестандартное значение `NumberOfSeriesRelatedInstances` уронит весь парсинг серий.

**Предложение**: переименовать в «Orthanc REST (WADO)» в UI/комментариях либо добавить настоящий WADO-RS fallback; обезопасить `int()`.

---

## Сводка

| # | Серьёзность | Суть | Файл:строка |
|---|---|---|---|
| H1 | 🔴 высокая | Синхронный ping в конструкторе диалога → фриз GUI до 30 с | `orthanc_study_dialog.py:140`, `dicom_retrieve_service.py:208` |
| H2 | 🔴 высокая | Частичный сбой → очистка всей сессии (потеря успешных) + «мёртвые» pre-scanned studies в следующем запуске | `orthanc_study_dialog.py:640-660, 771-778, 879-901`, `_on_load:572` |
| M1 | 🟠 средняя | Ошибки списка исследований молча → пустой список (401/таймаут/нет сети не видны) | `dicom_query_service.py:100`, `dimse_client.py:215`, `orthanc_study_dialog.py:78` |
| M2 | 🟠 средняя | «Auto» скачивания = разовая привязка по ping корня; реального fallback нет | `dicom_retrieve_service.py:233-268, 175` |
| M3 | 🟠 средняя | Отмена не прерывает запросы retrieve-service / C-MOVE; возможен пересозданный каталог после очистки | `orthanc_download_worker.py:104-120, 387`, `dimse_client.py:300+` |
| M4 | 🟠 средняя | Плашка «DIMSE C-GET» и селектор источника не влияют на скачивание | `orthanc_study_dialog.py:368-386` |
| L1 | 🟡 низкая | Литерал `{uid}` в статусе ошибки серии; не тот i18n-ключ | `orthanc_study_dialog.py:848-862` |
| L2 | 🟡 низкая | Скрытые фильтром исследования с отметками скачиваются | `orthanc_study_dialog.py:554-570` |
| L3 | 🟡 низкая | Краш на нечисловом порту; сброс `query_source` при сохранении настроек | `server_settings_dialog.py:198-221` |
| L4 | 🟡 низкая | Тройное дублирование HTTP-клиентов | `main_window.py:1106-1112` |
| L5 | 🟡 низкая | «WADO-RS» = Orthanc REST; хрупкий `int()` в парсере | `orthanc_client.py:205+`, `orthanc_dicom_json.py:100` |

Рекомендуемый порядок: **H1, H2** — перед релизом; затем **M1–M3** (восприятие ошибок, отмена и реальный fallback протоколов); M4/L1–L5 — по мере возможностей.

---

## Статус исправлений (2026-09-05)

Внесено на ветке `arena/01a06e35-sonoforge` по приоритету:

| # | Статус | Что сделано | Файлы |
|---|---|---|---|
| H1 | ✅ | Убран синхронный ping при создании retrieve-service: `make_retrieve_service` больше не делает сетевых вызовов, «auto» разрешается в момент скачивания | `dicom_retrieve_service.py`, `server_client_factory.py` |
| H2 | ✅ | Частичный сбой больше не стирает сессию: успешные исследования сохраняются и открываются (`_on_partial_done`); `_downloaded_studies` сбрасывается перед каждой новой загрузкой; «скачать на диск» копирует успешно скачанные | `orthanc_study_dialog.py`, i18n `ru/en` |
| M1 | ✅ | Ошибки уровня «список исследований» больше не маскируются под пустой список: явные режимы пробрасывают ошибку, AUTO пробрасывает последнюю при полном отказе; DIMSE C-FIND при отказе ассоциации/обрыве поднимает `DimseAssociationError`; диалог показывает итем/статус с текстом ошибки (`orthanc.find_error`) | `dicom_query_service.py`, `dimse_client.py`, `orthanc_study_dialog.py` |
| M2 | ✅ | Реальный fallback «auto» на каждый запрос (wado → dimse → cmove) вместо разовой привязки по ping; явный источник остаётся строгим | `dicom_retrieve_service.py` |
| M3 | ⚠️ | Отмена через retrieve-service: `worker.cancel()` вызывает `cancel_inflight()` (закрывает HTTP-сокеты), C-MOVE/C-GET проверяют `is_cancelled` в цикле статусов; сессия очищается только после `join` пула потоков (нет гонки «очистка ↔ докачка»). Остаточный риск: блокирующий DIMSE-вызов ждёт до `network_timeout`, если сервер не шлёт статусы | `orthanc_download_worker.py`, `dimse_client.py`, `dicom_retrieve_service.py` |
| M4 | ⚠️ | Плашка при выборе DIMSE показывает фактический источник скачивания (из `retrieval_source`) и текст «поиск через C-FIND»; при выключенном DIMSE поиск не стартует и показывает `orthanc.dimse_disabled`. Полной связки «выбор в диалоге ⇒ источник скачивания» не делал — источник остаётся настройкой | `orthanc_study_dialog.py`, i18n |
| L1 | ✅ | Правильный i18n-ключ/аргументы в статусе ошибки серии (`orthanc.series_error`) | `orthanc_study_dialog.py` |
| L2 | ✅ | Скрытые фильтром дат исследования исключены из сбора отмеченных серий | `orthanc_study_dialog.py` |
| L3 | ✅ | Сохранение настроек не сбрасывает `query_source`/`network_timeout`; валидация портов с понятным сообщением | `server_settings_dialog.py`, i18n |
| L5 | ⚠️ | Обезопасен `int()` парсера серий (`_as_int`). Переименование «WADO-RS»→«Orthanc REST» не делал (безопасно, но требует правок UI/локалей) | `orthanc_dicom_json.py` |
| L4 | ⏳ | Не делал (тройной клиент в `main_window`): требует рефакторинга фабрик, вне рамок этого прохода | — |

Проверка: не-GUI unit-наборы (`test_dicom_retrieve_service*`, `test_dicom_query_service*`, `test_dimse_client*`, `test_orthanc_client*`, `test_orthanc_download_worker`, `test_p4_skip_scan_worker`, `test_server_settings` и др.) — зелёные. GUI-тесты диалога в песочнице запустить нельзя (нет системных `libGL`/`libEGL`), нужен прогон CI на GUI-маркерах.
