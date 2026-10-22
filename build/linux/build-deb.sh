#!/usr/bin/env bash
# Build .deb package for ECHO Personal Tool
# Usage: ./build/linux/build-deb.sh [--clean]   (run from the repository root)
set -euo pipefail

APP_NAME="sonoforge"
APP_VERSION=$(python3 -c "import sys; sys.path.insert(0,'src'); from echo_personal_tool import __version__; print(__version__)")
DEB_ARCH="amd64"
BUILD_DIR="build/deb"
DIST_DIR="dist"
VENV_DIR=".venv-build"

echo "=== Building ${APP_NAME} v${APP_VERSION} .deb ==="

# ── Clean if requested ──
if [[ "${1:-}" == "--clean" ]]; then
    echo "[clean] Removing build artifacts..."
    rm -rf "${BUILD_DIR}" "${DIST_DIR}/sonoforge" "${VENV_DIR}"
fi

# ── 1. Create build venv ──
if [[ ! -d "${VENV_DIR}" ]]; then
    echo "[step 1] Creating build venv..."
    python3 -m venv "${VENV_DIR}"
fi
source "${VENV_DIR}/bin/activate"

echo "[step 2] Installing dependencies..."
pip install --quiet --upgrade pip
pip install --quiet pyinstaller
pip install --quiet -e ".[dev]" 2>/dev/null || pip install --quiet pyside6 pyqtgraph pydicom pylibjpeg pylibjpeg-openjpeg pylibjpeg-libjpeg "numpy<2" scipy opencv-python-headless httpx psutil pymupdf pynetdicom pyyaml jsonschema onnxruntime reportlab openpyxl keyring

# ── 3. Clear server settings on build machine ──
echo "[step 3] Clearing server settings..."
rm -f ~/.config/sonoforge/server.conf

# ── 4. Build with PyInstaller ──
echo "[step 4] Running PyInstaller (this may take a few minutes)..."
pyinstaller \
    --name "${APP_NAME}" \
    --onedir \
    --noconfirm \
    --clean \
    --windowed \
    --noconsole \
    --add-data "src/echo_personal_tool/resources/fonts:echo_personal_tool/resources/fonts" \
    --add-data "src/echo_personal_tool/resources/references:echo_personal_tool/resources/references" \
    --add-data "src/echo_personal_tool/resources/icons:echo_personal_tool/resources/icons" \
    --add-data "models:models" \
    --hidden-import=pyside6 \
    --hidden-import=pyqtgraph \
    --hidden-import=pydicom \
    --hidden-import=pylibjpeg \
    --hidden-import=pylibjpeg_openjpeg \
    --hidden-import=pylibjpeg_libjpeg \
    --hidden-import=numpy \
    --hidden-import=scipy \
    --hidden-import=cv2 \
    --hidden-import=httpx \
    --hidden-import=psutil \
    --hidden-import=pymupdf \
    --hidden-import=pynetdicom \
    --hidden-import=yaml \
    --hidden-import=jsonschema \
    --hidden-import=onnxruntime \
    --hidden-import=reportlab \
    --hidden-import=openpyxl \
    --hidden-import=echo_personal_tool \
    --collect-data echo_personal_tool \
    src/echo_personal_tool/__main__.py

# ── 5. Assemble .deb directory structure ──
echo "[step 5] Assembling .deb package..."
DEB_PKG="${BUILD_DIR}/${APP_NAME}_${APP_VERSION}_${DEB_ARCH}"
rm -rf "${DEB_PKG}"
mkdir -p "${DEB_PKG}/DEBIAN"
mkdir -p "${DEB_PKG}/opt/${APP_NAME}"
mkdir -p "${DEB_PKG}/usr/share/applications"
mkdir -p "${DEB_PKG}/usr/share/icons/hicolor/256x256/apps"

# Copy PyInstaller output
cp -a "dist/${APP_NAME}/"* "${DEB_PKG}/opt/${APP_NAME}/"

# Desktop entry
cp scripts/sonoforge.desktop "${DEB_PKG}/usr/share/applications/"

