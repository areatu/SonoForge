"""MLLP / MLLP+TLS listener for inbound HL7 v2 (#626).

Opt-in, loopback by default; the bind address is judged by
:func:`listener_policy.evaluate_listener_bind` before the socket opens.
Each connection reads one MLLP frame, hands the decoded message to the
application handler (which returns the ACK text), and writes the framed ACK
back — a synchronous ACK per message. Message payloads are never logged.
"""

from __future__ import annotations

import logging
import socket
import socketserver
import ssl
import threading
from collections.abc import Callable

from echo_personal_tool.domain.services.interop_hl7 import frame_mlp
from echo_personal_tool.domain.services.listener_policy import TransportPolicyError, evaluate_listener_bind

logger = logging.getLogger(__name__)

SB = 0x0B  # start block
EB = 0x1C  # end block
CR = 0x0D


def _read_frame(sock: socket.socket, *, max_bytes: int = 1024 * 1024) -> bytes:
    """Read one MLLP frame; returns the payload without SB/EB/CR."""
    header = sock.recv(1)
    if not header:
        raise ConnectionError("peer closed before frame start")
    if header[0] != SB:
        raise ValueError("missing MLLP start block")
    chunks = bytearray()
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("peer closed mid-frame")
        chunks.extend(chunk)
        if len(chunks) > max_bytes:
            raise ValueError("frame too large")
        if chunks.endswith(bytes([EB, CR])):
            break
    payload = bytes(chunks[:-2])
    if not payload:
        raise ValueError("empty frame")
    return payload


class _MllpHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        handler: Callable[[str], str] = getattr(self.server, "handler")
        encoding: str = str(getattr(self.server, "encoding"))
        try:
            payload = _read_frame(self.request)
            message = payload.decode(encoding, errors="replace")
            ack_text = handler(message)
            self.request.sendall(frame_mlp(ack_text.encode(encoding, errors="replace")))
        except (ConnectionError, ValueError, OSError) as exc:
            logger.debug("mllp connection ended: %s", type(exc).__name__)


class _ThreadingTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class Hl7MllpServer:
    """A stoppable MLLP listener bound to a policy-judged address."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        handler: Callable[[str], str],
        use_tls: bool = False,
        tls_verify: bool = True,
        tls_cert_path: str = "",
        tls_key_path: str = "",
        allowed_hosts: tuple[str, ...] = (),
        encoding: str = "utf-8",
    ) -> None:
        decision = evaluate_listener_bind(
            host, port, use_tls=use_tls, tls_verify=tls_verify, allowed_hosts=allowed_hosts
        )
        if decision.verdict.name != "ALLOW":
            raise TransportPolicyError(decision)
        if decision.insecure:
            logger.warning("MLLP listener on %s:%s is insecure (allowlisted)", host, port)
        self._decision = decision
        self._host = host
        self._port = port
        self._use_tls = use_tls
        self._tls_cert_path = tls_cert_path
        self._tls_key_path = tls_key_path
        self._encoding = encoding
        self._server: _ThreadingTCPServer | None = None
        self._thread: threading.Thread | None = None
        self._handler = handler

    @property
    def insecure(self) -> bool:
        return self._decision.insecure

    def _tls_context(self) -> ssl.SSLContext | None:
        if not self._use_tls:
            return None
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(certfile=self._tls_cert_path, keyfile=self._tls_key_path or None)
        return context

    def start(self) -> None:
        if self._server is not None:
            return
        server = _ThreadingTCPServer((self._host, self._port), _MllpHandler)
        setattr(server, "handler", self._handler)
        setattr(server, "encoding", self._encoding)
        context = self._tls_context()
        if context is not None:
            server.socket = context.wrap_socket(server.socket, server_side=True)
        self._server = server
        self._thread = threading.Thread(target=server.serve_forever, name="hl7-mllp-listener", daemon=True)
        self._thread.start()
        logger.info("MLLP listener started on %s:%s (tls=%s)", self._host, self._port, self._use_tls)

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    @property
    def running(self) -> bool:
        return self._server is not None
