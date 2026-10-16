#!/usr/bin/env python3
"""Ratchet for raw colour literals in the presentation layer (UI-0, PR-1).

The redesign moves the colours of the interface into semantic design tokens
(``src/echo_personal_tool/presentation/theme/``). Raw hex literals are allowed
in the palette module only; everywhere else they are a step backwards.

This script counts the literals that are left outside the palette and compares
the number with the baseline in ``scripts/ui_colors_baseline.json``:

* the number grew  → the build fails (a new literal was added),
* the number fell   → the baseline can be lowered (``--update``),
* the number is the same → nothing to do.

The baseline is a ratchet, not a quota: it may only be lowered automatically.
Raising it needs ``--allow-growth`` and a good reason in the pull request.

Usage:
    python scripts/check_ui_colors.py            # the CI gate
    python scripts/check_ui_colors.py --list     # per-file counts
    python scripts/check_ui_colors.py --update   # lower the baseline
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src" / "echo_personal_tool"

#: The scanned areas — everything that paints the interface.
SCAN_ROOTS: tuple[str, ...] = ("presentation", "ui", "constructor")

#: Files that may hold raw hex literals: the palette module owns the colours.
WHITELIST: tuple[str, ...] = ("presentation/theme/palettes.py",)

#: Default baseline file.
DEFAULT_BASELINE = REPO_ROOT / "scripts" / "ui_colors_baseline.json"

#: A colour literal: #rgb, #rgba, #rrggbb or #rrggbbaa. The look-ahead keeps
#: identifiers such as "#added" (a QSS object name) out of the count.
HEX_RE = re.compile(
    r"#[0-9a-fA-F]{3,4}(?![0-9a-fA-F])"
    r"|#[0-9a-fA-F]{6}(?![0-9a-fA-F])"
    r"|#[0-9a-fA-F]{8}(?![0-9a-fA-F])"
)


def count_literals(text: str) -> int:
    """Count the hex colour literals of a text."""
    return len(HEX_RE.findall(text))


def scan(
    roots: tuple[str, ...] = SCAN_ROOTS,
    whitelist: tuple[str, ...] = WHITELIST,
    base: Path = SRC_ROOT,
) -> dict[str, int]:
    """Return the number of literals per file, relative to *base*.

    Files of the whitelist and files without literals are left out.
    """
    counts: dict[str, int] = {}
    for root in roots:
        directory = base / root
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.py")):
            relative = path.relative_to(base).as_posix()
            if relative in whitelist:
                continue
            count = count_literals(path.read_text(encoding="utf-8"))
            if count:
                counts[relative] = count
    return counts


def total_of(counts: dict[str, int]) -> int:
    """Return the total number of literals."""
    return sum(counts.values())


def load_baseline(path: Path) -> dict:
    """Read the baseline file (an empty baseline when the file is missing)."""
    if not path.exists():
        return {"version": 1, "total": 0, "files": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "total" not in data:
        raise ValueError(f"{path} is not a colour baseline file")
    return data


def build_baseline(counts: dict[str, int], *, roots: tuple[str, ...], whitelist: tuple[str, ...]) -> dict:
    """Build the baseline document of a scan."""
    return {
        "version": 1,
        "total": total_of(counts),
        "roots": list(roots),
        "whitelist": list(whitelist),
        "files": dict(sorted(counts.items())),
    }


def write_baseline(path: Path, baseline: dict) -> None:
    """Write the baseline file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(baseline, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def diff_against_baseline(counts: dict[str, int], baseline: dict) -> list[tuple[str, int, int]]:
    """Return the files that changed: (path, before, after)."""
    before: dict[str, int] = dict(baseline.get("files", {}))
    changed: list[tuple[str, int, int]] = []
    for path in sorted(set(before) | set(counts)):
        old = int(before.get(path, 0))
        new = int(counts.get(path, 0))
        if old != new:
            changed.append((path, old, new))
    return changed


def main(argv: list[str] | None = None) -> int:
    """Run the ratchet. Returns the process exit code."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE, help="baseline file")
    parser.add_argument("--update", action="store_true", help="write the current state into the baseline")
    parser.add_argument(
        "--allow-growth",
        action="store_true",
        help="allow the baseline to grow (a new literal area needs a reason)",
    )
    parser.add_argument("--list", action="store_true", help="print the count of every file")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    args = parser.parse_args(argv)

    counts = scan()
    total = total_of(counts)
    try:
        baseline = load_baseline(args.baseline)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: cannot read the baseline {args.baseline}: {exc}", file=sys.stderr)
        return 2
    baseline_total = int(baseline.get("total", 0))

    if args.json:
        print(
            json.dumps(
                {
                    "total": total,
                    "baseline": baseline_total,
                    "files": counts,
                    "grew": total > baseline_total,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0 if total <= baseline_total else 1
    if args.list:
        for path, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
            print(f"{count:5d}  {path}")
        print(f"{total:5d}  total")

    if args.update:
        if total > baseline_total and not args.allow_growth and args.baseline.exists():
            print(
                f"error: the colour ratchet grew from {baseline_total} to {total} — "
                "move the colour into a design token instead",
                file=sys.stderr,
            )
            return 1
        write_baseline(args.baseline, build_baseline(counts, roots=SCAN_ROOTS, whitelist=WHITELIST))
        print(f"baseline written: {args.baseline} ({total} literals)")
        return 0

    if total > baseline_total:
        print(
            f"error: the colour ratchet grew from {baseline_total} to {total} literals (+{total - baseline_total})",
            file=sys.stderr,
        )
        for path, old, new in diff_against_baseline(counts, baseline):
            if old != new:
                print(f"  {path}: {old} -> {new}", file=sys.stderr)
        print(
            "raw colours belong to the design tokens "
            "(src/echo_personal_tool/presentation/theme/palettes.py); "
            "use a token instead of a literal",
            file=sys.stderr,
        )
        return 1

    if total < baseline_total:
        print(f"note: the colour ratchet fell from {baseline_total} to {total} — run with --update")
        return 0

    print(f"colour ratchet: {total} literals (baseline {baseline_total})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
