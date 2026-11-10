#!/usr/bin/env python3
"""Ratchet the size of the largest classes and modules in ``src`` (issue #474).

``check_function_length.py`` stops a single function from growing past 200
lines, and the cheapest way to satisfy it is to cut the function into more
private methods of the *same* class. That is how ``main_window.py`` grew from
2 752 to 7 719 lines in two months while every function stayed short. This
script measures what actually grows:

* **classes above 1 500 lines and modules above 2 000 lines** are
  grandfathered in ``scripts/class_size_baseline.json`` with their line count
  and, for classes, their **number of methods**. Both are ceilings: adding a
  method to ``MainWindow`` without removing another fails, and so does any
  line of growth;
* **a new class or module above the threshold fails** — a new god object
  does not get a baseline entry by accident;
* **ownership of state is tracked** for the classes named in
  ``TRACKED_FIELDS``: the number of distinct ``self.<name>`` attributes the
  class assigns. Each decomposition slice that moves state out (#478, #479)
  shows up here, and moving it back fails.

Improvements are not lost: ``--fix`` lowers every ceiling to the current value
(it never raises one) and drops entries that fell below their threshold, so
commit the baseline together with the refactoring that earned it. A plain run
mentions the unrecorded slack without failing, so parallel PRs do not conflict
on the baseline file.

Standard library only. Exit codes: 0 — within the baseline, 1 — violations,
2 — usage/parse/baseline errors.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = REPO_ROOT / "src" / "echo_personal_tool"
DEFAULT_BASELINE = REPO_ROOT / "scripts" / "class_size_baseline.json"

CLASS_LIMIT = 1500
MODULE_LIMIT = 2000
BASELINE_VERSION = 1
#: Classes whose ``self.*`` attribute count is part of the ratchet (state ownership).
TRACKED_FIELDS = (
    "presentation/viewer_widget.py::ViewerWidget",
    "presentation/main_window.py::MainWindow",
    "application/app_controller.py::AppController",
)
BASELINE_COMMENT = (
    "Ratchet for issue #474 (python scripts/check_class_size.py). Every number is a ceiling: classes above "
    f"{CLASS_LIMIT} lines (lines, methods), modules above {MODULE_LIMIT} lines, and the self.* attribute count "
    "of the tracked classes may only stay or go down. Run --fix after a refactoring to lower them; it never "
    "raises a ceiling."
)


@dataclass(frozen=True)
class ClassSize:
    lines: int
    methods: int
    fields: int


@dataclass(frozen=True)
class Measurement:
    classes: dict[str, ClassSize]
    modules: dict[str, int]


def _self_fields(class_node: ast.ClassDef) -> set[str]:
    """Distinct ``self.<name>`` targets assigned in the methods of the class (nested classes excluded)."""
    fields: set[str] = set()

    def targets(node: ast.AST) -> list[ast.expr]:
        if isinstance(node, ast.Assign):
            return list(node.targets)
        if isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            return [node.target]
        if isinstance(node, (ast.For, ast.AsyncFor)):
            return [node.target]
        if isinstance(node, ast.withitem) and node.optional_vars is not None:
            return [node.optional_vars]
        if isinstance(node, ast.NamedExpr):
            return [node.target]
        return []

    def collect(target: ast.expr) -> None:
        if isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                collect(element)
        elif isinstance(target, ast.Starred):
            collect(target.value)
        elif isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self":
            fields.add(target.attr)

    def visit(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                continue
            for target in targets(child):
                collect(target)
            visit(child)

    for statement in class_node.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            visit(statement)
    return fields


def measure(source_root: Path) -> Measurement:
    """Line/method/field counts of every class and the line count of every module above its threshold.

    The tracked classes are always measured so their field count is known even if they shrink below
    the class threshold.
    """
    classes: dict[str, ClassSize] = {}
    modules: dict[str, int] = {}
    for path in sorted(source_root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        relative = path.relative_to(source_root).as_posix()
        text = path.read_text(encoding="utf-8")
        line_count = len(text.splitlines())
        if line_count > MODULE_LIMIT:
            modules[relative] = line_count
        tree = ast.parse(text, filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            identifier = f"{relative}::{node.name}"
            lines = node.end_lineno - node.lineno + 1 if node.end_lineno is not None else 0
            if lines <= CLASS_LIMIT and identifier not in TRACKED_FIELDS:
                continue
            methods = sum(isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) for item in node.body)
            classes[identifier] = ClassSize(lines=lines, methods=methods, fields=len(_self_fields(node)))
    return Measurement(classes=classes, modules=modules)


# ── baseline ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Baseline:
    classes: dict[str, dict[str, int]]
    modules: dict[str, int]
    fields: dict[str, int]


def load_baseline(path: Path) -> Baseline:
    """Read and validate the baseline; raises ``OSError``/``ValueError``/``KeyError``."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != BASELINE_VERSION:
        raise ValueError(f"unsupported baseline version in {path}: {data.get('version')!r}")
    if data.get("class_limit") != CLASS_LIMIT or data.get("module_limit") != MODULE_LIMIT:
        raise ValueError(f"baseline limits differ from the script ({CLASS_LIMIT}/{MODULE_LIMIT} lines)")
    classes = data["classes"]
    if not isinstance(classes, dict) or not all(
        isinstance(entry, dict)
        and set(entry) == {"lines", "methods"}
        and all(isinstance(value, int) and value >= 0 for value in entry.values())
        for entry in classes.values()
    ):
        raise ValueError("'classes' must map class ids to {'lines': int, 'methods': int}")
    for key in ("modules", "fields"):
        section = data[key]
        if not isinstance(section, dict) or not all(
            isinstance(value, int) and value >= 0 for value in section.values()
        ):
            raise ValueError(f"'{key}' must map names to non-negative integers")
    return Baseline(classes=dict(classes), modules=dict(data["modules"]), fields=dict(data["fields"]))


