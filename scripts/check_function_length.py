#!/usr/bin/env python3
"""Ratchet the maximum physical length of Python functions in ``src``.

Functions already above the 200-line limit are grandfathered at their current
length. Their allowance can only stay the same or shrink; a new long function,
or growth in an existing one, fails the check.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = REPO_ROOT / "src" / "echo_personal_tool"
DEFAULT_BASELINE = REPO_ROOT / "scripts" / "function_length_baseline.json"
LIMIT = 200


def find_long_functions(source_root: Path, *, limit: int = LIMIT) -> dict[str, int]:
    """Return qualified function names whose source span exceeds ``limit``."""
    long_functions: dict[str, int] = {}

    def visit(node: ast.AST, path: Path, parents: tuple[str, ...]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                qualified = (*parents, child.name)
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    length = child.end_lineno - child.lineno + 1
                    if length > limit:
                        identifier = f"{path.as_posix()}::{'.'.join(qualified)}"
                        long_functions[identifier] = length
                visit(child, path, qualified)
            else:
                visit(child, path, parents)

    for path in sorted(source_root.rglob("*.py")):
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        visit(module, path.relative_to(source_root), ())
    return long_functions


def find_violations(current: dict[str, int], baseline: dict[str, int]) -> tuple[str, ...]:
    """Describe new long functions and any growth beyond the stored ceiling."""
    violations = []
    for identifier, length in sorted(current.items()):
        allowed = baseline.get(identifier)
        if allowed is None:
            violations.append(f"new function is {length} lines: {identifier}")
        elif length > allowed:
            violations.append(f"function grew from {allowed} to {length} lines: {identifier}")
    return tuple(violations)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    args = parser.parse_args(argv)

    try:
        baseline_data = json.loads(args.baseline.read_text(encoding="utf-8"))
        if baseline_data.get("version") != 1 or baseline_data.get("limit") != LIMIT:
            raise ValueError("unsupported function-length baseline version or limit")
        baseline = {str(name): int(value) for name, value in baseline_data["functions"].items()}
        current = find_long_functions(args.source)
    except (OSError, ValueError, KeyError, json.JSONDecodeError, SyntaxError) as exc:
        sys.stderr.write(f"function-length ratchet: {exc}\n")
        return 2

    violations = find_violations(current, baseline)
    if violations:
        sys.stderr.write("function-length ratchet failed:\n")
        for violation in violations:
            sys.stderr.write(f"  - {violation}\n")
        return 1

    sys.stdout.write(f"function-length ratchet passed: no function grew beyond {LIMIT} lines\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
