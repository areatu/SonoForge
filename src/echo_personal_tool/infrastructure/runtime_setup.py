"""Runtime environment setup: dependency check, model download, first-run dialog."""

from __future__ import annotations

import argparse
import hashlib
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
from echo_personal_tool.infrastructure.paths import (
    data_dir,
    models_dir,
    models_dirs_for_read,
    venv_dir,
)
from echo_personal_tool.infrastructure.safe_diagnostics import log_boundary_failure

logger = logging.getLogger(__name__)

_MODELS_RELEASE_URL = "https://github.com/areatu/sonoforge-models/releases/download/models-v1/models-v1.tar.gz"
#: SHA256 of that exact release asset, taken from the GitHub Releases asset
#: digest (`models-v1/models-v1.tar.gz`, 311779131 bytes), which GitHub computes
#: at upload time. Pinning it here means a truncated or substituted archive is
#: rejected *before* extraction instead of being unpacked into the data
#: directory. Re-uploading the asset is an integrity event and must update this
#: value; tests/unit/test_models_release_integrity.py checks the shape and the
#: launchers that verify against it.
MODELS_RELEASE_SHA256 = "cebaf1f2c80a1853a5e355246eefa50ffbb0b6bd1ff35b2964533703ed50825d"
_DATA_DIR = data_dir()
_VENV_DIR = venv_dir()
_MODELS_DIR = models_dir()

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


#: Exclusive interpreter bounds: the open CPython range is ``[PYTHON_MIN,
#: PYTHON_MAX_EXCL)``. This mirrors ``requires-python = ">=3.11,<3.12"`` in
#: pyproject.toml. ``tests/unit/test_python_version_guard.py`` fails CI when the
#: two drift, so this stays a checked mirror rather than a second hand-made truth.
PYTHON_MIN = (3, 11)
PYTHON_MAX_EXCL = (3, 12)


def check_python_version() -> bool:
    """Return True only for an interpreter inside ``requires-python``."""
    version = sys.version_info[:2]
    return PYTHON_MIN <= version < PYTHON_MAX_EXCL


def check_deps() -> bool:
    """Return True if all required packages are importable."""
    for pkg in _REQUIRED_PACKAGES:
        try:
            importlib.import_module(pkg)
        except ImportError:
            return False
    return True


def check_models() -> bool:
    """Return True if the manifest exists in the canonical or legacy models dir."""
    candidates = dict.fromkeys((_MODELS_DIR, *models_dirs_for_read()))
    return any((candidate / "model_manifest.json").is_file() for candidate in candidates)


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
        log_boundary_failure(logger, "runtime.setup", exc, code="io", level=logging.ERROR)
        return False


def verify_models_archive(archive: Path) -> bool:
    """Return True when an archive hashes to ``MODELS_RELEASE_SHA256``.

    Called before extraction: the download stays untrusted until it matches the
    pinned release digest, so a truncated or substituted tarball never reaches
    the data directory.
    """
    digest = hashlib.sha256()
    with archive.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual != MODELS_RELEASE_SHA256:
        logger.error(
            "model archive SHA256 mismatch: expected %s..., got %s...",
            MODELS_RELEASE_SHA256[:16],
            actual[:16],
        )
        return False
    return True


def download_models(progress_callback: Callable[[str, int], None] | None = None) -> bool:
    """Download and extract models from GitHub Releases. Returns True on success."""
    _MODELS_DIR.mkdir(parents=True, exist_ok=True)

    _report(progress_callback, "Downloading models...", 10)
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            archive = Path(tmp_dir) / "models.tar.gz"
            _download_file(_MODELS_RELEASE_URL, archive, progress_callback)

            _report(progress_callback, "Verifying archive...", 80)
            if not verify_models_archive(archive):
                logger.error("refusing to extract: model archive failed the SHA256 check")
                return False

            _report(progress_callback, "Extracting models...", 85)
            with tarfile.open(archive, "r:gz") as tar:
                # Validate all members stay within target directory (prevent tar slip)
                abs_dest = _DATA_DIR.resolve()
                for member in tar.getmembers():
                    member_path = (abs_dest / member.name).resolve()
                    if not str(member_path).startswith(str(abs_dest)):
                        raise ValueError(f"Tar member escapes target dir: {member.name}")
                # Extract each member individually (safer than extractall)
                for member in tar.getmembers():
                    tar.extract(member, path=_DATA_DIR)

        if (_MODELS_DIR / "model_manifest.json").is_file():
            _report(progress_callback, "Models ready.", 100)
            return True
        else:
            logger.error("model_manifest.json not found after extraction")
            return False
    except Exception as exc:
        log_boundary_failure(logger, "runtime.setup", exc, code="io", level=logging.ERROR)
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
        except Exception as exc:  # noqa: BLE001
            log_boundary_failure(logger, "runtime.setup", exc, code="unexpected", level=logging.DEBUG)


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
    dialog.setWindowFlags(dialog.windowFlags() & ~Qt.WindowContextHelpButtonHint)  # type: ignore

    layout = QVBoxLayout(dialog)

    # Logo
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap

    _logo_path = Path(__file__).resolve().parent.parent / "resources" / "logo.png"
    if _logo_path.exists():
        logo_label = QLabel()
        pixmap = QPixmap(str(_logo_path))
        logo_label.setPixmap(pixmap.scaledToHeight(80, Qt.SmoothTransformation))  # type: ignore
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
    worker.progress.connect(lambda msg, pct: (status_label.setText(msg), progress_bar.setValue(pct)))  # type: ignore
    worker.finished.connect(lambda ok: dialog.accept() if ok else dialog.reject())

    dialog.show()
    worker.start()
    dialog.exec()

    return worker.isRunning() or not worker.isRunning()


def _main() -> int:
    """Small CLI so the shell launcher can read the pinned release digest.

    ``build/linux/sonoforge-launcher`` verifies the model archive with this
    value instead of repeating the literal, which would be a second place to
    keep in sync.
    """
    parser = argparse.ArgumentParser(description="SonoForge runtime setup helpers")
    output = parser.add_mutually_exclusive_group(required=True)
    output.add_argument("--print-models-sha256", action="store_true")
    args = parser.parse_args()

    if args.print_models_sha256:
        print(MODELS_RELEASE_SHA256)  # noqa: T201 - this module is a setup CLI
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
