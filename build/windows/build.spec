# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for ECHO Personal Tool (folder mode, Windows 10)."""

import os
from pathlib import Path

block_cipher = None

# Spec always runs from project root (pyinstaller cwd)
PROJECT_ROOT = Path(os.getcwd())
SRC = PROJECT_ROOT / "src" / "echo_personal_tool"

a = Analysis(
    [str(SRC / "__main__.py")],
    pathex=[str(PROJECT_ROOT / "src")],
    binaries=[],
    datas=[
        (str(SRC / "resources" / "fonts"), "echo_personal_tool/resources/fonts"),
        (str(SRC / "resources" / "icons"), "echo_personal_tool/resources/icons"),
        (str(SRC / "resources" / "references"), "echo_personal_tool/resources/references"),
    ],
    hiddenimports=[
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
        # CV
        "cv2",
        # HTTP / network
        "httpx",
        "httpx._transports",
        "httpx._transports.default",
        # System
        "psutil",
        "psutil._pswindows",
        # PDF
        "pymupdf",
        # ONNX (optional — phase2)
        "onnxruntime",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
    ],
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
    name="ECHO-Personal-Tool",
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
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="ECHO-Personal-Tool",
)