def baseline_payload(current: Measurement, previous: Baseline | None = None) -> dict[str, object]:
    """The baseline that records ``current`` — never above ``previous`` where an entry already exists."""

    def capped(value: int, ceiling: int | None) -> int:
        return value if ceiling is None else min(value, ceiling)

    classes: dict[str, dict[str, int]] = {}
    for identifier, size in sorted(current.classes.items()):
        if size.lines <= CLASS_LIMIT:
            continue
        before = previous.classes.get(identifier, {}) if previous else {}
        classes[identifier] = {
            "lines": capped(size.lines, before.get("lines")),
            "methods": capped(size.methods, before.get("methods")),
        }
    modules = {
        name: capped(lines, previous.modules.get(name) if previous else None)
        for name, lines in sorted(current.modules.items())
    }
    fields = {
        identifier: capped(current.classes[identifier].fields, previous.fields.get(identifier) if previous else None)
        for identifier in sorted(TRACKED_FIELDS)
        if identifier in current.classes
    }
    return {
        "version": BASELINE_VERSION,
        "comment": BASELINE_COMMENT,
        "class_limit": CLASS_LIMIT,
        "module_limit": MODULE_LIMIT,
        "classes": classes,
        "modules": modules,
        "fields": fields,
    }


def find_violations(current: Measurement, baseline: Baseline) -> tuple[str, ...]:
    """Growth of a ceiling and new entries above a threshold, with the delta."""
    violations: list[str] = []
    for identifier, size in sorted(current.classes.items()):
        allowed = baseline.classes.get(identifier)
        if allowed is None:
            if size.lines > CLASS_LIMIT:
                violations.append(
                    f"new class above {CLASS_LIMIT} lines: {identifier} ({size.lines} lines, "
                    f"{size.methods} methods) — split it instead of growing it"
                )
        else:
            if size.methods > allowed["methods"]:
                violations.append(
                    f"{identifier}: {size.methods} methods, the baseline allows {allowed['methods']} "
                    f"(+{size.methods - allowed['methods']}) — move behaviour into a collaborator, "
                    "or remove a method for every one you add"
                )
            if size.lines > allowed["lines"]:
                violations.append(
                    f"{identifier}: {size.lines} lines, the baseline allows {allowed['lines']} "
                    f"(+{size.lines - allowed['lines']})"
                )
        ceiling = baseline.fields.get(identifier)
        if ceiling is not None and size.fields > ceiling:
            violations.append(
                f"{identifier}: owns {size.fields} self.* attributes, the baseline allows {ceiling} "
                f"(+{size.fields - ceiling}) — new state belongs in the collaborator that uses it"
            )
    for name, lines in sorted(current.modules.items()):
        allowed_lines = baseline.modules.get(name)
        if allowed_lines is None:
            violations.append(f"new module above {MODULE_LIMIT} lines: {name} ({lines} lines)")
        elif lines > allowed_lines:
            violations.append(
                f"module {name}: {lines} lines, the baseline allows {allowed_lines} (+{lines - allowed_lines})"
            )
    for identifier in sorted(set(baseline.fields) - set(current.classes)):
        violations.append(f"tracked class {identifier} no longer exists — update TRACKED_FIELDS and --fix")
    return tuple(violations)


