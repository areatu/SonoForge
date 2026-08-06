"""Tests for Orthanc server settings persistence."""

from __future__ import annotations

import sys
import types
from collections.abc import Iterator

import pytest

pytestmark = pytest.mark.gui
from PySide6.QtCore import QSettings

from echo_personal_tool.infrastructure import server_settings as ss
from echo_personal_tool.infrastructure.server_settings import (
    ServerSettings,
    load_server_settings,
    parse_http_headers,
    save_server_settings,
    split_orthanc_urls,
)


@pytest.fixture
def isolated_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    org = "sonoforge-test"
    app = "server-test"
    monkeypatch.setattr(ss, "_SETTINGS_ORG", org)
    monkeypatch.setattr(ss, "_SETTINGS_APP", app)
    store = QSettings(org, app)
    store.clear()
    store.sync()
    # Mock keyring so _load_password_keyring doesn't hit the real OS keychain
    _patch_keyring(monkeypatch)
    yield
    store.clear()
    store.sync()


def _patch_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    kr = types.ModuleType("keyring")
    _stored: dict[str, str] = {}
    kr.set_password = staticmethod(
        lambda svc, user, pw: _stored.update({f"{svc}:{user}": pw}) if pw else _stored.pop(f"{svc}:{user}", None)
    )
    kr.get_password = staticmethod(lambda svc, user: _stored.get(f"{svc}:{user}"))
    kr.delete_password = staticmethod(lambda svc, user: _stored.pop(f"{svc}:{user}", None))
    kr_errors = types.ModuleType("keyring.errors")
    kr_errors.PasswordDeleteError = type("PasswordDeleteError", (Exception,), {})
    kr.errors = kr_errors  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "keyring", kr)
    monkeypatch.setitem(sys.modules, "keyring.errors", kr_errors)


def test_load_defaults(isolated_settings: None) -> None:
    settings = load_server_settings()
    assert settings.url == "http://127.0.0.1:8042/dicom-web"
    assert settings.username == ""
    assert settings.password == ""
    assert settings.auth_mode == "basic"
    assert settings.use_mock is False


def test_save_and_load_roundtrip(isolated_settings: None) -> None:
    original = ServerSettings(
        description="ORTHANC WEB",
        url="http://192.168.1.111:8042/dicom-web",
        username="user",
        password="secret",
        auth_mode="basic",
        http_headers="Authorization: Basic abc",
        use_mock=False,
        dimse_enabled=True,
        dimse_ae_title="ECHO2026",
        dimse_called_ae="ORTHANC",
        dimse_host="10.0.0.5",
        dimse_port=4242,
        stow_dicom_web_url="http://10.0.0.5:8042/dicom-web",
        query_source="auto",
    )
    save_server_settings(original)
    assert load_server_settings() == original


def test_split_orthanc_urls_accepts_dicom_web_suffix() -> None:
    orthanc, dicom = split_orthanc_urls("http://192.168.1.111:8042/dicom-web")
    assert orthanc == "http://192.168.1.111:8042"
    assert dicom == "http://192.168.1.111:8042/dicom-web"


def test_split_orthanc_urls_appends_dicom_web() -> None:
    orthanc, dicom = split_orthanc_urls("http://127.0.0.1:8042")
    assert orthanc == "http://127.0.0.1:8042"
    assert dicom == "http://127.0.0.1:8042/dicom-web"


def test_parse_http_headers() -> None:
    headers = parse_http_headers("Authorization: Basic abc\nX-Test: 1")
    assert headers == {"Authorization": "Basic abc", "X-Test": "1"}


# ── Profile tests ──────────────────────────────────────────────────


def test_list_profiles_empty(isolated_settings: None) -> None:
    from echo_personal_tool.infrastructure.server_settings import list_profiles

    assert list_profiles() == {}


def test_save_and_load_profile(isolated_settings: None) -> None:
    from echo_personal_tool.infrastructure.server_settings import (
        delete_profile,
        list_profiles,
        load_profile,
        save_profile,
    )

    settings = ServerSettings(
        description="Test Profile",
        url="http://10.0.0.1:8042/dicom-web",
        dimse_host="10.0.0.1",
        dimse_port=11112,
    )
    save_profile("test-prod", settings)
    profiles = list_profiles()
    assert "test-prod" in profiles
    loaded = load_profile("test-prod")
    assert loaded is not None
    assert loaded.url == "http://10.0.0.1:8042/dicom-web"
    assert loaded.dimse_host == "10.0.0.1"
    assert loaded.dimse_port == 11112
    assert delete_profile("test-prod") is True
    assert list_profiles() == {}


