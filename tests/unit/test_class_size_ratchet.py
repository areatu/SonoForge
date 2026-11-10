"""Tests for the class/module size ratchet (issue #474).

``check_function_length.py`` is satisfied by cutting a long function into more
private methods of the same class, which is how ``MainWindow`` reached 488
methods. ``scripts/check_class_size.py`` holds what actually grows: the lines
and the method count of the largest classes, the largest modules, and the
``self.*`` state of the three god objects.
"""

from __future__ import annotations

import ast
import json
import sys
import textwrap
from pathlib import Path
from typing import cast

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_class_size  # noqa: E402

SCRIPT_FILE = REPO_ROOT / "scripts" / "check_class_size.py"
BASELINE_FILE = REPO_ROOT / "scripts" / "class_size_baseline.json"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _big_class(name: str = "Big", methods: int = 2, *, extra_lines: int = 0, fields: int = 0) -> str:
    """A class just above the 1 500-line threshold with the given number of methods and fields."""
    body = [f"class {name}:"]
    body.append("    def __init__(self):")
    body += [f"        self.f{index} = {index}" for index in range(fields)]
    body.append("        pass")
    body += [f"    def m{index}(self):\n        return {index}" for index in range(methods - 1)]
    padding = check_class_size.CLASS_LIMIT + 1 + extra_lines - sum(part.count("\n") + 1 for part in body)
    # Class-level statements, not comments: a class ends at its last statement.
    body += [f"    pad{index} = {index}" for index in range(max(padding, 0))]
    return "\n".join(body) + "\n"


def _measure(tmp_path: Path, files: dict[str, str]) -> check_class_size.Measurement:
    for name, source in files.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")
    return check_class_size.measure(tmp_path)


def _baseline_from(current: check_class_size.Measurement) -> check_class_size.Baseline:
    payload = check_class_size.baseline_payload(current)
    return check_class_size.Baseline(
        classes=cast("dict[str, dict[str, int]]", payload["classes"]),
        modules=cast("dict[str, int]", payload["modules"]),
        fields=cast("dict[str, int]", payload["fields"]),
    )


class TestMeasurement:
    def test_only_classes_above_the_threshold_are_measured(self, tmp_path: Path) -> None:
        current = _measure(tmp_path, {"pkg/big.py": _big_class(methods=3), "pkg/small.py": "class Small:\n    pass\n"})

        assert set(current.classes) == {"pkg/big.py::Big"}
        size = current.classes["pkg/big.py::Big"]
        assert size.lines == check_class_size.CLASS_LIMIT + 1
        assert size.methods == 3

    def test_self_fields_are_distinct_names_assigned_in_methods(self) -> None:
        tree = ast.parse(
            textwrap.dedent(
                """
                class C:
                    def __init__(self):
                        self.a = 1
                        self.a = 2
                        self.b: int = 3
                        self.c, (self.d, other.e) = 1, (2, 3)
                    def later(self):
                        self.count += 1
                        for self.cursor in range(3):
                            pass
                        with open("x") as self.handle:
                            pass
                        print(self.read_only)
                    class Nested:
                        def __init__(self):
                            self.not_mine = 1
                """
            )
        )
        class_node = tree.body[0]
        assert isinstance(class_node, ast.ClassDef)

        assert check_class_size._self_fields(class_node) == {"a", "b", "c", "d", "count", "cursor", "handle"}

    def test_modules_above_the_threshold_are_measured_by_physical_lines(self, tmp_path: Path) -> None:
        long_module = "x = 1\n" * (check_class_size.MODULE_LIMIT + 5)

        current = _measure(tmp_path, {"pkg/long.py": long_module, "pkg/short.py": "x = 1\n"})

        assert current.modules == {"pkg/long.py": check_class_size.MODULE_LIMIT + 5}


class TestViolations:
    def test_a_new_method_without_removing_another_fails_with_the_delta(self, tmp_path: Path) -> None:
        baseline = _baseline_from(_measure(tmp_path, {"pkg/big.py": _big_class(methods=3)}))
        grown = _measure(tmp_path, {"pkg/big.py": _big_class(methods=4)})

        violations = check_class_size.find_violations(grown, baseline)

        assert any("pkg/big.py::Big: 4 methods" in line and "(+1)" in line for line in violations)

    def test_replacing_a_method_with_another_of_the_same_size_passes(self, tmp_path: Path) -> None:
        baseline = _baseline_from(_measure(tmp_path, {"pkg/big.py": _big_class(methods=3)}))
        same = _measure(tmp_path, {"pkg/big.py": _big_class(methods=3).replace("def m1(", "def renamed(")})

        assert check_class_size.find_violations(same, baseline) == ()

    def test_line_growth_fails(self, tmp_path: Path) -> None:
        baseline = _baseline_from(_measure(tmp_path, {"pkg/big.py": _big_class()}))
        grown = _measure(tmp_path, {"pkg/big.py": _big_class(extra_lines=7)})

        violations = check_class_size.find_violations(grown, baseline)

        assert any("lines, the baseline allows" in line and "(+7)" in line for line in violations)

    def test_a_new_god_class_fails(self, tmp_path: Path) -> None:
        empty = check_class_size.Baseline(classes={}, modules={}, fields={})
        current = _measure(tmp_path, {"pkg/new.py": _big_class("Fresh")})

        violations = check_class_size.find_violations(current, empty)

        assert len(violations) == 1
        assert "new class above 1500 lines: pkg/new.py::Fresh" in violations[0]

    def test_a_new_long_module_fails(self) -> None:
        empty = check_class_size.Baseline(classes={}, modules={}, fields={})
        current = check_class_size.Measurement(classes={}, modules={"pkg/long.py": 2500})

        assert check_class_size.find_violations(current, empty) == (
            "new module above 2000 lines: pkg/long.py (2500 lines)",
        )

    def test_new_state_in_a_tracked_class_fails(self) -> None:
        tracked = check_class_size.TRACKED_FIELDS[0]
        baseline = check_class_size.Baseline(
            classes={tracked: {"lines": 3000, "methods": 10}}, modules={}, fields={tracked: 5}
        )
        current = check_class_size.Measurement(
            classes={tracked: check_class_size.ClassSize(lines=3000, methods=10, fields=6)}, modules={}
        )

        violations = check_class_size.find_violations(current, baseline)

        assert violations == (
            f"{tracked}: owns 6 self.* attributes, the baseline allows 5 (+1) — new state belongs in the "
            "collaborator that uses it",
        )

    def test_shrinking_passes_and_is_reported_as_slack(self, tmp_path: Path) -> None:
        baseline = _baseline_from(_measure(tmp_path, {"pkg/big.py": _big_class(methods=4, extra_lines=10)}))
        smaller = _measure(tmp_path, {"pkg/big.py": _big_class(methods=3)})

        assert check_class_size.find_violations(smaller, baseline) == ()
        slack = check_class_size.find_slack(smaller, baseline)
        assert "pkg/big.py::Big: methods 4 -> 3" in slack


