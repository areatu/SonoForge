# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for **SonoForge Presenter** (lite portable build).

Profile differences vs `sonoforge-standalone.spec` (full build):

- Entry point: `__main_presenter__.py` — sets SONOFORGE_PROFILE=presenter
  and SONOFORGE_PORTABLE=1 before importing the app.
- NO onnxruntime, NO models, NO first-run download dialog.
- NO reference UI: QtWebEngine/QtWebChannel, PyMuPDF (fitz), openpyxl and
  the reference/constructor app modules are excluded. The small normative
  YAMLs (references_structured*.yaml) stay — report comparisons use them.
- Windows: onefile `SonoForgePresenter.exe` (single file, USB-stick ready).
- Linux: onedir — wrapped into an AppImage by `build-appimage.sh`.

Build:  python -m PyInstaller build/presenter/sonoforge-presenter.spec --noconfirm --clean
Deps:   pip install -r build/presenter/pinned-packages.txt pyinstaller
"""
import os
import sys

# PyInstaller resolves relative spec paths against the spec location —
# anchor everything to the repository root (spec lives in build/presenter/).
PROJECT_ROOT = os.path.abspath(os.path.join(SPECPATH, '..', '..'))  # noqa: F821

is_windows = sys.platform == 'win32'
is_linux = sys.platform.startswith('linux')
if not (is_windows or is_linux):
    raise SystemExit('presenter spec supports Windows and Linux only')

APP_NAME = 'SonoForgePresenter'
PKG = os.path.join(PROJECT_ROOT, 'src', 'echo_personal_tool')

# ── Data files ───────────────────────────────────────────────────────
# Only runtime-needed resources. Reference images (25 MB) and
# Standard_echo_RUS.pdf (11 MB) are NOT bundled (no reference UI).
datas = [
    (f'{PKG}/resources/fonts', 'echo_personal_tool/resources/fonts'),
    (f'{PKG}/resources/icons', 'echo_personal_tool/resources/icons'),
    (f'{PKG}/resources/logo.png', 'echo_personal_tool/resources'),
    (f'{PKG}/resources/logo_dark.png', 'echo_personal_tool/resources'),
    (f'{PKG}/infrastructure/locales', 'echo_personal_tool/infrastructure/locales'),
    (f'{PKG}/infrastructure/samsung_tick_calibration.json', 'echo_personal_tool/infrastructure'),
    # Normative data for report comparisons (report_builder / ReferenceDataStore)
    (f'{PKG}/resources/references/references_structured.yaml', 'echo_personal_tool/resources/references'),
    (f'{PKG}/resources/references/references_structured_ru.yaml', 'echo_personal_tool/resources/references'),
    (f'{PKG}/resources/references/references_schema.json', 'echo_personal_tool/resources/references'),
]

# ── Excludes ─────────────────────────────────────────────────────────
# Third-party modules removed from the Presenter product:
#   onnxruntime  — AI segmentation is not part of Presenter
#   fitz/pymupdf — reference PDF rendering only
#   openpyxl     — reference-constructor Excel import only
# PySide6 modules: everything beyond Core/Gui/Widgets/Network/PrintSupport/
# Svg/OpenGL (Essentials). QtWebEngine* is the big one (~200 MB in bundle).
excludes = [
    'onnxruntime',
    'fitz',
    'pymupdf',
    'openpyxl',
    # PySide6 — Web/Quick/QML family and other unused modules
    'PySide6.QtWebEngineCore',
    'PySide6.QtWebEngineWidgets',
    'PySide6.QtWebEngineQuick',
    'PySide6.QtWebChannel',
    'PySide6.QtWebSockets',
    'PySide6.QtWebView',
    'PySide6.QtQml',
    'PySide6.QtQmlModels',
    'PySide6.QtQuick',
    'PySide6.QtQuickWidgets',
    'PySide6.QtQuickControls2',
    'PySide6.QtMultimedia',
    'PySide6.QtMultimediaWidgets',
    'PySide6.QtPdf',
    'PySide6.QtPdfWidgets',
    'PySide6.QtCharts',
    'PySide6.QtDataVisualization',
    'PySide6.QtGraphs',
    'PySide6.QtGraphsWidgets',
    'PySide6.Qt3DCore',
    'PySide6.Qt3DRender',
    'PySide6.Qt3DInput',
    'PySide6.Qt3DLogic',
    'PySide6.Qt3DAnimation',
    'PySide6.Qt3DExtras',
    'PySide6.QtBluetooth',
    'PySide6.QtNfc',
    'PySide6.QtPositioning',
    'PySide6.QtLocation',
    'PySide6.QtSensors',
    'PySide6.QtSerialPort',
    'PySide6.QtSerialBus',
    'PySide6.QtRemoteObjects',
    'PySide6.QtScxml',
    'PySide6.QtStateMachine',
    'PySide6.QtTextToSpeech',
    'PySide6.QtSpatialAudio',
    'PySide6.QtHttpServer',
    'PySide6.QtGrpc',
    'PySide6.QtProtobuf',
    'PySide6.QtSql',
    'PySide6.QtXml',
    'PySide6.QtTest',
    'PySide6.QtDesigner',
    'PySide6.QtHelp',
    'PySide6.QtUiTools',
    # App modules belonging to the reference UI (not reachable in Presenter;
    # main_window imports them lazily behind profile/ImportError guards)
    'echo_personal_tool.presentation.ase_reference_dialog',
    'echo_personal_tool.presentation.structured_reference_widget',
    'echo_personal_tool.presentation.web_reference',
    'echo_personal_tool.presentation.web_reference.web_reference_widget',
    'echo_personal_tool.presentation.web_reference.web_reference_bridge',
    'echo_personal_tool.constructor',
    # Test/dev-only
    'pytest',
    'IPython',
    'matplotlib',
    'tkinter',
]

hiddenimports = [
    'pyside6', 'pyqtgraph', 'pydicom', 'pylibjpeg',
    'pylibjpeg_openjpeg', 'pylibjpeg_libjpeg',
    'numpy', 'scipy', 'cv2', 'httpx', 'psutil',
    'pynetdicom', 'yaml', 'jsonschema',
    'reportlab', 'keyring', 'cryptography',
    'echo_personal_tool',
]

a = Analysis(
    [os.path.join(PKG, '__main_presenter__.py')],
    pathex=[os.path.join(PROJECT_ROOT, 'src')],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

if is_windows:
    # Windows: onefile — a single .exe that can run straight from a USB stick.
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name=APP_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=f'{PKG}/resources/logo.ico',
    )
else:
    # Linux: onedir — build-appimage.sh wraps dist/SonoForgePresenter/ into
    # an AppImage (single portable file, faster start than onefile).
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=APP_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name=APP_NAME,
    )
