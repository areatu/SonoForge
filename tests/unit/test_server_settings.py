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