def find_slack(current: Measurement, baseline: Baseline) -> tuple[str, ...]:
    """Ceilings above the current value (informational; ``--fix`` records them)."""
    slack: list[str] = []
    for identifier, allowed in sorted(baseline.classes.items()):
        size = current.classes.get(identifier)
        if size is None or size.lines <= CLASS_LIMIT:
            slack.append(f"{identifier} is no longer above {CLASS_LIMIT} lines")
            continue
        for metric in ("lines", "methods"):
            value = getattr(size, metric)
            if value < allowed[metric]:
                slack.append(f"{identifier}: {metric} {allowed[metric]} -> {value}")
    for name, allowed_lines in sorted(baseline.modules.items()):
        lines = current.modules.get(name)
        if lines is None:
            slack.append(f"module {name} is no longer above {MODULE_LIMIT} lines")
        elif lines < allowed_lines:
            slack.append(f"module {name}: lines {allowed_lines} -> {lines}")
    for identifier, ceiling in sorted(baseline.fields.items()):
        size = current.classes.get(identifier)
        if size is not None and size.fields < ceiling:
            slack.append(f"{identifier}: self.* attributes {ceiling} -> {size.fields}")
    return tuple(slack)


def write_baseline(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ── command line ────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ratchet class and module size in src (issue #474).")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument(
        "--fix", action="store_true", help="lower the ceilings to the current values (creates the baseline)"
    )
    args = parser.parse_args(argv)

    try:
        current = measure(args.source)
    except (OSError, SyntaxError, UnicodeDecodeError) as exc:
        sys.stderr.write(f"class-size ratchet: cannot analyse {args.source}: {exc}\n")
        return 2
    if not current.classes and not current.modules:
        sys.stderr.write(f"class-size ratchet: nothing measured under {args.source} — wrong --source?\n")
        return 2

    previous: Baseline | None = None
    if args.baseline.exists():
        try:
            previous = load_baseline(args.baseline)
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            sys.stderr.write(f"class-size ratchet: cannot read {args.baseline}: {exc}\n")
            return 2

    if args.fix:
        violations = find_violations(current, previous) if previous else ()
        if violations:
            sys.stderr.write("class-size ratchet: refusing to raise a ceiling — --fix only lowers it:\n")
            sys.stderr.write("".join(f"  - {violation}\n" for violation in violations))
            return 1
        write_baseline(args.baseline, baseline_payload(current, previous))
        sys.stdout.write(f"class-size baseline {'refreshed' if previous else 'created'}: {args.baseline}\n")
        return 0

    if previous is None:
        sys.stderr.write(
            f"class-size ratchet: {args.baseline} does not exist — create it with "
            "`python scripts/check_class_size.py --fix`\n"
        )
        return 2

    violations = find_violations(current, previous)
    if violations:
        sys.stderr.write(f"class-size ratchet failed ({len(violations)} problem(s)):\n")
        sys.stderr.write("".join(f"  - {violation}\n" for violation in violations))
        return 1
    slack = find_slack(current, previous)
    if slack:
        sys.stdout.write("class-size ratchet: smaller than the baseline — `--fix` records it:\n")
        sys.stdout.write("".join(f"  - {line}\n" for line in slack))
    sys.stdout.write(
        f"class-size ratchet passed: {len(previous.classes)} classes above {CLASS_LIMIT} lines and "
        f"{len(previous.modules)} modules above {MODULE_LIMIT} lines did not grow\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
