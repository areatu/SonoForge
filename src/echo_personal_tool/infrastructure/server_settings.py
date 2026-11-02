"""Persistent Orthanc / DICOMweb server connection settings."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, fields, replace
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from PySide6.QtCore import QSettings

from echo_personal_tool.application.transport_policy import (
    InsecureException,
    ProfileDecision,
    Transport,
    evaluate_profile,
)

logger = logging.getLogger(__name__)

_SETTINGS_ORG = "sonoforge"
_SETTINGS_APP = "server"

_DEFAULT_URL = "http://127.0.0.1:8042/dicom-web"
_DEFAULT_USE_MOCK = False
_DEFAULT_AUTH_MODE = "basic"
_AUTH_MODES = frozenset({"none", "basic"})
_SERVICE_NAME = "sonoforge"
TRANSPORT_POLICY_MIGRATION_VERSION = 1


@dataclass
class ServerSettings:
    description: str = ""
    url: str = _DEFAULT_URL
    username: str = ""
    password: str = ""
    auth_mode: str = _DEFAULT_AUTH_MODE
    http_headers: str = ""
    use_mock: bool = _DEFAULT_USE_MOCK
    # DIMSE
    dimse_enabled: bool = False
    dimse_ae_title: str = "ECHO2026"
    dimse_called_ae: str = "ORTHANC"
    dimse_host: str = "127.0.0.1"
    dimse_port: int = 4242
    # STOW-RS override
    stow_dicom_web_url: str = ""
    # Query source preference
    query_source: str = "dicomweb"
    # Retrieval source preference
    retrieval_source: str = "auto"  # wado | dimse | cmove | auto
    dimse_retrieval_mode: str = "cget"  # cget | cmove
    # TLS
    dimse_use_tls: bool = False
    dimse_tls_verify: bool = True
    dimse_tls_ca_path: str = ""
    dimse_tls_cert_path: str = ""  # optional client cert
    dimse_tls_key_path: str = ""
    # Embedded Storage SCP for C-MOVE
    dimse_scp_port: int = 11112
    dimse_scp_host: str = "127.0.0.1"  # bind address; PACS must reach this IP
    dimse_scp_ae_title: str = ""  # default: dimse_ae_title
    # Network
    network_timeout: float = 30.0
    tls_verify: bool = True
    #: PEM bundle used to verify the DICOMweb server certificate.  The right
    #: answer to a self-signed hospital PACS: keep verification on and trust
    #: exactly one certificate instead of disabling the check.
    tls_ca_path: str = ""
    #: Explicit user-granted transport exception for this profile's scope.
    allow_insecure_transport: bool = False
    #: Serialized endpoint scope bound to ``allow_insecure_transport``.
    insecure_exception_scope: str = ""
    #: True when a migrated legacy profile requires user confirmation before any network call.
    needs_confirmation: bool = False

    def __post_init__(self) -> None:
        if self.allow_insecure_transport and not self.insecure_exception_scope and not self.needs_confirmation:
            self.insecure_exception_scope = compute_insecure_exception_scope(self)


def required_insecure_exceptions_for_settings(settings: ServerSettings) -> tuple[InsecureException, ...]:
    """Return the scoped :class:`InsecureException` entries required by ``settings``."""
    raw = evaluate_profile(
        url=settings.url,
        tls_verify=settings.tls_verify,
        tls_ca_path=settings.tls_ca_path,
        stow_url=settings.stow_dicom_web_url,
        dimse_enabled=settings.dimse_enabled,
        dimse_host=settings.dimse_host,
        dimse_port=settings.dimse_port,
        dimse_use_tls=settings.dimse_use_tls,
        dimse_tls_verify=settings.dimse_tls_verify,
        dimse_tls_ca_path=settings.dimse_tls_ca_path,
        exceptions=(),
    )
    seen: list[InsecureException] = []
    for decision in raw.blocked:
        if decision.requires_exception and decision.endpoint is not None:
            exc = InsecureException.for_endpoint(decision.endpoint)
            if exc not in seen:
                seen.append(exc)
    return tuple(seen)


def compute_insecure_exception_scope(settings: ServerSettings) -> str:
    """Serialize the exact endpoint scope for ``settings`` into canonical JSON."""
    payload = {
        "v": TRANSPORT_POLICY_MIGRATION_VERSION,
        "exceptions": [
            {
                "transport": exc.transport.value,
                "host": exc.host,
                "port": exc.port,
                "secure": exc.secure,
                "verify": exc.verify,
            }
            for exc in required_insecure_exceptions_for_settings(settings)
        ],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def parse_insecure_exception_scope(scope: str) -> tuple[InsecureException, ...]:
    """Parse a serialized ``insecure_exception_scope`` back into :class:`InsecureException` items."""
    text = (scope or "").strip()
    if not text:
        return ()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return ()
    if not isinstance(data, dict):
        return ()
    raw_items = data.get("exceptions")
    if not isinstance(raw_items, list):
        return ()
    parsed: list[InsecureException] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        try:
            transport = Transport(str(item.get("transport", "")))
            host = str(item.get("host", "")).strip().lower()
            port = int(item.get("port", 0))
            secure = bool(item.get("secure", False))
            verify = bool(item.get("verify", True))
        except (TypeError, ValueError):
            continue
        if host and 1 <= port <= 65535:
            parsed.append(
                InsecureException(
                    transport=transport,
                    host=host,
                    port=port,
                    secure=secure,
                    verify=verify,
                )
            )
    return tuple(parsed)


def effective_exceptions_for_settings(settings: ServerSettings) -> tuple[InsecureException, ...]:
    """Return active :class:`InsecureException` items authorized by ``settings``."""
    if settings.needs_confirmation or not settings.allow_insecure_transport:
        return ()
    return parse_insecure_exception_scope(settings.insecure_exception_scope)


def evaluate_server_settings(settings: ServerSettings) -> ProfileDecision:
    """Evaluate ``settings`` against the transport policy using its scoped exceptions."""
    return evaluate_profile(
        url=settings.url,
        tls_verify=settings.tls_verify,
        tls_ca_path=settings.tls_ca_path,
        stow_url=settings.stow_dicom_web_url,
        dimse_enabled=settings.dimse_enabled,
        dimse_host=settings.dimse_host,
        dimse_port=settings.dimse_port,
        dimse_use_tls=settings.dimse_use_tls,
        dimse_tls_verify=settings.dimse_tls_verify,
        dimse_tls_ca_path=settings.dimse_tls_ca_path,
        exceptions=effective_exceptions_for_settings(settings),
    )


def settings_requires_confirmation(settings: ServerSettings) -> bool:
    """True when ``settings`` must not open a network connection without user confirmation."""
    if not isinstance(settings, ServerSettings) or settings.use_mock:
        return False
    return bool(settings.needs_confirmation or not evaluate_server_settings(settings).allowed)


def grant_insecure_exception(settings: ServerSettings) -> ServerSettings:
    """Return a copy of ``settings`` with a scoped exception granted for its current endpoints."""
    scope = compute_insecure_exception_scope(settings)
    return replace(
        settings,
        allow_insecure_transport=True,
        insecure_exception_scope=scope,
        needs_confirmation=False,
    )


def revoke_insecure_exception(settings: ServerSettings) -> ServerSettings:
    """Return a copy of ``settings`` with any insecure transport exception cleared."""
    return replace(
        settings,
        allow_insecure_transport=False,
        insecure_exception_scope="",
        needs_confirmation=False,
    )


def describe_insecure_transport_modes(settings: ServerSettings) -> list[str]:
    """Return localized labels for any insecure transport modes configured in ``settings``."""
    from echo_personal_tool.infrastructure.i18n import tr

    raw = evaluate_profile(
        url=settings.url,
        tls_verify=settings.tls_verify,
        tls_ca_path=settings.tls_ca_path,
        stow_url=settings.stow_dicom_web_url,
        dimse_enabled=settings.dimse_enabled,
        dimse_host=settings.dimse_host,
        dimse_port=settings.dimse_port,
        dimse_use_tls=settings.dimse_use_tls,
        dimse_tls_verify=settings.dimse_tls_verify,
        dimse_tls_ca_path=settings.dimse_tls_ca_path,
        exceptions=(),
    )
    modes: list[str] = []
    for decision in raw.decisions:
        label = ""
        if decision.code == "block-plaintext-remote":
            label = tr("server_settings.insecure_mode_http_plaintext")
        elif decision.code == "block-tls-unverified":
            label = tr("server_settings.insecure_mode_tls_unverified")
        elif decision.code == "block-dimse-clear-remote":
            label = tr("server_settings.insecure_mode_dimse_plaintext")
        if label and label not in modes:
            modes.append(label)
    return modes


# ── Profile management ──────────────────────────────────────────────


def _profile_store() -> QSettings:
    from echo_personal_tool.infrastructure.profile import qsettings_for

    return qsettings_for(_SETTINGS_ORG, _SETTINGS_APP)


def _settings_to_dict(s: ServerSettings) -> dict[str, Any]:
    return {f.name: getattr(s, f.name) for f in fields(s)}


def _dict_to_settings(d: dict[str, Any]) -> ServerSettings:
    valid = {f.name for f in fields(ServerSettings)}
    return ServerSettings(**{k: v for k, v in d.items() if k in valid})


def list_profiles() -> dict[str, ServerSettings]:
    """Return all saved profiles {name: ServerSettings}."""
    store = _profile_store()
    raw = str(store.value("profiles", "{}"))
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    profiles: dict[str, ServerSettings] = {}
    migrated = False
    for name, d in list(data.items()):
        if not isinstance(d, dict):
            continue
        legacy_pw = str(d.get("password") or "")
        if legacy_pw:
            _save_password_keyring(f"profile:{name}", legacy_pw)
            d.pop("password", None)
            migrated = True
        raw_version = d.get("transport_policy_version", 0)
        try:
            prof_version = int(raw_version) if raw_version is not None else 0
        except (TypeError, ValueError):
            prof_version = 0
        if prof_version < TRANSPORT_POLICY_MIGRATION_VERSION:
            candidate = _dict_to_settings(
                {
                    **d,
                    "allow_insecure_transport": False,
                    "insecure_exception_scope": "",
                    "needs_confirmation": False,
                }
            )
            needs_confirm = not evaluate_server_settings(candidate).allowed
            settings = replace(
                candidate,
                allow_insecure_transport=False,
                insecure_exception_scope="",
                needs_confirmation=needs_confirm,
            )
            d["allow_insecure_transport"] = False
            d["insecure_exception_scope"] = ""
            d["needs_confirmation"] = needs_confirm
            d["transport_policy_version"] = TRANSPORT_POLICY_MIGRATION_VERSION
            d.pop("password", None)
            migrated = True
        else:
            settings = _dict_to_settings(d)
        # Load password from keyring / portable secret store
        settings.password = _load_password_keyring(f"profile:{name}")
        profiles[name] = settings
    if migrated:
        store.setValue("profiles", json.dumps(data, ensure_ascii=False))
        store.sync()
    return profiles


def save_profile(name: str, settings: ServerSettings) -> None:
    """Save a named profile."""
    store = _profile_store()
    raw = str(store.value("profiles", "{}"))
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    profile_data = _settings_to_dict(settings)
    # Store password in keyring, not in JSON
    if settings.password:
        _save_password_keyring(f"profile:{name}", settings.password)
    profile_data.pop("password", None)
    profile_data["transport_policy_version"] = TRANSPORT_POLICY_MIGRATION_VERSION
    data[name] = profile_data
    store.setValue("profiles", json.dumps(data, ensure_ascii=False))
    store.sync()


def load_profile(name: str) -> ServerSettings | None:
    """Load a named profile. Returns None if not found."""
    profiles = list_profiles()
    return profiles.get(name)


def delete_profile(name: str) -> bool:
    """Delete a named profile. Returns True if deleted."""
    store = _profile_store()
    raw = str(store.value("profiles", "{}"))
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        data = {}
    if name not in data:
        return False
    del data[name]
    store.setValue("profiles", json.dumps(data, ensure_ascii=False))
    store.sync()
    # Clear keyring password for this profile
    _save_password_keyring(f"profile:{name}", "")
    return True


def _settings_store() -> QSettings:
    from echo_personal_tool.infrastructure.profile import qsettings_for

    return qsettings_for(_SETTINGS_ORG, _SETTINGS_APP)


def _read_int_value(raw: object, default: int) -> int:
    """QSettings hands numbers back as `object`; coerce without an ignore."""
    if not isinstance(raw, (int, float, str)):
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _read_float_value(raw: object, default: float) -> float:
    if not isinstance(raw, (int, float, str)):
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _read_bool(value: object, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    return bool(value)


def split_orthanc_urls(url: str) -> tuple[str, str]:
    """Return (orthanc_root, dicom_web_root) for ping vs QIDO/WADO."""
    raw = url.strip().rstrip("/")
    if not raw:
        raw = _DEFAULT_URL.rstrip("/")
    if raw.endswith("/dicom-web"):
        orthanc_root = raw[: -len("/dicom-web")].rstrip("/")
        if not orthanc_root:
            orthanc_root = raw
        return orthanc_root, raw
    return raw, f"{raw}/dicom-web"


def parse_http_headers(text: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()
        if key:
            headers[key] = value
    return headers


def load_server_settings() -> ServerSettings:
    store = _settings_store()
    has_stored_config = any(
        store.contains(key)
        for key in (
            "url",
            "dimse_enabled",
            "dimse_host",
            "tls_verify",
            "dimse_use_tls",
            "dimse_tls_verify",
            "stow_dicom_web_url",
        )
    )
    raw_version = store.value("transport_policy_version", 0)
    stored_version = _read_int_value(raw_version, 0)

    legacy_url = str(store.value("url", _DEFAULT_URL))
    if legacy_url == "http://127.0.0.1:8042":
        legacy_url = _DEFAULT_URL
    auth_mode = str(store.value("auth_mode", _DEFAULT_AUTH_MODE))
    if auth_mode not in _AUTH_MODES:
        auth_mode = _DEFAULT_AUTH_MODE
    username = str(store.value("username", ""))
    if store.contains("password"):
        stale_pw = str(store.value("password") or "")
        if stale_pw and not _load_password_keyring(username):
            _save_password_keyring(username, stale_pw)
        _purge_password_from_qsettings()

    allow_insecure = _read_bool(store.value("allow_insecure_transport"), False)
    exception_scope = str(store.value("insecure_exception_scope", ""))
    needs_confirmation = _read_bool(store.value("needs_confirmation"), False)

    settings = ServerSettings(
        description=str(store.value("description", "")),
        url=legacy_url,
        username=username,
        password=_load_password_keyring(username),
        auth_mode=auth_mode,
        http_headers=str(store.value("http_headers", "")),
        use_mock=_read_bool(store.value("use_mock"), _DEFAULT_USE_MOCK),
        dimse_enabled=_read_bool(store.value("dimse_enabled"), False),
        dimse_ae_title=str(store.value("dimse_ae_title", "ECHO2026")),
        dimse_called_ae=str(store.value("dimse_called_ae", "ORTHANC")),
        dimse_host=str(store.value("dimse_host", "127.0.0.1")),
        dimse_port=_read_int_value(store.value("dimse_port", 4242), 4242),
        stow_dicom_web_url=str(store.value("stow_dicom_web_url", "")),
        query_source=str(store.value("query_source", "dicomweb")),
        retrieval_source=str(store.value("retrieval_source", "auto")),
        dimse_retrieval_mode=str(store.value("dimse_retrieval_mode", "cget")),
        dimse_use_tls=_read_bool(store.value("dimse_use_tls"), False),
        dimse_tls_verify=_read_bool(store.value("dimse_tls_verify"), True),
        dimse_tls_ca_path=str(store.value("dimse_tls_ca_path", "")),
        dimse_tls_cert_path=str(store.value("dimse_tls_cert_path", "")),
        dimse_tls_key_path=str(store.value("dimse_tls_key_path", "")),
        dimse_scp_port=_read_int_value(store.value("dimse_scp_port", 11112), 11112),
        dimse_scp_host=str(store.value("dimse_scp_host", "127.0.0.1")),
        dimse_scp_ae_title=str(store.value("dimse_scp_ae_title", "")),
        network_timeout=_read_float_value(store.value("network_timeout", 30.0), 30.0),
        tls_verify=_read_bool(store.value("tls_verify"), True),
        tls_ca_path=str(store.value("tls_ca_path", "")),
        allow_insecure_transport=allow_insecure,
        insecure_exception_scope=exception_scope,
        needs_confirmation=needs_confirmation,
    )

    if has_stored_config and stored_version < TRANSPORT_POLICY_MIGRATION_VERSION:
        unconfirmed_candidate = replace(
            settings,
            allow_insecure_transport=False,
            insecure_exception_scope="",
            needs_confirmation=False,
        )
        needs_confirm = not evaluate_server_settings(unconfirmed_candidate).allowed
        settings = replace(
            unconfirmed_candidate,
            needs_confirmation=needs_confirm,
        )
        store.setValue("allow_insecure_transport", False)
        store.setValue("insecure_exception_scope", "")
        store.setValue("needs_confirmation", needs_confirm)
        store.setValue("transport_policy_version", TRANSPORT_POLICY_MIGRATION_VERSION)
        store.sync()

    return settings


def reset_server_settings() -> None:
    """Clear all server settings, restoring QSettings to factory defaults."""
    store = _settings_store()
    # Clear keyring password for current username
    username = str(store.value("username", ""))
    if username:
        _save_password_keyring(username, "")
    for key in (
        "description",
        "url",
        "username",
        "password",
        "auth_mode",
        "http_headers",
        "use_mock",
        "dimse_enabled",
        "dimse_ae_title",
        "dimse_called_ae",
        "dimse_host",
        "dimse_port",
        "stow_dicom_web_url",
        "query_source",
        "retrieval_source",
        "dimse_retrieval_mode",
        "dimse_use_tls",
        "dimse_tls_verify",
        "dimse_tls_ca_path",
        "dimse_tls_cert_path",
        "dimse_tls_key_path",
        "dimse_scp_port",
        "dimse_scp_host",
        "dimse_scp_ae_title",
        "network_timeout",
        "tls_verify",
        "tls_ca_path",
        "allow_insecure_transport",
        "insecure_exception_scope",
        "needs_confirmation",
        "transport_policy_version",
    ):
        store.remove(key)
    store.sync()


def save_server_settings(settings: ServerSettings) -> None:
    store = _settings_store()
    store.setValue("description", settings.description)
    store.setValue("url", settings.url.strip())
    store.setValue("username", settings.username)
    _save_password_keyring(settings.username, settings.password)
    # Ensure password never persists in QSettings
    _purge_password_from_qsettings()
    store.setValue("auth_mode", settings.auth_mode)
    store.setValue("http_headers", settings.http_headers)
    store.setValue("use_mock", settings.use_mock)
    store.setValue("dimse_enabled", settings.dimse_enabled)
    store.setValue("dimse_ae_title", settings.dimse_ae_title)
    store.setValue("dimse_called_ae", settings.dimse_called_ae)
    store.setValue("dimse_host", settings.dimse_host)
    store.setValue("dimse_port", settings.dimse_port)
    store.setValue("stow_dicom_web_url", settings.stow_dicom_web_url)
    store.setValue("query_source", settings.query_source)
    store.setValue("retrieval_source", settings.retrieval_source)
    store.setValue("dimse_retrieval_mode", settings.dimse_retrieval_mode)
    store.setValue("dimse_use_tls", settings.dimse_use_tls)
    store.setValue("dimse_tls_verify", settings.dimse_tls_verify)
    store.setValue("dimse_tls_ca_path", settings.dimse_tls_ca_path)
    store.setValue("dimse_tls_cert_path", settings.dimse_tls_cert_path)
    store.setValue("dimse_tls_key_path", settings.dimse_tls_key_path)
    store.setValue("dimse_scp_port", settings.dimse_scp_port)
    store.setValue("dimse_scp_host", settings.dimse_scp_host)
    store.setValue("dimse_scp_ae_title", settings.dimse_scp_ae_title)
    store.setValue("network_timeout", settings.network_timeout)
    store.setValue("tls_verify", settings.tls_verify)
    store.setValue("tls_ca_path", settings.tls_ca_path)
    store.setValue("allow_insecure_transport", settings.allow_insecure_transport)
    store.setValue("insecure_exception_scope", settings.insecure_exception_scope)
    store.setValue("needs_confirmation", settings.needs_confirmation)
    store.setValue("transport_policy_version", TRANSPORT_POLICY_MIGRATION_VERSION)
    store.sync()


# ── Keyring helpers ────────────────────────────────────────────────

import base64 as _base64
import logging as _logging
import os as _os
from pathlib import Path as _Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cryptography.fernet import Fernet as _Fernet

_keyring_logger = _logging.getLogger(__name__)

# Portable mode (default for Presenter, optional for Full): PACS passwords
# live in secrets.ini next to the executable instead of the host OS keychain,
# so the app never writes credentials to someone else's machine.
# The INI is managed through QSettings, exactly like preferences.ini and
# server.ini — the full profile's keyring path is likewise a native store.
#
# Values are Fernet-encrypted (AES-128-CBC + HMAC-SHA256).  The key is
# derived via PBKDF2-HMAC-SHA256 from a per-device random secret kept in
# ``device.key`` inside the same portable directory.  Trust model: whoever
# possesses the stick possesses the credentials — exactly like an OS
# keychain bound to one machine account — but the file is not readable by
# casual inspection and ciphertexts differ across devices.  When the
# optional ``cryptography`` package is missing (full-profile dev opt-in via
# SONOFORGE_PORTABLE=1), passwords are simply NOT persisted; there is no
# clear-text fallback.
_PORTABLE_KDF_SALT = b"sonoforge-presenter-portable-v1"
_PORTABLE_KDF_ITERATIONS = 120_000
_PORTABLE_DEVICE_SECRET_FALLBACK = b"sonoforge-presenter-default-device-secret"

# Cache keyed by portable root so tests (and stick swaps) get fresh keys.
_FERNET_CACHE: dict[str, _Fernet] = {}


def _portable_secrets_file() -> _Path | None:
    from echo_personal_tool.infrastructure.profile import secrets_path

    return secrets_path()


def _portable_device_secret() -> bytes:
    """Random per-device secret, generated once and kept in the portable dir.

    Falls back to a fixed application constant when ``device.key`` cannot be
    created or read (e.g. read-only media) so encryption still works.
    """
    from echo_personal_tool.infrastructure.profile import portable_path

    path = portable_path("device.key")
    if path is None:
        return _PORTABLE_DEVICE_SECRET_FALLBACK
    try:
        if path.is_file():
            raw = bytes.fromhex(path.read_text(encoding="ascii").strip())
            if len(raw) == 32:
                return raw
        raw = _os.urandom(32)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(raw.hex(), encoding="ascii")
        try:
            _os.chmod(path, 0o600)
        except OSError:
            pass
        return raw
    except Exception:  # noqa: BLE001
        return _PORTABLE_DEVICE_SECRET_FALLBACK


def _portable_fernet() -> _Fernet | None:
    """Fernet instance for the portable store, or None when unavailable."""
    from echo_personal_tool.infrastructure.profile import portable_root

    root = portable_root()
    cache_key = str(root)
    cached = _FERNET_CACHE.get(cache_key)
    if cached is not None:
        return cached
    try:
        from cryptography.fernet import Fernet
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    except Exception:  # noqa: BLE001
        return None
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_PORTABLE_KDF_SALT,
        iterations=_PORTABLE_KDF_ITERATIONS,
    )
    key = _base64.urlsafe_b64encode(kdf.derive(_portable_device_secret()))
    fernet = Fernet(key)
    _FERNET_CACHE[cache_key] = fernet
    return fernet


def _encrypt_secret(plain: str) -> str:
    fernet = _portable_fernet()
    if fernet is None:
        raise RuntimeError(
            "portable password storage requires the 'cryptography' package "
            "(install SonoForge with the 'presenter' extra)"
        )
    # `cryptography` is a `follow_imports = "skip"` dependency (#325), so its
    # return value reaches mypy as `Any`; the token is ASCII by contract.
    return cast(str, fernet.encrypt(plain.encode("utf-8")).decode("ascii"))


def _decrypt_secret(token: str) -> str:
    fernet = _portable_fernet()
    if fernet is None:
        return ""
    try:
        return cast(str, fernet.decrypt(token.encode("ascii")).decode("utf-8"))
    except Exception:  # noqa: BLE001
        return ""


def _secrets_store() -> QSettings:
    """Dedicated QSettings INI (``secrets.ini``) holding encrypted tokens."""
    from echo_personal_tool.infrastructure.profile import qsettings_for

    return qsettings_for(_SETTINGS_ORG, "secrets")


def _portable_secret_key(username: str) -> str:
    """QSettings needs a non-empty key; username-less profiles share one slot."""
    return username.strip() or "__anonymous__"


def _save_password_portable(username: str, password: str) -> None:
    store = _secrets_store()
    key = _portable_secret_key(username)
    if password:
        # Stored via Qt's native settings API as a Fernet ciphertext token —
        # the same category of store the full profile uses (OS keychain).
        store.setValue(key, _encrypt_secret(password))
    else:
        store.remove(key)
    store.sync()
    path = _portable_secrets_file()
    if path is not None:
        try:
            _os.chmod(path, 0o600)
        except OSError:
            pass


def _load_password_portable(username: str) -> str:
    token = _secrets_store().value(_portable_secret_key(username))
    if not token:
        return ""
    return _decrypt_secret(str(token))


def _save_password_keyring(username: str, password: str) -> None:
    """Store password in the portable secrets file or the OS keychain."""
    if _portable_secrets_file() is not None:
        try:
            _save_password_portable(username, password)
            _purge_password_from_qsettings()
            return
        except Exception:  # noqa: BLE001
            _keyring_logger.warning("portable secret store failed — password NOT saved")
            return
    try:
        import keyring

        if password:
            keyring.set_password(_SERVICE_NAME, username, password)
        else:
            try:
                keyring.delete_password(_SERVICE_NAME, username)
            except keyring.errors.PasswordDeleteError:
                pass
        # Clean up any stale password that may have leaked into QSettings
        _purge_password_from_qsettings()
        return
    except Exception:
        _keyring_logger.warning("keyring unavailable — password NOT saved (OS keychain required)")


def _load_password_keyring(username: str) -> str:
    """Load password from the portable secrets file or the OS keychain."""
    if _portable_secrets_file() is not None:
        return _load_password_portable(username)
    try:
        import keyring

        pwd = keyring.get_password(_SERVICE_NAME, username)
        if pwd:
            return cast(str, pwd)
    except Exception as exc:
        logger.debug("OS keyring password lookup failed (%s)", type(exc).__name__)
    return ""


def _purge_password_from_qsettings() -> None:
    """Remove stale password key from QSettings if present."""
    store = _settings_store()
    if store.contains("password"):
        store.remove("password")
        store.sync()
