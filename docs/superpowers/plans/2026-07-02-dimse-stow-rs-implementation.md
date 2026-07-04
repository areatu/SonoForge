# План: DIMSE + STOW-RS для ECHO2026

Дата: 2026-07-02  
Статус: **v1 implemented** (main) · **v2 spec:** [2026-07-04-dimse-phase2-design.md](../specs/2026-07-04-dimse-phase2-design.md)  
Связанные документы: [`2026-06-23-dicomweb-orthanc-design.md`](../specs/2026-06-23-dicomweb-orthanc-design.md)

## Мотивация

Приложение поддерживает только DICOMweb (QIDO-RS + WADO-RS) через Orthanc по HTTP. Этого недостаточно для полноценного DICOM-вьюера. Другие вьюеры (Horos, RadiAnt, Weasis) поддерживают DIMSE (C-ECHO, C-FIND, C-STORE, C-MOVE) для прямого взаимодействия с PACS, а также STOW-RS для загрузки.

---

## Scope v1 (зафиксировано)

| Возможность | v1 | Фаза 2 |
|-------------|----|--------|
| C-ECHO | ✓ | |
| C-FIND (Study / Series / **Instance**) | ✓ | |
| C-STORE (upload) | ✓ | |
| STOW-RS (upload) | ✓ | |
| **Гибридный retrieval**: C-FIND + WADO-RS download | ✓ | |
| Полностью DIMSE-only retrieval (C-GET / C-MOVE) | | ✓ |
| C-STORE SCP / C-MOVE SCP в приложении | | ✓ |
| DIMSE TLS | | ✓ (при необходимости для hospital PACS) |
| DICOMDIR / Media Storage | | отдельная задача |

**Ключевое решение v1:** DIMSE используется для **каталога** (поиск UID), скачивание инстансов — через существующий **WADO-RS** (`OrthancDicomWebClient.download_instance`), если настроен DICOMweb URL. Режим «только DIMSE без HTTP» в v1 **не поддерживается** — UI показывает предупреждение, если `dimse_enabled=True`, но DICOMweb URL пуст/недоступен.

---

## 1. Зависимость: pynetdicom

Добавить в `pyproject.toml`:

```toml
dependencies = [
    ...
    "pynetdicom>=2.0",
]
```

`pynetdicom` — реализация DICOM DIMSE на Python (C-ECHO, C-FIND, C-STORE, C-GET, SCP). Для desktop PACS-клиента включать в core dependencies (не optional extra).

---

## 2. Порты в `domain/ports.py`

### 2.1 `DimseClient` — DIMSE-native

Единое имя протокола во всём документе: **`DimseClient`** (реализация: `PynetdimseClient`, мок: `FakeDimseClient`).

```python
@dataclass(frozen=True)
class StowResult:
    """Результат STOW-RS или batch C-STORE."""
    success_count: int
    failed_uids: list[str]
    error_message: str = ""


class DimseClient(Protocol):
    """DIMSE-native DICOM communication (blocking — только из worker thread)."""

    def c_echo(self) -> bool:
        """C-ECHO — проверка соединения с DICOM-узлом."""

    def c_find_studies(
        self,
        *,
        patient_name: str | None = None,
        patient_id: str | None = None,
        study_date: str | None = None,
    ) -> list[StudyInfo]:
        """C-FIND, Study Root, уровень STUDY."""

    def c_find_series(self, study_uid: str) -> list[SeriesInfo]:
        """C-FIND, Study Root, уровень SERIES."""

    def c_find_instances(self, study_uid: str, series_uid: str) -> list[InstanceInfo]:
        """C-FIND, Study Root, уровень IMAGE — обязателен для download pipeline."""

    def c_store(self, dicom_bytes: bytes) -> bool:
        """C-STORE одного DICOM-объекта. False при non-Success status."""


class DicomUploadClient(Protocol):
    """Единый контракт upload (DIMSE или STOW-RS)."""

    def upload_instance(self, dicom_bytes: bytes) -> bool: ...


class DicomWebClient(Protocol):
    """Существующий протокол DICOMweb + STOW-RS + расширенные фильтры QIDO."""

    def ping(self) -> bool: ...

    def query_studies(
        self,
        *,
        patient_name: str | None = None,
        patient_id: str | None = None,
        study_date: str | None = None,
    ) -> list[StudyInfo]: ...

    def query_series(self, study_uid: str) -> list[SeriesInfo]: ...

    def query_instances(self, study_uid: str, series_uid: str) -> list[InstanceInfo]: ...

    def download_instance(
        self, study_uid: str, series_uid: str, instance_uid: str
    ) -> bytes: ...

    def stow_instances(self, dicom_files: list[bytes]) -> StowResult:
        """STOW-RS — загрузка одного или нескольких DICOM-объектов."""
```

