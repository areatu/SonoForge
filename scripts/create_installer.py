"""Create a self-extracting installer for SonoForge on Windows.

Produces SonoForge-Setup.exe — a PyInstaller-frozen exe with embedded zip.
"""

import io
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STAGING = PROJECT_ROOT / "dist" / "SonoForge-Setup"
OUTPUT = PROJECT_ROOT / "dist" / "SonoForge-Setup.exe"
INSTALLER_STUB = PROJECT_ROOT / "installer_stub.py"


def create_installer():
    if not STAGING.exists():
        print(f"Error: staging directory not found: {STAGING}")
        sys.exit(1)

    if not INSTALLER_STUB.exists():
        print(f"Error: installer_stub.py not found: {INSTALLER_STUB}")
        sys.exit(1)

    print("Creating installer zip...")

    # Create zip in memory
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(STAGING):
            for f in files:
                if f.endswith(".sed"):
                    continue
                fp = Path(root) / f
                arcname = str(fp.relative_to(STAGING))
                zf.write(fp, arcname)
                print(f"  + {arcname}")

    # Save zip to temp file for PyInstaller --add-data
    zip_path = PROJECT_ROOT / "dist" / "installer_data.zip"
    zip_path.write_bytes(zip_buf.getvalue())
    print(f"  Zip size: {zip_buf.tell() / 1024 / 1024:.1f} MB")

    # Build exe with PyInstaller
    print()
    print("Building installer exe with PyInstaller...")
    sep = ";" if os.name == "nt" else ":"
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--name",
        "SonoForge-Setup",
        "--console",
        "--clean",
        "--distpath",
        str(PROJECT_ROOT / "dist"),
        "--add-data",
        f"{zip_path}{sep}.",
        "--specpath",
        str(PROJECT_ROOT / "dist"),
        str(INSTALLER_STUB),
    ]
    result = subprocess.call(cmd)
    if result != 0:
        print(f"PyInstaller failed with code {result}")
        sys.exit(1)

    # Cleanup temp files
    zip_path.unlink(missing_ok=True)
    spec_path = PROJECT_ROOT / "dist" / "installer_stub.spec"
    spec_path.unlink(missing_ok=True)

    exe_path = PROJECT_ROOT / "dist" / "SonoForge-Setup.exe"
    if exe_path.exists():
        size_mb = exe_path.stat().st_size / (1024 * 1024)
        print()
        print(f"Installer created: {exe_path}")
        print(f"Size: {size_mb:.1f} MB")
    else:
        print("Error: exe was not created.")
        sys.exit(1)


if __name__ == "__main__":
    create_installer()
