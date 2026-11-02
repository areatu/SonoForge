#!/usr/bin/env bash
# Helper for environments where venv python does not activate site-packages (Cyrillic paths).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="${ROOT}/src:${ROOT}/.venv/lib/python3.11/site-packages"
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}"
exec python3 -m pytest "$@"
