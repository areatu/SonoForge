# DICOMweb Orthanc — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Загрузка выбранных DICOM-серий с Orthanc (QIDO-RS + WADO-RS) в сессионный локальный кэш и открытие в существующем viewer через `open_folder()`.

**Architecture:** `OrthancDicomWebClient` (httpx) + парсер `application/dicom+json` → `OrthancSessionCache` (temp session dir) → `OrthancDownloadWorker` (QThreadPool) → `OrthancStudyDialog` → `AppController.open_folder(study_path)`. Дома: `FakeDicomWebClient` + JSON/DICOM фикстуры.

**Tech Stack:** Python 3.10+, PySide6, httpx≥0.27, pydicom (existing), QSettings

**Spec:** [`docs/superpowers/specs/2026-06-23-dicomweb-orthanc-design.md`](../specs/2026-06-23-dicomweb-orthanc-design.md)

---

## File map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `src/echo_personal_tool/domain/models/orthanc.py` | `StudyInfo`, `SeriesInfo`, `InstanceInfo` DTO |
| Create | `src/echo_personal_tool/domain/ports/dicom_web.py` | `DicomWebClient` Protocol |
| Create | `src/echo_personal_tool/infrastructure/orthanc_dicom_json.py` | Parse DICOMweb JSON tags |
| Create | `src/echo_personal_tool/infrastructure/orthanc_client.py` | Live httpx client |
| Create | `src/echo_personal_tool/infrastructure/orthanc_cache.py` | Session cache dirs |
| Create | `src/echo_personal_tool/infrastructure/fake_dicom_web_client.py` | Mock for offline dev |
| Create | `src/echo_personal_tool/application/workers/orthanc_download_worker.py` | Download worker |
| Create | `src/echo_personal_tool/presentation/orthanc_study_dialog.py` | Browse + download UI |
| Create | `src/echo_personal_tool/presentation/server_settings_dialog.py` | URL/login/password/mock |
| Create | `tests/fixtures/orthanc/studies.json` | Recorded QIDO studies (minimal) |
| Create | `tests/fixtures/orthanc/series.json` | Recorded series for test study |
| Create | `tests/fixtures/orthanc/instances.json` | Recorded instances |
| Create | `tests/unit/test_orthanc_dicom_json.py` | Parser tests |
| Create | `tests/unit/test_orthanc_cache.py` | Cache tests |
| Create | `tests/unit/test_orthanc_download_worker.py` | Worker tests |
| Create | `tests/unit/test_fake_dicom_web_client.py` | Mock client tests |
| Modify | `pyproject.toml` | Add `httpx>=0.27` |
| Modify | `src/echo_personal_tool/presentation/system_bar.py` | Button + signal |
| Modify | `src/echo_personal_tool/presentation/main_window.py` | Wire dialog, cache lifecycle |
| Modify | `src/echo_personal_tool/presentation/ase_reference_dialog.py` | Reuse `_SETTINGS_ORG` or extract `settings_keys.py` |

---

### Task 1: DICOMweb JSON parser

**Files:**
- Create: `src/echo_personal_tool/infrastructure/orthanc_dicom_json.py`
- Create: `tests/unit/test_orthanc_dicom_json.py`
- Create: `tests/fixtures/orthanc/studies.json`

- [ ] **Step 1: Add minimal fixture**

`tests/fixtures/orthanc/studies.json` — один study из orthanc_analysis (UID `1.2.410.200001...448.1`), поля PatientName, StudyDate, StudyDescription, StudyInstanceUID.

- [ ] **Step 2: Write failing tests**

```python
# tests/unit/test_orthanc_dicom_json.py
from echo_personal_tool.infrastructure.orthanc_dicom_json import (
    parse_studies,
    tag_value,
)


def test_tag_value_reads_pn_and_uid():
    item = {"00100010": {"vr": "PN", "Value": ["IVANOV^IVAN"]}}
    assert tag_value(item, "00100010") == "IVANOV^IVAN"


def test_parse_studies_from_fixture():
    raw = Path("tests/fixtures/orthanc/studies.json").read_text()
    studies = parse_studies(json.loads(raw))
    assert len(studies) >= 1
    assert studies[0].study_uid.startswith("1.2.")
```

- [ ] **Step 3: Implement parser**

```python
def tag_value(item: dict, tag: str, default: str = "") -> str:
    node = item.get(tag) or {}
    values = node.get("Value") or []
    if not values:
        return default
    first = values[0]
    if isinstance(first, dict):
        return str(first.get("Alphabetic", default))
    return str(first)


def parse_studies(payload: list[dict]) -> list[StudyInfo]: ...
def parse_series(payload: list[dict]) -> list[SeriesInfo]: ...
def parse_instances(payload: list[dict]) -> list[InstanceInfo]: ...
```

- [ ] **Step 4: Run tests**

`pytest tests/unit/test_orthanc_dicom_json.py -q`

- [ ] **Step 5: Commit** `feat: add DICOMweb JSON parser for Orthanc QIDO responses`

