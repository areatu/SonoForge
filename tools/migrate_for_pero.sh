#!/usr/bin/env bash
# ============================================================================
# One-time migration: data/dicom/For_pero  ->  areatu/Sonoforge_data (private)
#
# Copies the LFS study clips out of the public SonoForge repository into the
# private data repository, preserving the data/dicom/For_pero path. Requires
# git-lfs and push access to both repositories. SRC_REF is pinned to the last
# commit that still contains the clips, so the script works after the merge too.
#
# Usage:
#   ./tools/migrate_for_pero.sh [--src-ref <ref>] [--keep-workdir]
# ============================================================================
set -euo pipefail

SRC_REPO="https://github.com/areatu/SonoForge.git"
# Last commit that still contains data/dicom/For_pero (the removal landed in the
# commit after this one) — pinned so the script works even after the merge.
SRC_REF="dfeef2360bfa740b8b6c577b711df0d390f0f704"
DATA_REPO="https://github.com/areatu/Sonoforge_data.git"
SOURCE_DIR="data/dicom/For_pero"
KEEP=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --src-ref) SRC_REF="$2"; shift 2 ;;
        --keep-workdir) KEEP=1; shift ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

command -v git >/dev/null || { echo "git not found" >&2; exit 1; }
git lfs version >/dev/null 2>&1 || { echo "git-lfs not found — install it first (https://git-lfs.com)" >&2; exit 1; }

WORK="$(mktemp -d -t sonoforge-migrate-XXXX)"
trap '[[ "$KEEP" == 1 ]] && echo "[keep] workdir: $WORK" || rm -rf "$WORK"' EXIT

echo "[1/5] Cloning $SRC_REPO @ $SRC_REF (LFS objects included)..."
git clone --quiet "$SRC_REPO" "$WORK/sonoforge"
git -C "$WORK/sonoforge" checkout --quiet "$SRC_REF"
git -C "$WORK/sonoforge" lfs pull --include="$SOURCE_DIR/**"

CLIP_COUNT=$(find "$WORK/sonoforge/$SOURCE_DIR" -type f | wc -l)
echo "      found $CLIP_COUNT clip files"
# Sanity: no LFS pointer files may remain (they are < 1 KB text files).
POINTERS=$(find "$WORK/sonoforge/$SOURCE_DIR" -type f -size -1024c | wc -l)
if [[ "$POINTERS" -gt 0 ]]; then
    echo "ERROR: $POINTERS files look like LFS pointers, not real content:" >&2
    find "$WORK/sonoforge/$SOURCE_DIR" -type f -size -1024c >&2
    exit 1
fi

echo "[2/5] Cloning $DATA_REPO..."
git clone --quiet "$DATA_REPO" "$WORK/data"
if [[ -n "$(git -C "$WORK/data" log --oneline 2>/dev/null)" && -e "$WORK/data/$SOURCE_DIR" ]]; then
    echo "ERROR: $SOURCE_DIR already exists in the data repo — refusing to overwrite." >&2
    exit 1
fi

echo "[3/5] Copying clips + writing .gitattributes..."
mkdir -p "$WORK/data/data/dicom"
cp -r "$WORK/sonoforge/$SOURCE_DIR" "$WORK/data/$SOURCE_DIR"
cat > "$WORK/data/.gitattributes" <<'EOF'
*.dcm filter=lfs diff=lfs merge=lfs -text
data/dicom/For_pero/gold_Ph_ECG* filter=lfs diff=lfs merge=lfs -text
data/dicom/For_pero/strain_ph* filter=lfs diff=lfs merge=lfs -text
EOF

if [[ ! -f "$WORK/data/README.md" ]]; then
    cat > "$WORK/data/README.md" <<'EOF'
# Sonoforge_data (private)

Клинические данные SonoForge. Репозиторий закрытый: файлы содержат
идентифицирующую информацию (в т.ч. ФИО, впаянные в кадры).

| Путь | Содержимое |
|------|------------|
| `data/dicom/For_pero/` | 19 STE-клипов: Samsung RS85 (`gold1…gold6`, `strain_sams1…6`), клипы с ЭКГ (`gold7+ECG`, `gold8+ECG`), Philips (`gold_Ph_ECG1/2`, `strain_ph1…3`). Git LFS. |

Публичный репозиторий `areatu/SonoForge` использует эти клипы через воркфлоу
`ste-fixtures.yml` (секрет `SONOFORGE_DATA_TOKEN`) и хранит только компактные
обезличенные фикстуры `tests/fixtures/for_pero/`.
EOF
fi

echo "[4/5] Committing in the data repo..."
git -C "$WORK/data" add -A
git -C "$WORK/data" -c user.name="SonoForge migration" -c user.email="actions@users.noreply.github.com" \
    commit --quiet -m "data: migrate For_pero study clips from areatu/SonoForge (PHI -> private)"

echo "[5/5] Pushing (LFS objects upload may take a while, ~460 MB)..."
git -C "$WORK/data" push origin HEAD

echo ""
echo "Done. Remaining steps on GitHub:"
echo "  1. Create a fine-grained token with Contents:read on Sonoforge_data."
echo "  2. Add it as the SONOFORGE_DATA_TOKEN secret in areatu/SonoForge"
echo "     (Settings → Secrets and variables → Actions)."
echo "  3. Merge the SonoForge branch that removes $SOURCE_DIR."
