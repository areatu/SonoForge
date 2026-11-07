"""Portable credential storage must fail closed when ``device.key`` is unusable.

The older behaviour derived the Fernet key from a fixed application constant
whenever the device key could not be read or created, silently weakening the
store (and keeping it usable on read-only media). These tests pin the opposite
contract: no fallback secret, no plaintext token, no host-keychain fallback,
no overwrite of an existing token, and a visible, stable failure code.
"""

from __future__ import annotations

import logging
import os
import sys
import types
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from echo_personal_tool.infrastructure import profile
from echo_personal_tool.infrastructure import server_settings as ss

pytestmark = pytest.mark.security

_ENV_VARS = (profile.PROFILE_ENV, profile.PORTABLE_ENV, profile.PORTABLE_DIR_ENV)


@pytest.fixture(autouse=True)
def portable_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    """Give every test its own stick and an empty key cache."""
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    root = tmp_path / "stick"
    monkeypatch.setenv(profile.PROFILE_ENV, "presenter")
    monkeypatch.setenv(profile.PORTABLE_DIR_ENV, str(root))
    ss._FERNET_CACHE.clear()
    yield root
    ss._FERNET_CACHE.clear()


def _keyring_spy(monkeypatch: pytest.MonkeyPatch) -> list[tuple[object, ...]]:
    """Replace the OS keychain with a spy that records any attempted write."""
    calls: list[tuple[object, ...]] = []
    module = types.ModuleType("keyring")

    def set_password(*args: object) -> None:
        calls.append(args)

    setattr(module, "set_password", set_password)
    monkeypatch.setitem(sys.modules, "keyring", module)
    return calls


class TestDeviceKey:
    def test_key_is_random_and_there_is_no_fallback_constant(self, portable_root: Path) -> None:
        assert not hasattr(ss, "_PORTABLE_DEVICE_SECRET_FALLBACK")
        raw = ss._portable_device_secret()
        key_file = portable_root / "device.key"
        assert len(raw) == 32
        assert key_file.is_file()
        assert key_file.read_text(encoding="ascii").strip() == raw.hex()
        if os.name == "posix":
            assert key_file.stat().st_mode & 0o777 == 0o600

    def test_parallel_first_start_publishes_one_key(self, portable_root: Path) -> None:
        with ThreadPoolExecutor(max_workers=8) as pool:
            secrets = list(pool.map(lambda _: ss._portable_device_secret(), range(24)))
        assert len({secret.hex() for secret in secrets}) == 1
        assert (portable_root / "device.key").is_file()
        assert not list(portable_root.glob(".device.key.*.tmp"))

    def test_corrupt_key_is_not_regenerated(self, portable_root: Path) -> None:
        portable_root.mkdir(parents=True, exist_ok=True)
        key_file = portable_root / "device.key"
        key_file.write_text("not-a-key\n", encoding="ascii")
        with pytest.raises(ss.PortableSecretStoreError) as excinfo:
            ss._portable_device_secret()
        assert excinfo.value.code == "key_invalid"
        assert key_file.read_text(encoding="ascii") == "not-a-key\n"


