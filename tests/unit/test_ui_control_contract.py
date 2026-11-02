"""The shared button/panel contract (2026-10-27 UI list, item 8).

One geometry and one QSS recipe for the settings dialog, the protocol strip,
the panel chips and the tool rows.  The tests here are Qt-free: they check the
recipe, the token colours and their contrast, so a palette change cannot
silently break a hover state.
"""

from __future__ import annotations

import re

import pytest

from echo_personal_tool.presentation.theme import controls
from echo_personal_tool.presentation.theme.contrast import contrast_ratio
from echo_personal_tool.presentation.theme.palettes import (
    ACCENT_PALETTES,
    PALETTES,
    get_palette_tokens,
)

_STATES = ("", ":hover", ":pressed", ":checked", ":focus", ":disabled")


def test_geometry_uses_one_grid() -> None:
    assert controls.CONTROL_HEIGHT == 32
    assert controls.CHIP_HEIGHT == 34
    assert controls.BUTTON_RADIUS == controls.CHIP_RADIUS == 6
    assert controls.BORDER_WIDTH == 1
    assert controls.GAP_XS == 4 and controls.GAP_SM == 6 and controls.GAP_MD == 8
    assert controls.MIN_TOOL_CELL_WIDTH >= 120


@pytest.mark.parametrize("variant", ["secondary", "primary", "chip"])
def test_every_button_has_every_interactive_state(variant: str) -> None:
    tokens = get_palette_tokens("graphite")
    qss = controls.button_qss("QPushButton#probe", tokens, variant=variant)
    for state in _STATES:
        assert f"QPushButton#probe{state} {{" in qss, (variant, state)
    assert "border-radius: 6px" in qss
    assert "min-height: 32px" in qss
    # A fixed pixel vertical padding + min-height freezes the button at every
    # UI font (Э4/D-26).  The padding must scale with the font instead.
    assert re.search(r"padding:\s*[\d.]+em\s+10px", qss), qss
    assert "padding: 5px" not in qss


@pytest.mark.parametrize("theme", PALETTES)
@pytest.mark.parametrize("accent", ["theme", *ACCENT_PALETTES])
def test_primary_caption_stays_readable_in_every_state(theme: str, accent: str) -> None:
    """Hover/press of «Готово» must not brighten the fill below AA."""
    tokens = get_palette_tokens(theme, accent_palette=accent)
    qss = controls.button_qss("QPushButton#primary", tokens, variant="primary")
    for state in ("", ":hover", ":pressed"):
        block = qss.split(f"QPushButton#primary{state} {{", 1)[1].split("}", 1)[0]
        background = re.search(r"background:\s*(#[0-9a-fA-F]{6})", block).group(1)
        assert contrast_ratio(tokens["accent.text"], background) >= 4.5, (theme, accent, state)


@pytest.mark.parametrize("theme", PALETTES)
@pytest.mark.parametrize("accent", ["theme", *ACCENT_PALETTES])
def test_secondary_caption_stays_readable_in_every_state(theme: str, accent: str) -> None:
    tokens = get_palette_tokens(theme, accent_palette=accent)
    qss = controls.button_qss("QPushButton#secondary", tokens)
    for state in ("", ":hover", ":pressed"):
        block = qss.split(f"QPushButton#secondary{state} {{", 1)[1].split("}", 1)[0]
        background = re.search(r"background:\s*(#[0-9a-fA-F]{6})", block).group(1)
        assert contrast_ratio(tokens["text.1"], background) >= 4.5, (theme, accent, state)


def test_card_qss_has_one_hairline_and_one_radius() -> None:
    tokens = get_palette_tokens("graphite")
    qss = controls.card_qss("#card", tokens)
    assert f"border: 1px solid {tokens['line.1']}" in qss
    assert "border-radius: 8px" in qss


def test_interface_palette_presets_are_accents_only() -> None:
    """The palette chooses the accent; the theme keeps the ground (item 1).

    The picker used to write *both* the theme and the accent, so a card
    repainted the window ground, the panels and the text — the same promise as
    the theme combo.  A preset now names an accent and nothing else; the theme
    is not part of its identity anymore.
    """
    from echo_personal_tool.presentation.theme.palette_picker import PRESETS

    assert len(PRESETS) == 1 + len(ACCENT_PALETTES)
    assert len({preset.preset_id for preset in PRESETS}) == len(PRESETS)
    accents = {preset.accent for preset in PRESETS}
    assert accents == {"theme", *ACCENT_PALETTES}
    for preset in PRESETS:
        assert not hasattr(preset, "theme"), preset
        # The surfaces of the card preview come from the *current* theme and do
        # not depend on the accent; only ``accent`` moves.
        for theme in PALETTES:
            tokens = get_palette_tokens(theme, accent_palette=preset.accent)
            assert all(role in tokens for role in ("surface.1", "surface.2", "surface.3", "accent"))


@pytest.mark.parametrize("theme", PALETTES)
def test_an_accent_palette_never_repaints_the_ground(theme: str) -> None:
    """Item 1 of the 2026-10-27 list: palette and theme do not overlap.

    A theme fixes the ground, the panels and the text; the accent palette may
    change the controls and the selection, never those.  The test compares the
    full token dicts: every role outside ``accent.*`` / the ring must be the
    same under all five palette choices.
    """
    base = get_palette_tokens(theme)
    accent_only = {
        "accent",
        "accent.text",
        "accent.on",
        "accent.tab",
        "accent.selected",
        "accent.tint",
        "accent.line",
        "focus.ring",
        "slider.fill",
        "progress.text",
        "text.selected",
    }
    for accent in ACCENT_PALETTES:
        palette = get_palette_tokens(theme, accent_palette=accent)
        changed = {name for name in base if base[name] != palette[name]}
        assert changed <= accent_only, (theme, accent, sorted(changed - accent_only))
        for role in (
            "surface.0",
            "surface.1",
            "surface.2",
            "surface.3",
            "text.1",
            "text.2",
            "text.3",
            "line.1",
            "line.2",
        ):
            assert palette[role] == base[role], (theme, accent, role)
