#!/usr/bin/env bash
# ============================================
#  SonoForge — Linux Build
#  Folder mode (portable directory)
# ============================================
set -euo pipefail

echo ""
echo "=== SonoForge — Linux Build ==="
echo ""

# [1] Проверка venv
VENV_PYTHON=".venv/bin/python"
VENV_PIP=".venv/bin/pip"
if [ ! -f "$VENV_PYTHON" ]; then
    echo "[ERROR] .venv not found."
    echo "  Run: python3 -m venv .venv && .venv/bin/pip install -e '.[phase2]'"
    exit 1
fi

# [2] Установка зависимостей
echo "[1/4] Installing dependencies..."
$VENV_PIP install -e ".[phase2]" --quiet 2>/dev/null || $VENV_PIP install -e "." --quiet
$VENV_PIP install pyinstaller --quiet

# [3] Clear server settings on build machine
echo "[2/4] Clearing server settings..."
rm -f ~/.config/sonoforge/server.conf

# [4] Сборка
echo "[3/4] Building (folder mode)..."
$VENV_PYTHON -m PyInstaller build/linux/build.spec --noconfirm --clean

# [4] Готово
echo ""
echo "[4/4] Build complete!"
echo ""
echo "  Output: dist/SonoForge/"
echo "  Launch: ./dist/SonoForge/SonoForge"
echo ""
