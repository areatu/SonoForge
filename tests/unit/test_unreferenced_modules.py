"""The module dead-code ratchet without importing the Qt application."""

from __future__ import annotations

from pathlib import Path

from scripts.audit_unreferenced_modules import find_unreferenced_modules


def _write(path: Path, source: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def test_relative_imports_make_a_module_reachable(tmp_path: Path) -> None:
    package = tmp_path / "echo_personal_tool"
    _write(package / "__init__.py", "")
    _write(package / "__main__.py", "from . import feature\n")
    _write(package / "feature.py", "VALUE = 1\n")

    assert find_unreferenced_modules(package) == ()


def test_literal_dynamic_imports_are_included(tmp_path: Path) -> None:
    package = tmp_path / "echo_personal_tool"
    _write(package / "__init__.py", "")
    _write(package / "__main__.py", 'import importlib\nimportlib.import_module("echo_personal_tool.feature")\n')
    _write(package / "feature.py", "VALUE = 1\n")

    assert find_unreferenced_modules(package) == ()


def test_unreferenced_runtime_module_is_reported_but_entrypoint_is_not(tmp_path: Path) -> None:
    package = tmp_path / "echo_personal_tool"
    _write(package / "__init__.py", "")
    _write(package / "__main__.py", "from . import live\n")
    _write(package / "live.py", "VALUE = 1\n")
    _write(package / "dead.py", "VALUE = 2\n")

    assert find_unreferenced_modules(package) == ("echo_personal_tool.dead",)
