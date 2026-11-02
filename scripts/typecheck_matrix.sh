#!/usr/bin/env bash
# Reproduce one cell of the CI mypy matrix locally (#417).
#
#   scripts/typecheck_matrix.sh 3.11
#   scripts/typecheck_matrix.sh 3.12
#   scripts/typecheck_matrix.sh 3.13
#
# The interpreter must match the requested cell (CI installs it with
# actions/setup-python). Every tool is pinned from uv.lock; numpy is selected
# with --python-version because uv.lock resolves 2.4.6 below 3.12 and 2.5.4
# from it. The final guard refuses a run that checked zero source files.

set -euo pipefail

PY_VERSION="${1:?usage: scripts/typecheck_matrix.sh 3.11|3.12|3.13}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

case "$PY_VERSION" in
  3.11|3.12|3.13) ;;
  *) echo "typecheck: unsupported Python $PY_VERSION (supported: 3.11–3.13)" >&2; exit 1 ;;
esac

ACTUAL="$(python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if [[ "$ACTUAL" != "$PY_VERSION" ]]; then
  echo "typecheck: requested Python $PY_VERSION but the active interpreter is $ACTUAL" >&2
  exit 1
fi

locked() { python .github/scripts/locked_version.py "$@"; }

python -m pip install --disable-pip-version-check -q \
  "mypy==$(locked mypy)" \
  "PySide6==$(locked PySide6)" \
  "numpy==$(locked numpy --python-version "$PY_VERSION")" \
  "opencv-python-headless==$(locked opencv-python-headless)" \
  "pydicom==$(locked pydicom)" \
  "types-PyYAML==$(locked types-PyYAML)"

LOG="$(mktemp)"
trap 'rm -f "$LOG"' EXIT

set -o pipefail
python -m mypy --python-version "$PY_VERSION" 2>&1 | tee "$LOG"
python - "$PY_VERSION" "$LOG" <<'PY'
import re
import sys

version, path = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as handle:
    text = handle.read()
match = re.search(r"no issues found in (\d+) source files", text)
if not match or int(match.group(1)) == 0:
    raise SystemExit(
        f"typecheck {version}: mypy reported no checked source files — a green no-op is not a gate"
    )
print(f"typecheck {version}: mypy strict checked {match.group(1)} source files")
PY