`OrthancDicomWebClient` и `FakeDicomWebClient` получают расширенную сигнатуру `query_studies` (обратная совместимость: новые параметры optional).

`PynetdimseClient` реализует `DimseClient`; adapter `DimseUploadAdapter(DimseClient)` реализует `DicomUploadClient` через `c_store`.

---

## 3. Application layer: фасады (не размазывать логику по UI)

### 3.1 `application/dicom_query_service.py`

```python
class DicomQueryService:
    """Единая точка поиска для orthanc_study_dialog."""

    def __init__(
        self,
        web: DicomWebClient | None,
        dimse: DimseClient | None,
        *,
        source: QuerySource = QuerySource.AUTO,
    ): ...

    def query_studies(self, filters: StudyQueryFilters) -> list[StudyInfo]: ...
    def query_series(self, study_uid: str) -> list[SeriesInfo]: ...
    def query_instances(self, study_uid: str, series_uid: str) -> list[InstanceInfo]: ...
```

`QuerySource`: `DICOMWEB` | `DIMSE` | `AUTO`.

- **DICOMweb** — только `web.query_*`
- **DIMSE** — только `dimse.c_find_*`
- **Auto** — `web` first; при `HTTPError` / timeout / пустой конфиг → fallback `dimse` (если `dimse_enabled`)

Download **всегда** через `DicomWebClient.download_instance` в v1 (`OrthancDownloadWorker` без изменений контракта). Если WADO недоступен — ошибка с понятным сообщением, не silent fallback.

### 3.2 Фабрика клиентов

```python
# infrastructure/server_settings.py (или server_client_factory.py)

def make_dimse_client(settings: ServerSettings) -> DimseClient:
    if settings.use_mock:
        return FakeDimseClient()
    return PynetdimseClient.from_settings(settings)

def make_dicom_web_client(settings: ServerSettings) -> DicomWebClient:
    if settings.use_mock:
        return FakeDicomWebClient()
    return OrthancDicomWebClient.from_settings(settings)

def make_dicom_query_service(settings: ServerSettings, source: QuerySource) -> DicomQueryService:
    ...
```

`main_window.py` создаёт сервис, передаёт в `OrthancStudyDialog` — **не** `DicomWebClient | DimseClient` напрямую.

---

## 4. `infrastructure/dimse_client.py` — `PynetdimseClient`

Реализация `DimseClient` через `pynetdicom`.

### 4.1 Параметры конфигурации

| Поле | Тип | По умолчанию | Описание |
|------|-----|--------------|----------|
| `ae_title` | str | `ECHO2026` | AE Title клиента (Calling AE) |
| `called_ae` | str | `ORTHANC` | AE Title удалённого узла (Called AE) |
| `host` | str | `127.0.0.1` | Хост удалённого узла |
| `port` | int | `4242` | Порт удалённого узла |
| `timeout_s` | float | `10.0` | Таймаут ассоциации / DIMSE |

### 4.2 Presentation Contexts (обязательно явно)

При `AE.associate()` запрашивать как **SCU**:

| SOP Class | UID | Операция |
|-----------|-----|----------|
| Verification | `1.2.840.10008.1.1` | C-ECHO |
| Study Root Query/Retrieve FIND | `1.2.840.10008.1.2.2` + FIND | C-FIND |
| Storage SOP Classes | US, Enhanced US, SC, … | C-STORE |

Transfer syntax v1: **Implicit VR Little Endian** (`1.2.840.10008.1.2`) — совместим с Orthanc. Для hospital PACS — опциональный список storage classes в settings (фаза 2) или `AllStoragePresentationContexts` из pynetdicom с фильтром по модальности US.

Association reject → лог + `False` / пустой список / исключение `DimseAssociationError` (domain).

### 4.3 Методы

**`c_echo()`** — `AE → associate → send_c_echo → release`. Success = `0x0000`.

**`c_find_*`** — Study Root Model, уровни `STUDY` / `SERIES` / `IMAGE`. Wildcard `*` для PatientName как в QIDO. Итерация по pending responses до `0x0000` / `0xFF00`.

**`c_store()`** — `dcmread(BytesIO(dicom_bytes), force=True)` → `send_c_store`. Проверка `Status.Success`.

### 4.4 Маппинг C-FIND → domain models

Отдельный модуль `infrastructure/dimse_find_mapper.py`:

| DICOM tag | `StudyInfo` / `SeriesInfo` / `InstanceInfo` |
|-----------|---------------------------------------------|
| `(0020,000D)` | `study_uid` |
| `(0010,0010)` | `patient_name` (PN formatting) |
| `(0010,0020)` | `patient_id` |
| `(0008,0020)` | `study_date` |
| `(0008,1030)` | `study_description` |
| `(0020,000E)` | `series_uid` |
| `(0008,0060)` | `modality` |
| `(0008,103E)` | `description` (series) |
| `(0008,0018)` | `sop_instance_uid` |

