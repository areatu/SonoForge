"""SonoForge launcher — finds Python, sets up venv, installs deps, runs the app."""

import os
import subprocess
import sys
import shutil
from pathlib import Path

APP_NAME = "SonoForge"
DATA_DIR = Path(os.environ.get("LOCALAPPDATA", "")) / "SonoForge"
VENV_DIR = DATA_DIR / "venv"
MODELS_DIR = DATA_DIR / "models"
MODELS_URL = "https://github.com/areatu/sonoforge-models/releases/download/models-v1/models-v1.tar.gz"

INSTALL_DIR = Path(__file__).resolve().parent
LIB_DIR = INSTALL_DIR / "lib"


def find_python():
    """Find Python 3.10+ on the system."""
    for name in ("python", "python3"):
        path = shutil.which(name)
        if path:
            try:
                out = subprocess.check_output([path, "--version"], stderr=subprocess.STDOUT, text=True)
                parts = out.strip().split()
                if len(parts) == 2:
                    ver = parts[1].split(".")
                    major, minor = int(ver[0]), int(ver[1])
                    if major >= 3 and minor >= 10:
                        return path
            except Exception:
                continue
    return None


def create_venv(python_path):
    """Create virtual environment if it doesn't exist."""
    if VENV_DIR.exists():
        return True
    print(f"[{APP_NAME}] Creating virtual environment in {VENV_DIR}...")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.check_call([python_path, "-m", "venv", str(VENV_DIR)])
    print(f"[{APP_NAME}] venv created.")
    return True


def install_deps():
    """Install dependencies if not already installed."""
    marker = VENV_DIR / ".deps_installed"
    if marker.exists():
        return True
    pip = VENV_DIR / "Scripts" / "pip.exe"
    print(f"[{APP_NAME}] Installing dependencies (this may take a few minutes)...")
    subprocess.check_call([str(pip), "install", "--quiet", "--upgrade", "pip"])
    subprocess.check_call(
        [
            str(pip),
            "install",
            "--quiet",
            "PySide6",
            "pyqtgraph",
            "pydicom",
            "pylibjpeg",
            "pylibjpeg-openjpeg",
            "pylibjpeg-libjpeg",
            "numpy<2",
            "scipy",
            "opencv-python-headless",
            "httpx",
            "psutil",
            "pymupdf",
            "pynetdicom",
            "pyyaml",
            "jsonschema",
            "onnxruntime",
            "reportlab",
            "openpyxl",
            "keyring",
        ]
    )
    marker.write_text("installed")
    print(f"[{APP_NAME}] Dependencies installed.")
    return True


def download_models():
    """Download AI models if not present."""
    if (MODELS_DIR / "model_manifest.json").exists():
        return True
    print()
    print(f"[{APP_NAME}] AI models are required for automatic cardiac segmentation.")
    print(f"[{APP_NAME}] Download size: ~300 MB")
    print()
    answer = input("Download models? [Y/n]: ").strip().lower()
    if answer == "n":
        print(f"[{APP_NAME}] Skipping models. AI segmentation will be unavailable.")
        return False
    print(f"[{APP_NAME}] Downloading models...")
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    archive = DATA_DIR / "models.tar.gz"
    try:
        curl = shutil.which("curl")
        if curl:
            subprocess.check_call(
                [
                    curl,
                    "-fSL",
                    "--connect-timeout",
                    "30",
                    "--retry",
                    "2",
                    "--progress-bar",
                    "-o",
                    str(archive),
                    MODELS_URL,
                ]
            )
        else:
            subprocess.check_call(
                ["powershell", "-Command", f"Invoke-WebRequest -Uri '{MODELS_URL}' -OutFile '{archive}'"]
            )
    except Exception as e:
        print(f"[{APP_NAME}] Model download failed: {e}")
        return False
    if archive.exists():
        print(f"[{APP_NAME}] Extracting models...")
        subprocess.check_call(["tar", "-xzf", str(archive), "-C", str(DATA_DIR)])
        archive.unlink()
    if (MODELS_DIR / "model_manifest.json").exists():
        print(f"[{APP_NAME}] Models ready.")
        return True
    else:
        print(f"[{APP_NAME}] Model extraction failed.")
        return False


def launch_app():
    """Launch the actual application."""
    venv_python = VENV_DIR / "Scripts" / "python.exe"
    print(f"[{APP_NAME}] Starting {APP_NAME}...")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(LIB_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    subprocess.call([str(venv_python), "-m", "echo_personal_tool"] + sys.argv[1:], env=env)


def main():
    print(f"[{APP_NAME}] Checking environment...")

    python_path = find_python()
    if not python_path:
        print()
        print(f"[{APP_NAME}] Python 3.10+ is required but not found.")
        print()
        print("Please install Python 3.10 or 3.11 from https://www.python.org/downloads/")
        print('Make sure to check "Add Python to PATH" during installation.')
        input("Press Enter to exit...")
        sys.exit(1)

    # Check version for display
    out = subprocess.check_output([python_path, "--version"], stderr=subprocess.STDOUT, text=True)
    print(f"[{APP_NAME}] Using: {python_path} ({out.strip()})")

    create_venv(python_path)
    install_deps()
    download_models()
    launch_app()


if __name__ == "__main__":
    main()
