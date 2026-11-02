"""The embedded C-MOVE Storage SCP has no remote-peer admission policy.

Until one exists, the only safe rule is loopback-only: a non-loopback bind must
be rejected before any socket is opened, and the failure must reach the caller
as a stable code rather than a raw exception. AE titles are identifiers, not
authentication, and are never used here as an access control.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from echo_personal_tool.application.server_io import is_loopback_scp_bind
from echo_personal_tool.application.services.dicom_retrieve_service import CMoveRetrieveAdapter, RetrieveError
from echo_personal_tool.infrastructure import embedded_storage_scp as scp_mod
from echo_personal_tool.infrastructure.embedded_storage_scp import (
    EmbeddedStorageSCP,
    StorageSCPBindError,
    is_loopback_bind_host,
)
from echo_personal_tool.infrastructure.server_settings import ServerSettings

pytestmark = pytest.mark.security


@pytest.mark.parametrize(
    "host",
    ["127.0.0.1", "127.0.0.2", "::1", "[::1]", "localhost", "::ffff:127.0.0.1"],
)
def test_loopback_literals_are_allowed(host: str) -> None:
    assert is_loopback_bind_host(host)
    assert is_loopback_scp_bind(host)


@pytest.mark.parametrize(
    "host",
    [
        "",
        "0.0.0.0",
        "::",
        "192.168.1.10",
        "10.0.0.5",
        "pacs.example.org",
        "localhost.attacker.example",
        "127.0.0.1.nip.io",
        "127.1",
        "2130706433",
        "fe80::1%eth0",
    ],
)
def test_remote_or_ambiguous_hosts_are_rejected(host: str) -> None:
    assert not is_loopback_bind_host(host)
    assert not is_loopback_scp_bind(host)


def test_remote_bind_is_refused_before_socket(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    constructed: list[object] = []

    class SpyAE:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            constructed.append(self)

    monkeypatch.setattr(scp_mod, "AE", SpyAE)
    scp = EmbeddedStorageSCP(host="0.0.0.0", port=0, ae_title="TESTSCP")
    with caplog.at_level(logging.WARNING):
        with pytest.raises(StorageSCPBindError) as excinfo:
            scp.start()

    assert excinfo.value.code == "scp_bind_rejected"
    assert constructed == [], "no AE/socket may be created for a remote bind"
    assert scp._ae is None
    assert scp._server is None
    assert "0.0.0.0" not in caplog.text, "log messages carry no host details"


def test_loopback_cmove_scp_still_binds() -> None:
    scp = EmbeddedStorageSCP(host="127.0.0.1", port=0, ae_title="TESTSCP")
    scp.start()
    try:
        assert scp.bound_port > 0
    finally:
        scp.shutdown()
    assert scp._server is None


@pytest.mark.parametrize("method", ["retrieve_instance", "retrieve_series"])
def test_retrieve_maps_rejected_bind_to_a_stable_code(method: str) -> None:
    client = MagicMock()
    adapter = CMoveRetrieveAdapter(
        client=client,
        settings=ServerSettings(dimse_scp_host="192.168.10.5", dimse_scp_port=11112),
    )
    with pytest.raises(RetrieveError) as excinfo:
        if method == "retrieve_instance":
            adapter.retrieve_instance("study-uid", "series-uid", "instance-uid")
        else:
            adapter.retrieve_series("study-uid", "series-uid")

    assert excinfo.value.code == "scp_bind_rejected"
    client.c_move_instances.assert_not_called()
    client.c_move_series.assert_not_called()
    assert not adapter._series_cache
