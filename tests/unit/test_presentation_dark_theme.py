"""Unit tests for presentation/dark_theme.py."""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def _setup_qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class TestResolveTheme:
    def test_dark_returns_dark_palette(self):
        from echo_personal_tool.presentation.dark_theme import _DARK, _resolve_theme

        assert _resolve_theme("dark") is _DARK

    def test_light_returns_light_palette(self):
        from echo_personal_tool.presentation.dark_theme import _LIGHT, _resolve_theme

        assert _resolve_theme("light") is _LIGHT

    def test_vscode_dark_returns_correct_palette(self):
        from echo_personal_tool.presentation.dark_theme import _VS_CODE_DARK, _resolve_theme

        assert _resolve_theme("vscode_dark") is _VS_CODE_DARK

    def test_vscode_light_returns_correct_palette(self):
        from echo_personal_tool.presentation.dark_theme import _VS_CODE_LIGHT, _resolve_theme

        assert _resolve_theme("vscode_light") is _VS_CODE_LIGHT

    def test_unknown_mode_defaults_to_dark(self):
        from echo_personal_tool.presentation.dark_theme import _DARK, _resolve_theme

        assert _resolve_theme("nonexistent") is _DARK

    def test_system_mode_linux_defaults_dark(self):
        from echo_personal_tool.presentation.dark_theme import _DARK, _resolve_theme

        with patch.object(sys, "platform", "linux"), patch.dict(os.environ, {}, clear=True):
            assert _resolve_theme("system") is _DARK

    def test_system_mode_linux_dark_gtk(self):
        from echo_personal_tool.presentation.dark_theme import _DARK, _resolve_theme

        with patch.object(sys, "platform", "linux"), patch.dict(os.environ, {"GTK_THEME": "Adwaita:dark"}):
            assert _resolve_theme("system") is _DARK

    def test_system_mode_darwin_dark(self):
        from echo_personal_tool.presentation.dark_theme import _DARK, _resolve_theme

        mock_result = MagicMock()
        mock_result.stdout = "Dark\n"
        with (
            patch.object(sys, "platform", "darwin"),
            patch("subprocess.run", return_value=mock_result),
        ):
            assert _resolve_theme("system") is _DARK

    def test_system_mode_darwin_light(self):
        from echo_personal_tool.presentation.dark_theme import _LIGHT, _resolve_theme

        mock_result = MagicMock()
        mock_result.stdout = "\n"
        with (
            patch.object(sys, "platform", "darwin"),
            patch("subprocess.run", return_value=mock_result),
        ):
            assert _resolve_theme("system") is _LIGHT

    def test_system_mode_darwin_exception(self):
        from echo_personal_tool.presentation.dark_theme import _DARK, _resolve_theme

        with (
            patch.object(sys, "platform", "darwin"),
            patch("subprocess.run", side_effect=Exception),
        ):
            assert _resolve_theme("system") is _DARK


class TestGetThemePalette:
    def test_returns_dict(self):
        from echo_personal_tool.presentation.dark_theme import get_theme_palette

        palette = get_theme_palette()
        assert isinstance(palette, dict)
        assert "bg_dark" in palette
        assert "text" in palette

    def test_contains_required_keys(self):
        from echo_personal_tool.presentation.dark_theme import get_theme_palette

        palette = get_theme_palette()
        required = {"bg_dark", "bg_panel", "bg_control", "text", "accent", "border"}
        assert required.issubset(set(palette.keys()))

    def test_all_values_are_hex_strings(self):
        from echo_personal_tool.presentation.dark_theme import get_theme_palette

        palette = get_theme_palette()
        for key, val in palette.items():
            assert isinstance(val, str), f"{key} is not a string"
            assert val.startswith("#"), f"{key} value {val} doesn't start with #"


