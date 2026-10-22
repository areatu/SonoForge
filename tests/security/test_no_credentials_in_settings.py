"""Verify no passwords/tokens/keys are stored in QSettings.

Ensures that sensitive credentials are persisted only via the OS keyring
and that log sanitization strips UIDs and paths.
"""

from __future__ import annotations

import sys
import types
from collections.abc import Iterator
from pathlib import Path

import pytest

pytestmark = pytest.mark.security

from echo_personal_tool.infrastructure import server_settings as ss
from echo_personal_tool.infrastructure.log_sanitizer import sanitize_path, sanitize_uid
from echo_personal_tool.infrastructure.server_settings import (
    ServerSettings,
    _purge_password_from_qsettings,
    _save_password_keyring,
    reset_server_settings,
    save_server_settings,
)


@pytest.fixture
def isolated_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    org = "sonoforge-test-security"
    app = "server-test-security"
    monkeypatch.setattr(ss, "_SETTINGS_ORG", org)
    monkeypatch.setattr(ss, "_SETTINGS_APP", app)
    from PySide6.QtCore import QSettings

    store = QSettings(org, app)
    store.clear()
    store.sync()
    yield
    store.clear()
    store.sync()


@pytest.fixture
def mock_keyring(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
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
    return stored


class TestPasswordNeverInQSettings:
    """Password must never be persisted in QSettings, only in keyring."""

    def test_save_settings_password_not_in_qsettings(
        self, isolated_settings: None, mock_keyring: dict[str, str]
    ) -> None:
        from PySide6.QtCore import QSettings

        settings = ServerSettings(
            username="testuser",
            password="supersecret123",
            auth_mode="basic",
        )
        save_server_settings(settings)
        store = QSettings("sonoforge-test-security", "server-test-security")
        assert store.value("password", None) is None

    def test_password_stored_in_keyring(self, isolated_settings: None, mock_keyring: dict[str, str]) -> None:
        settings = ServerSettings(
            username="testuser",
            password="supersecret123",
            auth_mode="basic",
        )
        save_server_settings(settings)
        assert "sonoforge:testuser" in mock_keyring
        assert mock_keyring["sonoforge:testuser"] == "supersecret123"

    def test_empty_password_deletes_from_keyring(self, isolated_settings: None, mock_keyring: dict[str, str]) -> None:
        _save_password_keyring("user1", "secret")
        _save_password_keyring("user1", "")
        assert "sonoforge:user1" not in mock_keyring

    def test_purge_removes_stale_password(self, isolated_settings: None, mock_keyring: dict[str, str]) -> None:
        from PySide6.QtCore import QSettings

        store = QSettings("sonoforge-test-security", "server-test-security")
        store.setValue("password", "leaked_password")
        store.sync()
        _purge_password_from_qsettings()
        assert store.value("password", None) is None

    def test_reset_clears_keyring_password(self, isolated_settings: None, mock_keyring: dict[str, str]) -> None:
        settings = ServerSettings(username="resetuser", password="oldpass")
        save_server_settings(settings)
        reset_server_settings()
        # After reset, keyring should have empty password for this user
        assert mock_keyring.get("sonoforge:resetuser", None) == "" or "sonoforge:resetuser" not in mock_keyring

    def test_no_token_or_api_key_fields_in_settings(self) -> None:
        """ServerSettings should not have token/api_key/secret fields."""
        import dataclasses

        field_names = {f.name for f in dataclasses.fields(ServerSettings)}
        sensitive_fields = {"token", "api_key", "api_secret", "secret_key", "access_token", "bearer_token"}
        leaked = field_names & sensitive_fields
        assert not leaked, f"Sensitive fields found in ServerSettings: {leaked}"


class TestLogSanitization:
    """Verify log sanitization utilities truncate sensitive data."""

    def test_sanitize_uid_truncates_long(self) -> None:
        uid = "1.2.840.113619.2.55.3.604688119.330.1426555527.469"
        result = sanitize_uid(uid)
        assert len(result) < len(uid)
        assert result.endswith("...")

    def test_sanitize_uid_short_keeps_full(self) -> None:
        uid = "1.2.3"
        assert sanitize_uid(uid) == uid

    def test_sanitize_uid_exact_boundary(self) -> None:
        uid = "1234567890123456"  # 16 chars
        assert sanitize_uid(uid) == uid

    def test_sanitize_uid_over_boundary(self) -> None:
        uid = "12345678901234567"  # 17 chars
        result = sanitize_uid(uid)
        assert len(result) == 19  # 16 + "..."
        assert result == "1234567890123456..."

    def test_sanitize_uid_custom_keep(self) -> None:
        uid = "1.2.840.113619.2.55.3.12345"
        result = sanitize_uid(uid, keep=8)
        assert result == "1.2.840...."
        assert len(result) == 11

    def test_sanitize_path_returns_filename_only(self) -> None:
        path = Path("/some/deep/path/to/Patient_Doe_John_12345.dcm")
        result = sanitize_path(path)
        assert result == "Patient_Doe_John_12345.dcm"
        assert "/" not in result

    def test_sanitize_path_no_parent_leak(self) -> None:
        path = Path("/dicom/studies/1.2.3/4.5.6/7.8.9/file.dcm")
        result = sanitize_path(path)
        assert result == "file.dcm"
        assert "1.2.3" not in result

    def test_sanitize_uid_empty_string(self) -> None:
        assert sanitize_uid("") == ""

    def test_sanitize_path_root(self) -> None:
        assert sanitize_path(Path("file.dcm")) == "file.dcm"
