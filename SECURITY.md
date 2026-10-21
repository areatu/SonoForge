# Security and Managed Persistence

This document describes the current SonoForge desktop application's behavior. It is an implementation inventory, not a security certification, regulatory submission, or claim that a particular clinic's deployment complies with a law or policy. SonoForge does not provide an in-app multi-user login or application-level encryption for cached DICOM or user exports.

For the regulatory mapping and shared-responsibility notes, see [`docs/security/data-inventory.md`](docs/security/data-inventory.md). For release artifact authenticity — what is signed, what is attested, and how to verify a download — see [`docs/security/code-signing.md`](docs/security/code-signing.md).

## Where data is stored

| Zone | Data | Current controls and lifecycle |
|---|---|---|
| **Z1 — Application files** | Executables, code, packaged model manifest/ONNX files when included | Model files are SHA256-checked against the applicable manifest at load time. Downloaded models are stored under `<app-data>/models`; application files are protected by the installation directory and host OS. |
| **Z2 — Settings and credentials** | UI preferences, PACS endpoints/usernames, custom HTTP headers, user-selected folders, (Full only) recent/last-session paths, key references and portable secrets | QSettings/INI and credential storage follow portable mode. Non-portable runs use the OS keychain; portable mode (the Presenter default) stores Fernet-encrypted password tokens under the portable root (`secrets.ini` + `device.key`). That stick/root and its `device.key` form one trust boundary; if portable secret storage is unavailable, passwords are not saved in clear text or redirected to the host keychain. Presenter does not read, display, or persist recent folder/study history or a last-session path. Settings can contain usernames, server details, or other paths that may identify a person or organization. In the full build patient measurements are retained locally by default (the Z2-M store below); Presenter keeps them session-only unless that store is enabled. |
| **Z2-M — Saved measurements** | Study/SOP identifiers, contours, calipers, Doppler/calibration inputs, result summaries, height/weight and their provenance; medical data even without a name | **On by default in the full build** (opt-in in Presenter); the toggle applies immediately. Versioned JSON under `<app-data>/measurements` (the active portable root whenever portable mode is enabled), atomic replacement and OS-backed single-writer lock. New POSIX directories/files use `0700`/`0600`; Windows inherits profile ACLs. 32 MiB document limit, 1 GiB aggregate write-admission limit, no automatic eviction or age cleanup. Records remain until explicit deletion; clearing the DICOM cache does not delete them. Settings provides export/import, record deletion and delete-all. Unsupported/corrupt records remain in place and block overwrite. A read-only portable medium fails visibly and never falls back to host measurements. No at-rest encryption or secure erase. |
| **Z3 — Managed DICOM cache** | Raw DICOM instances downloaded from a configured PACS/Orthanc server; files contain the original DICOM tags and may contain PHI | Stored at `<app-data>/cache/orthanc` (Windows `%LOCALAPPDATA%\SonoForge\cache\orthanc`; Linux `$XDG_DATA_HOME/sonoforge/cache/orthanc`; macOS `~/Library/Application Support/SonoForge/cache/orthanc`). In Presenter and any forced portable mode, it is under the portable root beside the executable/on the removable drive. UIDs are validated before forming paths. Files are set to mode `0600` where POSIX mode bits apply; SonoForge does not set cache-directory modes or ACLs, and on Windows file permissions are inherited from the containing folder/volume ACL. One running cache instance applies a **20 GiB write-admission limit**: a write that would exceed it is rejected and existing sessions are not evicted to make room. Sessions older than **7 days** are removed at application startup. By default, a normal application exit clears all sessions; this can be disabled in Settings. Settings shows the cache path and size and can clear it; a session backing the currently open PACS study is retained by that button so the study remains usable. Cancellation and handled whole-download failures clean up their temporary session where possible; if a download partially succeeds, its successful instances are retained and the failure is reported. A forced termination can leave a partial session until it is cleared or ages out. |
| **Z4 — User exports** | Explicitly saved DICOM, PDF, MP4, JPEG/PNG and other output files | Written to the location selected by the user. Exports may contain patient identifiers, rendered identifiers, or diagnostic images. SonoForge does not manage their retention after saving. |
| **Z5 — Logs** | Diagnostic and error messages | Stored under `<app-data>/logs`; Presenter logs and any forced-portable Full logs are under the portable root beside the executable. Logging helpers truncate DICOM UIDs and the application is designed not to log patient names/IDs intentionally. Logs are not a formal audit trail, and exception text or filesystem paths can still disclose operational details; inspect/redact logs before sharing them. Session files rotate within a run (`RotatingFileHandler`) and a privacy-filtered ZIP for support reports is produced by `infrastructure/diagnostics.py`. |

On the first full-profile launch after the path update, SonoForge attempts a one-time, non-overwriting move of legacy models, Orthanc cache, font cache, and logs. If a destination already contains an item, that legacy item is retained rather than overwritten. Existing models, and an old Orthanc cache when the canonical cache root is absent, have a read fallback during the migration release; original files are not automatically deleted to resolve conflicts.

