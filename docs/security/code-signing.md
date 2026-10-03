# Code Signing and Release Verification

**Snapshot:** 2026-10-03
**Scope:** every artifact published on
[GitHub Releases](https://github.com/areatu/SonoForge/releases) — Windows setup/portable
executables, the Linux `.deb`, the macOS Apple Silicon `.dmg`, the source tarball, the
Presenter onefile `.exe` and AppImage, the CycloneDX SBOMs, and the checksum manifests.
**Purpose:** states what is and is not cryptographically guaranteed about a SonoForge
download today, how a user or a hospital IT/security team can verify one, and what the
signing options are per platform. This is a policy and status document, not a conformity
assessment.

---

## 1. Current state

| Guarantee | Mechanism | Status |
|---|---|---|
| The file was not altered in transit or after upload | `SHA256SUMS` (main release) and `SHA256SUMS-presenter.txt` (Presenter assets) | ✅ In place |
| The file was built by a workflow in `areatu/SonoForge`, from a known commit, on a known ref | GitHub **artifact attestations** — SLSA build provenance, signed with a short-lived Sigstore/Fulcio certificate via `actions/attest@v4` | ✅ In place — see [§3.2](#32-build-provenance-attestation-recommended) |
| What components the file contains, and that this list belongs to *that* file | **CycloneDX 1.6 SBOM** per platform, published as a release asset and bound to the artifact by a second Sigstore attestation | ✅ In place — see [§3.4](#34-software-bill-of-materials-sbom) |
| The checksum manifest was published by the project's own key, not just by whoever can edit the release | GPG detached signature `SHA256SUMS.asc` | ⚠️ **Implemented, dormant** — published only once the `GPG_PRIVATE_KEY` secret exists, see [Enabling GPG signing](#enabling-gpg-signing) |
| The published name identifies the version | Version in every asset name, fixed names kept as byte-identical aliases | ✅ In place — see [Asset naming](#asset-naming-and-version-binding) |
| The publisher identity is validated by a public CA and shown by the OS ("Verified publisher") | Authenticode (Windows), Developer ID + notarization (macOS), distribution signing (Linux) | ❌ **Not in place** — unsigned builds |

Consequences of the unsigned state:

- **Windows** — SmartScreen shows *"Windows protected your PC"* / **Unknown publisher** on
  first run of the setup and portable executables. Some enterprise environments
  (AppLocker / WDAC / "block unsigned" policy) will not run the binary at all. PyInstaller
  `onefile` builds also attract antivirus false positives, which signing reduces but does
  not eliminate.
- **macOS** — Gatekeeper reports that the app *"cannot be opened because Apple cannot check
  it for malicious software"*. On Apple Silicon a signature is mandatory to execute at all,
  so the build carries a local **ad-hoc** signature applied by PyInstaller
  (`codesign_identity=None` in the `.spec` files). That ad-hoc signature satisfies the
  arm64 loader but is not a Developer ID and is not notarized, so Gatekeeper still blocks
  first launch until the user overrides it.
- **Linux** — no OS-level signing gate. `.deb` and AppImage run without a signature;
  distributions only enforce signatures on packages coming from a **repository** (`apt`),
  not on a file the user downloads.

---

## 2. What each platform actually requires

### Windows — Authenticode

A code-signing certificate chained to a CA in the **Microsoft Trusted Root Program**,
applied with `signtool` plus an RFC 3161 timestamp.

Important, and frequently misunderstood: **signing does not silence SmartScreen on its
own.** Since Microsoft removed the EV instant-reputation behaviour in 2024, *every*
certificate class — OV, EV, and Microsoft's own **Azure Artifact Signing** (the service
formerly called *Trusted Signing*) — builds reputation over time. A brand-new signed file
can still show a warning. What signing buys you is:

1. a named publisher instead of "Unknown publisher";
2. reputation that **carries across releases** via the certificate (an unsigned binary
   only ever has per-file-hash reputation, so every release starts from zero);
3. eligibility for enterprise allow-listing policies.

There is no free publicly trusted Authenticode certificate. Realistic options, cheapest
first:

| Option | Cost | Eligibility | Publisher shown | Notes |
|---|---|---|---|---|
| **Microsoft Store, MSIX package** — the Store re-signs the package | Free | Worldwide | Store publisher identity | Individual developer registration became free in Sept 2025 (no credit card; company accounts still one-time $99), and MSIX submitted to the Store is signed by Microsoft — no SmartScreen warnings, and `winget` can point at the Store package. **The only genuinely free path to a warning-free Windows install**, but it requires real repackaging work: an MSIX container virtualizes `%LOCALAPPDATA%`, so
the Z2/Z3/Z5 storage zones and the per-user install layout from WP1 would need
re-validation, and the payload is large (the current onefile exe is ~370 MB, the onedir
install comparable). |
| **Microsoft Store, Win32 EXE/MSI** ("all app types welcome, no code changes") | Free registration | Worldwide | Your publisher identity | Free to *register and submit*, but Microsoft requires the installer itself to carry a signature chaining to a Trusted Root Program CA — the Store does **not** re-sign Win32 payloads. So this removes no certificate cost; it only adds a distribution channel. |
| **SignPath Foundation** (free OSS program) | Free | Qualifying open-source projects | `SignPath Foundation` | See [§4](#4-recommended-plan). OV-level Sectigo certificate, private key held in SignPath's HSM, signing happens in CI. Manual approval per release. |
| **Certum "Open Source Code Signing"** | ~€49/yr (cloud, SimplySign) or ~€69 one-off set with a smart card | Any verified natural person; the certificate reads *"Open Source Developer, \<name\>"* | Your personal name | Cheapest certificate you can own outright. Needs identity verification (ID + proof of address + a link proving you are the project author). Cloud variant works from CI without a physical token. |
| **Azure Artifact Signing** (ex-Trusted Signing) | $9.99/mo Basic (5 000 signatures), $99.99/mo Premium | Organizations: US, CA, EU, UK. **Individuals: US and CA only** | Your validated name/org | Best CI ergonomics (native GitHub Actions integration, no token). No instant SmartScreen trust. Not free. |
| OV certificate from DigiCert / Sectigo / SSL.com / GlobalSign | ~$150–300/yr | Worldwide, individuals and orgs | Your validated name | Functionally equivalent to Azure Artifact Signing for SmartScreen purposes. |
| EV certificate | $400+/yr | Worldwide | Your validated name | **No longer recommended for SmartScreen** — the instant-reputation benefit was removed in 2024. Still required only for kernel-mode driver signing. |
| Self-signed certificate | Free | — | — | Actively harmful: strong SmartScreen block for anyone who has not imported the root. Dev/test only. |

A free supplementary step regardless of choice: submit each release to the
[Microsoft Security Intelligence portal](https://www.microsoft.com/en-us/wdsi/filesubmission)
as a software developer with the SHA-256 and download URL. If analysts confirm the file is
clean, Microsoft can adjust its reputation ahead of the organic curve. It is a review, not
a guarantee.

### macOS — Developer ID + notarization

There is **no free path**. Notarization requires a Developer ID certificate, which
requires paid **Apple Developer Program** membership ($99/yr, individual or organization).
Apple's fee waiver exists only for eligible *non-profit, educational, or government
organizations* — not for individual open-source developers. Notarization is a hard
requirement for Gatekeeper-clean distribution outside the Mac App Store since Catalina,
and since Sequoia the right-click→Open workaround has been removed for unsigned apps on
Apple Silicon; the user must go to **System Settings → Privacy & Security → Open Anyway**,
or clear the quarantine attribute:

```bash
xattr -dr com.apple.quarantine /Applications/SonoForge.app
```

Options, in order of practicality for an unfunded project:

1. **Ship unsigned + document the override** (current state). Free. Must be stated clearly
   on the download page — a first-run Gatekeeper block on a clinical tool is a support and
   trust problem, not just an inconvenience.
2. **One paid Apple Developer membership ($99/yr)** shared with the project, if/when there
   is any funding or a maintainer willing to absorb it. This is the *only* thing that makes
   macOS behave like a normal download: `codesign --options runtime` + hardened runtime
   entitlements → `xcrun notarytool submit --wait` → `xcrun stapler staple` on both the
   `.app` and the `.dmg`. Roughly 20 lines of CI plus three secrets
   (`MACOS_CERT_P12_BASE64`, `MACOS_CERT_PASSWORD`, `AC_NOTARY_*` app-specific password or
   App Store Connect API key).
3. **Ask a registered developer to sign and notarize** the build. Free, but the signing
   identity then vouches for the artifact and the chain of custody has to be documented;
   not recommended for a medical-adjacent tool.
4. **Drop the macOS binary and publish source/pip instructions only.** Free, honest, and
   removes an expectation the project cannot currently meet. Revisit when there is funding.

Note that macOS signing is unrelated to Sigstore/attestations: an attestation proves
provenance but Gatekeeper ignores it entirely.

### Linux — nothing is required, but something is cheap

No distribution enforces a signature on a downloaded `.deb` or AppImage. The genuinely
useful, free additions are:

- **GPG-sign the `SHA256SUMS` manifest** and publish the key fingerprint in the repository
  and on the project site (`SHA256SUMS.asc`). This upgrades the manifest from
  "self-asserted" to "signed by a key you can pin", and is the conventional expectation for
  Linux users. Cost: one GPG key, kept offline or on a hardware token; the CI signing step
  needs the private key as a secret — which is the one thing attestations avoid.
  **Implemented and dormant**: `release.yml` signs and publishes `SHA256SUMS.asc` as soon as
  the `GPG_PRIVATE_KEY` secret exists, and skips with a workflow notice when it does not.
  See [Enabling GPG signing](#enabling-gpg-signing).
- **Attestations** (already in place) cover the same ground without any key management,
  and are arguably stronger: they bind the artifact to a specific workflow run and commit
  rather than to a key that could be used to sign anything.
- Repository signing only becomes relevant if SonoForge is ever published through an `apt`
  repository, Flathub, Snap, or AUR — each of those has its own, free, key-based review and
  signing process, and each also gives users a signed install path with no key handling on
  their side. **Flathub is the highest-value free Linux channel**: it verifies the build
  against upstream sources and users get updates through their software centre.

### Asset naming and version binding

Attestation verification is **digest-keyed and file-name-agnostic** (§3.2), so an asset
named without a version cannot be tied to a release by its attestation alone. Every
published artifact therefore carries a versioned name; fixed names survive only as
byte-identical aliases for existing download URLs and README instructions.

| Artifact | Canonical (versioned) name | Alias kept for compatibility |
|---|---|---|
| Windows installer | `SonoForge-Setup-<version>-x64.exe` | — |
| Windows portable | `SonoForge-<version>-portable.exe` | `SonoForge.exe` |
| Linux package | `sonoforge_<version>_amd64.deb` | — |
| macOS disk image | `SonoForge-<version>-macos-arm64.dmg` | `SonoForge-macos-arm64.dmg` |
| Source | `sonoforge-<version>.tar.gz` | — |
| Presenter (Windows) | `SonoForgePresenter-<version>.exe` | `SonoForgePresenter.exe` |
| Presenter (Linux) | `SonoForge-Presenter-<version>-x86_64.AppImage` | — |
| SBOM | `SonoForge-<version>-<platform>.sbom.cdx.json`, `SonoForge-Presenter-<version>-<platform>.sbom.cdx.json` | — |
| Checksums | `SHA256SUMS`, `SHA256SUMS-presenter.txt` | — |

An alias shares its canonical file's digest byte-for-byte, so it resolves through the same
attestation and is deliberately **not** attested twice. The macOS and Presenter build steps
assert that equality (`cmp` / `Get-FileHash`) before upload, so an alias can never drift
away from the file the attestation actually covers.

Presenter assets are published by `presenter.yml`, a separate workflow, which is why they
have their own `SHA256SUMS-presenter.txt`: the main `SHA256SUMS` is generated by
`release.yml` before the Presenter workflow attaches anything, and never listed them.

---

## 3. Verifying a download

### 3.1 Checksums (works everywhere, no tooling)

```bash
curl -LO https://github.com/areatu/SonoForge/releases/latest/download/SHA256SUMS
sha256sum -c SHA256SUMS --ignore-missing
```

`--ignore-missing` is required, not optional: the manifest lists both the versioned asset
and its fixed-name alias, and you will normally have downloaded only one of them.

Presenter assets are covered by a separate manifest, because they are published by a
different workflow:

```bash
curl -LO https://github.com/areatu/SonoForge/releases/latest/download/SHA256SUMS-presenter.txt
sha256sum -c SHA256SUMS-presenter.txt --ignore-missing
```

On Windows (PowerShell):

```powershell
Get-FileHash .\SonoForge-Setup-<version>-x64.exe -Algorithm SHA256
# compare against the line in SHA256SUMS
```

This proves the file matches what the release workflow published. It does **not** by itself
prove who published it — anyone who could replace the release assets could also replace the
manifest. That gap is what attestations close.

When a GPG key is configured, the manifest additionally carries a detached signature:

```bash
gpg --recv-keys <FINGERPRINT>          # once; fingerprint published in this file and on the project site
gpg --verify SHA256SUMS.asc SHA256SUMS
sha256sum -c SHA256SUMS --ignore-missing
```

**GPG key fingerprint:** _not yet configured_ — see
[Enabling GPG signing](#enabling-gpg-signing). Until a key exists, `SHA256SUMS.asc` is not
published and the attestation in §3.2 is the authenticity check to rely on.

### 3.2 Build provenance attestation (recommended)

Every release asset is attested with
[`actions/attest`](https://github.com/actions/attest): a SLSA build-provenance statement,
signed with a short-lived Sigstore/Fulcio certificate minted from the workflow's OIDC
identity, and recorded in GitHub's attestation store and the public Rekor transparency log.
No project key exists to steal or rotate.

> `actions/attest-build-provenance` — the action this is usually introduced by — is, from
> version 4, simply a wrapper around `actions/attest`; its own README says new
> implementations should use `actions/attest` directly. This project uses `actions/attest@v4`
> so that provenance and SBOM attestations come from one action.

With [GitHub CLI](https://cli.github.com/) ≥ 2.60 and `gh auth login` completed:

```bash
gh attestation verify SonoForge-Setup-<version>-x64.exe --repo areatu/SonoForge
```

Expected output includes:

```text
Build repo:      areatu/SonoForge
Build workflow:  .github/workflows/release.yml@refs/tags/v<version>
```

Tighten the policy for a deployment gate — restrict *which* workflow may have produced the
artifact, so that a signature minted by any other workflow in the repository is rejected:

```bash
gh attestation verify SonoForge-Setup-<version>-x64.exe \
  --repo areatu/SonoForge \
  --signer-workflow areatu/SonoForge/.github/workflows/release.yml
```

Presenter artifacts are built by a different workflow:

```bash
gh attestation verify SonoForgePresenter-<version>.exe \
  --repo areatu/SonoForge \
  --signer-workflow areatu/SonoForge/.github/workflows/presenter.yml
```

**What attestation does and does not prove.**

- It proves the artifact's SHA-256 digest was produced by a run of the named workflow in
  `areatu/SonoForge`, and the provenance statement records the source ref and commit.
- Verification is **digest-keyed and file-name-agnostic**. `gh` recomputes the hash of the
  local file and looks up attestations for that digest; the file name is not checked. Two
  consequences:
  - `SonoForge.exe`, `SonoForge-macos-arm64.dmg` and `SonoForgePresenter.exe` (the
    fixed-name compatibility aliases) are byte-identical copies of their versioned
    counterparts and therefore verify through the canonical artifact's attestation without
    needing one of their own.
  - An attestation alone does not pin a *version*. A genuine artifact from an older release
    also verifies. Two defences are in place: every canonical asset name carries the version
    (§2, [Asset naming](#asset-naming-and-version-binding)), and the `Build workflow` line
    in the verification output shows the tag the artifact was built from — check it against
    the release you intended. Verifying the version-carrying `SHA256SUMS` first and then
    matching digests closes it completely.
- It is **not** an OS trust signal. SmartScreen and Gatekeeper do not consult it.
- `gh attestation verify` requires an authenticated `gh` session; an unauthenticated
  `gh` fails with an auth error, which must not be misread as a forged release.

### 3.3 Where attestations are generated

| Workflow | Job | Provenance subject(s) | SBOM subject(s) |
|---|---|---|---|
| `.github/workflows/release.yml` | `build-source` | `dist/*.tar.gz` | — |
| | `build-linux` | `dist/sonoforge_*.deb` | same, + `SonoForge-<v>-linux-amd64.sbom.cdx.json` |
| | `build-windows` | `dist/SonoForge-Setup-*-x64.exe`, `dist/SonoForge-*-portable.exe` | same, + `SonoForge-<v>-windows-x64.sbom.cdx.json` |
| | `build-macos-apple-silicon` | `dist/SonoForge-*-macos-arm64.dmg` | same, + `SonoForge-<v>-macos-arm64.sbom.cdx.json` |
| | `release` | `SHA256SUMS` | — |
| `.github/workflows/presenter.yml` | `build-windows` | `dist/SonoForgePresenter-*.exe` | same, + `SonoForge-Presenter-<v>-windows-x64.sbom.cdx.json` |
| | `build-linux` | `dist/SonoForge-Presenter-*-x86_64.AppImage` | same, + `SonoForge-Presenter-<v>-linux-x86_64.sbom.cdx.json` |
| | `release` | `SHA256SUMS-presenter.txt` | — |

Attestations are created in the job that *produces* the artifact, so the provenance
statement describes the real build rather than a later repackaging step. Both workflows
carry `permissions: { id-token: write, attestations: write }` (`artifact-metadata: write`
is **not** needed — it applies only to OCI storage records with `push-to-registry`).

Fixed-name aliases (`SonoForge.exe`, `SonoForge-macos-arm64.dmg`,
`SonoForgePresenter.exe`) are deliberately absent from the subject globs: they are
byte-identical to their canonical counterparts and would only duplicate the attestation
under a second name.

### 3.4 Software bill of materials (SBOM)

Each platform build emits a **CycloneDX 1.6 JSON** SBOM, published as a release asset and
bound to its artifact by a second Sigstore attestation (predicate type
`https://cyclonedx.org/bom`). Provenance says *how* the file was built; the SBOM says *what
is inside it* — which is what clinical procurement and vulnerability response actually ask
for.

Generation differs by profile:

| Build | SBOM source | Why |
|---|---|---|
| Main app (`.deb`, Windows, macOS) | `cyclonedx-py environment` over the build job's Python environment, with `--pyproject pyproject.toml` naming the root component | That environment is exactly what PyInstaller bundles |
| Presenter (`.exe`, AppImage) | `cyclonedx-py requirements build/presenter/pinned-packages.txt` | The lite profile is fully pinned, so the SBOM is exact and reproducible |

Both use `--output-reproducible`, so a given environment always yields a byte-stable SBOM.

Verify the SBOM belongs to the artifact you hold:

```bash
gh attestation verify SonoForge-Setup-<version>-x64.exe \
  --repo areatu/SonoForge \
  --predicate-type https://cyclonedx.org/bom
```

Inspect it with any CycloneDX tooling, e.g. `syft`'s consumer `grype` for known
vulnerabilities, or `cyclonedx-py`/`cyclonedx-cli` for a component list.

Two honest caveats:

- **`--spec-version 1.6` is pinned deliberately.** `actions/attest` sniffs the SBOM and
  rejects CycloneDX **1.7** with `Unsupported SBOM format` as of v4.2.2, while
  `cyclonedx-py`'s default tracks the newest spec. Bumping the flag without checking the
  action's supported range will break the release.
- **The main-app SBOMs are generated from the build environment**, so they also list build
  tooling (`pip`, `setuptools`, `pyinstaller`, `cyclonedx-bom`) alongside the runtime
  components. Filter on component scope or PURL when consuming them. The Presenter SBOMs do
  not have this noise, because they are derived from the pinned runtime list.

---

## 4. Recommended plan

Ordered by cost, and deliberately free-first:

| # | Action | Cost | Status / effect |
|---|---|---|---|
| 1 | Build-provenance attestations + `SHA256SUMS` + documented `gh attestation verify` | Free | ✅ **Done.** Cryptographic provenance with no key management. |
| 2 | Version in **every** asset name, fixed names kept as byte-identical aliases | Free | ✅ **Done.** Attestations are name-agnostic; version-carrying names are what make verification version-specific. |
| 3 | Attested CycloneDX SBOM per platform, published as a release asset | Free | ✅ **Done.** Increasingly requested in clinical procurement; says *what is inside*, not just *how it was built*. |
| 4 | Checksum manifest for Presenter assets (`SHA256SUMS-presenter.txt`) | Free | ✅ **Done.** Presenter binaries were previously in no manifest at all. |
| 5 | GPG-sign `SHA256SUMS`, publish the fingerprint | Free (one key to protect) | 🟡 **CI ready, key missing.** Signs automatically once `GPG_PRIVATE_KEY` exists — see [Enabling GPG signing](#enabling-gpg-signing). |
| 6 | Submit each release to the Microsoft Security Intelligence portal | Free | ⬜ Manual per release. Reduces SmartScreen/AV false-positive duration, especially for PyInstaller `onefile`. |
| 7 | Apply to **SignPath Foundation** | Free | ⬜ Blocked on reputation — see [Honest constraint](#honest-constraint-on-the-signpath-step). Removes *Unknown publisher* on Windows. |
| 8 | Publish to **winget** and/or **Flathub** | Free | ⬜ Signed install path through channels users already trust. Requirements in [Distribution channels](#distribution-channels-winget--flathub--microsoft-store). |
| 9 | Certum Open Source Code Signing | ~€49/yr | ⬜ Fallback only if step 7 is rejected. Own-name Authenticode, usable from CI via SimplySign cloud. |
| 10 | Apple Developer Program | $99/yr | ⬜ The only fix for macOS Gatekeeper. Defer until funded or a macOS user base justifies it. |

Explicitly **not** recommended: an EV certificate (the SmartScreen benefit was removed in
2024, so it is pure cost), and Azure Artifact Signing (paid, and individual onboarding is
limited to the US and Canada).

### Enabling GPG signing

The `release.yml` job `release` already contains the signing step. It is gated on a
repository secret and publishes a workflow **notice** (not a failure) when the secret is
absent, so releases are unaffected until a key is provisioned.

To activate:

1. Generate a signing key. RSA 3072 or Ed25519, with a signing-capable subkey. Keep the
   primary key offline; export only what CI needs.
2. Add repository secrets (**Settings → Secrets and variables → Actions**):
   - `GPG_PRIVATE_KEY` — the ASCII-armored private key block, including
     `-----BEGIN PGP PRIVATE KEY BLOCK-----` and trailing newline.
   - `GPG_PASSPHRASE` — only if the exported key is passphrase-protected. Leave unset for an
     unencrypted CI key; the step adapts (`--pinentry-mode loopback` is added only when a
     passphrase exists).
3. Publish the fingerprint in [§3.1](#31-checksums-works-everywhere-no-tooling) of this
   file, on the project site, and ideally in a `KEYS` file, so users can pin it out of
   band. A fingerprint only published next to the signature it validates is worthless.
4. Upload the public key to a keyserver (`keyserver.ubuntu.com`) so `gpg --recv-keys` works.

Trade-off worth stating plainly: this introduces a long-lived private key into CI, which is
exactly the risk class attestations were adopted to avoid. The signature is worth it for
users who have no `gh` and for the conventional Linux expectation, but if the key is ever
exposed it must be revoked and the fingerprint re-published — and every user who pinned the
old one has to be told. Do not add the key until someone owns that rotation.

### Distribution channels: winget, Flathub, Microsoft Store

All three are free and none of them requires the project to own a certificate, but each has
a different relationship to signing.

**winget (`microsoft/winget-pkgs`).** There is **no signing rule** — unsigned installers are
accepted, and many OSS packages ship that way. What to expect anyway:

- The validation pipeline runs AV / Defender / SmartScreen scans. An unsigned publisher can
  produce `SmartScreen-Validation-Error` ("the URL you provided has a bad reputation") or
  `Validation-Executable-Error`, which typically clears only as publisher reputation builds.
  Plan for a slow or stalled first PR, not a fast one.
- **The first submission of a new package must be a manual new-package PR** reviewed by a
  moderator. Only subsequent version updates can be automated.
- Automation needs `WINGET_TOKEN`: a **classic** PAT with `public_repo` scope, from an
  account holding a **fork of `microsoft/winget-pkgs`**. Tooling: Microsoft's `wingetcreate`
  or `vedantmgoyal9/winget-releaser` (komac). The job must skip cleanly when the secret is
  absent, and must not fail the release.
- Installer hashes should be taken from the published `SHA256SUMS`, not recomputed from a
  re-downloaded file.
- Manifests are not generated in this repository yet: they cannot be validated here
  (`winget validate` needs Windows and the package does not exist in winget), and generating
  three YAML files that no one has run is worse than not having them. Create them with
  `wingetcreate` at first submission.

**Flathub.** The highest-value free Linux channel: Flathub verifies the build against
upstream sources and users get a signed install path plus updates through their software
centre, with no key handling on their side. The cost is conformance work, not money — a
Flathub manifest, an appdata/metainfo XML, and adapting to the Flatpak sandbox. Note that
sandboxing conflicts with parts of SonoForge's model: outbound DICOM/DICOMweb to arbitrary
user-configured hosts needs `--share=network` and socket permissions, the 20 GiB Orthanc
cache needs real filesystem access rather than the sandbox's `~/.var/app` view, and the
portable USB-stick Presenter profile is not a Flatpak shape at all. Scope Flathub for the
main app only.

**Microsoft Store.** See the Windows options table. MSIX is the only free path to a
warning-free install because the Store signs the package; Win32 EXE/MSI submissions are free
to *register* but Microsoft requires the installer itself to carry a Trusted Root Program
signature, which removes none of the certificate cost.

### Honest constraint on the SignPath step

SignPath Foundation states that for *executable programs that may be downloaded and
executed* (as opposed to developer libraries) it requires **"a certain verifiable
reputation"**. As of this snapshot `areatu/SonoForge` has seven releases since June 2026
but single-digit download counts and one star, which is not yet the profile that gets
approved. What does help, and is already present: an OSI license (GPL-3.0) with no
commercial dual-licensing, a public CI-built release pipeline, a Zenodo DOI and
`CITATION.cff`, documented functionality, and a published code-signing policy (§5).

So the practical order is: steps 1–4 are shipped, activate step 5 when someone owns key
rotation, do steps 6 and 8 as they become worth the effort, let a few releases accumulate
real download numbers and community signals, then submit the OSS Request Form
(`https://signpath.org/assets/OSSRequestForm-v4.xlsx`, application at
<https://signpath.org/apply>). The application is identity-bound and must be filed by a
maintainer; it cannot be automated, and MFA must be enabled on every maintainer's GitHub
account beforehand. Expect the publisher name shown by Windows to be
**"SignPath Foundation"**, not "SonoForge", and expect a manual approval per release.
SignPath signs **Windows artifacts only** — it does not help with macOS notarization.

Two SignPath conditions this project must respect once approved, both of which the current
pipeline satisfies: signed binaries must be built from source **in a verifiable way** (CI
only, never a laptop build), and all signed binaries must carry **enforced file metadata** —
product name set to the project name and a product version identical in every build. The
second one was checked rather than assumed: the PyInstaller specs embedded no PE version
resource at all and the macOS bundle version was a hardcoded literal that had drifted
behind `__version__`, both now derived from it and covered by
`tests/unit/test_build_version_metadata.py` (see [§5](#5-code-signing-policy)).

### Sequencing note

The attestation and SBOM steps fail the job if Sigstore/Fulcio or Rekor is unavailable,
which would block a release. That is deliberate: publishing unattested assets silently would
defeat the control. If an outage ever blocks a release, re-run the workflow rather than
disabling the step. The GPG step is the exception — it degrades to a notice, because it is a
convenience layer on top of a mechanism (attestation) that is already stronger.

---

## 5. Code signing policy

*This section is the artifact SignPath Foundation requires on the project home page. It is
written now so the application can be submitted as soon as the project has the release
history and reputation the program asks for; the wording about SignPath takes effect only
if the application is approved.*

**Status: no third-party code-signing certificate is currently used. No Windows or macOS
artifact published by this project is signed with a publicly trusted certificate.**

- **Official source.** The only official repository is
  <https://github.com/areatu/SonoForge>. The only official download location is
  <https://github.com/areatu/SonoForge/releases>. Binaries are not redistributed through
  third-party download sites.
- **What is signed.** Today: nothing with a CA certificate. Every release asset carries a
  Sigstore build-provenance attestation and an attested CycloneDX SBOM (§3.4), and is listed
  in a checksum manifest (`SHA256SUMS`, plus `SHA256SUMS-presenter.txt` for Presenter
  assets). If/when a certificate is obtained, the signed set will be the canonical versioned
  Windows artifacts — `SonoForge-Setup-<version>-x64.exe`,
  `SonoForge-<version>-portable.exe`, `SonoForgePresenter-<version>.exe` — and the
  fixed-name aliases `SonoForge.exe` / `SonoForgePresenter.exe`, which are byte-identical to
  them.
- **Where signing happens.** Only in the GitHub Actions release workflows, from a tagged
  commit of this repository. No artifact is ever signed from a local or manual build. Any
  private key or signing credential lives in a CI secret or a provider HSM and never on a
  maintainer workstation.
- **File metadata is set and derived, not hardcoded.** Windows executables carry a PE
  version resource (`ProductName`, `ProductVersion`, `FileVersion`, `CompanyName`,
  `OriginalFilename`, `LegalCopyright`) generated by
  [`scripts/pyinstaller_version.py`](../../scripts/pyinstaller_version.py) from `__version__`,
  and the Inno Setup installer sets the matching `VersionInfo*` attributes. The macOS bundle
  takes `CFBundleShortVersionString` / `CFBundleVersion` from the same source. This is what
  makes "one product name, one product version per build" enforceable instead of
  aspirational — a signing provider requires it, and it was previously unmet: the specs
  embedded no version resource at all, and the macOS bundle version was a hardcoded literal
  that had drifted behind `__version__`.
- **Reproducibility and provenance.** Builds are produced from the public source tree; the
  attestation records the workflow file, the source ref, and the commit. SBOMs are generated
  with `--output-reproducible`, so a given environment always yields a byte-stable document.
- **Team roles.**
  - *Authors* (may modify the repository without additional review): the project
    maintainers with write access to `areatu/SonoForge`.
  - *Reviewers*: every change proposed by a non-maintainer (pull request) is reviewed by a
    maintainer before merge.
  - *Approvers*: a release is published, and any signing request approved, only by a
    maintainer.
  - All maintainers use multi-factor authentication for GitHub and for any signing
    provider.
- **Bundled upstream binaries.** Third-party components (PySide6/Qt, Python runtime, ONNX
  Runtime, OpenCV, PyMuPDF, and similar wheels) are included as-is from their published,
  upstream-signed packages and are **not** re-signed under this project's identity. They are
  enumerated in the published SBOM, so what is bundled is inspectable without unpacking the
  binary. AI segmentation models are downloaded at first run and are SHA-256 verified against
  the packaged manifest before loading; they are not part of the release artifacts and
  therefore not covered by the release attestations.
- **Privacy.** SonoForge does not transmit any information to networked systems unless the
  user explicitly requests it (opening a configured PACS/DICOMweb endpoint, sending a study
  to a server the user selected, or downloading AI models). There is no telemetry, no crash
  reporting, and no analytics. See [`SECURITY.md`](../../SECURITY.md) and
  [`data-inventory.md`](data-inventory.md).
- **Attribution (applies only once approved).** Free code signing provided by SignPath.io,
  certificate by SignPath Foundation.

---

## 6. Related

- [`SECURITY.md`](../../SECURITY.md) — data zones, safeguards, and known limitations.
- [`data-inventory.md`](data-inventory.md) — where data lives and who is responsible.
- [`.github/workflows/release.yml`](../../.github/workflows/release.yml) — release build,
  SBOM, checksum, GPG signing and attestation jobs.
- [`.github/workflows/presenter.yml`](../../.github/workflows/presenter.yml) — Presenter
  portable build, SBOM, checksum and attestation jobs.
- [`scripts/pyinstaller_version.py`](../../scripts/pyinstaller_version.py) — derives the Windows
  PE version resource and the macOS bundle version keys from `__version__`.
- [`tests/unit/test_build_version_metadata.py`](../../tests/unit/test_build_version_metadata.py)
  — guards the version-metadata wiring against drifting back to hardcoded values.
- [`docs/superpowers/specs/2026-10-01-persistence-packaging-security-plan.md`](../superpowers/specs/2026-10-01-persistence-packaging-security-plan.md)
  — WP1 packaging decisions; item 1.6 tracked Authenticode signing as a separate
  organizational task. This document supersedes that placeholder.
