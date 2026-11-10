#!/usr/bin/env python3
"""Ratchet cross-layer import directions and indirect facade leaks (#419, #477).

The no-cycles gate (`test_import_graph_has_no_cycles`) proves acyclicity, not
ownership: an acyclic `infrastructure -> application` or `ui -> presentation`
edge is still the wrong dependency. And an import-only boundary is defeated
whenever an ``application`` facade re-exports an ``infrastructure`` class
(``ServerSettings = _adapter.ServerSettings``) or ``presentation`` imports an
adapter symbol that ``application`` happened to pull into module scope (#477).

This scanner inventories both:

1. **Direct forbidden-direction imports** (`infrastructure -> application`,
   `ui -> presentation`, `ui -> infrastructure`), classified as module-level,
   lazy or `TYPE_CHECKING`, and compared against the exact allowlist.
2. **Facade re-exports and indirect `presentation`/`ui` -> `infrastructure`
   uses via `application` (#477)**:
   - any public `application` binding (`__all__` entry or non-private
     module-level assignment `Name = _adapter.Attr`) whose AST origin is in
     `echo_personal_tool.infrastructure`;
   - any symbol imported or accessed on an `application` module by
     `presentation` or `ui` whose AST binding in `application` originates in
     `echo_personal_tool.infrastructure`.

Any new edge or unreviewed facade re-export, any growth, and any stale allowlist
entry fail — the exception list cannot grow silently.

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
import sys
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = REPO_ROOT / "src" / "echo_personal_tool"
DEFAULT_ALLOWLIST = REPO_ROOT / "tests" / "architecture" / "layer_direction_allowlist.json"
PACKAGE = "echo_personal_tool"
INFRA_PREFIX = f"{PACKAGE}.infrastructure"
APP_PREFIX = f"{PACKAGE}.application"
UI_CONSUMER_LAYERS = ("presentation", "ui")

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


@dataclass(frozen=True)
class FacadeReexport:
    """A public binding in ``application`` whose AST definition comes from ``infrastructure``."""

    facade_file: str
    line: int
    symbol: str
    infra_origin: str

    @property
    def key(self) -> tuple[str, str]:
        return (self.facade_file, self.symbol)


@dataclass(frozen=True)
class IndirectInfraUse:
    """A ``presentation``/``ui`` reference to an ``application`` symbol defined in ``infrastructure``."""

    source_file: str
    line: int
    facade_file: str
    symbol: str
    infra_origin: str


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


def _module_top_statements(tree: ast.Module) -> Iterator[ast.stmt]:
    """Yield module-level statements, descending into ``if TYPE_CHECKING:`` blocks."""
    for stmt in tree.body:
        yield stmt
        if isinstance(stmt, ast.If) and _is_type_checking(stmt.test):
            yield from stmt.body
            yield from stmt.orelse


def _resolve_from_module(node: ast.ImportFrom, pkg: tuple[str, ...]) -> str:
    if node.level:
        anchor = pkg[: max(len(pkg) - (node.level - 1), 0)]
        return ".".join([*anchor, node.module]) if node.module else ".".join(anchor)
    return node.module or ""


def _dotted_expr(expr: ast.expr) -> tuple[str, ...] | None:
    if isinstance(expr, ast.Name):
        return (expr.id,)
    if isinstance(expr, ast.Attribute):
        head = _dotted_expr(expr.value)
        if head is not None:
            return (*head, expr.attr)
    return None


def _string_list_literal(expr: ast.expr) -> set[str] | None:
    if isinstance(expr, (ast.List, ast.Tuple, ast.Set)):
        items: set[str] = set()
        for elt in expr.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                items.add(elt.value)
        return items
    return None


def _module_name_for_path(path: Path, src_parent: Path) -> tuple[str, str, tuple[str, ...]]:
    relative = path.relative_to(src_parent).as_posix()
    parts = relative[:-3].split("/")
    if parts[-1] == "__init__":
        mod_parts = tuple(parts[:-1])
        pkg = mod_parts
    else:
        mod_parts = tuple(parts)
        pkg = tuple(parts[:-1])
    return relative, ".".join(mod_parts), pkg


def scan_facade_contracts(root: Path) -> tuple[list[FacadeReexport], list[IndirectInfraUse]]:
    """Inventory ``application`` re-exports of ``infrastructure`` and UI uses of them (#477)."""
    app_dir = root / "application"
    if not app_dir.is_dir():
        return [], []

    src_parent = root.parent
    mod_to_rel: dict[str, str] = {}
    app_trees: dict[str, tuple[str, tuple[str, ...], ast.Module]] = {}
    for path in sorted(app_dir.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel, mod_name, pkg = _module_name_for_path(path, src_parent)
        mod_to_rel[mod_name] = rel
        app_trees[mod_name] = (rel, pkg, ast.parse(path.read_text(encoding="utf-8"), filename=rel))

    # Map (app_module -> {local_symbol: (infra_origin, lineno, is_explicit_assign)}).
    raw_bindings: dict[str, dict[str, tuple[str, int, bool]]] = {}
    app_reexports: dict[str, dict[str, tuple[str, str, int, bool]]] = {}
    dunder_all: dict[str, set[str]] = {}

    for mod_name, (_rel, pkg, tree) in app_trees.items():
        infra_syms: dict[str, tuple[str, int, bool]] = {}
        app_aliases: dict[str, str] = {}
        app_sym_links: dict[str, tuple[str, str, int, bool]] = {}
        explicit_all: set[str] | None = None

        for stmt in _module_top_statements(tree):
            if isinstance(stmt, ast.ImportFrom):
                base = _resolve_from_module(stmt, pkg)
                for alias in stmt.names:
                    if alias.name == "*":
                        continue
                    local = alias.asname or alias.name
                    full = f"{base}.{alias.name}" if base else alias.name
                    if full == INFRA_PREFIX or full.startswith(f"{INFRA_PREFIX}."):
                        infra_syms[local] = (full, stmt.lineno, False)
                    elif base == APP_PREFIX or base.startswith(f"{APP_PREFIX}."):
                        if full in app_trees:
                            app_aliases[local] = full
                        else:
                            app_sym_links[local] = (base, alias.name, stmt.lineno, False)
            elif isinstance(stmt, ast.Import):
                for alias in stmt.names:
                    local = alias.asname or alias.name.split(".")[0]
                    if alias.name == INFRA_PREFIX or alias.name.startswith(f"{INFRA_PREFIX}."):
                        infra_syms[local] = (alias.name, stmt.lineno, False)
                    elif alias.name in app_trees and alias.asname:
                        app_aliases[local] = alias.name
            elif isinstance(stmt, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                infra_syms.pop(stmt.name, None)
                app_sym_links.pop(stmt.name, None)
            elif isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Name) and target.id == "__all__":
                        parsed = _string_list_literal(stmt.value)
                        if parsed is not None:
                            explicit_all = parsed
                        continue
                    if not isinstance(target, ast.Name):
                        continue
                    chain = _dotted_expr(stmt.value)
                    if chain is None:
                        infra_syms.pop(target.id, None)
                        continue
                    head = chain[0]
                    tail = ".".join(chain[1:])
                    if head in infra_syms:
                        origin_base = infra_syms[head][0]
                        origin = f"{origin_base}.{tail}" if tail else origin_base
                        infra_syms[target.id] = (origin, stmt.lineno, True)
                    elif head in app_aliases and len(chain) == 2:
                        app_sym_links[target.id] = (app_aliases[head], chain[1], stmt.lineno, True)
            elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.value is not None:
                chain = _dotted_expr(stmt.value)
                if chain is not None and chain[0] in infra_syms:
                    origin_base = infra_syms[chain[0]][0]
                    tail = ".".join(chain[1:])
                    origin = f"{origin_base}.{tail}" if tail else origin_base
                    infra_syms[stmt.target.id] = (origin, stmt.lineno, True)

        raw_bindings[mod_name] = infra_syms
        app_reexports[mod_name] = app_sym_links
        if explicit_all is not None:
            dunder_all[mod_name] = explicit_all

    # Propagate transitive application -> application re-exports to a fixed point.
    changed = True
    while changed:
        changed = False
        for mod_name, links in app_reexports.items():
            for local, (target_mod, target_sym, lineno, is_assign) in links.items():
                if local in raw_bindings[mod_name]:
                    continue
                upstream = raw_bindings.get(target_mod, {}).get(target_sym)
                if upstream is not None:
                    raw_bindings[mod_name][local] = (upstream[0], lineno, is_assign)
                    changed = True

    reexports: list[FacadeReexport] = []
    for mod_name, bindings in sorted(raw_bindings.items()):
        rel = mod_to_rel[mod_name]
        exported = dunder_all.get(mod_name, set())
        for sym, (infra_origin, lineno, is_assign) in sorted(bindings.items()):
            if sym in exported or (is_assign and not sym.startswith("_")):
                reexports.append(FacadeReexport(rel, lineno, sym, infra_origin))

    indirect_uses: list[IndirectInfraUse] = []
    for layer in UI_CONSUMER_LAYERS:
        layer_dir = root / layer
        if not layer_dir.is_dir():
            continue
        for path in sorted(layer_dir.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            rel, _mod_name, pkg = _module_name_for_path(path, src_parent)
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
            module_aliases: dict[str, str] = {}
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    base = _resolve_from_module(node, pkg)
                    if not (base == APP_PREFIX or base.startswith(f"{APP_PREFIX}.")):
                        continue
                    for alias in node.names:
                        if alias.name == "*":
                            continue
                        candidate_mod = f"{base}.{alias.name}"
                        if candidate_mod in raw_bindings:
                            module_aliases[alias.asname or alias.name] = candidate_mod
                            continue
                        hit = raw_bindings.get(base, {}).get(alias.name)
                        if hit is not None:
                            indirect_uses.append(
                                IndirectInfraUse(rel, node.lineno, mod_to_rel[base], alias.name, hit[0])
                            )
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in raw_bindings and alias.asname:
                            module_aliases[alias.asname] = alias.name
            if module_aliases:
                for node in ast.walk(tree):
                    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                        target_mod = module_aliases.get(node.value.id)
                        if target_mod is None:
                            continue
                        hit = raw_bindings.get(target_mod, {}).get(node.attr)
                        if hit is not None:
                            indirect_uses.append(
                                IndirectInfraUse(rel, node.lineno, mod_to_rel[target_mod], node.attr, hit[0])
                            )
    return reexports, indirect_uses


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

    facade_entries = data.get("facade_reexports")
    if facade_entries is not None:
        if not isinstance(facade_entries, list):
            problems.append("'facade_reexports' must be a list when present")
        else:
            seen_reexports: set[tuple[str, str]] = set()
            for index, entry in enumerate(facade_entries):
                if not isinstance(entry, dict):
                    problems.append(f"facade_reexports[{index}] is not an object")
                    continue
                facade = entry.get("facade")
                symbols = entry.get("symbols")
                reason = entry.get("reason")
                issue = entry.get("issue")
                if (
                    not isinstance(facade, str)
                    or not facade.startswith(f"{PACKAGE}/application/")
                    or not facade.endswith(".py")
                ):
                    problems.append(f"facade_reexports[{index}] has invalid facade path {facade!r}")
                if not isinstance(reason, str) or not reason.strip():
                    problems.append(f"facade_reexports[{index}] ({facade}) has no reviewed reason")
                if type(issue) is not int or issue <= 0:
                    problems.append(f"facade_reexports[{index}] ({facade}) needs a positive tracking issue")
                if not isinstance(symbols, dict) or not symbols:
                    problems.append(f"facade_reexports[{index}] ({facade}) needs a non-empty symbols map")
                    continue
                for sym, origin in symbols.items():
                    if not isinstance(sym, str) or not sym:
                        problems.append(f"facade_reexports[{index}] ({facade}) has an empty symbol name")
                    if not isinstance(origin, str) or not origin.startswith(f"{INFRA_PREFIX}."):
                        problems.append(
                            f"facade_reexports[{index}] ({facade}.{sym}) has invalid infrastructure origin {origin!r}"
                        )
                    rkey = (str(facade), str(sym))
                    if rkey in seen_reexports:
                        problems.append(f"duplicate facade_reexports symbol {rkey}")
                    seen_reexports.add(rkey)
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


def expected_facade_reexports(data: dict[str, object]) -> dict[tuple[str, str], str]:
    allowed: dict[tuple[str, str], str] = {}
    entries = data.get("facade_reexports", [])
    if not isinstance(entries, list):
        return allowed
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        facade = entry.get("facade")
        symbols = entry.get("symbols")
        if not isinstance(facade, str) or not isinstance(symbols, dict):
            continue
        for sym, origin in symbols.items():
            if isinstance(sym, str) and isinstance(origin, str):
                allowed[(facade, sym)] = origin
    return allowed


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


def check_facade_contracts(
    reexports: list[FacadeReexport],
    indirect_uses: list[IndirectInfraUse],
    data: dict[str, object],
) -> list[str]:
    """Verify no unreviewed infrastructure symbol leaks through ``application`` (#477)."""
    problems: list[str] = []
    allowed = expected_facade_reexports(data)
    actual = {item.key: item for item in reexports}

    for key in sorted(actual.keys() - allowed.keys()):
        item = actual[key]
        problems.append(
            f"NEW facade re-export {item.facade_file}:{item.line} {item.symbol} -> {item.infra_origin} "
            "(replace with an application-owned dataclass/Protocol or def wrapper)"
        )
    for key in sorted(allowed.keys() - actual.keys()):
        problems.append(f"STALE facade_reexports allowlist entry {key[0]}::{key[1]} (remove it after migrating)")
    for key in sorted(actual.keys() & allowed.keys()):
        if actual[key].infra_origin != allowed[key]:
            problems.append(
                f"CHANGED facade re-export {key[0]}::{key[1]}: "
                f"expected {allowed[key]}, found {actual[key].infra_origin}"
            )

    for use in sorted(indirect_uses, key=lambda u: (u.source_file, u.line, u.symbol)):
        if (use.facade_file, use.symbol) not in allowed:
            problems.append(
                f"NEW indirect presentation->infrastructure use at {use.source_file}:{use.line}: "
                f"{use.facade_file}::{use.symbol} originates in {use.infra_origin}"
            )
    return problems


def format_inventory(
    edges: list[Edge],
    reexports: list[FacadeReexport] | None = None,
    indirect_uses: list[IndirectInfraUse] | None = None,
) -> str:
    lines: list[str] = []
    for direction in FORBIDDEN:
        group = [edge for edge in edges if edge.direction == direction]
        lines.append(f"=== {direction}: {len(group)} import(s) ===")
        for edge in sorted(group, key=lambda item: (item.source_file, item.line)):
            lines.append(f"  {edge.source_file}:{edge.line}  {edge.kind:<9}  {edge.dest_module}")
        if not group:
            lines.append("  (none)")
    if reexports is not None:
        lines.append(f"=== application facade re-exports of infrastructure: {len(reexports)} symbol(s) ===")
        for item in reexports:
            lines.append(f"  {item.facade_file}:{item.line}  {item.symbol} -> {item.infra_origin}")
        if not reexports:
            lines.append("  (none)")
    if indirect_uses is not None:
        lines.append(f"=== presentation/ui uses of reviewed facade re-exports: {len(indirect_uses)} site(s) ===")
        if not indirect_uses:
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
    reexports, indirect_uses = scan_facade_contracts(args.root)
    if args.list:
        print(format_inventory(edges, reexports, indirect_uses))
        return 0

    data, baseline_problems = load_allowlist(args.allowlist)
    problems = check(edges, data, baseline_problems)
    problems.extend(check_facade_contracts(reexports, indirect_uses, data))
    counts = edge_counts(edges)
    summary = (
        f"layer directions: {len(edges)} reviewed forbidden import(s) in {len(counts)} edges, "
        f"{len(reexports)} reviewed facade function re-export(s), 0 unreviewed indirect infrastructure uses"
        if not problems
        else "layer-direction gate FAILED:\n" + "\n".join(f"- {item}" for item in problems)
    )
    print(summary)
    if args.github_summary and os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as handle:
            handle.write(
                "### Layer-direction ratchet\n\n```\n"
                + format_inventory(edges, reexports, indirect_uses)
                + "\n```\n\n"
                + summary
                + "\n"
            )
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