class TestGetThemeTokens:
    """The migration entry point of UI-0 PR-3: roles of the active theme.

    The shell (system bar, tab strip, activity rail, status bar) switched from
    the legacy palette keys to the tokens; ``get_theme_tokens()`` is what it
    asks, so the facade has to answer with the tokens of the *active* theme and
    with a copy the caller cannot spoil.
    """

    def test_dark_theme_tokens_match_the_palette_package(self, monkeypatch):
        # The mode is process-global and some tests apply a theme for real
        # (``apply_clinical_theme``); pin it so the case cannot inherit the
        # theme of whichever file ran before it in the CI GUI shard.
        from echo_personal_tool.presentation import dark_theme
        from echo_personal_tool.presentation.dark_theme import get_theme_tokens
        from echo_personal_tool.presentation.theme.palettes import get_palette_tokens

        monkeypatch.setattr(dark_theme, "_current_theme_mode", "dark")

        assert get_theme_tokens() == get_palette_tokens("dark")

    def test_tokens_follow_the_active_theme(self, monkeypatch):
        from echo_personal_tool.presentation import dark_theme
        from echo_personal_tool.presentation.theme.palettes import PALETTES

        monkeypatch.setattr(dark_theme, "_current_theme_mode", "graphite")

        assert dark_theme.get_theme_tokens()["accent"] == PALETTES["graphite"]["accent"]

    def test_system_mode_resolves_like_the_palette(self, monkeypatch):
        from echo_personal_tool.presentation import dark_theme
        from echo_personal_tool.presentation.theme.palettes import get_palette_tokens

        monkeypatch.setattr(dark_theme, "_current_theme_mode", "system")
        with patch.object(sys, "platform", "linux"):
            assert dark_theme.get_theme_tokens() == get_palette_tokens("dark")

    def test_tokens_are_a_copy(self):
        from echo_personal_tool.presentation.dark_theme import get_theme_tokens

        tokens = get_theme_tokens()
        tokens["text.1"] = "#000000"

        assert get_theme_tokens()["text.1"] != "#000000"

    def test_tokens_are_roles_not_legacy_keys(self):
        from echo_personal_tool.presentation.dark_theme import get_theme_tokens
        from echo_personal_tool.presentation.theme.tokens import TOKEN_NAMES

        tokens = get_theme_tokens()

        assert "bg_dark" not in tokens
        assert set(tokens) <= set(TOKEN_NAMES)

    def test_every_required_token_has_a_value(self):
        from echo_personal_tool.presentation.dark_theme import get_theme_tokens
        from echo_personal_tool.presentation.theme.tokens import REQUIRED_TOKEN_NAMES

        tokens = get_theme_tokens()

        assert set(REQUIRED_TOKEN_NAMES) <= set(tokens)


class TestBuildClinicalStylesheet:
    def test_returns_nonempty_string(self):
        from echo_personal_tool.presentation.dark_theme import build_clinical_stylesheet

        css = build_clinical_stylesheet()
        assert isinstance(css, str)
        assert len(css) > 100

    def test_font_size_appears_in_css(self):
        from echo_personal_tool.presentation.dark_theme import build_clinical_stylesheet

        css = build_clinical_stylesheet(font_size=15)
        assert "15px" in css

    def test_each_theme_produces_css(self):
        from echo_personal_tool.presentation.dark_theme import build_clinical_stylesheet

        for mode in ("dark", "light", "vscode_dark", "vscode_light"):
            css = build_clinical_stylesheet(theme=mode)
            assert len(css) > 100, f"Theme {mode} produced empty CSS"


class TestModuleConstants:
    def test_bg_dark_matches_dark_palette(self):
        from echo_personal_tool.presentation.dark_theme import _DARK, BG_DARK

        assert BG_DARK == _DARK["bg_dark"]

    def test_text_matches_dark_palette(self):
        from echo_personal_tool.presentation.dark_theme import _DARK, TEXT

        assert TEXT == _DARK["text"]

    def test_accent_matches_dark_palette(self):
        from echo_personal_tool.presentation.dark_theme import _DARK, ACCENT

        assert ACCENT == _DARK["accent"]

    def test_border_matches_dark_palette(self):
        from echo_personal_tool.presentation.dark_theme import _DARK, BORDER

        assert BORDER == _DARK["border"]


class TestApplyClinicalTheme:
    def test_no_app_instance_returns_early(self):
        from echo_personal_tool.presentation.dark_theme import apply_clinical_theme

        with patch("echo_personal_tool.presentation.dark_theme.QApplication.instance", return_value=None):
            apply_clinical_theme()

    def test_direct_apply_sets_stylesheet(self):
        from echo_personal_tool.presentation.dark_theme import apply_clinical_theme

        mock_app = MagicMock()
        with patch("echo_personal_tool.presentation.dark_theme.QApplication.instance", return_value=mock_app):
            apply_clinical_theme(widget=None, animate=False)
        mock_app.setStyleSheet.assert_called_once()

    def test_direct_apply_with_widget(self):
        from echo_personal_tool.presentation.dark_theme import apply_clinical_theme

        mock_app = MagicMock()
        mock_widget = MagicMock()
        with patch("echo_personal_tool.presentation.dark_theme.QApplication.instance", return_value=mock_app):
            apply_clinical_theme(widget=mock_widget, animate=False)
        mock_app.setStyleSheet.assert_called_once()
        mock_widget.setPalette.assert_called_once()

    def test_animate_with_widget(self):
        from echo_personal_tool.presentation.dark_theme import apply_clinical_theme

        mock_app = MagicMock()
        mock_widget = MagicMock()
        with (
            patch("echo_personal_tool.presentation.dark_theme.QApplication.instance", return_value=mock_app),
            patch("echo_personal_tool.presentation.dark_theme._fade_theme_transition") as mock_fade,
        ):
            apply_clinical_theme(widget=mock_widget, animate=True, font_size=14, theme="light")
            mock_fade.assert_called_once_with(mock_widget, 14, "light")


