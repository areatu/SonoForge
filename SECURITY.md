# Security and Managed Persistence

This document describes the current SonoForge desktop application's behavior. It is an implementation inventory, not a security certification, regulatory submission, or claim that a particular clinic's deployment complies with a law or policy. SonoForge does not provide an in-app multi-user login or application-level encryption for cached DICOM or user exports.

For the regulatory mapping and shared-responsibility notes, see [`docs/security/data-inventory.md`](docs/security/data-inventory.md). For release artifact authenticity — what is signed, what is attested, and how to verify a download — see [`docs/security/code-signing.md`](docs/security/code-signing.md).

## Where data is stored

| Zone | Data | Current controls and lifecycle |
|---|---|---|
| **Z1 — Application files** | Executables, code, packaged model manifest/ONNX files when included | Model files are SHA256-checked against the applicable manifest at load time. Downloaded models are stored under `<app-data>/models`; application files are protected by the installation directory and host OS. |
| **Z2 — Settings and credentials** | UI preferences, PACS endpoints/usernames, custom HTTP headers, user-selected folders, last-opened-folder path, key references and (Presenter) portable secrets | QSettings/INI and the OS keychain are used according to build profile. Full SonoForge stores PACS passwords through the OS keychain. Presenter stores encrypted password tokens beside its executable; the stick and its `device.key` form one trust boundary. Settings can contain usernames, server details, or paths that may identify a person or organization. Patient measurements are session-only by default during the experimental persistence rollout; the opt-in Z2-M store below can retain them. |
| **Z2-M — Saved measurements (experimental opt-in)** | Study/SOP identifiers, contours, calipers, Doppler/calibration inputs, result summaries, height/weight and their provenance; medical data even without a name | Off by default in Full and Presenter; enabling requires restart. Versioned JSON under `<app-data>/measurements` (portable root in Presenter), atomic replacement and OS-backed single-writer lock. New POSIX directories/files use `0700`/`0600`; Windows inherits profile ACLs. 32 MiB document limit, 1 GiB aggregate write-admission limit, no automatic eviction or age cleanup. Records remain until explicit deletion; clearing the DICOM cache does not delete them. Settings provides export/import, record deletion and delete-all. Unsupported/corrupt records remain in place and block overwrite. No at-rest encryption or secure erase. |
| **Z3 — Managed DICOM cache** | Raw DICOM instances downloaded from a configured PACS/Orthanc server; files contain the original DICOM tags and may contain PHI | Stored at `<app-data>/cache/orthanc` (Windows `%LOCALAPPDATA%\SonoForge\cache\orthanc`; Linux `$XDG_DATA_HOME/sonoforge/cache/orthanc`; macOS `~/Library/Application Support/SonoForge/cache/orthanc`). In Presenter, it is beside the executable/on the removable drive. UIDs are validated before forming paths. Files are set to mode `0600` where POSIX mode bits apply; SonoForge does not set cache-directory modes or ACLs, and on Windows file permissions are inherited from the containing folder/volume ACL. One running cache instance applies a **20 GiB write-admission limit**: a write that would exceed it is rejected and existing sessions are not evicted to make room. Sessions older than **7 days** are removed at application startup. By default, a normal application exit clears all sessions; this can be disabled in Settings. Settings shows the cache path and size and can clear it; a session backing the currently open PACS study is retained by that button so the study remains usable. Cancellation and handled whole-download failures clean up their temporary session where possible; if a download partially succeeds, its successful instances are retained and the failure is reported. A forced termination can leave a partial session until it is cleared or ages out. |
| **Z4 — User exports** | Explicitly saved DICOM, PDF, MP4, JPEG/PNG and other output files | Written to the location selected by the user. Exports may contain patient identifiers, rendered identifiers, or diagnostic images. SonoForge does not manage their retention after saving. |
| **Z5 — Logs** | Diagnostic and error messages | Stored under `<app-data>/logs`; Presenter logs are on the removable drive beside the executable. Logging helpers truncate DICOM UIDs and the application is designed not to log patient names/IDs intentionally. Logs are not a formal audit trail, and exception text or filesystem paths can still disclose operational details; inspect/redact logs before sharing them. Current file handlers do not rotate logs. |

