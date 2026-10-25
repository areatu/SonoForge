"""Runtime environment setup: dependency check, model download, first-run dialog."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import logging
import os
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
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
# Import names used for the runtime environment check — one import surface per
# direct runtime dependency in pyproject.toml. This is NOT an install
# manifest: installing distributions from these module names was the #326 bug
# class (`cv2`/`yaml` do not exist on PyPI). Installations use only the
# hash-pinned, lock-derived pinned-packages.txt (see install_deps).
_REQUIRED_MODULES = [
    "PySide6",
    "pyqtgraph",
    "pydicom",
    "pylibjpeg",
    "libjpeg",
    "openjpeg",
    "numpy",
    "scipy",
    "cv2",
    "httpx",
    "psutil",
    "fitz",
    "yaml",
    "jsonschema",
    "onnxruntime",
    "reportlab",
    "openpyxl",
    "keyring",
    "pynetdicom",
]
#: Required modules whose import name is not the distribution that ships them;
#: every other entry maps to the like-named distribution. Pinned against
#: uv.lock by tests so a dropped dependency cannot stay "required" here.
_MODULE_DISTRIBUTIONS = {
    "cv2": "opencv-python-headless",
    "fitz": "pymupdf",
    "libjpeg": "pylibjpeg-libjpeg",
    "openjpeg": "pylibjpeg-openjpeg",
    "yaml": "pyyaml",
}


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
    """Return True if all required modules are importable."""
    for module in _REQUIRED_MODULES:
        try:
            importlib.import_module(module)
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


def _pinned_requirements_file() -> Path | None:
    """Find the build-generated, lock-derived requirements shipped with a launcher."""
    configured = os.environ.get("SONOFORGE_PINNED_REQUIREMENTS")
    if configured:
        candidate = Path(configured).expanduser()
        return candidate if candidate.is_file() else None
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "pinned-packages.txt"
        if candidate.is_file():
            return candidate
    return None


def _dependency_install_args(requirements: Path) -> list[str] | None:
    """Build pip arguments for a pinned install; offline mode never queries an index."""
    args = ["install", "--quiet", "--require-hashes"]
    mode = os.environ.get("SONOFORGE_INSTALL_MODE", "online").strip().lower()
    if mode == "offline":
        wheelhouse = os.environ.get("SONOFORGE_WHEELHOUSE", "").strip()
        if not wheelhouse or not Path(wheelhouse).expanduser().is_dir():
            logger.error("offline mode requires SONOFORGE_WHEELHOUSE to name a local wheelhouse directory")
            return None
        args.extend(("--no-index", "--find-links", str(Path(wheelhouse).expanduser())))
    elif mode != "online":
        logger.error("SONOFORGE_INSTALL_MODE must be 'online' or 'offline', got %r", mode)
        return None
    args.extend(("-r", str(requirements)))
    return args


def _verify_installed_deps() -> bool:
    """Import every required module with the *venv* interpreter.

    ``install_deps`` runs in the launcher's interpreter, so a pip exit code 0
    is the only signal it gets; re-checking the imports inside the target
    venv turns "pip said ok but the environment is still broken" into an
    honest failure instead of a setup dialog that loops forever (#326).
    """
    python = _VENV_DIR / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if not python.is_file():
        logger.error("venv interpreter not found after install: %s", python)
        return False
    probe = "import importlib, sys; [importlib.import_module(name) for name in sys.argv[1:]]"
    try:
        result = subprocess.run([str(python), "-c", probe, *_REQUIRED_MODULES], capture_output=True, timeout=300)
    except (OSError, subprocess.SubprocessError) as exc:
        log_boundary_failure(logger, "runtime.setup", exc, code="io", level=logging.ERROR)
        return False
    if result.returncode != 0:
        logger.error("dependency verification failed in venv (exit %d)", result.returncode)
        return False
    return True


def install_deps(progress_callback: Callable[[str, int], None] | None = None) -> bool:
    """Install the lock-pinned requirements into the user venv.

    Lightweight packages ship ``pinned-packages.txt`` generated from ``uv.lock``.
    The default ``online`` mode uses the configured package index with pip's
    hash enforcement; ``offline`` requires a local wheelhouse and disables indexes.
    There is deliberately no unpinned fallback.
    """
    if not _VENV_DIR.is_dir():
        _report(progress_callback, "Creating virtual environment...", 5)
        try:
            subprocess.run(
                [sys.executable, "-m", "venv", str(_VENV_DIR)],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as exc:
            log_boundary_failure(logger, "runtime.setup", exc, code="io", level=logging.ERROR)
            return False

    requirements = _pinned_requirements_file()
    if requirements is None:
        logger.error("pinned-packages.txt is missing; refusing an unpinned dependency install")
        _report(progress_callback, "Pinned dependency list is missing; reinstall SonoForge.", 0)
        return False

    pip = _VENV_DIR / ("Scripts/pip.exe" if sys.platform == "win32" else "bin/pip")
    if not pip.is_file():
        logger.error("pip not found in venv: %s", pip)
        return False

    args = _dependency_install_args(requirements)
    if args is None:
        _report(progress_callback, "Dependency install mode is invalid or offline wheelhouse is missing.", 0)
        return False

    mode = os.environ.get("SONOFORGE_INSTALL_MODE", "online").strip().lower()
    _report(progress_callback, f"Installing hash-verified dependencies ({mode} mode)...", 20)
    try:
        subprocess.run([str(pip), *args], check=True, capture_output=True)
        if not _verify_installed_deps():
            _report(progress_callback, "Dependencies installed but verification failed; reinstall SonoForge.", 0)
            return False
        _report(progress_callback, "Dependencies installed.", 90)
        return True
    except subprocess.CalledProcessError as exc:
        log_boundary_failure(logger, "runtime.setup", exc, code="io", level=logging.ERROR)
        _report(progress_callback, "Dependency installation failed; check network or wheelhouse.", 0)
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
                members = tar.getmembers()
                for member in members:
                    member_path = (abs_dest / member.name).resolve()
                    try:
                        member_path.relative_to(abs_dest)
                    except ValueError as exc:
                        raise ValueError(f"Tar member escapes target dir: {member.name}") from exc
                    if member.issym() or member.islnk() or member.isdev():
                        raise ValueError(f"Unsupported tar member type: {member.name}")
                # Extract each validated regular file/directory individually.
                for member in members:
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


_MODELS_DOWNLOAD_HOSTS = frozenset({"github.com"})


def _validate_download_url(url: str) -> str:
    """Return *url* unchanged when it is the expected download endpoint.

    The only download in this module is the pinned GitHub Releases model
    archive, so anything that is not https on the release host is a
    programming error rather than user input — refuse before opening a
    socket (#324/B310). Redirect targets GitHub serves stay covered by the
    ``MODELS_RELEASE_SHA256`` check that runs before extraction.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in _MODELS_DOWNLOAD_HOSTS:
        raise ValueError(f"refusing unexpected download URL: {parsed.scheme}://{parsed.hostname or ''}")
    return url


def _download_file(
    url: str,
    dest: Path,
    progress_callback: Callable[[str, int], None] | None = None,
) -> None:
    """Download a file with progress reporting."""
    _validate_download_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": f"SonoForge/{__version__}"})
    # Scheme/host validated above; the payload is SHA256-verified before use.
    with urllib.request.urlopen(req, timeout=120) as resp:  # nosec B310
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
    output.add_argument("--verify-models-archive", metavar="PATH")
    args = parser.parse_args()

    if args.print_models_sha256:
        print(MODELS_RELEASE_SHA256)  # noqa: T201 - this module is a setup CLI
        return 0
    if args.verify_models_archive:
        try:
            verified = verify_models_archive(Path(args.verify_models_archive))
        except OSError as exc:
            log_boundary_failure(logger, "runtime.setup", exc, code="io", level=logging.ERROR)
            return 1
        if verified:
            return 0
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(_main())
