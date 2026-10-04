# Data Inventory and Security-Expectation Mapping

**Snapshot:** 2026-10-03  

**Scope:** current SonoForge desktop application and its managed Orthanc/DICOM cache.  
**Purpose:** implementation inventory for deployment review, not a legal opinion, conformity assessment, or compliance certificate.

A product feature alone cannot determine whether a clinic's processing is compliant. The organization deploying the application must determine which laws and policies apply, assess the complete system (workstation, OS, PACS, network, backups, users and exports), and set its own retention and access rules.

## Data inventory

| Data / activity | Created or received by | Location | Lifecycle and protections | Remaining responsibility |
|---|---|---|---|---|
| DICOM opened from a local folder | User selects a folder; SonoForge reads source instances and decodes frames | Original user-selected files; decoded frames are session memory; measurements are session memory unless the experimental Z2-M store is enabled | SonoForge does not copy local-folder source instances into the managed Orthanc cache. OS paging, hibernation, crash dumps and backups are outside app control. | Protect the source folder and workstation; manage source retention and backup. |
| Saved measurements and height/weight (experimental opt-in) | Completed measurement edits, source DICOM metrics or manual entry | Z2-M: `<app-data>/measurements`; portable data root in Presenter | Disabled by default; enabling requires restart. Atomic versioned JSON, source checks, single-writer OS lock, 32 MiB per document and 1 GiB write-admission ceiling, no eviction. Retained until explicit deletion; cache clearing does not affect it. Corrupt/future records block overwrite. Source files and patient-name fields are not copied. Own-format JSON export/import includes height/weight. | Treat UID, geometry, labels and values as PHI; protect the account/volume; set retention policy and delete explicitly. No app encryption, secure erase or full clinical archive. Verify restored results and experimental limitations before use. |
| DICOM retrieved from a PACS | User configures a PACS endpoint and starts a retrieve | Z3 managed cache: `<app-data>/cache/orthanc` (Windows `%LOCALAPPDATA%\SonoForge\cache\orthanc`; Linux `$XDG_DATA_HOME/sonoforge/cache/orthanc`; macOS `~/Library/Application Support/SonoForge/cache/orthanc`), or Presenter data directory on removable media | Raw DICOM (including original tags) is stored. 20 GiB write-admission limit per running app process; writes beyond the limit are rejected without evicting existing sessions. Default cleanup on normal app exit; 7-day stale-session removal at next startup; manual clear in Settings preserves a session backing an open study. Files receive `0600` mode where supported; the app does not set directory modes/ACLs and Windows inherits the containing folder/volume ACL. No app-level at-rest encryption. | Use approved account/volume controls and disk encryption; confirm PACS/network security; choose whether to retain cache between launches. |
| User-selected DICOM export / PACS save-to-disk | User invokes an export/save action and selects a destination | User-selected directory or removable media | Outside Z3 cache retention and size controls. Contents may include PHI. Normal filesystem deletion only. | Apply the organization's destination, access, encryption, labeling and retention policy. |
| PDF, MP4, JPEG/PNG and other reports/exports | User invokes export and chooses a path | User-selected destination | Not automatically encrypted, purged, or backed up by SonoForge. Rendered overlays or report fields may identify a patient. | Protect and retain/delete according to the local policy. |
| Preferences and PACS profile | User configures the application | QSettings/INI and OS keychain; Presenter profile files reside beside the executable | Can contain usernames, server endpoints, custom headers and folder paths (including paths that may be identifying). Passwords use OS keychain in full profile; Presenter uses encrypted portable tokens under a stick-level trust model. | Protect the user profile/removable drive; review custom headers and paths. |
| Diagnostics | Application runtime and error handlers | `<app-data>/logs` in the full profile; Presenter logs are beside the executable on removable media | UID truncation and PHI-aware tag filtering are present, but logs are not a formal audit trail and exception text/paths can reveal details. Logs are not rotated. The first launch after the path update attempts a one-time move of legacy logs without overwriting destination files. | Review and redact logs before sharing; manage host-profile or removable-media access and retention. |
| Explicit PACS upload | User configures a target and invokes **Send to Server** | Configured DICOMweb or DIMSE peer | DICOMweb uses the configured scheme and TLS verification setting; the code does not force HTTPS for remote endpoints. DIMSE TLS is optional and off by default. | Use the site's approved secure profile/network and validate peer identity/configuration. |

