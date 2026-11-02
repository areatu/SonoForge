"""Tests for the spec-ID reference ratchet (issue #329).

``# QH-1b.2 slice 2`` and ``# UI-5 PR-2`` in `src` mean something only next to the
spec that issued them. `scripts/check_id_references.py` keeps their number from
growing and makes every reduction stick; these tests pin what counts as a
reference, how comments and strings are told apart, the arithmetic of the
baseline and the command line.
"""

from __future__ import annotations

import ast
import json
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_id_references  # noqa: E402

BASELINE_FILE = REPO_ROOT / "scripts" / "id_references_baseline.json"
SCRIPT_FILE = REPO_ROOT / "scripts" / "check_id_references.py"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
MODULE = "src/pkg/mod.py"


def _count(source: str) -> check_id_references.Counts:
    return check_id_references.count_references(textwrap.dedent(source))


def _write(tmp_path: Path, files: dict[str, str]) -> Path:
    for name, source in files.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(source), encoding="utf-8")
    return tmp_path


def _baseline(total: int, files: dict[str, int] | None = None) -> check_id_references.Baseline:
    return check_id_references.Baseline(total=total, comments=total, strings=0, files=files or {})


def _run(tmp_path: Path, *extra: str) -> int:
    return check_id_references.main(["--root", str(tmp_path), "--baseline", str(tmp_path / "baseline.json"), *extra])


class TestWhatCounts:
    @pytest.mark.parametrize(
        "identifier",
        ["QH-1", "QH-1b.2", "QH-4a", "TP-3", "UI-5", "UD-12", "UQ-7", "UA-3", "S-02", "A-16", "D-23"],
    )
    def test_every_family_the_audit_counted_is_a_reference(self, identifier: str) -> None:
        assert _count(f"# see {identifier} for the reason\n") == check_id_references.Counts(comments=1, strings=0)

    @pytest.mark.parametrize(
        "text",
        ["S-2", "X-02", "UI-", "QH-x", "PUI-5", "SS-02", "S-02x", "UI-5a", "issue 329", "TP-12-bis"],
    )
    def test_look_alikes_are_not(self, text: str) -> None:
        assert _count(f"# {text}\n").total == 0

    def test_several_references_in_one_comment_are_each_counted(self) -> None:
        assert _count("# UI-6 (S-02): the focus view, QH-3\n").comments == 3


class TestCommentsAndStrings:
    def test_a_comment_and_a_docstring_are_told_apart(self) -> None:
        counts = _count(
            '''
            """Module docstring (UI-4)."""


            def f():
                """Another one: S-02 and QH-3."""
                return 1  # D-23 repeated measurements
            '''
        )

        assert counts == check_id_references.Counts(comments=1, strings=3)

    def test_a_string_literal_counts_as_a_string(self) -> None:
        assert _count('NAME = "UI-5 sections"\n') == check_id_references.Counts(comments=0, strings=1)

    def test_an_f_string_counts_the_same_on_every_python_version(self) -> None:
        assert _count('value = 1\nlabel = f"UI-5 {value} S-02"\n') == check_id_references.Counts(comments=0, strings=2)

    def test_code_tokens_hold_no_reference(self) -> None:
        assert _count("UI_5 = 1\nS02 = 2\nQH_1b = 3\n").total == 0

    def test_a_hash_inside_a_string_is_not_a_comment(self) -> None:
        assert _count('text = "# UI-5"\n') == check_id_references.Counts(comments=0, strings=1)


class TestScanning:
    def test_only_python_files_under_the_source_directory_are_scanned(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            {
                MODULE: "# UI-5\n",
                "src/pkg/sub/deep.py": "# S-02 and QH-3\n",
                "src/pkg/readme.md": "UI-5\n",
                "tests/test_x.py": "# UI-5\n",
                "src/pkg/clean.py": "x = 1\n",
            },
        )

        found, errors = check_id_references.scan(tmp_path, "src")

        assert errors == []
        assert {name: counts.total for name, counts in found.items()} == {MODULE: 1, "src/pkg/sub/deep.py": 2}

    def test_a_file_that_cannot_be_tokenized_is_reported_not_raised(self, tmp_path: Path) -> None:
        _write(tmp_path, {MODULE: "x = (1,\n"})

        found, errors = check_id_references.scan(tmp_path, "src")

        assert found == {}
        assert errors and errors[0].startswith(f"{MODULE}: cannot tokenize")


