"""Extended unit tests for infrastructure/dimse_client.py — covers from_settings, error paths, TLS."""

from __future__ import annotations

from unittest.mock import patch

from echo_personal_tool.infrastructure.dimse_client import (
    DimseAssociationError,
    DimseMoveDestinationError,
    PynetdimseClient,
)
from echo_personal_tool.infrastructure.server_settings import ServerSettings


class TestFromSettings:
    def test_basic_settings(self):
        settings = ServerSettings(
            dimse_ae_title="MY_AE",
            dimse_called_ae="REMOTE",
            dimse_host="10.0.0.1",
            dimse_port=5555,
            network_timeout=20.0,
            dimse_use_tls=True,
            dimse_tls_verify=False,
            dimse_tls_ca_path="/ca.pem",
            dimse_tls_cert_path="/cert.pem",
            dimse_tls_key_path="/key.pem",
        )
        client = PynetdimseClient.from_settings(settings)
        assert client._ae_title == "MY_AE"
        assert client._called_ae == "REMOTE"
        assert client._host == "10.0.0.1"
        assert client._port == 5555
        assert client._timeout_s == 20.0
        assert client._use_tls is True
        assert client._tls_verify is False
        assert client._tls_ca_path == "/ca.pem"
        assert client._tls_cert_path == "/cert.pem"
        assert client._tls_key_path == "/key.pem"

    def test_default_settings(self):
        settings = ServerSettings()
        client = PynetdimseClient.from_settings(settings)
        assert client._ae_title == "ECHO2026"
        assert client._called_ae == "ORTHANC"
        assert client._host == "127.0.0.1"
        assert client._port == 4242
        assert client._use_tls is False


class TestDimseAssociationError:
    def test_message(self):
        exc = DimseAssociationError("cannot associate")
        assert str(exc) == "cannot associate"

    def test_inheritance(self):
        assert issubclass(DimseMoveDestinationError, DimseAssociationError)


class TestCEcho:
    def test_c_echo_returns_false_on_association_error(self):
        client = PynetdimseClient(host="127.0.0.1", port=1, timeout_s=0.5)
        assert client.c_echo() is False

    def test_c_echo_returns_false_on_general_exception(self):
        client = PynetdimseClient(host="127.0.0.1", port=4242)
        with patch.object(client, "_associate", side_effect=RuntimeError("unexpected")):
            assert client.c_echo() is False


class TestCFind:
    def test_c_find_studies_returns_empty_on_error(self):
        client = PynetdimseClient(host="127.0.0.1", port=1, timeout_s=0.5)
        result = client.c_find_studies(patient_name="test")
        assert result == []

    def test_c_find_series_returns_empty_on_error(self):
        client = PynetdimseClient(host="127.0.0.1", port=1, timeout_s=0.5)
        result = client.c_find_series("1.2.3")
        assert result == []

    def test_c_find_instances_returns_empty_on_error(self):
        client = PynetdimseClient(host="127.0.0.1", port=1, timeout_s=0.5)
        result = client.c_find_instances("1.2.3", "4.5.6")
        assert result == []


class TestCStore:
    def test_c_store_returns_false_on_association_error(self):
        client = PynetdimseClient(host="127.0.0.1", port=1, timeout_s=0.5)
        assert client.c_store(b"\x00\x01") is False

    def test_c_store_returns_false_on_general_error(self):
        client = PynetdimseClient(host="127.0.0.1", port=4242)
        with patch.object(client, "_associate", side_effect=RuntimeError("fail")):
            assert client.c_store(b"\x00") is False


class TestBuildTLSContext:
    def test_no_tls_returns_none(self):
        client = PynetdimseClient(host="127.0.0.1", port=4242)
        assert client._build_tls_context(use_tls=False) is None

    def test_tls_verify_true(self):
        client = PynetdimseClient(host="127.0.0.1", port=4242)
        result = client._build_tls_context(use_tls=True, verify=True)
        assert result is not None
        ssl_cx, host = result
        assert host == "127.0.0.1"
        import ssl
        assert ssl_cx.verify_mode == ssl.CERT_REQUIRED

    def test_tls_verify_false(self):
        client = PynetdimseClient(host="127.0.0.1", port=4242)
        result = client._build_tls_context(use_tls=True, verify=False)
        assert result is not None
        import ssl
        assert result[0].verify_mode == ssl.CERT_NONE


class TestBuildAE:
    def test_build_ae_has_contexts(self):
        client = PynetdimseClient(host="127.0.0.1", port=4242)
        ae = client._build_ae()
        assert ae.ae_title == "ECHO2026"
        assert ae.acse_timeout == 10.0


class TestCMoveDestinationError:
    def test_inherits_from_association_error(self):
        assert issubclass(DimseMoveDestinationError, DimseAssociationError)
        exc = DimseMoveDestinationError("unknown destination")
        assert "unknown destination" in str(exc)
