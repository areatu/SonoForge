"""Tests for the private-access ratchet of the viewer tests (issue #327).

``ViewerWidget`` cannot be decomposed (#305, #307) while hundreds of tests read
``w._contour_stage`` or call ``w._apply_caliper_node_drag(...)``: they pin how the
widget works, not what it promises. `scripts/check_test_private_access.py` keeps
that number from growing and makes every reduction stick; these tests pin what
counts as a reference, the arithmetic of the baseline and the command line.
"""

from __future__ import annotations

import ast
import collections
import json
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_test_private_access  # noqa: E402

BASELINE_FILE = REPO_ROOT / "scripts" / "test_private_access_baseline.json"
SCRIPT_FILE = REPO_ROOT / "scripts" / "check_test_private_access.py"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
SCOPE = ("tests/unit/test_*viewer*.py",)


def _references(source: str) -> list[str]:
    tree = ast.parse(textwrap.dedent(source))
    return [name for _line, name in check_test_private_access.iter_private_references(tree)]


def _write(tmp_path: Path, files: dict[str, str]) -> Path:
    for name, source in files.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(source), encoding="utf-8")
    return tmp_path


def _baseline(total: int, files: dict[str, int] | None = None) -> check_test_private_access.Baseline:
    return check_test_private_access.Baseline(scope=SCOPE, total=total, files=files or {})


def _run(tmp_path: Path, *extra: str) -> int:
    return check_test_private_access.main(
        ["--root", str(tmp_path), "--baseline", str(tmp_path / "baseline.json"), *extra]
    )


VIEWER = "tests/unit/test_viewer_demo.py"


class TestWhatCounts:
    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ("w._contour_stage", ["_contour_stage"]),
            ("w._apply_caliper_node_drag(10.0, 10.0)", ["_apply_caliper_node_drag"]),
            ("w._doppler._state", ["_state", "_doppler"]),
            ("w._a = 1", ["_a"]),
            ("self._w._current_frame", ["_current_frame"]),  # ``self._w`` is the test's own handle on the widget
            ("getattr(w, '_zoom')", ["_zoom"]),
            ("setattr(w, '_zoom', 2)", ["_zoom"]),
            ("hasattr(w, '_zoom')", ["_zoom"]),
            ("delattr(w, '_zoom')", ["_zoom"]),
            ("monkeypatch.setattr(w, '_zoom', 2)", ["_zoom"]),
            ("patch.object(w, '_zoom')", ["_zoom"]),
        ],
    )
    def test_these_reach_into_private_state(self, source: str, expected: list[str]) -> None:
        assert sorted(_references(source)) == sorted(expected)

    @pytest.mark.parametrize(
        "source",
        [
            "self._helper",
            "self._helper()",
            "cls._registry",
            "w.zoom_mode",
            "w.__class__",
            "w.__dict__",
            "x = _",
            "w._",
            "getattr(self, '_zoom')",
            "getattr(w, 'zoom')",
            "getattr(w, name)",
            "monkeypatch.setattr(w, 'zoom', 2)",
            "other.setattr(w, '_zoom', 2)",
            "from module import _private_helper",
        ],
    )
    def test_these_do_not(self, source: str) -> None:
        assert _references(source) == [], source

    def test_a_bare_underscore_and_dunders_are_not_private_names(self) -> None:
        names = ["_", "__", "__init__", "plain", "x_", "_x", "_x_y", "__x"]

        assert [name for name in names if check_test_private_access.is_private_name(name)] == ["_x", "_x_y", "__x"]


class TestScanning:
    def test_only_files_in_the_scope_are_scanned(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            {
                VIEWER: "def test_a(w): assert w._x == w._y\n",
                "tests/unit/test_viewer_other.py": "def test_b(w): assert w._x\n",
                "tests/unit/test_unrelated.py": "def test_c(w): assert w._x\n",
                "tests/unit/helpers_viewer.py": "w._x\n",
            },
        )

        found, errors = check_test_private_access.scan(tmp_path, SCOPE)

        assert errors == []
        assert check_test_private_access.file_counts(found) == {
            "tests/unit/test_viewer_demo.py": 2,
            "tests/unit/test_viewer_other.py": 1,
        }
        assert found["tests/unit/test_viewer_demo.py"] == collections.Counter({"_x": 1, "_y": 1})

    def test_a_clean_file_is_not_listed(self, tmp_path: Path) -> None:
        _write(tmp_path, {VIEWER: "def test_a(w): assert w.zoom_mode == 'fit'\n"})

        found, _errors = check_test_private_access.scan(tmp_path, SCOPE)

        assert found == {}

    def test_a_file_that_cannot_be_parsed_is_reported_not_raised(self, tmp_path: Path) -> None:
        _write(tmp_path, {VIEWER: "def (:\n"})

        found, errors = check_test_private_access.scan(tmp_path, SCOPE)

        assert found == {}
        assert errors and errors[0].startswith("tests/unit/test_viewer_demo.py: cannot parse")


