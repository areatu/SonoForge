#!/usr/bin/env bash
# ============================================
#  SonoForge Presenter — Linux AppImage build
#
#  PyInstaller onedir  →  AppDir  →  AppImage (single portable file)
#
#  Prereqs: python3.10/3.11 venv with
#    pip install -r build/presenter/pinned-packages.txt pyinstaller
#  The script downloads appimagetool automatically when it is not on PATH.
#
#  Output: dist/SonoForge-Presenter-<version>-x86_64.AppImage
# ============================================
set -euo pipefail

cd "$(dirname "$0")/../.."   # project root

APP_NAME="SonoForgePresenter"
PRODUCT="SonoForge-Presenter"
PKG_DIR="sonoforge-presenter"
VERSION=$(python3 -c "import sys; sys.path.insert(0,'src'); from echo_personal_tool import __version__; print(__version__)")
DIST="dist"
APPDIR="${DIST}/${PRODUCT}.AppDir"
APPIMAGETOOL_URL="https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"

echo ""
echo "=== SonoForge Presenter — AppImage Build v${VERSION} ==="
echo ""

# ── 1. PyInstaller (onedir) ──
echo "[1/4] PyInstaller onedir..."
rm -rf "${DIST}/${APP_NAME}" build/${APP_NAME}
python3 -m PyInstaller build/presenter/sonoforge-presenter.spec --noconfirm --clean

# ── 2. Assemble AppDir ──
echo "[2/4] Assembling ${APPDIR}..."
mkdir -p "${DIST}"
rm -rf "${APPDIR}"
mkdir -p "${APPDIR}/usr/bin" \
         "${APPDIR}/usr/lib" \
         "${APPDIR}/usr/share/applications" \
         "${APPDIR}/usr/share/icons/hicolor/256x256/apps"

# Keep the PyInstaller onedir intact (the binary locates _internal/ next to it)
cp -r "${DIST}/${APP_NAME}" "${APPDIR}/usr/lib/${PKG_DIR}"
ln -s "../lib/${PKG_DIR}/${APP_NAME}" "${APPDIR}/usr/bin/${APP_NAME}"

cat > "${APPDIR}/AppRun" << 'APPRUN'
#!/usr/bin/env bash
HERE="$(dirname "$(readlink -f "${0}")")"
exec "${HERE}/usr/lib/sonoforge-presenter/SonoForgePresenter" "$@"
APPRUN
chmod +x "${APPDIR}/AppRun"

cat > "${APPDIR}/usr/share/applications/${PRODUCT,,}.desktop" << DESKTOP
[Desktop Entry]
Type=Application
Name=SonoForge Presenter
GenericName=DICOM Echocardiography Viewer
Comment=Portable echocardiography analysis and DICOM viewing (lite build)
Exec=${APP_NAME} %F
Icon=${PRODUCT,,}
Terminal=false
Categories=Medical;Science;Education;
Keywords=dicom;echocardiography;ultrasound;medical;
StartupWMClass=${APP_NAME}
DESKTOP

# Icon: prefer a 256px render, fall back to the bundled logo as-is
ICON_SRC="src/echo_personal_tool/resources/logo.png"
ICON_ROOT="${APPDIR}/${PRODUCT,,}.png"
if command -v convert &>/dev/null; then
    convert "${ICON_SRC}" -resize 256x256 "${ICON_ROOT}"
else
    cp "${ICON_SRC}" "${ICON_ROOT}"
fi
cp "${ICON_ROOT}" "${APPDIR}/usr/share/icons/hicolor/256x256/apps/${PRODUCT,,}.png"

# ── 3. Resolve appimagetool ──
echo "[3/4] Resolving appimagetool..."
run_appimagetool() {
    local out="$1"
    if [[ -n "${APPIMAGETOOL:-}" && -x "${APPIMAGETOOL}" ]]; then
        ARCH=x86_64 "${APPIMAGETOOL}" --no-appstream "${APPDIR}" "${out}" \
            || ARCH=x86_64 "${APPIMAGETOOL}" "${APPDIR}" "${out}"
    elif command -v appimagetool &>/dev/null; then
        ARCH=x86_64 appimagetool --no-appstream "${APPDIR}" "${out}" \
            || ARCH=x86_64 appimagetool "${APPDIR}" "${out}"
    else
        local tool="${DIST}/appimagetool-x86_64.AppImage"
        if [[ ! -f "${tool}" ]]; then
            echo "  downloading appimagetool..."
            curl -fsSL -o "${tool}" "${APPIMAGETOOL_URL}"
            chmod +x "${tool}"
        fi
        if [[ -x /dev/fuse ]] && fusermount -V &>/dev/null 2>&1; then
            ARCH=x86_64 "${tool}" --no-appstream "${APPDIR}" "${out}" \
                || ARCH=x86_64 "${tool}" "${APPDIR}" "${out}"
        else
            # No FUSE (CI containers): extract and run AppRun directly
            rm -rf "${DIST}/squashfs-root"
            (cd "${DIST}" && ./appimagetool-x86_64.AppImage --appimage-extract >/dev/null)
            ARCH=x86_64 "${DIST}/squashfs-root/AppRun" --no-appstream "${APPDIR}" "${out}" \
                || ARCH=x86_64 "${DIST}/squashfs-root/AppRun" "${APPDIR}" "${out}"
            rm -rf "${DIST}/squashfs-root"
        fi
    fi
}

# ── 4. Build AppImage ──
echo "[4/4] Building AppImage..."
mkdir -p "${DIST}"
OUTPUT="${DIST}/${PRODUCT}-${VERSION}-x86_64.AppImage"
rm -f "${OUTPUT}"
run_appimagetool "${OUTPUT}"

echo ""
echo "Done!"
echo "  Output: ${OUTPUT}"
echo "  Size:   $(du -h "${OUTPUT}" | cut -f1)"
echo ""
echo "  Run from USB stick:  ./${OUTPUT}"
echo "  No FUSE on host:     ./${OUTPUT} --appimage-extract-and-run"
echo "  Portable data lives in: <stick>/SonoForgePresenter-data/"
echo ""
