"""Master-password mode for the portable secret store must fail closed (#621).

The plaintext ``device.key`` is removed from the medium once a master
password is set; the device secret survives only as a scrypt-wrapped Fernet
token, and the unlocked secret lives in process memory only. A wrong password
never derives a fallback key.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from echo_personal_tool.infrastructure import master_password as mp
from echo_personal_tool.infrastructure import profile
from echo_personal_tool.infrastructure import server_settings as ss

pytestmark = pytest.mark.security

_ENV_VARS = (profile.PROFILE_ENV, profile.PORTABLE_ENV, profile.PORTABLE_DIR_ENV)


@pytest.fixture(autouse=True)
def portable_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    """Give every test its own stick and a locked session."""
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    root = tmp_path / "stick"
    monkeypatch.setenv(profile.PROFILE_ENV, "presenter")
    monkeypatch.setenv(profile.PORTABLE_DIR_ENV, str(root))
    ss._FERNET_CACHE.clear()
    mp.lock_master_password()
    yield root
    ss._FERNET_CACHE.clear()
    mp.lock_master_password()


def _save_and_load(username: str, password: str) -> str:
    ss._save_password_portable(username, password)
    return ss._load_password_portable(username)


class TestEnableAndUnlock:
    def test_set_master_password_removes_plaintext_device_key(self, portable_root: Path) -> None:
        assert not mp.master_password_enabled()
        mp.set_master_password("correct horse battery staple")
        assert mp.master_password_enabled()
        assert not (portable_root / "device.key").exists()
        assert (portable_root / "device.key.enc").is_file()
        assert (portable_root / "master.lock").is_file()

    def test_wrong_password_does_not_unlock_and_store_stays_closed(self, portable_root: Path) -> None:
        _save_and_load("orthanc", "s3cret")
        mp.set_master_password("right-password")
        mp.lock_master_password()
        assert mp.unlock_master_password("wrong-password") is False
        assert mp.session_device_secret() is None
        # fail closed: no fallback decryption, no password leak
        assert ss._load_password_portable("orthanc") == ""
        with pytest.raises(ss.PortableSecretStoreError) as excinfo:
            ss._encrypt_secret("new-secret")
        assert excinfo.value.code == "master_password_required"

    def test_unlock_restores_access_to_existing_secrets(self, portable_root: Path) -> None:
        assert _save_and_load("orthanc", "s3cret") == "s3cret"
        mp.set_master_password("right-password")
        mp.lock_master_password()
        assert mp.unlock_master_password("right-password") is True
        assert ss._load_password_portable("orthanc") == "s3cret"

    def test_lock_drops_the_in_memory_secret(self, portable_root: Path) -> None:
        mp.set_master_password("pw")
        assert mp.unlock_master_password("pw") is True
        mp.lock_master_password()
        assert mp.session_device_secret() is None
        with pytest.raises(ss.PortableSecretStoreError):
            ss._encrypt_secret("x")

    def test_double_enable_is_rejected(self, portable_root: Path) -> None:
        mp.set_master_password("pw")
        with pytest.raises(mp.MasterPasswordError) as excinfo:
            mp.set_master_password("pw2")
        assert excinfo.value.code == "already_enabled"

    def test_empty_password_is_rejected(self, portable_root: Path) -> None:
        with pytest.raises(mp.MasterPasswordError) as excinfo:
            mp.set_master_password("")
        assert excinfo.value.code == "empty_password"


class TestMigration:
    def test_existing_device_key_is_migrated_and_secrets_survive(self, portable_root: Path) -> None:
        # Legacy layout: plaintext device.key + encrypted token.
        assert _save_and_load("orthanc", "old-secret") == "old-secret"
        assert (portable_root / "device.key").exists()
        mp.set_master_password("master-pw")
        assert not (portable_root / "device.key").exists()
        # Same device secret → same Fernet key → old tokens still decrypt.
        assert mp.unlock_master_password("master-pw") is True
        assert ss._load_password_portable("orthanc") == "old-secret"

    def test_missing_key_with_secrets_is_not_migrated(self, portable_root: Path) -> None:
        _save_and_load("orthanc", "s3cret")
        (portable_root / "device.key").unlink()
        with pytest.raises(mp.MasterPasswordError) as excinfo:
            mp.set_master_password("master-pw")
        assert excinfo.value.code == "key_missing_with_secrets"
        assert not mp.master_password_enabled()


class TestChangePassword:
    def test_change_rewraps_and_old_password_stops_working(self, portable_root: Path) -> None:
        _save_and_load("orthanc", "s3cret")
        mp.set_master_password("old-pw")
        assert mp.change_master_password("old-pw", "new-pw") is True
        mp.lock_master_password()
        assert mp.unlock_master_password("old-pw") is False
        assert mp.unlock_master_password("new-pw") is True
        assert ss._load_password_portable("orthanc") == "s3cret"

    def test_change_with_wrong_old_password_leaves_store_untouched(self, portable_root: Path) -> None:
        mp.set_master_password("old-pw")
        assert mp.change_master_password("nope", "new-pw") is False
        mp.lock_master_password()
        assert mp.unlock_master_password("old-pw") is True


class TestFacade:
    def test_facade_maps_failures_to_stable_codes(self, portable_root: Path) -> None:
        from echo_personal_tool.application import master_password as facade

        assert facade.master_password_enabled() is False
        assert facade.set_master_password("pw") is None
        assert facade.master_password_enabled() is True
        assert facade.set_master_password("pw") == "already_enabled"
        mp.lock_master_password()
        assert facade.unlock_master_password("bad") == "wrong_password"
        assert facade.unlock_master_password("pw") is None
        assert facade.change_master_password("bad", "pw2") == "wrong_password"
        assert facade.change_master_password("pw", "pw2") is None
        facade.lock_master_password()
        assert mp.session_device_secret() is None
