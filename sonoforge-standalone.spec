# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for SonoForge standalone exe (--onefile).

Used for both Windows and macOS builds. Architecture is determined by the
build environment (CI runner). Models are NOT bundled — they are downloaded
on first launch via runtime_setup.show_setup_dialog(). This keeps the exe
at ~250-400 MB instead of ~1 GB.
"""
from PyInstaller.utils.hooks import collect_data_files

datas = [
    ('src/echo_personal_tool/resources/fonts', 'echo_personal_tool/resources/fonts'),
    ('src/echo_personal_tool/resources/references', 'echo_personal_tool/resources/references'),
    ('src/echo_personal_tool/resources/icons', 'echo_personal_tool/resources/icons'),
    ('src/echo_personal_tool/resources/logo.png', 'echo_personal_tool/resources'),
    ('src/echo_personal_tool/resources/logo_dark.png', 'echo_personal_tool/resources'),
]
datas += collect_data_files('echo_personal_tool')

a = Analysis(
    ['src/echo_personal_tool/__main__.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'pyside6', 'pyqtgraph', 'pydicom', 'pylibjpeg',
        'pylibjpeg_openjpeg', 'pylibjpeg_libjpeg',
        'numpy', 'scipy', 'cv2', 'httpx', 'psutil', 'pymupdf',
        'pynetdicom', 'yaml', 'jsonschema', 'onnxruntime',
        'reportlab', 'openpyxl', 'keyring',
        'echo_personal_tool',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='SonoForge',
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
    icon='src/echo_personal_tool/resources/logo.ico',
)

# macOS .app bundle (used by CI for DMG creation)
app = BUNDLE(
    exe,
    name='SonoForge.app',
    icon='src/echo_personal_tool/resources/logo.icns',
    bundle_identifier='com.echocardiography.sonoforge',
    info_plist={
        'CFBundleShortVersionString': '0.2.3',
        'NSHighResolutionCapable': True,
        'NSRequiresAquaSystemAppearance': False,
    },
)