class TestFailClosedWrites:
    def test_read_only_media_does_not_fall_back(
        self,
        portable_root: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        portable_root.mkdir(parents=True, exist_ok=True)
        keyring_calls = _keyring_spy(monkeypatch)
        secret = "portable-secret-should-never-be-written"
        portable_root.chmod(0o500)
        try:
            with caplog.at_level(logging.WARNING):
                status = ss.save_server_settings(ss.ServerSettings(username="demo", password=secret))
        finally:
            portable_root.chmod(0o700)

        assert status.saved is False
        assert status.error_code in {
            "key_write_failed",
            "key_unreadable",
            "secrets_store_unreadable",
        }
        assert keyring_calls == [], "portable failure must not switch to the host keychain"
        assert "password NOT saved" in caplog.text
        assert status.error_code in caplog.text
        assert secret not in caplog.text
        for path in portable_root.iterdir():
            if path.is_file():
                assert secret not in path.read_text(encoding="utf-8", errors="replace")

    def test_corrupt_key_leaves_previous_ciphertext_untouched(self, portable_root: Path) -> None:
        first = ss.save_server_settings(ss.ServerSettings(username="demo", password="old-password"))
        assert first.saved is True
        secrets_file = portable_root / "secrets.ini"
        original_token = secrets_file.read_text(encoding="utf-8")
        original_key = (portable_root / "device.key").read_bytes()

        (portable_root / "device.key").write_text("deadbeef", encoding="ascii")
        ss._FERNET_CACHE.clear()
        second = ss.save_server_settings(ss.ServerSettings(username="demo", password="new-password"))

        assert second.saved is False
        assert second.error_code == "key_invalid"
        assert secrets_file.read_text(encoding="utf-8") == original_token
        assert "new-password" not in secrets_file.read_text(encoding="utf-8")

        (portable_root / "device.key").write_bytes(original_key)
        ss._FERNET_CACHE.clear()
        assert ss.load_server_settings().password == "old-password"

    def test_wrong_key_returns_no_password_and_no_plaintext(
        self, portable_root: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        assert ss.save_server_settings(ss.ServerSettings(username="demo", password="old-password")).saved
        (portable_root / "device.key").write_text("0" * 64, encoding="ascii")
        ss._FERNET_CACHE.clear()
        with caplog.at_level(logging.WARNING):
            loaded = ss.load_server_settings()
        assert loaded.password == ""
        assert "old-password" not in caplog.text
        assert "re-enter" in caplog.text

    def test_missing_key_with_existing_tokens_is_not_recreated(self, portable_root: Path) -> None:
        assert ss.save_server_settings(ss.ServerSettings(username="demo", password="old-password")).saved
        key_file = portable_root / "device.key"
        secrets_file = portable_root / "secrets.ini"
        original_token = secrets_file.read_text(encoding="utf-8")
        key_file.unlink()
        ss._FERNET_CACHE.clear()

        second = ss.save_server_settings(ss.ServerSettings(username="demo", password="new-password"))
        assert second.saved is False
        assert second.error_code == "key_missing_with_secrets"
        assert not key_file.exists(), "a new key would orphan the stored ciphertext"
        assert secrets_file.read_text(encoding="utf-8") == original_token
        assert "new-password" not in secrets_file.read_text(encoding="utf-8")
        assert ss.load_server_settings().password == ""

    def test_cached_fernet_cannot_outlive_the_device_key(self, portable_root: Path) -> None:
        assert ss.save_server_settings(ss.ServerSettings(username="demo", password="old-password")).saved
        assert ss._FERNET_CACHE, "the first write derives and caches a Fernet"
        (portable_root / "device.key").unlink()
        portable_root.chmod(0o500)
        try:
            second = ss.save_server_settings(ss.ServerSettings(username="demo", password="new-password"))
        finally:
            portable_root.chmod(0o700)

        assert second.saved is False, "a deleted key must invalidate the cached Fernet"
        assert "new-password" not in (portable_root / "secrets.ini").read_text(encoding="utf-8")

    def test_legacy_inline_password_is_kept_for_reentry(self, portable_root: Path) -> None:
        portable_root.mkdir(parents=True, exist_ok=True)
        store = profile.qsettings_for(ss._SETTINGS_ORG, ss._SETTINGS_APP)
        store.setValue("username", "legacy-user")
        store.setValue("password", "legacy-inline-secret")
        store.sync()
        (portable_root / "device.key").write_text("broken", encoding="ascii")
        ss._FERNET_CACHE.clear()

        loaded = ss.load_server_settings()
        assert loaded.password == ""
        reloaded = profile.qsettings_for(ss._SETTINGS_ORG, ss._SETTINGS_APP)
        assert str(reloaded.value("password", "")) == "legacy-inline-secret"

        (portable_root / "device.key").unlink()
        ss._FERNET_CACHE.clear()
        saved = ss.save_server_settings(ss.ServerSettings(username="legacy-user", password="fresh-secret"))
        assert saved.saved is True
        assert ss.load_server_settings().password == "fresh-secret"
        assert not profile.qsettings_for(ss._SETTINGS_ORG, ss._SETTINGS_APP).contains("password")


class TestStatusContract:
    def test_non_portable_keychain_failure_is_reported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ss, "_portable_secrets_file", lambda: None)
        # A keyring module without the write API simulates an unusable backend.
        monkeypatch.setitem(sys.modules, "keyring", types.ModuleType("keyring"))
        status = ss._save_password_keyring("user", "secret")
        assert status.saved is False
        assert status.error_code == "keychain_unavailable"