The current cache is a **transient working copy**, not an archive or backup. The 20 GiB write-admission check is coordinated within one running application/cache instance, not across separate SonoForge processes sharing the same cache root; concurrent instances may therefore exceed it. Existing data from an older version is not deleted solely because it is already above the limit, but further writes are rejected until enough space is cleared. A cache limit or normal file deletion does not provide secure erasure: files may remain in filesystem snapshots, backups, SSD wear-leveling, the OS pagefile/swap, hibernation data, or crash dumps. The 20 GiB check is not a total-disk-usage limit for exports, logs, snapshots, or OS-managed copies.

## Data flow and network behavior

- **Support reports leave the machine only by the user's own hand.** `Settings → Report a problem…` builds a GitHub issue-form link from the allowlisted runtime summary (the same text the session log header carries) and, optionally, a sanitized diagnostic bundle on disk; the application never uploads anything itself, never puts log text or file paths into the link, and shows the exact environment block in the dialog before the user confirms.
- DICOM opened from a local folder is read from the user's source files and decoded in memory; SonoForge does not copy those source files into Z3. The OS may still page process memory to disk.
- A study retrieved from a configured server is saved as raw DICOM in Z3 so the viewer can access instances on demand. A separately selected **Save to disk** action copies the download to the user-selected destination.
- Sending a study to a server is an explicit user action. Network destinations and credentials are configured by the user; the application does not silently upload patient studies to a vendor cloud.
- DICOMweb uses the configured URL. The development default is loopback HTTP (`http://127.0.0.1:8042/dicom-web`). For any non-loopback endpoint, the transport policy (`application/transport_policy.py`, enforced in `OrthancDicomWebClient`, `PynetdimseClient`, `ServerSettings`, and UI connection flows under QH-2b) blocks plaintext HTTP (`http://`), HTTPS with certificate verification disabled (`tls_verify=False`), and unencrypted remote DIMSE (`dimse_use_tls=False`) before any network request or association is made, unless the user explicitly grants a scoped per-endpoint exception (`allow_insecure_transport` + `insecure_exception_scope` bound to `(transport, host, port, secure, verify)`).
- HTTP redirects are evaluated hop-by-hop (`evaluate_redirect`) in `OrthancDicomWebClient`: `https://` → `http://` downgrade redirects and redirects to unapproved plaintext/unverified remote endpoints are blocked before the redirect target is contacted, and `Authorization` plus user-configured custom headers are stripped on cross-authority redirects.
- Legacy server profiles saved before transport-policy migration (`transport_policy_version < 1`) are preserved without losing credentials; if a legacy profile targets a remote plaintext or unverified endpoint, it is marked `needs_confirmation=True` and blocked from network activity until the user either configures TLS/CA or explicitly confirms an exception for that server. Changing the host, port, scheme, or TLS verification mode invalidates any previously granted exception scope.
- DIMSE TLS (`dimse_use_tls=True`) defaults certificate verification to enabled (`dimse_tls_verify=True`) and supports custom CA bundles and optional client certificates. TLS handshake or certificate verification failures raise `DimseTlsError` and never downgrade to a plaintext DIMSE association.
- Local file access is governed by the host OS account and filesystem permissions. SonoForge has no local user/role system, centralized audit export, application-level at-rest encryption, cache backup/restore, or secure-delete function.

## Implemented safeguards

### DICOM input and filesystem paths

Files are validated before parsing (including magic bytes and a size limit). DICOM UIDs are validated before they are used in cache paths; invalid, overlong, or traversal-like values are rejected.

Relevant implementation:
- `src/echo_personal_tool/infrastructure/dicom_validator.py`
- `src/echo_personal_tool/infrastructure/dicom_uid_validator.py`
- `src/echo_personal_tool/infrastructure/orthanc_cache.py`

### Network transport

Transport security policy is evaluated and enforced across DICOMweb (QIDO-RS, WADO-RS, STOW-RS, Orthanc REST ping/previews/statistics) and DIMSE (C-ECHO, C-FIND, C-STORE, C-GET, C-MOVE). Loopback literals (`127.0.0.1`, `::1`, `localhost`) are permitted for local development; remote endpoints require verified TLS (system trust store or user-configured PEM CA bundle) unless a scoped per-endpoint exception is explicitly confirmed in the UI and shown as an active insecure-transport status badge. Service-level TLS and DIMSE TLS behavior is verified in CI against local loopback socket fixtures (`tests/security/test_https_enforcement.py`); interoperability with a specific hospital's external PACS/TLS deployment still depends on that environment's certificates, cipher suites, and network configuration.

Relevant implementation:
- `src/echo_personal_tool/application/transport_policy.py`
- `src/echo_personal_tool/infrastructure/server_settings.py`
- `src/echo_personal_tool/infrastructure/orthanc_client.py`
- `src/echo_personal_tool/infrastructure/dimse_client.py`
- `src/echo_personal_tool/presentation/server_settings_dialog.py`

### Credentials and model integrity