class TestViolations:
    def test_growth_fails_and_names_the_file_that_grew(self) -> None:
        counts = {"a.py": 12, "b.py": 5}

        violations = check_test_private_access.find_violations(counts, _baseline(15, {"a.py": 10, "b.py": 5}))

        assert len(violations) == 2
        assert "17 times" in violations[0]
        assert "allows 15 (+2)" in violations[0]
        assert violations[1] == "a.py: 12 references, baseline 10 (+2)"

    def test_a_new_file_in_the_scope_starts_with_no_allowance(self) -> None:
        violations = check_test_private_access.find_violations({"new.py": 3}, _baseline(0))

        assert "new.py: 3 references, baseline 0 (+3)" in violations

    def test_the_same_total_passes_even_when_references_move_between_files(self) -> None:
        counts = {"a.py": 8, "split_off.py": 4}

        assert check_test_private_access.find_violations(counts, _baseline(12, {"a.py": 12})) == ()

    def test_an_improvement_must_be_recorded(self) -> None:
        violations = check_test_private_access.find_violations({"a.py": 9}, _baseline(12, {"a.py": 12}))

        assert len(violations) == 1
        assert "still allows 12" in violations[0]
        assert "--fix" in violations[0]

    def test_exactly_the_baseline_passes(self) -> None:
        assert check_test_private_access.find_violations({"a.py": 12}, _baseline(12, {"a.py": 12})) == ()


class TestBaselineFile:
    def test_the_baseline_round_trips_sorted(self, tmp_path: Path) -> None:
        path = tmp_path / "baseline.json"

        check_test_private_access.write_baseline(path, SCOPE, {"b.py": 2, "a.py": 3})
        data = json.loads(path.read_text(encoding="utf-8"))
        loaded = check_test_private_access.load_baseline(path)

        assert data["version"] == 1
        assert data["total"] == 5
        assert list(data["files"]) == ["a.py", "b.py"]
        assert loaded == check_test_private_access.Baseline(scope=SCOPE, total=5, files={"a.py": 3, "b.py": 2})
        assert path.read_text(encoding="utf-8").endswith("\n")

    @pytest.mark.parametrize(
        "payload",
        [
            {"version": 2, "scope": ["x"], "total": 0, "files": {}},
            {"version": 1, "scope": [], "total": 0, "files": {}},
            {"version": 1, "scope": "tests/*.py", "total": 0, "files": {}},
            {"version": 1, "scope": ["x"], "total": -1, "files": {}},
            {"version": 1, "scope": ["x"], "total": "3", "files": {}},
            {"version": 1, "scope": ["x"], "total": 0, "files": {"a.py": "3"}},
            {"version": 1, "scope": ["x"], "total": 0, "files": []},
        ],
        ids=[
            "version",
            "empty-scope",
            "scope-not-a-list",
            "negative-total",
            "total-not-int",
            "count-not-int",
            "files-not-a-dict",
        ],
    )
    def test_a_malformed_baseline_is_rejected(self, tmp_path: Path, payload: dict[str, object]) -> None:
        path = tmp_path / "baseline.json"
        path.write_text(json.dumps(payload), encoding="utf-8")

        with pytest.raises(ValueError):
            check_test_private_access.load_baseline(path)