class TestBaseline:
    def test_fix_never_raises_a_ceiling(self, tmp_path: Path) -> None:
        current = _measure(tmp_path, {"pkg/big.py": _big_class(methods=5)})
        previous = check_class_size.Baseline(
            classes={"pkg/big.py::Big": {"lines": 9999, "methods": 3}}, modules={}, fields={}
        )

        payload = check_class_size.baseline_payload(current, previous)

        assert payload["classes"] == {"pkg/big.py::Big": {"lines": check_class_size.CLASS_LIMIT + 1, "methods": 3}}

    @pytest.mark.parametrize(
        "change",
        [
            {"version": 2},
            {"class_limit": 1000},
            {"classes": {"a::B": {"lines": 1}}},
            {"classes": {"a::B": {"lines": -1, "methods": 1}}},
            {"modules": {"a.py": "3000"}},
            {"fields": []},
        ],
        ids=["version", "limit", "missing-methods", "negative", "module-not-int", "fields-not-dict"],
    )
    def test_a_malformed_baseline_is_rejected(self, tmp_path: Path, change: dict[str, object]) -> None:
        payload: dict[str, object] = {
            "version": 1,
            "class_limit": check_class_size.CLASS_LIMIT,
            "module_limit": check_class_size.MODULE_LIMIT,
            "classes": {},
            "modules": {},
            "fields": {},
            **change,
        }
        path = tmp_path / "baseline.json"
        path.write_text(json.dumps(payload), encoding="utf-8")

        with pytest.raises(ValueError):
            check_class_size.load_baseline(path)


class TestCommandLine:
    def _run(self, tmp_path: Path, *extra: str) -> int:
        return check_class_size.main(
            ["--source", str(tmp_path / "src"), "--baseline", str(tmp_path / "b.json"), *extra]
        )

    def test_fix_creates_then_growth_fails_and_fix_refuses_to_hide_it(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        module = tmp_path / "src" / "pkg" / "big.py"
        module.parent.mkdir(parents=True)
        module.write_text(_big_class(methods=3), encoding="utf-8")

        assert self._run(tmp_path) == 2  # no baseline yet
        assert self._run(tmp_path, "--fix") == 0
        assert self._run(tmp_path) == 0

        module.write_text(_big_class(methods=4), encoding="utf-8")
        capsys.readouterr()
        assert self._run(tmp_path) == 1
        assert "pkg/big.py::Big: 4 methods" in capsys.readouterr().err
        assert self._run(tmp_path, "--fix") == 1

    def test_fix_records_an_improvement(self, tmp_path: Path) -> None:
        module = tmp_path / "src" / "pkg" / "big.py"
        module.parent.mkdir(parents=True)
        module.write_text(_big_class(methods=4), encoding="utf-8")
        assert self._run(tmp_path, "--fix") == 0

        module.write_text(_big_class(methods=3), encoding="utf-8")
        assert self._run(tmp_path, "--fix") == 0

        data = json.loads((tmp_path / "b.json").read_text(encoding="utf-8"))
        assert data["classes"]["pkg/big.py::Big"]["methods"] == 3


class TestCommittedBaseline:
    def test_the_committed_tree_passes_the_ratchet(self) -> None:
        assert check_class_size.main([]) == 0

    def test_the_god_objects_are_held_with_their_state(self) -> None:
        baseline = check_class_size.load_baseline(BASELINE_FILE)

        for identifier in check_class_size.TRACKED_FIELDS:
            assert identifier in baseline.classes
            assert baseline.fields[identifier] > 0

    def test_the_ratchet_runs_in_the_lint_job(self) -> None:
        workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
        commands = [str(step.get("run", "")) for step in workflow["jobs"]["lint"]["steps"]]

        assert "python scripts/check_class_size.py" in commands
        assert "lint" in workflow["jobs"]["test"]["needs"]

    def test_the_script_needs_only_the_standard_library(self) -> None:
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
