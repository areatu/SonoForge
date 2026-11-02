"""The compact control palette stays readable across all themes and accents."""

from echo_personal_tool.presentation.theme.contrast import contrast_ratio
from echo_personal_tool.presentation.theme.palettes import ACCENT_PALETTES, PALETTES, get_palette_tokens
from echo_personal_tool.presentation.theme.qss import build_clinical_stylesheet


def test_button_captions_are_aa_readable_in_every_theme_and_accent():
    for theme in PALETTES:
        for accent in ("theme", *ACCENT_PALETTES):
            t = get_palette_tokens(theme, accent_palette=accent)
            for foreground, background in (
                ("text.1", "surface.3"),
                ("text.1", "surface.2"),
                ("accent.text", "accent.tint"),
                ("text.1", "surface.hover"),
                ("accent.on", "accent"),
            ):
                assert contrast_ratio(t[foreground], t[background]) >= 4.5, (theme, accent, foreground, background)


def test_accents_do_not_change_clinical_or_overlay_colours_or_mutate_the_theme():
    for theme, original in PALETTES.items():
        before = dict(original)
        for accent in ACCENT_PALETTES:
            changed = get_palette_tokens(theme, accent_palette=accent)
            for name in original:
                if name.startswith(("state.", "overlay.", "gallery.", "paper.")):
                    assert changed[name] == original[name], (theme, accent, name)
            assert original == before


def test_primary_and_checked_buttons_use_the_same_quiet_selection_tokens():
    for theme in PALETTES:
        t = get_palette_tokens(theme)
        qss = build_clinical_stylesheet(13, theme)
        for selector in ("QPushButton:default {", "QPushButton:checked, QToolButton:checked {"):
            block = qss.split(selector, 1)[1].split("}", 1)[0]
            assert f"background: {t['accent.tint']}" in block
            assert f"border-color: {t['accent.line']}" in block
            assert f"color: {t['accent.text']}" in block


def test_accent_selection_is_explicit_cache_safe_and_unknown_values_fall_back():
    original = get_palette_tokens("vscode_dark")
    assert get_palette_tokens("vscode_dark", accent_palette="unknown") == original
    blue = build_clinical_stylesheet(13, "vscode_dark", accent_palette="blue")
    teal = build_clinical_stylesheet(13, "vscode_dark", accent_palette="teal")
    assert blue != teal
    assert blue == build_clinical_stylesheet(13, "vscode_dark", accent_palette="blue")
    assert get_palette_tokens("vscode_dark") == original
