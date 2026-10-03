# Plan: Managed Persistence, Platform Paths, and Windows Packaging

**Date:** 2026-10-01
**Status:** Plan; WP1 and WP3 implementation snapshots updated 2026-10-02
**Type:** Architecture / Packaging / Security
**Scope:** data-storage security concept, platform path handling, Windows distribution
**Related:**
- `SECURITY.md`, `README.md` (Security and Privacy sections) — claims to be revised
- `src/echo_personal_tool/infrastructure/profile.py` — portable-mode helpers
- `src/echo_personal_tool/infrastructure/orthanc_cache.py` — PHI session cache (lifecycle gap)
- `src/echo_personal_tool/infrastructure/runtime_setup.py`, `onnx_engine.py`, `onnx_worker.py` — XDG-style hardcoded model paths
- `docs/superpowers/specs/2026-08-07-memory-optim-spec.md` — where the disk frame cache was rejected under the old "no PHI on disk" rule
- `scripts/setup.bat` — helper used by the lightweight Windows ZIP only; the old `scripts/create_installer.py` / `installer_stub.py` zip-stub flow is retired
- `.github/workflows/release.yml` — builds the Inno Setup installer and versioned portable EXE

---

## 1. Executive Summary

Three converging changes:

1. **Security concept** — replace the absolute claim "no PHI is written to disk" with
   **managed persistence**: PHI may reside on disk only in explicitly defined zones with
   permissions, quota, and a documented lifecycle. Processing pipelines stay in RAM;
   anything written is either (a) a user-initiated export, (b) a managed cache, or
   (c) the user's own study data (measurements) with a clear retention policy.
2. **Platform paths** — one path module (platformdirs/QStandardPaths-based) replacing
   four inconsistent hardcoded locations; migration from old locations.
3. **Windows packaging** — a real per-user installer (default, no UAC →
   `%LOCALAPPDATA%\Programs\SonoForge`) with optional per-machine mode (admin,
   Program Files); fix README/release artifact mismatches. No separate "portable SKU"
   for the main app — the onefile EXE stays as a secondary artifact short-term under
   `SonoForge-<version>-portable.exe`; the fixed `SonoForge.exe` name remains as a
   compatibility alias for the existing stable download URL. SonoForge Presenter
   remains the official portable product.

Relaxing the "no disk" rule unblocks (later phases): measurement persistence,
per-study height/weight, crash recovery, optional disk frame cache, thumbnails cache,
report drafts, recent-studies list.

---

## 2. Answers to Open Questions (recorded decisions)

### 2.1 Two builds (installer + portable) — or is that too much?

**Decision: one installer artifact covering both privilege modes; no second product build.**
- Inno Setup 6: `PrivilegesRequired=lowest` + `PrivilegesRequiredOverridesAllowed=dialog`
  → dialog "Just for me / For all users" in a single `SonoForge-Setup-<ver>-x64.exe`.
- Per-user default installs to `%LOCALAPPDATA%\Programs\SonoForge` (no UAC — solves the
  "hospital user is not admin" problem). Per-machine goes to Program Files (admin).
- App data (models, cache, logs) is **always per-user** (`%LOCALAPPDATA%\SonoForge`),
  even for per-machine installs: model download/update never needs admin.
- The raw onefile build stays in releases short-term as a "portable/advanced" artifact
  named `SonoForge-<version>-portable.exe`, documented as "put in a permanent folder,
  not Downloads". The exact `SonoForge.exe` asset is also retained as a compatibility
  alias for the existing stable URL. Candidate for removal after 1–2 releases: the
  portable niche is covered by Presenter.
- Installer packages the **onedir** build (`build/windows/build.spec` folder mode), not
  onefile — faster startup, no `%TEMP%\_MEIxxx` unpack on every run.
- The `launcher.py` + venv + `pip install` on first run scheme is retired for the main
  distribution (fragile, requires system Python); the self-contained PyInstaller folder
  replaces it. `.deb` lite flow on Linux is out of scope here.
- Code signing (Authenticode) is tracked as a separate organizational task; SmartScreen
  warnings affect both onefile and installer until signed.

### 2.2 Hardcoded paths and README

