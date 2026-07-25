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
