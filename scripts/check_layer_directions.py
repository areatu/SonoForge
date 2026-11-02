#!/usr/bin/env python3
"""Ratchet the *direction* of cross-layer imports (issue #419).

The no-cycles gate (`test_import_graph_has_no_cycles`) proves acyclicity, not
ownership: an acyclic `infrastructure -> application` or `ui -> presentation`
edge is still the wrong dependency. This scanner inventories those edges with
file/line and classifies them, then compares them with an explicitly reviewed
baseline. Any new edge, any growth in an existing edge, and any stale baseline
entry fail — the exception list cannot grow silently.

Decisions recorded in the allowlist:

* `application -> infrastructure` is allowed: the application facade owns the
  adapters. The reverse (`infrastructure -> application`) is forbidden; a
  contract belongs to its consumer, not to the adapter that happens to need it.
  `application/preferences_contract.py` therefore stays in application — it is
  not moved into `domain/ports.py` without an argument about the owner.
* `presentation -> ui` is allowed: presentation is the composition root and
  may mount leaf widgets. `ui -> presentation` is forbidden; leaf widgets must
  not reach back into the shell.
* `ui -> infrastructure` is forbidden for the same reason as the existing
  `presentation -> infrastructure` ratchet (#307): UI layers go through the
  application facade. Historical edges are baselined, not fixed here; removing
  them belongs to small follow-up slices with characterization tests.

Classification is a conservative proxy for "real call": a module-level import
is a runtime dependency, an import inside a function is lazy, and one inside
`if TYPE_CHECKING:` is type-only. All three are gated; `--list` shows which is
which so a follow-up slice can pick the cheap ones first.

Standard library only: the lint job installs nothing to run this.

Usage:  python scripts/check_layer_directions.py [--list] [--github-summary]
        python scripts/check_layer_directions.py --root SRC --allowlist JSON
Exit:   0 — clean, 1 — new/stale/grown edge or invalid baseline, 2 — usage/IO.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = REPO_ROOT / "src" / "echo_personal_tool"
DEFAULT_ALLOWLIST = REPO_ROOT / "tests" / "architecture" / "layer_direction_allowlist.json"
PACKAGE = "echo_personal_tool"

#: source layer -> destination layer. Only these directions are forbidden.
FORBIDDEN: dict[str, tuple[str, str]] = {
    "infrastructure>application": ("infrastructure", "application"),
    "ui>presentation": ("ui", "presentation"),
    "ui>infrastructure": ("ui", "infrastructure"),
}


@dataclass(frozen=True)
class Edge:
    direction: str
    source_file: str
    line: int
    dest_module: str
    kind: str  # "module" | "lazy" | "type-only"

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.direction, self.source_file, self.dest_module)


def _is_type_checking(test: ast.expr) -> bool:
    if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
        return True
    return (
        isinstance(test, ast.Attribute)
        and test.attr == "TYPE_CHECKING"
        and isinstance(test.value, ast.Name)
        and test.value.id == "typing"
    )


def _walk(node: ast.AST, parents: tuple[ast.AST, ...] = ()) -> Iterator[tuple[ast.AST, tuple[ast.AST, ...]]]:
    for child in ast.iter_child_nodes(node):
        chain = (child,) + parents
        yield child, chain
        yield from _walk(child, chain)


def _kind(parents: tuple[ast.AST, ...]) -> str:
    for parent in parents:
        if isinstance(parent, ast.If) and _is_type_checking(parent.test):
            return "type-only"
    if any(isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)) for parent in parents):
        return "lazy"
    return "module"


def _imported_modules(node: ast.AST, pkg: tuple[str, ...]) -> list[str]:
    modules: list[str] = []
    if isinstance(node, ast.ImportFrom):
        if node.level:
            anchor = pkg[: max(len(pkg) - (node.level - 1), 0)]
            if node.module:
                modules.append(".".join([*anchor, node.module]))
            else:
                modules.extend(".".join([*anchor, alias.name]) for alias in node.names)
        elif node.module:
            modules.append(node.module)
            if node.module == PACKAGE:
                modules.extend(f"{PACKAGE}.{alias.name}" for alias in node.names)
    elif isinstance(node, ast.Import):
        modules.extend(alias.name for alias in node.names)
    return modules


def inventory(root: Path) -> list[Edge]:
    """Inventory forbidden-direction imports under a package root."""
    edges: list[Edge] = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root.parent).as_posix()
        parts = relative[:-3].split("/")
        if len(parts) < 2 or parts[0] != PACKAGE:
            continue
        source_layer = parts[1]
        relevant = {name: dest for name, (src, dest) in FORBIDDEN.items() if src == source_layer}
        if not relevant:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        pkg = tuple(parts[:-1])
        for node, parents in _walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            for module in _imported_modules(node, pkg):
                for direction, dest_layer in relevant.items():
                    if module == f"{PACKAGE}.{dest_layer}" or module.startswith(f"{PACKAGE}.{dest_layer}."):
                        edges.append(Edge(direction, relative, node.lineno, module, _kind(parents)))
    return edges


def edge_counts(edges: list[Edge]) -> Counter[tuple[str, str, str]]:
    return Counter(edge.key for edge in edges)


def load_allowlist(path: Path) -> tuple[dict[str, object], list[str]]:
    """Return (data, problems); an invalid baseline is a failure, not a skip."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, [f"cannot read allowlist {path}: {exc}"]
    problems: list[str] = []
    if not isinstance(data, dict):
        return {}, ["allowlist must be a JSON object"]
    if data.get("origin_issue") != 419:
        problems.append("allowlist origin_issue must be 419")
    decisions = data.get("decisions")
    if not isinstance(decisions, dict):
        problems.append("allowlist needs a 'decisions' object")
    else:
        for direction in FORBIDDEN:
            text = decisions.get(direction)
            if not isinstance(text, str) or not text.strip():
                problems.append(f"missing decision/reason for forbidden direction {direction}")
        for direction in ("presentation>ui", "application>infrastructure"):
            text = decisions.get(direction)
            if not isinstance(text, str) or not text.strip():
                problems.append(f"missing decision for allowed direction {direction}")
    entries = data.get("entries")
    if not isinstance(entries, list):
        problems.append("allowlist needs an 'entries' list")
        return data, problems
    seen: set[tuple[str, str, str]] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            problems.append(f"entry {index} is not an object")
            continue
        direction, source, imports = entry.get("direction"), entry.get("source"), entry.get("imports")
        reason, issue = entry.get("reason"), entry.get("issue")
        if direction not in FORBIDDEN:
            problems.append(f"entry {index} has unknown direction {direction!r}")
        if not isinstance(source, str) or not source.startswith(f"{PACKAGE}/") or not source.endswith(".py"):
            problems.append(f"entry {index} has an invalid source path {source!r}")
        if not isinstance(reason, str) or not reason.strip():
            problems.append(f"entry {index} ({source}) has no reviewed reason")
        if type(issue) is not int or issue <= 0:
            problems.append(f"entry {index} ({source}) needs a positive tracking issue")
        if not isinstance(imports, dict) or not imports:
            problems.append(f"entry {index} ({source}) needs a non-empty imports map")
            continue
        for module, count in imports.items():
            if not isinstance(module, str) or not module.startswith(f"{PACKAGE}."):
                problems.append(f"entry {index} ({source}) has an invalid module {module!r}")
            if type(count) is not int or count < 1:
                problems.append(f"entry {index} ({source}/{module}) needs a positive count")
            key = (str(direction), str(source), str(module))
            if key in seen:
                problems.append(f"duplicate allowlist edge {key}")
            seen.add(key)
    return data, problems


