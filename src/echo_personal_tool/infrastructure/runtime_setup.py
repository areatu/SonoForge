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
    "pymupdf",
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
    "libjpeg": "pylibjpeg-libjpeg",
    "openjpeg": "pylibjpeg-openjpeg",
    "yaml": "pyyaml",
}

#: Every way ``install_deps`` can fail, with the one sentence a user gets.
#: The keys are stable reason codes: they go to the log, the sentences go to
#: the first-run dialog. pip's own output never reaches the user — it names
#: paths, indexes and hashes, and a traceback in a setup dialog is a support
#: ticket, not a next step (#326).
_INSTALL_FAILURE_MESSAGES = {
    "venv_failed": "Could not create the application environment; check free disk space and permissions.",
    "pins_missing": "Pinned dependency list is missing; reinstall SonoForge.",
    "pip_missing": "The application environment has no installer; reinstall SonoForge.",
    "mode_invalid": "Dependency install mode is invalid or the offline wheelhouse is missing.",
    "pip_failed": "Dependency installation failed; check the network connection or the wheelhouse.",
    "pip_failed_network": "Could not reach the package index; check the connection and retry.",
    "pip_failed_hash": "A downloaded package failed the integrity check; retry, then reinstall SonoForge.",
    "pip_failed_unavailable": "A required package is not offered by the configured package index.",
    "verify_failed": "Dependencies installed but verification failed; reinstall SonoForge.",
}


def _pip_failure_reason(stderr: bytes | str | None) -> str:
    """Classify pip's captured output into a stable reason code.

    Only the class is ever surfaced; the text itself stays out of the dialog
    and out of the log (it embeds user paths and index URLs).
    """
    if stderr is None:
        return "pip_failed"
    text = stderr.decode("utf-8", "replace") if isinstance(stderr, bytes) else stderr
    lowered = text.lower()
    if "hash mismatch" in lowered or "do not match the hashes" in lowered or "these packages do not match" in lowered:
        return "pip_failed_hash"
    if any(
        marker in lowered
        for marker in (
            "temporary failure in name resolution",
            "connectionerror",
            "connection reset",
            "connection aborted",
            "newconnectionerror",
            "proxyerror",
            "sslerror",
            "timed out",
            "network is unreachable",
        )
    ):
        return "pip_failed_network"
    if "no matching distribution" in lowered or "could not find a version" in lowered:
        return "pip_failed_unavailable"
    return "pip_failed"


def _report_install_failure(
    progress_callback: Callable[[str, int], None] | None,
    reason: str,
) -> bool:
    """Log the reason code, tell the user one sentence, and report failure."""
    logger.error("dependency setup failed: %s", reason)
    _report(progress_callback, _INSTALL_FAILURE_MESSAGES[reason], 0)
    return False


@dataclass
class SetupStatus:
    venv_exists: bool
    deps_installed: bool
    models_exist: bool
    python_ok: bool


#: Exclusive interpreter bounds: the open CPython range is ``[PYTHON_MIN,
#: PYTHON_MAX_EXCL)``. This mirrors ``requires-python = ">=3.11,<3.14"`` in
#: pyproject.toml (widened to 3.13 by S3-02 / #311). ``tests/unit/test_python_version_guard.py`` fails CI when the
#: two drift, so this stays a checked mirror rather than a second hand-made truth.
PYTHON_MIN = (3, 11)
PYTHON_MAX_EXCL = (3, 14)


def check_python_version() -> bool:
    """Return True only for an interpreter inside ``requires-python``."""
    version = sys.version_info[:2]
    return PYTHON_MIN <= version < PYTHON_MAX_EXCL