---

### Task 2: DTO + Protocol

**Files:**
- Create: `src/echo_personal_tool/domain/models/orthanc.py`
- Create: `src/echo_personal_tool/domain/ports/dicom_web.py`

- [ ] **Step 1: Add dataclasses**

```python
@dataclass(frozen=True)
class StudyInfo:
    study_uid: str
    patient_name: str
    patient_id: str
    study_date: str
    study_description: str
    series_count: int | None = None


@dataclass(frozen=True)
class SeriesInfo:
    series_uid: str
    study_uid: str
    modality: str
    description: str
    instance_count: int | None = None


@dataclass(frozen=True)
class InstanceInfo:
    sop_instance_uid: str
    series_uid: str
    study_uid: str
```

- [ ] **Step 2: Protocol**

```python
class DicomWebClient(Protocol):
    def ping(self) -> bool: ...
    def query_studies(self, patient_name: str | None = None) -> list[StudyInfo]: ...
    def query_series(self, study_uid: str) -> list[SeriesInfo]: ...
    def query_instances(self, study_uid: str, series_uid: str) -> list[InstanceInfo]: ...
    def download_instance(self, study_uid: str, series_uid: str, instance_uid: str) -> bytes: ...
```

- [ ] **Step 3: Export from `domain/models/__init__.py` if needed by UI**

- [ ] **Step 4: Commit** `feat: add Orthanc DICOMweb domain DTOs and port`

---

### Task 3: OrthancSessionCache

**Files:**
- Create: `src/echo_personal_tool/infrastructure/orthanc_cache.py`
- Create: `tests/unit/test_orthanc_cache.py`

- [ ] **Step 1: Failing test**

```python
def test_session_cache_writes_instance(tmp_path):
    cache = OrthancSessionCache(tmp_path)
    session = cache.create_session()
    path = cache.save_instance(session, "1.2.study", "1.2.series", "1.2.1", b"DICM")
    assert path.exists()
    assert cache.study_path(session, "1.2.study").is_dir()
```

- [ ] **Step 2: Implement**

```python
class OrthancSessionCache:
    def __init__(self, root: Path): ...
    def create_session(self) -> str: ...  # returns session_id
    def save_instance(self, session_id, study_uid, series_uid, sop_uid, data: bytes) -> Path: ...
    def study_path(self, session_id: str, study_uid: str) -> Path: ...
    def clear_session(self, session_id: str) -> None: ...
    def clear_all(self) -> None: ...
```

Path layout: `{root}/session-{uuid}/{study_uid}/{series_uid}/{sop_uid}.dcm`

- [ ] **Step 3: Run** `pytest tests/unit/test_orthanc_cache.py -q`

- [ ] **Step 4: Commit** `feat: add Orthanc session cache for downloaded DICOM`

---

### Task 4: OrthancDicomWebClient (httpx)

**Files:**
- Create: `src/echo_personal_tool/infrastructure/orthanc_client.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Add dependency**

```toml
"httpx>=0.27",
```

- [ ] **Step 2: Implement client**

```python
class OrthancDicomWebClient:
    def __init__(self, base_url: str, username: str, password: str, timeout: float = 30.0):
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            auth=(username, password),
            timeout=timeout,
        )

    def ping(self) -> bool:
        try:
            r = self._client.get("/system")
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    def query_studies(self, patient_name: str | None = None) -> list[StudyInfo]:
        params = {}
        if patient_name:
            params["PatientName"] = f"*{patient_name}*"
        r = self._client.get(
            "/dicom-web/studies",
            params=params,
            headers={"Accept": "application/dicom+json"},
        )
        r.raise_for_status()
        return parse_studies(r.json())

    # ... series, instances, download_instance similarly
```

WADO download: `Accept: application/dicom` → `response.content`

- [ ] **Step 3: Unit test with `httpx.MockTransport`** (optional Task 4b) or defer to integration

- [ ] **Step 4: Commit** `feat: add Orthanc DICOMweb httpx client`

---

### Task 5: FakeDicomWebClient (offline)

**Files:**
- Create: `src/echo_personal_tool/infrastructure/fake_dicom_web_client.py`
- Create: `tests/fixtures/orthanc/series.json`, `instances.json`
- Create: `tests/unit/test_fake_dicom_web_client.py`

- [ ] **Step 1: Copy one synthetic DICOM** from `tests/fixtures/generate_synthetic_dicom.py` output into `tests/fixtures/orthanc/sample.dcm` (or generate in conftest)

- [ ] **Step 2: Implement FakeDicomWebClient**

- Reads JSON fixtures for QIDO
- `download_instance` returns `sample.dcm` bytes (same file for all instances in mock — OK for UI dev)
- `ping()` always True

- [ ] **Step 3: Tests** `pytest tests/unit/test_fake_dicom_web_client.py -q`

- [ ] **Step 4: Commit** `feat: add fake DICOMweb client for offline Orthanc dev`

---

### Task 6: Server settings

**Files:**
- Create: `src/echo_personal_tool/infrastructure/server_settings.py`
- Create: `src/echo_personal_tool/presentation/server_settings_dialog.py`

- [ ] **Step 1: QSettings wrapper**

```python
@dataclass
class ServerSettings:
    url: str
    username: str
    password: str
    use_mock: bool