Пустые / missing tags → `""` или `None` для counts (C-FIND не всегда отдаёт `NumberOfStudyRelatedSeries`).

### 4.5 Thread safety

- Каждый публичный метод — **новая ассоциация** (проще, без shared state).
- Batch C-STORE в upload worker: **одна ассоциация на batch** + `threading.Lock` на экземпляре клиента.
- **Запрещено** вызывать из GUI thread — только `QThreadPool` / `QRunnable` (как `OrthancDownloadWorker`).

---

## 5. Расширение `infrastructure/server_settings.py`

### Новые поля `ServerSettings`

```python
@dataclass
class ServerSettings:
    # ... существующие поля (url, username, use_mock, ...)

    # DIMSE
    dimse_enabled: bool = False
    dimse_ae_title: str = "ECHO2026"
    dimse_called_ae: str = "ORTHANC"
    dimse_host: str = "127.0.0.1"
    dimse_port: int = 4242

    # STOW-RS override (не отдельный path — полный dicom-web root)
    stow_dicom_web_url: str = ""  # пусто → derive из url через split_orthanc_urls()
```

### QSettings-ключи

```
dimse_enabled, dimse_ae_title, dimse_called_ae, dimse_host, dimse_port
stow_dicom_web_url
query_source   # "dicomweb" | "dimse" | "auto" — последний выбор в диалоге поиска
```

---

## 6. STOW-RS: расширение `infrastructure/orthanc_client.py`

### 6.1 Endpoint

POST `{dicom_web_root}/studies` — тот же `_client`, что для QIDO/WADO (`split_orthanc_urls`).

Если `stow_dicom_web_url` задан — использовать его как dicom-web root для STOW (отдельный `httpx.Client` или переиспользовать base URL).

### 6.2 Multipart body (DICOMweb Part 18)

```python
def _build_stow_multipart_body(boundary: str, dicom_files: list[bytes]) -> bytes:
    """multipart/related; type=application/dicom; boundary=...

    --{boundary}\r\n
    Content-Type: application/dicom\r\n
    \r\n
    {raw dicom bytes}\r\n
    --{boundary}--\r\n
    """
```

### 6.3 Response handling

Orthanc возвращает **200** + `application/dicom+json` (массив результатов по instance).

```python
def stow_instances(self, dicom_files: list[bytes]) -> StowResult:
    ...
    if r.status_code not in (200, 201):
        return StowResult(0, [], f"HTTP {r.status_code}")
    # parse JSON: extract failed SOP Instance UIDs from 00081198 sequences
    return StowResult(success_count=..., failed_uids=..., error_message=...)
```

`success_count + len(failed_uids)` должно равняться числу отправленных файлов. Partial failure — не считать полным успехом; UI показывает список failed UIDs.

---

## 7. Мок: `infrastructure/fake_dimse_client.py`

```python
class FakeDimseClient:
    """Мок DIMSE для офлайн-разработки (те же данные, что FakeDicomWebClient)."""

    def c_echo(self) -> bool: ...
    def c_find_studies(self, **filters) -> list[StudyInfo]: ...
    def c_find_series(self, study_uid: str) -> list[SeriesInfo]: ...
    def c_find_instances(self, study_uid: str, series_uid: str) -> list[InstanceInfo]: ...
    def c_store(self, dicom_bytes: bytes) -> bool: ...
```

Общие mock-данные вынести в `tests/fixtures/orthanc_mock_data.py` или shared helper между fake clients.

---

## 8. UI: Настройки DIMSE-узла

В `server_settings_dialog.py` — секция после DICOMweb:

```
┌─ DIMSE (Native DICOM) ─────────────────────────┐
│ ☐ Enable DIMSE connection                       │
│ AE Title:  [ECHO2026      ]  Called AE: [ORTHANC]│
│ Host:      [127.0.0.1     ]  Port: [4242]       │
│                              [Test C-ECHO Ping] │
└──────────────────────────────────────────────────┘
```

- Поля активны только при `dimse_enabled=True`.
- **Test C-ECHO Ping** — `DimseEchoWorker` (QRunnable), результат в status bar / QMessageBox. **Не блокировать GUI thread.**

---

## 9. UI: Выбор источника в диалоге поиска

В `orthanc_study_dialog.py`:

```
Источник: [DICOMweb | DIMSE (C-FIND) | Auto]
```

Диалог получает `DicomQueryService`, не клиенты напрямую.

