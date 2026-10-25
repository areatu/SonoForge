"""First run of the .deb installs a hash-verified dependency list (audit P1-3).

Before this change `build/linux/sonoforge-launcher` ran `pip install -e` and,
on failure, an unpinned package list resolved against whatever PyPI served that
day — unpinned, unreproducible, and failing without guidance when offline.

The build now generates ``pinned-packages.txt`` from ``uv.lock`` (versions +
every wheel/sdist hash) and the launcher installs it with
``pip install --require-hashes``. The file is generated, not committed:
``uv.lock`` stays the single reviewed source of truth.
"""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "build" / "linux" / "sonoforge-launcher"
BUILD = ROOT / "build" / "linux" / "build-lite.sh"
PINS_RELPATH = "opt/sonoforge/lib/pinned-packages.txt"
HEX64 = re.compile(r"--hash=sha256:([0-9a-f]{64})")
PIN_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*==\s*([^\s;#]+)")


def _launcher_text() -> str:
    return LAUNCHER.read_text(encoding="utf-8")


def _build_text() -> str:
    return BUILD.read_text(encoding="utf-8")


class TestBuildShipsAPinnedList:
    def test_windows_build_generates_hash_pins_and_fails_closed(self) -> None:
        text = (ROOT / "build" / "windows" / "build-lite.bat").read_text(encoding="utf-8")
        assert "uv export --locked --no-emit-project --format requirements-txt" in text
        assert "pinned-packages.txt" in text
        assert "refusing to produce an unpinned Windows package" in text

    def test_windows_launcher_checks_model_archive_and_uses_hash_pins(self) -> None:
        text = (ROOT / "build" / "windows" / "sonoforge-launcher.bat").read_text(encoding="utf-8")
        assert "--require-hashes -r" in text
        assert "--verify-models-archive" in text
        assert "SONOFORGE_INSTALL_MODE" in text

    def test_build_generates_pins_from_uv_lock(self) -> None:
        text = _build_text()
        assert "uv export --locked --no-emit-project" in text, "build must derive pins from uv.lock"
        assert "lib/pinned-packages.txt" in text, "pins must be written into the package"
        assert "command -v uv" in text, "the build must guard for a missing uv"

    def test_pins_are_not_committed_to_the_repo(self) -> None:
        # Generated at build time: uv.lock stays the only reviewed manifest, and
        # a second file in the repo would drift (see presenter_pins.py).
        assert not (ROOT / "build" / "linux" / "pinned-packages.txt").exists()

    def test_launcher_reads_the_shipped_pins(self) -> None:
        text = _launcher_text()
        assert 'PINS_FILE="${LIB_DIR}/pinned-packages.txt"' in text
        assert "--require-hashes -r" in text, "the first run must hash-verify every wheel"
        assert '--require-hashes -r "${PINS_FILE}"' in text

    def test_unpinned_fallback_is_forbidden(self) -> None:
        text = _launcher_text()
        assert "Refusing an unpinned install" in text
        assert "falling back to unpinned resolution" not in text
        assert "numpy<2" not in text

    def test_online_and_offline_modes_are_explicit(self) -> None:
        text = _launcher_text()
        assert "SONOFORGE_INSTALL_MODE" in text
        assert "SONOFORGE_WHEELHOUSE" in text
        assert "--no-index --find-links" in text
        assert "--require-hashes" in text


# ── behavioural: extract install_deps() and drive it with a stub pip ──


def _extract_install_deps() -> str:
    text = _launcher_text()
    start = text.index("install_deps() {")
    end = text.index("\n}\n", start) + len("\n}\n")
    return text[start:end]


def _run_install_deps(
    tmp_path: Path,
    *,
    pins: bool,
    req: bool,
    fail_editable: bool = False,
) -> tuple[int, list[list[str]]]:
    lib = tmp_path / "lib"
    lib.mkdir()
    if pins:
        (lib / "pinned-packages.txt").write_text(
            "numpy==1.26.4 \\\n    --hash=sha256:" + "a" * 64 + "\n",
            encoding="utf-8",
        )
    if req:
        (lib / "pyproject.toml").write_text("[project]\n", encoding="utf-8")

    log = tmp_path / "argv.log"
    stub = tmp_path / "pip"
    stub.write_text(
        textwrap.dedent(
            """\
            #!/bin/sh
            printf '%s\\n' "$*" >> "$STUB_LOG"
            case " $* " in
              *" -e "*)
                if [ "${STUB_FAIL_E:-0}" = "1" ]; then exit 1; fi
                ;;
            esac
            exit 0
            """
        ),
        encoding="utf-8",
    )
    stub.chmod(0o755)

    harness = (
        "set -uo pipefail\n"
        'info() { printf "info %s\\n" "$*"; }\n'
        'warn() { printf "warn %s\\n" "$*"; }\n'
        'err() { printf "err %s\\n" "$*" >&2; }\n'
        'PINS_FILE="$1"\n'
        'REQ_FILE="$2"\n'
        'LIB_DIR="$3"\n'
        'VENV_PIP="$4"\n'
        'export STUB_LOG="$5"\n'
        'export STUB_FAIL_E="${6:-0}"\n'
        f"{_extract_install_deps()}\n"
        "install_deps\n"
    )
    bash = shutil.which("bash") or "/bin/bash"
    harness_args = [
        str(lib / "pinned-packages.txt"),
        str(lib / "pyproject.toml"),
        str(lib),
        str(stub),
        str(log),
        "1" if fail_editable else "0",
    ]
    result = subprocess.run(
        [bash, "-c", textwrap.dedent(harness), "harness", *harness_args],
        capture_output=True,
        text=True,
        env=os.environ,
        timeout=60,
        check=False,
    )
    invocations = [line.split() for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
    return result.returncode, invocations


class TestInstallDepsBehaviour:
    def test_pins_present_installs_with_hashes(self, tmp_path: Path) -> None:
        code, invocations = _run_install_deps(tmp_path, pins=True, req=True)
        assert code == 0, "hash-verified install must succeed"
        assert len(invocations) == 1, invocations
        argv = invocations[0]
        assert "--require-hashes" in argv
        assert "-r" in argv
        assert argv[argv.index("-r") + 1].endswith("pinned-packages.txt")
        assert "-e" not in argv, "the .deb ships the code on PYTHONPATH; nothing must be installed editable"

    def test_pins_present_installs_keeping_hashes(self, tmp_path: Path) -> None:
        _, invocations = _run_install_deps(tmp_path, pins=True, req=False)
        assert invocations and "--require-hashes" in invocations[0]

    def test_missing_pins_fails_closed_without_pip(self, tmp_path: Path) -> None:
        code, invocations = _run_install_deps(tmp_path, pins=False, req=True)
        assert code == 1
        assert invocations == []

    def test_missing_pins_without_project_fails_closed(self, tmp_path: Path) -> None:
        code, invocations = _run_install_deps(tmp_path, pins=False, req=False)
        assert code == 1
        assert invocations == []


# ── the generated list must equal uv.lock ──


def _load_lock_module():
    spec = importlib.util.spec_from_file_location("presenter_pins", ROOT / "tools" / "release" / "presenter_pins.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _exported_entries() -> list[tuple[str, str, list[str]]]:
    """``[(name, version, hashes)]`` from the same command build-lite.sh runs."""
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is not installed")
    result = subprocess.run(
        [uv, "export", "--locked", "--no-emit-project", "--format", "requirements-txt"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    entries: list[tuple[str, str, list[str]]] = []
    buffer = ""
    for raw in result.stdout.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.endswith("\\"):
            buffer += line[:-1].strip() + " "
            continue
        buffer += line
        logical, buffer = buffer, ""
        hashes = HEX64.findall(logical)
        match = PIN_RE.match(logical)
        assert match, f"not a requirement line: {logical!r}"
        entries.append((match.group(1), match.group(2), hashes))
    if buffer.strip():
        pytest.fail(f"unterminated requirement continuation: {buffer!r}")
    assert entries, "uv export produced no packages"
    return entries


class TestGeneratedPinsMatchTheLock:
    def test_every_version_comes_from_uv_lock(self) -> None:
        lock_versions = _load_lock_module().lock_versions()
        for name, version, _ in _exported_entries():
            key = name.lower()
            assert version in lock_versions.get(key, set()), f"{name}=={version} is not what uv.lock resolves"

    def test_every_package_carries_at_least_one_hash(self) -> None:
        for name, version, hashes in _exported_entries():
            assert hashes, f"{name}=={version} has no sha256 hash; --require-hashes would refuse it"

    def test_full_closure_keeps_the_heavy_packages(self) -> None:
        names = {name for name, _, _ in _exported_entries()}
        # The .deb is the full profile: unlike Presenter it must keep these.
        for required in ("onnxruntime", "pyside6", "pyside6-addons", "pyside6-essentials", "pymupdf", "openpyxl"):
            assert required in names, f"{required} missing from the shipped dependency closure"

    def test_no_dev_tools_leak_into_the_shipped_list(self) -> None:
        names = {name for name, _, _ in _exported_entries()}
        for dev in ("pytest", "hypothesis", "coverage", "mypy", "ruff", "pyinstaller"):
            assert dev not in names, f"{dev} must not be installed on a user's machine at first run"
        assert "sonoforge" not in names, "the project itself runs via PYTHONPATH in the .deb"