class TestViolations:
    def test_growth_fails_and_names_the_file_that_grew(self) -> None:
        found = {"a.py": check_id_references.Counts(comments=5), "b.py": check_id_references.Counts(comments=2)}

        violations = check_id_references.find_violations(found, _baseline(5, {"a.py": 3, "b.py": 2}))

        assert len(violations) == 2
        assert "carries 7 spec-ID references" in violations[0]
        assert "allows 5 (+2)" in violations[0]
        assert violations[1] == "a.py: 5 references, baseline 3 (+2)"

    def test_a_new_file_starts_with_no_allowance(self) -> None:
        violations = check_id_references.find_violations(
            {"new.py": check_id_references.Counts(strings=2)}, _baseline(0)
        )

        assert "new.py: 2 references, baseline 0 (+2)" in violations

    def test_the_same_total_passes_even_when_references_move_between_files(self) -> None:
        found = {"a.py": check_id_references.Counts(comments=4), "moved.py": check_id_references.Counts(comments=2)}

        assert check_id_references.find_violations(found, _baseline(6, {"a.py": 6})) == ()

    def test_an_improvement_must_be_recorded(self) -> None:
        violations = check_id_references.find_violations({"a.py": check_id_references.Counts(comments=4)}, _baseline(6))

        assert len(violations) == 1
        assert "still allows 6" in violations[0]
        assert "--fix" in violations[0]


class TestBaselineFile:
    def test_the_baseline_round_trips_sorted_with_the_split(self, tmp_path: Path) -> None:
        path = tmp_path / "baseline.json"
        found = {
            "b.py": check_id_references.Counts(comments=1, strings=1),
            "a.py": check_id_references.Counts(comments=3),
        }

        check_id_references.write_baseline(path, found)
        data = json.loads(path.read_text(encoding="utf-8"))

        assert data["total"] == 5
        assert (data["comments"], data["strings"]) == (4, 1)
        assert list(data["files"]) == ["a.py", "b.py"]
        assert check_id_references.load_baseline(path) == check_id_references.Baseline(
            total=5, comments=4, strings=1, files={"a.py": 3, "b.py": 2}
        )

    @pytest.mark.parametrize(
        "payload",
        [
            {"version": 2, "total": 0, "comments": 0, "strings": 0, "files": {}},
            {"version": 1, "total": -1, "comments": 0, "strings": 0, "files": {}},
            {"version": 1, "total": "3", "comments": 0, "strings": 0, "files": {}},
            {"version": 1, "total": 0, "comments": 0, "strings": 0, "files": {"a.py": "3"}},
            {"version": 1, "total": 0, "comments": 0, "strings": 0, "files": []},
        ],
        ids=["version", "negative", "not-an-int", "count-not-an-int", "files-not-a-dict"],
    )
    def test_a_malformed_baseline_is_rejected(self, tmp_path: Path, payload: dict[str, object]) -> None:
        path = tmp_path / "baseline.json"
        path.write_text(json.dumps(payload), encoding="utf-8")

        with pytest.raises(ValueError):
            check_id_references.load_baseline(path)


