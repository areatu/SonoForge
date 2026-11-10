"""Tests for the per-file/per-code mypy presentation ratchet and #476 strict slice."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import tomllib

_REPO_ROOT = Path(__file__).parents[2]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "check_mypy_presentation.py"

_spec = importlib.util.spec_from_file_location("check_mypy_presentation", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
ratchet = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = ratchet
_spec.loader.exec_module(ratchet)


def _setup_fake_repo(tmp_path: Path) -> tuple[Path, Path, Path]:
    pres = tmp_path / "src" / "echo_personal_tool" / "presentation"
    pres.mkdir(parents=True)
    (pres / "__init__.py").write_text("", encoding="utf-8")
    (pres / "clean_leaf.py").write_text("x: int = 1\n", encoding="utf-8")
    (pres / "dirty_view.py").write_text("def f(a):\n    return a\n", encoding="utf-8")
    (pres / "blocked_caller.py").write_text(
        "from echo_personal_tool.presentation import dirty_view\n",
        encoding="utf-8",
    )

    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[tool.mypy]\nfiles = [\n    "src/echo_personal_tool/domain",\n'
        '    "src/echo_personal_tool/presentation/__init__.py",\n'
        '    "src/echo_personal_tool/presentation/clean_leaf.py",\n]\n',
        encoding="utf-8",
    )

    baseline = tmp_path / "mypy_presentation_baseline.json"
    ratchet.write_baseline(
        baseline,
        {"src/echo_personal_tool/presentation/dirty_view.py": {"no-untyped-def": 1}},
    )
    return pres, pyproject, baseline


def test_committed_baseline_and_pyproject_coverage_are_consistent() -> None:
    """#476: ui, constructor, and >=58 presentation modules are in [tool.mypy].files; baseline is valid."""
    pyproject_path = _REPO_ROOT / "pyproject.toml"
    baseline_path = _REPO_ROOT / "scripts" / "mypy_presentation_baseline.json"
    pres_root = _REPO_ROOT / "src" / "echo_personal_tool" / "presentation"

    config = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    mypy_files: list[str] = config["tool"]["mypy"]["files"]
    assert "src/echo_personal_tool/ui" in mypy_files
    assert "src/echo_personal_tool/constructor" in mypy_files

    all_pres = ratchet.presentation_files(pres_root)
    strict_covered = ratchet.strict_presentation_files(pyproject_path, all_pres)
    assert len(strict_covered) >= 58, f"expected >=58 strict presentation modules, got {len(strict_covered)}"

    data, problems = ratchet.load_baseline(baseline_path, set(all_pres))
    assert problems == []
    raw_files = data.get("files")
    assert isinstance(raw_files, dict)
    baseline_files = set(raw_files)
    assert strict_covered.isdisjoint(baseline_files)
    # ViewerWidget and MainWindow stay in the baseline until #478/#479 finish decomposing them.
    assert "src/echo_personal_tool/presentation/viewer_widget.py" in baseline_files
    assert "src/echo_personal_tool/presentation/main_window.py" in baseline_files


def test_matching_mypy_output_passes(tmp_path: Path) -> None:
    pres, pyproject, baseline = _setup_fake_repo(tmp_path)
    out = tmp_path / "mypy.txt"
    out.write_text(
        "src/echo_personal_tool/presentation/dirty_view.py:1: error: "
        "Function is missing a type annotation  [no-untyped-def]\n",
        encoding="utf-8",
    )

    rc = ratchet.main(
        ["--root", str(pres), "--pyproject", str(pyproject), "--baseline", str(baseline), "--mypy-output", str(out)]
    )
    assert rc == 0


def test_new_error_in_zero_ceiling_file_fails(tmp_path: Path) -> None:
    pres, pyproject, baseline = _setup_fake_repo(tmp_path)
    out = tmp_path / "mypy.txt"
    out.write_text(
        "src/echo_personal_tool/presentation/dirty_view.py:1: error: Missing  [no-untyped-def]\n"
        "src/echo_personal_tool/presentation/blocked_caller.py:2: error: Oops  [attr-defined]\n",
        encoding="utf-8",
    )

    rc = ratchet.main(
        ["--root", str(pres), "--pyproject", str(pyproject), "--baseline", str(baseline), "--mypy-output", str(out)]
    )
    assert rc == 1


def test_decreased_count_requires_fix_on_311_and_passes_ceiling_on_312(tmp_path: Path) -> None:
    pres, pyproject, baseline = _setup_fake_repo(tmp_path)
    ratchet.write_baseline(
        baseline,
        {"src/echo_personal_tool/presentation/dirty_view.py": {"no-untyped-def": 2}},
    )
    out = tmp_path / "mypy.txt"
    out.write_text(
        "src/echo_personal_tool/presentation/dirty_view.py:1: error: Missing  [no-untyped-def]\n",
        encoding="utf-8",
    )

    rc_exact = ratchet.main(
        ["--root", str(pres), "--pyproject", str(pyproject), "--baseline", str(baseline), "--mypy-output", str(out)]
    )
    rc_ceiling = ratchet.main(
        [
            "--root",
            str(pres),
            "--pyproject",
            str(pyproject),
            "--baseline",
            str(baseline),
            "--mypy-output",
            str(out),
            "--python-version",
            "3.12",
        ]
    )
    assert rc_exact == 1
    assert rc_ceiling == 0


def test_zero_error_module_graduates_to_pyproject_via_fix(tmp_path: Path) -> None:
    pres, pyproject, baseline = _setup_fake_repo(tmp_path)
    out = tmp_path / "mypy.txt"
    out.write_text("", encoding="utf-8")

    # Without --fix, the newly 0-error modules fail as unpromoted/decreased.
    assert (
        ratchet.main(
            ["--root", str(pres), "--pyproject", str(pyproject), "--baseline", str(baseline), "--mypy-output", str(out)]
        )
        == 1
    )

    # --fix promotes both dirty_view.py and blocked_caller.py to [tool.mypy].files and empties baseline.
    assert (
        ratchet.main(
            [
                "--root",
                str(pres),
                "--pyproject",
                str(pyproject),
                "--baseline",
                str(baseline),
                "--mypy-output",
                str(out),
                "--fix",
            ]
        )
        == 0
    )
    configured = set(tomllib.loads(pyproject.read_text(encoding="utf-8"))["tool"]["mypy"]["files"])
    assert "src/echo_personal_tool/presentation/dirty_view.py" in configured
    assert "src/echo_personal_tool/presentation/blocked_caller.py" in configured
    refreshed = json.loads(baseline.read_text(encoding="utf-8"))
    assert refreshed["total_errors"] == 0
    assert refreshed["files"] == {}

    # Subsequent check passes cleanly.
    assert (
        ratchet.main(
            ["--root", str(pres), "--pyproject", str(pyproject), "--baseline", str(baseline), "--mypy-output", str(out)]
        )
        == 0
    )


def test_constructor_pdf_exporter_writes_valid_pdf(qapp: object, tmp_path: Path) -> None:
    """#476: export_to_pdf uses Qt 6 QPageLayout/QPageSize/PdfFormat and writes a valid PDF."""
    del qapp
    from echo_personal_tool.constructor.exporters.pdf_exporter import export_to_pdf
    from echo_personal_tool.constructor.models import PathologyModel, ReferenceModel, TopicModel

    model = ReferenceModel(
        topics=[TopicModel(slug="lv", name="LV", pathologies=[PathologyModel(slug="hcm", name="HCM")])]
    )
    target = tmp_path / "handbook.pdf"
    export_to_pdf(model, target)
    assert target.is_file()
    assert target.read_bytes().startswith(b"%PDF")
