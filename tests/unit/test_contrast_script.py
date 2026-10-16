"""Unit tests for the contrast check (scripts/check_contrast.py, UI-0, PR-1).

The graphite theme is checked strictly (spec G-4); the former themes are
reported only — their colours were never agreed with anyone and must not
change silently.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_contrast  # noqa: E402

from echo_personal_tool.presentation.theme import palettes  # noqa: E402


class TestContrastMath:
    def test_black_on_white_is_the_maximum(self):
        assert check_contrast.contrast_ratio("#000000", "#ffffff") == 21.0

    def test_a_colour_on_itself_is_one(self):
        assert check_contrast.contrast_ratio("#102135", "#102135") == 1.0

    def test_the_ratio_is_symmetric(self):
        first = check_contrast.contrast_ratio("#e6e9ec", "#0b0d0f")
        second = check_contrast.contrast_ratio("#0b0d0f", "#e6e9ec")
        assert first == second

    def test_three_digit_colours_are_accepted(self):
        assert check_contrast.contrast_ratio("#fff", "#000") == 21.0

    def test_an_invalid_colour_is_rejected(self):
        try:
            check_contrast.relative_luminance("#12345")
        except ValueError:
            return
        raise AssertionError("a five-digit colour must be rejected")


class TestGraphiteTheme:
    def test_every_pair_reaches_its_minimum(self):
        records = check_contrast.check_theme(palettes.THEME_GRAPHITE)
        failures = [record for record in records if not record["passed"]]
        assert failures == [], failures

    def test_the_text_tokens_reach_the_wcag_aa_minimum(self):
        records = check_contrast.check_theme(palettes.THEME_GRAPHITE)
        text_records = [record for record in records if record["foreground"].startswith("text.")]
        assert text_records
        assert all(record["ratio"] >= 4.5 for record in text_records)

    def test_the_command_passes(self, capsys):
        assert check_contrast.main(["--theme", palettes.THEME_GRAPHITE]) == 0


class TestFormerThemes:
    def test_the_former_themes_are_reported_but_not_blocking(self, capsys):
        assert check_contrast.main(["--theme", "light"]) == 0

    def test_strict_mode_blocks_the_former_themes(self, capsys):
        assert check_contrast.main(["--theme", "light", "--strict"]) == 1

    def test_an_unknown_theme_is_an_error(self, capsys):
        assert check_contrast.main(["--theme", "nonexistent"]) == 2


class TestBlocking:
    def test_a_failing_graphite_pair_fails_the_build(self, monkeypatch, capsys):
        broken = dict(palettes.PALETTES[palettes.THEME_GRAPHITE])
        broken["text.1"] = broken["surface.1"]  # no contrast at all
        monkeypatch.setitem(check_contrast.PALETTES, palettes.THEME_GRAPHITE, broken)
        assert check_contrast.main(["--theme", palettes.THEME_GRAPHITE]) == 1

    def test_json_output(self, monkeypatch, capsys):
        assert check_contrast.main(["--theme", palettes.THEME_GRAPHITE, "--json"]) == 0
        payload = capsys.readouterr().out
        assert '"checks"' in payload
        assert '"failures": 0' in payload
