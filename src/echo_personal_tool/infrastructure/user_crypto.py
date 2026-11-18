"""Cryptographic primitives for local user authentication and Ed25519 signing keys.

Uses Python's ``hashlib.scrypt`` (RFC 7914 memory-hard KDF) with independent
random salts for password/PIN verification and private-key wrapping, and
``cryptography`` for Ed25519 keypairs and AES-256-GCM authenticated encryption.

A user's private signing key is never persisted in plaintext: it is sealed with
a key derived from the user's own secret and bound to ``user_id`` + ``key_id``
via AES-GCM additional authenticated data (AAD).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
from dataclasses import dataclass
from typing import Any, cast

from echo_personal_tool.domain.exceptions import UserAuthError
from echo_personal_tool.domain.models.user import KEY_ID_RE, SigningKeyPublic, is_valid_user_id

KDF_ID = "scrypt-v1"
SIGNING_ALGORITHM = "ed25519"
WRAP_CIPHER = "aes-256-gcm"

#: Interactive workstation scrypt parameters (~40-60 ms on desktop CPUs, 16 MiB RAM).
DEFAULT_SCRYPT_N = 1 << 14
DEFAULT_SCRYPT_R = 8
DEFAULT_SCRYPT_P = 1
_ALLOWED_SCRYPT_N = frozenset({1 << 12, 1 << 13, 1 << 14, 1 << 15, 1 << 16})
_MAX_SCRYPT_R = 16
_MAX_SCRYPT_P = 4
_SCRYPT_MAXMEM = 128 * 1024 * 1024
_SALT_BYTES = 16
_DKLEN = 32
_GCM_NONCE_BYTES = 12
_ED25519_KEY_BYTES = 32

#: Fixed dummy salt used to equalize timing when a login names an unknown user.
_DUMMY_SALT = hashlib.sha256(b"sonoforge-local-auth-dummy-salt-v1").digest()[:_SALT_BYTES]


def _b64e(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _b64d(text: str, *, expected_len: int | None = None) -> bytes:
    if not isinstance(text, str) or not text:
        raise UserAuthError("corrupt_store")
    try:
        raw = base64.b64decode(text.encode("ascii"), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise UserAuthError("corrupt_store") from exc
    if expected_len is not None and len(raw) != expected_len:
        raise UserAuthError("corrupt_store")
    return raw


def _validate_scrypt_params(kdf: str, n: int, r: int, p: int) -> None:
    if kdf != KDF_ID:
        raise UserAuthError("corrupt_store")
    if type(n) is not int or n not in _ALLOWED_SCRYPT_N:
        raise UserAuthError("corrupt_store")
    if type(r) is not int or not (1 <= r <= _MAX_SCRYPT_R):
        raise UserAuthError("corrupt_store")
    if type(p) is not int or not (1 <= p <= _MAX_SCRYPT_P):
        raise UserAuthError("corrupt_store")


def _derive_scrypt(secret: str, salt: bytes, *, domain: bytes, n: int, r: int, p: int) -> bytes:
    """Domain-separated scrypt derivation so auth verifiers and wrap keys stay independent."""
    material = domain + b"\x00" + secret.encode("utf-8")
    return hashlib.scrypt(material, salt=salt, n=n, r=r, p=p, maxmem=_SCRYPT_MAXMEM, dklen=_DKLEN)


def _wrap_aad(user_id: str, key_id: str) -> bytes:
    return f"sonoforge-sign-v1:{user_id}:{key_id}".encode("ascii")


def _wipe(buf: bytearray) -> None:
    for idx in range(len(buf)):
        buf[idx] = 0


@dataclass(frozen=True)
class PasswordVerifier:
    """Stored scrypt verifier for a user's password or PIN."""

    kdf: str
    n: int
    r: int
    p: int
    salt_b64: str
    digest_b64: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "kdf": self.kdf,
            "n": self.n,
            "r": self.r,
            "p": self.p,
            "salt_b64": self.salt_b64,
            "digest_b64": self.digest_b64,
        }

    @classmethod
    def from_dict(cls, data: MappingLike) -> PasswordVerifier:
        kdf = str(data.get("kdf", ""))
        n = data.get("n")
        r = data.get("r")
        p = data.get("p")
        if type(n) is not int or type(r) is not int or type(p) is not int:
            raise UserAuthError("corrupt_store")
        _validate_scrypt_params(kdf, n, r, p)
        salt_b64 = str(data.get("salt_b64", ""))
        digest_b64 = str(data.get("digest_b64", ""))
        _b64d(salt_b64, expected_len=_SALT_BYTES)
        _b64d(digest_b64, expected_len=_DKLEN)
        return cls(kdf=kdf, n=n, r=r, p=p, salt_b64=salt_b64, digest_b64=digest_b64)