### Cache lifecycle summary

The 20 GiB write-admission check is synchronized among worker threads sharing one cache object, not across separate SonoForge processes sharing the same cache path. If concurrent app processes write to one root, the aggregate may exceed 20 GiB. Existing data already over the limit is not purged solely for that reason, but subsequent writes are refused until space is cleared.

1. A server download is written into a per-session DICOM directory; identifiers used for filesystem paths are validated.
2. Each cache write is checked against the 20 GiB combined limit. If it would exceed the limit, that write fails; the cache does not silently evict a session that may be in use.
3. On application startup, sessions whose directory modification time is older than 7 days are removed. Each successful instance write refreshes that session timestamp.
4. On a normal application exit, all sessions are cleared by default. Users can opt out in **Settings → Other → Downloaded DICOM cache**.
5. The Settings clear action shows current path and size. It clears non-active sessions and retains any cache session referenced by the currently loaded PACS study.
6. Cancellation and handled whole-download failures attempt to remove the session. If a download partially succeeds, successful instances are retained and a warning is shown. A forced kill may leave partial DICOM files; startup age cleanup and manual clear are recovery paths.
7. Deletion is not secure erasure and does not reach user exports, OS snapshots/backups, pagefile/swap, hibernation files or crash dumps.

## Mapping to selected security expectations

This table maps implementation facts to topics in the regulations; it does **not** conclude that the application or a deployment satisfies them.

| Reference / expectation | SonoForge implementation relevant to the topic | Gaps / deployment-level work |
|---|---|---|
| **152-ФЗ, Article 19** — the personal-data operator must take legal, organizational and technical measures; Article 19 includes threat assessment, access rules and accounting of actions, detection/response, and recovery among the measures relevant to its scope. | UID/path validation; per-user cache location; 20 GiB cap; 7-day stale cleanup; normal-exit/manual deletion; configurable DICOM transport protection. | No in-app user/role administration or central audit record of every PHI read/export/delete; no cache backup/restore; no app-level encryption at rest. The operator must assess applicable threat/level requirements, OS controls, network, incident response, backups and records of processing. |
| **GDPR, Article 32** — risk-appropriate technical and organizational measures, including as appropriate confidentiality, integrity, availability/resilience, recovery and regular testing; pseudonymization/encryption are examples, not a one-size-fits-all guarantee. | Managed cache lifecycle and size cap; optional TLS settings; UID validation; model-file hash verification; explicit exports. | Cache and exports are not app-encrypted; no app-provided PHI recovery/backup, full audit export, or availability guarantee. Controller/processor must evaluate the complete processing risk and document adequate organizational and technical controls. |
| **HIPAA Security Rule, 45 CFR §164.312** — technical safeguards cover access control, audit controls, integrity, person/entity authentication and transmission security for ePHI. | OS account/ACL and PACS authentication are relied upon; DIMSE TLS can be enabled and has certificate-verification options; DICOMweb certificate verification defaults to true for HTTPS. | SonoForge has no local login/RBAC, no centralized audit controls, no general integrity mechanism for stored patient DICOM, and no enforced HTTPS; DIMSE TLS defaults off. Covered entities/business associates must assess and configure the full environment, including policies, unique-user access, audit, integrity and secure transmission. |

## References

- Russian Federation, Federal Law No. 152-ФЗ, Article 19, *Measures to ensure the security of personal data during their processing* (current text should be confirmed for the deployment date): [Article 19 text](https://legalacts.ru/doc/152_FZ-o-personalnyh-dannyh/glava-4/statja-19/).
- Regulation (EU) 2016/679, Article 32, *Security of processing*: [EUR-Lex official text](https://eur-lex.europa.eu/eli/reg/2016/679/oj/eng).
- U.S. HIPAA Security Rule, 45 CFR Part 164, Subpart C, including §164.312: [eCFR current text](https://www.ecfr.gov/current/title-45/subtitle-A/subchapter-C/part-164).
- Implementation details and limitations: [`SECURITY.md`](../../SECURITY.md).