class TestGetLogoPath:
    def test_returns_path(self):
        from pathlib import Path

        from echo_personal_tool.presentation.dark_theme import get_logo_path

        path = get_logo_path()
        assert isinstance(path, Path)


class TestIsSystemDark:
    def test_linux_gtk_dark(self):
        from echo_personal_tool.presentation.dark_theme import _is_system_dark

        with patch.object(sys, "platform", "linux"), patch.dict(os.environ, {"GTK_THEME": "Adwaita:dark"}):
            assert _is_system_dark() is True

    def test_linux_no_gtk(self):
        """The application keeps its dark theme on Linux — the logo must match."""
        from echo_personal_tool.presentation.dark_theme import _is_system_dark

        with patch.object(sys, "platform", "linux"), patch.dict(os.environ, {}, clear=True):
            assert _is_system_dark() is True

    def test_darwin_dark(self):
        from echo_personal_tool.presentation.dark_theme import _is_system_dark

        mock_result = MagicMock()
        mock_result.stdout = "Dark\n"
        with (
            patch.object(sys, "platform", "darwin"),
            patch("subprocess.run", return_value=mock_result),
        ):
            assert _is_system_dark() is True

    def test_darwin_exception_defaults_true(self):
        """macOS cannot be asked — the dark theme is the fallback."""
        from echo_personal_tool.presentation.dark_theme import _is_system_dark

        with (
            patch.object(sys, "platform", "darwin"),
            patch("subprocess.run", side_effect=Exception),
        ):
            assert _is_system_dark() is True


class TestSystemThemeOnWindows:
    """The regression of the inverted system theme (UI-0, PR-1).

    ``AppsUseLightTheme == 0`` means that the *applications* of Windows are
    dark — the value used to be read the other way round, so a user with a
    dark Windows got a light interface.
    """

    @staticmethod
    def _fake_winreg(apps_use_light_theme: int | None) -> object:
        """A ``winreg`` stand-in; ``None`` makes the key unreadable."""
        import types

        module = types.ModuleType("winreg")
        module.HKEY_CURRENT_USER = 0  # type: ignore[attr-defined]
        if apps_use_light_theme is None:

            def _fail(_root: object, _path: str) -> object:
                raise OSError("no such key")

            module.OpenKey = _fail  # type: ignore[attr-defined]
        else:
            module.OpenKey = lambda _root, _path: object()  # type: ignore[attr-defined]
            module.QueryValueEx = lambda _key, _name: (apps_use_light_theme, 1)  # type: ignore[attr-defined]
        module.CloseKey = lambda _key: None  # type: ignore[attr-defined]
        return module

    def test_dark_system_gives_the_dark_palette(self):
        """AppsUseLightTheme == 0 means a dark system (it used to be inverted)."""
        from echo_personal_tool.presentation.dark_theme import _DARK, _resolve_theme

        with (
            patch.object(sys, "platform", "win32"),
            patch.dict(sys.modules, {"winreg": self._fake_winreg(0)}),
        ):
            assert _resolve_theme("system") is _DARK

    def test_light_system_gives_the_light_palette(self):
        from echo_personal_tool.presentation.dark_theme import _LIGHT, _resolve_theme

        with (
            patch.object(sys, "platform", "win32"),
            patch.dict(sys.modules, {"winreg": self._fake_winreg(1)}),
        ):
            assert _resolve_theme("system") is _LIGHT

    def test_unreadable_registry_defaults_dark(self):
        """A policy or an old Windows must not break the theme."""
        from echo_personal_tool.presentation.dark_theme import _DARK, _resolve_theme

        with (
            patch.object(sys, "platform", "win32"),
            patch.dict(sys.modules, {"winreg": self._fake_winreg(None)}),
        ):
            assert _resolve_theme("system") is _DARK

    def test_palette_and_logo_agree(self):
        """The palette and the logo must answer the same question."""
        from echo_personal_tool.presentation.dark_theme import _is_system_dark, _resolve_theme_id

        for value, dark in ((0, True), (1, False)):
            with (
                patch.object(sys, "platform", "win32"),
                patch.dict(sys.modules, {"winreg": self._fake_winreg(value)}),
            ):
                assert _is_system_dark() is dark
                assert (_resolve_theme_id("system") == "dark") is dark

    def test_stylesheet_follows_the_system_on_every_call(self):
        """The system may change while the application runs."""
        from echo_personal_tool.presentation.dark_theme import build_clinical_stylesheet

        with (
            patch.object(sys, "platform", "win32"),
            patch.dict(sys.modules, {"winreg": self._fake_winreg(0)}),
        ):
            dark_css = build_clinical_stylesheet(13, theme="system")
        with (
            patch.object(sys, "platform", "win32"),
            patch.dict(sys.modules, {"winreg": self._fake_winreg(1)}),
        ):
            light_css = build_clinical_stylesheet(13, theme="system")
        assert dark_css == build_clinical_stylesheet(13, theme="dark")
        assert light_css == build_clinical_stylesheet(13, theme="light")