PACS passwords are stored in the OS keychain in non-portable mode and as Fernet-encrypted tokens in `secrets.ini` in portable mode (the Presenter default; subject to the portable-root trust model described above). If portable encryption/storage is unavailable, the password is not persisted; it is never redirected to the host keychain. Passwords are not intentionally stored in ordinary QSettings fields. ONNX models are SHA256-verified against the packaged manifest; a mismatch blocks model loading.

### Diagnostics

DICOM UID logging uses truncation helpers and PHI-sensitive tag values are masked in the DICOM tag inspector. These measures do not make all logs a complete or independently verified de-identification boundary. Logs should be reviewed before being sent outside the user's organization.

## Operational responsibilities and known limitations

- Use distinct OS accounts and appropriate ACLs for distinct operators. SonoForge has no in-app identity or role separation; people sharing one OS login share the same application access boundary.
- Enable full-disk/volume encryption and appropriate account ACLs on any workstation or removable drive that can hold Z2-M, Z3 or Z4 data. The application itself does not encrypt these files at rest.
- Treat Presenter USB media as patient-data media when a server study is downloaded or exported to it. Password-token encryption does not encrypt saved measurements, the DICOM cache or reports; do not store PHI on removable media unless the organization's approved media protections (including encryption where required) are in place.
- Choose a retention period compatible with the organization's policy. The built-in cache lifecycle is limited to normal-exit cleanup (enabled by default), a 7-day startup age cleanup, a 20 GiB cache ceiling, and manual clearing; it does not manage user exports or PACS retention.
- Validate TLS support, peer certificate setup, access policy, backups, audit requirements, and recovery procedures for the particular PACS and workstation deployment.
- Obtain the application only from [GitHub Releases](https://github.com/areatu/SonoForge/releases) and verify the download before deployment: the release `SHA256SUMS` manifest covers integrity, and the Sigstore build-provenance attestation on every asset (`gh attestation verify <file> --repo areatu/SonoForge`) establishes that the artifact was built by a workflow in this repository from a known commit. **Windows executables are not Authenticode-signed and macOS builds are neither Developer ID-signed nor notarized**; SmartScreen and Gatekeeper warnings are expected, and environments that block unsigned binaries will need an explicit allow-list entry. See [`docs/security/code-signing.md`](docs/security/code-signing.md).
- No blanket claim of HIPAA, GDPR, 152-ФЗ, FDA, CE/MDR, or DICOM security-profile compliance is made. The data-inventory appendix maps relevant expectations to the application's current controls and gaps; the data controller/operator and clinical organization remain responsible for applicability and deployment-level controls.

### Measurement-store limitations

- Recovery covers the last successfully written snapshot, not every mouse movement or an unfinished AI preview. A failed or timed-out save blocks switching studies/closing until retry, export or an explicit decision to continue without saving.
- Source checks prevent automatic restore to incompatible geometry/calibration. DICOM matching relies on correct Study/Series/SOP UID assignment and semantic header fingerprints; it is not a pixel-integrity guarantee. Non-DICOM uses a path-derived identity plus a full content hash; moving a folder never triggers automatic restore. Explicit import can rebind an export to a local study only after a unique full-content-hash/frame-count/spacing match for every source and user confirmation. Duplicate content or changed sources are refused; sources are rehashed at preview and confirmation.
- Source images, PACS endpoints, patient names and credentials are not included by the store's codec. User-entered labels, UIDs and clinical values may still be identifying. JSON exports are unencrypted PHI outside managed retention.
- This is an experimental implementation, not the completed WP4 acceptance matrix. Native Windows/macOS locking, packaging and recovery still require verification; detailed migration/provenance and richer conflict-management workflows remain tracked in the WP4.1 spec.


### Diagnostic filtering limitations (QH-4a)

Support ZIP generation projects only complete allowlisted `operation/code/error_type` boundary
events (`safe_diagnostics.py`) and pre-sanitizes local log files (`sanitize_local_log_files`).
Local `session-*.log`, `crash.log`, and `presenter_diag.log` files are also scrubbed at write
time (`_SanitizingFileFormatter`, `_SanitizingCrashStream`, `PresenterDiagnostics._write`) to
redact known structured patient fields (including quoted JSON/repr keys), full UID-like
identifiers, filesystem paths, URLs, emails, single-line exception payloads, and structured
Authorization/password/API-key/token, label and payload fields. Source filenames in the ZIP are
replaced with opaque archive names; symlinks are not followed. These contracts and the codebase-wide
producer ratchets (zero `logger.exception`/`exc_info=True` and zero raw exception payloads in logger
calls) are enforced by `tests/security/test_qh4a_diagnostics.py` in the required security CI gate.

Pattern-based scrubbing of local logs remains **defense in depth, not a formal proof of
anonymisation for arbitrary free-form text** or native OS core dumps outside Python's
`faulthandler` stream. Inspect every archive or log file before sharing externally; do not
attach files publicly if privacy cannot be verified. See the
[QH-4a register](docs/reviews/2026-10-14-qh-4a-error-register-ru.md).
