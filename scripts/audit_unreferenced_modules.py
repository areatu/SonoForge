#!/usr/bin/env python3
"""Fail when an application module has no static importers.

The scan is deliberately AST-based: it does not import Qt-heavy application
modules and it includes imports under TYPE_CHECKING. Literal calls to
``importlib.import_module`` and ``__import__`` are included. Runtime-computed
module names still need an explicit entry point in code review.

Run from any directory:

    python scripts/audit_unreferenced_modules.py
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import sys
from collections import defaultdict
from pathlib import Path

PACKAGE_NAME = "echo_personal_tool"
# These modules are launched by Python, not imported by another application
# module. Tooling under ``echo_personal_tool.scripts`` is intentionally outside
# the runtime inventory for the same reason.
_ENTRYPOINTS = frozenset(
    {
        f"{PACKAGE_NAME}.__main__",
        f"{PACKAGE_NAME}.__main_presenter__",
    }
)


def _module_names(package_root: Path) -> dict[str, Path]:
    """Map importable application module names to their source files."""
    modules: dict[str, Path] = {}
    for path in sorted(package_root.rglob("*.py")):
        relative = path.relative_to(package_root)
        if relative.parts and relative.parts[0] == "scripts":
            continue
        parts = list(relative.parts)
        if parts[-1] == "__init__.py":
            parts.pop()
        else:
            parts[-1] = path.stem
        name = ".".join((PACKAGE_NAME, *parts)) if parts else PACKAGE_NAME
        modules[name] = path
    return modules


def _resolve_imports(module: str, path: Path, tree: ast.Module, modules: set[str]) -> set[str]:
    """Return application modules imported by one parsed module."""
    package = module if path.name == "__init__.py" else module.rpartition(".")[0]
    imported: set[str] = set()

    def add(name: str) -> None:
        if name in modules and name != module:
            imported.add(name)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                relative_name = "." * node.level + (node.module or "")
                try:
                    base = importlib.util.resolve_name(relative_name, package)
                except (ImportError, ValueError):
                    continue
            else:
                base = node.module or ""
            add(base)
            # ``from package import child`` imports the child module when it
            # exists; otherwise the name is usually an attribute/class.
            for alias in node.names:
                if alias.name != "*":
                    add(f"{base}.{alias.name}")
        elif isinstance(node, ast.Call) and node.args:
            function = node.func
            is_import_module = (
                isinstance(function, ast.Attribute)
                and function.attr == "import_module"
                and isinstance(function.value, ast.Name)
                and function.value.id == "importlib"
            )
            is_dunder_import = isinstance(function, ast.Name) and function.id == "__import__"
            first_argument = node.args[0]
            if (is_import_module or is_dunder_import) and isinstance(first_argument, ast.Constant):
                value = first_argument.value
                if not isinstance(value, str):
                    continue
                if is_import_module and value.startswith("."):
                    try:
                        value = importlib.util.resolve_name(value, package)
                    except (ImportError, ValueError):
                        continue
                add(value)
    return imported


def find_unreferenced_modules(package_root: Path) -> tuple[str, ...]:
    """Return runtime modules with no inbound application import edge."""
    modules = _module_names(package_root)
    known_modules = set(modules)
    imported_by: dict[str, set[str]] = defaultdict(set)
    parse_errors: list[str] = []

    for module, path in modules.items():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError) as error:
            parse_errors.append(f"{path}: {error}")
            continue
        for target in _resolve_imports(module, path, tree, known_modules):
            imported_by[target].add(module)

    if parse_errors:
        raise ValueError("could not parse application modules:\n" + "\n".join(parse_errors))

    return tuple(
        sorted(
            module
            for module, path in modules.items()
            if path.name != "__init__.py" and module not in _ENTRYPOINTS and not imported_by[module]
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--package-root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "src" / PACKAGE_NAME,
        help="package source directory (default: src/echo_personal_tool)",
    )
    args = parser.parse_args(argv)

    unreferenced = find_unreferenced_modules(args.package_root)
    if unreferenced:
        print("Unreferenced application modules:", file=sys.stderr)
        for module in unreferenced:
            print(f"  {module}", file=sys.stderr)
        print("Delete, connect, or document an explicit non-runtime entry point.", file=sys.stderr)
        return 1

    print("No unreferenced runtime modules found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
