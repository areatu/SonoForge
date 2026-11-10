"""Unit tests for scripts/audit_untested_modules.py and CI suite coverage (issue 483)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "audit_untested_modules.py"

spec = importlib.util.spec_from_file_location("audit_untested_modules", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
aum = importlib.util.module_from_spec(spec)
sys.modules["audit_untested_modules"] = aum
spec.loader.exec_module(aum)

# Suites intentionally executed manually by a human (never headless in CI) and documented in tests/README.md
MANUAL_ONLY_TEST_SUITES = frozenset({"tests/interactive"})


def test_committed_untested_modules_baseline_passes_and_excludes_priority_modules() -> None:
    rc = aum.main([])
    assert rc == 0

    current = aum.scan_untested_modules(aum.DEFAULT_SRC_ROOT, aum.DEFAULT_TESTS_ROOT)
    current_paths = {item.relpath for item in current}
    for covered_module in (
        "echo_personal_tool/application/workers/dcm_export_worker.py",
        "echo_personal_tool/domain/services/roi_validator.py",
        "echo_personal_tool/application/workers/orthanc_enrichment_worker.py",
        "echo_personal_tool/domain/calculations/simpson_contours.py",
        "echo_personal_tool/presentation/window_chrome/caption_drag.py",
    ):
        assert covered_module not in current_paths


def test_new_untested_module_fails_ratchet_and_fix_refuses_to_grow(tmp_path: Path) -> None:
    src = tmp_path / "src"
    pkg = src / "echo_personal_tool" / "domain"
    pkg.mkdir(parents=True)
    (src / "echo_personal_tool" / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "covered.py").write_text("def compute(x: int) -> int:\n    return x + 1\n", encoding="utf-8")

    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_covered.py").write_text(
        "from echo_personal_tool.domain.covered import compute\n\ndef test_c():\n    assert compute(1) == 2\n",
        encoding="utf-8",
    )

    baseline = tmp_path / "baseline.json"
    assert aum.main(["--src-root", str(src), "--tests-root", str(tests), "--baseline", str(baseline), "--fix"]) == 0
    assert json.loads(baseline.read_text(encoding="utf-8"))["count"] == 0

    # Add an untested module -> both check and --fix must fail
    (pkg / "orphan.py").write_text("def forgot_to_test() -> int:\n    return 42\n", encoding="utf-8")
    assert aum.main(["--src-root", str(src), "--tests-root", str(tests), "--baseline", str(baseline)]) == 1
    assert aum.main(["--src-root", str(src), "--tests-root", str(tests), "--baseline", str(baseline), "--fix"]) == 1


def test_covering_a_legacy_module_lowers_baseline_via_fix(tmp_path: Path) -> None:
    src = tmp_path / "src"
    pkg = src / "echo_personal_tool" / "application"
    pkg.mkdir(parents=True)
    (src / "echo_personal_tool" / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "legacy.py").write_text("class LegacyService:\n    pass\n", encoding="utf-8")

    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_empty.py").write_text("def test_noop():\n    assert 1 == 1\n", encoding="utf-8")

    baseline = tmp_path / "baseline.json"
    assert aum.main(["--src-root", str(src), "--tests-root", str(tests), "--baseline", str(baseline), "--fix"]) == 0
    assert json.loads(baseline.read_text(encoding="utf-8"))["count"] == 1

    # Add a test referencing LegacyService -> --fix lowers baseline to 0
    (tests / "test_legacy.py").write_text(
        "from echo_personal_tool.application.legacy import LegacyService\n\ndef test_l():\n    assert LegacyService() is not None\n",
        encoding="utf-8",
    )
    assert aum.main(["--src-root", str(src), "--tests-root", str(tests), "--baseline", str(baseline), "--fix"]) == 0
    assert json.loads(baseline.read_text(encoding="utf-8"))["count"] == 0


def test_every_test_directory_is_wired_into_a_workflow_or_marked_manual() -> None:
    """issue 483: no directory under tests/ containing test_*.py may sit outside workflows."""
    workflows_dir = REPO_ROOT / ".github" / "workflows"
    workflow_text = "\n".join(p.read_text(encoding="utf-8") for p in sorted(workflows_dir.glob("*.yml")))
    tests_readme = (REPO_ROOT / "tests" / "README.md").read_text(encoding="utf-8")

    tests_root = REPO_ROOT / "tests"
    if list(tests_root.glob("test_*.py")):
        assert "tests/test_*.py" in workflow_text, "root tests/test_*.py files must run in a CI workflow"

    subdirs_with_tests = sorted(
        {
            f"tests/{p.relative_to(tests_root).parts[0]}"
            for p in tests_root.rglob("test_*.py")
            if len(p.relative_to(tests_root).parts) >= 2
        }
    )
    assert len(subdirs_with_tests) >= 10

    unwired: list[str] = []
    for suite_dir in subdirs_with_tests:
        if suite_dir in MANUAL_ONLY_TEST_SUITES:
            leaf = suite_dir.split("/", 1)[1]
            assert f"`{leaf}/`" in tests_readme, f"manual suite {suite_dir} must be documented in tests/README.md"
            continue
        if suite_dir not in workflow_text:
            unwired.append(suite_dir)

    assert unwired == [], f"test directories missing from .github/workflows/*.yml: {unwired}"
