#!/usr/bin/env python3
"""Ratchet how deep the viewer tests reach into private state (issue #327).

``ViewerWidget`` is a 9 000-line class with 236 private attributes, and its
tests read and write them directly: ``w._contour_stage``, ``w._current_frame``,
``w._apply_caliper_node_drag(...)``. Such a test pins *how* the widget works,
not what it promises, so every attempt to split the widget (#305, #307) breaks
hundreds of tests that say nothing about behaviour. The goal of the issue is
zero references; this script makes the way there one-directional:

* **the count only goes down** — references to private names of *other*
  objects in the files of the scope (``tests/unit/test_*viewer*.py`` by
  default) are summed and compared with ``scripts/test_private_access_baseline.json``.
  Growth fails the check;
* **progress is recorded** — a lower count than the baseline fails too, until
  ``--fix`` lowers it, so an improvement cannot be silently spent again later;
* **a split does not hide anything** — the limit is the *total* over the scope,
  so moving tests between viewer files changes nothing, and per-file numbers
  are only there to show where the references live.

What counts as a reference: ``obj._name`` where ``obj`` is not ``self``/``cls``
(dunder names and a bare ``_`` do not count), and the string forms that do the
same thing — ``getattr``/``setattr``/``hasattr``/``delattr(obj, "_name")``,
``monkeypatch.setattr(obj, "_name", ...)`` and ``patch.object(obj, "_name")``.
Importing a private *module-level* helper is not counted.

**Groups (issue #474, #536)** extend the ratchet beyond the main scope.
``MainWindow`` and ``AppController`` cannot be decomposed (#478, #480) while
~2 000 test lines read ``window._…`` and ``controller._…``. The viewer tests
themselves are mostly outside ``test_*viewer*.py`` (contour, caliper and zoom
files), and the Orthanc dialog has its own batch state, so groups select those
files by the class they build and count the receivers they use. A group names

* ``scope`` — the candidate files (globs, like the main scope);
* ``uses`` — a file belongs to the group only if it mentions one of these
  names (an import, a fixture parameter, any identifier): ``MainWindow`` /
  ``make_main_window`` select the tests that build the real window, not the
  ones with a ``FakeWindow``;
* ``receivers`` — only references whose attribute chain starts at one of
  these names count, so ``window._viewer._frame`` counts twice and
  ``dialog._x`` in the same file does not.

Each group has its own ``total`` and ``files`` with the same rules as the
main scope: growth fails, a lower count must be recorded with ``--fix``.

Run ``python scripts/check_test_private_access.py --fix`` after replacing
private access with a public API; ``--list`` shows where the references are
and which names are used most. ``--fix`` creates the baseline when it is
missing and otherwise only lowers it. Standard library only.

Exit codes: 0 — within the baseline, 1 — violations, 2 — usage/parse/baseline
errors.
"""

from __future__ import annotations

import argparse
import ast
import collections
import json
import os
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = REPO_ROOT / "scripts" / "test_private_access_baseline.json"
DEFAULT_SCOPE = ("tests/unit/test_*viewer*.py",)

BASELINE_VERSION = 1
BASELINE_COMMENT = (
    "Ratchet for issue #327 (python scripts/check_test_private_access.py). 'total' is the number of references to "
    "private names of other objects in the files matching 'scope'; it only goes down - run --fix after replacing "
    "private access with a public API. 'files' shows where the references live (informational). Every entry in "
    "'groups' applies the same rules to the tests that build one large class."
)

#: Builtins that read or write an attribute by its name.
ATTRIBUTE_BUILTINS = frozenset({"getattr", "setattr", "hasattr", "delattr"})
#: ``<owner>.<method>(obj, "name", ...)`` forms that patch an attribute by its name.
PATCH_CALLS = {
    "monkeypatch": frozenset({"setattr", "delattr"}),
    "patch": frozenset({"object"}),
    "mock": frozenset({"object"}),
}


