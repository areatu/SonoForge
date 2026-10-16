"""Unit tests for the design tokens, the palettes and the stylesheet (UI-0, PR-1).

The tokens are the new single source of the colours of the interface. Two
things are checked here:

* the tokens are complete and consistent — every theme defines every token,
  the legacy 28-key palette is still computed from them,
* nothing changes for the user — the stylesheet of the four former themes is
  byte for byte the one of the previous release (golden files).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from echo_personal_tool.presentation.theme import palettes, qss, tokens

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_ui_colors  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ui"
LEGACY_THEMES = ("dark", "light", "vscode_dark", "vscode_light")
GOLDEN_STYLESHEETS = {
    "dark": "stylesheet_navy.golden.txt",
    "light": "stylesheet_light.golden.txt",
    "vscode_dark": "stylesheet_vscode_dark.golden.txt",
    "vscode_light": "stylesheet_vscode_light.golden.txt",
}


def _normalize(stylesheet: str) -> str:
    """Replace the machine-specific icon path and the "white" spelling."""
    icons = Path(palettes.__file__).resolve().parent.parent.parent / "resources" / "icons"
    normalized = stylesheet.replace(icons.resolve().as_posix(), "{ICONS}")
    # The former stylesheet spelled the colour of the close button "white".
    return normalized.replace("color: white;", "color: #ffffff;")


class TestTokenVocabulary:
    def test_every_palette_defines_every_token(self):
        for theme_id in palettes.THEME_IDS:
            assert palettes.missing_tokens(theme_id) == (), theme_id
            assert palettes.validate_palette(theme_id) == (), theme_id

    def test_token_names_are_unique(self):
        assert len(set(tokens.TOKEN_NAMES)) == len(tokens.TOKEN_NAMES)

    def test_overlay_group_is_declared_but_not_valued_yet(self):
        """The overlay colours arrive with UI-0 PR-7 (the viewer)."""
        overlay = [spec.name for spec in tokens.TOKENS if spec.group == tokens.GROUP_OVERLAY]
        assert overlay, "the overlay group must stay declared"
        for theme_id in palettes.THEME_IDS:
            values = palettes.PALETTES[theme_id]
            assert all(name not in values for name in overlay)

    def test_legacy_contract_covers_28_keys(self):
        assert len(tokens.LEGACY_KEYS) == 28
        assert set(tokens.LEGACY_KEY_TO_TOKEN.values()) <= set(tokens.REQUIRED_TOKEN_NAMES)


class TestLegacyPalettes:
    def test_legacy_palettes_match_the_golden_fixture(self):
        golden = json.loads((FIXTURES / "legacy_palettes.json").read_text(encoding="utf-8"))
        for theme_id in LEGACY_THEMES:
            assert palettes.get_legacy_palette(theme_id) == golden[theme_id], theme_id

    def test_legacy_round_trip(self):
        for theme_id in LEGACY_THEMES:
            legacy = palettes.get_legacy_palette(theme_id)
            assert tokens.tokens_to_legacy(tokens.legacy_to_tokens(legacy)) == legacy

    def test_legacy_palette_has_28_hex_values(self):
        for theme_id in palettes.THEME_IDS:
            legacy = palettes.get_legacy_palette(theme_id)
            assert len(legacy) == 28, theme_id
            assert all(value.startswith("#") for value in legacy.values()), theme_id

    def test_paper_is_the_same_in_every_theme(self):
        """The A4 sheet of the report is always light."""
        for token_name in ("paper.surface", "paper.text", "paper.text.dim", "paper.line"):
            values = {palettes.PALETTES[theme_id][token_name] for theme_id in palettes.THEME_IDS}
            assert len(values) == 1, token_name


class TestGraphitePalette:
    def test_documented_values(self):
        """The graphite palette of the spec (§5.2)."""
        values = palettes.PALETTES[palettes.THEME_GRAPHITE]
        expected = {
            "surface.0": "#0b0d0f",
            "surface.1": "#131619",
            "surface.2": "#1a1e22",
            "surface.3": "#23282d",
            "line.1": "#262b31",
            "line.2": "#343b42",
            "text.1": "#e6e9ec",
            "text.2": "#a3abb3",
            "text.3": "#858f99",
            "text.disabled": "#6e7781",
            "accent": "#2bd1cb",
            "accent.text": "#5fe3dd",
            "accent.on": "#032421",
            "state.ok": "#3ccb7f",
            "state.warn": "#f2a93b",
            "state.err": "#f06a6a",
            "state.info": "#5aa9ff",
            "paper.surface": "#ffffff",
        }
        for token_name, value in expected.items():
            assert values[token_name] == value, token_name

    def test_focus_ring_is_the_accent(self):
        values = palettes.PALETTES[palettes.THEME_GRAPHITE]
        assert values["focus.ring"] == values["accent"]


class TestStylesheet:
    @pytest.mark.parametrize("theme_id", LEGACY_THEMES)
    def test_stylesheet_matches_the_golden_file(self, theme_id):
        """The former themes must not change a single pixel."""
        golden = _normalize((FIXTURES / GOLDEN_STYLESHEETS[theme_id]).read_text(encoding="utf-8"))
        assert _normalize(qss.build_clinical_stylesheet(13, theme_id)) == golden

    def test_stylesheet_source_has_no_raw_colour_literal(self):
        """The stylesheet is assembled from tokens — no literal colours."""
        source = Path(qss.__file__).read_text(encoding="utf-8")
        assert check_ui_colors.count_literals(source) == 0

    def test_stylesheet_is_cached(self):
        first = qss.build_clinical_stylesheet(13, "dark")
        second = qss.build_clinical_stylesheet(13, "dark")
        assert first is second

    def test_system_theme_is_resolved_on_every_call(self, monkeypatch):
        """The system may change while the application runs."""
        monkeypatch.setattr(qss, "system_theme_id", lambda: "dark")
        dark_sheet = qss.build_clinical_stylesheet(13, "system")
        monkeypatch.setattr(qss, "system_theme_id", lambda: "light")
        light_sheet = qss.build_clinical_stylesheet(13, "system")
        assert dark_sheet != light_sheet
        assert dark_sheet == qss.build_clinical_stylesheet(13, "dark")
        assert light_sheet == qss.build_clinical_stylesheet(13, "light")

    def test_font_size_changes_the_sheet(self):
        assert "15px" in qss.build_clinical_stylesheet(15, "dark")
        assert "13px" in qss.build_clinical_stylesheet(13, "dark")

    def test_every_theme_produces_a_sheet(self):
        for theme_id in palettes.THEME_IDS:
            assert len(qss.build_clinical_stylesheet(13, theme_id)) > 100, theme_id

    def test_system_theme_resolves_to_a_concrete_theme(self):
        sheet = qss.build_clinical_stylesheet(13, "system")
        assert len(sheet) > 100


class TestCompatibilityFacade:
    """``presentation.theme_tokens`` stays importable (UI-0, PR-1).

    The flat token module of the first UI-0 pull request became the package
    ``presentation/theme`` (spec §9). The old name keeps working as a facade,
    so nothing that imported it breaks.
    """

    def test_the_facade_exposes_the_same_values(self):
        from echo_personal_tool.presentation import theme_tokens

        assert theme_tokens.THEME_IDS == palettes.THEME_IDS
        assert set(theme_tokens.TOKEN_NAMES) == set(tokens.TOKEN_NAMES)
        assert theme_tokens.LEGACY_KEY_TOKENS == tokens.LEGACY_KEY_TO_TOKEN
        assert theme_tokens.legacy_palette("dark") == palettes.get_legacy_palette("dark")

    def test_the_facade_falls_back_to_navy(self):
        from echo_personal_tool.presentation import theme_tokens

        assert theme_tokens.normalize_theme_id("nonexistent") == "dark"
        assert theme_tokens.normalize_theme_id("system") == "dark"
        assert theme_tokens.tokens_for("nonexistent") == theme_tokens.tokens_for("dark")

    def test_the_facade_rejects_an_unknown_token(self):
        from echo_personal_tool.presentation import theme_tokens

        assert theme_tokens.token("light", "text.1") == palettes.PALETTES["light"]["text.1"]
        with pytest.raises(KeyError):
            theme_tokens.token("light", "bg_dark")

    def test_the_facade_tables_are_read_only(self):
        from echo_personal_tool.presentation import theme_tokens

        with pytest.raises(TypeError):
            theme_tokens.THEME_TOKENS["dark"]["surface.0"] = "#000000"  # type: ignore[index]

    def test_the_facade_returns_a_fresh_legacy_palette(self):
        from echo_personal_tool.presentation import theme_tokens

        first = theme_tokens.legacy_palette("dark")
        first["bg_dark"] = "#000000"
        assert theme_tokens.legacy_palette("dark")["bg_dark"] == "#102135"

    def test_the_token_tables_are_consistent(self):
        from echo_personal_tool.presentation import theme_tokens

        assert theme_tokens.validate_tokens() == []

    def test_the_contrast_math_is_shared(self):
        from echo_personal_tool.presentation import theme_tokens
        from echo_personal_tool.presentation.theme import contrast

        assert theme_tokens.contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0)
        assert theme_tokens.hex_to_rgb("#11223344") == (17, 34, 51)
        assert theme_tokens.relative_luminance is contrast.relative_luminance