def load_server_settings() -> ServerSettings: ...
def save_server_settings(settings: ServerSettings) -> None: ...
```

Keys: `server/url`, `server/username`, `server/password`, `server/use_mock`

- [ ] **Step 2: Dialog** — форма + checkbox «Mock (без сервера)»

- [ ] **Step 3: Wire into `MainWindow._show_settings_menu`** — пункт «Сервер…»

- [ ] **Step 4: Commit** `feat: add Orthanc server settings dialog`

---

### Task 7: OrthancDownloadWorker

**Files:**
- Create: `src/echo_personal_tool/application/workers/orthanc_download_worker.py`
- Create: `tests/unit/test_orthanc_download_worker.py`

- [ ] **Step 1: Mirror ScanWorker pattern** (QRunnable + QObject signals)

```python
class OrthancDownloadSignals(QObject):
    progress = Signal(str, int, int)  # series_uid, current, total
    series_done = Signal(str, str)
    done = Signal(str, str)  # session_id, study_uid
    failed = Signal(str, str)


class OrthancDownloadWorker(QRunnable):
    def __init__(
        self,
        client: DicomWebClient,
        cache: OrthancSessionCache,
        session_id: str,
        study_uid: str,
        series_uids: list[str],
    ): ...
```

- [ ] **Step 2: Test with FakeClient + tmp cache**

- [ ] **Step 3: Commit** `feat: add Orthanc download worker`

---

### Task 8: OrthancStudyDialog

**Files:**
- Create: `src/echo_personal_tool/presentation/orthanc_study_dialog.py`

- [ ] **Step 1: Layout** — search line, QTreeWidget (study → series checkboxes), status, progress bar, buttons

- [ ] **Step 2: Lazy load** — expand study → `query_series` in QThreadPool or sync with wait cursor for v1

- [ ] **Step 3: On Load** — start worker; on `done` emit `download_finished(session_id, study_uid)`

- [ ] **Step 4: Manual test** with `use_mock=True`

- [ ] **Step 5: Commit** `feat: add Orthanc study browser dialog`

---

### Task 9: MainWindow integration

**Files:**
- Modify: `src/echo_personal_tool/presentation/system_bar.py`
- Modify: `src/echo_personal_tool/presentation/main_window.py`

- [ ] **Step 1: SystemBar** — `load_from_server_requested = Signal()`, button «Загрузить с сервера…»

- [ ] **Step 2: MainWindow**

```python
def _open_orthanc_dialog(self):
    settings = load_server_settings()
    client = FakeDicomWebClient(...) if settings.use_mock else OrthancDicomWebClient(...)
    dialog = OrthancStudyDialog(client, self._orthanc_cache, self)
    if dialog.exec() == Accepted:
        session_id, study_uid = dialog.result()
        path = self._orthanc_cache.study_path(session_id, study_uid)
        self._controller.open_folder(path)


def closeEvent(self, event):
    self._orthanc_cache.clear_all()
    super().closeEvent(event)
```

- [ ] **Step 3: Commit** `feat: wire Orthanc download into main window`

---

### Task 10: Documentation + ROADMAP

**Files:**
- Modify: `ROADMAP.md` (new item DICOMweb)
- Modify: `DICOM_parsing.md` (link to spec, status implemented)

- [ ] **Step 1: Update ROADMAP** — DICOMweb Orthanc [x] after complete

- [ ] **Step 2: Note in spec** — record workplace fixture capture checklist

- [ ] **Step 3: Commit** `docs: mark DICOMweb Orthanc integration`

---

## Spec coverage checklist

| Spec requirement | Task |
|------------------|------|
| QIDO-RS | Task 4 |
| WADO-RS | Task 4, 7 |
| Session cache + clear on exit | Task 3, 9 |
| Mock offline | Task 5 |
| Settings QSettings | Task 6 |
| open_folder integration | Task 9 |
| httpx dependency | Task 4 |
| Unit tests | Tasks 1, 3, 5, 7 |
| No STOW v1 | — |

---

## Workplace checklist (when server available)

```bash
# Save fixtures (replace UID as needed)
curl -u "user:pass" -H "Accept: application/dicom+json" \
  "http://192.168.1.111:8042/dicom-web/studies?limit=5" \
  > tests/fixtures/orthanc/studies.json

curl -u "user:pass" -H "Accept: application/dicom+json" \
  "http://192.168.1.111:8042/dicom-web/studies/{StudyUID}/series" \
  > tests/fixtures/orthanc/series.json
```

---

## Self-review

- No TBD placeholders in tasks above
- Type names consistent: `StudyInfo`, `DicomWebClient`, `OrthancSessionCache`
- v1 scope: download only, no STOW