#: Groups written when ``--fix`` creates a baseline from scratch (issue #474, #536).
DEFAULT_GROUPS: tuple[dict[str, object], ...] = (
    {
        "name": "MainWindow",
        "scope": ["tests/unit/test_*.py"],
        "uses": ["MainWindow", "make_main_window"],
        "receivers": ["window", "main_window", "mw", "win", "MainWindow"],
    },
    {
        "name": "AppController",
        "scope": ["tests/unit/test_*.py"],
        "uses": ["AppController", "make_main_window"],
        "receivers": ["controller", "ctrl", "app_controller", "AppController"],
    },
    {
        "name": "ViewerWidget",
        "scope": ["tests/unit/test_*.py"],
        "uses": ["ViewerWidget", "make_viewer", "viewer", "viewer_widget"],
        "receivers": ["ViewerWidget", "viewer", "viewer_widget", "w", "widget"],
    },
    {
        "name": "OrthancStudyDialog",
        "scope": ["tests/unit/test_*.py"],
        "uses": ["OrthancStudyDialog"],
        "receivers": ["OrthancStudyDialog", "dialog", "d"],
    },
)


@dataclass(frozen=True)
class Group:
    name: str
    scope: tuple[str, ...]
    uses: frozenset[str]
    receivers: frozenset[str]
    total: int = 0
    files: dict[str, int] = field(default_factory=dict)

    def definition(self) -> dict[str, object]:
        return {
            "name": self.name,
            "scope": list(self.scope),
            "uses": sorted(self.uses),
            "receivers": sorted(self.receivers),
        }


@dataclass(frozen=True)
class Baseline:
    scope: tuple[str, ...]
    total: int
    files: dict[str, int]
    groups: tuple[Group, ...] = ()


def is_private_name(name: str) -> bool:
    """``_x`` and ``_x_y`` are private; ``__x__`` and a bare ``_`` are not."""
    if name == "_" or not name.startswith("_"):
        return False
    return not (name.startswith("__") and name.endswith("__"))


def _is_own(expr: ast.expr) -> bool:
    """``self`` / ``cls`` — a test touching its own helpers is not reaching into the widget."""
    return isinstance(expr, ast.Name) and expr.id in {"self", "cls"}


def _patched_name(call: ast.Call) -> str | None:
    """The attribute name given as a string literal to ``getattr``-like calls, if this is one."""
    if len(call.args) < 2:
        return None
    func = call.func
    if isinstance(func, ast.Name):
        matches = func.id in ATTRIBUTE_BUILTINS
    elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        matches = func.attr in PATCH_CALLS.get(func.value.id, frozenset())
    else:
        matches = False
    target, name = call.args[0], call.args[1]
    if not matches or _is_own(target):
        return None
    if isinstance(name, ast.Constant) and isinstance(name.value, str):
        return name.value
    return None


def _chain_root(expr: ast.expr) -> str | None:
    """``window`` for ``window._viewer._frame`` / ``window.panel()._x``; ``None`` for anything else."""
    while True:
        if isinstance(expr, ast.Name):
            return expr.id
        if isinstance(expr, (ast.Attribute, ast.Subscript)):
            expr = expr.value
        elif isinstance(expr, ast.Call):
            expr = expr.func
        else:
            return None


def iter_rooted_references(tree: ast.AST) -> Iterator[tuple[int, str, str | None]]:
    """Yield ``(line, private name, root of the receiver)`` for every reference that counts."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and is_private_name(node.attr) and not _is_own(node.value):
            yield node.lineno, node.attr, _chain_root(node.value)
        elif isinstance(node, ast.Call):
            name = _patched_name(node)
            if name is not None and is_private_name(name):
                yield node.lineno, name, _chain_root(node.args[0])


def iter_private_references(tree: ast.AST) -> Iterator[tuple[int, str]]:
    """Yield ``(line, private name)`` for every reference that counts."""
    for line, name, _root in iter_rooted_references(tree):
        yield line, name


def mentioned_names(tree: ast.AST) -> set[str]:
    """Identifiers a module mentions: names, imported names (and aliases) and parameters."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add(alias.name.rsplit(".", 1)[-1])
                if alias.asname:
                    names.add(alias.asname)
    return names


def scan_group(root: Path, group: Group) -> tuple[dict[str, int], list[str]]:
    """Per file of the group: references through the group's receivers. Also unparsable files."""
    counts: dict[str, int] = {}
    errors: list[str] = []
    for path in scope_files(root, group.scope):
        relative = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError, OSError) as exc:
            errors.append(f"{relative}: cannot parse ({exc})")
            continue
        if not mentioned_names(tree) & group.uses:
            continue
        count = sum(1 for _line, _name, owner in iter_rooted_references(tree) if owner in group.receivers)
        if count:
            counts[relative] = count
    return dict(sorted(counts.items())), errors


