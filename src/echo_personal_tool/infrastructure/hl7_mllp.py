"""MLLP / MLLP+TLS client for HL7 v2 ORU^R01 (#625).

Infrastructure adapter for :class:`~echo_personal_tool.domain.ports.Hl7MllpPort`.
One framed message per connection (the common MLLP practice), ACK read back
with a size cap and timeout.  The endpoint is judged by
:mod:`application.transport_policy` (DIMSE transport kind) before any socket
is opened; payloads (PHI) and credentials are never logged.
"""

from __future__ import annotations

import socket
import ssl
from collections.abc import Iterable

from echo_personal_tool.application.transport_policy import (
    InsecureException,
    TransportPolicyError,
    Verdict,
    evaluate_dimse,
)
from echo_personal_tool.domain.exceptions import InteropError
from echo_personal_tool.domain.services.interop_hl7 import (
    MLLP_CR,
    MLLP_END,
    MLLP_START,
    AckResult,
    Hl7BuildError,
    frame_mlp,
    parse_ack,
)

#: Hard cap on one ACK frame (ACKs are small; anything bigger is an attack or a bug).
MAX_ACK_BYTES = 64 * 1024


class Hl7MllpClient:
    """Send one ORU message over MLLP (optionally TLS) and parse the ACK."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        timeout_s: float = 30.0,
        use_tls: bool = False,
        tls_verify: bool = True,
        tls_ca_path: str = "",
        tls_cert_path: str = "",
        tls_key_path: str = "",
        exceptions: Iterable[InsecureException] = (),
    ) -> None:
        decision = evaluate_dimse(
            host,
            port,
            use_tls=use_tls,
            tls_verify=tls_verify,
            tls_ca_path=tls_ca_path,
            exceptions=exceptions,
        )
        if decision.verdict is not Verdict.ALLOW:
            raise TransportPolicyError(decision)
        self._host = host
        self._port = int(port)
        self._timeout_s = max(1.0, float(timeout_s))
        self._use_tls = use_tls
        self._tls_verify = tls_verify
        self._tls_ca_path = tls_ca_path
        self._tls_cert_path = tls_cert_path
        self._tls_key_path = tls_key_path
        self._insecure = decision.insecure

    @property
    def insecure(self) -> bool:
        return self._insecure

    def _tls_context(self) -> ssl.SSLContext:
        context = ssl.create_default_context()
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        if not self._tls_verify:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        elif self._tls_ca_path:
            context.load_verify_locations(cafile=self._tls_ca_path)
        if self._tls_cert_path:
            context.load_cert_chain(certfile=self._tls_cert_path, keyfile=self._tls_key_path or None)
        return context

    def send_oru(self, payload: bytes, *, encoding: str = "utf-8") -> AckResult:
        """Frame, send and read one ACK. Raises :class:`InteropError` on failure."""
        if not isinstance(payload, (bytes, bytearray)) or not payload:
            raise InteropError("invalid_payload")
        framed = frame_mlp(bytes(payload))
        try:
            with socket.create_connection((self._host, self._port), timeout=self._timeout_s) as raw:
                sock: socket.socket = raw
                if self._use_tls:
                    sock = self._tls_context().wrap_socket(raw, server_hostname=self._host)
                sock.settimeout(self._timeout_s)
                sock.sendall(framed)
                ack = self._read_frame(sock)
        except InteropError:
            raise
        except (OSError, ssl.SSLError, ValueError) as exc:
            raise InteropError("transport") from exc
        try:
            return parse_ack(ack, encoding=encoding)
        except Hl7BuildError as exc:  # a malformed ACK is a protocol failure
            raise InteropError("ack_malformed") from exc

    @staticmethod
    def _read_frame(sock: socket.socket) -> bytes:
        """Read one MLLP frame; enforce the size cap; strip SB/EB/CR."""
        chunks = bytearray()
        started = False
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            chunks.extend(chunk)
            if len(chunks) > MAX_ACK_BYTES:
                raise InteropError("ack_too_large")
            if not started and chunks[:1] == MLLP_START:
                started = True
                del chunks[:1]
            if started and chunks[-2:] == MLLP_END + MLLP_CR:
                del chunks[-2:]
                break
        if not started or not chunks:
            raise InteropError("ack_empty")
        return bytes(chunks)
