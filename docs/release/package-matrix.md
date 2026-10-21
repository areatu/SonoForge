# Release package matrix and packaged-artifact evidence

> [Русская версия](package-matrix-ru.md)

**Status:** implemented for Gate **G5a** (QH-5a, issue #188, spec
[2026-10-13 §9.1](../superpowers/specs/2026-10-13-quality-safety-hardening-spec-plan-ru.md),
acceptance rows A-16/A-17). **Snapshot:** 2026-10-21.
**Machine-readable source of truth:** [`.github/package-matrix.yml`](../../.github/package-matrix.yml).

This document answers three questions a release has to answer honestly:

1. **What is a SonoForge release?** The set of assets in the table below, built
   by a named workflow job from a named profile on a named platform.
2. **How is it proven?** A release is confirmed by *running the packaged
   artifact* — not by importing the checkout — and by verifying the published
   bytes against the checksums, SBOMs and build records.
3. **What is not proven?** The gaps at the end of this page. They are part of
   the matrix file as well, so they cannot be forgotten quietly.

---

## 1. Profiles

| | Full | Presenter (lite) |
|---|---|---|
| Entry point | `src/echo_personal_tool/__main__.py` | `src/echo_personal_tool/__main_presenter__.py` |
| Dependencies | `pyproject.toml` runtime set, resolved in `uv.lock` | `build/presenter/pinned-packages.txt` — a lock-verified subset |
| AI segmentation (ONNX, models) | yes | **no** (`onnxruntime` excluded) |
| ASE reference UI / constructor | yes (`PyQt6-WebEngine`, PyMuPDF, openpyxl) | **no** |
| Measurements, Doppler, M-mode, strain, PACS, PDF report | yes | yes |
| Storage | per-user data directory | portable next to the executable (`SONOFORGE_PORTABLE=1`) |
| Build tools | `uv sync --locked --extra build` | pinned lite set + PyInstaller from `uv.lock` |
| Smoke assertion | ONNX/PyMuPDF/openpyxl **present**, reference UI available, portable storage honoured | the same modules **absent**, reference UI hidden, portable storage honoured |

The Presenter pin list is a second dependency list, which is only acceptable
while it provably belongs to the same lock: `tools/release/presenter_pins.py`
runs in CI and in the Presenter build and fails when a pin drifts from
`uv.lock`, names a package outside the project dependency closure, or lets an
excluded package into the lite profile.

## 2. The matrix

Every row is an asset that is published, the job that builds it, how far the
shipped bytes are exercised, and the evidence published beside it.

| Asset (`{version}` = `__version__`) | Profile | Platform | Workflow / job | Kind | Smoke | SBOM | Checksum manifest |
|---|---|---|---|---|---|---|---|
| `sonoforge_{version}_amd64.deb` | Full | linux-amd64 | `release.yml` / `build-linux` | lite `.deb` | payload | `SonoForge-{version}-linux-amd64.sbom.cdx.json` | `SHA256SUMS` |
| `SonoForge-Setup-{version}-x64.exe` | Full | windows-x64 | `release.yml` / `build-windows` | Inno Setup installer | artifact | `SonoForge-{version}-windows-x64.sbom.cdx.json` | `SHA256SUMS` |
| `SonoForge-{version}-portable.exe` | Full | windows-x64 | `release.yml` / `build-windows` | onefile portable | artifact | same SBOM | `SHA256SUMS` |
| `SonoForge-{version}-macos-arm64.dmg` | Full | macos-arm64 | `release.yml` / `build-macos-apple-silicon` | `.dmg` with `.app` | artifact | `SonoForge-{version}-macos-arm64.sbom.cdx.json` | `SHA256SUMS` |
| `sonoforge-{version}.tar.gz` | Full | source | `release.yml` / `build-source` | sdist | none | — | `SHA256SUMS` |
| `SonoForgePresenter-{version}.exe` | Presenter | windows-x64 | `presenter.yml` / `build-windows` | onefile portable | artifact | `SonoForge-Presenter-{version}-windows-x64.sbom.cdx.json` | `SHA256SUMS-presenter.txt` |
| `SonoForge-Presenter-{version}-x86_64.AppImage` | Presenter | linux-x86_64 | `presenter.yml` / `build-linux` | AppImage | artifact | `SonoForge-Presenter-{version}-linux-x86_64.sbom.cdx.json` | `SHA256SUMS-presenter.txt` |

`latest.json` is the fixed-name manifest that resolves the newest versions of
all of the above (main release assets plus the Presenter builds). It lists only
binaries covered by the checksum manifests, and only after their digests were
verified.

**Smoke levels**

* `artifact` — the shipped executable is launched: first launch, a synthetic
  cine, a measurement saved through the real persistence layer, a **second
  process** restoring it from disk, text and PDF export, portable-storage
  boundaries and the profile capabilities of §1.
* `payload` — the files the package installs are executed with the locked
  interpreter (used for the lite `.deb`, whose first run downloads its
  dependencies).
* `none` — source-only asset; there is nothing to launch.

## 3. Dependency policy

One locked toolchain for CI, build, release and Presenter (QH-2a.1 extended by
QH-5a):

* `uv.lock` is the only source of versions; `uv lock --check` runs in the
  `lint` job, `uv sync --locked` in every job that installs Python
  dependencies. `UV_PYTHON_DOWNLOADS=never` keeps the interpreter from
  `setup-python`.
* The packaging toolchain — `pyinstaller`, `pyinstaller-hooks-contrib`,
  `cyclonedx-bom`, `hatchling` — is the `build` extra of the project and is
  resolved from the same lock.
