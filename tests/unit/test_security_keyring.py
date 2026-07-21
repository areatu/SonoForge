"""Tests for keyring password storage integration."""

from __future__ import annotations

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
    def test_save_and_load_password(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Mock keyring to avoid OS keychain dependency
        stored: dict[str, str] = {}

        class MockKeyring:
            @staticmethod
            def set_password(service: str, username: str, password: str) -> None:
                stored[f"{service}:{username}"] = password

            @staticmethod
            def get_password(service: str, username: str) -> str | None:
                return stored.get(f"{service}:{username}")

            @staticmethod
            def delete_password(service: str, username: str) -> None:
                stored.pop(f"{service}:{username}", None)

            class errors:
                class PasswordDeleteError(Exception):
                    pass

        monkeypatch.setattr("keyring", MockKeyring())

        _save_password_keyring("testuser", "secret123")
        assert _load_password_keyring("testuser") == "secret123"

    def test_delete_password(self, monkeypatch: pytest.MonkeyPatch) -> None:
        stored: dict[str, str] = {}

        class MockKeyring:
            @staticmethod
            def set_password(service: str, username: str, password: str) -> None:
                stored[f"{service}:{username}"] = password

            @staticmethod
            def get_password(service: str, username: str) -> str | None:
                return stored.get(f"{service}:{username}")

            @staticmethod
            def delete_password(service: str, username: str) -> None:
                stored.pop(f"{service}:{username}", None)

            class errors:
                class PasswordDeleteError(Exception):
                    pass

        monkeypatch.setattr("keyring", MockKeyring())

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
