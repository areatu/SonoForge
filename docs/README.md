# Documentation

> [Русская версия](README_RU.md)

Technical documentation, specs, and implementation plans.

## Structure

| Folder | Description |
|--------|-------------|
| `superpowers/specs/` | Technical feature specs (STE, DICOMweb/DIMSE, lazy loading, M-Mode, ONNX segmentation, reference browser, etc.) |
| `reviews/` | Code and design reviews |
| `screenshots/` | Application screenshots for documentation; `screenshots/ste_references/` — vendor references (images are not committed, see `.gitignore`) |

> Local (not committed, see `.gitignore`): `superpowers/plans/` — sprint plans,
> `compose/` — compose workflow documentation, `bench/` — benchmark notes.
> Links to them from other documents only resolve in local checkouts.

## User help

| File | Description |
|------|-------------|
| [`HELP_EN.md`](HELP_EN.md) | English user help covering the current UI, local/server data, measurements, calibration, references, settings, export, shortcuts, and troubleshooting |
| [`HELP_RU.md`](HELP_RU.md) | Extended Russian help for the actual SonoForge implementation: local and server data, measurements, calibration, references, settings, export, shortcuts, and diagnostics |
| [`TECHNICAL_HELP_EN.md`](TECHNICAL_HELP_EN.md) | English technical help: formulas, source chain, calibration, Settings effects, and DICOMweb/DIMSE/PACS protocols |
| [`TECHNICAL_HELP_RU.md`](TECHNICAL_HELP_RU.md) | Russian technical help: formulas, value sources, calibration, Settings effects, and DICOMweb/DIMSE/PACS protocols |

## Security and release integrity

| File | Description |
|------|-------------|
| [`security/data-inventory.md`](security/data-inventory.md) | Data inventory and mapping to selected security expectations |
| [`security/code-signing.md`](security/code-signing.md) | Code signing and release verification: signing status per platform, `SHA256SUMS` and build-provenance attestation checks, options and costs, and the project code signing policy |

See also [`../SECURITY.md`](../SECURITY.md).

## Standalone documents

| File | Description |
|------|-------------|
| [`superpowers/specs/2026-10-01-multiview-two-clips-spec-ru.md`](superpowers/specs/2026-10-01-multiview-two-clips-spec-ru.md) | Russian specification for two-clip multiview, event markers, and cycle-synchronized playback |
| `STE_IMPROVEMENT_PLAN.md` | Plan for bringing the STE module to commercial quality (rev.4, current; §5.2 — implementation status) |
| `STE_TRACKING_VERIFICATION.md` | STE tracking verification |
| `STE_VENDOR_REFERENCE.md` | Vendor STE reference values (Samsung RS85, Philips EPIQ) |
| `speckle_tracking_analysis.md` | Measurement analysis of the current STE tracking (diagnostics) |
| `dicom_parcer_advanced.md` | Advanced DICOM tag parsing |
| `DICOM_VTI_tag_fix.md` | VTI tag fix |
| `doppler_baseline_samsung.md` | Samsung Doppler baseline parameters |
| `outlier_rejection.md` | Outlier rejection |
| `web_reference_review.md` | Review of the web reference viewer |
| `new_reference_parameters.yaml` | New reference parameters (vessels, thyroid, kidneys, etc.) with verified sources |

Data and everything related to it are described in [`../data/README.md`](../data/README.md).
