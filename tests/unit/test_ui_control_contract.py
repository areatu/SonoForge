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


def test_interface_palette_presets_are_real_themes_and_accents() -> None:
    from echo_personal_tool.presentation.theme.palette_picker import PRESETS

    assert len(PRESETS) == 6
    assert len({preset.preset_id for preset in PRESETS}) == len(PRESETS)
    for preset in PRESETS:
        assert preset.theme in PALETTES, preset
        assert preset.accent == "theme" or preset.accent in ACCENT_PALETTES, preset
        tokens = get_palette_tokens(preset.theme, accent_palette=preset.accent)
        assert all(role in tokens for role in ("surface.1", "surface.2", "surface.3", "accent"))
