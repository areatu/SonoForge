#!/usr/bin/env python3
"""WCAG 2.1 contrast check of design-token pairs (UI-0, spec 2026-10-16 §5.3).

For every theme in ``presentation/theme_tokens.py`` the script evaluates the
pairs of :data:`CONTRAST_REQUIREMENTS` (primary/secondary/hint text on the
surfaces, accent text, text on the accent fill).

* Themes in :data:`ENFORCED_CONTRAST_THEMES` fail CI on any miss (from UI-0
  PR-2: the new "Graphite" theme).
* The historical themes (navy, light, VS Code) are reported only — their
  colours are user-facing today and are not changed by UI-0.

Usage::

    python scripts/check_theme_contrast.py           # report + gate
    python scripts/check_theme_contrast.py --quiet   # only failures / summary

Standard library only: the token module is loaded by path, without importing
the application package (no Qt needed).
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
TOKENS_PATH = ROOT / "src" / "echo_personal_tool" / "presentation" / "theme_tokens.py"


def load_tokens_module(path: Path = TOKENS_PATH) -> ModuleType:
    spec = importlib.util.spec_from_file_location("_sonoforge_theme_tokens", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--quiet", action="store_true", help="print failures and the summary only")
    args = parser.parse_args(argv)

    tt = load_tokens_module()
    problems = tt.validate_tokens()
    if problems:
        print("::error title=Design tokens::inconsistent token tables")
        for line in problems:
            print(f"  {line}")
        return 1

    gate_failed = False
    for theme in tt.THEME_TOKENS:
        enforced = theme in tt.ENFORCED_CONTRAST_THEMES
        values = tt.tokens_for(theme)
        failures = tt.contrast_failures(theme)
        label = "gate" if enforced else "report"
        if not args.quiet:
            print(f"── {theme} ({label})")
            for foreground, backgrounds, required in tt.CONTRAST_REQUIREMENTS:
                for background in backgrounds:
                    ratio = tt.contrast_ratio(values[foreground], values[background])
                    mark = "ok " if ratio + 1e-9 >= required else "LOW"
                    print(f"   {mark} {foreground:12s} on {background:10s} {ratio:5.2f}:1 (≥ {required:g})")
        if failures:
            if enforced:
                gate_failed = True
                print(f"::error title=Contrast ({theme})::{len(failures)} token pair(s) below the WCAG threshold")
            else:
                print(f"{theme}: {len(failures)} pair(s) below the threshold (reported, not enforced)")
    if gate_failed:
        return 1
    print(
        "Contrast: enforced themes OK"
        if tt.ENFORCED_CONTRAST_THEMES
        else "Contrast: report only (no enforced themes yet)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
