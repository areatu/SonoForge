"""Verify that remote server connections enforce HTTPS and TLS settings.

Tests that the shipped defaults are judged by the transport policy (QH-2b),
TLS defaults are secure, and certificate verification settings propagate
into every transport the clients build.
"""

from __future__ import annotations

import contextlib
import dataclasses
import ssl
from unittest.mock import MagicMock, patch

import httpx
import pytest

pytestmark = pytest.mark.security

from echo_personal_tool.application.transport_policy import (
    HostKind,
    InsecureException,
    evaluate_dicomweb_url,
    evaluate_dimse,
    evaluate_profile,
    parse_dicomweb_endpoint,
)
from echo_personal_tool.infrastructure.orthanc_client import OrthancDicomWebClient
from echo_personal_tool.infrastructure.server_settings import (
    _DEFAULT_URL,
    ServerSettings,
    grant_insecure_exception,
    split_orthanc_urls,
)


class TestDefaultUrlScheme:
    """The shipped default profile is a loopback DICOMweb root, judged as such by the policy."""

    def test_default_url_ends_with_dicom_web(self) -> None:
        assert _DEFAULT_URL.endswith("/dicom-web")

    def test_default_profile_is_a_parsed_loopback_local_profile(self) -> None:
        """Plaintext is tolerated for the default only because the parsed host is loopback."""
        settings = ServerSettings()
        endpoint = parse_dicomweb_endpoint(settings.url, tls_verify=settings.tls_verify)
        assert endpoint.scheme == "http"
        assert endpoint.host_kind is HostKind.LOOPBACK
        decision = evaluate_dicomweb_url(settings.url, tls_verify=settings.tls_verify)
        assert decision.allowed
        assert decision.code == "allow-loopback"
        profile = evaluate_profile(
            url=settings.url,
            tls_verify=settings.tls_verify,
            tls_ca_path=settings.tls_ca_path,
            stow_url=settings.stow_dicom_web_url,
            dimse_enabled=True,
            dimse_host=settings.dimse_host,
            dimse_port=settings.dimse_port,
            dimse_use_tls=settings.dimse_use_tls,
            dimse_tls_verify=settings.dimse_tls_verify,
        )
        assert profile.allowed
        assert profile.insecure is False


class TestTlsSettingsDefaults:
    """Verify secure TLS defaults on ServerSettings."""

    def test_tls_verify_defaults_true(self) -> None:
        settings = ServerSettings()
        assert settings.tls_verify is True

    def test_dimse_tls_verify_defaults_true(self) -> None:
        settings = ServerSettings()
        assert settings.dimse_tls_verify is True

    def test_dimse_use_tls_defaults_false(self) -> None:
        settings = ServerSettings()
        assert settings.dimse_use_tls is False

    def test_dimse_tls_paths_default_empty(self) -> None:
        settings = ServerSettings()
        assert settings.dimse_tls_ca_path == ""
        assert settings.dimse_tls_cert_path == ""
        assert settings.dimse_tls_key_path == ""


class TestHttpUrlPolicy:
    """Remote plaintext / unverified profiles are blocked by the policy, not merely warned about.

    The decision comes from the real evaluator (QH-2b slice 1); the production
    clients adopt it in slice 2 (0 network requests before the user decides).
    """

    def test_remote_http_profile_is_blocked_until_a_scoped_exception(self) -> None:
        settings = ServerSettings(url="http://insecure.example.com/dicom-web")
        decision = evaluate_dicomweb_url(settings.url, tls_verify=settings.tls_verify)
        assert decision.blocked
        assert decision.code == "block-plaintext-remote"
        assert decision.requires_exception is True
        assert "https://" in decision.findings[0].message

    def test_private_lan_http_profile_is_remote_too(self) -> None:
        """The settings-dialog placeholder address is RFC1918 — a LAN is not evidence of trust."""
        settings = ServerSettings(url="http://192.168.1.111:8042/dicom-web")
        decision = evaluate_dicomweb_url(settings.url, tls_verify=settings.tls_verify)
        assert decision.blocked and decision.code == "block-plaintext-remote"

    def test_https_profile_with_verification_is_allowed_without_findings(self) -> None:
        settings = ServerSettings(url="https://secure.example.com/dicom-web")
        decision = evaluate_dicomweb_url(settings.url, tls_verify=settings.tls_verify)
        assert decision.allowed and decision.code == "allow"
        assert decision.findings == ()

    def test_https_profile_with_verification_disabled_is_blocked(self) -> None:
        settings = ServerSettings(url="https://secure.example.com/dicom-web", tls_verify=False)
        decision = evaluate_dicomweb_url(settings.url, tls_verify=settings.tls_verify)
        assert decision.blocked and decision.code == "block-tls-unverified"

    def test_loopback_http_profile_stays_a_local_profile(self) -> None:
        settings = ServerSettings(url="http://127.0.0.1:8042/dicom-web")
        decision = evaluate_dicomweb_url(settings.url, tls_verify=settings.tls_verify)
        assert decision.allowed and decision.code == "allow-loopback"

    def test_loopback_look_alike_profile_is_not_a_local_profile(self) -> None:
        for url in ("http://localhost.attacker.example:8042/dicom-web", "http://127.0.0.1.nip.io:8042/dicom-web"):
            settings = ServerSettings(url=url)
            decision = evaluate_dicomweb_url(settings.url, tls_verify=settings.tls_verify)
            assert decision.blocked, url

    def test_exception_is_scoped_to_the_exact_endpoint(self) -> None:
        settings = ServerSettings(url="http://insecure.example.com:8042/dicom-web")
        exception = InsecureException.for_endpoint(parse_dicomweb_endpoint(settings.url))
        assert evaluate_dicomweb_url(settings.url, exceptions=[exception]).code == "allow-by-exception"
        moved = ServerSettings(url="http://insecure.example.com:8043/dicom-web")
        assert evaluate_dicomweb_url(moved.url, exceptions=[exception]).blocked

    def test_remote_clear_dimse_profile_is_blocked(self) -> None:
        settings = ServerSettings(dimse_enabled=True, dimse_host="192.168.1.20", dimse_port=104, dimse_use_tls=False)
        decision = evaluate_dimse(settings.dimse_host, settings.dimse_port, use_tls=settings.dimse_use_tls)
        assert decision.blocked and decision.code == "block-dimse-clear-remote"