**Decision: single source of truth for paths + migration + README corrections.**
- See WP2. README mismatches confirmed against actual release assets:
  - before WP1, `SonoForge-Setup-*.exe` was promised but only `SonoForge.exe` was published; WP1 now adds the installer;
  - macOS: README says `.zip`, releases ship `SonoForge-macos-arm64.dmg`;
  - "First run will automatically set up the environment and install all dependencies"
    is true for the .deb/lite flow only — for the standalone exe only AI models download.

### 2.3 Updated security concept; what "nothing on disk" constrained; architecture?

**Decision: managed persistence (zones + lifecycle), not zero writes.**
What the old rule constrained in the current code:
1. No disk cache for decoded frames (explicitly rejected in the 2026-08-07 memory spec) —
   everything must fit the RAM `FrameCache` budget; weak PCs re-decode constantly.
2. `StudyMeasurementSessionStore` is in-memory only — restart loses all measurements;
   no autosave, no crash recovery, no "continue tomorrow".
3. Height/Weight are session-only and re-entered every time.
4. No recent-studies (MRU) list, no report drafts (both would persist identifiers).
5. The Orthanc download cache already writes raw PHI DICOM to disk as a compromise
   (`orthanc_cache.py`) — i.e., the rule was already broken in practice, undocumented.
6. Good things the rule produced and that STAY: sanitized logs (no names, truncated UIDs),
   `np.memmap` read-only mapping of the original file instead of copies, keyring secrets.

New concept — storage zones (see WP3). Architecture unlocked (see WP4): measurement
persistence, per-study demographics, optional disk frame cache, thumbnail cache, MRU.

---

## 3. Workstreams

### WP1 — Windows packaging (installer)

| # | Task | Notes |
|---|------|-------|
| 1.1 | Inno Setup script (new `build/windows/sonoforge.iss`) | per-user default → `%LOCALAPPDATA%\Programs\SonoForge`; optional per-machine via dialog; Start Menu + Desktop shortcuts; ARP uninstall entry; closes running app through Restart Manager on install/uninstall (without forced termination) |
| 1.2 | Package onedir build (`build/windows/build.spec`) | retire `installer_stub.py`/`scripts/create_installer.py` zip-stub flow |
| 1.3 | CI: extend `release.yml` `build-windows` job | install Inno Setup 6.7.1 with Chocolatey; compile and upload `SonoForge-Setup-<version>-x64.exe`; upload the onefile build as `SonoForge-<version>-portable.exe` and retain `SonoForge.exe` as a compatibility alias |
| 1.4 | Uninstaller semantics | remove app dir, shortcuts, ARP entry; **never** touch `%LOCALAPPDATA%\SonoForge` data without an explicit checkbox ("remove user data") |
| 1.5 | README/HELP updates | correct artifact names (see WP2/§5); describe "install for me / for all users" |
| 1.6 | (Separate track) Authenticode signing | org task: certificate + signtool step in CI |

Acceptance: clean install on a non-admin Windows account → app runs from Start Menu,
survives reboot, uninstalls cleanly; no UAC prompt in per-user mode.

**Implementation status (2026-10-02):** WP1 items 1.1–1.5 are implemented on this
branch. The new Inno Setup script installs the PyInstaller onedir payload per-user by
default, offers an all-users mode, creates Start Menu/Desktop shortcuts and an ARP
entry, requests app closure through Windows Restart Manager during install/uninstall,
and removes the current account's `%LOCALAPPDATA%\SonoForge` data only after an explicit
checkbox selection. Silent uninstall preserves user data. The release workflow compiles
the setup, publishes the versioned portable EXE plus the existing fixed-name
compatibility alias, generates a release `SHA256SUMS` manifest, and includes a per-user
install/uninstall smoke test. This session cannot execute the Windows workflow; real
non-admin-account/reboot acceptance remains pending its CI run and manual platform
verification. Authenticode remains the separate organizational task in 1.6.

### WP2 — Platform paths

Current state (all confirmed in code):

| Consumer | Current path | Issue |
|---|---|---|
| `runtime_setup.py`, `onnx_engine.py`, `onnx_worker.py` | `Path.home()/".local"/"share"/"sonoforge"` | XDG hardcode; on Windows → `C:\Users\X\.local\share` |
| `app_controller.py`, `main_window.py`, `profile.diag_log_dir` | `%LOCALAPPDATA%\SonoForge\logs` (fallback `~/SonoForge/logs`) | definition duplicated ×3; Linux fallback wrong |
| `profile.orthanc_cache_root` | `~/.sonoforge/orthanc` | a third dotdir |
| `launcher.py`, `scripts/uninstall.bat` | `%LOCALAPPDATA%\SonoForge` | separate tree (`venv`, `models`) |