class TestCommandLine:
    def test_a_missing_baseline_is_an_error_that_explains_how_to_create_it(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(tmp_path, {VIEWER: "def test_a(w): assert w._x\n"})

        assert _run(tmp_path) == 2
        assert "--fix" in capsys.readouterr().err

    def test_fix_creates_the_baseline_and_the_check_then_passes(self, tmp_path: Path) -> None:
        _write(tmp_path, {VIEWER: "def test_a(w): assert w._x == w._y\n"})

        assert _run(tmp_path, "--fix") == 0
        baseline = json.loads((tmp_path / "baseline.json").read_text(encoding="utf-8"))

        assert baseline["total"] == 2
        assert baseline["scope"] == list(SCOPE)
        assert _run(tmp_path) == 0

    def test_a_new_private_reference_fails_and_fix_refuses_to_hide_it(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(tmp_path, {VIEWER: "def test_a(w): assert w._x\n"})
        assert _run(tmp_path, "--fix") == 0
        before = (tmp_path / "baseline.json").read_text(encoding="utf-8")
        capsys.readouterr()
        (tmp_path / VIEWER).write_text("def test_a(w): assert w._x == w._y\n", encoding="utf-8")

        assert _run(tmp_path) == 1
        assert "+1" in capsys.readouterr().err

        assert _run(tmp_path, "--fix") == 1
        assert "refusing to raise the bar" in capsys.readouterr().err
        assert (tmp_path / "baseline.json").read_text(encoding="utf-8") == before

    def test_replacing_private_access_fails_until_fix_lowers_the_baseline(self, tmp_path: Path) -> None:
        _write(tmp_path, {VIEWER: "def test_a(w): assert w._x == w._y\n"})
        assert _run(tmp_path, "--fix") == 0
        (tmp_path / VIEWER).write_text("def test_a(w): assert w.x == w._y\n", encoding="utf-8")

        assert _run(tmp_path) == 1
        assert _run(tmp_path, "--fix") == 0
        assert json.loads((tmp_path / "baseline.json").read_text(encoding="utf-8"))["total"] == 1
        assert _run(tmp_path) == 0

    def test_a_scope_that_matches_nothing_does_not_pass_silently(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run(tmp_path, "--fix") == 2
        assert "no test files match" in capsys.readouterr().err

    def test_an_unparsable_test_module_is_an_error(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        _write(tmp_path, {VIEWER: "def (:\n"})

        assert _run(tmp_path, "--fix") == 2
        assert "tests/unit/test_viewer_demo.py" in capsys.readouterr().err

    def test_the_listing_shows_files_and_the_most_used_names(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(tmp_path, {VIEWER: "def test_a(w): assert w._x == w._x == w._y\n"})

        assert _run(tmp_path, "--list") == 0
        listing = capsys.readouterr().out

        assert "3 references in 1 files" in listing
        assert "2 distinct private names" in listing
        assert listing.index("_x") < listing.index("_y")

    def test_the_summary_is_appended_to_the_github_step_summary_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write(tmp_path, {VIEWER: "def test_a(w): assert w._x\n"})
        assert _run(tmp_path, "--fix") == 0
        summary = tmp_path / "summary.md"
        summary.write_text("earlier step\n", encoding="utf-8")
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

        assert _run(tmp_path, "--github-summary") == 0
        text = summary.read_text(encoding="utf-8")

        assert text.startswith("earlier step\n")
        assert "### Private access in viewer tests (#327)" in text
        assert "| **References to private names** (gated: may only go down) | 1 | 1 | 0 |" in text

    def test_a_failing_run_still_publishes_the_summary_with_the_violations(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write(tmp_path, {VIEWER: "def test_a(w): assert w._x\n"})
        assert _run(tmp_path, "--fix") == 0
        (tmp_path / VIEWER).write_text("def test_a(w): assert w._x == w._y\n", encoding="utf-8")
        summary = tmp_path / "summary.md"
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

        assert _run(tmp_path, "--github-summary") == 1
        assert "**Violations**" in summary.read_text(encoding="utf-8")


class TestCommittedBaseline:
    def test_the_committed_tree_passes_the_ratchet(self) -> None:
        assert check_test_private_access.main([]) == 0

    def test_the_baseline_matches_the_tree_exactly(self) -> None:
        baseline = check_test_private_access.load_baseline(BASELINE_FILE)
        found, errors = check_test_private_access.scan(REPO_ROOT, baseline.scope)

        assert errors == []
        assert check_test_private_access.file_counts(found) == baseline.files
        assert sum(baseline.files.values()) == baseline.total

    def test_the_scope_covers_the_widget_tests_the_issue_names(self) -> None:
        baseline = check_test_private_access.load_baseline(BASELINE_FILE)

        assert "tests/unit/test_viewer_widget.py" in baseline.files
        assert baseline.scope == SCOPE


class TestWiring:
    def test_the_ratchet_runs_in_the_lint_job_and_publishes_its_summary(self) -> None:
        workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
        commands = [str(step.get("run", "")) for step in workflow["jobs"]["lint"]["steps"]]

        assert "python scripts/check_test_private_access.py --github-summary" in commands

    def test_the_script_needs_nothing_the_lint_job_does_not_install(self) -> None:
        tree = ast.parse(SCRIPT_FILE.read_text(encoding="utf-8"))
        modules = {
            alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
        }
        modules |= {
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0
        }

        assert modules <= set(sys.stdlib_module_names)

    @pytest.mark.parametrize("document", ["CONTRIBUTING.md", "tests/README.md", "tests/README_RU.md"])
    def test_the_rule_is_written_down_where_contributors_look(self, document: str) -> None:
        text = (REPO_ROOT / document).read_text(encoding="utf-8")

        assert "check_test_private_access.py" in text