MappingLike = dict[str, Any]


@dataclass(frozen=True)
class EncryptedSigningKey:
    """Password-wrapped Ed25519 keypair stored in the local user repository."""

    key_id: str
    algorithm: str
    public_key_b64: str
    created_at: str
    cipher: str
    kdf: str
    n: int
    r: int
    p: int
    wrap_salt_b64: str
    nonce_b64: str
    ciphertext_b64: str

    def public_key(self) -> SigningKeyPublic:
        return SigningKeyPublic(
            key_id=self.key_id,
            algorithm=self.algorithm,
            public_key_b64=self.public_key_b64,
            created_at=self.created_at,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "key_id": self.key_id,
            "algorithm": self.algorithm,
            "public_key_b64": self.public_key_b64,
            "created_at": self.created_at,
            "cipher": self.cipher,
            "kdf": self.kdf,
            "n": self.n,
            "r": self.r,
            "p": self.p,
            "wrap_salt_b64": self.wrap_salt_b64,
            "nonce_b64": self.nonce_b64,
            "ciphertext_b64": self.ciphertext_b64,
        }

    @classmethod
    def from_dict(cls, data: MappingLike) -> EncryptedSigningKey:
        key_id = str(data.get("key_id", ""))
        algorithm = str(data.get("algorithm", ""))
        cipher = str(data.get("cipher", ""))
        kdf = str(data.get("kdf", ""))
        n = data.get("n")
        r = data.get("r")
        p = data.get("p")
        if not KEY_ID_RE.fullmatch(key_id) or algorithm != SIGNING_ALGORITHM or cipher != WRAP_CIPHER:
            raise UserAuthError("corrupt_store")
        if type(n) is not int or type(r) is not int or type(p) is not int:
            raise UserAuthError("corrupt_store")
        _validate_scrypt_params(kdf, n, r, p)
        pub_b64 = str(data.get("public_key_b64", ""))
        pub_raw = _b64d(pub_b64, expected_len=_ED25519_KEY_BYTES)
        if compute_key_id(pub_raw) != key_id:
            raise UserAuthError("corrupt_store")
        wrap_salt_b64 = str(data.get("wrap_salt_b64", ""))
        nonce_b64 = str(data.get("nonce_b64", ""))
        ciphertext_b64 = str(data.get("ciphertext_b64", ""))
        _b64d(wrap_salt_b64, expected_len=_SALT_BYTES)
        _b64d(nonce_b64, expected_len=_GCM_NONCE_BYTES)
        # 32-byte Ed25519 seed + 16-byte GCM tag = 48 bytes.
        _b64d(ciphertext_b64, expected_len=_ED25519_KEY_BYTES + 16)
        created_at = str(data.get("created_at", ""))
        return cls(
            key_id=key_id,
            algorithm=algorithm,
            public_key_b64=pub_b64,
            created_at=created_at,
            cipher=cipher,
            kdf=kdf,
            n=n,
            r=r,
            p=p,
            wrap_salt_b64=wrap_salt_b64,
            nonce_b64=nonce_b64,
            ciphertext_b64=ciphertext_b64,
        )