| # | Task | Notes |
|---|------|-------|
| 2.1 | New `infrastructure/paths.py` (or extend `profile.py`) | `platformdirs` (tiny dep) or `QStandardPaths.AppLocalDataLocation`; expose `data_dir()`, `models_dir()`, `cache_dir()`, `logs_dir()`, `orthanc_cache_dir()`; portable overrides keep priority (`profile.portable_path`) |
| 2.2 | Target layout | Windows: `%LOCALAPPDATA%\SonoForge\{models,cache\orthanc,logs}`; Linux: `$XDG_DATA_HOME/sonoforge/...` (default `~/.local/share/sonoforge`); macOS: `~/Library/Application Support/SonoForge/...` |
| 2.3 | Replace all hardcoded call sites | route platform-path resolution through the shared module, including the duplicated `_LOG_DIR` expressions; this does not fold the separate logging refactor into WP2 |
| 2.4 | Migration on startup | detect old `~/.local/share/sonoforge/models`, `~/.sonoforge/{orthanc,fonts}`, and legacy `~/SonoForge/logs` / `%LOCALAPPDATA%\\SonoForge\\logs`; move models/cache/logs into the new layout once without overwriting; keep model/cache read-fallback for one release |
| 2.5 | README/HELP/docs corrections | `SonoForge-Setup-*.exe` → actual names; macOS `.zip` → `SonoForge-macos-arm64.dmg`; first-run wording per distribution |

Acceptance: fresh Windows install creates no dotdirs in `%USERPROFILE%`; models land in
`%LOCALAPPDATA%\SonoForge\models`; old installs migrate without re-downloading models.

**Implementation status (2026-10-02):** WP2 items 2.1–2.4 and P0 item 2.5 are implemented on this branch. `infrastructure/paths.py` is the shared source for per-user data, models, cache, logs, fonts, and launcher venv paths; portable paths retain priority. Startup performs a non-overwriting, marker-based migration and keeps legacy model/cache reads for the migration release. Linux and Windows lightweight launchers query the same module before model checks. Unit tests cover Windows/Linux/macOS path resolution, XDG behavior, migration, conflict preservation, portable-mode isolation, and fallback reads. A real fresh Windows install and Apple-Silicon DMG smoke test still require their respective platforms.

### WP3 — Security concept: managed persistence

Zones:

| Zone | Content | PHI? | Controls | Lifecycle |
|---|---|---|---|---|
| Z1 install dir | binaries, model manifest/weights | no (models are not patient studies) | host installation permissions; model SHA256 verification | replaced on update |
| Z2 app data | settings, server profiles, keyring refs, Presenter device key | may include identifying paths/usernames/endpoints | OS profile/ACL and OS keychain (full profile); Presenter secrets remain within the stick trust boundary | kept according to OS/user policy |
| Z3 managed cache | Orthanc session cache; (later) frame/thumbnail cache | **yes** | UID/path validation; per-file POSIX `0600` where supported (no directory-mode/ACL configuration); Windows inherits folder/volume ACL; fixed 20 GiB write-admission limit per app process, shown in Settings | stale sessions >7 days removed at startup; clear button; normal-exit clear enabled by default; open-study session preserved by manual clear |
| Z4 user exports | PDF/MP4/«save to disk» DICOM | **yes** | user-chosen folder; application does not encrypt or manage retention | user's responsibility; UI warning is not currently implemented |
| Z5 logs | diagnostics | UID truncation and PHI-aware tag filtering are used; exceptions/paths may still disclose details | platform app-data `logs` directory; Presenter logs follow the portable data root; current file handlers are not rotated | log retention/sharing is user's responsibility |