class TestThemeMap:
    def test_all_modes_present(self):
        from echo_personal_tool.presentation.dark_theme import _THEME_MAP

        assert "dark" in _THEME_MAP
        assert "light" in _THEME_MAP
        assert "vscode_dark" in _THEME_MAP
        assert "vscode_light" in _THEME_MAP


class TestStylesheetFromTokens:
    """UI-0 gate: the token-built stylesheet is the one of the previous release."""

    # sha256 of build_clinical_stylesheet(13, theme=…), with the absolute icon
    # directory replaced by "<ICONS>".
    #
    # UI-0 introduced these pins as «the token-built sheet is byte-identical to
    # the one of the previous release».  The UI-acceptance round of 2026-10-23
    # changed the sheet on purpose — the flat system-action row with hairline
    # separators, the segment control, the muted «Сброс», rounded tab pills and
    # the icon-box gap — so the pins were re-taken from that revision.  The
    # ui-redesign button round (accent.tint checked state, filled default
    # button, radius 6) retook them again on purpose; from now on a diff here
    # means an unintended restyle of the whole application.  The 2026-10-25
    # round added one global rule — captions (``QLabel``) paint no background —
    # to stop the grey stripes over hovered measurement rows, so the pins were
    # re-taken from that revision.
    # 2026-10-26: compact metric controls and quiet tint/outline/text selected
    # states intentionally update these pins together with the QSS goldens.
    _PRE_TOKEN_QSS_SHA256 = {
        "dark": "5425f4c0250cd216112344b019cb2fbaee01e7c1400476b611897d9c9a7d8522",
        "light": "44aa5c15972d9c3cb789bb39e674e3b3693c1d193ef0bc36d901881929697fcf",
        "vscode_dark": "cbc82e108b71f50e829df7e5a61570226c6f2ec11c16b1bdc61f9ea23cfb5948",
        "vscode_light": "e16c526c30660fb7474dbd807434113a4a67663430b7b4923dbf9eb98c67be7e",
    }

    @pytest.mark.parametrize("theme", sorted(_PRE_TOKEN_QSS_SHA256))
    def test_qss_unchanged(self, theme):
        import hashlib
        from pathlib import Path

        from echo_personal_tool.presentation import dark_theme

        icons = (Path(dark_theme.__file__).resolve().parent.parent / "resources" / "icons").as_posix()
        css = dark_theme.build_clinical_stylesheet(13, theme=theme).replace(icons, "<ICONS>")
        assert hashlib.sha256(css.encode()).hexdigest() == self._PRE_TOKEN_QSS_SHA256[theme]

    def test_qss_uses_only_token_colours(self):
        import re

        from echo_personal_tool.presentation.dark_theme import build_clinical_stylesheet
        from echo_personal_tool.presentation.theme.palettes import THEME_IDS, get_palette_tokens

        for theme in THEME_IDS:
            allowed = {value.lower() for value in get_palette_tokens(theme).values()}
            used = {m.lower() for m in re.findall(r"#[0-9a-fA-F]{3,8}\b", build_clinical_stylesheet(13, theme=theme))}
            assert used <= allowed, f"{theme}: {sorted(used - allowed)}"

    def test_qss_is_cached_per_theme_and_font(self):
        from echo_personal_tool.presentation.dark_theme import build_clinical_stylesheet

        assert build_clinical_stylesheet(13, theme="dark") is build_clinical_stylesheet(13, theme="dark")
        assert build_clinical_stylesheet(14, theme="dark") != build_clinical_stylesheet(13, theme="dark")