def check_deps() -> bool:
    """Return True if all required modules are importable.

    ``OSError`` counts as missing too: a wheel that is installed but cannot load
    its shared library (a missing ``libGL``/VC runtime, a truncated native
    extension) is not a working dependency, and reporting it as present is how
    a first-run dialog ends up claiming success over a broken environment.
    """
    for module in _REQUIRED_MODULES:
        try:
            importlib.import_module(module)
        except (ImportError, OSError) as exc:
            logger.debug("required module %s is not importable: %s", module, type(exc).__name__)
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
    There is deliberately no unpinned fallback: the module-name list that used
    to be handed to pip (``cv2``, ``yaml``) does not exist as distributions
    (#326), and a half-populated venv is worse than a clear failure.

    Idempotent by construction: an existing venv with the full closure just
    re-runs the hash-pinned install, which pip turns into a no-op, and the
    post-install probe confirms the result either way.
    """
    if not _VENV_DIR.is_dir():
        _report(progress_callback, "Creating virtual environment...", 5)
        try:
            subprocess.run(
                [sys.executable, "-m", "venv", str(_VENV_DIR)],
                check=True,
                capture_output=True,
            )
        except (subprocess.CalledProcessError, OSError) as exc:
            log_boundary_failure(logger, "runtime.setup", exc, code="io", level=logging.ERROR)
            return _report_install_failure(progress_callback, "venv_failed")

    requirements = _pinned_requirements_file()
    if requirements is None:
        return _report_install_failure(progress_callback, "pins_missing")

    pip = _VENV_DIR / ("Scripts/pip.exe" if sys.platform == "win32" else "bin/pip")
    if not pip.is_file():
        return _report_install_failure(progress_callback, "pip_missing")

    args = _dependency_install_args(requirements)
    if args is None:
        return _report_install_failure(progress_callback, "mode_invalid")

    mode = os.environ.get("SONOFORGE_INSTALL_MODE", "online").strip().lower()
    _report(progress_callback, f"Installing hash-verified dependencies ({mode} mode)...", 20)
    try:
        subprocess.run([str(pip), *args], check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        log_boundary_failure(logger, "runtime.setup", exc, code="io", level=logging.ERROR)
        return _report_install_failure(progress_callback, _pip_failure_reason(getattr(exc, "stderr", None)))
    except OSError as exc:
        log_boundary_failure(logger, "runtime.setup", exc, code="io", level=logging.ERROR)
        return _report_install_failure(progress_callback, "pip_missing")

    if not _verify_installed_deps():
        return _report_install_failure(progress_callback, "verify_failed")
    _report(progress_callback, "Dependencies installed.", 90)
    return True


def run_setup_tasks(
    status: SetupStatus,
    progress_callback: Callable[[str, int], None] | None = None,
    *,
    frozen: bool | None = None,
) -> bool:
    """Run the first-run tasks described by *status*; True only on full success.

    Dependencies go before models because a missing dependency makes the model
    extraction pointless, and the first failure stops the sequence: a partial
    setup that keeps going reports progress over an environment it knows is
    broken. ``frozen`` builds ship their dependencies inside the executable, so
    only the model download applies there.
    """
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    success = True
    if not frozen and not status.deps_installed:
        success = install_deps(progress_callback)
    if success and not status.models_exist:
        success = download_models(progress_callback)
    return success


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

        def __init__(self) -> None:
            super().__init__()
            #: Outcome of the run; ``None`` until ``run`` returns. The dialog
            #: used to answer ``worker.isRunning() or not worker.isRunning()``,
            #: i.e. always True, so a failed setup still looked successful to
            #: the caller (#326).
            self.result: bool | None = None

        def run(self) -> None:
            self.result = run_setup_tasks(
                status,
                lambda msg, pct: self.progress.emit(msg, pct),
                frozen=frozen,
            )
            self.finished.emit(self.result)

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
    worker.progress.connect(lambda msg, pct: (status_label.setText(msg), progress_bar.setValue(pct)))  # type: ignore
    worker.finished.connect(lambda ok: dialog.accept() if ok else dialog.reject())

    dialog.show()
    worker.start()
    dialog.exec()

    # A download or a pip run cannot be interrupted once started, so closing
    # the dialog early must not abandon the thread (and the half-written data
    # directory) behind a "success" answer: wait for it, then report what
    # actually happened.
    if worker.isRunning():
        worker.wait(600_000)
    return worker.result is True


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
