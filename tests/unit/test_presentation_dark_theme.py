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
        from echo_personal_tool.presentation.dark_theme import _is_system_dark

        with patch.object(sys, "platform", "linux"), patch.dict(os.environ, {}, clear=True):
            assert _is_system_dark() is False

    def test_darwin_dark(self):
        from echo_personal_tool.presentation.dark_theme import _is_system_dark

        mock_result = MagicMock()
        mock_result.stdout = "Dark\n"
        with (
            patch.object(sys, "platform", "darwin"),
            patch("subprocess.run", return_value=mock_result),
        ):
            assert _is_system_dark() is True

    def test_darwin_exception_defaults_false(self):
        from echo_personal_tool.presentation.dark_theme import _is_system_dark

        with (
            patch.object(sys, "platform", "darwin"),
            patch("subprocess.run", side_effect=Exception),
        ):
            assert _is_system_dark() is False


class TestThemeMap:
    def test_all_modes_present(self):
        from echo_personal_tool.presentation.dark_theme import _THEME_MAP

        assert "dark" in _THEME_MAP
        assert "light" in _THEME_MAP
        assert "vscode_dark" in _THEME_MAP
        assert "vscode_light" in _THEME_MAP


def _fake_winreg(apps_use_light_theme: int | None) -> MagicMock:
    """``winreg`` stand-in; ``None`` makes the key unreadable."""
    fake = MagicMock()
    fake.HKEY_CURRENT_USER = object()
    if apps_use_light_theme is None:
        fake.OpenKey.side_effect = OSError("no key")
    else:
        fake.QueryValueEx.return_value = (apps_use_light_theme, 4)
    return fake


class TestSystemThemeWindows:
    """UI-0 (spec 2026-10-16 §2.1): ``system`` on Windows followed the inverse of the OS."""

    def test_dark_desktop_gives_dark_palette(self):
        from echo_personal_tool.presentation.dark_theme import _DARK, _resolve_theme

        fake = _fake_winreg(0)  # AppsUseLightTheme == 0 → dark apps
        with patch.object(sys, "platform", "win32"), patch.dict(sys.modules, {"winreg": fake}):
            assert _resolve_theme("system") is _DARK
        fake.CloseKey.assert_called_once()

    def test_light_desktop_gives_light_palette(self):
        from echo_personal_tool.presentation.dark_theme import _LIGHT, _resolve_theme

        with patch.object(sys, "platform", "win32"), patch.dict(sys.modules, {"winreg": _fake_winreg(1)}):
            assert _resolve_theme("system") is _LIGHT

    def test_unreadable_registry_defaults_dark(self):
        from echo_personal_tool.presentation.dark_theme import _DARK, _resolve_theme

        with patch.object(sys, "platform", "win32"), patch.dict(sys.modules, {"winreg": _fake_winreg(None)}):
            assert _resolve_theme("system") is _DARK

    def test_palette_and_logo_agree(self):
        from echo_personal_tool.presentation.dark_theme import _is_system_dark, _resolve_theme_id

        for value, dark in ((0, True), (1, False)):
            with patch.object(sys, "platform", "win32"), patch.dict(sys.modules, {"winreg": _fake_winreg(value)}):
                assert _is_system_dark() is dark
                assert (_resolve_theme_id("system") == "dark") is dark

    def test_stylesheet_follows_system_on_each_call(self):
        from echo_personal_tool.presentation.dark_theme import build_clinical_stylesheet

        with patch.object(sys, "platform", "win32"), patch.dict(sys.modules, {"winreg": _fake_winreg(0)}):
            dark_css = build_clinical_stylesheet(13, theme="system")
        with patch.object(sys, "platform", "win32"), patch.dict(sys.modules, {"winreg": _fake_winreg(1)}):
            light_css = build_clinical_stylesheet(13, theme="system")
        assert dark_css == build_clinical_stylesheet(13, theme="dark")
        assert light_css == build_clinical_stylesheet(13, theme="light")


class TestStylesheetFromTokens:
    """UI-0 gate: the token-built QSS is identical to the pre-token one."""

    # sha256 of build_clinical_stylesheet(13, theme=…) before UI-0 (327e5290),
    # with the absolute icon directory replaced by "<ICONS>".  A later PR that
    # changes the stylesheet on purpose updates these hashes in the same PR.
    _PRE_TOKEN_QSS_SHA256 = {
        "dark": "02a5df7156c941342aece8b3e01642bbdd1e66fd3c7d4b49e9eba2d382b4f280",
        "light": "d64ffe03ebc2c75e8e79d53d6807d1b98c227e1f3324396cc22a9b1058d1da8f",
        "vscode_dark": "e5aae705928ae060ebd9d3aa44633e996ac0738b9ca6a4f1d57fbe22905a6986",
        "vscode_light": "55a01546e4bbfc351a7822becaebde31e257145e88e7772ae96047988ebead70",
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
        from echo_personal_tool.presentation.theme_tokens import THEME_IDS, tokens_for

        for theme in THEME_IDS:
            allowed = {value.lower() for value in tokens_for(theme).values()}
            used = {m.lower() for m in re.findall(r"#[0-9a-fA-F]{3,8}\b", build_clinical_stylesheet(13, theme=theme))}
            assert used <= allowed, f"{theme}: {sorted(used - allowed)}"

    def test_qss_is_cached_per_theme_and_font(self):
        from echo_personal_tool.presentation.dark_theme import build_clinical_stylesheet

        assert build_clinical_stylesheet(13, theme="dark") is build_clinical_stylesheet(13, theme="dark")
        assert build_clinical_stylesheet(14, theme="dark") != build_clinical_stylesheet(13, theme="dark")