def scope_files(root: Path, scope: tuple[str, ...]) -> list[Path]:
    found = {path for pattern in scope for path in root.glob(pattern) if "__pycache__" not in path.parts}
    return sorted(found)


def scan(root: Path, scope: tuple[str, ...]) -> tuple[dict[str, collections.Counter[str]], list[str]]:
    """Per file: how often each private name is referenced. Also the files that cannot be parsed."""
    found: dict[str, collections.Counter[str]] = {}
    errors: list[str] = []
    for path in scope_files(root, scope):
        relative = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError, OSError) as exc:
            errors.append(f"{relative}: cannot parse ({exc})")
            continue
        names = collections.Counter(name for _line, name in iter_private_references(tree))
        if names:
            found[relative] = names
    return found, errors


def file_counts(found: dict[str, collections.Counter[str]]) -> dict[str, int]:
    return {path: sum(names.values()) for path, names in sorted(found.items())}


# ── baseline ────────────────────────────────────────────────────────────────


def load_baseline(path: Path) -> Baseline:
    """Read and validate the baseline; raises ``OSError``/``ValueError``/``KeyError``."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != BASELINE_VERSION:
        raise ValueError(f"unsupported baseline version in {path}: {data.get('version')!r}")
    scope = data["scope"]
    files = data["files"]
    if not (isinstance(scope, list) and scope and all(isinstance(pattern, str) for pattern in scope)):
        raise ValueError("'scope' must be a non-empty list of glob patterns")
    if not (
        isinstance(files, dict)
        and all(isinstance(name, str) and isinstance(count, int) for name, count in files.items())
    ):
        raise ValueError("'files' must map file names to counts")
    total = data["total"]
    if not isinstance(total, int) or total < 0:
        raise ValueError("'total' must be a non-negative integer")
    return Baseline(scope=tuple(scope), total=total, files=dict(files), groups=_load_groups(data.get("groups", [])))


def _string_list(value: object, what: str) -> tuple[str, ...]:
    if not (isinstance(value, list) and value and all(isinstance(item, str) and item for item in value)):
        raise ValueError(f"{what} must be a non-empty list of strings")
    return tuple(value)


def _load_groups(raw: object) -> tuple[Group, ...]:
    if not isinstance(raw, list):
        raise ValueError("'groups' must be a list")
    groups: list[Group] = []
    for entry in raw:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str) or not entry["name"]:
            raise ValueError("every group needs a 'name'")
        name = entry["name"]
        files = entry.get("files", {})
        total = entry.get("total", 0)
        if not (
            isinstance(files, dict)
            and all(isinstance(path, str) and isinstance(count, int) and count >= 0 for path, count in files.items())
        ):
            raise ValueError(f"group {name!r}: 'files' must map file names to counts")
        if not isinstance(total, int) or isinstance(total, bool) or total < 0:
            raise ValueError(f"group {name!r}: 'total' must be a non-negative integer")
        groups.append(
            Group(
                name=name,
                scope=_string_list(entry.get("scope"), f"group {name!r}: 'scope'"),
                uses=frozenset(_string_list(entry.get("uses"), f"group {name!r}: 'uses'")),
                receivers=frozenset(_string_list(entry.get("receivers"), f"group {name!r}: 'receivers'")),
                total=total,
                files=dict(files),
            )
        )
    if len({group.name for group in groups}) != len(groups):
        raise ValueError("group names must be unique")
    return tuple(groups)


def default_groups() -> tuple[Group, ...]:
    return _load_groups([dict(group) for group in DEFAULT_GROUPS])


def write_baseline(
    path: Path,
    scope: tuple[str, ...],
    counts: dict[str, int],
    groups: tuple[tuple[Group, dict[str, int]], ...] = (),
) -> None:
    payload: dict[str, object] = {
        "version": BASELINE_VERSION,
        "comment": BASELINE_COMMENT,
        "scope": list(scope),
        "total": sum(counts.values()),
        "files": dict(sorted(counts.items())),
    }
    if groups:
        payload["groups"] = [
            {**group.definition(), "total": sum(found.values()), "files": dict(sorted(found.items()))}
            for group, found in groups
        ]
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def find_violations(counts: dict[str, int], baseline: Baseline) -> tuple[str, ...]:
    """Growth, or a baseline that no longer matches an improvement."""
    total = sum(counts.values())
    violations: list[str] = []
    if total > baseline.total:
        violations.append(
            f"viewer tests reference private names of other objects {total} times, the baseline allows "
            f"{baseline.total} (+{total - baseline.total}) — use the public API, or add one to the widget"
        )
        for path, count in sorted(counts.items()):
            allowed = baseline.files.get(path, 0)
            if count > allowed:
                violations.append(f"{path}: {count} references, baseline {allowed} (+{count - allowed})")
    elif total < baseline.total:
        violations.append(
            f"viewer tests reference private names {total} times but the baseline still allows {baseline.total}: "
            "run `python scripts/check_test_private_access.py --fix` to keep the improvement"
        )
    return tuple(violations)


def find_group_violations(group: Group, counts: dict[str, int]) -> tuple[str, ...]:
    """The same rules for one group: growth fails, an improvement must be recorded."""
    total = sum(counts.values())
    violations: list[str] = []
    if total > group.total:
        violations.append(
            f"tests reach into private state of {group.name} {total} times, the baseline allows {group.total} "
            f"(+{total - group.total}) — use the public API, or add one to {group.name}"
        )
        for path, count in sorted(counts.items()):
            allowed = group.files.get(path, 0)
            if count > allowed:
                violations.append(f"{path}: {count} {group.name} references, baseline {allowed} (+{count - allowed})")
    elif total < group.total:
        violations.append(
            f"tests reach into private state of {group.name} {total} times but the baseline still allows "
            f"{group.total}: run `python scripts/check_test_private_access.py --fix` to keep the improvement"
        )
    return tuple(violations)


def fix_baseline(
    path: Path,
    scope: tuple[str, ...],
    counts: dict[str, int],
    groups: tuple[tuple[Group, dict[str, int]], ...] = (),
) -> int:
    """Lower the baseline after a cleanup; create it when missing; never let it grow."""
    created = not path.exists()
    try:
        previous = None if created else load_baseline(path)
    except (OSError, ValueError, KeyError) as exc:
        sys.stderr.write(f"error: cannot read {path}: {exc}\n")
        return 2
    total = sum(counts.values())
    if previous is not None and total > previous.total:
        sys.stderr.write(
            f"refusing to raise the bar — {total} references against a baseline of {previous.total}; "
            "--fix only lowers it\n"
        )
        return 1
    if previous is not None:
        for group, found in groups:
            if sum(found.values()) > group.total:
                sys.stderr.write(
                    f"refusing to raise the bar for {group.name} — {sum(found.values())} references against a "
                    f"baseline of {group.total}; --fix only lowers it\n"
                )
                return 1
    write_baseline(path, scope, counts, groups)
    verb = "created" if created else "refreshed"
    was = "" if previous is None else f" (was {previous.total})"
    sys.stdout.write(f"private-access baseline {verb}: {total} references in {len(counts)} files{was}\n")
    return 0


# ── report ──────────────────────────────────────────────────────────────────


def render_line(counts: dict[str, int], baseline: Baseline | None) -> str:
    allowed = "" if baseline is None else f" (baseline {baseline.total})"
    return f"{sum(counts.values())} references to private names in {len(counts)} viewer test files{allowed}"


def render_markdown(
    counts: dict[str, int],
    baseline: Baseline,
    violations: tuple[str, ...],
    group_counts: tuple[tuple[Group, dict[str, int]], ...] = (),
) -> str:
    """The table shown on the workflow run page (``$GITHUB_STEP_SUMMARY``)."""
    total = sum(counts.values())
    delta = "0" if total == baseline.total else f"{total - baseline.total:+d}"
    lines = [
        "### Private access in viewer tests (#327)",
        "",
        "| Metric | Now | Baseline | Δ |",
        "|---|---:|---:|---:|",
        f"| **References to private names** (gated: may only go down) | {total} | {baseline.total} | {delta} |",
        f"| Files with references | {len(counts)} | {len(baseline.files)} | {len(counts) - len(baseline.files):+d} |",
    ]
    for path, count in sorted(counts.items(), key=lambda item: -item[1])[:5]:
        lines.append(
            f"| `{path}` | {count} | {baseline.files.get(path, 0)} | {count - baseline.files.get(path, 0):+d} |"
        )
    for group, found in group_counts:
        now = sum(found.values())
        delta = "0" if now == group.total else f"{now - group.total:+d}"
        lines.append(
            f"| **{group.name}** (group, #474; {len(found)} files; may only go down) | {now} | {group.total} | {delta} |"
        )
    if violations:
        lines += ["", "**Violations**", ""]
        lines += [f"- {violation}" for violation in violations]
    return "\n".join(lines) + "\n"


def _emit_github_summary(markdown: str) -> None:
    """Append to ``$GITHUB_STEP_SUMMARY`` in CI, print locally."""
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(markdown)
    else:
        sys.stdout.write(markdown)


def render_listing(found: dict[str, collections.Counter[str]], limit: int = 25) -> str:
    """Where the references are and which private names are used most."""
    counts = file_counts(found)
    lines = [f"{sum(counts.values())} references in {len(counts)} files", ""]
    lines += [f"{count:5d}  {path}" for path, count in sorted(counts.items(), key=lambda item: -item[1])]
    names: collections.Counter[str] = collections.Counter()
    for per_file in found.values():
        names.update(per_file)
    lines += ["", f"{len(names)} distinct private names; the most used:"]
    lines += [f"{count:5d}  {name}" for name, count in names.most_common(limit)]
    return "\n".join(lines) + "\n"


# ── command line ────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ratchet private access in the viewer tests (issue #327).")
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="repository root the scope globs are relative to")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE, help="baseline JSON file")
    parser.add_argument(
        "--fix", action="store_true", help="lower the baseline after a cleanup (creates it when missing)"
    )
    parser.add_argument("--list", action="store_true", help="show where the references are and the most used names")
    parser.add_argument(
        "--github-summary", action="store_true", help="append the metrics table to $GITHUB_STEP_SUMMARY"
    )
    args = parser.parse_args(argv)

    root = args.root.resolve()
    baseline: Baseline | None = None
    if args.baseline.exists():
        try:
            baseline = load_baseline(args.baseline)
        except (OSError, ValueError, KeyError) as exc:
            sys.stderr.write(f"error: cannot read {args.baseline}: {exc}\n")
            return 2
    scope = baseline.scope if baseline is not None else DEFAULT_SCOPE

    if not scope_files(root, scope):
        sys.stderr.write(f"error: no test files match {list(scope)} under {root} — wrong --root or scope?\n")
        return 2
    found, parse_errors = scan(root, scope)
    if parse_errors:
        sys.stderr.write(
            "error: cannot analyse the tests:\n" + "\n".join(f"  {error}" for error in parse_errors) + "\n"
        )
        return 2
    counts = file_counts(found)
    groups = baseline.groups if baseline is not None else default_groups()
    group_counts: list[tuple[Group, dict[str, int]]] = []
    for group in groups:
        group_found, group_errors = scan_group(root, group)
        if group_errors:
            sys.stderr.write(
                "error: cannot analyse the tests:\n" + "\n".join(f"  {error}" for error in group_errors) + "\n"
            )
            return 2
        group_counts.append((group, group_found))

    if args.list:
        sys.stdout.write(render_listing(found))
        for group, group_found in group_counts:
            sys.stdout.write(
                f"\n{group.name} (group): {sum(group_found.values())} references in {len(group_found)} files\n"
            )
            ranked = sorted(group_found.items(), key=lambda item: -item[1])
            sys.stdout.write("".join(f"{count:5d}  {path}\n" for path, count in ranked))
        return 0
    if args.fix:
        return fix_baseline(args.baseline, scope, counts, tuple(group_counts))
    if baseline is None:
        sys.stderr.write(
            f"error: {args.baseline} does not exist\ncreate it with `python scripts/check_test_private_access.py --fix`\n"
        )
        return 2

    violations = find_violations(counts, baseline)
    for group, group_found in group_counts:
        violations += find_group_violations(group, group_found)
    if args.github_summary:
        _emit_github_summary(render_markdown(counts, baseline, violations, tuple(group_counts)))
    if violations:
        sys.stderr.write(f"private-access ratchet failed ({len(violations)} problem(s)):\n")
        sys.stderr.write("\n".join(f"  {violation}" for violation in violations) + "\n")
        return 1
    groups_line = "".join(f"; {group.name}: {sum(found.values())}" for group, found in group_counts)
    sys.stdout.write(f"private-access ratchet passed: {render_line(counts, baseline)}{groups_line}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
