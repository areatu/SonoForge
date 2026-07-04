# DIMSE Phase 2 — C-GET, C-MOVE, DIMSE-only, TLS

**Дата:** 2026-07-04  
**Статус:** Approved (brainstorming)  
**Предшественник:** [2026-07-02-dimse-stow-rs-implementation.md](../plans/2026-07-02-dimse-stow-rs-implementation.md) (v1 в main)

---

## Цель

Расширить PACS-интеграцию за пределы гибрида «C-FIND + WADO-RS»:

1. **C-GET** — скачивание инстансов по DIMSE без HTTP.
2. **C-MOVE** — retrieval через **embedded Storage SCP** (порт 11112 только на время download).
3. **DIMSE-only** — работа без DICOMweb URL (каталог + download + upload через DIMSE).
4. **TLS** — защищённые DIMSE-ассоциации для hospital PACS.

---

## Scope v2

| Возможность | v2 | Вне scope |
|-------------|----|-----------|
| C-GET (IMAGE level) | ✓ | Patient Root (Study Root достаточно) |
| C-MOVE + embedded Storage SCP | ✓ | Persistent SCP daemon |
| `retrieval_source`: wado / dimse / auto | ✓ | |
| DIMSE-only (нет URL) | ✓ | DICOMDIR import |
| TLS client (verify + optional client cert) | ✓ | DIMSE SCP TLS (Phase 3) |
| Mock parity (`FakeDimseClient`) | ✓ | |

---

## Архитектура

```
OrthancStudyDialog
    └── DicomQueryService              # каталог (без изменений API)

OrthancDownloadWorker
    └── DicomRetrieveService           # NEW
            ├── resolve(source, settings) → adapter
            ├── WadoRetrieveAdapter      → DicomWebClient.download_instance
            ├── CGetRetrieveAdapter      → DimseClient.c_get_instance
            └── CMoveRetrieveAdapter     → DimseClient.c_move_series + EmbeddedStorageSCP

EmbeddedStorageSCP (context manager)
    start_server(("0.0.0.0", port), block=False)
    EVT_C_STORE → in-memory dict[sop_uid, bytes]
    shutdown() on exit
```

### Новые порты (`domain/ports.py`)

```python
class DimseClient(Protocol):
    ...
    def c_get_instance(self, study_uid: str, series_uid: str, instance_uid: str) -> bytes: ...

    def c_move_instances(
        self,
        study_uid: str,
        series_uid: str,
        instance_uids: list[str],
        *,
        move_destination_ae: str,
        scp_host: str,
        scp_port: int,
        received: dict[str, bytes],  # filled by EmbeddedStorageSCP
    ) -> CMoveResult: ...
```

```python
@dataclass(frozen=True)
class CMoveResult:
    completed: int
    failed: int
    warning: int
```

`DicomRetrieveService.retrieve_instance(study_uid, series_uid, instance_uid) -> bytes` — единая точка для worker.

---

## ServerSettings (новые поля)

```python
retrieval_source: str = "auto"       # wado | dimse | cmove | auto
dimse_retrieval_mode: str = "cget"     # cget | cmove — когда retrieval_source=dimse
dimse_use_tls: bool = False
dimse_tls_verify: bool = True
dimse_tls_ca_path: str = ""
dimse_tls_cert_path: str = ""          # optional client cert
dimse_tls_key_path: str = ""
dimse_scp_port: int = 11112
dimse_scp_host: str = "127.0.0.1"      # bind address; PACS must reach this IP
dimse_scp_ae_title: str = ""           # default: dimse_ae_title
```

**`retrieval_source` semantics:**

| Значение | Поведение |
|----------|-----------|
| `wado` | Только WADO-RS; ошибка если URL пуст |
| `dimse` | C-GET или C-MOVE по `dimse_retrieval_mode` |
| `cmove` | C-MOVE (embedded SCP) |
| `auto` | WADO если `url` настроен и ping OK; иначе C-GET |

---

## DIMSE-only режим

**Условие:** `dimse_enabled=True`, `url` пуст или `use_mock=True` с dimse mock.

- Убрать blocking warning «DIMSE needs WADO» в `orthanc_study_dialog` — заменить info: «Download via DIMSE (C-GET)».
- Upload: C-STORE (уже есть).
- Query: C-FIND (уже есть).
- Ping: C-ECHO (уже есть).
- STOW недоступен без URL — UI disable «Send to server» или force C-STORE only.

---

## C-GET (Phase 2.1)

### pynetdicom (Study Root)

- Presentation context: `StudyRootQueryRetrieveInformationModelGet`
- Для C-GET SCU: `add_requested_context(Get)` + `build_role(StorageSOP, scp_role=True)` для приёма sub-operations C-STORE на той же association **или** inline datasets в response stream.

**Рекомендуемый паттерн (getscu-style):**

```python
handlers = [(evt.EVT_C_STORE, handle_store)]  # accumulate bytes in dict
ae.add_requested_context(StudyRootQueryRetrieveInformationModelGet)
role = build_role(CTImageStorage, scp_role=True)  # + all storage contexts used
assoc = ae.associate(host, port, ext_neg=[role, ...], evt_handlers=handlers, tls_args=...)
ds = Dataset()
ds.QueryRetrieveLevel = "IMAGE"
ds.StudyInstanceUID = study_uid
ds.SeriesInstanceUID = series_uid
ds.SOPInstanceUID = instance_uid
for status, identifier in assoc.send_c_get(ds, StudyRootQueryRetrieveInformationModelGet):
    ...
```

- Возвращать `bytes` через `dataset.save_as(BytesIO(), enforce_file_format=True)`.
- Timeout: reuse `dimse` association timeouts (10s default).
- Cancel: propagate worker `_cancelled` → abort association.

### FakeDimseClient

