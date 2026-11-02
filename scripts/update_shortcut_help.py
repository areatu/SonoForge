#!/usr/bin/env python3
"""Regenerate the marked shortcut sections in the localized user guides."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from echo_personal_tool.keyboard_shortcuts import replace_shortcut_help_section  # noqa: E402


def main() -> None:
    for language, suffix in (("ru", "RU"), ("en", "EN")):
        path = ROOT / "docs" / f"HELP_{suffix}.md"
        original = path.read_text(encoding="utf-8")
        updated = replace_shortcut_help_section(original, language, add_markers=True)
        if updated == original and "<!-- SHORTCUT_REGISTRY:START -->" not in original:
            raise SystemExit(f"Could not find shortcut section in {path}")
        path.write_text(updated, encoding="utf-8")


if __name__ == "__main__":
    main()