| # | Task | Notes |
|---|------|-------|
| 3.1 | Fix `OrthancSessionCache` lifecycle | Call `clear_stale()` at startup; clear on normal exit by default with a persisted opt-out; enforce a 20 GiB per-process write-admission quota; manual clear preserves active study sessions |
| 3.2 | Settings UI | "Downloaded DICOM cache" block: location, current size, fixed quota, "Clear cache", optional "Clear cache on exit" |
| 3.3 | Rewrite `SECURITY.md` + README privacy block | replace "no PHI is written to disk" with the zone table + retention rules; state OS-level reliance (BitLocker/FileVault) for at-rest protection of Z3/Z4; note pagefile/hibernation/crash-dumps are outside app control |
| 3.4 | Data inventory / processing record | short appendix mapping to 152-FZ / GDPR Art.32 / HIPAA Security Rule expectations (minimization, access control, retention, auditability) |
| 3.5 | Keep unchanged | log sanitization, DICOM/UID validation, model SHA256, keyring, TLS options |
| 3.6 | Explicitly out of scope | custom cache encryption, secure-delete claims, fighting pagefile/hiberfil/WER dumps, and an in-app user/role system. WP3 treats one OS account as the local access boundary; use distinct OS accounts/ACLs for distinct operators. Write a separate threat model/spec before supporting shared OS logins or requiring user-separated records; assess encrypted-volume requirements separately for Presenter media containing PHI. |

Acceptance: after force-killing the app mid-download, the partial session is removed at
startup once it is older than 7 days; SECURITY.md matches actual behavior (no absolute
claims left); Settings shows path, size and quota, clears inactive cache sessions, and
persists the normal-exit cleanup preference; a single app process cannot write beyond
the 20 GiB cache limit. Concurrent processes sharing the same root are not coordinated.

**Implementation snapshot (2026-10-02):** WP3 code and documentation are in place on
this branch. The cache limit is a fixed 20 GiB per-process write-admission ceiling (not
user-configurable); concurrent processes sharing a cache root are not coordinated, and
existing over-limit data is not retroactively deleted. Exports and operating-system
copies are outside this quota. POSIX file mode `0600` does not set Windows ACLs or
directory permissions. The application does not encrypt cache
files or provide secure deletion. Ninety cache, worker, QSettings-persistence, and locale
tests pass in the available environment. Qt GUI tests could not be executed in this sandbox
because `libGL.so.1` is unavailable; this is an environment limitation, not a test pass.
This snapshot is not an independent security or regulatory review.

### WP4 — Architecture enabled by managed persistence (later phases)

| # | Task | Zone | Value |
|---|---|---|---|
| 4.1 | Measurement persistence keyed by Study Instance UID (autosave, restore on reopen, crash recovery) | Z3/Z2 hybrid — own store (e.g. per-study JSON/SQLite under app data), documented | biggest product win; commercial stations all persist measurements |
| 4.2 | Per-study Height/Weight persistence | same store | stop re-entering |
| 4.3 | Optional disk cache for decoded frames (LRU, quota) | Z3 | fast study switching, weak-PC relief (the 2026-08-07 rejected item) |
| 4.4 | Thumbnail cache for local folder scans | Z3 | faster galleries |
| 4.5 | Report drafts + recent studies (MRU) | Z2 (MRU stores UIDs/paths only, no names) | ergonomics |

Each item gets its own spec under `docs/superpowers/specs/` before implementation;
4.1 is the recommended first candidate.

**WP4.1 specification (2026-10-03):** [Measurement persistence draft (RU)](2026-10-03-wp4-1-measurement-persistence-spec-ru.md)
now covers identity, storage/codec, autosave and recovery, deletion, portability,
security, and acceptance tests. It is a proposal for review, not implemented behavior.
Retention/defaults and the first-release scope remain subject to approval; WP4.2
height/weight persistence remains separate.

---

## 4. Phasing

| Phase | Content | Rationale |
|---|---|---|
| **P0 (quick wins)** | 3.1 cache lifecycle fix, 3.3 docs honesty, 2.5 README corrections | cheap, removes real PHI risk and false claims |
| **P1** | WP2 paths + migration | prerequisite for everything touching storage |
| **P2** | WP1 installer + CI + 3.2 Settings cache UI | user-visible distribution fix |
| **P3** | 3.4 compliance appendix | after behavior is stable |
| **P4** | WP4 items, each behind its own spec | product features, not security debt |

## 5. Risks

- **Migration mistakes** (models/cache moved wrong) → fallback-read old paths for one release; migration unit-tested against fixtures.
- **Inno + CI friction** (ISCC on windows-latest) → pin installer action/choco version; keep raw exe published until installer proven.
- **Scope creep in WP4** — persistence of measurements is a product feature with its own UX (export/import, delete-all); do not fold it into P0–P2.
- **Docs drift again** → acceptance criterion "SECURITY.md statements trace to code" for review checklists.
