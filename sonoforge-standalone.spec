# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for SonoForge standalone builds.

- Windows: oneffile mode (single .exe)
- macOS: onedir mode + BUNDLE (.app → DMG)

Architecture is determined by the build environment (CI runner).
Models are NOT bundled — they are downloaded on first launch via
runtime_setup.show_setup_dialog(). This keeps the package at ~250-400 MB.
"""
import sys
from PyInstaller.utils.hooks import collect_data_files

is_macos = sys.platform == 'darwin'

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

if is_macos:
    # macOS: onedir mode for .app bundle
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name='SonoForge',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon='src/echo_personal_tool/resources/logo.icns',
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name='SonoForge',
    )
    app = BUNDLE(
        coll,
        name='SonoForge.app',
        icon='src/echo_personal_tool/resources/logo.icns',
        bundle_identifier='com.echocardiography.sonoforge',
        info_plist={
            'CFBundleShortVersionString': '0.2.3',
            'NSHighResolutionCapable': True,
            'NSRequiresAquaSystemAppearance': False,
        },
    )
else:
    # Windows/Linux: onefile mode
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
