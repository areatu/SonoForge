#!/usr/bin/env python3
"""Ratchet broad and silent ``except`` handlers in ``src`` per layer (issue #474).

A broad handler (``except Exception``, ``except BaseException``, a bare
``except:`` or a tuple that contains one of them) is sometimes the right
boundary — a worker thread must not die on a corrupt file. A *silent* broad
handler is never right in a medical viewer: its body only ``pass``-es,
``continue``-s or returns a constant, so a measurement can come out wrong and
nothing anywhere says why. Nobody held either number, so both grew quietly.

This script counts, per top-level package under ``src/echo_personal_tool``
(``domain``, ``application``, ``infrastructure``, ``presentation``, ``ui``,
``constructor``, …; top-level modules count as ``(root)``):

* ``broad`` — every broad handler;
* ``silent`` — the broad handlers whose body does nothing observable.

Both are ceilings in ``scripts/broad_except_baseline.json``: growth in any
layer fails, a layer that is not in the baseline starts at zero, and ``--fix``
lowers the ceilings after a cleanup (it never raises one). ``--list`` prints
every silent handler with its location — the worklist.

What makes a body silent: only ``pass``, ``continue``, ``break``, ``...``, a
docstring, or ``return`` of nothing, a constant or an empty literal (``[]``,
``{}``, ``()``). Logging, re-raising, assigning a fallback that is reported
elsewhere — anything else — is not silent. Standard library only.

Exit codes: 0 — within the baseline, 1 — violations, 2 — usage/parse/baseline
errors.
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
DEFAULT_BASELINE = REPO_ROOT / "scripts" / "broad_except_baseline.json"
BASELINE_VERSION = 1
BROAD_NAMES = frozenset({"Exception", "BaseException"})
ROOT_LAYER = "(root)"
BASELINE_COMMENT = (
    "Ratchet for issue #474 (python scripts/check_broad_excepts.py). Per layer: 'broad' counts except "
    "Exception/BaseException/bare except handlers, 'silent' the broad ones whose body only passes, continues "
    "or returns a constant. Both are ceilings; run --fix after a cleanup to lower them (it never raises one)."
)


@dataclass(frozen=True)
class Handler:
    path: str
    line: int
    silent: bool


def _is_broad_type(node: ast.expr | None) -> bool:
    if node is None:
        return True
    if isinstance(node, ast.Tuple):
        return any(_is_broad_type(element) for element in node.elts)
    if isinstance(node, ast.Name):
        return node.id in BROAD_NAMES
    if isinstance(node, ast.Attribute):
        return node.attr in BROAD_NAMES
    return False


def _is_silent_statement(statement: ast.stmt) -> bool:
    if isinstance(statement, (ast.Pass, ast.Continue, ast.Break)):
        return True
    if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant):
        return True  # ``...`` or a docstring-like string
    if isinstance(statement, ast.Return):
        value = statement.value
        if value is None or isinstance(value, ast.Constant):
            return True
        if isinstance(value, (ast.List, ast.Tuple, ast.Set)) and not value.elts:
            return True
        if isinstance(value, ast.Dict) and not value.keys:
            return True
    return False


def is_silent(handler: ast.ExceptHandler) -> bool:
    """The body does nothing anyone could observe."""
    return all(_is_silent_statement(statement) for statement in handler.body)


def iter_broad_handlers(tree: ast.AST, path: str) -> list[Handler]:
    return [
        Handler(path=path, line=node.lineno, silent=is_silent(node))
        for node in ast.walk(tree)
        if isinstance(node, ast.ExceptHandler) and _is_broad_type(node.type)
    ]


def layer_of(relative: str) -> str:
    parts = relative.split("/")
    return parts[0] if len(parts) > 1 else ROOT_LAYER


def scan(source_root: Path) -> list[Handler]:
    handlers: list[Handler] = []
    for path in sorted(source_root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        relative = path.relative_to(source_root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        handlers.extend(iter_broad_handlers(tree, relative))
    return handlers


def count_by_layer(handlers: list[Handler]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for handler in handlers:
        entry = counts.setdefault(layer_of(handler.path), {"broad": 0, "silent": 0})
        entry["broad"] += 1
        entry["silent"] += int(handler.silent)
    return dict(sorted(counts.items()))


# ── baseline ────────────────────────────────────────────────────────────────


def load_baseline(path: Path) -> dict[str, dict[str, int]]:
    """Read and validate the baseline; raises ``OSError``/``ValueError``/``KeyError``."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != BASELINE_VERSION:
        raise ValueError(f"unsupported baseline version in {path}: {data.get('version')!r}")
    layers = data["layers"]
    if not isinstance(layers, dict) or not all(
        isinstance(entry, dict)
        and set(entry) == {"broad", "silent"}
        and all(isinstance(value, int) and value >= 0 for value in entry.values())
        and entry["silent"] <= entry["broad"]
        for entry in layers.values()
    ):
        raise ValueError("'layers' must map layer names to {'broad': int, 'silent': int <= broad}")
    return {str(name): dict(entry) for name, entry in layers.items()}


