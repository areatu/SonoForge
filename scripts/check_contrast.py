#!/usr/bin/env python3
"""WCAG 2.1 contrast check for the design tokens (UI-0, PR-1).

The token system states a colour *role*; the rules of
``src/echo_personal_tool/presentation/theme/contrast.py`` state how much
contrast the roles must have against each other (spec §5.2, G-4):

* the graphite theme is checked strictly — a failing pair fails the build,
* the former themes (navy, light, VS Code) are only reported: their colours
  were not agreed with anyone and must not change silently (``--strict``
  turns them into errors as well).

The script is the command line around those rules; the rules themselves live
in the token package, which imports no Qt and needs no display.

Usage:
    python scripts/check_contrast.py
    python scripts/check_contrast.py --theme graphite
    python scripts/check_contrast.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from echo_personal_tool.presentation.theme.contrast import (  # noqa: E402
    CHECKS,
    ENFORCED_CONTRAST_THEMES,
    TEXT_MINIMUM,
    UI_MINIMUM,
    check_theme,
    contrast_failures,
    contrast_ratio,
    hex_to_rgb,
    relative_luminance,
)
from echo_personal_tool.presentation.theme.palettes import (  # noqa: E402
    PALETTES,
    THEME_GRAPHITE,
)


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