| Режим | Поиск | Download (v1) |
|-------|-------|---------------|
| DICOMweb | QIDO-RS | WADO-RS |
| DIMSE | C-FIND | WADO-RS (требует настроенный DICOMweb URL) |
| Auto | QIDO → fallback C-FIND | WADO-RS |

Если DIMSE выбран, но DICOMweb URL недоступен — banner: «Скачивание возможно только при настроенном DICOMweb (WADO-RS). C-GET — в следующей версии.»

Смена источника не сбрасывает результаты (повторный Search — по новому источнику).

---

## 10. UI: Загрузка DICOM на сервер

Кнопка: `[↥ Send to Server...]` (system bar или контекстное меню галереи).

1. Выбор локальных исследований / файлов
2. Диалог: целевой сервер + протокол `DIMSE (C-STORE)` | `DICOMweb (STOW-RS)`
3. Сбор `.dcm` bytes из кэша / пути на диске
4. `DicomUploadWorker` + `QProgressDialog`
5. Итог: `StowResult` / per-file C-STORE status

### Worker: `application/workers/dicom_upload_worker.py`

```python
class DicomUploadWorker(QRunnable):
    def __init__(self, files: list[bytes], uploader: DicomUploadClient): ...
    # signals: progress(int, int), finished(StowResult), failed(str)
```

- STOW: один POST на batch (или chunks по N файлов, если body > лимит сервера)
- C-STORE: последовательно в одной ассоциации, progress после каждого файла
- Отмена: флаг + прерывание между файлами

---

## 11. Тестирование

### Unit-тесты

| Файл | Что тестирует |
|------|---------------|
| `tests/unit/test_dimse_client.py` | C-ECHO, C-FIND (study/series/instance), C-STORE на in-process SCP (`pynetdicom` test AE) |
| `tests/unit/test_dimse_find_mapper.py` | Dataset → `StudyInfo` / `SeriesInfo` / `InstanceInfo` |
| `tests/unit/test_dicom_query_service.py` | Auto fallback, DIMSE-only search, WADO-required guard |
| `tests/unit/test_server_settings.py` | DIMSE + `stow_dicom_web_url` + `query_source` persist |
| `tests/unit/test_orthanc_client_stow.py` | multipart body format, parse 200 JSON, partial failure |
| `tests/unit/test_dicom_upload_worker.py` | progress, cancel, STOW vs C-STORE adapter |
| `tests/unit/test_fake_dimse_client.py` | parity с `FakeDicomWebClient` данными |

### Интеграционные (manual / CI optional)

- C-ECHO + C-FIND на Orthanc `:4242`
- STOW-RS на Orthanc `:8042/dicom-web/studies`
- Маркер pytest: `@pytest.mark.integration` + env `ECHO_ORTHANC=1`

---

## 12. Порядок реализации

| Этап | Описание | Зависимости |
|------|----------|-------------|
| **1** | `pynetdicom` + `ServerSettings` + `StowResult` | — |
| **2** | `PynetdimseClient` + `dimse_find_mapper` + `FakeDimseClient` | 1 |
| **3** | `DicomQueryService` + расширение `query_studies` в web client | 2 |
| **4** | STOW-RS в `OrthancDicomWebClient` + `DicomUploadClient` adapters | 1 |
| **5** | `DicomUploadWorker` + Send to Server UI | 4 |
| **6** | UI: DIMSE settings + C-ECHO worker | 2 |
| **7** | UI: источник поиска в `orthanc_study_dialog` | 3, 6 |
| **8** | Unit + integration tests | всё |

Этап 7 **после** `DicomQueryService` — не внедрять переключатель источника до готовности фасада.

---

## 13. Архитектурные заметки

- **Клиент-only v1**: без C-STORE SCP и C-MOVE SCP в приложении.
- **C-GET / C-MOVE (фаза 2)**: потребуют SCP для приёма или filesystem staging; отдельный design doc.
- **DICOMDIR**: не в scope; локальный scanner работает по файлам.
- **Thread safety**: DIMSE и httpx — только worker threads; GUI через signals.
- **Mock parity**: `use_mock=True` → `FakeDimseClient` + `FakeDicomWebClient`; upload/search работают offline.
- **Orthanc defaults**: HTTP `8042/dicom-web`, DIMSE `4242`, Called AE `ORTHANC` — документировать в README.
- **TLS**: v1 — plain TCP DIMSE; v2 — `dimse_use_tls` (spec 2026-07-04).

---

## 14. Phase 2 (отдельная спека)

C-GET, C-MOVE (embedded Storage SCP on :11112 during download), DIMSE-only retrieval, TLS.

**Спека:** [`2026-07-04-dimse-phase2-design.md`](../specs/2026-07-04-dimse-phase2-design.md)