def find_violations(current: dict[str, dict[str, int]], baseline: dict[str, dict[str, int]]) -> tuple[str, ...]:
    violations: list[str] = []
    for layer, counts in current.items():
        allowed = baseline.get(layer, {"broad": 0, "silent": 0})
        if counts["silent"] > allowed["silent"]:
            violations.append(
                f"{layer}: {counts['silent']} silent broad except handlers, the baseline allows "
                f"{allowed['silent']} (+{counts['silent'] - allowed['silent']}) — log the failure "
                "(log_boundary_failure outside domain) or catch the specific exception"
            )
        if counts["broad"] > allowed["broad"]:
            violations.append(
                f"{layer}: {counts['broad']} broad except handlers, the baseline allows "
                f"{allowed['broad']} (+{counts['broad'] - allowed['broad']}) — catch the exceptions the call "
                "can actually raise"
            )
    return tuple(violations)


def fixed_baseline(
    current: dict[str, dict[str, int]], previous: dict[str, dict[str, int]] | None
) -> dict[str, dict[str, int]]:
    """``current`` capped by ``previous`` — ``--fix`` never raises a ceiling."""
    if previous is None:
        return current
    return {
        layer: {metric: min(value, previous[layer][metric]) for metric, value in counts.items()}
        for layer, counts in current.items()
        if layer in previous
    }


def write_baseline(path: Path, layers: dict[str, dict[str, int]]) -> None:
    payload = {
        "version": BASELINE_VERSION,
        "comment": BASELINE_COMMENT,
        "total": {
            "broad": sum(entry["broad"] for entry in layers.values()),
            "silent": sum(entry["silent"] for entry in layers.values()),
        },
        "layers": dict(sorted(layers.items())),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def render_markdown(current: dict[str, dict[str, int]], baseline: dict[str, dict[str, int]]) -> str:
    lines = [
        "### Broad `except` handlers per layer (#474)",
        "",
        "| Layer | Broad | Baseline | Silent | Baseline |",
        "|---|---:|---:|---:|---:|",
    ]
    for layer in sorted(set(current) | set(baseline)):
        now = current.get(layer, {"broad": 0, "silent": 0})
        allowed = baseline.get(layer, {"broad": 0, "silent": 0})
        lines.append(f"| `{layer}` | {now['broad']} | {allowed['broad']} | {now['silent']} | {allowed['silent']} |")
    return "\n".join(lines) + "\n"


# ── command line ────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    import os

    parser = argparse.ArgumentParser(description="Ratchet broad and silent except handlers (issue #474).")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--fix", action="store_true", help="lower the ceilings after a cleanup (creates the file)")
    parser.add_argument("--list", action="store_true", help="print every silent broad handler")
    parser.add_argument("--github-summary", action="store_true", help="append a table to $GITHUB_STEP_SUMMARY")
    args = parser.parse_args(argv)

    try:
        handlers = scan(args.source)
    except (OSError, SyntaxError, UnicodeDecodeError) as exc:
        sys.stderr.write(f"broad-except ratchet: cannot analyse {args.source}: {exc}\n")
        return 2
    current = count_by_layer(handlers)

    if args.list:
        silent = [handler for handler in handlers if handler.silent]
        sys.stdout.write("".join(f"{handler.path}:{handler.line}\n" for handler in silent))
        sys.stdout.write(f"{len(silent)} silent of {len(handlers)} broad except handlers\n")
        return 0

    previous: dict[str, dict[str, int]] | None = None
    if args.baseline.exists():
        try:
            previous = load_baseline(args.baseline)
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            sys.stderr.write(f"broad-except ratchet: cannot read {args.baseline}: {exc}\n")
            return 2

    if args.fix:
        violations = find_violations(current, previous) if previous is not None else ()
        if violations:
            sys.stderr.write("broad-except ratchet: refusing to raise a ceiling — --fix only lowers it:\n")
            sys.stderr.write("".join(f"  - {violation}\n" for violation in violations))
            return 1
        write_baseline(args.baseline, fixed_baseline(current, previous))
        sys.stdout.write(f"broad-except baseline {'refreshed' if previous else 'created'}: {args.baseline}\n")
        return 0

    if previous is None:
        sys.stderr.write(
            f"broad-except ratchet: {args.baseline} does not exist — create it with "
            "`python scripts/check_broad_excepts.py --fix`\n"
        )
        return 2

    violations = find_violations(current, previous)
    if args.github_summary:
        markdown = render_markdown(current, previous)
        target = os.environ.get("GITHUB_STEP_SUMMARY")
        if target:
            with open(target, "a", encoding="utf-8") as handle:
                handle.write(markdown)
        else:
            sys.stdout.write(markdown)
    if violations:
        sys.stderr.write(f"broad-except ratchet failed ({len(violations)} problem(s)):\n")
        sys.stderr.write("".join(f"  - {violation}\n" for violation in violations))
        return 1
    broad = sum(entry["broad"] for entry in current.values())
    silent = sum(entry["silent"] for entry in current.values())
    sys.stdout.write(f"broad-except ratchet passed: {broad} broad handlers, {silent} of them silent, no layer grew\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
