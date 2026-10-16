"""Screenshot base of the themes (UI-0 PR-2, spec 2026-10-16 §5.3, §10).

The gate of UI-0: the new «Graphite» theme is correct, and the historical
navy theme did not change while the tokens were reworked.  The base is a
committed PNG per theme (``tests/baselines/ui``); the comparison is tolerant
to the PySide6 version and to the font rasterizer — see
``tests/fixtures/screenshot_base.py`` for the rules.

Regenerate the baselines after an intentional change of a theme::

    SONOFORGE_UPDATE_SCREENSHOTS=1 pytest tests/unit/test_ui_screenshot_base.py
"""

from __future__ import annotations

import pytest

pytest.importorskip("pytestqt")
pytestmark = pytest.mark.gui

from tests.fixtures.screenshot_base import (  # noqa: E402
    FRINGE_BUDGET,
    blend_pairs,
    colour_histogram,
    compare_images,
    expected_colours,
    foreign_pixels,
    is_blend,
    is_channel_mix,
    load_baseline,
    render_probe,
    required_colours,
    save_baseline,
    strong_colours,
    text_colour,
    update_requested,
)

#: Themes with a committed baseline.
THEMES = ("dark", "graphite")

#: The colours of the fringes that the subpixel antialiasing produced on a
#: screen platform (the CI runner with Xvfb) — they are not mixtures with a
#: single share, but every channel lies between the channels of the theme.
SUBPIXEL_FRONTIERS = (
    ("dark", "#1c4b82"),
    ("dark", "#90bad7"),
    ("dark", "#d9eaf4"),
    ("dark", "#edeeed"),
    ("dark", "#dcd8d3"),
    ("dark", "#b2a384"),
    ("graphite", "#1d3b67"),
    ("graphite", "#8aadc6"),
    ("graphite", "#d0dde6"),
    ("graphite", "#e2e2df"),
    ("graphite", "#d2cbc1"),
    ("graphite", "#aa9568"),
)


@pytest.fixture(scope="module")
def renderings(qapp_session) -> dict:
    """One rendering per theme (the module scope keeps the run fast)."""
    return {theme: render_probe(theme) for theme in THEMES}


@pytest.mark.parametrize("theme", THEMES)
def test_probe_shows_only_the_colours_of_the_theme(theme: str, renderings: dict) -> None:
    """No foreign colour in the rendering — the theme really is the source."""
    strong = strong_colours(renderings[theme])
    allowed = expected_colours(theme)
    foreign = {colour: share for colour, share in strong.items() if colour not in allowed}
    assert foreign == {}, (theme, foreign)


@pytest.mark.parametrize("theme", THEMES)
def test_probe_shows_the_main_colours(theme: str, renderings: dict) -> None:
    strong = strong_colours(renderings[theme])
    missing = sorted(colour for colour in required_colours(theme) if colour not in strong)
    assert missing == [], (theme, missing)


@pytest.mark.parametrize("theme", THEMES)
def test_every_pixel_is_a_mixture_of_theme_colours(theme: str, renderings: dict) -> None:
    """The rendering mixes nothing but the colours of the theme.

    The check does not depend on the font: the antialiasing of the glyphs
    produces exactly mixtures of the background and of the text colour.
    """
    foreign = foreign_pixels(renderings[theme], theme)
    assert foreign == [], (theme, foreign)


@pytest.mark.parametrize("theme", THEMES)
def test_text_is_drawn_in_the_text_token(theme: str, renderings: dict) -> None:
    """The primary text colour of the theme is really used for the text."""
    counter = colour_histogram(renderings[theme])
    assert counter[text_colour(theme)] >= 1, (theme, counter[text_colour(theme)])


@pytest.mark.parametrize("theme", THEMES)
def test_theme_matches_the_committed_baseline(theme: str, renderings: dict) -> None:
    """«Скриншоты navy до и после совпадают в пределах допуска» (gate UI-0)."""
    baseline = load_baseline(theme)
    if baseline is None:
        if update_requested():
            save_baseline(renderings[theme], theme)
            pytest.skip(f"the baseline of {theme} was created")
        pytest.fail(f"no baseline for {theme}: {theme}.png is missing")
    assert compare_images(renderings[theme], baseline) == []


def test_graphite_baseline_is_committed() -> None:
    """The base exists in the repository — it is the gate of the theme."""
    assert load_baseline("graphite") is not None
    assert load_baseline("dark") is not None


@pytest.mark.parametrize(("theme", "colour"), SUBPIXEL_FRONTIERS)
def test_the_fringes_of_the_subpixel_antialiasing_are_tolerated(theme: str, colour: str) -> None:
    """A fringe of a screen platform is a per-channel mixture, not a foreign colour.

    The probe rasterizes the text with the grayscale antialiasing, but a
    machine with a screen may still mix the channels separately.  Such a
    colour must not be reported as a colour of another theme.
    """
    pairs = blend_pairs(theme)
    assert not any(is_blend(colour, background, foreground) for background, foreground in pairs)
    assert any(is_channel_mix(colour, background, foreground) for background, foreground in pairs)


def test_a_colour_of_another_theme_is_still_foreign() -> None:
    """The tolerance of the fringes does not open the gate for a real colour."""
    pairs = blend_pairs("graphite")
    assert not any(is_blend("#ff0000", background, foreground) for background, foreground in pairs)
    assert not any(is_channel_mix("#ff0000", background, foreground) for background, foreground in pairs)


def test_the_budget_of_the_fringes_is_small() -> None:
    """The fringes may not become the rule: they are an artefact, not the theme."""
    assert 0 < FRINGE_BUDGET <= 0.05


def test_navy_theme_is_unchanged_by_the_new_theme() -> None:
    """The navy palette still equals the pre-token values (UI-0 PR-1)."""
    from echo_personal_tool.presentation.theme_tokens import legacy_palette

    palette = legacy_palette("dark")
    assert palette["bg_dark"] == "#102135"
    assert palette["bg_panel"] == "#12273d"
    assert palette["accent"] == "#40e2de"
    assert palette["text"] == "#f1f5f9"
