"""SonoForge launcher — finds Python, sets up venv, installs deps, runs the app."""

import locale
import os
import shutil
import subprocess
import sys
from pathlib import Path

APP_NAME = "SonoForge"
INSTALL_DIR = Path(__file__).resolve().parent
LIB_DIR = INSTALL_DIR / "lib"

# The launcher is also kept at the repository root for the lightweight builds.
# Resolve paths through the same module as the application, not a second
# platform-specific approximation.
for _package_root in (INSTALL_DIR / "src", LIB_DIR):
    if (_package_root / "echo_personal_tool").is_dir():
        sys.path.insert(0, str(_package_root))
        break

from echo_personal_tool.infrastructure.paths import (
    data_dir,
    migrate_legacy_paths,
    models_dir,
    models_dirs_for_read,
    venv_dir,
)

DATA_DIR = data_dir()
VENV_DIR = venv_dir()
MODELS_DIR = models_dir()
MODELS_URL = "https://github.com/areatu/sonoforge-models/releases/download/models-v1/models-v1.tar.gz"


# Mirrors requires-python in pyproject.toml (">=3.11,<3.14"). The same range is
# asserted by tests/unit/test_python_version_guard.py, so this launcher cannot
# silently accept an interpreter the package refuses to install under.
PYTHON_MIN = (3, 11)
PYTHON_MAX_EXCL = (3, 14)


def _is_russian() -> bool:
    language = (locale.getlocale()[0] or os.environ.get("LANG", "")).lower()
    return language.startswith("ru")


def _message(en: str, ru: str) -> str:
    return ru if _is_russian() else en


def find_python():
    """Find a CPython interpreter inside the supported requires-python range."""
    out_of_range = []
    for name in ("python", "python3"):
        path = shutil.which(name)
        if path:
            try:
                out = subprocess.check_output([path, "--version"], stderr=subprocess.STDOUT, text=True)
                parts = out.strip().split()
                if len(parts) == 2:
                    ver = parts[1].split(".")
                    major, minor = int(ver[0]), int(ver[1])
                    if PYTHON_MIN <= (major, minor) < PYTHON_MAX_EXCL:
                        return path
                    out_of_range.append(f"{path} ({major}.{minor})")
            except Exception:
                continue
    if out_of_range:
        detail = ", ".join(out_of_range)
        if _is_russian():
            print(f"[{APP_NAME}] Неподдерживаемая версия Python: требуется 3.11–3.13; обнаружено: {detail}")
        else:
            print(f"[{APP_NAME}] Unsupported Python: 3.11–3.13 is required; found: {detail}")
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
    """Install the lock-derived requirements with hash verification only."""
    marker = VENV_DIR / ".deps_installed"
    if marker.exists():
        return True
    pip = VENV_DIR / "Scripts" / "pip.exe"
    pins = LIB_DIR / "pinned-packages.txt"
    if not pins.is_file() or "--hash=sha256:" not in pins.read_text(encoding="utf-8"):
        raise RuntimeError("Hash-pinned requirements are missing; refusing an unpinned dependency install.")

    mode = os.environ.get("SONOFORGE_INSTALL_MODE", "online").strip().lower()
    args = [str(pip), "install", "--quiet", "--require-hashes"]
    if mode == "offline":
        wheelhouse = Path(os.environ.get("SONOFORGE_WHEELHOUSE", "")).expanduser()
        if not wheelhouse.is_dir():
            raise RuntimeError("Offline mode requires SONOFORGE_WHEELHOUSE to name a local wheelhouse directory.")
        args.extend(("--no-index", "--find-links", str(wheelhouse)))
    elif mode != "online":
        raise RuntimeError("SONOFORGE_INSTALL_MODE must be 'online' or 'offline'.")
    args.extend(("-r", str(pins)))
    print(f"[{APP_NAME}] Installing lock-pinned dependencies with SHA256 verification ({mode} mode)...")
    subprocess.check_call(args)
    marker.write_text("installed")
    print(f"[{APP_NAME}] Dependencies installed.")
    return True


def models_available():
    """Return whether models exist in the current or one-release legacy path."""
    return any((candidate / "model_manifest.json").is_file() for candidate in models_dirs_for_read())


def download_models():
    """Download AI models if not present."""
    if models_available():
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
        # Pinned digest from the application package; import lazily so a first
        # run does not pay for it when models are already present.
        from echo_personal_tool.infrastructure.runtime_setup import verify_models_archive

        print(f"[{APP_NAME}] Verifying archive checksum...")
        if not verify_models_archive(archive):
            archive.unlink(missing_ok=True)
            print(f"[{APP_NAME}] Model archive failed the SHA256 check; nothing was extracted.")
            print(f"[{APP_NAME}] Download it again, or install manually from {MODELS_URL}")
            return False
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
        print(
            _message(
                f"[{APP_NAME}] Python 3.11–3.13 is required (>= 3.11, < 3.14) but was not found.",
                f"[{APP_NAME}] Требуется Python 3.11–3.13 (>= 3.11, < 3.14); совместимая версия не найдена.",
            )
        )
        print()
        print(
            _message(
                "Install Python 3.11–3.13 from https://www.python.org/downloads/ and enable 'Add Python to PATH'.",
                "Установите Python 3.11–3.13: https://www.python.org/downloads/ и добавьте его в PATH.",
            )
        )
        if sys.stdin.isatty():
            input(_message("Press Enter to exit...", "Нажмите Enter для выхода..."))
        return 1

    # Check version for display
    out = subprocess.check_output([python_path, "--version"], stderr=subprocess.STDOUT, text=True)
    print(f"[{APP_NAME}] Using: {python_path} ({out.strip()})")

    for warning in migrate_legacy_paths():
        print(f"[{APP_NAME}] Path migration: {warning}", file=sys.stderr)

    try:
        create_venv(python_path)
        install_deps()
        download_models()
        launch_app()
    except (OSError, subprocess.CalledProcessError, RuntimeError) as exc:
        print(
            _message(
                f"[{APP_NAME}] Setup failed: {exc}",
                f"[{APP_NAME}] Ошибка настройки: {exc}",
            ),
            file=sys.stderr,
        )
        print(
            _message(
                "For offline installation, set SONOFORGE_INSTALL_MODE=offline and SONOFORGE_WHEELHOUSE to a prepared wheelhouse.",
                "Для установки без сети задайте SONOFORGE_INSTALL_MODE=offline и SONOFORGE_WHEELHOUSE с путём к wheelhouse.",
            ),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
