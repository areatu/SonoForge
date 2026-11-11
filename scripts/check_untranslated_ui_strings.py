#!/usr/bin/env python3
"""Static AST gate for untranslated user-facing UI strings (#484).

Scans ``src/echo_personal_tool`` (stdlib only, runs in the CI ``lint`` job) for:
1. User-facing string literals containing alphabetic characters passed directly
   (or via f-string / concatenation / ternary) to Qt UI constructors and setters
   (``setText``, ``QLabel``, ``addRow``, ``setWindowTitle``, ``setPlaceholderText``,
   ``QPushButton``, ``QCheckBox``, ``QGroupBox``, ``addTab``) without calling
   ``tr()`` / ``tr_plural()`` / ``tr_for_language()`` (or reviewed local aliases).
2. Inline ``get_language() == "ru"`` / ``_language() == "ru"`` ternary branches
   inside UI display calls instead of dictionary keys.

Reviewed allowlist: product name, technical/clinical units and standard view/phase
codes, HTML markup wrappers, and example URLs/paths/AE-titles/DICOM tags in
``setPlaceholderText``.
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = REPO_ROOT / "src" / "echo_personal_tool"

#: Call name -> index of the user-facing caption/placeholder positional argument.
UI_CALL_TARGETS: dict[str, int] = {
    "setText": 0,
    "QLabel": 0,
    "addRow": 0,
    "setWindowTitle": 0,
    "setPlaceholderText": 0,
    "QPushButton": 0,
    "QCheckBox": 0,
    "QGroupBox": 0,
    "addTab": 1,
}

#: Translation/shortcut helpers whose presence marks a localized expression.
TRANSLATION_CALLS: frozenset[str] = frozenset(
    {
        "tr",
        "tr_plural",
        "tr_for_language",
        "_tr",
        "_t",
        "_translate",
        "translate",
        "shortcut_label",
    }
)

#: Exact literals permitted without ``tr()``: brand name, SI/technical units,
#: universal clinical/echo view codes, and technical placeholder examples.
ALLOWLIST_EXACT: frozenset[str] = frozenset(
    {
        # Product / brand
        "SonoForge",
        "SonoForge ",
        # Technical & physical units / coordinate prefixes
        " ms",
        " fps",
        " bpm",
        " mm",
        " cm",
        " kg",
        " m²",
        " MHz",
        " px",
        " px²",
        " fr",
        "X[",
        "] Y[",
        "RefY0: ",
        # Standard international echo/STE codes & loop markers
        "HR: --",
        "HR: ",
        "HR ",
        "GLS ",
        "ED ",
        " / ES ",
        " / AVC ",
        " · ES ",
        "A",
        "B",
        "A4C",
        "A2C",
        # Reviewed technical examples in setPlaceholderText (URLs, paths, AE titles, tags)
        "http://192.168.1.111:8042/dicom-web",
        "Authorization: Basic cGFjczpwYcIBTU2NBRERS\nX-Custom-Header: value",
        "/path/to/ca.pem",
        "/path/to/client.pem",
        "/path/to/client.key",
        "ECHO2026",
        "ORTHANC",
        "SonoForge-gold",
        "SonoForge-references",
        "PatientName,StudyDate,HeartRate",
    }
)

_HTML_FRAGMENT_RE = re.compile(r"</?[a-zA-Z][^>]*>|<[a-zA-Z][^>]*$|px;'>|px;\">")


@dataclass(frozen=True)
class Violation:
    file: str
    line: int
    call: str
    literal: str


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _contains_translation_call(node: ast.AST) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and _call_name(sub) in TRANSLATION_CALLS:
            return True
    return False


def _extract_display_literals(node: ast.AST) -> list[str]:
    """Return string constants that directly form the displayed UI text."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.JoinedStr):
        return [part.value for part in node.values if isinstance(part, ast.Constant) and isinstance(part.value, str)]
    if isinstance(node, ast.IfExp):
        return _extract_display_literals(node.body) + _extract_display_literals(node.orelse)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _extract_display_literals(node.left) + _extract_display_literals(node.right)
    return []


def is_allowed_literal(literal: str) -> bool:
    """True when ``literal`` has no letters or is in the reviewed technical allowlist."""
    if not any(ch.isalpha() for ch in literal):
        return True
    if literal in ALLOWLIST_EXACT:
        return True
    stripped = _HTML_FRAGMENT_RE.sub("", literal)
    return not any(ch.isalpha() for ch in stripped)


def scan_source(source: str, rel_path: str = "<memory>") -> list[Violation]:
    """Inspect one Python module's source and return any untranslated UI string violations."""
    tree = ast.parse(source, filename=rel_path)
    violations: list[Violation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        cname = _call_name(node)
        if cname not in UI_CALL_TARGETS:
            continue
        arg_index = UI_CALL_TARGETS[cname]
        if len(node.args) <= arg_index:
            continue
        arg = node.args[arg_index]
        if _contains_translation_call(arg):
            continue
        for lit in _extract_display_literals(arg):
            if not is_allowed_literal(lit):
                violations.append(Violation(file=rel_path, line=node.lineno, call=cname, literal=lit))
    return sorted(violations, key=lambda item: (item.file, item.line, item.call, item.literal))


def scan_tree(root: Path = DEFAULT_SOURCE) -> list[Violation]:
    """Scan all Python files under ``root``."""
    found: list[Violation] = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        found.extend(scan_source(path.read_text(encoding="utf-8"), rel))
    return found


def _write_github_summary(violations: list[Violation]) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    lines = [
        "### UI i18n literal gate (`scripts/check_untranslated_ui_strings.py`)",
        "",
        f"- Untranslated UI literals outside allowlist: **{len(violations)}** (ceiling **0**)",
    ]
    if violations:
        lines.append("")
        for item in violations[:30]:
            lines.append(f"- `{item.file}:{item.line}` `{item.call}`: `{item.literal!r}`")
    lines.append("")
    with open(summary_path, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_SOURCE, help="Source tree root to scan.")
    parser.add_argument("--github-summary", action="store_true", help="Append markdown summary to GITHUB_STEP_SUMMARY.")
    args = parser.parse_args(argv)

    violations = scan_tree(args.root)
    if args.github_summary:
        _write_github_summary(violations)

    if violations:
        sys.stderr.write(
            f"untranslated-ui-strings gate failed: {len(violations)} user-facing literal(s) bypass tr():\n"
        )
        for item in violations:
            sys.stderr.write(f"  - {item.file}:{item.line} [{item.call}] {item.literal!r}\n")
        return 1

    sys.stdout.write("untranslated-ui-strings gate passed: 0 user-facing literals bypass tr() outside allowlist\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
