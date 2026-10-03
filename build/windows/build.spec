# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the full SonoForge Windows onedir distribution."""

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

# The release workflow invokes PyInstaller from the repository root.
PROJECT_ROOT = Path(os.getcwd())
SRC = PROJECT_ROOT / "src" / "echo_personal_tool"

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
