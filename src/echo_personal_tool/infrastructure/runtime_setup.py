"""Runtime environment setup: dependency check, model download, first-run dialog."""

from __future__ import annotations

import importlib
import logging
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from echo_personal_tool import __version__

logger = logging.getLogger(__name__)

_MODELS_RELEASE_URL = "https://github.com/areatu/sonoforge-models/releases/download/models-v1/models-v1.tar.gz"
_DATA_DIR = Path.home() / ".local" / "share" / "sonoforge"
_VENV_DIR = _DATA_DIR / "venv"
_MODELS_DIR = _DATA_DIR / "models"

_REQUIRED_PACKAGES = [
    "PySide6",
    "pyqtgraph",
    "pydicom",
    "numpy",
    "scipy",
    "cv2",
    "httpx",
    "psutil",
    "yaml",
    "jsonschema",
    "onnxruntime",
    "reportlab",
    "openpyxl",
    "keyring",
    "pynetdicom",
]


@dataclass
class SetupStatus:
    venv_exists: bool
    deps_installed: bool
    models_exist: bool
    python_ok: bool


def check_python_version() -> bool:
    """Return True if Python >= 3.10."""
    return sys.version_info >= (3, 10)


def check_deps() -> bool:
    """Return True if all required packages are importable."""
    for pkg in _REQUIRED_PACKAGES:
        try:
            importlib.import_module(pkg)
        except ImportError:
            return False
    return True


def check_models() -> bool:
    """Return True if model_manifest.json exists in the models dir."""
    return (_MODELS_DIR / "model_manifest.json").is_file()


def get_setup_status() -> SetupStatus:
    return SetupStatus(
        venv_exists=_VENV_DIR.is_dir(),
        deps_installed=check_deps(),
        models_exist=check_models(),
        python_ok=check_python_version(),
    )


def install_deps(progress_callback: Callable[[str, int], None] | None = None) -> bool:
    """Install dependencies into the user venv. Returns True on success."""
    if not _VENV_DIR.is_dir():
        _report(progress_callback, "Creating virtual environment...", 5)
        subprocess.run(
            [sys.executable, "-m", "venv", str(_VENV_DIR)],
            check=True,
            capture_output=True,
        )

    venv_pip = _VENV_DIR / "bin" / "pip"
    if not venv_pip.exists():
        logger.error("pip not found in venv: %s", venv_pip)
        return False

    _report(progress_callback, "Installing dependencies...", 20)
    try:
        subprocess.run(
            [str(venv_pip), "install", "--quiet", "--upgrade", "pip"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [str(venv_pip), "install", "--quiet"] + _REQUIRED_PACKAGES,
            check=True,
            capture_output=True,
        )
        _report(progress_callback, "Dependencies installed.", 90)
        return True
    except subprocess.CalledProcessError as exc:
        logger.error("pip install failed: %s", exc)
        return False


def download_models(progress_callback: Callable[[str, int], None] | None = None) -> bool:
    """Download and extract models from GitHub Releases. Returns True on success."""
    _MODELS_DIR.mkdir(parents=True, exist_ok=True)

    _report(progress_callback, "Downloading models...", 10)
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            archive = Path(tmp_dir) / "models.tar.gz"
            _download_file(_MODELS_RELEASE_URL, archive, progress_callback)

            _report(progress_callback, "Extracting models...", 85)
            with tarfile.open(archive, "r:gz") as tar:
                # Validate all members stay within target directory (prevent tar slip)
                abs_dest = _DATA_DIR.resolve()
                for member in tar.getmembers():
                    member_path = (abs_dest / member.name).resolve()
                    if not str(member_path).startswith(str(abs_dest)):
                        raise ValueError(f"Tar member escapes target dir: {member.name}")
                tar.extractall(path=_DATA_DIR)

        if (_MODELS_DIR / "model_manifest.json").is_file():
            _report(progress_callback, "Models ready.", 100)
            return True
        else:
            logger.error("model_manifest.json not found after extraction")
            return False
    except Exception as exc:
        logger.error("Model download failed: %s", exc)
        return False


def _download_file(
    url: str,
    dest: Path,
    progress_callback: Callable[[str, int], None] | None = None,
) -> None:
    """Download a file with progress reporting."""
    req = urllib.request.Request(url, headers={"User-Agent": f"SonoForge/{__version__}"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        chunk_size = 256 * 1024

        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    pct = int(downloaded * 70 / total) + 10  # 10-80% range
                    _report(
                        progress_callback,
                        f"Downloading... {downloaded // (1024 * 1024)}/{total // (1024 * 1024)} MB",
                        pct,
                    )


def _report(
    callback: Callable[[str, int], None] | None,
    message: str,
    progress: int,
) -> None:
    if callback is not None:
        try:
            callback(message, progress)
        except Exception:
            pass


# ── Qt Dialog ──


def show_setup_dialog() -> bool:
    """Show first-run setup dialog. Returns True if setup succeeded."""
    try:
        from PySide6.QtCore import Qt, QThread, Signal
        from PySide6.QtWidgets import (
            QDialog,
            QLabel,
            QProgressBar,
            QPushButton,
            QVBoxLayout,
        )
    except ImportError:
        # PySide6 not installed — must be running from venv already
        return True

    status = get_setup_status()
    if status.deps_installed and status.models_exist:
        return True

    # In frozen (PyInstaller) builds, deps are bundled — only download models.
    frozen = getattr(sys, "frozen", False)

    class SetupWorker(QThread):
        progress = Signal(str, int)
        finished = Signal(bool)

        def run(self) -> None:
            success = True
            if not frozen and not status.deps_installed:
                success = install_deps(progress_callback=lambda msg, pct: self.progress.emit(msg, pct))
            if success and not status.models_exist:
                success = download_models(progress_callback=lambda msg, pct: self.progress.emit(msg, pct))
            self.finished.emit(success)

    dialog = QDialog()
    dialog.setWindowTitle("SonoForge — First Run Setup")
    dialog.setMinimumWidth(450)
    dialog.setWindowFlags(dialog.windowFlags() & ~Qt.WindowContextHelpButtonHint)

    layout = QVBoxLayout(dialog)

    # Logo
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap

    _logo_path = Path(__file__).resolve().parent.parent / "resources" / "logo.png"
    if _logo_path.exists():
        logo_label = QLabel()
        pixmap = QPixmap(str(_logo_path))
        logo_label.setPixmap(pixmap.scaledToHeight(80, Qt.SmoothTransformation))
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(logo_label)

    title = QLabel("SonoForge is setting up for the first time.")
    title.setStyleSheet("font-size: 14px; font-weight: bold;")
    title.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(title)

    status_label = QLabel("Preparing...")
    layout.addWidget(status_label)

    progress_bar = QProgressBar()
    progress_bar.setRange(0, 100)
    layout.addWidget(progress_bar)

    skip_btn = QPushButton("Skip (run without AI segmentation)")
    skip_btn.clicked.connect(dialog.reject)
    layout.addWidget(skip_btn)

    worker = SetupWorker()
    worker.progress.connect(lambda msg, pct: (status_label.setText(msg), progress_bar.setValue(pct)))
    worker.finished.connect(lambda ok: dialog.accept() if ok else dialog.reject())

    dialog.show()
    worker.start()
    dialog.exec()

    return worker.isRunning() or not worker.isRunning()
