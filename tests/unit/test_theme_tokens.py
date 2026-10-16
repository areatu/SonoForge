"""UI-0 PR-1: design tokens, legacy palette compatibility, colour ratchet, contrast.

Pure-Python tests (no QApplication): ``theme_tokens`` and the two CI scripts
must import without Qt.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from echo_personal_tool.presentation import theme_tokens as tt

ROOT = Path(__file__).resolve().parents[2]

# The palettes of dark_theme.py before UI-0 (commit 327e5290), verbatim.
# ``legacy_palette()`` must reproduce them exactly: gate "nothing visible
# changes" of spec 2026-10-16 §5.3.
_PRE_TOKEN_PALETTES: dict[str, dict[str, str]] = {
    "dark": {
        "bg_dark": "#102135", "bg_panel": "#12273d", "bg_control": "#1a3050", "bg_button": "#244161",
        "bg_button_hover": "#2e5580", "bg_button_pressed": "#0c1a29", "accent": "#40e2de",
        "accent_bright": "#5ff0ea", "accent_tab": "#40e2de", "accent_selected": "#1a5c5a", "text": "#f1f5f9",
        "text_dim": "#9bacbb", "border": "#2a4a6b", "slider_track": "#1a3050", "slider_fill": "#40e2de",
        "reset_bg1": "#991b1b", "reset_bg2": "#7f1d1d", "reset_hov1": "#dc2626", "reset_hov2": "#991b1b",
        "reset_pressed": "#7f1d1d", "reset_border": "#ef4444", "reset_border_hov": "#f87171",
        "reset_text": "#f1f5f9", "progress_text": "#f1f5f9", "hover_btn1": "#2e5580", "success": "#34d399",
        "warning": "#fb923c", "error": "#f87171",
    },
    "light": {
        "bg_dark": "#f8fafc", "bg_panel": "#ffffff", "bg_control": "#f1f5f9", "bg_button": "#e2e8f0",
        "bg_button_hover": "#cbd5e1", "bg_button_pressed": "#94a3b8", "accent": "#0891b2",
        "accent_bright": "#06b6d4", "accent_tab": "#0891b2", "accent_selected": "#0e7490", "text": "#0f172a",
        "text_dim": "#64748b", "border": "#e2e8f0", "slider_track": "#e2e8f0", "slider_fill": "#0891b2",
        "reset_bg1": "#dc2626", "reset_bg2": "#b91c1c", "reset_hov1": "#ef4444", "reset_hov2": "#dc2626",
        "reset_pressed": "#b91c1c", "reset_border": "#ef4444", "reset_border_hov": "#f87171",
        "reset_text": "#ffffff", "progress_text": "#ffffff", "hover_btn1": "#cbd5e1", "success": "#22c55e",
        "warning": "#f59e0b", "error": "#ef4444",
    },
    "vscode_dark": {
        "bg_dark": "#1e1e1e", "bg_panel": "#252526", "bg_control": "#333333", "bg_button": "#3c3c3c",
        "bg_button_hover": "#454545", "bg_button_pressed": "#2d2d2d", "accent": "#007acc",
        "accent_bright": "#1a8fe3", "accent_tab": "#007acc", "accent_selected": "#007acc", "text": "#cccccc",
        "text_dim": "#858585", "border": "#3c3c3c", "slider_track": "#3c3c3c", "slider_fill": "#007acc",
        "reset_bg1": "#c42b1c", "reset_bg2": "#a01d10", "reset_hov1": "#e04030", "reset_hov2": "#c42b1c",
        "reset_pressed": "#8b1a10", "reset_border": "#e04030", "reset_border_hov": "#f05545",
        "reset_text": "#cccccc", "progress_text": "#cccccc", "hover_btn1": "#505050", "success": "#4ec9b0",
        "warning": "#cca700", "error": "#f14c4c",
    },
    "vscode_light": {
        "bg_dark": "#ffffff", "bg_panel": "#f3f3f3", "bg_control": "#ececec", "bg_button": "#ddd",
        "bg_button_hover": "#c8c8c8", "bg_button_pressed": "#b0b0b0", "accent": "#0066b8",
        "accent_bright": "#005a9e", "accent_tab": "#0066b8", "accent_selected": "#0066b8", "text": "#333333",
        "text_dim": "#6e6e6e", "border": "#d4d4d4", "slider_track": "#d4d4d4", "slider_fill": "#0066b8",
        "reset_bg1": "#c42b1c", "reset_bg2": "#a01d10", "reset_hov1": "#e04030", "reset_hov2": "#c42b1c",
        "reset_pressed": "#8b1a10", "reset_border": "#c42b1c", "reset_border_hov": "#e04030",
        "reset_text": "#ffffff", "progress_text": "#ffffff", "hover_btn1": "#c0c0c0", "success": "#16825d",
        "warning": "#bf8803", "error": "#c42b1c",
    },
}  # fmt: skip


def _load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_script_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestTokenTables:
    def test_tables_are_consistent(self):
        assert tt.validate_tokens() == []

    def test_every_theme_defines_every_token(self):
        for theme in tt.THEME_IDS:
            assert set(tt.tokens_for(theme)) == set(tt.TOKEN_NAMES)

    def test_tables_are_read_only(self):
        with pytest.raises(TypeError):
            tt.THEME_TOKENS["dark"]["surface.0"] = "#000000"  # type: ignore[index]

    def test_unknown_theme_falls_back_to_navy(self):
        assert tt.tokens_for("nonexistent") is tt.THEME_TOKENS["dark"]
        assert tt.normalize_theme_id("system") == "dark"

    def test_token_lookup_rejects_unknown_names(self):
        assert tt.token("light", "text.1") == "#0f172a"
        with pytest.raises(KeyError):
            tt.token("dark", "bg_dark")

    def test_dark_theme_classification(self):
        assert tt.is_dark_theme("dark") and tt.is_dark_theme("vscode_dark")
        assert not tt.is_dark_theme("light") and not tt.is_dark_theme("vscode_light")


class TestLegacyCompatibility:
    @pytest.mark.parametrize("theme", sorted(_PRE_TOKEN_PALETTES))
    def test_legacy_palette_reproduces_pre_token_values(self, theme):
        assert tt.legacy_palette(theme) == _PRE_TOKEN_PALETTES[theme]

    def test_legacy_key_set_is_the_historical_28(self):
        assert len(tt.LEGACY_KEY_TOKENS) == 28
        assert set(tt.LEGACY_KEY_TOKENS) == set(_PRE_TOKEN_PALETTES["dark"])

    def test_legacy_palette_returns_a_fresh_dict(self):
        first = tt.legacy_palette("dark")
        first["bg_dark"] = "#000000"
        assert tt.legacy_palette("dark")["bg_dark"] == "#102135"


class TestContrast:
    def test_known_ratios(self):
        assert tt.contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0)
        assert tt.contrast_ratio("#ffffff", "#ffffff") == pytest.approx(1.0)
        assert tt.contrast_ratio("#777", "#ffffff") == pytest.approx(4.48, abs=0.01)

    def test_short_and_alpha_hex(self):
        assert tt.hex_to_rgb("#ddd") == (221, 221, 221)
        assert tt.hex_to_rgb("#11223344") == (17, 34, 51)
        with pytest.raises(ValueError):
            tt.hex_to_rgb("red")

    def test_navy_primary_text_passes(self):
        failing = {(fg, bg) for fg, bg, _ratio, _req in tt.contrast_failures("dark")}
        assert not any(fg == "text.1" for fg, _bg in failing)

    def test_script_reports_without_failing_legacy_themes(self, capsys):
        script = _load_script("check_theme_contrast")
        assert script.main(["--quiet"]) == 0
        assert "report only" in capsys.readouterr().out or tt.ENFORCED_CONTRAST_THEMES


class TestColourRatchet:
    def test_counts_only_string_literals(self):
        script = _load_script("check_ui_colors")
        source = (
            "# colour #ffffff in a comment and issue (#150)\n"
            "A = '#102135'\n"
            'B = f"color: #abc; border: 1px solid {x}"\n'
            "C = 'see issue #150 and &#123; and url(a#b)'\n"
            "D = '#12345'  # five digits: not a colour\n"
            "E = '#11223344'\n"
        )
        # '#150' inside a string is indistinguishable from a 3-digit colour and counts.
        assert script.count_hex_literals(source) == 4

    def test_compare_flags_growth_and_stale_baseline(self):
        script = _load_script("check_ui_colors")
        up, down = script.compare({"a.py": 3, "new.py": 1}, {"a.py": 2, "gone.py": 4})
        assert any(line.startswith("a.py") for line in up)
        assert any(line.startswith("new.py") for line in up)
        assert any(line.startswith("gone.py") for line in down)

    def test_token_module_is_allowlisted(self):
        script = _load_script("check_ui_colors")
        assert "presentation/theme_tokens.py" in script.ALLOWLIST
        assert "presentation/theme_tokens.py" not in script.collect_counts()

    def test_tree_matches_committed_baseline(self):
        """Same gate as the CI lint step: no new literals, baseline not stale."""
        script = _load_script("check_ui_colors")
        baseline = json.loads((ROOT / "scripts" / "ui_colors_baseline.json").read_text(encoding="utf-8"))
        current = script.collect_counts()
        increases, decreases = script.compare(current, baseline["files"])
        assert not increases, "new hex colour literals — use a design token:\n" + "\n".join(increases)
        assert not decreases, "stale baseline — run scripts/check_ui_colors.py --update:\n" + "\n".join(decreases)
        assert baseline["total"] == sum(baseline["files"].values())
