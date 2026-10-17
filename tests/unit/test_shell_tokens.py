"""The window shell paints design tokens, never colours (UI-0, PR-3, spec §5).

The shell — the top system bar, the tab strip, the activity rail and the
permanent labels of the status bar — used to carry raw colours: a hex fallback
of the icon tint in three modules, six literals of the legacy teal fill of the
«Нормативы» button (the same in every theme, because they were hardcoded in
the widget) and two literals of the status-bar labels. All of them are gone:
the shell asks the active theme for a *role* (``text.1``, ``state.warn``,
``text.3``), so it follows any theme without a branch of its own.

The tests pin what the migration is about:

* no colour literal survives in the stylesheets of the shell widgets,
* every glyph the shell draws takes ``text.1`` of the active theme,
* the tint is re-read on a theme change — a theme switch repaints the shell.

The tests switch the theme *mode* of the facade and never the application-wide
stylesheet: a changed sheet repolishes every widget the suite keeps alive
(``tests/unit/conftest.py`` pins it back for that very reason), while the shell
reads the tokens of the mode directly.
"""

from __future__ import annotations

import collections
import re
import types

import pytest

pytestmark = pytest.mark.gui

#: A colour literal in a stylesheet — what the shell must not contain anymore.
_COLOUR_LITERAL = re.compile(r"#[0-9a-fA-F]{3,8}\b")


@pytest.fixture()
def apply_theme(monkeypatch):
    """Switch the theme mode of the facade; returns its tokens.

    ``dark_theme._current_theme_mode`` is what both ``get_theme_palette()`` and
    ``get_theme_tokens()`` resolve, so a shell widget follows it without an
    application-wide stylesheet — and the suite keeps its style-sheet repolish
    budget for the tests that need a real theme change.
    """
    from echo_personal_tool.presentation import dark_theme

    def _apply(theme: str) -> dict[str, str]:
        monkeypatch.setattr(dark_theme, "_current_theme_mode", theme)
        return dark_theme.get_theme_tokens()

    return _apply


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    text = value.lstrip("#")
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def _solid_colours(icon, size: int = 48) -> collections.Counter:
    """Colours of the pixels of a glyph, antialiased fringes left out."""
    image = icon.pixmap(size, size).toImage()
    colours: collections.Counter = collections.Counter()
    for y in range(image.height()):
        for x in range(image.width()):
            pixel = image.pixelColor(x, y)
            if pixel.alpha() >= 200:
                colours[(pixel.red(), pixel.green(), pixel.blue())] += 1
    return colours


def _glyph_colour(icon, size: int = 48) -> tuple[int, int, int]:
    """The colour of a glyph of the theme (solid pixels are exactly the token)."""
    colours = _solid_colours(icon, size)
    assert colours, "the glyph rendered nothing — the icon file is missing?"
    return colours.most_common(1)[0][0]


def _styled_widgets(widget):
    """The widget itself and its children that carry a stylesheet."""
    from PySide6.QtWidgets import QWidget

    return [child for child in (widget, *widget.findChildren(QWidget)) if child.styleSheet()]


def _system_bar():
    from echo_personal_tool.presentation.system_bar import SystemBar

    return SystemBar()


def _tab_strip():
    from echo_personal_tool.presentation.tab_bar import TabStrip

    return TabStrip()


def _activity_rail():
    from echo_personal_tool.presentation.activity_bar import ActivityBar

    return ActivityBar()


# ── No colour literals left in the shell ───────────────────────────


@pytest.mark.parametrize(
    "factory",
    [_system_bar, _tab_strip, _activity_rail],
    ids=["system-bar", "tab-strip", "activity-rail"],
)
def test_shell_stylesheets_hold_no_colour_literal(qtbot, apply_theme, factory) -> None:
    apply_theme("graphite")
    widget = factory()
    qtbot.addWidget(widget)

    for child in _styled_widgets(widget):
        stylesheet = child.styleSheet()
        assert not _COLOUR_LITERAL.search(stylesheet), (
            f"{type(child).__name__} {child.objectName()!r} paints a raw colour: {stylesheet!r}"
        )


def test_references_button_is_a_plain_bar_button(qtbot) -> None:
    """UI-0 PR-3: the legacy teal fill of «Нормативы» is gone (spec §2.1).

    The button keeps its glyph, its text and its signal; only the hardcoded
    colour of the widget — the same in every theme, including the light one —
    is dropped. UI-1 re-homes the action to the patient row as a plain button.
    """
    bar = _system_bar()
    qtbot.addWidget(bar)

    references = bar._btn_references
    assert references.styleSheet() == ""
    assert not references.icon().isNull()
    assert references.toolTip()
    assert not references.text().startswith("system_bar.")


# ── Glyphs follow the theme through the text token ─────────────────