- `c_get_instance` → read fixture `.dcm` by SOP UID from mock store.

---

## C-MOVE + Embedded Storage SCP (Phase 2.2)

**Решение (approved):** SCP слушает **только на время download**, default port **11112**.

### Lifecycle

```python
with EmbeddedStorageSCP(host, port, ae_title) as scp:
    scp.start()  # ae.start_server(..., block=False)
    client.c_move_series(..., move_destination_ae=ae_title, scp_host=host, scp_port=port)
    return scp.instances  # dict[sop_uid, bytes]
# scp.shutdown() always
```

### pynetdicom pattern

```python
ae = AE(ae_title=scp_ae_title)
ae.supported_contexts = StoragePresentationContexts
ae.add_requested_context(StudyRootQueryRetrieveInformationModelMove)
scp = ae.start_server((host, port), block=False, evt_handlers=[(evt.EVT_C_STORE, handle_store)])
assoc = ae.associate(pacs_host, pacs_port, tls_args=...)
responses = assoc.send_c_move(ds, scp_ae_title, StudyRootQueryRetrieveInformationModelMove)
scp.shutdown()
```

### Orthanc configuration

PACS должен знать Move Destination AE. Для local Orthanc — `DicomModalities` в `orthanc.json`:

```json
"ECHO2026": { "AET": "ECHO2026", "Host": "127.0.0.1", "Port": 11112 }
```

UI: подсказка в Server Settings если C-MOVE fails with «Unknown destination».

### Когда использовать C-MOVE vs C-GET

| | C-GET | C-MOVE |
|---|-------|--------|
| Orthanc | ✓ | ✓ (needs modality entry) |
| Firewall | same association | PACS → client inbound |
| Complexity | lower | SCP lifecycle |
| Default | **yes** | opt-in (`dimse_retrieval_mode=cmove`) |

Per-instance download в worker: для series batch можно один C-MOVE на SERIES level вместо N C-GET.

---

## TLS (Phase 2.3)

### SCU associate

```python
ssl_cx = ssl.create_default_context()
if ca_path:
    ssl_cx.load_verify_locations(cafile=ca_path)
ssl_cx.verify_mode = ssl.CERT_REQUIRED if verify else ssl.CERT_NONE
if cert_path and key_path:
    ssl_cx.load_cert_chain(certfile=cert_path, keyfile=key_path)
assoc = ae.associate(host, port, tls_args=(ssl_cx, host))
```

### UI (Server Settings → DIMSE section)

- Checkbox «Use TLS»
- File pickers: CA (optional), Client cert, Client key
- Checkbox «Verify server certificate»

### Testing

- Unit: mock `ssl.create_default_context`, assert `tls_args` passed
- Integration: `ECHO_ORTHANC_TLS=1` + local Orthanc with TLS (optional CI job)

---

## OrthancDownloadWorker refactor

Replace direct `client.download_instance(...)` with:

```python
retrieve = make_retrieve_service(settings, web_client, dimse_client)
data = retrieve.retrieve_instance(study_uid, series_uid, instance_uid)
```

Thread-local clients unchanged; `DicomRetrieveService` holds references.

**Series-level optimization:** if `retrieval_source=cmove`, one C-MOVE per series then read from SCP buffer (fewer round-trips).

---

## UI changes

| Место | Изменение |
|-------|-----------|
| Server Settings | Retrieval source combo; TLS fields; SCP port/host; C-GET/C-MOVE mode |
| Orthanc Study Dialog | DIMSE-only info banner (not error); disable WADO-only assumptions |
| README | C-MOVE Orthanc modality setup; TLS notes |

---

## Error handling

| Error | UX |
|-------|-----|
| C-GET timeout | series failed, retry single instance |
| C-MOVE unknown destination | dialog hint: add modality in Orthanc |
| SCP port in use | try ephemeral port + show port in error |
| TLS handshake fail | clear message + check CA |
| Partial C-MOVE | report completed/failed counts |

---

## Testing

### Unit

- `test_dicom_retrieve_service.py` — routing wado/dimse/auto
- `test_dimse_c_get.py` — identifier dataset, mock responses
- `test_embedded_storage_scp.py` — C-STORE handler accumulates bytes
- `test_fake_dimse_client.py` — extend c_get, c_move
- `FakeDimseClient` parity for offline dev

### Integration

```bash
# C-GET
ECHO_ORTHANC=1 ECHO_ORTHANC_DIMSE=1 ECHO_ORTHANC_RETRIEVAL=dimse pytest tests/integration/test_orthanc_live.py -k c_get

# C-MOVE (local Orthanc with modality configured)
ECHO_ORTHANC=1 ECHO_ORTHANC_DIMSE=1 ECHO_ORTHANC_RETRIEVAL=cmove pytest ...
```

---

## Порядок реализации

| # | Задача | Зависимости |
|---|--------|-------------|
| 1 | `RetrievalSource` enum + ServerSettings fields | — |
| 2 | `EmbeddedStorageSCP` + unit tests | — |
| 3 | `PynetdimseClient.c_get_instance` | 2 |
| 4 | `DicomRetrieveService` + WADO/C-GET adapters | 3 |
| 5 | Refactor `OrthancDownloadWorker` | 4 |
| 6 | DIMSE-only UI (remove WADO warning) | 5 |
| 7 | TLS in `_associate()` + settings UI | 3 |
| 8 | `c_move_series` + CMove adapter | 2, 3 |
| 9 | Integration tests + README | all |

---

## Отменённые связанные пункты

- C-STORE SCP как permanent service — не в v2
- DIMSE SCP TLS — Phase 3
- DICOMDIR — отдельная задача

---

## depth: implementation plan via `writing-plans` → `docs/superpowers/plans/2026-07-04-dimse-phase2-implementation.md`.