class TestCommandLine:
    def test_a_missing_baseline_is_an_error_that_explains_how_to_create_it(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(tmp_path, {MODULE: "# UI-5\n"})

        assert _run(tmp_path) == 2
        assert "--fix" in capsys.readouterr().err

    def test_fix_creates_the_baseline_and_the_check_then_passes(self, tmp_path: Path) -> None:
        _write(tmp_path, {MODULE: "# UI-5 and S-02\n"})

        assert _run(tmp_path, "--fix") == 0
        assert json.loads((tmp_path / "baseline.json").read_text(encoding="utf-8"))["total"] == 2
        assert _run(tmp_path) == 0

    def test_a_new_reference_fails_and_fix_refuses_to_hide_it(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(tmp_path, {MODULE: "# UI-5\n"})
        assert _run(tmp_path, "--fix") == 0
        before = (tmp_path / "baseline.json").read_text(encoding="utf-8")
        capsys.readouterr()
        (tmp_path / MODULE).write_text("# UI-5\n# S-02\n", encoding="utf-8")

        assert _run(tmp_path) == 1
        assert "+1" in capsys.readouterr().err

        assert _run(tmp_path, "--fix") == 1
        assert "refusing to raise the bar" in capsys.readouterr().err
        assert (tmp_path / "baseline.json").read_text(encoding="utf-8") == before

    def test_turning_a_reference_into_a_reason_fails_until_fix_lowers_the_baseline(self, tmp_path: Path) -> None:
        _write(tmp_path, {MODULE: "# UI-5 and S-02\n"})
        assert _run(tmp_path, "--fix") == 0
        (tmp_path / MODULE).write_text("# the focus view belongs to the tab; S-02\n", encoding="utf-8")

        assert _run(tmp_path) == 1
        assert _run(tmp_path, "--fix") == 0
        assert json.loads((tmp_path / "baseline.json").read_text(encoding="utf-8"))["total"] == 1
        assert _run(tmp_path) == 0

    def test_a_wrong_source_directory_does_not_pass_silently(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run(tmp_path, "--fix") == 2
        assert "is not a directory" in capsys.readouterr().err

    def test_an_unparsable_module_is_an_error(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        _write(tmp_path, {MODULE: "x = (1,\n"})

        assert _run(tmp_path, "--fix") == 2
        assert MODULE in capsys.readouterr().err

    def test_the_listing_shows_the_densest_files_and_the_most_used_ids(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(tmp_path, {MODULE: "# UI-5 UI-5 S-02\n", "src/pkg/other.py": '"""QH-3"""\n'})

        assert _run(tmp_path, "--list") == 0
        listing = capsys.readouterr().out

        assert "4 spec-ID references in 2 files" in listing
        assert listing.index("src/pkg/mod.py") < listing.index("src/pkg/other.py")
        assert "3 distinct IDs" in listing
        assert listing.index("UI-5") < listing.index("QH-3")

    def test_the_summary_is_appended_to_the_github_step_summary_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write(tmp_path, {MODULE: '# UI-5\n"""S-02"""\n'})
        assert _run(tmp_path, "--fix") == 0
        summary = tmp_path / "summary.md"
        summary.write_text("earlier step\n", encoding="utf-8")
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

        assert _run(tmp_path, "--github-summary") == 0
        text = summary.read_text(encoding="utf-8")

        assert text.startswith("earlier step\n")
        assert "### Spec-ID references in src (#329)" in text
        assert "| **References** (gated: may only go down) | 2 | 2 | 0 |" in text
        assert "| in comments | 1 | 1 | 0 |" in text
        assert "| in docstrings and strings | 1 | 1 | 0 |" in text

    def test_a_failing_run_still_publishes_the_summary_with_the_violations(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write(tmp_path, {MODULE: "# UI-5\n"})
        assert _run(tmp_path, "--fix") == 0
        (tmp_path / MODULE).write_text("# UI-5 S-02\n", encoding="utf-8")
        summary = tmp_path / "summary.md"
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

        assert _run(tmp_path, "--github-summary") == 1
        assert "**Violations**" in summary.read_text(encoding="utf-8")


class TestCommittedBaseline:
    def test_the_committed_tree_passes_the_ratchet(self) -> None:
        assert check_id_references.main([]) == 0

    def test_the_baseline_matches_the_tree_exactly(self) -> None:
        baseline = check_id_references.load_baseline(BASELINE_FILE)
        found, errors = check_id_references.scan(REPO_ROOT, "src")
        summed = check_id_references.totals(found)

        assert errors == []
        assert {name: counts.total for name, counts in found.items()} == baseline.files
        assert (summed.total, summed.comments, summed.strings) == (baseline.total, baseline.comments, baseline.strings)

    def test_the_count_has_come_down_from_the_audit_figure(self) -> None:
        """The issue counted 763 references; the ratchet must never sit above that again."""
        assert check_id_references.load_baseline(BASELINE_FILE).total < 763


class TestWiring:
    def test_the_ratchet_runs_in_the_lint_job_and_publishes_its_summary(self) -> None:
        workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
        commands = [str(step.get("run", "")) for step in workflow["jobs"]["lint"]["steps"]]

        assert "python scripts/check_id_references.py --github-summary" in commands

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

    def test_the_rule_is_written_down_where_contributors_look(self) -> None:
        text = (REPO_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")

        assert "check_id_references.py" in text
