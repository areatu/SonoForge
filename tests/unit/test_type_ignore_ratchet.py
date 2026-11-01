"""Tests for the `# type: ignore` ratchet (issue #325).

The mypy gate already runs on `domain`, `imaging`, `application` and
`infrastructure`, so the remaining hole is not *whether* types are checked but
*what* the code is allowed to switch off: a bare `# type: ignore` silences every
error on the line, and a suppression added today can hide tomorrow's
regression. `scripts/check_type_ignores.py` is the ratchet that keeps the count
honest; these tests pin its arithmetic and its baseline.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_type_ignores  # noqa: E402

CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _counts(ignores: int, bare: int) -> dict[str, int]:
    return {"ignores": ignores, "bare": bare}


class TestScanning:
    def test_coded_and_bare_ignores_are_counted_separately(self, tmp_path: Path) -> None:
        module = tmp_path / "sample.py"
        module.write_text(
            "\n".join(
                (
                    "x = call()  # type: ignore[arg-type]",
                    "y = call()  # type: ignore",
                    "z = call()  #type:ignore",
                    "w = call()  # type: ignore[attr-defined]  # noqa: E501",
                    "plain = 1",
                )
            )
            + "\n",
            encoding="utf-8",
        )

        assert check_type_ignores.scan_file(module) == _counts(4, 2)

    def test_a_clean_file_contributes_nothing(self, tmp_path: Path) -> None:
        module = tmp_path / "clean.py"
        module.write_text("value = 1\n", encoding="utf-8")

        assert check_type_ignores.scan_file(module) == _counts(0, 0)
        assert check_type_ignores.scan_source(tmp_path) == {}

    def test_scan_source_reports_relative_paths(self, tmp_path: Path) -> None:
        nested = tmp_path / "pkg" / "mod.py"
        nested.parent.mkdir()
        nested.write_text("x = call()  # type: ignore[misc]\n", encoding="utf-8")

        assert check_type_ignores.scan_source(tmp_path) == {"pkg/mod.py": _counts(1, 0)}


class TestViolations:
    def test_a_new_suppression_in_a_new_file_is_rejected(self) -> None:
        current = {"pkg/new.py": _counts(1, 0)}

        violations = check_type_ignores.find_violations(current, {})

        assert violations
        assert "pkg/new.py" in violations[0]

    def test_growth_in_an_existing_file_is_rejected(self) -> None:
        current = {"pkg/old.py": _counts(5, 0)}
        baseline = {"pkg/old.py": _counts(4, 0)}

        assert check_type_ignores.find_violations(current, baseline)

    def test_a_cleanup_is_allowed_and_lowers_the_ceiling(self) -> None:
        current = {"pkg/old.py": _counts(2, 1)}
        baseline = {"pkg/old.py": _counts(4, 1)}

        assert check_type_ignores.find_violations(current, baseline) == ()

    def test_a_bare_ignore_where_there_was_none_is_rejected(self) -> None:
        # Same total, but one suppression lost its code: that is a regression
        # even though the count did not move.
        current = {"pkg/old.py": _counts(2, 1)}
        baseline = {"pkg/old.py": _counts(2, 0)}

        violations = check_type_ignores.find_violations(current, baseline)

        assert violations
        assert "bare" in violations[0]

    def test_removing_a_file_is_not_a_violation(self) -> None:
        current = {"pkg/kept.py": _counts(1, 0)}
        baseline = {"pkg/kept.py": _counts(1, 0), "pkg/deleted.py": _counts(3, 2)}

        assert check_type_ignores.find_violations(current, baseline) == ()


class TestCommittedBaseline:
    def test_the_baseline_matches_the_source_tree(self) -> None:
        data = json.loads((REPO_ROOT / "scripts" / "type_ignore_baseline.json").read_text(encoding="utf-8"))
        current = check_type_ignores.scan_source(check_type_ignores.DEFAULT_SOURCE)

        assert data["version"] == 1
        assert data["files"] == current, "run `python scripts/check_type_ignores.py --fix` after a cleanup"
        assert data["totals"] == check_type_ignores.totals(current)

    def test_the_committed_tree_passes_the_ratchet(self) -> None:
        assert check_type_ignores.main([]) == 0

    def test_the_baseline_only_allows_a_decrease(self, tmp_path: Path) -> None:
        baseline_path = tmp_path / "baseline.json"
        check_type_ignores.write_baseline(baseline_path, {"pkg/mod.py": _counts(2, 1)})
        data = json.loads(baseline_path.read_text(encoding="utf-8"))

        assert data["totals"] == _counts(2, 1)
        assert check_type_ignores.load_baseline(baseline_path) == {"pkg/mod.py": _counts(2, 1)}

    def test_the_gate_is_wired_into_ci(self) -> None:
        workflow = CI_WORKFLOW.read_text(encoding="utf-8")

        assert "python scripts/check_type_ignores.py" in workflow


class TestMypySettings:
    """#325: the loosening this slice removed must not come back silently."""

    def test_application_checks_untyped_bodies_and_dead_suppressions(self) -> None:
        import tomllib

        config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        overrides = config["tool"]["mypy"]["overrides"]

        application = next(
            item
            for item in overrides
            if "echo_personal_tool.application" in item["module"] and "infrastructure" not in str(item["module"])
        )

        assert application["check_untyped_defs"] is True
        assert application["warn_unused_ignores"] is True

    def test_no_error_code_stays_disabled(self) -> None:
        """#325: mypy checks every code in `application` and `infrastructure`.

        The incremental-adoption overrides may still relax *annotation*
        requirements (`disallow_untyped_defs` and friends) — that is about how
        much of the code is annotated, not about which errors are reported.
        `disable_error_code`, `ignore_errors` and `check_untyped_defs = false`
        would hide real findings again, so they are asserted out.
        """
        import tomllib

        config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        overrides = [
            item
            for item in config["tool"]["mypy"]["overrides"]
            if any("application" in name or "infrastructure" in name for name in item["module"])
        ]

        assert overrides, "the incremental-adoption overrides must still exist"
        for override in overrides:
            assert "disable_error_code" not in override, override["module"]
            assert "ignore_errors" not in override, override["module"]
            assert override.get("check_untyped_defs") is True, override["module"]
            assert override.get("warn_unused_ignores") is True, override["module"]
