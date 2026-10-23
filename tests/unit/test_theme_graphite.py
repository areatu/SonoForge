"""Unit tests for the «Graphite» theme (UI-0 PR-2, spec 2026-10-16 §5.2, §10).

UI-0 PR-1 described the theme in the tokens but kept it out of the interface.
PR-2 makes it selectable and holds it in place:

* the palette of the theme is the one of the spec (§5.2),
* the theme is offered by the start page and by the preferences dialog and is
  accepted by the stored preferences,
* the theme is a dark theme (the inverted logo belongs to it),
* its contrast is *enforced*: a pair below the WCAG 2.1 AA minimum fails the
  build, unlike the former themes, whose colours are only reported.
"""

from __future__ import annotations

import pytest

from echo_personal_tool.presentation.theme import contrast, palettes
from echo_personal_tool.presentation.theme_tokens import (
    DARK_THEMES,
    THEME_IDS,
    legacy_palette,
    normalize_theme_id,
    tokens_for,
)

GRAPHITE = palettes.THEME_GRAPHITE


class _MemoryStore:
    """A minimal stand-in for the QSettings of the preferences."""

    def __init__(self, values: dict[str, object] | None = None) -> None:
        self._values = dict(values or {})

    def value(self, key: str, default=None):  # noqa: ANN001, ANN201
        return self._values.get(key, default)

    def setValue(self, key: str, value) -> None:  # noqa: N802, ANN001
        self._values[key] = value


class TestGraphiteIsSelectable:
    def test_the_theme_id_is_known(self):
        assert GRAPHITE in THEME_IDS
        assert GRAPHITE in palettes.PALETTES

    def test_the_theme_is_dark(self):
        """The inverted logo belongs to the theme."""
        assert palettes.is_dark_theme(GRAPHITE)
        assert GRAPHITE in DARK_THEMES

    def test_the_legacy_palette_is_computed_for_it(self):
        """The 28-key contract of ``get_theme_palette()`` holds for it too."""
        legacy = legacy_palette(GRAPHITE)
        assert len(legacy) == 28
        assert legacy["bg_dark"] == palettes.PALETTES[GRAPHITE]["surface.0"]
        assert legacy["text"] == palettes.PALETTES[GRAPHITE]["text.1"]
        assert legacy["accent"] == palettes.PALETTES[GRAPHITE]["accent"]

    def test_the_start_page_offers_the_theme(self):
        from echo_personal_tool.presentation.start_page import StartPage

        values = [value for _key, value in StartPage._THEMES]
        assert GRAPHITE in values

    def test_the_stored_preferences_accept_the_theme(self, monkeypatch: pytest.MonkeyPatch):
        from echo_personal_tool.infrastructure import user_preferences as up_mod

        store = _MemoryStore({"theme_mode": GRAPHITE})
        monkeypatch.setattr(up_mod, "_settings_store", lambda: store)
        assert up_mod.load_user_preferences().theme_mode == GRAPHITE

    def test_an_unknown_theme_still_falls_back_to_navy(self):
        assert normalize_theme_id(GRAPHITE) == GRAPHITE
        assert normalize_theme_id("no-such-theme") == palettes.THEME_DARK


class TestGraphiteContrastIsEnforced:
    def test_the_theme_is_in_the_enforced_set(self):
        assert GRAPHITE in contrast.ENFORCED_CONTRAST_THEMES

    def test_the_former_themes_are_only_reported(self):
        assert contrast.ENFORCED_CONTRAST_THEMES == {GRAPHITE}
        for theme_id in ("dark", "light", "vscode_dark", "vscode_light"):
            assert theme_id not in contrast.ENFORCED_CONTRAST_THEMES

    def test_every_checked_pair_reaches_its_minimum(self):
        failures = contrast.contrast_failures(GRAPHITE)
        assert failures == [], failures

    @pytest.mark.parametrize(
        "check",
        contrast.CHECKS,
        ids=lambda check: f"{check.foreground}-on-{check.background}",
    )
    def test_the_pair_reaches_its_minimum(self, check: contrast.ContrastCheck):
        values = tokens_for(GRAPHITE)
        ratio = contrast.contrast_ratio(values[check.foreground], values[check.background])
        assert ratio >= check.minimum, (check.foreground, check.background, ratio, check.minimum)

    def test_the_script_passes_for_the_theme(self):
        import sys
        from pathlib import Path

        scripts = Path(__file__).resolve().parents[2] / "scripts"
        sys.path.insert(0, str(scripts))
        import check_contrast

        assert check_contrast.main(["--theme", GRAPHITE]) == 0


class TestGraphitePalette:
    def test_every_token_is_defined(self):
        assert palettes.missing_tokens(GRAPHITE) == ()
        assert palettes.validate_palette(GRAPHITE) == ()

    def test_the_destructive_scale_stays_visible(self):
        """The border of a destructive button is seen on every surface."""
        values = palettes.PALETTES[GRAPHITE]
        for surface in ("surface.0", "surface.1", "surface.2", "surface.3"):
            ratio = contrast.contrast_ratio(values["state.danger.border"], values[surface])
            assert ratio >= 3.0, (surface, ratio)

    def test_the_destructive_text_is_readable_on_every_fill(self):
        values = palettes.PALETTES[GRAPHITE]
        for fill in ("state.danger.bg", "state.danger.bg.hover", "state.danger.bg.pressed"):
            ratio = contrast.contrast_ratio(values["state.danger.text"], values[fill])
            assert ratio >= 4.5, (fill, ratio)

    def test_the_quiet_destructive_fill_keeps_its_label_readable_in_every_theme(self):
        """«Сброс» is painted on the muted danger fill, not on the bright one.

        The action row used the brightest red for the destructive button, so it
        looked like the primary action; the muted shade is now the resting
        state. Unlike a ghost variant (transparent background), it stays legible
        in the light themes, where ``state.danger.text`` is white.
        """
        for theme, values in palettes.PALETTES.items():
            ratio = contrast.contrast_ratio(values["state.danger.text"], values["state.danger.bg2"])
            assert ratio >= 4.5, (theme, ratio)

    def test_the_paper_is_light_in_every_theme(self):
        """The A4 sheet of the report stays light — also in the new theme."""
        assert palettes.PALETTES[GRAPHITE]["paper.surface"] == "#ffffff"
        assert palettes.PALETTES[GRAPHITE]["paper.text"] == "#1b1f24"
