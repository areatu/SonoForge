"""Tests for Orthanc server settings persistence."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
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
    org = "echo-personal-tool-test"
    app = "server-test"
    monkeypatch.setattr(ss, "_SETTINGS_ORG", org)
    monkeypatch.setattr(ss, "_SETTINGS_APP", app)
    store = QSettings(org, app)
    store.clear()
    store.sync()
    yield
    store.clear()
    store.sync()


def test_load_defaults(isolated_settings: None) -> None:
    settings = load_server_settings()
    assert settings.url == "http://127.0.0.1:8042/dicom-web"
    assert settings.username == ""
    assert settings.password == ""
    assert settings.auth_mode == "none"
    assert settings.use_mock is True


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
