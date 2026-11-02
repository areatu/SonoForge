"""``locked_version.py``: marker-split aware pin selection (S3-02 / #311).

The lint job installs its tools straight from ``uv.lock`` without a full
``uv sync``; since numpy went 2.x the lock resolves two versions across the
supported Python range (2.4.6 below 3.12, 2.5.4 from it), so the script must
pick the pin for the interpreter that will install it — and fail loudly when
that pick is ambiguous or the marker cannot be evaluated.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github" / "scripts" / "locked_version.py"
LOCK = ROOT / "uv.lock"


def _load_module():
    spec = importlib.util.spec_from_file_location("locked_version_under_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


locked_version = _load_module()


def _numpy_package(version: str, *markers: str) -> str:
    block = f'[[package]]\nname = "numpy"\nversion = "{version}"\n'
    if markers:
        listed = ",\n".join(f'    "{marker}"' for marker in markers)
        block += f"resolution-markers = [\n{listed},\n]\n"
    return block


def _lock(tmp_path: Path, *packages: str) -> Path:
    path = tmp_path / "uv.lock"
    path.write_text("version = 1\n" + "\n".join(packages), encoding="utf-8")
    return path


class TestSingleVersion:
    def test_prints_the_only_pin_without_any_selection(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        lock = _lock(tmp_path, _numpy_package("1.26.4"))
        assert locked_version.main(["numpy", "--lock", str(lock)]) == 0
        assert capsys.readouterr().out.strip() == "1.26.4"

    def test_absent_distribution_fails(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        lock = _lock(tmp_path, _numpy_package("1.26.4"))
        assert locked_version.main(["scipy", "--lock", str(lock)]) == 1
        assert "not pinned" in capsys.readouterr().err


class TestMarkerSplit:
    def test_explicit_python_selects_its_pin(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        lock = _lock(
            tmp_path,
            _numpy_package("2.4.6", "python_full_version < '3.12'"),
            _numpy_package("2.5.4", "python_full_version >= '3.12'"),
        )
        assert locked_version.main(["numpy", "--lock", str(lock), "--python-version", "3.11"]) == 0
        assert capsys.readouterr().out.strip() == "2.4.6"
        assert locked_version.main(["numpy", "--lock", str(lock), "--python-version", "3.13"]) == 0
        assert capsys.readouterr().out.strip() == "2.5.4"

    def test_default_is_the_running_interpreter(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        # '99' is above every real interpreter, so the first package is the
        # one any running Python selects — the assertion is deterministic.
        lock = _lock(
            tmp_path,
            _numpy_package("2.4.6", "python_full_version < '99'"),
            _numpy_package("2.5.4", "python_full_version >= '99'"),
        )
        assert locked_version.main(["numpy", "--lock", str(lock)]) == 0
        assert capsys.readouterr().out.strip() == "2.4.6"

    def test_real_uv_lock_numpy_split(self, capsys: pytest.CaptureFixture[str]) -> None:
        # The actual pins of the S3-02 lock; update deliberately at a numpy
        # bump (the same way the presenter pins pin their scipy).
        assert locked_version.main(["numpy", "--lock", str(LOCK), "--python-version", "3.11"]) == 0
        assert capsys.readouterr().out.strip() == "2.4.6"
        assert locked_version.main(["numpy", "--lock", str(LOCK), "--python-version", "3.13"]) == 0
        assert capsys.readouterr().out.strip() == "2.5.4"

    def test_real_uv_lock_resolution_markers_are_honestly_evaluated(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Verbatim resolution-markers from uv.lock (parens, and/or, platform
        # atoms): exactly one candidate may survive on any CI platform.
        lock = _lock(
            tmp_path,
            _numpy_package(
                "2.4.6",
                "python_full_version < '3.12' and sys_platform == 'darwin'",
                "python_full_version < '3.12' and platform_machine == 'aarch64' and sys_platform == 'linux'",
                "(python_full_version < '3.12' and platform_machine != 'aarch64' and sys_platform == 'linux') "
                "or (python_full_version < '3.12' and sys_platform != 'darwin' and sys_platform != 'linux')",
            ),
            _numpy_package(
                "2.5.4",
                "python_full_version >= '3.12' and sys_platform == 'darwin'",
                "python_full_version >= '3.12' and platform_machine == 'aarch64' and sys_platform == 'linux'",
                "(python_full_version >= '3.12' and platform_machine != 'aarch64' and sys_platform == 'linux') "
                "or (python_full_version >= '3.12' and sys_platform != 'darwin' and sys_platform != 'linux')",
            ),
        )
        assert locked_version.main(["numpy", "--lock", str(lock), "--python-version", "3.11"]) == 0
        assert capsys.readouterr().out.strip() == "2.4.6"
        assert locked_version.main(["numpy", "--lock", str(lock), "--python-version", "3.13"]) == 0
        assert capsys.readouterr().out.strip() == "2.5.4"

    def test_two_applicable_candidates_fail_loudly(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        lock = _lock(
            tmp_path,
            _numpy_package("2.4.6", "python_full_version >= '3.11'"),
            _numpy_package("2.5.4", "python_full_version >= '3.11'"),
        )
        assert locked_version.main(["numpy", "--lock", str(lock), "--python-version", "3.11"]) == 1
        err = capsys.readouterr().err
        assert "several versions" in err
        assert "2.4.6" in err and "2.5.4" in err

    def test_no_applicable_candidate_fails_loudly(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        lock = _lock(
            tmp_path,
            _numpy_package("2.4.6", "python_full_version < '3.11'"),
            _numpy_package("2.5.4", "python_full_version >= '3.14'"),
        )
        assert locked_version.main(["numpy", "--lock", str(lock), "--python-version", "3.12"]) == 1
        assert "matches nothing" in capsys.readouterr().err

    def test_unknown_marker_variable_fails_loudly(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        lock = _lock(
            tmp_path,
            _numpy_package("2.4.6", "python_full_version < '3.12'"),
            _numpy_package("2.5.4", "python_implementation == 'CPython'"),
        )
        assert locked_version.main(["numpy", "--lock", str(lock), "--python-version", "3.11"]) == 1
        assert "unknown marker variable" in capsys.readouterr().err

    def test_unparsable_marker_fails_loudly(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        lock = _lock(
            tmp_path,
            _numpy_package("2.4.6", "python_full_version <"),
            _numpy_package("2.5.4", "python_full_version >= '3.12'"),
        )
        assert locked_version.main(["numpy", "--lock", str(lock), "--python-version", "3.11"]) == 1
        assert "failed" in capsys.readouterr().err


class TestMarkerEvaluation:
    def test_version_ordering_is_numeric_not_lexical(self) -> None:
        env = locked_version.target_env("3.10")
        assert locked_version.marker_applies("python_version < '3.9'", env) is False
        assert locked_version.marker_applies("python_version >= '3.9'", env) is True
        assert locked_version.marker_applies("python_full_version > '3.9.2'", env) is True

    def test_boolean_structure_and_quoted_strings(self) -> None:
        env = locked_version.target_env("3.11.9")
        assert locked_version.marker_applies("sys_platform == 'linux' and python_version == '3.11'", env) == (
            env["sys_platform"] == "linux"
        )
        assert locked_version.marker_applies("(python_version < '3.11' or python_version >= '3.11')", env) is True
        assert locked_version.marker_applies("sys_platform != 'darwin'", env) is not (env["sys_platform"] == "darwin")
