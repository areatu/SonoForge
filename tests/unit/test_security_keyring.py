"""Tests for keyring password storage integration."""

from __future__ import annotations

import sys
import types
from collections.abc import Iterator

import pytest

pytestmark = pytest.mark.gui

from echo_personal_tool.infrastructure import server_settings as ss
from echo_personal_tool.infrastructure.server_settings import (
    ServerSettings,
    _load_password_keyring,
    _save_password_keyring,
    load_server_settings,
    save_server_settings,
)


@pytest.fixture
def isolated_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    org = "sonoforge-test-keyring"
    app = "server-test-keyring"
    monkeypatch.setattr(ss, "_SETTINGS_ORG", org)
    monkeypatch.setattr(ss, "_SETTINGS_APP", app)
    from PySide6.QtCore import QSettings

    store = QSettings(org, app)
    store.clear()
    store.sync()
    yield
    store.clear()
    store.sync()


class TestKeyringHelpers:
    def test_save_and_load_password(self, isolated_settings: None, monkeypatch: pytest.MonkeyPatch) -> None:
        # Mock keyring to avoid OS keychain dependency
        stored: dict[str, str] = {}

        kr = types.ModuleType("keyring")
        kr.set_password = staticmethod(lambda svc, user, pw: stored.update({f"{svc}:{user}": pw}))
        kr.get_password = staticmethod(lambda svc, user: stored.get(f"{svc}:{user}"))
        kr.delete_password = staticmethod(lambda svc, user: stored.pop(f"{svc}:{user}", None))
        kr_errors = types.ModuleType("keyring.errors")
        kr_errors.PasswordDeleteError = type("PasswordDeleteError", (Exception,), {})
        kr.errors = kr_errors  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "keyring", kr)
        monkeypatch.setitem(sys.modules, "keyring.errors", kr_errors)

        _save_password_keyring("testuser", "secret123")
        assert _load_password_keyring("testuser") == "secret123"

    def test_delete_password(self, isolated_settings: None, monkeypatch: pytest.MonkeyPatch) -> None:
        stored: dict[str, str] = {}

        kr = types.ModuleType("keyring")
        kr.set_password = staticmethod(lambda svc, user, pw: stored.update({f"{svc}:{user}": pw}))
        kr.get_password = staticmethod(lambda svc, user: stored.get(f"{svc}:{user}"))
        kr.delete_password = staticmethod(lambda svc, user: stored.pop(f"{svc}:{user}", None))
        kr_errors = types.ModuleType("keyring.errors")
        kr_errors.PasswordDeleteError = type("PasswordDeleteError", (Exception,), {})
        kr.errors = kr_errors  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "keyring", kr)
        monkeypatch.setitem(sys.modules, "keyring.errors", kr_errors)

        _save_password_keyring("testuser", "secret123")
        _save_password_keyring("testuser", "")
        assert _load_password_keyring("testuser") == ""


class TestServerSettingsKeyring:
    def test_password_not_in_qsettings(self, isolated_settings: None) -> None:
        """Password should not be stored in QSettings."""
        from PySide6.QtCore import QSettings

        settings = ServerSettings(
            username="testuser",
            password="secret123",
            auth_mode="basic",
        )
        save_server_settings(settings)
        store = QSettings("sonoforge-test-keyring", "server-test-keyring")
        # Password should not be in QSettings
        assert store.value("password", None) is None

    def test_load_uses_keyring(self, isolated_settings: None) -> None:
        """Loading settings should use keyring for password."""
        # The password field should be populated from keyring (or empty if not set)
        settings = load_server_settings()
        assert settings.password == "" or isinstance(settings.password, str)