class TestOrthancClientTlsPropagation:
    """Verify TLS settings propagate correctly to httpx.Client."""

    def test_tls_verify_true_passed_to_httpx(self) -> None:
        with patch("echo_personal_tool.infrastructure.orthanc_client.httpx.Client") as mock_cls:
            mock_cls.return_value = MagicMock()
            from echo_personal_tool.infrastructure.orthanc_client import OrthancDicomWebClient

            OrthancDicomWebClient(
                "https://example.com/dicom-web",
                tls_verify=True,
            )
            assert len(mock_cls.call_args_list) >= 2, "no httpx.Client was constructed"
            for call in mock_cls.call_args_list:
                assert call.kwargs.get("verify", None) is True

    def test_tls_verify_false_passed_to_httpx(self) -> None:
        with patch("echo_personal_tool.infrastructure.orthanc_client.httpx.Client") as mock_cls:
            mock_cls.return_value = MagicMock()
            from echo_personal_tool.infrastructure.orthanc_client import OrthancDicomWebClient

            OrthancDicomWebClient(
                "https://example.com/dicom-web",
                tls_verify=False,
            )
            assert len(mock_cls.call_args_list) >= 2, "no httpx.Client was constructed"
            for call in mock_cls.call_args_list:
                assert call.kwargs.get("verify", None) is False

    def test_timeout_propagated(self) -> None:
        with patch("echo_personal_tool.infrastructure.orthanc_client.httpx.Client") as mock_cls:
            mock_cls.return_value = MagicMock()
            from echo_personal_tool.infrastructure.orthanc_client import OrthancDicomWebClient

            client = OrthancDicomWebClient(
                "https://example.com/dicom-web",
                timeout=60.0,
            )
            assert client is not None
            assert len(mock_cls.call_args_list) >= 2, "no httpx.Client was constructed"
            for call in mock_cls.call_args_list:
                assert call.kwargs.get("timeout", None) == 60.0

    def test_from_settings_uses_tls_verify(self) -> None:
        with patch("echo_personal_tool.infrastructure.orthanc_client.httpx.Client") as mock_cls:
            mock_cls.return_value = MagicMock()
            from echo_personal_tool.infrastructure.orthanc_client import OrthancDicomWebClient

            settings = ServerSettings(
                url="https://example.com/dicom-web",
                tls_verify=False,
                network_timeout=45.0,
            )
            OrthancDicomWebClient.from_settings(settings)
            assert len(mock_cls.call_args_list) >= 2, "no httpx.Client was constructed"
            for call in mock_cls.call_args_list:
                assert call.kwargs.get("verify", None) is False


class TestDimseTlsContext:
    """Verify DIMSE TLS context construction."""

    def test_no_tls_returns_none(self) -> None:
        from echo_personal_tool.infrastructure.dimse_client import PynetdimseClient

        client = PynetdimseClient(host="127.0.0.1", port=4242, use_tls=False)
        result = client._build_tls_context(use_tls=False)
        assert result is None

    def test_tls_enabled_returns_tuple(self) -> None:
        from echo_personal_tool.infrastructure.dimse_client import PynetdimseClient

        client = PynetdimseClient(host="127.0.0.1", port=4242, use_tls=True)
        result = client._build_tls_context(use_tls=True, verify=True)
        assert result is not None
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_tls_verify_false_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        from echo_personal_tool.infrastructure.dimse_client import PynetdimseClient

        client = PynetdimseClient(
            host="127.0.0.1",
            port=4242,
            use_tls=True,
            tls_verify=False,
        )
        client._build_tls_context(use_tls=True, verify=False)
        assert any("MITM risk" in record.message for record in caplog.records)


class TestSplitOrthancUrls:
    """Verify URL splitting handles various schemes correctly."""

    def test_https_url_splits(self) -> None:
        root, web = split_orthanc_urls("https://pacs.example.com/dicom-web")
        assert root == "https://pacs.example.com"
        assert web == "https://pacs.example.com/dicom-web"

    def test_http_url_splits(self) -> None:
        root, web = split_orthanc_urls("http://127.0.0.1:8042/dicom-web")
        assert root == "http://127.0.0.1:8042"
        assert web == "http://127.0.0.1:8042/dicom-web"

    def test_bare_root_adds_dicom_web(self) -> None:
        root, web = split_orthanc_urls("https://pacs.example.com")
        assert root == "https://pacs.example.com"
        assert web == "https://pacs.example.com/dicom-web"


# ---------------------------------------------------------------------------
# QH-2b.2 — Production client enforcement, redirects, TLS, DIMSE, migration, UI
# ---------------------------------------------------------------------------


