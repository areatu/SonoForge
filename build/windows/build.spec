# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the full SonoForge Windows onedir distribution."""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

# The release workflow invokes PyInstaller from the repository root.
PROJECT_ROOT = Path(os.getcwd())
SRC = PROJECT_ROOT / "src" / "echo_personal_tool"

# Windows PE version resource, generated from __version__. This spec is always
# built on Windows, so no platform guard is needed here. SPECPATH is the directory
# holding this spec (build/windows/), injected by PyInstaller, so parents[1] is the
# repository root. The helper lives in scripts/ rather than build/ because build/ is
# gitignored (it is PyInstaller's workpath) and a source file there can be silently
# dropped by `git add -A`. See scripts/pyinstaller_version.py for why a file path is
# used rather than a VSVersionInfo object (the object form would import pefile and
# pywin32, both Windows-only, and break the macOS and Linux builds). scripts/ is
# popped again right after the import so nothing in it can shadow a real module.
_HELPERS = str(Path(SPECPATH).parents[1] / "scripts")  # noqa: F821
sys.path.insert(0, _HELPERS)
try:
    from pyinstaller_version import write_version_file  # noqa: E402
finally:
    sys.path.remove(_HELPERS)

# Keep core assets explicit for directory builds, then include remaining package data.
datas = [
    (str(SRC / "resources" / "fonts"), "echo_personal_tool/resources/fonts"),
    (str(SRC / "resources" / "references"), "echo_personal_tool/resources/references"),
    (str(SRC / "resources" / "icons"), "echo_personal_tool/resources/icons"),
    (str(SRC / "resources" / "logo.png"), "echo_personal_tool/resources"),
    (str(SRC / "resources" / "logo_dark.png"), "echo_personal_tool/resources"),
]
datas += collect_data_files("echo_personal_tool")

hiddenimports = [
    # DICOM stack
    "pydicom",
    "pydicom.encaps",
    "pydicom.pixel_data_handlers",
    "pydicom.pixel_data_handlers.util",
    "pylibjpeg",
    "pylibjpeg_openjpeg",
    "pylibjpeg_libjpeg",
    "pynetdicom",
    "pynetdicom.encoders",
    "pynetdicom.encoders.generation",
    "pynetdicom.sop_class",
    "pynetdicom.storage",
    # NumPy / SciPy
    "numpy",
    "scipy",
    "scipy._lib.messagestream",
    "scipy.special",
    # Qt / plotting
    "PySide6",
    "pyqtgraph",
    "pyqtgraph.graphicsItems.ViewBox.axisCtrlTemplate_pyqt5",
    "pyqtgraph.imageview.ImageViewTemplate_pyqt5",
    # CV and networking
    "cv2",
    "httpx",
    "httpx._transports",
    "httpx._transports.default",
    "psutil",
    "psutil._pswindows",
    # Documents, configuration, and optional AI
    "pymupdf",
    "yaml",
    "jsonschema",
    "onnxruntime",
    "reportlab",
    "openpyxl",
    "keyring",
    "keyring.backends.Windows",
    "echo_personal_tool",
]

a = Analysis(
    [str(SRC / "__main__.py")],
    pathex=[str(PROJECT_ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SonoForge",
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
    icon=str(SRC / "resources" / "logo.ico"),
    # The Inno Setup installer already carries VersionInfoProductName /
    # VersionInfoProductVersion, but the payload exe it installs did not. Without
    # this the installed SonoForge.exe shows an empty Details tab in Explorer and
    # a signing provider cannot enforce its product-name/version requirements.
    version=write_version_file(
        original_filename="SonoForge.exe",
        file_description="SonoForge - desktop echocardiography analysis",
    ),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="SonoForge",
)