def expected_counts(data: dict[str, object]) -> Counter[tuple[str, str, str]]:
    counts: Counter[tuple[str, str, str]] = Counter()
    entries = data.get("entries", [])
    if not isinstance(entries, list):
        return counts
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        imports = entry.get("imports")
        if not isinstance(imports, dict):
            continue
        for module, count in imports.items():
            if isinstance(count, int):
                counts[(str(entry.get("direction")), str(entry.get("source")), str(module))] += count
    return counts


def check(edges: list[Edge], data: dict[str, object], baseline_problems: list[str]) -> list[str]:
    problems = list(baseline_problems)
    actual = edge_counts(edges)
    expected = expected_counts(data)
    lines: dict[tuple[str, str, str], list[str]] = {}
    for edge in edges:
        lines.setdefault(edge.key, []).append(f"{edge.source_file}:{edge.line} ({edge.kind})")

    for key in sorted(actual.keys() - expected.keys()):
        problems.append(f"NEW forbidden edge {key[0]} {key[1]} -> {key[2]} at {', '.join(lines[key])}")
    for key in sorted(expected.keys() - actual.keys()):
        problems.append(f"STALE baseline edge {key[0]} {key[1]} -> {key[2]} (remove it with a reviewed slice)")
    for key in sorted(actual.keys() & expected.keys()):
        if actual[key] > expected[key]:
            problems.append(
                f"GROWN forbidden edge {key[0]} {key[1]} -> {key[2]}: "
                f"{expected[key]} -> {actual[key]} import(s) at {', '.join(lines[key])}"
            )
        elif actual[key] < expected[key]:
            problems.append(
                f"STALE baseline count {key[0]} {key[1]} -> {key[2]}: expected {expected[key]}, found {actual[key]}"
            )
    return problems


def format_inventory(edges: list[Edge]) -> str:
    lines: list[str] = []
    for direction in FORBIDDEN:
        group = [edge for edge in edges if edge.direction == direction]
        lines.append(f"=== {direction}: {len(group)} import(s) ===")
        for edge in sorted(group, key=lambda item: (item.source_file, item.line)):
            lines.append(f"  {edge.source_file}:{edge.line}  {edge.kind:<9}  {edge.dest_module}")
        if not group:
            lines.append("  (none)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="source package root")
    parser.add_argument("--allowlist", type=Path, default=DEFAULT_ALLOWLIST)
    parser.add_argument("--list", action="store_true", help="print the AST inventory and exit")
    parser.add_argument("--github-summary", action="store_true", help="append a report to GITHUB_STEP_SUMMARY")
    args = parser.parse_args(argv)

    if not args.root.is_dir():
        print(f"check_layer_directions: no such source root {args.root}", file=sys.stderr)
        return 2
    edges = inventory(args.root)
    if args.list:
        print(format_inventory(edges))
        return 0

    data, baseline_problems = load_allowlist(args.allowlist)
    problems = check(edges, data, baseline_problems)
    counts = edge_counts(edges)
    summary = (
        f"layer directions: {len(edges)} reviewed forbidden import(s) in {len(counts)} edges, "
        f"{len(FORBIDDEN)} forbidden directions — no new, grown or stale edge"
        if not problems
        else "layer-direction gate FAILED:\n" + "\n".join(f"- {item}" for item in problems)
    )
    print(summary)
    if args.github_summary and os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as handle:
            handle.write(
                "### Layer-direction ratchet\n\n```\n" + format_inventory(edges) + "\n```\n\n" + summary + "\n"
            )
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
