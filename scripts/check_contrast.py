#!/usr/bin/env python3
"""WCAG 2.1 contrast check for the design tokens (UI-0, PR-1).

The token system states a colour *role*; this script states how much contrast
the roles must have against each other (spec §5.2, G-4):

* the graphite theme is checked strictly — a failing pair fails the build,
* the former themes (navy, light, VS Code) are only reported: their colours
  were not agreed with anyone and must not change silently (``--strict``
  turns them into errors as well).

The script reads the palettes directly; it needs no Qt and no display.

Usage:
    python scripts/check_contrast.py
    python scripts/check_contrast.py --theme graphite
    python scripts/check_contrast.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from echo_personal_tool.presentation.theme.palettes import (  # noqa: E402
    PALETTES,
    THEME_GRAPHITE,
)

#: Text needs 4.5:1 (WCAG 2.1 AA), a non-text element 3:1 (1.4.11).
TEXT_MINIMUM = 4.5
UI_MINIMUM = 3.0

SURFACES = ("surface.0", "surface.1", "surface.2", "surface.3")


@dataclass(frozen=True)
class ContrastCheck:
    """One pair of tokens with the contrast it has to reach."""

    foreground: str
    background: str
    minimum: float

    @property
    def kind(self) -> str:
        return "text" if self.minimum >= TEXT_MINIMUM else "ui"


def _checks() -> tuple[ContrastCheck, ...]:
    """Build the list of checked token pairs."""
    checks: list[ContrastCheck] = []
    for text_token in ("text.1", "text.2", "text.3", "accent.text"):
        for surface in SURFACES:
            checks.append(ContrastCheck(text_token, surface, TEXT_MINIMUM))
    checks.append(ContrastCheck("accent.on", "accent", TEXT_MINIMUM))
    for surface in SURFACES:
        checks.append(ContrastCheck("accent", surface, UI_MINIMUM))
    checks.append(ContrastCheck("focus.ring", "surface.0", UI_MINIMUM))
    for state in ("state.ok", "state.warn", "state.err"):
        checks.append(ContrastCheck(state, "surface.1", TEXT_MINIMUM))
    checks.append(ContrastCheck("state.danger.text", "state.danger.bg", TEXT_MINIMUM))
    return tuple(checks)


CHECKS: tuple[ContrastCheck, ...] = _checks()


def relative_luminance(color: str) -> float:
    """Return the relative luminance of a hex colour (WCAG 2.1)."""
    value = color.lstrip("#")
    if len(value) == 3:
        value = "".join(char * 2 for char in value)
    if len(value) not in (6, 8):
        raise ValueError(f"not a hex colour: {color!r}")
    channels = [int(value[index : index + 2], 16) / 255 for index in (0, 2, 4)]
    linear = [channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(foreground: str, background: str) -> float:
    """Return the contrast ratio of two hex colours (1.0 … 21.0)."""
    first = relative_luminance(foreground)
    second = relative_luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def check_theme(theme_id: str) -> list[dict]:
    """Check one theme; returns one record per checked pair."""
    tokens = PALETTES[theme_id]
    records: list[dict] = []
    for check in CHECKS:
        foreground = tokens[check.foreground]
        background = tokens[check.background]
        ratio = contrast_ratio(foreground, background)
        records.append(
            {
                "theme": theme_id,
                "foreground": check.foreground,
                "background": check.background,
                "foreground_color": foreground,
                "background_color": background,
                "ratio": round(ratio, 2),
                "minimum": check.minimum,
                "kind": check.kind,
                "passed": ratio >= check.minimum,
            }
        )
    return records


def main(argv: list[str] | None = None) -> int:
    """Run the contrast check. Returns the process exit code."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--theme", action="append", default=None, help="check only this theme (repeatable)")
    parser.add_argument("--strict", action="store_true", help="fail on the former themes as well")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    args = parser.parse_args(argv)

    themes = tuple(args.theme) if args.theme else tuple(PALETTES)
    records: list[dict] = []
    for theme_id in themes:
        if theme_id not in PALETTES:
            print(f"error: unknown theme {theme_id!r}", file=sys.stderr)
            return 2
        records.extend(check_theme(theme_id))

    failures = [record for record in records if not record["passed"]]
    blocking = [record for record in failures if record["theme"] == THEME_GRAPHITE or args.strict]

    if args.json:
        print(json.dumps({"checks": records, "failures": len(failures)}, indent=2, ensure_ascii=False))
    else:
        for theme_id in themes:
            theme_records = [record for record in records if record["theme"] == theme_id]
            role = "blocking" if theme_id == THEME_GRAPHITE or args.strict else "report only"
            print(f"── {theme_id} ({role})")
            for record in theme_records:
                mark = "ok  " if record["passed"] else "FAIL"
                print(
                    f"  {mark} {record['foreground']:>18} on {record['background']:<18} "
                    f"{record['ratio']:>6.2f}:1 (min {record['minimum']})"
                )
        if failures:
            print(f"{len(failures)} pair(s) below the minimum, {len(blocking)} of them blocking")
        else:
            print("every checked pair reaches its minimum")

    if blocking:
        print(
            "error: the contrast of the graphite theme is below the WCAG 2.1 AA minimum",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