On the first full-profile launch after the path update, SonoForge attempts a one-time, non-overwriting move of legacy models, Orthanc cache, font cache, and logs. If a destination already contains an item, that legacy item is retained rather than overwritten. Existing models, and an old Orthanc cache when the canonical cache root is absent, have a read fallback during the migration release; original files are not automatically deleted to resolve conflicts.

The current cache is a **transient working copy**, not an archive or backup. The 20 GiB write-admission check is coordinated within one running application/cache instance, not across separate SonoForge processes sharing the same cache root; concurrent instances may therefore exceed it. Existing data from an older version is not deleted solely because it is already above the limit, but further writes are rejected until enough space is cleared. A cache limit or normal file deletion does not provide secure erasure: files may remain in filesystem snapshots, backups, SSD wear-leveling, the OS pagefile/swap, hibernation data, or crash dumps. The 20 GiB check is not a total-disk-usage limit for exports, logs, snapshots, or OS-managed copies.

## Data flow and network behavior

- DICOM opened from a local folder is read from the user's source files and decoded in memory; SonoForge does not copy those source files into Z3. The OS may still page process memory to disk.
- A study retrieved from a configured server is saved as raw DICOM in Z3 so the viewer can access instances on demand. A separately selected **Save to disk** action copies the download to the user-selected destination.
- Sending a study to a server is an explicit user action. Network destinations and credentials are configured by the user; the application does not silently upload patient studies to a vendor cloud.
- DICOMweb uses the configured URL. The development default is loopback HTTP (`http://127.0.0.1:8042/dicom-web`); HTTPS is **not** forced for remote URLs. Certificate verification defaults to enabled when HTTPS is used, but can be disabled in settings.
- DIMSE TLS is optional and **disabled by default**. When enabled, certificate verification defaults to enabled; disabling verification logs a warning. Use an approved secure transport or a suitably isolated clinical network for transfers containing PHI.
- Local file access is governed by the host OS account and filesystem permissions. SonoForge has no local user/role system, centralized audit export, application-level at-rest encryption, cache backup/restore, or secure-delete function.

## Implemented safeguards

### DICOM input and filesystem paths

Files are validated before parsing (including magic bytes and a size limit). DICOM UIDs are validated before they are used in cache paths; invalid, overlong, or traversal-like values are rejected.

Relevant implementation:
- `src/echo_personal_tool/infrastructure/dicom_validator.py`
- `src/echo_personal_tool/infrastructure/dicom_uid_validator.py`
- `src/echo_personal_tool/infrastructure/orthanc_cache.py`

### Network transport

DICOMweb TLS certificate verification defaults to `True` for HTTPS. DIMSE TLS settings, including certificate verification and optional CA/client certificate paths, are configurable in Server Settings. These settings do not guarantee that a configured peer uses a secure profile; both endpoints and the deployment network must be checked.

Relevant implementation:
- `src/echo_personal_tool/infrastructure/server_settings.py`
- `src/echo_personal_tool/infrastructure/orthanc_client.py`
- `src/echo_personal_tool/infrastructure/dimse_client.py`

### Credentials and model integrity

PACS passwords are stored in the OS keychain in the full profile and as encrypted tokens in the Presenter profile (subject to the portable-stick trust model described above). Passwords are not intentionally stored in ordinary QSettings fields. ONNX models are SHA256-verified against the packaged manifest; a mismatch blocks model loading.

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

### Experimental measurement-store limitations

- Recovery covers the last successfully written snapshot, not every mouse movement or an unfinished AI preview. A failed or timed-out save blocks switching studies/closing until retry, export or an explicit decision to continue without saving.
- Source checks prevent automatic restore to incompatible geometry/calibration. DICOM matching relies on correct Study/Series/SOP UID assignment and semantic header fingerprints; it is not a pixel-integrity guarantee. Non-DICOM uses a path-derived identity plus a full content hash; moving a folder currently requires a new record.
- Source images, PACS endpoints, patient names and credentials are not included by the store's codec. User-entered labels, UIDs and clinical values may still be identifying. JSON exports are unencrypted PHI outside managed retention.
- This is an experimental implementation, not the completed WP4 acceptance matrix. Native Windows/macOS locking, packaging and recovery still require verification; detailed migration/provenance and richer conflict-management workflows remain tracked in the WP4.1 spec.
