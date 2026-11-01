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


def _counts(ignores: int, bare: int, unexplained: int = 0) -> dict[str, int]:
    return {"ignores": ignores, "bare": bare, "unexplained": unexplained}


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

        assert check_type_ignores.scan_file(module) == _counts(4, 2, 2)

    def test_a_clean_file_contributes_nothing(self, tmp_path: Path) -> None:
        module = tmp_path / "clean.py"
        module.write_text("value = 1\n", encoding="utf-8")

        assert check_type_ignores.scan_file(module) == _counts(0, 0)
        assert check_type_ignores.scan_source(tmp_path) == {}

    def test_prose_about_suppressions_is_not_a_suppression(self, tmp_path: Path) -> None:
        module = tmp_path / "docs.py"
        module.write_text(
            '"""Why `# type: ignore` is forbidden in this package."""\n'
            'MESSAGE = "# type: ignore"\n'
            "value = 1  # type: ignore[misc]  # the stub returns object\n",
            encoding="utf-8",
        )

        assert check_type_ignores.scan_file(module) == _counts(1, 0)

    def test_a_suppression_without_a_reason_is_unexplained(self, tmp_path: Path) -> None:
        module = tmp_path / "reasons.py"
        module.write_text(
            "\n".join(
                (
                    "a = call()  # type: ignore[arg-type]",
                    "b = call()  # type: ignore[arg-type]  # the stub returns Any",
                    "c = call()  # type: ignore[arg-type]  # noqa: E501",
                )
            )
            + "\n",
            encoding="utf-8",
        )

        assert check_type_ignores.scan_file(module) == _counts(3, 0, 2)

    def test_scan_source_reports_relative_paths(self, tmp_path: Path) -> None:
        nested = tmp_path / "pkg" / "mod.py"
        nested.parent.mkdir()
        nested.write_text("x = call()  # type: ignore[misc]\n", encoding="utf-8")

        assert check_type_ignores.scan_source(tmp_path) == {"pkg/mod.py": _counts(1, 0, 1)}


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

    def test_a_new_unexplained_suppression_is_rejected(self) -> None:
        # Same count as the baseline, but one of them lost its reason.
        current = {"pkg/old.py": _counts(3, 0, 1)}
        baseline = {"pkg/old.py": _counts(3, 0, 0)}

        violations = check_type_ignores.find_violations(current, baseline)

        assert violations
        assert "unexplained" in violations[0]

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


def _mypy_config() -> dict[str, object]:
    import tomllib

    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return config["tool"]["mypy"]


class TestMypySettings:
    """#325: the loosening this issue removed must not come back silently."""

    def test_no_project_package_is_carved_out_of_mypy(self) -> None:
        """Only third-party libraries may be special-cased.

        Slices 1-4 deleted the `application`/`infrastructure` overrides; a new
        one naming the project itself would reopen the same hole.
        """
        for override in _mypy_config()["overrides"]:
            for module in override["module"]:
                assert not module.startswith("echo_personal_tool"), module

    def test_strict_mode_is_the_global_setting(self) -> None:
        mypy = _mypy_config()

        assert mypy["strict"] is True
        assert "ignore_errors" not in mypy
        assert "disable_error_code" not in mypy

    def test_untyped_definitions_and_calls_stay_rejected(self) -> None:
        """`strict` is what turns `def handler(event):` into an error.

        The final slice removed the per-package flags because `strict` already
        implies them; flipping any of them off would silently undo #325.
        """
        mypy = _mypy_config()
        guards = (
            "disallow_untyped_defs",
            "disallow_untyped_calls",
            "warn_return_any",
            "warn_unused_ignores",
        )

        for name in guards:
            assert mypy.get(name, True) is True, name
        for override in mypy["overrides"]:
            for name in guards:
                assert override.get(name, True) is True, (override["module"], name)

    def test_remaining_overrides_only_silence_unstubbed_libraries(self) -> None:
        """The two surviving blocks exist because the lint job installs no stubs."""
        for override in _mypy_config()["overrides"]:
            relaxations = {name for name, value in override.items() if name != "module" and value is not True}

            assert relaxations <= {"ignore_missing_imports", "follow_imports"}, (override["module"], relaxations)


class TestSuppressionDiscipline:
    """#325 acceptance: a suppression always names the code it silences."""

    def test_no_bare_suppression_survives(self) -> None:
        counts = check_type_ignores.scan_source(check_type_ignores.DEFAULT_SOURCE)

        assert check_type_ignores.totals(counts)["bare"] == 0

    def test_every_suppression_explains_itself(self) -> None:
        counts = check_type_ignores.scan_source(check_type_ignores.DEFAULT_SOURCE)

        assert check_type_ignores.totals(counts)["unexplained"] == 0

    def test_the_baseline_sits_at_the_post_cleanup_count(self) -> None:
        current = check_type_ignores.totals(check_type_ignores.scan_source(check_type_ignores.DEFAULT_SOURCE))
        baseline = check_type_ignores.load_baseline(check_type_ignores.DEFAULT_BASELINE)

        assert current == check_type_ignores.totals(baseline)