def compute_key_id(public_key_raw: bytes) -> str:
    """Return 16-hex short fingerprint of a 32-byte raw Ed25519 public key."""
    return hashlib.sha256(public_key_raw).hexdigest()[:16]


def hash_secret(
    secret: str,
    *,
    n: int = DEFAULT_SCRYPT_N,
    r: int = DEFAULT_SCRYPT_R,
    p: int = DEFAULT_SCRYPT_P,
) -> PasswordVerifier:
    """Hash a password or PIN with ``hashlib.scrypt`` and a fresh 128-bit salt."""
    _validate_scrypt_params(KDF_ID, n, r, p)
    salt = os.urandom(_SALT_BYTES)
    digest = _derive_scrypt(secret, salt, domain=b"auth-v1", n=n, r=r, p=p)
    return PasswordVerifier(
        kdf=KDF_ID,
        n=n,
        r=r,
        p=p,
        salt_b64=_b64e(salt),
        digest_b64=_b64e(digest),
    )


def verify_secret(secret: str, verifier: PasswordVerifier) -> bool:
    """Constant-time check of *secret* against *verifier*."""
    _validate_scrypt_params(verifier.kdf, verifier.n, verifier.r, verifier.p)
    salt = _b64d(verifier.salt_b64, expected_len=_SALT_BYTES)
    expected = _b64d(verifier.digest_b64, expected_len=_DKLEN)
    candidate = _derive_scrypt(secret, salt, domain=b"auth-v1", n=verifier.n, r=verifier.r, p=verifier.p)
    return hmac.compare_digest(candidate, expected)


def dummy_verify_secret(secret: str, *, n: int = DEFAULT_SCRYPT_N) -> None:
    """Spend one scrypt evaluation when a username does not exist."""
    digest = _derive_scrypt(secret, _DUMMY_SALT, domain=b"auth-v1", n=n, r=DEFAULT_SCRYPT_R, p=DEFAULT_SCRYPT_P)
    hmac.compare_digest(digest, _DUMMY_SALT + _DUMMY_SALT)


def _seal_seed(
    seed: bytes,
    *,
    user_id: str,
    key_id: str,
    public_key_b64: str,
    created_at: str,
    secret: str,
    n: int,
    r: int,
    p: int,
) -> EncryptedSigningKey:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    wrap_salt = os.urandom(_SALT_BYTES)
    nonce = os.urandom(_GCM_NONCE_BYTES)
    wrap_key = bytearray(_derive_scrypt(secret, wrap_salt, domain=b"sign-wrap-v1", n=n, r=r, p=p))
    try:
        aesgcm = AESGCM(bytes(wrap_key))
        ciphertext = cast(bytes, aesgcm.encrypt(nonce, seed, _wrap_aad(user_id, key_id)))
    finally:
        _wipe(wrap_key)
    return EncryptedSigningKey(
        key_id=key_id,
        algorithm=SIGNING_ALGORITHM,
        public_key_b64=public_key_b64,
        created_at=created_at,
        cipher=WRAP_CIPHER,
        kdf=KDF_ID,
        n=n,
        r=r,
        p=p,
        wrap_salt_b64=_b64e(wrap_salt),
        nonce_b64=_b64e(nonce),
        ciphertext_b64=_b64e(ciphertext),
    )


