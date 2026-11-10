#!/usr/bin/env python3
"""Ratchet runtime modules that are never imported or referenced in tests (issue 483).

Static AST inventory of ``src/echo_personal_tool/**/*.py`` against ``tests/**/*.py``:
a runtime module counts as referenced by tests when at least one test file
imports it (``import``, ``from ... import``, ``importlib.import_module``,
``__import__``) or references one of its public top-level classes, functions,
or ``__all__`` symbols. String literals inside ``monkeypatch.setattr("...")``
do NOT count — replacing a module with a mock in a caller's test is not a test
of that module.

Ratchet rules against ``scripts/untested_modules_baseline.json``:
  - Any new untested module not present in the baseline fails CI.
  - The total count of untested modules may only stay equal or shrink.
  - ``--fix`` lowers the baseline when modules gain tests and refuses to add
    new untested modules.

Standard library only so ``lint`` can run it without extra dependencies.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

PACKAGE_NAME = "echo_personal_tool"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SRC_ROOT = REPO_ROOT / "src"
DEFAULT_TESTS_ROOT = REPO_ROOT / "tests"
DEFAULT_BASELINE = Path(__file__).resolve().with_name("untested_modules_baseline.json")

# CLI entry points are exercised via subprocess / package_smoke rather than Python imports.
_EXCLUDED_MODULES = frozenset(
    {
        f"{PACKAGE_NAME}.__main__",
        f"{PACKAGE_NAME}.__main_presenter__",
    }
)


@dataclass(frozen=True)
class UntestedModule:
    relpath: str
    module: str
    layer: str
    lines: int
    public_symbols: tuple[str, ...]


def _discover_runtime_modules(src_root: Path) -> list[tuple[str, str, Path]]:
    """Return sorted ``(relpath, dotted_module, path)`` for runtime modules."""
    pkg_root = src_root / PACKAGE_NAME
    found: list[tuple[str, str, Path]] = []
    for path in sorted(pkg_root.rglob("*.py")):
        if path.name == "__init__.py":
            continue
        rel_to_pkg = path.relative_to(pkg_root)
        if rel_to_pkg.parts and rel_to_pkg.parts[0] == "scripts":
            continue
        rel_to_src = path.relative_to(src_root).as_posix()
        dotted = rel_to_src[:-3].replace("/", ".")
        if dotted in _EXCLUDED_MODULES:
            continue
        found.append((rel_to_src, dotted, path))
    return found


def _public_symbols(tree: ast.Module) -> tuple[str, ...]:
    """Extract top-level public classes, functions, and ``__all__`` exports."""
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_"):
                names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    if isinstance(node.value, (ast.List, ast.Tuple)):
                        for elt in node.value.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                names.add(elt.value)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and not node.target.id.startswith("_"):
                names.add(node.target.id)
    return tuple(sorted(names))


def _collect_test_references(tests_root: Path) -> tuple[set[str], set[str]]:
    """Return ``(imported_modules, referenced_identifiers)`` across ``tests_root``."""
    imported_modules: set[str] = set()
    referenced_names: set[str] = set()

    for test_file in sorted(tests_root.rglob("*.py")):
        source = test_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(test_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_modules.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported_modules.add(node.module)
                    for alias in node.names:
                        if alias.name != "*":
                            imported_modules.add(f"{node.module}.{alias.name}")
                            referenced_names.add(alias.name)
            elif isinstance(node, ast.Call) and node.args:
                func = node.func
                is_import_mod = (
                    isinstance(func, ast.Attribute)
                    and func.attr == "import_module"
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "importlib"
                )
                is_dunder = isinstance(func, ast.Name) and func.id == "__import__"
                first = node.args[0]
                if (is_import_mod or is_dunder) and isinstance(first, ast.Constant) and isinstance(first.value, str):
                    imported_modules.add(first.value)
            elif isinstance(node, ast.Name):
                referenced_names.add(node.id)
            elif isinstance(node, ast.Attribute):
                referenced_names.add(node.attr)

    return imported_modules, referenced_names


def scan_untested_modules(src_root: Path, tests_root: Path) -> list[UntestedModule]:
    """Scan ``src_root`` and return runtime modules not referenced in ``tests_root``."""
    imported_modules, referenced_names = _collect_test_references(tests_root)
    untested: list[UntestedModule] = []

    for relpath, dotted, path in _discover_runtime_modules(src_root):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        pubs = _public_symbols(tree)
        is_imported = dotted in imported_modules or any(m.startswith(dotted + ".") for m in imported_modules)
        has_symbol_ref = bool(set(pubs) & referenced_names)
        if not is_imported and not has_symbol_ref:
            parts = relpath.split("/")
            layer = parts[1] if len(parts) > 2 else "root"
            untested.append(
                UntestedModule(
                    relpath=relpath,
                    module=dotted,
                    layer=layer,
                    lines=len(source.splitlines()),
                    public_symbols=pubs,
                )
            )
    return untested


def load_baseline(path: Path) -> tuple[set[str], int]:
    data = json.loads(path.read_text(encoding="utf-8"))
    modules = data.get("modules")
    if not isinstance(modules, list) or not all(isinstance(item, str) for item in modules):
        raise ValueError(f"{path}: 'modules' must be a list of strings")
    count = int(data.get("count", len(modules)))
    return set(modules), count


def write_baseline(path: Path, modules: list[UntestedModule]) -> None:
    relpaths = sorted(item.relpath for item in modules)
    payload = {
        "origin_issue": 483,
        "policy": (
            "Ratchet of runtime modules with zero static import or public-symbol "
            "reference in tests/. The set and count may only shrink; --fix "
            "removes newly tested modules and refuses to add new untested ones."
        ),
        "count": len(relpaths),
        "modules": relpaths,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def render_markdown_summary(current: list[UntestedModule], baseline_count: int) -> str:
    total_lines = sum(item.lines for item in current)
    by_layer = Counter(item.layer for item in current)
    layer_str = ", ".join(f"`{layer}`: {cnt}" for layer, cnt in sorted(by_layer.items())) or "none"
    lines = [
        "### Untested modules ratchet (issue 483)",
        "",
        f"- **Untested runtime modules**: **{len(current)}** (baseline ceiling: **{baseline_count}**, total `{total_lines}` LOC)",
        f"- **By layer**: {layer_str}",
        "",
    ]
    if current:
        lines.extend(
            [
                "| Module | Layer | Lines | Public symbols |",
                "|---|---|---:|---|",
            ]
        )
        for item in current:
            syms = ", ".join(f"`{s}`" for s in item.public_symbols[:4]) or "—"
            lines.append(f"| `{item.relpath}` | `{item.layer}` | {item.lines} | {syms} |")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src-root", type=Path, default=DEFAULT_SRC_ROOT)
    parser.add_argument("--tests-root", type=Path, default=DEFAULT_TESTS_ROOT)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--list", action="store_true", help="Print all currently untested modules and exit 0.")
    parser.add_argument("--fix", action="store_true", help="Refresh baseline when untested modules shrink.")
    parser.add_argument("--github-summary", action="store_true", help="Append Markdown report to GITHUB_STEP_SUMMARY.")
    args = parser.parse_args(argv)

    if not args.src_root.is_dir() or not args.tests_root.is_dir():
        print(f"audit_untested_modules: invalid roots src={args.src_root} tests={args.tests_root}", file=sys.stderr)
        return 2

    current = scan_untested_modules(args.src_root, args.tests_root)
    current_paths = {item.relpath for item in current}

    if args.list:
        for item in current:
            print(f"{item.relpath} ({item.lines} lines) [{item.layer}] {list(item.public_symbols)}")
        print(f"Total: {len(current)} module(s), {sum(x.lines for x in current)} line(s)")
        return 0

    if not args.baseline.is_file():
        if args.fix:
            write_baseline(args.baseline, current)
            print(f"untested-modules baseline initialized: {len(current)} module(s)")
            return 0
        print(f"audit_untested_modules: missing baseline {args.baseline}", file=sys.stderr)
        return 2

    baseline_paths, baseline_count = load_baseline(args.baseline)
    added = sorted(current_paths - baseline_paths)
    covered = sorted(baseline_paths - current_paths)

    if args.fix:
        if added:
            print(
                "untested-modules ratchet: refusing to add untested modules with --fix:\n"
                + "\n".join(f"  + {m}" for m in added),
                file=sys.stderr,
            )
            return 1
        write_baseline(args.baseline, current)
        print(f"untested-modules baseline refreshed: {len(current)} module(s) (was {baseline_count})")
        return 0

    if args.github_summary and os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as handle:
            handle.write(render_markdown_summary(current, baseline_count) + "\n")

    problems: list[str] = []
    for mod in added:
        problems.append(f"NEW untested module: {mod} (add behavioral tests under tests/)")
    if len(current) > baseline_count:
        problems.append(f"untested module count grew: {len(current)} > baseline {baseline_count}")

    if problems:
        print("untested-modules ratchet FAILED:\n" + "\n".join(f"  - {p}" for p in problems), file=sys.stderr)
        return 1

    extra = f" ({len(covered)} newly covered; run --fix to lower ceiling)" if covered else ""
    print(f"untested-modules ratchet passed: {len(current)} untested module(s) within baseline {baseline_count}{extra}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