def test_system_bar_glyphs_take_the_text_token(qtbot, apply_theme) -> None:
    theme = apply_theme("graphite")
    bar = _system_bar()
    qtbot.addWidget(bar)

    expected = _hex_to_rgb(theme["text.1"])
    # 24 px is the natural size of the bundled glyphs: a requested 18 px would
    # be a downscaled, heavily antialiased copy without a solid pixel.
    for button in (bar._btn_open, bar._btn_pacs, bar._btn_references, bar._btn_heart_rate):
        assert _glyph_colour(button.icon(), 24) == expected


def test_system_bar_reglyphs_follow_a_theme_change(qtbot, apply_theme) -> None:
    apply_theme("graphite")
    bar = _system_bar()
    qtbot.addWidget(bar)
    before = _solid_colours(bar._btn_open.icon(), 24)

    other = apply_theme("vscode_dark")
    bar.reload_icons()

    assert _solid_colours(bar._btn_open.icon(), 24) != before
    assert _glyph_colour(bar._btn_open.icon(), 24) == _hex_to_rgb(other["text.1"])


def test_tab_strip_close_glyph_takes_the_text_token(qtbot, apply_theme) -> None:
    theme = apply_theme("graphite")
    strip = _tab_strip()
    qtbot.addWidget(strip)
    strip.set_tabs([("tab-1", "клип")], "tab-1")

    from PySide6.QtWidgets import QToolButton

    close_buttons = [button for button in strip._bar.findChildren(QToolButton) if button.property("themedClose")]
    assert close_buttons, "the tab strip draws no themed close glyph"
    assert _glyph_colour(close_buttons[0].icon(), 16) == _hex_to_rgb(theme["text.1"])


def test_tab_strip_close_glyph_follows_a_theme_change(apply_theme) -> None:
    from echo_personal_tool.presentation.tab_bar import _close_icon

    apply_theme("graphite")
    before = _solid_colours(_close_icon(), 16)

    other = apply_theme("light")

    assert _solid_colours(_close_icon(), 16) != before
    assert _glyph_colour(_close_icon(), 16) == _hex_to_rgb(other["text.1"])


def test_activity_rail_icons_have_no_background_patch(qtbot, apply_theme) -> None:
    """The rail glyphs used to be drawn on an opaque black square.

    ``QPixmap.fill(0)`` produced the RGB32 format, so the transparent button
    background of the theme showed a black tile behind every glyph (and the
    tint of the glyph was the only thing that followed the theme).
    """
    apply_theme("graphite")
    rail = _activity_rail()
    qtbot.addWidget(rail)

    for button in rail._buttons.values():
        image = button.icon().pixmap(48, 48).toImage()
        assert image.hasAlphaChannel()
        assert image.pixelColor(0, 0).alpha() == 0


def test_activity_rail_glyphs_take_the_text_token(qtbot, apply_theme) -> None:
    theme = apply_theme("graphite")
    rail = _activity_rail()
    qtbot.addWidget(rail)

    expected = _hex_to_rgb(theme["text.1"])
    for button in rail._buttons.values():
        assert _glyph_colour(button.icon(), 48) == expected


# ── The permanent labels of the status bar ─────────────────────────


def _status_bar_double() -> types.SimpleNamespace:
    """The two labels the main window holds (a full window is not needed)."""
    from PySide6.QtWidgets import QLabel

    return types.SimpleNamespace(_research_warning=QLabel(), _version_label=QLabel())


def test_status_bar_labels_take_theme_tokens(apply_theme) -> None:
    from echo_personal_tool.presentation.main_window import MainWindow

    theme = apply_theme("graphite")
    window = _status_bar_double()
    MainWindow.apply_status_bar_tokens(window)

    assert theme["state.warn"] in window._research_warning.styleSheet()
    assert theme["text.3"] in window._version_label.styleSheet()


def test_status_bar_labels_follow_a_theme_change(apply_theme) -> None:
    from echo_personal_tool.presentation.main_window import MainWindow

    apply_theme("graphite")
    window = _status_bar_double()
    MainWindow.apply_status_bar_tokens(window)
    before = (window._research_warning.styleSheet(), window._version_label.styleSheet())

    other = apply_theme("vscode_light")
    MainWindow.apply_status_bar_tokens(window)

    assert (window._research_warning.styleSheet(), window._version_label.styleSheet()) != before
    assert other["state.warn"] in window._research_warning.styleSheet()
    assert other["text.3"] in window._version_label.styleSheet()


def test_status_bar_tokens_are_skipped_until_the_labels_exist() -> None:
    """The window applies its preferences once before the status bar is built."""
    from echo_personal_tool.presentation.main_window import MainWindow

    MainWindow.apply_status_bar_tokens(types.SimpleNamespace())