# Convert an SVG icon to PNG for the desktop entry (using rsvg if available, else fallback)
ICON_SRC="src/echo_personal_tool/resources/icons/activity_measures.svg"
ICON_DST="${DEB_PKG}/usr/share/icons/hicolor/256x256/apps/${APP_NAME}.png"
if command -v rsvg-convert &>/dev/null; then
    rsvg-convert -w 256 -h 256 "${ICON_SRC}" -o "${ICON_DST}"
elif command -v convert &>/dev/null; then
    convert -background none "${ICON_SRC}" -resize 256x256 "${ICON_DST}"
else
    echo "[warn] No SVG converter found (rsvg-convert/ImageMagick). Using SVG directly."
    cp "${ICON_SRC}" "${DEB_PKG}/usr/share/icons/hicolor/scalable/apps/${APP_NAME}.svg" 2>/dev/null || true
    # Update desktop file to reference SVG
    sed -i "s|Icon=${APP_NAME}|Icon=/usr/share/icons/hicolor/scalable/apps/${APP_NAME}.svg|" \
        "${DEB_PKG}/usr/share/applications/sonoforge.desktop"
fi

# ── 6. Generate DEBIAN/control ──
# Calculate installed size in KB
INSTALLED_SIZE=$(du -sk "${DEB_PKG}/opt" | cut -f1)

cat > "${DEB_PKG}/DEBIAN/control" << EOF
Package: ${APP_NAME}
Version: ${APP_VERSION}
Section: science
Priority: optional
Architecture: ${DEB_ARCH}
Depends: libgl1-mesa-glx | libgl1, libglib2.0-0, libfontconfig1, libxkbcommon0, libxkbcommon-x11-0, libxcb-cursor0, libxcb-icccm4, libxcb-image0, libxcb-keysyms1, libxcb-randr0, libxcb-render-util0, libxcb-shape0, libxcb-xinerama0, libxcb-xfixes0, libxcb-xinput0
Installed-Size: ${INSTALLED_SIZE}
Maintainer: SonoForge Team
Description: Personal desktop echocardiography analysis tool
 SonoForge is a desktop application for echocardiography
 analysis, DICOM viewing, cardiac measurements, and reference management.
EOF

# ── 7. Post-install script (optional: create symlink) ──
cat > "${DEB_PKG}/DEBIAN/postinst" << 'POSTINST'
#!/bin/bash
set -e
# Make the binary executable
chmod +x /opt/sonoforge/sonoforge
# Create a symlink in /usr/local/bin
ln -sf /opt/sonoforge/sonoforge /usr/local/bin/sonoforge
# Update icon cache
if command -v gtk-update-icon-cache &>/dev/null; then
    gtk-update-icon-cache -f -t /usr/share/icons/hicolor || true
fi
# Update desktop database
if command -v update-desktop-database &>/dev/null; then
    update-desktop-database /usr/share/applications || true
fi
POSTINST
chmod 755 "${DEB_PKG}/DEBIAN/postinst"

# Pre-removal script
cat > "${DEB_PKG}/DEBIAN/prerm" << 'PRERM'
#!/bin/bash
set -e
rm -f /usr/local/bin/sonoforge
PRERM
chmod 755 "${DEB_PKG}/DEBIAN/prerm"

# ── 8. Build .deb ──
echo "[step 7] Building .deb..."
DEB_OUTPUT="${DIST_DIR}/${APP_NAME}_${APP_VERSION}_${DEB_ARCH}.deb"
mkdir -p "${DIST_DIR}"
dpkg-deb --build --root-owner-group "${DEB_PKG}" "${DEB_OUTPUT}"

echo ""
echo "=== Done! ==="
echo "Package: ${DEB_OUTPUT}"
echo "Size: $(du -h "${DEB_OUTPUT}" | cut -f1)"
echo ""
echo "Install with:  sudo dpkg -i ${DEB_OUTPUT}"
echo "Fix deps with: sudo apt-get install -f"