* There is no `pip install -e .` and no floating `pip install <dependency>`
  fallback in the build/release/Presenter/benchmark workflows. A failed locked
  install fails the job; it is never hidden behind an alternative install.
  `tests/unit/test_release_package_matrix.py` enforces this on the workflow
  files.
* Presenter pins are checked against the lock (`tools/release/presenter_pins.py`)
  before the lite environment is built.

## 4. Evidence published with a release

| Evidence | Written by | Contents |
|---|---|---|
| `SHA256SUMS`, `SHA256SUMS-presenter.txt` | release / Presenter release job | digest + published file name for every binary |
| `*.sbom.cdx.json` | each packaging job | CycloneDX 1.6 of the dependency set that was packaged; `metadata.component.version` = package version, deterministic `serialNumber` = `uuid5(NAMESPACE_URL, …/releases/tag/v{version})` |
| `build-record-{profile}-{platform}.json` | `tools/release/build_record.py` in each packaging job | tag/version, source commit/ref, workflow run id/attempt, profile, platform/architecture, Python/Qt/NumPy/ORT/PyMuPDF versions, `uv.lock` SHA-256 + package count, model-manifest hash (or `null`), artifact digests/sizes, smoke evidence status |
| `package-smoke-{profile}-{platform}.json` | `tools/release/run_package_smoke.py` | per-stage checks of the packaged run (and the smoke-test workflow artifact) |
| Sigstore attestations | `actions/attest` | build provenance for every binary, plus a CycloneDX SBOM attestation bound to the same digest |
| `latest.json` | release / Presenter release job | version-bound asset names, sizes, SHA-256 and download URLs |

## 5. Verification of a published release

The workflows verify themselves after publishing: the release job downloads the
published assets back from the release (`gh release download`) and runs

```bash
python tools/release/verify_release.py \
  --dir published --tag v0.3.3 --version 0.3.3 --profile full \
  --latest-json published/latest.json --attestations --json-out release-verification.json
```

which fails the workflow unless all of the following hold:

| Check | What it means |
|---|---|
| `matrix` | every asset the matrix declares for the selected profile is published, and every name carries the version |
| `checksums` | each checksum manifest lists exactly its binaries and every digest matches the downloaded file |
| `sboms` | one CycloneDX 1.6 SBOM per packaged artifact, version-bound, serialNumber derived from the tag, with a non-empty component list |
| `records` | a build record per profile/platform: same tag/version, same `uv.lock` hash as the tagged commit, artifact digests equal to the published bytes, package smoke `pass` for every packaged asset |
| `latest_json` | every entry points at a published file with the listed digest and size, and every checksum-verified binary is listed |
| `attestations` | `gh attestation verify` succeeds for each binary and for its CycloneDX SBOM predicate |

A user or a hospital IT team can reproduce the essential part without the
workflow:

```bash
sha256sum -c SHA256SUMS
gh attestation verify sonoforge_0.3.3_amd64.deb --repo areatu/SonoForge
gh attestation verify sonoforge_0.3.3_amd64.deb --repo areatu/SonoForge \
  --predicate-type https://cyclonedx.org/bom
```

The remaining trust question — *is the publisher who they claim to be* — is the
OS-signature question and belongs to Gate G5b ([`docs/security/code-signing.md`](../security/code-signing.md)).
Unsigned builds stay explicitly unsigned.

## 6. Running the smoke locally

```bash
# the scenario on the checkout (what the required CI job runs)
uv run python tools/release/run_package_smoke.py \
  --runner module --profile full --workdir /tmp/package-smoke

# the scenario on a shipped artifact
uv run python tools/release/run_package_smoke.py \
  --runner artifact --artifact dist/SonoForge/SonoForge.exe --profile full \
  --workdir /tmp/package-smoke --evidence dist/package-smoke-full-windows-x64.json
```

The scenario itself is `echo_personal_tool.application.package_smoke`; the
frozen builds expose it as `<artifact> --package-smoke save|restart|compare`
(see `src/echo_personal_tool/__main__.py` and `__main_presenter__.py`). The
two stages must be two separate processes — that is the restart.

## 7. Declared gaps

The matrix file lists these under `gaps`; they are not covered by a PASS and
must not be read as covered:

* The lite `.deb` downloads its dependencies on first run. Its **payload** is
  smoke-tested against the locked dependency set; the network bootstrap itself
  is not exercised in CI.
* Presenter USB-stick acceptance (owner-run P1–P7, read-only stick behaviour)
  remains a separate acceptance, not an automated check.
* Windows Authenticode, macOS Developer ID/notarization and their verification
  on published assets are **Gate G5b** and stay **Blocked** until a signing
  provider, owner and key custody exist. Current artifacts are unsigned
  (macOS carries only the ad-hoc signature PyInstaller applies).
* Clinical/regulatory acceptance is outside this document.

## 8. Changing the matrix

Adding, renaming or dropping a published asset is a three-file change:

1. `.github/package-matrix.yml` — the asset row (name, profile, platform,
   job, smoke level, SBOM, manifest) and, if new, the manifest/SBOM naming.
2. the packaging workflow — build it, smoke it, write the build record, attest
   it, upload it;
3. this document and its Russian twin.

`tests/unit/test_release_package_matrix.py` fails when the matrix contradicts
itself, when a packaging workflow drops the lock, the pin check or the smoke,
or when a documented build record is not written by the workflows — so the
documentation cannot drift away from what is published.
