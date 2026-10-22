# STE reference interfaces (internal materials)

> [Русская версия](README_RU.md)

This folder holds **local** screenshots of vendor STE packages, used only as visual
references during UI development (see `docs/STE_IMPROVEMENT_PLAN.md`, appendix F).

## Contents

| File | Source | What it shows |
|------|--------|---------------|
| `ge_echopac_afi_gls_curves_bullseye.jpg` | GE EchoPAC AFI (Global Longitudinal Strain) | 2×2 layout `4CH/2CH/APLAX/bull's eye`, segment curves with a labeled legend, AVC line, ECG strip with tick markers, 17-segment "Peak Systolic Strain" bullseye, 20/0/−20 colorbar, `6LPS_LAX/A4C/A2C/Avg` rows |
| `philips_epiq_autostrain_3views_bullseye_strain_ttp.jpg` | Philips AutoStrain LV (EPIQ CVx, marketing material) | Three views in a row with endo/mid/epi lines, ECG under each view, `Endo/Mid/LV Length` layer toggle, `GLS Endo Peak A4C/A2C/A3C/Avg` rows, two 18-segment bullseyes (strain and time-to-peak) with a colorbar |

## Legal status

The materials belong to their respective manufacturers and are provided solely for
internal comparison. The image files are **excluded from Git** (see `.gitignore`) — only
this README is committed. Do not distribute in external publications, presentations, or
product builds.

## What is missing here (see §11.2 of the plan)

1. **Samsung** UI screenshots (the corresponding clips are in a Google Drive folder — the
   `drive.google.com` domain is unreachable from the work sandbox; the files must be
   attached to the chat or placed in the repository).
2. Numeric vendor GLS values for the test clips (DICOM SR, PDF report, or a screenshot with
   the numbers) — needed for quantitative comparison (bias/LoA), not just visual.
