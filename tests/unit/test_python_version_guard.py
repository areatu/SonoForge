"""Guards the supported CPython range from drifting across launchers.

The 2026-10-22 audit (P1-4) found three disagreeing Python claims: pyproject
required ``>=3.11,<3.12`` while both shell/Python launchers accepted ``>=3.10``
and the ``.deb`` depended on ``python3 (>= 3.10)``. On Ubuntu 24.04/25.04 that
combination picked a Python the package then refused to install under, and the
user only saw a raw ``pip install`` traceback.

``requires-python`` in pyproject.toml stays the single source of truth. Every
other place that states the range must repeat it exactly, or this module fails.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from echo_personal_tool.infrastructure import runtime_setup as rs_mod

ROOT = Path(__file__).resolve().parents[2]
SUPPORTED_MIN = (3, 11)
SUPPORTED_MAX_EXCL = (3, 12)


def _requires_python() -> str:
    import tomllib

    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["requires-python"])


def _specifier_bounds() -> tuple[tuple[int, int], tuple[int, int]]:
    """Lower bound and exclusive upper bound declared by ``requires-python``."""
    spec = _requires_python()
    matches = re.findall(r"(>=|<=|>|<)\s*(\d+)\.(\d+)", spec)
    assert matches, f"unrecognised requires-python: {spec!r}"
    lower: tuple[int, int] | None = None
    upper: tuple[int, int] | None = None
    for operator, major, minor in matches:
        version = (int(major), int(minor))
        if operator == ">=":
            assert lower is None, f"duplicate lower bound in {spec!r}"
            lower = version
        elif operator == "<":
            assert upper is None, f"duplicate upper bound in {spec!r}"
            upper = version
        else:
            pytest.fail(
                f"requires-python {spec!r} uses {operator!r}; only '>=' / '<' are "
                "supported by this guard — extend it together with the launchers"
            )
    assert lower is not None and upper is not None, f"incomplete requires-python: {spec!r}"
    return lower, upper


def _version_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


class TestCheckPythonVersion:
    @pytest.mark.parametrize(
        ("version", "expected"),
        [
            ((3, 9, 18), False),
            ((3, 10, 14), False),  # floor raised 2026-10-22 for Pillow 13
            ((3, 11, 0), True),
            ((3, 11, 9), True),  # any 3.11.x patch level
            ((3, 12, 0), False),  # no numpy<2 wheel issue, package refuses it
            ((3, 13, 1), False),
            ((4, 0, 0), False),
        ],
    )
    def test_boundaries(self, version: tuple[int, ...], expected: bool) -> None:
        with patch.object(sys, "version_info", version):
            assert rs_mod.check_python_version() is expected

    def test_matches_requires_python(self) -> None:
        assert (rs_mod.PYTHON_MIN, rs_mod.PYTHON_MAX_EXCL) == _specifier_bounds()

    def test_current_interpreter_is_supported(self) -> None:
        assert rs_mod.check_python_version() is True


class TestLaunchersRepeatRequiresPython:
    """Every copy of the range must equal ``requires-python`` in pyproject."""

    def test_runtime_setup_constants(self) -> None:
        assert (rs_mod.PYTHON_MIN, rs_mod.PYTHON_MAX_EXCL) == _specifier_bounds()

    def test_linux_launcher_constants(self) -> None:
        text = (ROOT / "build" / "linux" / "sonoforge-launcher").read_text(encoding="utf-8")
        minimum = re.search(r'^PYTHON_MIN="([^"]+)"', text, re.MULTILINE)
        maximum = re.search(r'^PYTHON_MAX_EXCL="([^"]+)"', text, re.MULTILINE)
        assert minimum and maximum, "launcher no longer declares PYTHON_MIN/PYTHON_MAX_EXCL"
        assert _version_tuple(minimum.group(1)) == SUPPORTED_MIN
        assert _version_tuple(maximum.group(1)) == SUPPORTED_MAX_EXCL
        assert (_version_tuple(minimum.group(1)), _version_tuple(maximum.group(1))) == _specifier_bounds()

    def test_root_launcher_constants(self) -> None:
        text = (ROOT / "launcher.py").read_text(encoding="utf-8")
        minimum = re.search(r"^PYTHON_MIN = \((\d+), (\d+)\)", text, re.MULTILINE)
        maximum = re.search(r"^PYTHON_MAX_EXCL = \((\d+), (\d+)\)", text, re.MULTILINE)
        assert minimum and maximum, "launcher.py no longer declares PYTHON_MIN/PYTHON_MAX_EXCL"
        assert (
            (int(minimum.group(1)), int(minimum.group(2))),
            (int(maximum.group(1)), int(maximum.group(2))),
        ) == _specifier_bounds()

    def test_windows_launcher_accepts_only_supported_line(self) -> None:
        text = (ROOT / "build" / "windows" / "sonoforge-launcher.bat").read_text(encoding="utf-8")
        lower, upper = _specifier_bounds()
        assert f"if %PYMINOR% LSS {lower[1]} (" in text, "lower bound missing from .bat"
        assert f"if %PYMINOR% GEQ {upper[1]} (" in text, "upper bound missing from .bat"

    def test_deb_depends_floor(self) -> None:
        text = (ROOT / "build" / "linux" / "build-lite.sh").read_text(encoding="utf-8")
        lower, _ = _specifier_bounds()
        assert f"python3 (>= {lower[0]}.{lower[1]})" in text, "build-lite Depends floor is stale"
        assert "python3 (>= 3.10)" not in text, "stale Python 3.10 dependency"


def _extract_find_python() -> str:
    text = (ROOT / "build" / "linux" / "sonoforge-launcher").read_text(encoding="utf-8")
    start = text.index("find_python()")
    end = text.index("\n}\n", start) + len("\n}\n")
    return text[start:end]


def _stub_interpreter(directory: Path, name: str, version: str) -> None:
    path = directory / name
    path.write_text(f"#!/bin/sh\nprintf '%s\\n' {version}\n", encoding="utf-8")
    path.chmod(0o755)


def _run_find_python(tmp_path: Path, interpreters: dict[str, str]) -> subprocess.CompletedProcess:
    for name, version in interpreters.items():
        _stub_interpreter(tmp_path, name, version)
    lower, upper = _specifier_bounds()
    script = (
        "set -euo pipefail\n"
        f"PYTHON_MIN={lower[0]}.{lower[1]}\n"
        f"PYTHON_MAX_EXCL={upper[0]}.{upper[1]}\n"
        f"PY_MIN_MINOR={lower[1]}\n"
        f"PY_MAX_MINOR_EXCL={upper[1]}\n"
        f"{_extract_find_python()}\n"
        "find_python\n"
    )
    # PATH is only the stub directory: the launcher's own lookup must be the
    # sole source of interpreters, so the host's real Python cannot win.
    # bash itself is resolved first — with PATH overridden it could not be
    # located by name any more.
    bash = shutil.which("bash") or "/bin/bash"
    env = {**os.environ, "PATH": str(tmp_path)}
    return subprocess.run(
        [bash, "-c", textwrap.dedent(script)],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        check=False,
    )


class TestLinuxLauncherRejectsUnsupportedPython:
    def test_accepts_supported_interpreter(self, tmp_path: Path) -> None:
        result = _run_find_python(tmp_path, {"python3.11": "3.11"})
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "python3.11"

    def test_rejects_python_3_12(self, tmp_path: Path) -> None:
        result = _run_find_python(tmp_path, {"python3.12": "3.12"})
        assert result.returncode == 1
        assert result.stdout.strip() == ""
        assert "Python 3.11.x" in result.stderr
        assert "python3.12 (3.12)" in result.stderr

    def test_rejects_python_3_13(self, tmp_path: Path) -> None:
        result = _run_find_python(tmp_path, {"python3.13": "3.13"})
        assert result.returncode == 1
        assert result.stdout.strip() == ""
        assert "python3.13 (3.13)" in result.stderr, result.stderr

    def test_rejects_python_3_10(self, tmp_path: Path) -> None:
        # 3.10 was accepted before 2026-10-22 while pyproject already refused it.
        result = _run_find_python(tmp_path, {"python3.10": "3.10"})
        assert result.returncode == 1
        assert result.stdout.strip() == ""
        assert "python3.10 (3.10)" in result.stderr, result.stderr

    def test_rejects_bare_python3_when_out_of_range(self, tmp_path: Path) -> None:
        # Ubuntu 24.04 ships python3 -> 3.12: previously accepted, then `pip
        # install -e` failed on requires-python with a raw traceback.
        result = _run_find_python(tmp_path, {"python3": "3.12"})
        assert result.returncode == 1
        assert "python3 (3.12)" in result.stderr

    def test_prefers_supported_over_out_of_range(self, tmp_path: Path) -> None:
        result = _run_find_python(tmp_path, {"python3": "3.12", "python3.11": "3.11"})
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "python3.11"

    def test_no_interpreter_at_all(self, tmp_path: Path) -> None:
        result = _run_find_python(tmp_path, {})
        assert result.returncode == 1
        assert result.stdout.strip() == ""
        # Nothing was installed, so there is nothing to name as out of range;
        # the outer handler in the launcher prints the requirement itself.
        assert "found:" not in result.stderr