def _unseal_seed(envelope: EncryptedSigningKey, *, user_id: str, secret: str) -> bytearray:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if not is_valid_user_id(user_id):
        raise UserAuthError("invalid_credentials")
    _validate_scrypt_params(envelope.kdf, envelope.n, envelope.r, envelope.p)
    wrap_salt = _b64d(envelope.wrap_salt_b64, expected_len=_SALT_BYTES)
    nonce = _b64d(envelope.nonce_b64, expected_len=_GCM_NONCE_BYTES)
    ciphertext = _b64d(envelope.ciphertext_b64, expected_len=_ED25519_KEY_BYTES + 16)
    wrap_key = bytearray(
        _derive_scrypt(secret, wrap_salt, domain=b"sign-wrap-v1", n=envelope.n, r=envelope.r, p=envelope.p)
    )
    try:
        aesgcm = AESGCM(bytes(wrap_key))
        plaintext = cast(bytes, aesgcm.decrypt(nonce, ciphertext, _wrap_aad(user_id, envelope.key_id)))
    except InvalidTag as exc:
        raise UserAuthError("invalid_credentials") from exc
    finally:
        _wipe(wrap_key)
    return bytearray(plaintext)


def generate_user_signing_key(
    *,
    user_id: str,
    secret: str,
    created_at: str,
    n: int = DEFAULT_SCRYPT_N,
    r: int = DEFAULT_SCRYPT_R,
    p: int = DEFAULT_SCRYPT_P,
) -> tuple[SigningKeyPublic, EncryptedSigningKey]:
    """Generate a fresh Ed25519 keypair and seal its private seed with *secret*."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    if not is_valid_user_id(user_id):
        raise UserAuthError("corrupt_store")
    _validate_scrypt_params(KDF_ID, n, r, p)
    private_key = Ed25519PrivateKey.generate()
    seed = bytearray(
        cast(
            bytes,
            private_key.private_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PrivateFormat.Raw,
                encryption_algorithm=serialization.NoEncryption(),
            ),
        )
    )
    try:
        public_raw = cast(
            bytes,
            private_key.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            ),
        )
        key_id = compute_key_id(public_raw)
        public_b64 = _b64e(public_raw)
        envelope = _seal_seed(
            bytes(seed),
            user_id=user_id,
            key_id=key_id,
            public_key_b64=public_b64,
            created_at=created_at,
            secret=secret,
            n=n,
            r=r,
            p=p,
        )
    finally:
        _wipe(seed)
    return envelope.public_key(), envelope


def reencrypt_signing_key(
    envelope: EncryptedSigningKey,
    *,
    user_id: str,
    old_secret: str,
    new_secret: str,
    n: int = DEFAULT_SCRYPT_N,
    r: int = DEFAULT_SCRYPT_R,
    p: int = DEFAULT_SCRYPT_P,
) -> EncryptedSigningKey:
    """Re-wrap a user's existing Ed25519 private key when they change their own secret."""
    seed = _unseal_seed(envelope, user_id=user_id, secret=old_secret)
    try:
        return _seal_seed(
            bytes(seed),
            user_id=user_id,
            key_id=envelope.key_id,
            public_key_b64=envelope.public_key_b64,
            created_at=envelope.created_at,
            secret=new_secret,
            n=n,
            r=r,
            p=p,
        )
    finally:
        _wipe(seed)


def sign_with_user_key(
    envelope: EncryptedSigningKey,
    *,
    user_id: str,
    secret: str,
    payload: bytes,
) -> bytes:
    """Unlock the user's Ed25519 private key in memory, sign *payload*, and wipe the seed."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    seed = _unseal_seed(envelope, user_id=user_id, secret=secret)
    try:
        private_key = Ed25519PrivateKey.from_private_bytes(bytes(seed))
        return cast(bytes, private_key.sign(payload))
    finally:
        _wipe(seed)


def verify_ed25519_signature(public_key_b64: str, payload: bytes, signature: bytes) -> bool:
    """Verify an Ed25519 signature against an active or archived public key."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    if len(signature) != 64:
        return False
    try:
        public_raw = _b64d(public_key_b64, expected_len=_ED25519_KEY_BYTES)
    except UserAuthError:
        return False
    public_key = Ed25519PublicKey.from_public_bytes(public_raw)
    try:
        public_key.verify(signature, payload)
    except InvalidSignature:
        return False
    return True
