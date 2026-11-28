"""At-rest encryption of the Z2-M store: envelope, key sources, migration (#331).

Synthetic-only: every key comes from fakes or injected secrets, every record
from the empty ``StudyMeasurementData()`` payload.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from echo_personal_tool.application.study_measurement_session import StudyMeasurementData
from echo_personal_tool.infrastructure.measurement_codec import (
    MeasurementStorageError,
    study_key,
)
from echo_personal_tool.infrastructure.measurement_repository import MeasurementRepository
from echo_personal_tool.infrastructure.measurements_encryption import (
    ENVELOPE_FORMAT,
    KEY_SERVICE,
    KEY_USERNAME,
    VAULT_KEY_AAD,
    VAULT_KEY_NAME,
    MeasurementsCipher,
    is_encrypted_envelope,
    key_id_for,
    load_or_create_cipher,
)

UID = "1.2.3"
SOP = "1.2.3.4"
SOURCES = {SOP: {"fingerprint": "a" * 64, "frames": 5, "spacing": [0.5, 0.6]}}


class _FakeKeyring:
    """In-memory stand-in for the OS keychain backend."""

    def __init__(self) -> None:
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.store[(service, username)] = password


@pytest.fixture()
def fake_keyring(monkeypatch: pytest.MonkeyPatch) -> _FakeKeyring:
    fake = _FakeKeyring()
    monkeypatch.setitem(sys.modules, "keyring", fake)
    return fake


def _store() -> StudyMeasurementData:
    return StudyMeasurementData()


def _write_plaintext_records(root: Path, count: int) -> list[str]:
    """Seed the store through a plain repository; returns the record keys."""
    repo = MeasurementRepository(root)
    keys = []
    for index in range(count):
        uid = f"1.2.{index}"
        repo.save(uid, _store(), SOURCES, 0)
        keys.append(study_key(uid))
    repo.close()  # release the single-writer lock before the code under test runs
    return keys


def test_write_plaintext_records_seeds_the_expected_keys(tmp_path: Path) -> None:
    keys = _write_plaintext_records(tmp_path, 2)
    assert keys == [study_key(f"1.2.{index}") for index in range(2)]
    assert not any(is_encrypted_envelope(path.read_bytes()) for path in tmp_path.glob("*.json"))


# ── envelope cipher ──────────────────────────────────────────────────────────


def test_cipher_round_trips_payload() -> None:
    cipher = MeasurementsCipher(b"\x11" * 32)
    payload = b'{"study_uid": "1.2.3"}'
    envelope = cipher.encrypt(payload, aad=study_key(UID))
    assert isinstance(envelope, bytes)
    assert cipher.decrypt(envelope, aad=study_key(UID)) == payload


def test_envelope_is_self_describing_json() -> None:
    cipher = MeasurementsCipher(b"\x11" * 32)
    envelope = json.loads(cipher.encrypt(b"payload", aad=study_key(UID)))
    assert envelope["format"] == ENVELOPE_FORMAT
    assert envelope["version"] == 1
    assert envelope["key_id"] == cipher.key_id
    assert is_encrypted_envelope(cipher.encrypt(b"payload", aad=study_key(UID)))
    assert not is_encrypted_envelope(b'{"format": "other", "study_uid": "x"}')
    assert not is_encrypted_envelope(b"not json at all")


def test_aad_binds_the_envelope_to_its_record() -> None:
    cipher = MeasurementsCipher(b"\x11" * 32)
    envelope = cipher.encrypt(b"payload", aad=study_key(UID))
    with pytest.raises(MeasurementStorageError) as excinfo:
        cipher.decrypt(envelope, aad="different-record-key")
    assert excinfo.value.code == "decryption_failed"


def test_tampered_ciphertext_fails_closed() -> None:
    cipher = MeasurementsCipher(b"\x11" * 32)
    envelope = bytearray(cipher.encrypt(b"payload", aad=study_key(UID)))
    envelope[-3] ^= 0x01
    with pytest.raises(MeasurementStorageError) as excinfo:
        cipher.decrypt(bytes(envelope), aad=study_key(UID))
    assert excinfo.value.code == "decryption_failed"


def test_wrong_key_reports_key_mismatch() -> None:
    first = MeasurementsCipher(b"\x11" * 32)
    second = MeasurementsCipher(b"\x22" * 32)
    envelope = first.encrypt(b"payload", aad=study_key(UID))
    assert first.key_id != second.key_id
    with pytest.raises(MeasurementStorageError) as excinfo:
        second.decrypt(envelope, aad=study_key(UID))
    assert excinfo.value.code == "key_mismatch"


def test_key_id_is_stable_and_domain_separated() -> None:
    assert key_id_for(b"\x11" * 32) == key_id_for(b"\x11" * 32)
    assert key_id_for(b"\x11" * 32) != key_id_for(b"\x12" * 32)


def test_cipher_rejects_wrong_key_size() -> None:
    with pytest.raises(MeasurementStorageError) as excinfo:
        MeasurementsCipher(b"short")
    assert excinfo.value.code == "key_unavailable"


# ── keyring source (non-portable) ────────────────────────────────────────────


def test_keyring_source_generates_and_persists_the_key(fake_keyring: _FakeKeyring, tmp_path: Path) -> None:
    first = load_or_create_cipher(tmp_path, portable=False)
    assert fake_keyring.store[(KEY_SERVICE, KEY_USERNAME)]
    second = load_or_create_cipher(tmp_path, portable=False)
    assert second.key_id == first.key_id


def test_keyring_source_reuses_a_persisted_key(fake_keyring: _FakeKeyring, tmp_path: Path) -> None:
    fake_keyring.store[(KEY_SERVICE, KEY_USERNAME)] = (b"\x33" * 32).hex()
    cipher = load_or_create_cipher(tmp_path, portable=False)
    assert cipher.key_id == key_id_for(b"\x33" * 32)


def test_malformed_keyring_entry_fails_closed(fake_keyring: _FakeKeyring, tmp_path: Path) -> None:
    fake_keyring.store[(KEY_SERVICE, KEY_USERNAME)] = "not-hex"
    with pytest.raises(MeasurementStorageError) as excinfo:
        load_or_create_cipher(tmp_path, portable=False)
    assert excinfo.value.code == "key_unavailable"


# ── portable source (device-secret-wrapped vault key) ────────────────────────


@pytest.fixture()
def device_secret(monkeypatch: pytest.MonkeyPatch) -> bytes:
    secret = b"\x77" * 32
    monkeypatch.setattr(
        "echo_personal_tool.infrastructure.server_settings.portable_device_secret_for_wrapping",
        lambda: secret,
    )
    return secret


def test_portable_source_creates_and_reuses_the_vault_key(device_secret: bytes, tmp_path: Path) -> None:
    first = load_or_create_cipher(tmp_path, portable=True)
    key_file = tmp_path / VAULT_KEY_NAME
    assert key_file.is_file()
    # The key file itself is an envelope, not a plaintext key.
    document = json.loads(key_file.read_bytes())
    assert document["format"].startswith("sonoforge-measurements-vault-key")
    second = load_or_create_cipher(tmp_path, portable=True)
    assert second.key_id == first.key_id


def test_portable_source_without_the_device_secret_stays_locked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "echo_personal_tool.infrastructure.server_settings.portable_device_secret_for_wrapping",
        lambda: None,
    )
    with pytest.raises(MeasurementStorageError) as excinfo:
        load_or_create_cipher(tmp_path, portable=True)
    assert excinfo.value.code == "vault_locked"


def test_portable_vault_key_fails_closed_under_a_swapped_device_secret(
    device_secret: bytes, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    load_or_create_cipher(tmp_path, portable=True)
    monkeypatch.setattr(
        "echo_personal_tool.infrastructure.server_settings.portable_device_secret_for_wrapping",
        lambda: b"\x88" * 32,
    )
    with pytest.raises(MeasurementStorageError) as excinfo:
        load_or_create_cipher(tmp_path, portable=True)
    assert excinfo.value.code == "key_unavailable"


def test_portable_wrapping_uses_the_documented_aad(device_secret: bytes, tmp_path: Path) -> None:
    load_or_create_cipher(tmp_path, portable=True)
    document = json.loads((tmp_path / VAULT_KEY_NAME).read_bytes())
    assert VAULT_KEY_AAD == "sonoforge-measurements-vault-wrap-v1"
    # The nonce and the wrapped key are both stored; the plaintext key is not.
    assert document["ciphertext"] and document["nonce"]
    assert b"\x77" * 32 not in (tmp_path / VAULT_KEY_NAME).read_bytes()


# ── repository integration ───────────────────────────────────────────────────


def test_repository_with_cipher_writes_envelopes_and_round_trips(tmp_path: Path) -> None:
    cipher = MeasurementsCipher(b"\x44" * 32)
    repo = MeasurementRepository(tmp_path, cipher=cipher)
    stored = repo.save(UID, _store(), SOURCES, 0)
    on_disk = (tmp_path / (study_key(UID) + ".json")).read_bytes()
    assert is_encrypted_envelope(on_disk)
    assert not is_encrypted_envelope(on_disk) or json.loads(on_disk)["format"] == ENVELOPE_FORMAT
    assert repo.load(UID)["revision"] == stored["revision"]


def test_repository_without_cipher_refuses_envelopes(tmp_path: Path) -> None:
    cipher = MeasurementsCipher(b"\x44" * 32)
    sealed = MeasurementRepository(tmp_path, cipher=cipher)
    sealed.save(UID, _store(), SOURCES, 0)
    plain = MeasurementRepository(tmp_path)
    with pytest.raises(MeasurementStorageError) as excinfo:
        plain.load(UID)
    assert excinfo.value.code == "encrypted_unavailable"


def test_repository_with_cipher_still_reads_a_plaintext_record(tmp_path: Path) -> None:
    plain_repo = MeasurementRepository(tmp_path)
    plain_repo.save(UID, _store(), SOURCES, 0)
    ciphered = MeasurementRepository(tmp_path, cipher=MeasurementsCipher(b"\x44" * 32))
    assert ciphered.load(UID)["study_uid"] == UID


# ── migration ────────────────────────────────────────────────────────────────


def test_migration_encrypts_in_place_and_preserves_revisions(tmp_path: Path) -> None:
    uids = [f"1.2.{index}" for index in range(3)]
    plain_repo = MeasurementRepository(tmp_path)
    revisions = {}
    for uid in uids:
        stored = plain_repo.save(uid, _store(), SOURCES, 0)
        revisions[uid] = stored["revision"]
    plain_repo.close()

    cipher = MeasurementsCipher(b"\x55" * 32)
    converted, already = MeasurementRepository(tmp_path, cipher=cipher).migrate_encryption(cipher)
    assert (converted, already) == (3, 0)
    for path in tmp_path.glob("*.json"):
        assert is_encrypted_envelope(path.read_bytes())
    for uid in uids:
        loaded = MeasurementRepository(tmp_path, cipher=cipher).load(uid)
        assert loaded["revision"] == revisions[uid]
    # A second run is a no-op: the store is already current.
    assert MeasurementRepository(tmp_path, cipher=cipher).migrate_encryption(cipher) == (0, 3)


def test_migration_decrypts_back_to_plaintext(tmp_path: Path) -> None:
    cipher = MeasurementsCipher(b"\x55" * 32)
    sealed = MeasurementRepository(tmp_path, cipher=cipher)
    sealed.save(UID, _store(), SOURCES, 0)
    sealed.close()
    plain_target = MeasurementRepository(tmp_path)
    converted, already = plain_target.migrate_encryption(None, read_cipher=cipher)
    assert (converted, already) == (1, 0)
    assert not is_encrypted_envelope((tmp_path / (study_key(UID) + ".json")).read_bytes())
    assert MeasurementRepository(tmp_path).load(UID)["study_uid"] == UID


def test_migration_is_all_or_nothing_on_a_corrupt_record(tmp_path: Path) -> None:
    keys = _write_plaintext_records(tmp_path, 2)
    good_key = keys[0]
    cipher = MeasurementsCipher(b"\x55" * 32)
    # Seed one record through the cipher, then corrupt it on disk.
    sealed = MeasurementRepository(tmp_path, cipher=cipher)
    sealed.save("9.9.9", _store(), SOURCES, 0)
    corrupt = tmp_path / (study_key("9.9.9") + ".json")
    payload = bytearray(corrupt.read_bytes())
    payload[-5] ^= 0xFF
    corrupt.write_bytes(bytes(payload))
    with pytest.raises(MeasurementStorageError):
        MeasurementRepository(tmp_path, cipher=cipher).migrate_encryption(cipher)
    # The untouched plaintext record was not rewritten by the failed run.
    assert not is_encrypted_envelope((tmp_path / (good_key + ".json")).read_bytes())


def test_migration_without_a_read_cipher_refuses_envelopes(tmp_path: Path) -> None:
    cipher = MeasurementsCipher(b"\x55" * 32)
    MeasurementRepository(tmp_path, cipher=cipher).save(UID, _store(), SOURCES, 0)
    with pytest.raises(MeasurementStorageError) as excinfo:
        MeasurementRepository(tmp_path).migrate_encryption(None)
    assert excinfo.value.code == "encrypted_unavailable"
