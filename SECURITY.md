# Security

## Temporary Files and PHI

All DICOM data (including PHI — Patient Name, Patient ID, Study UIDs) is processed
entirely in memory. The application does NOT create temporary files containing PHI.

- DICOM parsing uses `pydicom` with in-memory `BytesIO` buffers
- Frame decoding produces `numpy.ndarray` objects in RAM
- ONNX inference operates on in-memory tensors
- The only file-based artifacts are the model files (.onnx) and error logs (no PHI)

## DICOM File Validation

Files are validated before parsing: magic bytes check, size limits (500 MB max),
and minimum header size. See `infrastructure/dicom_validator.py`.

## Path Traversal Protection

DICOM UIDs are validated to contain only digits and dots (`^[0-9.]+$`). This
prevents path traversal attacks via crafted UIDs like `../../etc/passwd`.

- `validate_dicom_uid()` — validates UID format
- `safe_uid_path_component()` — raises `ValueError` on invalid UIDs
- All storage operations (Orthanc cache, image storage) use validated UIDs

Files:
- `infrastructure/dicom_uid_validator.py` — UID validation
- `infrastructure/orthanc_cache.py` — uses `safe_uid_path_component()`
- `constructor/storage/image_storage.py` — blocks `..`, `/`, `\` in filenames

## PHI Tag Filtering

DICOM tags containing Protected Health Information (PHI) can be filtered to prevent
leakage in logs, overlays, or UI. See `infrastructure/dicom_tag_inspector.py`.

Filtered tags:
- All tags in group `0x0010` (Patient Name, Patient ID, Birth Date, Age, etc.)
- `(0008,0080)` InstitutionName
- `(0008,0090)` ReferringPhysicianName
- `(0008,1050)` PerformingPhysicianName
- `(0008,1040)` InstitutionalDepartmentName

Usage: `read_all_dicom_tag_rows(path, filter_phi=True)` — replaces PHI values with `"***"`.

## TLS Encryption

DIMSE connections support TLS encryption. DICOMweb defaults to HTTPS.

- `ServerSettings.dimse_use_tls` — enable TLS for DIMSE (default: `False`)
- `ServerSettings.dimse_tls_verify` — verify server certificate (default: `True`)
- `ServerSettings.dimse_tls_ca_path` — CA certificate path
- `ServerSettings.dimse_tls_cert_path` — client certificate (optional)
- `ServerSettings.dimse_tls_key_path` — client private key (optional)

A warning is logged when `dimse_tls_verify=False` is used.

Files:
- `infrastructure/server_settings.py` — TLS settings
- `infrastructure/dimse_client.py` — TLS context creation

## Password Storage

Passwords are stored in the operating system's keychain (via `keyring` library),
NOT in QSettings or any text file.

- `save_server_settings()` stores password via `keyring.set_password()`
- `load_server_settings()` retrieves password via `keyring.get_password()`
- QSettings stores username, URL, auth mode — never passwords

## Model Integrity

ONNX models are SHA256-verified against `model_manifest.json` at load time.
A mismatch is logged as a warning but does not block loading (desktop deployment).

## Network Timeouts

All DICOMweb (WADO-RS/QIDO-RS) and DIMSE connections use configurable timeouts
(default 30s). See `ServerSettings.network_timeout`.

## Logging Sanitization

DICOM UIDs are truncated to 16 characters in log output. Patient names and IDs
are never written to log files.