def _make_spy_client(
    client: OrthancDicomWebClient,
    handler,
) -> list[httpx.Request]:
    """Attach a recording MockTransport to all internal httpx clients."""
    recorded: list[httpx.Request] = []

    def _wrapped(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return handler(request)

    transport = httpx.MockTransport(_wrapped)
    client._client = httpx.Client(
        base_url=str(client._client.base_url),
        headers=dict(client._client.headers),
        auth=client._client.auth,
        transport=transport,
    )
    client._orthanc_client = httpx.Client(
        base_url=str(client._orthanc_client.base_url),
        headers=dict(client._orthanc_client.headers),
        auth=client._orthanc_client.auth,
        transport=transport,
    )
    if client._stow_client is not None:
        client._stow_client = httpx.Client(
            base_url=str(client._stow_client.base_url),
            headers=dict(client._stow_client.headers),
            auth=client._stow_client.auth,
            transport=transport,
        )
    return recorded


class TestOrthancClientPolicyEnforcement:
    """Verify OrthancDicomWebClient blocks insecure remote calls with 0 network requests."""

    def test_remote_http_blocks_ping_query_preview_stats_download_stow_with_zero_requests(
        self,
    ) -> None:
        from echo_personal_tool.application.transport_policy import TransportPolicyError, Verdict

        client = OrthancDicomWebClient("http://pacs.hospital.example:8042/dicom-web")
        recorded = _make_spy_client(client, lambda req: httpx.Response(200, json=[]))
        try:
            for call in (
                lambda: client.ping(),
                lambda: client.query_studies(),
                lambda: client.query_series("1.2.3"),
                lambda: client.query_instances("1.2.3", "1.2.3.4"),
                lambda: client.fetch_preview("1.2.3", "1.2.3.4", "1.2.3.4.5"),
                lambda: client.study_statistics("1.2.3"),
                lambda: client.download_instance("1.2.3", "1.2.3.4", "1.2.3.4.5"),
                lambda: client.stow_instances([b"DICM"]),
            ):
                with pytest.raises(TransportPolicyError) as exc_info:
                    call()
                assert exc_info.value.verdict is Verdict.BLOCK
                assert exc_info.value.code == "block-plaintext-remote"
            assert recorded == []
        finally:
            client.close()

    def test_tls_verify_false_blocks_remote_https_without_exception(self) -> None:
        from echo_personal_tool.application.transport_policy import TransportPolicyError

        client = OrthancDicomWebClient(
            "https://pacs.hospital.example:8443/dicom-web",
            tls_verify=False,
        )
        recorded = _make_spy_client(client, lambda req: httpx.Response(200, json=[]))
        try:
            with pytest.raises(TransportPolicyError) as exc_info:
                client.query_studies()
            assert exc_info.value.code == "block-tls-unverified"
            assert recorded == []
        finally:
            client.close()

    def test_stow_override_url_evaluated_independently(self) -> None:
        from echo_personal_tool.application.transport_policy import TransportPolicyError

        client = OrthancDicomWebClient(
            "https://pacs.hospital.example:8443/dicom-web",
            stow_dicom_web_url="http://stow.hospital.example:8042/dicom-web",
        )
        recorded = _make_spy_client(client, lambda req: httpx.Response(200, json=[]))
        try:
            assert client.query_studies() == []
            assert len(recorded) == 1
            with pytest.raises(TransportPolicyError) as exc_info:
                client.stow_instances([b"DICM"])
            assert exc_info.value.code == "block-plaintext-remote"
            assert len(recorded) == 1
        finally:
            client.close()

    def test_scoped_exception_allows_matching_endpoint_and_blocks_other_host(self) -> None:
        from echo_personal_tool.application.transport_policy import (
            InsecureException,
            Transport,
            TransportPolicyError,
        )

        exc = InsecureException(
            transport=Transport.DICOMWEB,
            host="10.20.30.40",
            port=8042,
            secure=False,
            verify=True,
        )
        allowed = OrthancDicomWebClient(
            "http://10.20.30.40:8042/dicom-web",
            exceptions=[exc],
        )
        blocked = OrthancDicomWebClient(
            "http://10.20.30.41:8042/dicom-web",
            exceptions=[exc],
        )
        allowed_reqs = _make_spy_client(allowed, lambda req: httpx.Response(200, json=[]))
        blocked_reqs = _make_spy_client(blocked, lambda req: httpx.Response(200, json=[]))
        try:
            assert allowed.query_studies() == []
            assert len(allowed_reqs) == 1
            with pytest.raises(TransportPolicyError):
                blocked.query_studies()
            assert blocked_reqs == []
        finally:
            allowed.close()
            blocked.close()

    def test_orthanc_download_worker_propagates_policy_enforcement(self, tmp_path) -> None:
        from echo_personal_tool.application.workers.orthanc_download_worker import (
            OrthancDownloadWorker,
        )

        client = OrthancDicomWebClient("http://pacs.hospital.example:8042/dicom-web")
        try:
            worker = OrthancDownloadWorker(
                client=client,
                cache=MagicMock(),
                session_id="sec-test",
                study_uid="1.2.3",
                series_uids=["1.2.3.4"],
            )
            errors: list[str] = []
            worker.signals.failed.connect(lambda _uid, msg: errors.append(msg))
            worker.run()
            from echo_personal_tool.infrastructure.i18n import tr

            assert errors == [tr("orthanc.transport_policy_blocked")]
        finally:
            client.close()


class TestOrthancRedirectAndHeaderSecurity:
    """Verify evaluate_redirect and header stripping on redirects in OrthancDicomWebClient."""

    def test_https_to_http_redirect_blocked_before_following(self) -> None:
        from echo_personal_tool.application.transport_policy import TransportPolicyError

        client = OrthancDicomWebClient("https://origin.example.com/dicom-web")

        def _handler(req: httpx.Request) -> httpx.Response:
            if str(req.url).startswith("https://"):
                return httpx.Response(
                    302,
                    headers={"Location": "http://origin.example.com/dicom-web/studies"},
                )
            return httpx.Response(200, json=[])

        recorded = _make_spy_client(client, _handler)
        try:
            with pytest.raises(TransportPolicyError) as exc_info:
                client.query_studies()
            assert exc_info.value.code == "block-redirect-downgrade"
            assert len(recorded) == 1
            assert recorded[0].url.scheme == "https"
        finally:
            client.close()

    def test_loopback_http_to_remote_http_redirect_blocked_before_following(self) -> None:
        from echo_personal_tool.application.transport_policy import TransportPolicyError

        client = OrthancDicomWebClient("http://127.0.0.1:8042/dicom-web")

        def _handler(req: httpx.Request) -> httpx.Response:
            if req.url.host == "127.0.0.1":
                return httpx.Response(
                    302,
                    headers={"Location": "http://10.0.0.99:8042/dicom-web/studies"},
                )
            return httpx.Response(200, json=[])

        recorded = _make_spy_client(client, _handler)
        try:
            with pytest.raises(TransportPolicyError) as exc_info:
                client.query_studies()
            assert exc_info.value.code == "block-plaintext-remote"
            assert len(recorded) == 1
        finally:
            client.close()

    def test_same_authority_https_redirect_preserves_credentials(self) -> None:
        client = OrthancDicomWebClient(
            "https://origin.example.com/dicom-web",
            username="alice",
            password="secret",
            http_headers={"X-Api-Key": "token-123"},
        )

        def _handler(req: httpx.Request) -> httpx.Response:
            if req.url.path.endswith("/dicom-web/studies"):
                return httpx.Response(
                    307,
                    headers={"Location": "https://origin.example.com/v2/studies"},
                )
            return httpx.Response(200, json=[])

        recorded = _make_spy_client(client, _handler)
        try:
            assert client.query_studies() == []
            assert len(recorded) == 2
            assert "authorization" in recorded[1].headers
            assert recorded[1].headers.get("x-api-key") == "token-123"
        finally:
            client.close()

    def test_cross_authority_https_redirect_strips_auth_and_secret_headers(self) -> None:
        client = OrthancDicomWebClient(
            "https://origin.example.com/dicom-web",
            username="alice",
            password="secret",
            http_headers={
                "X-Api-Key": "token-123",
                "Cookie": "sid=abc",
                "X-Custom-Secret": "custom-secret-val",
            },
        )

        def _handler(req: httpx.Request) -> httpx.Response:
            if req.url.host == "origin.example.com":
                return httpx.Response(
                    302,
                    headers={"Location": "https://cdn.other.example.com/dicom-web/studies"},
                )
            return httpx.Response(200, json=[])

        recorded = _make_spy_client(client, _handler)
        try:
            assert client.query_studies() == []
            assert len(recorded) == 2
            first, second = recorded
            assert "authorization" in first.headers
            assert first.headers.get("x-api-key") == "token-123"
            assert first.headers.get("x-custom-secret") == "custom-secret-val"
            assert "authorization" not in second.headers
            assert "x-api-key" not in second.headers
            assert "cookie" not in second.headers
            assert "x-custom-secret" not in second.headers
            assert second.headers.get("accept") == "application/dicom+json"
        finally:
            client.close()


class TestPynetdimseClientPolicyEnforcement:
    """Verify PynetdimseClient blocks insecure remote operations with 0 associations."""

    def test_remote_clear_dimse_blocks_all_operations_with_zero_associations(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import pynetdicom

        from echo_personal_tool.application.transport_policy import TransportPolicyError
        from echo_personal_tool.infrastructure.dimse_client import PynetdimseClient

        assoc_calls: list[tuple] = []
        monkeypatch.setattr(
            pynetdicom.AE,
            "associate",
            lambda self, *a, **kw: assoc_calls.append((a, kw)),
        )

        client = PynetdimseClient(
            host="pacs.hospital.example",
            port=4242,
            use_tls=False,
        )
        for op in (
            lambda: client.c_echo(),
            lambda: client.c_find_studies(),
            lambda: client.c_find_series("1.2.3"),
            lambda: client.c_find_instances("1.2.3", "1.2.3.4"),
            lambda: client.c_get_instance("1.2.3", "1.2.3.4", "1.2.3.4.5"),
            lambda: client.c_move_instances(
                "1.2.3",
                "1.2.3.4",
                ["1.2.3.4.5"],
                move_destination_ae="ECHOTOOL",
                scp_host="127.0.0.1",
                scp_port=0,
                received={},
            ),
            lambda: client.c_move_series(
                "1.2.3",
                "1.2.3.4",
                move_destination_ae="ECHOTOOL",
                scp_host="127.0.0.1",
                scp_port=0,
                received={},
            ),
        ):
            with pytest.raises(TransportPolicyError) as exc_info:
                op()
            assert exc_info.value.code == "block-dimse-clear-remote"
        assert assoc_calls == []

    def test_dimse_tls_verify_false_blocked_without_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import pynetdicom

        from echo_personal_tool.application.transport_policy import TransportPolicyError
        from echo_personal_tool.infrastructure.dimse_client import PynetdimseClient

        assoc_calls: list[tuple] = []
        monkeypatch.setattr(
            pynetdicom.AE,
            "associate",
            lambda self, *a, **kw: assoc_calls.append((a, kw)),
        )

        client = PynetdimseClient(
            host="pacs.hospital.example",
            port=2762,
            use_tls=True,
            tls_verify=False,
        )
        with pytest.raises(TransportPolicyError) as exc_info:
            client.c_echo()
        assert exc_info.value.code == "block-tls-unverified"
        assert assoc_calls == []


class TestQueryAndRetrieveNoInsecureFallback:
    """Verify DicomQueryService and DicomRetrieveService never fall back on TransportPolicyError."""

    def test_query_service_auto_mode_does_not_fallback_on_transport_policy_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import pynetdicom

        from echo_personal_tool.application.dicom_query_service import DicomQueryService
        from echo_personal_tool.application.transport_policy import TransportPolicyError
        from echo_personal_tool.domain.ports import QuerySource
        from echo_personal_tool.infrastructure.dimse_client import PynetdimseClient

        assoc_calls: list[tuple] = []
        monkeypatch.setattr(
            pynetdicom.AE,
            "associate",
            lambda self, *a, **kw: assoc_calls.append((a, kw)),
        )

        web = OrthancDicomWebClient("http://pacs.hospital.example:8042/dicom-web")
        dimse = PynetdimseClient(host="127.0.0.1", port=4242, use_tls=False)
        recorded = _make_spy_client(web, lambda req: httpx.Response(200, json=[]))
        try:
            svc = DicomQueryService(
                web=web,
                dimse=dimse,
                source=QuerySource.AUTO,
            )
            with pytest.raises(TransportPolicyError):
                svc.query_studies()
            assert recorded == []
            assert assoc_calls == []
        finally:
            web.close()

    def test_retrieve_service_auto_mode_does_not_fallback_on_transport_policy_error(self, tmp_path) -> None:
        from echo_personal_tool.application.services.dicom_retrieve_service import (
            DicomRetrieveService,
            WadoRetrieveAdapter,
        )
        from echo_personal_tool.application.transport_policy import TransportPolicyError

        web = OrthancDicomWebClient("http://pacs.hospital.example:8042/dicom-web")
        recorded = _make_spy_client(web, lambda req: httpx.Response(200, content=b"DICM"))
        fallback_adapter = MagicMock()
        try:
            svc = DicomRetrieveService(
                adapters={"wado": WadoRetrieveAdapter(web), "dimse": fallback_adapter},
                default_source="auto",
            )
            with pytest.raises(TransportPolicyError):
                svc.retrieve_instance("1.2.3", "1.2.3.4", "1.2.3.4.5")
            assert recorded == []
            fallback_adapter.retrieve_instance.assert_not_called()
        finally:
            web.close()


# ---------------------------------------------------------------------------
# Certificate generation helpers for real socket TLS / DIMSE tests
# ---------------------------------------------------------------------------


def _generate_pki(
    tmp_path,
    *,
    san_ip: str | None = "127.0.0.1",
    san_dns: str | None = "localhost",
    expired: bool = False,
) -> tuple[str, str, str]:
    """Generate a CA PEM, server cert PEM, and server key PEM in tmp_path."""
    import datetime
    import ipaddress

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    now = datetime.datetime.now(datetime.timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "SonoForge Test CA")])
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=10))
        .not_valid_after(now + datetime.timedelta(days=10))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )

    srv_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    srv_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, san_dns or "localhost")])
    if expired:
        not_before = now - datetime.timedelta(days=5)
        not_after = now - datetime.timedelta(days=1)
    else:
        not_before = now - datetime.timedelta(days=1)
        not_after = now + datetime.timedelta(days=5)

    san_entries: list[x509.GeneralName] = []
    if san_dns:
        san_entries.append(x509.DNSName(san_dns))
    if san_ip:
        san_entries.append(x509.IPAddress(ipaddress.ip_address(san_ip)))

    srv_cert = (
        x509.CertificateBuilder()
        .subject_name(srv_name)
        .issuer_name(ca_name)
        .public_key(srv_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
        .sign(ca_key, hashes.SHA256())
    )

    ca_pem = tmp_path / "ca.pem"
    srv_cert_pem = tmp_path / "server.pem"
    srv_key_pem = tmp_path / "server.key"
    ca_pem.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    srv_cert_pem.write_bytes(srv_cert.public_bytes(serialization.Encoding.PEM))
    srv_key_pem.write_bytes(
        srv_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    return str(ca_pem), str(srv_cert_pem), str(srv_key_pem)


@contextlib.contextmanager
def _run_tls_https_server(cert_pem: str, key_pem: str):
    """Run a local HTTPS server using the given certificate and yield (port, counters)."""
    import http.server
    import threading

    counters = {"tls_handshakes": 0, "requests": 0}

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            counters["requests"] += 1
            body = b"[]"
            self.send_response(200)
            self.send_header("Content-Type", "application/dicom+json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args) -> None:  # noqa: ANN002
            return

    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_port
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=cert_pem, keyfile=key_pem)

    orig_get_request = server.get_request

    def _tls_get_request():
        counters["tls_handshakes"] += 1
        newsock, addr = orig_get_request()
        return ctx.wrap_socket(newsock, server_side=True), addr

    server.get_request = _tls_get_request  # type: ignore[method-assign]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield port, counters
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class TestHttpsRealTlsSocketService:
    """Service-level HTTPS/TLS tests over real loopback TLS sockets."""

    def test_https_with_custom_ca_bundle_succeeds(self, tmp_path) -> None:
        ca_pem, cert_pem, key_pem = _generate_pki(tmp_path, san_ip="127.0.0.1", san_dns="localhost")
        with _run_tls_https_server(cert_pem, key_pem) as (port, counters):
            client = OrthancDicomWebClient(
                f"https://127.0.0.1:{port}/dicom-web",
                tls_verify=True,
                tls_ca_path=ca_pem,
            )
            try:
                assert client.ping() is True
                assert client.query_studies() == []
                assert counters["requests"] == 2
            finally:
                client.close()

    def test_https_with_untrusted_cert_fails_without_fallback(self, tmp_path) -> None:
        _, cert_pem, key_pem = _generate_pki(tmp_path, san_ip="127.0.0.1", san_dns="localhost")
        other_dir = tmp_path / "other_ca"
        other_dir.mkdir()
        other_ca_pem, _, _ = _generate_pki(other_dir)
        with _run_tls_https_server(cert_pem, key_pem) as (port, counters):
            client = OrthancDicomWebClient(
                f"https://127.0.0.1:{port}/dicom-web",
                tls_verify=True,
                tls_ca_path=other_ca_pem,
            )
            try:
                assert client.ping() is False
                with pytest.raises(httpx.ConnectError):
                    client.query_studies()
                assert counters["requests"] == 0
            finally:
                client.close()

    def test_https_with_expired_cert_fails_without_fallback(self, tmp_path) -> None:
        ca_pem, cert_pem, key_pem = _generate_pki(tmp_path, san_ip="127.0.0.1", san_dns="localhost", expired=True)
        with _run_tls_https_server(cert_pem, key_pem) as (port, counters):
            client = OrthancDicomWebClient(
                f"https://127.0.0.1:{port}/dicom-web",
                tls_verify=True,
                tls_ca_path=ca_pem,
            )
            try:
                with pytest.raises(httpx.ConnectError):
                    client.query_studies()
                assert counters["requests"] == 0
            finally:
                client.close()

    def test_https_with_wrong_hostname_fails_without_fallback(self, tmp_path) -> None:
        ca_pem, cert_pem, key_pem = _generate_pki(tmp_path, san_ip=None, san_dns="wrong.hospital.internal")
        with _run_tls_https_server(cert_pem, key_pem) as (port, counters):
            client = OrthancDicomWebClient(
                f"https://127.0.0.1:{port}/dicom-web",
                tls_verify=True,
                tls_ca_path=ca_pem,
            )
            try:
                with pytest.raises(httpx.ConnectError):
                    client.query_studies()
                assert counters["requests"] == 0
            finally:
                client.close()


@contextlib.contextmanager
def _run_dimse_scp(*, ssl_context: ssl.SSLContext | None = None):
    """Start an in-process pynetdicom SCP supporting Verification and Study Root FIND."""
    from pynetdicom import AE, evt
    from pynetdicom.sop_class import StudyRootQueryRetrieveInformationModelFind, Verification

    events_seen: list[str] = []

    def _handle_echo(event) -> int:  # noqa: ANN001
        events_seen.append("echo")
        return 0x0000

    def _handle_find(event):  # noqa: ANN001
        events_seen.append("find")
        yield 0x0000, None

    ae = AE(ae_title="ORTHANC")
    ae.add_supported_context(Verification)
    ae.add_supported_context(StudyRootQueryRetrieveInformationModelFind)
    handlers = [
        (evt.EVT_C_ECHO, _handle_echo),
        (evt.EVT_C_FIND, _handle_find),
    ]
    server = ae.start_server(
        ("127.0.0.1", 0),
        block=False,
        ssl_context=ssl_context,
        evt_handlers=handlers,
    )
    try:
        port = server.server_address[1]
        yield port, events_seen
    finally:
        server.shutdown()


class TestDimseRealTlsAndLegacyScp:
    """Service-level DIMSE tests against TLS-enabled and legacy non-TLS pynetdicom SCPs."""

    def test_dimse_tls_scp_echo_and_find_succeed_with_custom_ca(self, tmp_path) -> None:
        from echo_personal_tool.infrastructure.dimse_client import PynetdimseClient

        ca_pem, cert_pem, key_pem = _generate_pki(tmp_path, san_ip="127.0.0.1", san_dns="localhost")
        srv_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        srv_ctx.load_cert_chain(certfile=cert_pem, keyfile=key_pem)

        with _run_dimse_scp(ssl_context=srv_ctx) as (port, events_seen):
            client = PynetdimseClient(
                host="127.0.0.1",
                port=port,
                ae_title="ECHOTOOL",
                called_ae="ORTHANC",
                use_tls=True,
                tls_verify=True,
                tls_ca_path=ca_pem,
            )
            assert client.c_echo() is True
            assert client.c_find_studies() == []
            assert events_seen == ["echo", "find"]

    def test_dimse_tls_incompatible_or_untrusted_raises_dimse_tls_error_without_downgrade(self, tmp_path) -> None:
        from echo_personal_tool.infrastructure.dimse_client import (
            DimseTlsError,
            PynetdimseClient,
        )

        # Plaintext SCP while client requires TLS -> TLS handshake fails, must raise DimseTlsError
        # and never downgrade to plaintext association.
        with _run_dimse_scp(ssl_context=None) as (port, events_seen):
            ca_pem, _, _ = _generate_pki(tmp_path)
            client = PynetdimseClient(
                host="127.0.0.1",
                port=port,
                ae_title="ECHOTOOL",
                called_ae="ORTHANC",
                use_tls=True,
                tls_verify=True,
                tls_ca_path=ca_pem,
            )
            assert client.c_echo() is False
            with pytest.raises(DimseTlsError, match="refusing plaintext fallback"):
                client.c_find_studies()
            assert events_seen == []

    def test_dimse_legacy_plaintext_scp_requires_explicit_opt_in_for_remote_endpoint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from echo_personal_tool.application.transport_policy import (
            InsecureException,
            Transport,
            TransportPolicyError,
            evaluate_dimse,
        )
        from echo_personal_tool.infrastructure import dimse_client as dimse_mod
        from echo_personal_tool.infrastructure.dimse_client import PynetdimseClient

        with _run_dimse_scp(ssl_context=None) as (port, events_seen):
            # Simulate policy evaluation treating this legacy SCP as a remote host
            # while connecting the socket to the local fixture port.
            def _remote_eval(host: str, p: int, **kwargs):
                return evaluate_dimse("10.50.0.10", p, **kwargs)

            monkeypatch.setattr(dimse_mod, "evaluate_dimse", _remote_eval)

            blocked_client = PynetdimseClient(
                host="127.0.0.1",
                port=port,
                use_tls=False,
            )
            with pytest.raises(TransportPolicyError) as exc_info:
                blocked_client.c_echo()
            assert exc_info.value.code == "block-dimse-clear-remote"
            assert events_seen == []

            opt_in_exc = InsecureException(
                transport=Transport.DIMSE,
                host="10.50.0.10",
                port=port,
                secure=False,
                verify=True,
            )
            allowed_client = PynetdimseClient(
                host="127.0.0.1",
                port=port,
                use_tls=False,
                exceptions=[opt_in_exc],
            )
            assert allowed_client.c_echo() is True
            assert allowed_client.c_find_studies() == []
            assert events_seen == ["echo", "find"]


class TestProfileMigrationAndScopeInvalidation:
    """Verify legacy profile migration, scope invalidation, and Presenter isolation."""

    def test_legacy_remote_http_profile_preserved_and_marked_needs_confirmation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from echo_personal_tool.application.transport_policy import TransportPolicyError
        from echo_personal_tool.infrastructure import profile as prof_mod
        from echo_personal_tool.infrastructure import server_settings as ss

        store: dict[str, object] = {
            "url": "http://192.168.10.25:8042/dicom-web",
            "username": "clinician",
            "use_mock": False,
            # Note: no transport_policy_version key -> legacy pre-QH-2b.2 settings
        }

        class _FakeQSettings:
            def contains(self, key: str) -> bool:
                return key in store

            def value(self, key: str, default: object = None, *args) -> object:  # noqa: ANN002
                return store.get(key, default)

            def setValue(self, key: str, value: object) -> None:
                store[key] = value

            def remove(self, key: str) -> None:
                store.pop(key, None)

            def sync(self) -> None:
                pass

        monkeypatch.setattr(prof_mod, "qsettings_for", lambda *a, **kw: _FakeQSettings())
        monkeypatch.setattr(ss, "_load_password_keyring", lambda key=None: "super-secret")
        monkeypatch.setattr(ss, "_save_password_keyring", lambda pw, key=None: None)

        loaded = ss.load_server_settings()
        assert loaded.url == "http://192.168.10.25:8042/dicom-web"
        assert loaded.username == "clinician"
        assert loaded.password == "super-secret"
        assert loaded.needs_confirmation is True
        assert loaded.allow_insecure_transport is False
        assert store.get("transport_policy_version") == ss.TRANSPORT_POLICY_MIGRATION_VERSION
        assert "password" not in store

        client = OrthancDicomWebClient.from_settings(loaded)
        recorded = _make_spy_client(client, lambda req: httpx.Response(200, json=[]))
        try:
            with pytest.raises(TransportPolicyError):
                client.query_studies()
            assert recorded == []
        finally:
            client.close()

    def test_legacy_loopback_profile_migrates_without_needing_confirmation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from echo_personal_tool.infrastructure import profile as prof_mod
        from echo_personal_tool.infrastructure import server_settings as ss

        store: dict[str, object] = {
            "url": "http://127.0.0.1:8042/dicom-web",
            "use_mock": False,
        }

        class _FakeQSettings:
            def contains(self, key: str) -> bool:
                return key in store

            def value(self, key: str, default: object = None, *args) -> object:  # noqa: ANN002
                return store.get(key, default)

            def setValue(self, key: str, value: object) -> None:
                store[key] = value

            def remove(self, key: str) -> None:
                store.pop(key, None)

            def sync(self) -> None:
                pass

        monkeypatch.setattr(prof_mod, "qsettings_for", lambda *a, **kw: _FakeQSettings())
        monkeypatch.setattr(ss, "_load_password_keyring", lambda key=None: "")

        loaded = ss.load_server_settings()
        assert loaded.needs_confirmation is False
        assert ss.settings_requires_confirmation(loaded) is False

    def test_scope_invalidation_on_host_port_protocol_or_tls_mode_change(self) -> None:
        from echo_personal_tool.infrastructure.server_settings import (
            grant_insecure_exception,
            settings_requires_confirmation,
        )

        initial = ServerSettings(
            url="http://10.1.2.3:8042/dicom-web",
            use_mock=False,
        )
        assert settings_requires_confirmation(initial) is True

        confirmed = grant_insecure_exception(initial)
        assert confirmed.allow_insecure_transport is True
        assert confirmed.needs_confirmation is False
        assert settings_requires_confirmation(confirmed) is False

        # Changing host invalidates the granted exception scope
        changed_host = dataclasses.replace(confirmed, url="http://10.1.2.4:8042/dicom-web")
        assert settings_requires_confirmation(changed_host) is True

        # Changing port invalidates the granted exception scope
        changed_port = dataclasses.replace(confirmed, url="http://10.1.2.3:8043/dicom-web")
        assert settings_requires_confirmation(changed_port) is True

        # Enabling remote clear DIMSE adds an unconfirmed endpoint
        added_dimse = dataclasses.replace(
            confirmed,
            dimse_enabled=True,
            dimse_host="10.1.2.3",
            dimse_port=4242,
            dimse_use_tls=False,
        )
        assert settings_requires_confirmation(added_dimse) is True

        # Switching from HTTPS with CA to HTTPS with tls_verify=False requires confirmation
        https_ca = ServerSettings(
            url="https://10.1.2.3:8443/dicom-web",
            tls_verify=True,
            tls_ca_path="/etc/ssl/pacs-ca.pem",
            use_mock=False,
        )
        assert settings_requires_confirmation(https_ca) is False
        https_unverified = dataclasses.replace(https_ca, tls_verify=False)
        assert settings_requires_confirmation(https_unverified) is True

    def test_presenter_profile_uses_portable_settings_without_host_fallback(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from echo_personal_tool.infrastructure import profile as prof_mod
        from echo_personal_tool.infrastructure import server_settings as ss

        monkeypatch.setenv(prof_mod.PROFILE_ENV, prof_mod.PROFILE_PRESENTER)
        monkeypatch.setenv(prof_mod.PORTABLE_DIR_ENV, str(tmp_path))

        saved = grant_insecure_exception(
            ServerSettings(
                url="http://10.9.8.7:8042/dicom-web",
                username="presenter_user",
                password="",
                use_mock=False,
            )
        )
        ss.save_server_settings(saved)
        loaded = ss.load_server_settings()
        assert loaded.url == "http://10.9.8.7:8042/dicom-web"
        assert loaded.allow_insecure_transport is True
        assert loaded.insecure_exception_scope == saved.insecure_exception_scope
        ini_files = list(tmp_path.rglob("*.ini"))
        assert len(ini_files) >= 1

    def test_legacy_named_profile_migrates_and_marks_needs_confirmation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import json

        from echo_personal_tool.infrastructure import profile as prof_mod
        from echo_personal_tool.infrastructure import server_settings as ss

        store: dict[str, object] = {
            "profiles": json.dumps(
                {
                    "LegacyLAN": {
                        "url": "http://192.168.1.50:8042/dicom-web",
                        "username": "doc",
                        "password": "legacy-inline-secret",
                        "use_mock": False,
                    },
                    "LocalOrthanc": {
                        "url": "http://127.0.0.1:8042/dicom-web",
                        "use_mock": False,
                    },
                }
            )
        }
        keyring_saved: dict[str, str] = {}

        class _FakeQSettings:
            def contains(self, key: str) -> bool:
                return key in store

            def value(self, key: str, default: object = None, *args) -> object:  # noqa: ANN002
                return store.get(key, default)

            def setValue(self, key: str, value: object) -> None:
                store[key] = value

            def remove(self, key: str) -> None:
                store.pop(key, None)

            def sync(self) -> None:
                pass

        monkeypatch.setattr(prof_mod, "qsettings_for", lambda *a, **kw: _FakeQSettings())
        monkeypatch.setattr(
            ss,
            "_save_password_keyring",
            lambda key, pw=None: keyring_saved.__setitem__(key, str(pw or "")),
        )
        monkeypatch.setattr(
            ss,
            "_load_password_keyring",
            lambda key=None: keyring_saved.get(str(key), ""),
        )

        profiles = ss.list_profiles()
        assert profiles["LegacyLAN"].needs_confirmation is True
        assert profiles["LegacyLAN"].allow_insecure_transport is False
        assert profiles["LegacyLAN"].password == "legacy-inline-secret"
        assert profiles["LocalOrthanc"].needs_confirmation is False

        persisted = json.loads(str(store["profiles"]))
        assert "password" not in persisted["LegacyLAN"]
        assert persisted["LegacyLAN"]["transport_policy_version"] == ss.TRANSPORT_POLICY_MIGRATION_VERSION


@pytest.mark.gui
class TestTransportUiConfirmationAndStatus:
    """Verify UI warning texts (RU/EN), visible status banners, and 0 network calls on cancel."""

    def test_status_banner_and_locales_cover_ru_and_en(self, qapp) -> None:
        from echo_personal_tool.infrastructure.i18n import get_language, set_language
        from echo_personal_tool.presentation.server_settings_dialog import (
            ServerSettingsForm,
            format_transport_status_text,
        )

        prev_lang = get_language()
        try:
            insecure = ServerSettings(
                url="http://10.10.10.10:8042/dicom-web",
                use_mock=False,
                needs_confirmation=True,
            )
            for lang, expected_sub in (
                ("ru", "HTTP без шифрования"),
                ("en", "HTTP without encryption"),
            ):
                set_language(lang)
                text, is_insecure = format_transport_status_text(insecure)
                assert is_insecure is True
                assert expected_sub in text

                form = ServerSettingsForm()
                form.set_settings(insecure)
                assert expected_sub in form._transport_status_label.text()
        finally:
            set_language(prev_lang)

    def test_orthanc_study_dialog_blocks_network_when_confirmation_cancelled(
        self, qapp, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from echo_personal_tool.presentation import orthanc_study_dialog as dlg_mod
        from echo_personal_tool.presentation import server_settings_dialog as ssd_mod

        insecure = ServerSettings(
            url="http://10.10.10.10:8042/dicom-web",
            use_mock=False,
            needs_confirmation=True,
        )
        client = OrthancDicomWebClient.from_settings(insecure)
        recorded = _make_spy_client(client, lambda req: httpx.Response(200, json=[]))

        monkeypatch.setattr(
            ssd_mod,
            "ensure_transport_confirmed_before_network",
            lambda parent, settings, **kw: None,
        )

        ping_called: list[bool] = []
        load_called: list[bool] = []
        dlg = dlg_mod.OrthancStudyDialog(client, MagicMock(), server_settings=insecure)
        try:
            monkeypatch.setattr(dlg, "_ping_async", lambda: ping_called.append(True))
            monkeypatch.setattr(dlg, "_load_studies_async", lambda: load_called.append(True))
            dlg._init_network()
            assert ping_called == []
            assert load_called == []
            assert recorded == []
        finally:
            dlg.close()
            client.close()

    def test_ensure_transport_confirmed_before_network_actions_and_profile_dialog_status(
        self, qapp, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from echo_personal_tool.presentation import server_profile_dialog as spd_mod
        from echo_personal_tool.presentation import server_settings_dialog as ssd_mod

        insecure = ServerSettings(
            url="http://10.10.10.10:8042/dicom-web",
            use_mock=False,
            needs_confirmation=True,
        )
        persisted: list[ServerSettings] = []
        monkeypatch.setattr(ssd_mod, "save_server_settings", persisted.append)

        monkeypatch.setattr(ssd_mod, "prompt_transport_policy_confirmation", lambda _p, _s, **_kw: "cancel")
        assert ssd_mod.ensure_transport_confirmed_before_network(None, insecure) is None
        assert persisted == []

        monkeypatch.setattr(
            ssd_mod,
            "prompt_transport_policy_confirmation",
            lambda _p, _s, **_kw: "allow_exception",
        )
        confirmed = ssd_mod.ensure_transport_confirmed_before_network(None, insecure)
        assert confirmed is not None
        assert confirmed.allow_insecure_transport is True
        assert confirmed.needs_confirmation is False
        assert len(persisted) == 1

        monkeypatch.setattr(
            spd_mod,
            "list_profiles",
            lambda: {"HospitalHTTP": insecure},
        )
        prof_dlg = spd_mod.ServerProfileDialog(insecure)
        try:
            assert prof_dlg._list.count() == 1
            item = prof_dlg._list.item(0)
            assert item.text() == "HospitalHTTP"
            assert item.toolTip() != ""
            prof_dlg._list.setCurrentRow(0)
            assert prof_dlg._transport_status_label.text() != ""
        finally:
            prof_dlg.close()
