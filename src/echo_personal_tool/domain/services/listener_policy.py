"""Listener bind policy — the pure evaluator for inbound HL7/MWL listeners (#626).

Lives in the domain layer so the infrastructure servers can enforce it
*before* a socket opens without importing the application layer.  Loopback is
the sanctioned default (local worklist feed); a non-loopback bind requires
verified TLS or an explicit operator allowlist entry.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from echo_personal_tool.domain.exceptions import TransportPolicyError

__all__ = [
    "Decision",
    "Finding",
    "HostKind",
    "TransportPolicyError",
    "Verdict",
    "classify_host",
    "evaluate_listener_bind",
]

# RFC 1123 labels, plus "_" which intranet names use in practice; nothing else.
_HOSTNAME_RE = re.compile(r"^[a-z0-9_]([a-z0-9_-]*[a-z0-9_])?(\.[a-z0-9_]([a-z0-9_-]*[a-z0-9_])?)*$")


class HostKind(Enum):
    """What the *parsed* host literal is — never what it might resolve to."""

    #: ``127.0.0.0/8``, ``::1``, IPv4-mapped loopback, or exactly ``localhost``.
    LOOPBACK = "loopback"
    #: RFC1918, CGNAT, link-local, ULA, documentation ranges … — still remote.
    PRIVATE = "private"
    #: Any other IP literal.
    PUBLIC = "public"
    #: A DNS name that is not ``localhost``; remote until TLS proves otherwise.
    NAME = "name"
    #: Empty, unspecified (``0.0.0.0``/``::``) or syntactically impossible.
    INVALID = "invalid"


class Verdict(Enum):
    ALLOW = "allow"
    BLOCK = "block"


@dataclass(frozen=True)
class Finding:
    """One reason behind a decision (stable ``code`` for logs/i18n, English ``message``)."""

    code: str
    message: str


@dataclass(frozen=True)
class Decision:
    """The verdict for one endpoint (or one redirect hop)."""

    verdict: Verdict
    #: Stable code, e.g. ``allow``, ``allow-loopback``, ``allow-by-exception``,
    #: ``block-plaintext-remote``, ``block-tls-unverified``, ``block-dimse-clear-remote``,
    #: ``block-invalid-endpoint``, ``block-redirect-downgrade``, ``allow-redirect``,
    #: ``allow-redirect-cross-authority``.
    code: str
    findings: tuple[Finding, ...] = ()
    endpoint: Any = None  # application Endpoint when judged there
    #: A scoped :class:`InsecureException` for ``endpoint`` would turn this BLOCK into ALLOW.
    requires_exception: bool = False
    #: Allowed only because of a scoped exception: keep a visible insecure label.
    insecure: bool = False
    #: Redirects only: credentials / custom secret headers may accompany the next request.
    forward_credentials: bool = False

    @property
    def allowed(self) -> bool:
        return self.verdict is Verdict.ALLOW

    @property
    def blocked(self) -> bool:
        return self.verdict is Verdict.BLOCK

    def summary(self) -> str:
        """Log-safe one-liner: code, transport and host kind — no host, URL or secret."""
        if self.endpoint is None:
            return f"transport-policy {self.code}"
        return (
            f"transport-policy {self.code} transport={self.endpoint.transport.value} "
            f"flavour={self.endpoint.flavour} host={self.endpoint.host_kind.value}"
        )


def classify_host(host: str) -> HostKind:
    """Classify a host literal by parsing it; substrings and suffixes prove nothing."""
    text = host.strip().lower()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    text = text.rstrip(".")
    if not text:
        return HostKind.INVALID
    literal = text.split("%", 1)[0]  # IPv6 zone id does not change the kind
    try:
        address = ipaddress.ip_address(literal)
    except ValueError:
        if text == "localhost":
            return HostKind.LOOPBACK
        return HostKind.NAME if _HOSTNAME_RE.match(text) else HostKind.INVALID
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        address = mapped
    if address.is_unspecified:
        return HostKind.INVALID
    if address.is_loopback:
        return HostKind.LOOPBACK
    if address.is_global:
        return HostKind.PUBLIC
    return HostKind.PRIVATE


def evaluate_listener_bind(
    host: str,
    port: int,
    *,
    use_tls: bool,
    tls_verify: bool = True,
    allowed_hosts: Iterable[str] = (),
) -> Decision:
    """Judge a *listener* bind address (#626).

    Loopback is the sanctioned default profile (local worklist feed), so it
    is allowed with or without TLS. Binding a non-loopback address exposes a
    listener to the network: it requires TLS with certificate verification,
    or an explicit operator allowlist entry for the exact host.
    """
    if not host or not (0 < int(port) < 65536):
        return Decision(
            Verdict.BLOCK,
            "block-invalid-endpoint",
            findings=(Finding("invalid-listener-endpoint", "listener host/port is empty or out of range"),),
        )
    kind = classify_host(host)
    if kind is HostKind.LOOPBACK:
        return Decision(Verdict.ALLOW, "allow-loopback-listener")
    if kind is HostKind.INVALID:
        return Decision(
            Verdict.BLOCK,
            "block-invalid-endpoint",
            findings=(Finding("invalid-host", "listener bind host is unspecified or invalid"),),
        )
    allowlisted = host in {h.strip() for h in allowed_hosts if h.strip()}
    if use_tls and tls_verify:
        code = "allow-listener-tls" if allowlisted else "allow-listener-tls-remote"
        return Decision(Verdict.ALLOW, code)
    if allowlisted:
        return Decision(
            Verdict.ALLOW,
            "allow-listener-allowlisted" if use_tls else "allow-listener-allowlisted-insecure",
            findings=(
                Finding(
                    "insecure-listener",
                    "Non-loopback listener covered only by an explicit allowlist entry; traffic is not protected by verified TLS"
                    if not (use_tls and tls_verify)
                    else "Non-loopback listener with verified TLS, additionally allowlisted",
                ),
            ),
            insecure=not (use_tls and tls_verify),
        )
    finding = Finding(
        "plaintext-remote-listener",
        f"Binding a listener on non-loopback {host}:{port} without verified TLS would expose the worklist feed; "
        "use loopback, enable TLS with verification, or add the host to the explicit allowlist",
    )
    return Decision(Verdict.BLOCK, "block-remote-listener", findings=(finding,))