def test_profile_overwrite(isolated_settings: None) -> None:
    from echo_personal_tool.infrastructure.server_settings import (
        list_profiles,
        save_profile,
    )

    s1 = ServerSettings(description="v1", url="http://a:8042/dicom-web")
    s2 = ServerSettings(description="v2", url="http://b:8042/dicom-web")
    save_profile("p", s1)
    save_profile("p", s2)
    assert len(list_profiles()) == 1
    assert list_profiles()["p"].description == "v2"


def test_delete_nonexistent_profile(isolated_settings: None) -> None:
    from echo_personal_tool.infrastructure.server_settings import delete_profile

    assert delete_profile("nope") is False


# ── _read_bool tests ──────────────────────────────────────────────


def test_read_bool_none() -> None:
    assert ss._read_bool(None, True) is True
    assert ss._read_bool(None, False) is False


def test_read_bool_bool_passthrough() -> None:
    assert ss._read_bool(True, False) is True
    assert ss._read_bool(False, True) is False


def test_read_bool_string_true() -> None:
    assert ss._read_bool("true", False) is True
    assert ss._read_bool("True", False) is True
    assert ss._read_bool("1", False) is True
    assert ss._read_bool("yes", False) is True
    assert ss._read_bool("YES", False) is True


def test_read_bool_string_false() -> None:
    assert ss._read_bool("false", True) is False
    assert ss._read_bool("0", True) is False
    assert ss._read_bool("no", True) is False
    assert ss._read_bool("random", True) is False


def test_read_bool_other_type() -> None:
    assert ss._read_bool(42, False) is True
    assert ss._read_bool(0, True) is False


# ── split_orthanc_urls edge cases ────────────────────────────────


def test_split_orthanc_urls_empty_string() -> None:
    orthanc, dicom = ss.split_orthanc_urls("")
    assert orthanc == "http://127.0.0.1:8042"
    assert dicom == "http://127.0.0.1:8042/dicom-web"


def test_split_orthanc_urls_whitespace() -> None:
    orthanc, dicom = ss.split_orthanc_urls("  ")
    assert orthanc == "http://127.0.0.1:8042"
    assert dicom == "http://127.0.0.1:8042/dicom-web"


def test_split_orthanc_urls_only_dicom_web() -> None:
    """If URL is just '/dicom-web' after stripping, orthanc_root = raw."""
    orthanc, dicom = ss.split_orthanc_urls("http://x:8042/dicom-web")
    assert orthanc == "http://x:8042"
    assert dicom == "http://x:8042/dicom-web"


def test_split_orthanc_urls_trailing_slash() -> None:
    orthanc, dicom = ss.split_orthanc_urls("http://x:8042/")
    assert orthanc == "http://x:8042"
    assert dicom == "http://x:8042/dicom-web"


# ── parse_http_headers edge cases ────────────────────────────────


def test_parse_http_headers_empty() -> None:
    assert ss.parse_http_headers("") == {}


def test_parse_http_headers_no_colon() -> None:
    assert ss.parse_http_headers("invalid header") == {}


def test_parse_http_headers_blank_lines() -> None:
    result = ss.parse_http_headers("\n\n\n")
    assert result == {}


def test_parse_http_headers_value_with_colon() -> None:
    result = ss.parse_http_headers("Authorization: Bearer abc:def")
    assert result == {"Authorization": "Bearer abc:def"}


def test_parse_http_headers_strips_whitespace() -> None:
    result = ss.parse_http_headers("  Key  :  Value  ")
    assert result == {"Key": "Value"}


# ── _settings_to_dict / _dict_to_settings ────────────────────────


def test_settings_to_dict_roundtrip() -> None:
    s = ServerSettings(description="test", url="http://a:8042/dicom-web", dimse_port=11112)
    d = ss._settings_to_dict(s)
    assert d["description"] == "test"
    assert d["dimse_port"] == 11112
    s2 = ss._dict_to_settings(d)
    assert s2.description == "test"
    assert s2.dimse_port == 11112


def test_dict_to_settings_ignores_unknown_keys() -> None:
    d = {"description": "ok", "unknown_key": "skip", "dimse_port": 999}
    s = ss._dict_to_settings(d)
    assert s.description == "ok"
    assert s.dimse_port == 999


# ── Keyring error handling ──────────────────────────────────────


def test_save_password_keyring_no_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    """When keyring import fails, should log warning and not crash."""
    import builtins

    real_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "keyring":
            raise ImportError("No keyring")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)
    # Should not raise
    ss._save_password_keyring("user", "pass")
    monkeypatch.undo()


