"""Persistent Orthanc / DICOMweb server connection settings."""

from __future__ import annotations

import json
from dataclasses import dataclass, fields
from typing import Any

from PySide6.QtCore import QSettings

_SETTINGS_ORG = "sonoforge"
_SETTINGS_APP = "server"

_DEFAULT_URL = "http://127.0.0.1:8042/dicom-web"
_DEFAULT_USE_MOCK = False
_DEFAULT_AUTH_MODE = "basic"
_AUTH_MODES = frozenset({"none", "basic"})
_SERVICE_NAME = "sonoforge"


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
    profiles = {}
    for name, d in data.items():
        settings = _dict_to_settings(d)
        # Load password from keyring
        settings.password = _load_password_keyring(f"profile:{name}")
        profiles[name] = settings
    return profiles


def save_profile(name: str, settings: ServerSettings) -> None:
    """Save a named profile."""
    store = _profile_store()
    raw = str(store.value("profiles", "{}"))
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        data = {}
    profile_data = _settings_to_dict(settings)
    # Store password in keyring, not in JSON
    if settings.password:
        _save_password_keyring(f"profile:{name}", settings.password)
    profile_data.pop("password", None)
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
    legacy_url = str(store.value("url", _DEFAULT_URL))
    if legacy_url == "http://127.0.0.1:8042":
        legacy_url = _DEFAULT_URL
    auth_mode = str(store.value("auth_mode", _DEFAULT_AUTH_MODE))
    if auth_mode not in _AUTH_MODES:
        auth_mode = _DEFAULT_AUTH_MODE
    return ServerSettings(
        description=str(store.value("description", "")),
        url=legacy_url,
        username=str(store.value("username", "")),
        password=_load_password_keyring(str(store.value("username", ""))),
        auth_mode=auth_mode,
        http_headers=str(store.value("http_headers", "")),
        use_mock=_read_bool(store.value("use_mock"), _DEFAULT_USE_MOCK),
        dimse_enabled=_read_bool(store.value("dimse_enabled"), False),
        dimse_ae_title=str(store.value("dimse_ae_title", "ECHO2026")),
        dimse_called_ae=str(store.value("dimse_called_ae", "ORTHANC")),
        dimse_host=str(store.value("dimse_host", "127.0.0.1")),
        dimse_port=int(store.value("dimse_port", 4242)),
        stow_dicom_web_url=str(store.value("stow_dicom_web_url", "")),
        query_source=str(store.value("query_source", "dicomweb")),
        retrieval_source=str(store.value("retrieval_source", "auto")),
        dimse_retrieval_mode=str(store.value("dimse_retrieval_mode", "cget")),
        dimse_use_tls=_read_bool(store.value("dimse_use_tls"), False),
        dimse_tls_verify=_read_bool(store.value("dimse_tls_verify"), True),
        dimse_tls_ca_path=str(store.value("dimse_tls_ca_path", "")),
        dimse_tls_cert_path=str(store.value("dimse_tls_cert_path", "")),
        dimse_tls_key_path=str(store.value("dimse_tls_key_path", "")),
        dimse_scp_port=int(store.value("dimse_scp_port", 11112)),
        dimse_scp_host=str(store.value("dimse_scp_host", "127.0.0.1")),
        dimse_scp_ae_title=str(store.value("dimse_scp_ae_title", "")),
        network_timeout=float(store.value("network_timeout", 30.0)),
        tls_verify=_read_bool(store.value("tls_verify"), True),
    )


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
    store.sync()


# ── Keyring helpers ────────────────────────────────────────────────

import base64 as _base64
import logging as _logging
import os as _os
from pathlib import Path as _Path

_keyring_logger = _logging.getLogger(__name__)

# Portable mode (SonoForge Presenter): PACS passwords live in secrets.json
# next to the executable (i.e. on the USB stick) instead of the host OS
# keychain, so the app never writes credentials to someone else's machine.
# Values are XOR-obfuscated + base64 — this is OBFUSCATION, not encryption:
# anyone with the stick can recover them. Documented in build/presenter/README.md.
_PORTABLE_OBFUSCATION_KEY = b"sonoforge-presenter-portable"


def _portable_secrets_file() -> _Path | None:
    from echo_personal_tool.infrastructure.profile import secrets_path

    return secrets_path()


def _obfuscate_secret(plain: str) -> str:
    data = plain.encode("utf-8")
    xored = bytes(b ^ _PORTABLE_OBFUSCATION_KEY[i % len(_PORTABLE_OBFUSCATION_KEY)] for i, b in enumerate(data))
    return _base64.b64encode(xored).decode("ascii")


def _deobfuscate_secret(token: str) -> str:
    try:
        xored = _base64.b64decode(token.encode("ascii"))
    except Exception:  # noqa: BLE001
        return ""
    return bytes(b ^ _PORTABLE_OBFUSCATION_KEY[i % len(_PORTABLE_OBFUSCATION_KEY)] for i, b in enumerate(xored)).decode(
        "utf-8",
        errors="replace",
    )


def _read_portable_secrets(path: _Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _write_portable_secrets(path: _Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        _os.chmod(path, 0o600)
    except OSError:
        pass


def _save_password_portable(username: str, password: str) -> None:
    path = _portable_secrets_file()
    if path is None:
        return
    data = _read_portable_secrets(path)
    if password:
        data[username] = _obfuscate_secret(password)
    else:
        data.pop(username, None)
    _write_portable_secrets(path, data)


def _load_password_portable(username: str) -> str:
    path = _portable_secrets_file()
    if path is None or not path.is_file():
        return ""
    token = _read_portable_secrets(path).get(username)
    if not token:
        return ""
    return _deobfuscate_secret(str(token))


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
            return pwd
    except Exception:
        pass
    return ""


def _purge_password_from_qsettings() -> None:
    """Remove stale password key from QSettings if present."""
    store = _settings_store()
    if store.contains("password"):
        store.remove("password")
        store.sync()
