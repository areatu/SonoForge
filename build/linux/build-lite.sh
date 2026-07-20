#!/usr/bin/env bash
# ============================================
#  SonoForge — Lightweight .deb Build
#  Packages app code only (~50MB).
#  Dependencies + models are downloaded at first run.
# ============================================
set -euo pipefail

APP_NAME="sonoforge"
APP_VERSION=$(python3 -c "import sys; sys.path.insert(0,'src'); from echo_personal_tool import __version__; print(__version__)")
DEB_ARCH="amd64"
BUILD_DIR="build/deb-lite"
DIST_DIR="dist"
SRC_DIR="src/echo_personal_tool"

echo ""
echo "=== SonoForge Lite Build v${APP_VERSION} ==="
echo ""

# ── 1. Clean ──
echo "[1/5] Cleaning..."
rm -rf "${BUILD_DIR}"

# ── 2. Assemble package structure ──
echo "[2/5] Assembling package..."
DEB_PKG="${BUILD_DIR}/${APP_NAME}_${APP_VERSION}_${DEB_ARCH}"
mkdir -p "${DEB_PKG}/DEBIAN"
mkdir -p "${DEB_PKG}/opt/${APP_NAME}/lib"
mkdir -p "${DEB_PKG}/opt/${APP_NAME}/bin"
mkdir -p "${DEB_PKG}/usr/share/applications"
mkdir -p "${DEB_PKG}/usr/share/icons/hicolor/256x256/apps"

# Copy app code (pure Python, no binaries)
cp -r src/echo_personal_tool "${DEB_PKG}/opt/${APP_NAME}/lib/"

# Copy project files needed for pip install
cp pyproject.toml "${DEB_PKG}/opt/${APP_NAME}/lib/"
cp uv.lock "${DEB_PKG}/opt/${APP_NAME}/lib/" 2>/dev/null || true

# Copy launcher
cp build/linux/sonoforge-launcher "${DEB_PKG}/opt/${APP_NAME}/bin/sonoforge"
chmod 755 "${DEB_PKG}/opt/${APP_NAME}/bin/sonoforge"

# Desktop entry
cp scripts/sonoforge.desktop "${DEB_PKG}/usr/share/applications/"

# Convert logo to PNG for desktop icon
ICON_SRC="src/echo_personal_tool/resources/logo.png"
ICON_DST="${DEB_PKG}/usr/share/icons/hicolor/256x256/apps/${APP_NAME}.png"
if [ -f "${ICON_SRC}" ]; then
    cp "${ICON_SRC}" "${ICON_DST}"
elif command -v rsvg-convert &>/dev/null && [ -f "src/echo_personal_tool/resources/icons/activity_measures.svg" ]; then
    rsvg-convert -w 256 -h 256 "src/echo_personal_tool/resources/icons/activity_measures.svg" -o "${ICON_DST}"
else
    mkdir -p "${DEB_PKG}/usr/share/icons/hicolor/scalable/apps"
    cp "src/echo_personal_tool/resources/icons/activity_measures.svg" \
        "${DEB_PKG}/usr/share/icons/hicolor/scalable/apps/${APP_NAME}.svg" 2>/dev/null || true
    sed -i "s|Icon=${APP_NAME}|Icon=/usr/share/icons/hicolor/scalable/apps/${APP_NAME}.svg|" \
        "${DEB_PKG}/usr/share/applications/sonoforge.desktop"
fi

# ── 3. Generate DEBIAN/control ──
echo "[3/5] Generating control file..."
INSTALLED_SIZE=$(du -sk "${DEB_PKG}/opt" | cut -f1)

cat > "${DEB_PKG}/DEBIAN/control" << EOF
Package: ${APP_NAME}
Version: ${APP_VERSION}
Section: science
Priority: optional
Architecture: ${DEB_ARCH}
Depends: python3 (>= 3.10), python3-venv, python3-pip
Installed-Size: ${INSTALLED_SIZE}
Maintainer: SonoForge Team
Description: Personal desktop echocardiography analysis tool (lightweight)
 SonoForge is a desktop application for echocardiography
 analysis, DICOM viewing, cardiac measurements, and reference management.
 This package contains the application code only.
 Dependencies and AI models are downloaded on first run (~1.2 GB).
EOF

# ── 4. Post-install script ──
cat > "${DEB_PKG}/DEBIAN/postinst" << 'POSTINST'
#!/bin/bash
set -e
chmod +x /opt/sonoforge/bin/sonoforge
ln -sf /opt/sonoforge/bin/sonoforge /usr/local/bin/sonoforge
if command -v gtk-update-icon-cache &>/dev/null; then
    gtk-update-icon-cache -f -t /usr/share/icons/hicolor || true
fi
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

# Post-removal script (clean user data)
cat > "${DEB_PKG}/DEBIAN/postrm" << 'POSTRM'
#!/bin/bash
set -e
if [ "$1" = "purge" ]; then
    rm -rf ~/.local/share/sonoforge
fi
POSTRM
chmod 755 "${DEB_PKG}/DEBIAN/postrm"

# ── 5. Build .deb ──
echo "[4/5] Building .deb..."
DEB_OUTPUT="${DIST_DIR}/${APP_NAME}_${APP_VERSION}_${DEB_ARCH}.deb"
mkdir -p "${DIST_DIR}"
dpkg-deb --build --root-owner-group "${DEB_PKG}" "${DEB_OUTPUT}"

echo ""
echo "[5/5] Done!"
echo ""
echo "  Package: ${DEB_OUTPUT}"
echo "  Size:    $(du -h "${DEB_OUTPUT}" | cut -f1)"
echo ""
echo "  Install:  sudo dpkg -i ${DEB_OUTPUT}"
echo "  Run:      sonoforge"
echo ""
echo "  First run will download:"
echo "    - Python dependencies (~940 MB)"
echo "    - AI models (~193 MB)"
echo ""