def test_load_password_keyring_no_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    """When keyring import fails, should return empty string."""
    import builtins

    real_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "keyring":
            raise ImportError("No keyring")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)
    result = ss._load_password_keyring("user")
    assert result == ""
    monkeypatch.undo()


def test_load_password_keyring_empty_password(monkeypatch: pytest.MonkeyPatch) -> None:
    """keyring returns None → empty string."""
    mock_kr = __import__("keyring")
    monkeypatch.setattr(mock_kr, "get_password", lambda svc, user: None)
    result = ss._load_password_keyring("user")
    assert result == ""


def test_load_password_keyring_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """keyring throws → returns empty string."""
    mock_kr = __import__("keyring")
    monkeypatch.setattr(mock_kr, "get_password", lambda svc, user: (_ for _ in ()).throw(RuntimeError("kr err")))
    result = ss._load_password_keyring("user")
    assert result == ""


# ── reset_server_settings ────────────────────────────────────────


def test_reset_server_settings(isolated_settings: None) -> None:
    original = ServerSettings(
        description="before reset",
        url="http://10.0.0.1:8042/dicom-web",
        username="testuser",
        password="testpass",
        dimse_port=12345,
    )
    save_server_settings(original)
    ss.reset_server_settings()
    settings = load_server_settings()
    # Should be back to defaults
    assert settings.url == "http://127.0.0.1:8042/dicom-web"
    assert settings.dimse_port == 4242
    assert settings.description == ""


# ── load_server_settings defaults ────────────────────────────────


def test_load_server_settings_legacy_url_migration(isolated_settings: None) -> None:
    """Legacy URL without /dicom-web should be migrated."""
    store = QSettings("sonoforge-test", "server-test")
    store.setValue("url", "http://127.0.0.1:8042")
    store.sync()
    settings = load_server_settings()
    assert settings.url == "http://127.0.0.1:8042/dicom-web"


def test_load_server_settings_invalid_auth_mode(isolated_settings: None) -> None:
    store = QSettings("sonoforge-test", "server-test")
    store.setValue("auth_mode", "invalid_mode")
    store.sync()
    settings = load_server_settings()
    assert settings.auth_mode == "basic"  # falls back to default


def test_load_server_settings_with_all_fields(isolated_settings: None) -> None:
    s = ServerSettings(
        description="Full",
        url="http://1.2.3.4:8042/dicom-web",
        username="admin",
        password="pw",
        auth_mode="basic",
        http_headers="X-Custom: val",
        use_mock=True,
        dimse_enabled=True,
        dimse_ae_title="MY_AE",
        dimse_called_ae="REMOTE",
        dimse_host="10.0.0.1",
        dimse_port=5555,
        stow_dicom_web_url="http://10.0.0.1:8042/dicom-web",
        query_source="auto",
        retrieval_source="dimse",
        dimse_retrieval_mode="cmove",
        dimse_use_tls=True,
        dimse_tls_verify=False,
        dimse_tls_ca_path="/ca.pem",
        dimse_tls_cert_path="/cert.pem",
        dimse_tls_key_path="/key.pem",
        dimse_scp_port=9999,
        dimse_scp_host="0.0.0.0",
        dimse_scp_ae_title="SCP_AE",
        network_timeout=60.0,
        tls_verify=False,
    )
    save_server_settings(s)
    loaded = load_server_settings()
    assert loaded == s


# ── Profile with password ───────────────────────────────────────


def test_profile_password_stored_in_keyring(isolated_settings: None) -> None:
    from echo_personal_tool.infrastructure.server_settings import (
        load_profile,
        save_profile,
    )

    s = ServerSettings(
        description="pw test",
        url="http://x:8042/dicom-web",
        password="secret123",
    )
    save_profile("pw-prod", s)
    loaded = load_profile("pw-prod")
    assert loaded is not None
    assert loaded.password == "secret123"


# ── ServerSettings defaults ──────────────────────────────────────


def test_server_settings_defaults() -> None:
    s = ServerSettings()
    assert s.url == "http://127.0.0.1:8042/dicom-web"
    assert s.auth_mode == "basic"
    assert s.use_mock is False
    assert s.dimse_enabled is False
    assert s.dimse_ae_title == "ECHO2026"
    assert s.dimse_port == 4242
    assert s.dimse_retrieval_mode == "cget"
    assert s.network_timeout == 30.0
    assert s.tls_verify is True
    assert s.query_source == "dicomweb"
    assert s.retrieval_source == "auto"


def test_purge_password_from_qsettings(isolated_settings: None) -> None:
    store = QSettings("sonoforge-test", "server-test")
    store.setValue("password", "stale")
    store.sync()
    ss._purge_password_from_qsettings()
    assert not store.contains("password")
