# Data

> [Русская версия](README_RU.md)

Clinical data (source DICOM clips) is **not stored** in this public repository —
it contains identifying information and has been moved to a private repository.

## Where the source clips live

| Repository | Contents | Access |
|------------|----------|--------|
| [`areatu/Sonoforge_data`](https://github.com/areatu/Sonoforge_data) | `data/dicom/For_pero` — 19 STE clips (Samsung RS85, Philips; some with ECG), Git LFS | private |

Historically the clips lived here, in `data/dicom/For_pero` (Git LFS). On 2026-09-17
the folder was moved to a private repository because names were burned into the
frames; only LFS pointers remain in the public history.

## Derived data (public, in this repository)

| Path | What it is |
|------|------------|
| `tests/fixtures/for_pero/` | Compact fixtures exported from the clips: frames as JPEG + stripped headers (`index.json`, `_diagnostics.md`). Regular files, not LFS. |
| `gold/` | Reference segmentation annotations for LV/LA |

## How fixtures reach the public repository

Workflow [`ste-fixtures.yml`](../.github/workflows/ste-fixtures.yml):
1. clones the private `areatu/Sonoforge_data` (secret `SONOFORGE_DATA_TOKEN`),
2. runs `tools/ste_fixture_export.py`,
3. commits the compact result to `tests/fixtures/for_pero/` of the branch that triggered it.

Local regeneration (requires access to the private repository):

```bash
git clone https://github.com/areatu/Sonoforge_data.git /tmp/sonoforge_data
python tools/ste_fixture_export.py \
    --source /tmp/sonoforge_data/data/dicom/For_pero \
    --out tests/fixtures/for_pero
```

## Utility scripts

| Script | Purpose |
|--------|---------|
| `../tools/migrate_for_pero.sh` | One-off migration of the clips from the public repository to the private one (the commit with the clips is pinned in the script, so it works after the merge too) |
