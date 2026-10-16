"""Unit tests for the system colour scheme detection (UI-0, PR-1).

The theme "system" is resolved in one place now. Before, the palette and the
logo asked the system separately and disagreed: on Windows the palette was
inverted (``AppsUseLightTheme == 0`` means a *dark* system, and it produced
the light theme), on Linux the logo of the light theme was shown on the dark
interface.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import pytest


def _fake_winreg(apps_use_light_theme: int | None, *, fail: bool = False) -> types.ModuleType:
    """Build a fake ``winreg`` module with the Personalize key."""
    module = types.ModuleType("winreg")
    module.HKEY_CURRENT_USER = 0  # type: ignore[attr-defined]

    def _open_key(_root: object, _path: str) -> object:
        if fail:
            raise OSError("registry is not available")
        return object()

    def _query_value(_key: object, _name: str) -> tuple[int, int]:
        return (int(apps_use_light_theme or 0), 1)

    module.OpenKey = _open_key  # type: ignore[attr-defined]
    module.QueryValueEx = _query_value  # type: ignore[attr-defined]
    module.CloseKey = lambda _key: None  # type: ignore[attr-defined]
    return module


@pytest.fixture()
def _windows(monkeypatch):
    """Patch the platform to Windows and install a fake registry module."""

    def _install(apps_use_light_theme: int | None, *, fail: bool = False) -> None:
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setitem(sys.modules, "winreg", _fake_winreg(apps_use_light_theme, fail=fail))

    return _install


class TestWindowsSystemTheme:
    def test_dark_system_gives_the_dark_theme(self, _windows):
        """AppsUseLightTheme == 0 means a dark system — the inverted case."""
        from echo_personal_tool.presentation.theme.system_theme import system_theme_id

        _windows(0)
        assert system_theme_id() == "dark"

    def test_light_system_gives_the_light_theme(self, _windows):
        from echo_personal_tool.presentation.theme.system_theme import system_theme_id

        _windows(1)
        assert system_theme_id() == "light"

    def test_unreadable_registry_falls_back_to_dark(self, _windows):
        from echo_personal_tool.presentation.theme.system_theme import system_theme_id

        _windows(None, fail=True)
        assert system_theme_id() == "dark"

    def test_is_system_dark_follows_the_system(self, _windows):
        from echo_personal_tool.presentation.theme.system_theme import is_system_dark

        _windows(0)
        assert is_system_dark() is True
        _windows(1)
        assert is_system_dark() is False


class TestMacSystemTheme:
    def test_dark(self):
        from echo_personal_tool.presentation.theme.system_theme import system_theme_id

        result = MagicMock()
        result.stdout = "Dark\n"
        with (
            patch.object(sys, "platform", "darwin"),
            patch("subprocess.run", return_value=result),
        ):
            assert system_theme_id() == "dark"

    def test_light(self):
        from echo_personal_tool.presentation.theme.system_theme import system_theme_id

        result = MagicMock()
        result.stdout = "\n"
        with (
            patch.object(sys, "platform", "darwin"),
            patch("subprocess.run", return_value=result),
        ):
            assert system_theme_id() == "light"

    def test_failure_falls_back_to_dark(self):
        from echo_personal_tool.presentation.theme.system_theme import system_theme_id

        with (
            patch.object(sys, "platform", "darwin"),
            patch("subprocess.run", side_effect=Exception),
        ):
            assert system_theme_id() == "dark"


class TestOtherPlatforms:
    def test_linux_keeps_the_dark_theme(self):
        """The application keeps its dark theme on Linux, as before."""
        import os

        from echo_personal_tool.presentation.theme.system_theme import system_theme_id

        with patch.object(sys, "platform", "linux"), patch.dict(os.environ, {}, clear=True):
            assert system_theme_id() == "dark"

    def test_linux_keeps_the_dark_theme_with_a_dark_gtk_theme(self):
        import os

        from echo_personal_tool.presentation.theme.system_theme import system_theme_id

        with patch.object(sys, "platform", "linux"), patch.dict(os.environ, {"GTK_THEME": "Adwaita:dark"}):
            assert system_theme_id() == "dark"


class TestResolveThemeId:
    def test_known_ids_pass_through(self):
        from echo_personal_tool.presentation.theme.system_theme import resolve_theme_id

        for theme_id in ("dark", "light", "vscode_dark", "vscode_light", "graphite"):
            assert resolve_theme_id(theme_id) == theme_id

    def test_unknown_id_falls_back_to_dark(self):
        from echo_personal_tool.presentation.theme.system_theme import resolve_theme_id

        assert resolve_theme_id("nonexistent") == "dark"

    def test_system_follows_the_system(self, _windows):
        from echo_personal_tool.presentation.theme.system_theme import resolve_theme_id

        _windows(0)
        assert resolve_theme_id("system") == "dark"
        _windows(1)
        assert resolve_theme_id("system") == "light"
